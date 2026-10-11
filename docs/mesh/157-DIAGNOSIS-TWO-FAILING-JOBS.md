# NOTE ON THE NUMBER: this artifact was written as 155-DIAGNOSIS-TWO-FAILING-JOBS.md and has
# been renumbered to 157 because a sibling session had already taken 155 at 21:23Z
# (155-PRODUCTION-COMMS-FRESHNESS-DIAGNOSIS.md). Content is unchanged. Renumbered by the
# coordinator session 2026-10-11 21:33Z so the numbered series stays unambiguous.

# 155 — TWO FAILING JOBS: `guard-registry` (rc=2) and `ai-gateway-health` (rc=1)

Author: remote mesh child (thread `remote-6e0389f5`), running on **zabz-tech**, not on the authority.
Written 2026-10-11 21:2x–22:0xZ. Method: read-only. `runs.tsv`, the live crontab, the two job
scripts, migration docs `132`/`151`/`153`, read-only `sqlite3` on `/root/authority.db`
(`PRAGMA query_only=1`, `mode=ro`), one read-only `cat`/`sha256sum` of a 2.4 KB file on the frozen
office box, and hand-timed `curl`. Nothing on either box was started, stopped, enabled, disabled,
unmasked, restarted, or written. `/root/authority.db` was never opened read-write.

**Headline.** Both jobs are pointed at something that does not exist, and neither job is broken.
`guard-registry` is correctly refusing to run because a *config artifact* was dropped in the
cutover while its checker and its cron line were ported. `ai-gateway-health` is pointed at the
**correct, live, fast** endpoint — the "dead route" hypothesis is false — and its rc=1 has a
different, single cause: a bucket whose `model` column literally reads `unknown`.

---

## 1 — `guard-registry` — every 15 min, rc=2

### 1.1 What rc=2 is

```
2026-10-11T21:15:01Z	guard-registry	2	1	<no cause column>
```

Cron line (decoded from the base64 in root's crontab):

```
/usr/bin/python3 /usr/local/bin/guard-registry-check.py --write-status >> /root/.guard-registry/cron.log 2>&1
```

`main()` returns **2** before it judges anything:

```python
if not os.path.exists(args.registry):
    print("guard-registry-check: registry does not exist: %s" % args.registry, file=sys.stderr)
    return 2
```

`DEFAULT_REGISTRY = HOME / "bin" / "guards.yaml"` → `/root/bin/guards.yaml`. The file is absent
(verified: `ls` on `/root/bin/`, `/usr/local/bin/`, `/etc/` — all "No such file or directory"), and
`/root/.guard-registry/cron.log` holds **30 identical lines** of exactly that message.

So rc=2 is the checker's own documented code for *"could not read its own inputs"*. It is a correct
refusal, not a crash. The job is not broken; its input is missing.

### 1.2 What `guards.yaml` contained — established, not guessed

Read-only from the frozen office box (`cat` + `sha256sum`, 2.4 KB, one command):

| | |
|---|---|
| path | `secratary-ts:/home/zabz/bin/guards.yaml` |
| size / mode / mtime | 2463 bytes, `0644`, 2026-10-01 12:49 |
| **sha256** | **`91ea76998a893eb7d232307abdfb84597d3f7abc37b9da04feecc738f65d4483`** |

And in this box's checker, line ~100:

```python
BOOTSTRAP_REGISTRY_SHA256 = "91ea76998a893eb7d232307abdfb84597d3f7abc37b9da04feecc738f65d4483"
```

**The hashes are identical.** I decoded the office file independently and re-hashed the bytes to
confirm it (2463 bytes → same digest). This is a provenance *proof*, not an inference: the cloud
checker was installed expecting those exact bytes, and the file it names is not here. Its own
docstring says the constant is "Substituted at install time with the sha256 of the registry shipped
alongside this file" — so the registry was part of the unit of work, and it did not arrive.

Content: `version: 1` and three guards — `cron-targets`, `disk`, `db-integrity` — each with
`id`, `why`, `command`, `cron_match`, `cron_wrap_name`, `status_file`, `max_age_seconds`. Full text
in Appendix A.

### 1.3 Should it exist here? **Yes.** Three independent reasons

1. **The migration's own inventory says so.** `132-CRON-INVENTORY.md` L159 classifies
   `guard-registry` (L130) as **PORT-ADAPT**, and L537 reads
   *"**34. `guard-registry` (L130) — Machine: `secratary-cloud`.**"* It was assigned to this box,
   to be adapted. It was not left behind on purpose.
2. **Every guard it names is a live job on this box.** `/usr/local/bin/cron-target-guard.py`,
   `/usr/local/bin/disk-guard.py`, `/usr/local/bin/db-integrity-check.py` all exist and are `0755`,
   each has its own cloud cron line, and `/root/.cron-targets/status.json` +
   `/root/.disk-guard/status.json` are being written right now. The *concept* is already live here;
   only the register that checks it is missing.
3. **The owner already approved installing it.** `/root/authority.db` → `owner_decision_queue`
   row **227**, status `resolved`, resolved 2026-10-02T00:56:07Z, question:
   *"Should I install the guard-registry watchdog as a cron job? …"* — text that names the guard
   registry. (The checker's own `--selftest` fixture hardcodes row 227 as the legitimate approver.)

**Verdict: not a deliberately retired office concept. A config artifact lost in the cutover.**

### 1.4 Why a byte-identical copy would NOT work — the part that matters

The office registry hardcodes **office paths**, and they are wrong here:

| entry | office value | on `secratary-cloud` |
|---|---|---|
| `cron-targets.command` | `/home/zabz/bin/cron-target-guard.py` | → `/usr/local/bin/cron-target-guard.py` |
| `disk.command` | `/home/zabz/bin/disk-guard.py` | → `/usr/local/bin/disk-guard.py` |
| `db-integrity.command` | `/home/zabz/bin/db-integrity-check.py` | → `/usr/local/bin/db-integrity-check.py` |
| `cron-targets.status_file` | `/home/zabz/.cron-targets/status.json` | → `/root/.cron-targets/status.json` |
| `disk.status_file` | `/home/zabz/.disk-guard/status.json` | → `/root/.disk-guard/status.json` |
| `db-integrity.status_file` | `/home/zabz/.db-integrity/status.json` | → `/root/.db-integrity/status.json` |

(`cron_match: "cron-wrap.sh cron-target-guard"` etc. **do** match this crontab — that part is fine.)

Dropping the office bytes at `/root/bin/guards.yaml` satisfies the pin, and then produces three
`disabled` findings (command does not exist) and three `failing` findings (status file does not
exist) → **rc=1, permanently.** rc=1 is graded *GUARD-SYSTEM FAULT* and files repair work, which is
worse for the same missing file than rc=2.

**And there is a seventh change that a faithful port must make — this one is a trap:**

`db-integrity.max_age_seconds: 259200` (3 days) is the office value, and the office ran that check
**daily**. `151-VERIFY-CLOUD-AUTHORITY.md` records that on this box it was *"changed from daily to
weekly"* — its cron line is now `17 4 * * 0`. A weekly job with a 3-day max age makes the guard read
**`stale` for four days out of every seven**, and `stale` is one of the findings `verdict_for()`
deliberately keeps at **rc=1** ("a finding that means the GUARD SYSTEM ITSELF is broken"). A
byte-identical port would have gone red *on a schedule*, for a reason that looks like tampering.
So the port must also set `max_age_seconds: 604800` (7 days) — or put the check back to daily.

### 1.5 The port is a THREE-part change, and one part is the owner's

| | change | state |
|---|---|---|
| **a** | `/root/bin/guards.yaml` — office registry, six paths substituted, plus `max_age_seconds` 604800. sha256 **`b16d5d9a7fc00d2e7501e25b537331651f20342eed523aca92d944e91d13b913`** (3761 bytes, full text in Appendix B) | **prepared, NOT installed** |
| **b** | `/root/bin/guards.approval.json` = `{"registry_sha256": "<a>", "approved_by": …, "owner_row": 227}` | **owner's act — not written** |
| **c** | the cron line must gain **`--ledger-db /root/authority.db`** | **not changed** |

**Why (b) is unavoidable:** (a)'s hash is no longer the pin, so `check_approval()` returns
`unapproved` → rc=1 until a record for that exact hash exists.

**Why (c) is unavoidable, and is a trap of the same kind this estate already knows:** `verify_owner_row()`
defaults to `DEFAULT_LEDGER_DB = ~/personal-secretary-mvp/data/secretary.db`. That path **exists** on
this box — as a 1.8 MB cutover stub **with no `owner_decision_queue` table at all** (verified
read-only). So even a *correct, owner-authored* approval record would be judged unverifiable, because
the checker would be reading a dead copy. The live ledger is `/root/authority.db`
(445 rows, 190 resolved) — the cron line does not point at it. This is exactly the failure the
script's own docstring warns about: *"a monitor that measures a dead copy reports a confident wrong
number — the worst outcome in this estate's history."*

**Why I did not write (a) or (b).** (b) is the one act the checker exists to prevent: an agent
authoring the approval record that gates its own change to the registry. Row 227 is a real owner act
and is the correct row to cite, but the record must be the owner's, not mine. And writing (a) alone
would convert rc=2 (*cannot read inputs*) into rc=1 (*guard system tampered*) and file repair work —
a worse signal for the same missing file. So I prepared the exact bytes and the exact remaining
steps and changed nothing.

**What it needs, and what "fixed" will look like.** Install (a) and (c) together with an
owner-authorised (b). Then expect the next `*/15` run in `runs.tsv` to read **rc=3**, not 0 — because
two of the three guards are *already* reporting their own red conditions:
`/root/.cron-targets/status.json` has `"ok": false` (a CRLF finding on `monitor-hetzner-backups.sh`),
and `/root/.db-integrity/status.json` does not exist yet (`db-integrity-check` first runs 2026-10-18).
**rc=3 is the success code here** — it is the checker's designed "CONDITION, not fault" signal, and
`sources/cron-failures.py` honours rc=3 for every job. A porter who expects rc=0 will "fix" a working
checker into a worse state.

**Who should complete it.** The migration coordinator, who owns the `132` PORT-ADAPT list —
`152-OWNERSHIP-MAP-AND-PORT.md` assigns owners to other jobs and assigns **none** to
`guard-registry`, which is precisely why it fell through the cutover. The owner's part is one
approval record citing row 227.

---

## 2 — `ai-gateway-health` — every 30 min, rc=1

### 2.1 First correction: the exit code in the ledger is 1, not 3

Every one of the **25** rows ever recorded for this job is **rc=1** — there is no rc=3 row:

```
2026-10-11T19:30:02Z  rc=1  104s
2026-10-11T20:00:01Z  rc=1    7s
2026-10-11T20:30:01Z  rc=1   95s
2026-10-11T21:00:01Z  rc=1    3s
```

`151`'s table says *"FAILING — exit 3"*, and the task repeats "exit 3". rc=3 is the *script's internal
grade for one finding*, and it then loses to a fault, because `verdict_of()` is explicit that
**"A FAULT ALWAYS WINS"**. So "exit 3" describes a finding, not this job's exit code. Worth stating
plainly, because it changes the diagnosis: the job is not sitting at a benign "condition" code.

### 2.2 The probe is pointed at the RIGHT route — hypothesis falsified

```python
GATEWAY_BASE = os.environ.get("AI_GATEWAY_HEALTH_BASE", "http://127.0.0.1:8002")
```

and the cron line does **not** set `AI_GATEWAY_HEALTH_BASE` (`crontab -l | grep -c` → **0**). So the
probe calls **loopback on this box**. It is not calling a pre-cutover host, and it is not calling the
tailnet path.

```
$ ss -ltnp | grep -E "8002|8443"
LISTEN 127.0.0.1:8002        python (pid 105362)      <- company-api, what the probe calls
LISTEN 100.73.176.126%tailscale0:8443   tailscaled   <- the migration's private path, NOT used
```

Hand-timed with the gateway's own bearer (never printed), the exact endpoint the job calls:

```
call 1 (cold)  http=200  time=0.179s  size=13849
call 2 (warm)  http=200  time=0.033s  size=13849
routes advertised: 35
```

**35 routes, HTTP 200, in milliseconds.** *"The probe is pointed at a dead route"* is **false**.
A dead route or a wrong box cannot answer in 0.18 s with the correct catalogue.

### 2.3 The ~95 s is real, but it is NOT what makes the job red

Durations are 3–8 s on most runs, with two outliers: **104 s** (19:30Z) and **95 s** (20:30Z). When
the catalogue call times out, `main()` does this:

```python
if cat.get("enabled") and not cat.get("ok"):
    verdict["notes"].append({"kind": "catalogue-unreadable", …})
```

It goes into **`notes`** — printed with ⚠️ — and `notes` is **never passed to `verdict_of()`**. Notes
do not set rc. Confirmed in the code and in the log, which shows runs that printed
`catalogue-unreadable … TimeoutError` alongside the same rc they have otherwise. The script already
documents the cold-cache cost (*">90 s first call after the API has been idle … the immediately
following call took 10.2 s"*) and `CATALOGUE_TIMEOUT` was **already raised to 90 s** for it.

The 95 s is intermittent, not a fixed cost — and it is load, not a dead box: at **19:37:50**, inside
the 104 s window, `company-api`'s journal shows it actively serving agents
(`router served task=work_mode …`, `Agent dept_engineering step 47523 round 1 …`). A single-process,
memory-constrained API under agent load answers `/v1/models` slowly now and then. **Raising the
timeout again would not change rc, and is not a fix.**

### 2.4 What actually makes it rc=1 — one finding, one bucket

The only 🔴 (fault-graded) finding is a **bucket whose `model` column literally reads `unknown`.**
True 7-day window, using `julianday()` exactly as the script does (a naive
`created_at >= datetime('now','-7 days')` silently over-counts here, because `created_at` carries a
`T` while `datetime()` returns a space — the script documents that bug itself):

```
unknown   24 calls   24 failed (100%)   last seen 2026-10-07T16:52:10Z   0 calls in 6h   not retired
```

Its 24 failures split, by the script's own `CONDITION_ERROR_PATTERNS`:

* **15 condition-class** — `402 "You need positive balance"`, `404 "does not exist or you do not have access"`, anthropic `not_found_error`, `not deployed`.
* **9 fault-class** — `openai attempt N/3: Error code: 400 … 'invalid model ID'`.

Grading path, traced through the source:

1. `recent_calls == 0` → the **historical** branch (no live traffic to judge).
2. `_all_conditions(m, recent=False)` needs `window_condition == failed` → `15 != 24` → **False**.
3. Falls through to `fault / calls <= fail_rate_limit` → `9 / 24 = 0.375 > 0.20` → **False**.
4. So `_condition_not_ours()` is False → `condition=False` → 🔴 → `verdict_of()` → **rc=1**.

**`invalid model ID` is the whole reason this job is red.** It is the *same family* of text the
pattern list already treats as an external condition (`model not found`, `not_found_error`,
`does not exist or you do not have access`, `not deployed`) — it is simply not in the list. Nine
OpenAI rejections of an id the provider does not serve hold a 24-call bucket, and that bucket holds
the job.

Everything else is graded correctly and honestly: `tier-collapse` is promoted to a **CONDITION** (🟠)
on this box, and I confirmed it is real — `/opt/company/app/config.py` L131–133:

```
model_tier1: str = "deepseek/deepseek-v4-flash"
model_tier2: str = "deepseek/deepseek-v4-flash"
model_tier3: str = "deepseek/deepseek-v4-flash"
```

Three tiers on one literal is exactly the redundancy loss this monitor was built to catch, and it is
reported as a condition rather than a fault. That part is the job working as designed.

### 2.5 It will decay to green on its own — which is not a fix

The bucket's last row is **2026-10-07T16:52:10Z** and the window is 7 days, so the finding ages out
around **2026-10-14** and the job returns to rc=3 (all-conditions) with nothing changed. A false red
with a timer is worse than a red, because it teaches the reader that this job goes green on its own.

### 2.6 What it needs — two small, separable decisions

1. **Add `invalid model id` to `CONDITION_ERROR_PATTERNS`** — one line, in the same class as the
   patterns already listed. This is the actual repair.
2. **Decide whether `unknown` should be graded as a lane at all.** The gateway records `unknown` when
   it cannot attribute a call to a model (its journal at 19:37:50 shows
   *"Department model resolution dropped 3 id(s) not in the live gateway catalogue"*). That is a
   **data-quality bucket, not a model**. Reporting it as a failing model is the *"an empty result is
   not evidence"* family: the honest form is its own note — *the gateway could not attribute N calls*
   — because that is a signal about the gateway, not about a lane.

Separately, and **not** as a fix: the intermittent 95–104 s `/v1/models`. If that is to be made
reliable, the lever is making the API's catalogue cheap or warming it, not raising `CATALOGUE_TIMEOUT`.

---

## 3 — Cross-cutting notes

* **Transport.** This box's ssh does not reliably exit — `ssh … 'hostname'` returned its output and
  then hung the client until killed, three times. Every command in this work was run through a
  bounded wrapper that appends a remote sentinel, polls the output file, and kills the client the
  moment the sentinel lands (~1.3 s per real command instead of a 40 s hang). This is why the work
  could be done at all; a naive `ssh … | bash` loop would have spent its whole budget hanging.
  Worth knowing for the next session: this is not a property of the authority box.
* **Office box, frozen, honoured.** Every office command was `ls` / `cat` / `sha256sum` /
  `base64` on one 2.4 KB file. Nothing was started, stopped, enabled, disabled, unmasked or
  restarted; nothing was written.
* **Hard rules honoured.** `/root/authority.db` was opened only as `file:…?mode=ro` with
  `PRAGMA query_only=1`. No database, `-wal`, `-shm` or backup was written, deleted or overwritten.
  `company-api`, `cloudflared`, `secretary-dashboard` and `phone-redirector` were not touched. No
  credential value was printed (the bearer was expanded inside the remote shell).
* **Both jobs share one shape**, which is the point of the task: each is *pointed at something that
  does not exist* — a config file for #1, an error-text pattern for #2 — and neither failure is the
  thing its symptom names. `guard-registry` is not a broken checker; `ai-gateway-health` is not a
  slow gateway or a wrong route.

## 4 — Open questions for the owner (I cannot answer these myself)

1. **Authorise the `guards.yaml` port?** Approve the installed registry (Appendix B) and the
   approval record citing owner row 227, and set `--ledger-db /root/authority.db` on the cron line.
   Expected result: rc=3, and it must be read as success.
2. **`ai-gateway-health`** — approve the one-line `invalid model id` pattern addition, and decide
   whether `unknown` is a lane or a gateway note. Without a decision the job clears itself by
   accident on ~2026-10-14 and nobody learns anything.
3. **`/root/bin/guards.yaml` vs `/root/bin/guards.approval.json`** — if the owner prefers *not* to
   own a registry that must be re-approved on every future change, the alternative is to **retire**
   the check on this box (remove the cron line, and record that the office registry is office-only).
   That is a legitimate answer, but it is a deliberate retirement, not the accident we have now, and
   it must be recorded as such — `132` currently says PORT-ADAPT.

---

## Appendix A — office `guards.yaml`, verbatim (the pinned baseline)

`secratary-ts:/home/zabz/bin/guards.yaml`, 2463 bytes,
sha256 `91ea76998a893eb7d232307abdfb84597d3f7abc37b9da04feecc738f65d4483`.

```yaml
# guards.yaml -- the guards that matter, and the command that proves each one is alive.
#
# READ THIS BEFORE EDITING.
# -----------------------------------------------------------------------------
# This file is the registry read by `guard-registry-check.py`, which runs as a
# SEPARATE cron job (see guard-registry-check.cron / install-guard-registry-check.sh).
# A guard whose entry here is removed or disabled is a guard that has been turned
# off, so editing this file is itself a guarded act.
#
# guard-registry-check.py pins the sha256 of the registry it was built for
# (BOOTSTRAP_REGISTRY_SHA256, a constant in a DIFFERENT file). Any other hash is a
# CHANGE and makes the checker exit non-zero unless guards.approval.json carries a
# record for that exact hash naming a real owner-queue row. So changing a guard
# requires an owner approval record -- you cannot do it silently by editing this
# file alone. Do NOT "fix" a red checker by editing the pin in the checker: that is
# disabling the guard, which is precisely the self-modification this exists to stop
# (journal SI-5: a guard verified by the same process that could disable it is not
# a guard).
#
# The checker itself never runs these guards and never sends anything. It reads
# each guard's own status file and the live crontab, and judges. Running the guards
# from the checker would re-create the coupling this removes.
version: 1

guards:
  - id: cron-targets
    why: "Every path the crontab calls must exist. On 2026-09-30 five cron targets had been missing for ~28 hours and nothing said so."
    command: /home/zabz/bin/cron-target-guard.py
    cron_match: "cron-wrap.sh cron-target-guard"
    cron_wrap_name: cron-target-guard
    status_file: /home/zabz/.cron-targets/status.json
    max_age_seconds: 172800

  - id: disk
    why: "Filesystem headroom. The 2026-09-30 outage ended at 99% full because nothing watched retention."
    command: /home/zabz/bin/disk-guard.py
    cron_match: "cron-wrap.sh disk-guard"
    cron_wrap_name: disk-guard
    status_file: /home/zabz/.disk-guard/status.json
    max_age_seconds: 7200

  - id: db-integrity
    why: "SQLite integrity of the owner's records. A corrupt store makes every downstream answer confidently wrong."
    command: /home/zabz/bin/db-integrity-check.py
    cron_match: "cron-wrap.sh db-integrity-check"
    cron_wrap_name: db-integrity-check
    status_file: /home/zabz/.db-integrity/status.json
    max_age_seconds: 259200
```

## Appendix B — the proposed `/root/bin/guards.yaml` (NOT installed)

3761 bytes, sha256 **`b16d5d9a7fc00d2e7501e25b537331651f20342eed523aca92d944e91d13b913`**.
Seven changes from Appendix A: three `command:` paths, three `status_file:` paths, one
`max_age_seconds` (259200 → 604800, with its reason inline). A provenance header is prepended; the
body below `version: 1` is otherwise byte-identical to the office file.

```yaml
# PORTED TO secratary-cloud 2026-10-11 (workstream 155) -- provenance, do not remove.
# SOURCE : secratary-ts:/home/zabz/bin/guards.yaml, 2463 bytes,
#          sha256 91ea76998a893eb7d232307abdfb84597d3f7abc37b9da04feecc738f65d4483
# WHY    : that hash is EXACTLY BOOTSTRAP_REGISTRY_SHA256 in this box's
#          /usr/local/bin/guard-registry-check.py, so the registry was part of the
#          unit of work that installed the checker. 132-CRON-INVENTORY L130 lists
#          guard-registry as PORT-ADAPT and L537 assigns it to secratary-cloud.
# CHANGES (4, each mechanical and listed in 155-DIAGNOSIS-TWO-FAILING-JOBS.md):
#   1-3 command:      /home/zabz/bin/*.py  -> /usr/local/bin/*.py   (guards live there on cloud)
#   4-6 status_file:  /home/zabz/.*/       -> /root/.*/             (guards write there on cloud)
#   7   max_age_seconds for db-integrity: 259200 -> 604800. The cloud cron runs it
#       WEEKLY (17 4 * * 0), so the office 3-day max age would make the guard read
#       `stale` -- a GUARD-SYSTEM FAULT, rc=1 -- for four days out of every seven.
#       A byte-identical port would have gone red on a schedule. Do not revert this.
# THIS FILE IS NOT THE PINNED BASELINE, SO IT NEEDS AN OWNER APPROVAL RECORD
# (guards.approval.json, owner_row 227). See 155 for the exact remaining steps.
version: 1

guards:
  - id: cron-targets
    why: "Every path the crontab calls must exist. On 2026-09-30 five cron targets had been missing for ~28 hours and nothing said so."
    command: /usr/local/bin/cron-target-guard.py
    cron_match: "cron-wrap.sh cron-target-guard"
    cron_wrap_name: cron-target-guard
    status_file: /root/.cron-targets/status.json
    max_age_seconds: 172800

  - id: disk
    why: "Filesystem headroom. The 2026-09-30 outage ended at 99% full because nothing watched retention."
    command: /usr/local/bin/disk-guard.py
    cron_match: "cron-wrap.sh disk-guard"
    cron_wrap_name: disk-guard
    status_file: /root/.disk-guard/status.json
    max_age_seconds: 7200

  - id: db-integrity
    why: "SQLite integrity of the owner's records. A corrupt store makes every downstream answer confidently wrong."
    command: /usr/local/bin/db-integrity-check.py
    cron_match: "cron-wrap.sh db-integrity-check"
    cron_wrap_name: db-integrity-check
    status_file: /root/.db-integrity/status.json
    max_age_seconds: 604800
```

## Appendix C — evidence commands (all read-only, all re-runnable)

```bash
# the missing input and the exact refusal
ls -la /root/bin/guards.yaml; tail -3 /root/.guard-registry/cron.log
# the pin
grep -n BOOTSTRAP_REGISTRY_SHA256 /usr/local/bin/guard-registry-check.py
# the office bytes (on secratary-ts; FROZEN box -- keep it to ls/cat)
sha256sum ~/bin/guards.yaml
# the ledger the approval must be verified against
ls -la /root/personal-secretary-mvp/data/secretary.db          # 1.8 MB stub, no owner_decision_queue
/opt/company/.venv/bin/python -c "import sqlite3;c=sqlite3.connect('file:/root/authority.db?mode=ro',uri=True);print(c.execute(\"SELECT id,status FROM owner_decision_queue WHERE id=227\").fetchall())"
# job 2: the route is live and fast
curl -s -o /dev/null -w 'http=%{http_code} time=%{time_total}s\n' http://127.0.0.1:8002/v1/models
# job 2: the one fault-graded finding
grep -F ai-gateway-health /root/.cron-status/runs.tsv | tail -5
tail -14 /var/log/ai-gateway-health.log
```

---

## 5 — The change I made for #2, and the reading that could make it wrong

*Appended 2026-10-11T21:29Z, after §1–§4 were written.*

I applied the minimal form of §2.6(1). **One line, in `/usr/local/bin/ai-gateway-health.py`:**

```diff
-               r"not deployed|no such model", re.I),
+               r"not deployed|no such model|invalid model id", re.I),
```

| | |
|---|---|
| file | `/usr/local/bin/ai-gateway-health.py` (46175 bytes) |
| before | sha256 `bc4a3637cb9d2927025f69b502a9ea90213040a8d89a508022a32bac89040286` |
| after | sha256 `69900cdb4ff0c2502f4257c0cfc9f53a119b1ce625aad3dd0b51a9a81fa3ec2f` |
| pristine copy | `/root/out/migration-review/155-ai-gateway-health.py.orig` (byte-identical to *before*) |
| validation | `py_compile` OK; the script's own `--self-test` (its built-in negative control) **PASSED**, including `empty_response is a FAULT` and `404 'not deployed' is a condition` |
| rollback | `cp /root/out/migration-review/155-ai-gateway-health.py.orig /usr/local/bin/ai-gateway-health.py` |
| services | **none restarted.** `company-api`, `cloudflared`, `secretary-dashboard`, `phone-redirector` untouched. The change takes effect at the job's next `*/30` tick because cron re-executes the script each run. |

**This does not silence the finding.** The `unknown` bucket is still reported, still in the log, still
in `runs.tsv` — what changes is its *grade*, from FAULT to CONDITION, i.e. from rc=1 to rc=3. The
finding stays visible; the job stops claiming a code fault it cannot attribute to a lane.

**The reading that could make this wrong — stated plainly.** The nine rows read
`openai attempt N/3: Error code: 400 … 'invalid model ID'`. I read that as the same class as the
`404 The model … does not exist or you do not have access` rows sitting beside it — a provider
rejecting an id it does not serve — which is exactly what `CONDITION_ERROR_PATTERNS` already treats
`model not found`, `not_found_error`, `does not exist or you do not have access`, `not deployed` and
`no such model` as. On that reading the omission is an oversight.

**The opposite reading is available and I cannot settle it from the record:** a `400 invalid model ID`
may be *our* gateway offering a DeepSeek id to an OpenAI-shaped endpoint that will never accept it —
a genuine routing defect that is ours to fix, in which case the monitor was RIGHT and the repair
belongs in the gateway, not in the pattern list. What would distinguish the two is whether the gateway
*intends* to try that id on that provider; that is a routing question this artifact does not answer and
I have not guessed at it. So this change is a **hypothesis made visible**, not a closure: it makes the
job's own record readable (rc=3, conditions named) instead of leaving one unattributable bucket
holding the whole job at rc=1. **It should be checked, not assumed.**

If the gateway turns out to be mis-routing, the correct end state is both: revert this line *and* fix
the routing, so the fault is graded as a fault again — with a cause that can be named.

---

## 6 — Verification by the job's own next scheduled run

*Appended 2026-10-11T21:33Z.* Rule followed: **not proved by hand.** The change was validated only by
watching the job's next `*/30` tick land in `/root/.cron-status/runs.tsv`.

```
$ grep -F ai-gateway-health /root/.cron-status/runs.tsv | tail -4
2026-10-11T20:00:01Z	ai-gateway-health	1	7
2026-10-11T20:30:01Z	ai-gateway-health	1	95
2026-10-11T21:00:01Z	ai-gateway-health	1	3     <- last run BEFORE the change  (25 rows, all rc=1)
2026-10-11T21:30:02Z	ai-gateway-health	3	7     <- first scheduled run AFTER it
```

The run's own log shows the bucket re-graded and the footer the script prints only when **every**
finding is a condition:

```
🟠 failing-historical  unknown — 24 of 24 calls failed (100%) over 7d, and it has had NO traffic in 6h,
                        so whether it works NOW is unmeasured. Last seen 2026-10-07T16:52:10.953310+00:00.
                        [CONDITION: provider account/deployment error]
  → CONDITION, not fault (exit 3): every finding above is an external provider account/deployment
    condition (billing, or an id the provider no longer deploys). Nothing here is ours to fix;
    runs.tsv records rc=3 so this cannot be mistaken for a code fault.
```

**The finding is still there** — `unknown`, 24 of 24 — which is the point: it was re-graded, not
silenced. Nothing restarted; cron re-executes the script each tick, so the next tick picked the file up.

**And the same run advertised `gateway catalogue: 35 route(s) advertised`, in 7 s** — the identical
endpoint, through the identical cron line, that had "timed out" at 95 s and 104 s an hour earlier.
That is the dead-route hypothesis dying on its own evidence, in the job's own record.

`guard-registry`, deliberately untouched, held **rc=2** at 21:30:02Z — exactly as §1 predicts while
the registry is absent.

### Where the two jobs stand

| job | before | now | what remains |
|---|---|---|---|
| `ai-gateway-health` | rc=1, 25/25 | **rc=3**, verified 21:30:02Z | §5's open routing question; §2.6(2) `unknown` lane decision; §2.3 the intermittent 95 s catalogue |
| `guard-registry` | rc=2 every 15 min | **rc=2, unchanged by design** | an owner-authorised approval record (row 227) plus the registry (Appendix B) and `--ledger-db /root/authority.db`. Then expect **rc=3**, and read that as success — see §1.5 |

---

## 7 — Renumbering and final state

*Appended 2026-10-11T21:36Z by the author of this artifact.*

The **coordinator session** renumbered this file from `155-` to `157-` at 21:33Z, because a sibling
had already claimed 155 (`155-PRODUCTION-COMMS-FRESHNESS-DIAGNOSIS.md`, 21:23Z) and 156 was taken too
(`156-DIALPAD-GAP-TWO-JOBS.md`, 21:25Z). Its note is at the top of this file. **The body below is
unedited**, so self-references inside it still read "155" — the title line, Appendix B's provenance
header, and §5/§6's `155-ai-gateway-health.py.orig`, which is the backup's actual on-disk name and
has not moved.

Final state:

| | |
|---|---|
| this artifact | `/root/out/migration-review/157-DIAGNOSIS-TWO-FAILING-JOBS.md` |
| backup of the monitor I modified | `/root/out/migration-review/155-ai-gateway-health.py.orig` |
| `ai-gateway-health` | rc=1 on all 25 rows → **rc=3**, verified on its own 21:30:02Z scheduled run |
| `guard-registry` | rc=2 at 21:30:02Z — unchanged by design, awaiting the owner's approval record (§1.5) |
| services restarted | **none** |
| credentials printed | **none** |

### A coordination defect worth passing on

Three mesh children were dispatched into this directory at once and each ran a plain `ls` to claim
"the next free number after checking with `ls`". **`ls` cannot do that under concurrency:** 155 was
taken between my check (21:23:08Z) and my write (21:28Z), and 156 went in the same window. All three
artifacts are intact and none overwrote another, but the *numbering* is only unambiguous now because
the coordinator repaired it by hand. A claiming convention that needs a human to fix it afterwards
should be replaced — a file created with `O_EXCL` under the intended name, or a single allocation
step, would make the claim atomic. Flagging it because the next fan-out will hit the same race.
