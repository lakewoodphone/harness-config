# 170 — MASTER RECORD: the attention badge, the sentinel that moved, and the fleet audit it triggered

**Session:** 2026-10-12, 03:05Z–04:45Z. **Author:** Zabz, ZABZ-YOGA, with six mesh children on
`zabz-tech-linux` and `ZABZ-TECH`. **Machines touched:** `secratary-cloud` (THE AUTHORITY, writable);
`secratary` (office box — **READ-ONLY throughout**, every command `ls`/`stat`/`tail`/`grep`/`sha256sum`,
no service state changed, nothing written); ZABZ-YOGA; and the two mesh nodes via dispatched children.

**One-line status: the badge was reading a stopped clock on a frozen host. It now reads a live sentinel
running on the authority, it can never again be shadowed by a frozen source, and something finally alarms
when the sentinel stops. Everything else in this document is what the audit found on the way there.**

---

## 0. IF YOU READ ONLY ONE SCREEN

| | |
|---|---|
| **the question** | *"Why does it say stale? We migrated from the office secretary to the cloud secretary … Why is everything stable? What's going on? Audit this seriously and get it fully and robustly fixed and optimized."* |
| **why it said stale** | the findings are computed by the `ceo-kernel` sentinel, which **only ever ran on the office box**. The cutover moved the database, API and dashboard, left the sentinel behind, then froze the box. Its last write was `2026-10-11T20:20:06Z`. Every badge read that host. |
| **why it looked stable** | a stopped clock is stable: the same six findings, same numbers, forever. Two of them were artifacts of the stopped machine; **two real HIGH findings were invisible to it** (`db_writable`, `web_currency_math`). |
| **fixed and live** | sentinel on the authority every 5 minutes; the gate picked it up **with no service restarted**; the badge's data origin is now a **list** and the freshest reading wins; an **absence monitor** now alarms when the sentinel or its schedule disappears. |
| **still open** | a `company-api` restart to load two tested app fixes; two kernel checks that measure the wrong thing; the archive's green light is partial; the API's own process-wide DB lock; the fleet still fetches config from the frozen box. §6 has each with an owner. |
| **what you do** | **reload the GUI page once** (your browser still runs the old bundle that asks only the frozen box). Then answer the one question in your queue, §6.1. |

---

## 1. THE QUESTION, AND THE ANSWER

The badge was not broken. **It was honest** — it labelled a reading it could not prove current, with the
age, exactly as designed. What failed was the estate: a producer moved without the thing that reads it, and
nothing anywhere watched for a *missing* reading.

| what the owner saw | what was actually true |
|---|---|
| `6 needing attention · stale 6h ago`, and the age growing | `~/ceo-kernel-var/latest.json` on the **office box**, mtime `2026-10-11T20:20:06Z`, `host: secratary` — and that last write was itself inside the accidental **19:04–20:26Z unfreeze window** of 11 October |
| the same six items, never changing | `run.log` ends at `20:20:06`; `systemctl is-enabled cron` → **`masked`** (frozen by decision, `131` Rule 1 / `142`) |
| "everything stable" | the office gate was still answering `/dsh-attention.json` to this laptop's browser every 60 s — **115,737** such requests in its log |
| — the live authority, one hostname away | `secratary-cloud` answered `{"read": false, "error": "cannot read /root/ceo-kernel-var/latest.json: No such file or directory"}`: the gate was ready, **the producer did not exist there** |

**Correction kept on purpose:** the frozen report named `config_sync` and `session_archive` as HIGH. Both
were artifacts of the *stopped box*. The first live report named `db_writable` and `web_currency_math`
instead — and `db_writable` was reproducible (4/4 write probes refused at 5 s). A stopped clock does not
merely fail to tell the time; it hides the emergencies.

---

## 2. ROOT CAUSES

| # | cause | the measurement behind it |
|---|---|---|
| **R1** | **The producer was never moved.** `run-sentinel` existed only on the office box; the port was prepared on 11 October and never installed (`140 §A1`, blocked mid-session by an SSH refusal). | `ls /root/ceo-kernel*` → nothing; no `run-sentinel` in the authority's crontab; the gate's state path had no file |
| **R2** | **A hostname inside an immutably cached client bundle.** `BADGE_AUTHORITY` named the office box; client bundles are served immutable (a year). Even with a live authority, a loaded machine would ask the wrong host silently. | `packages/plugin-attention-badge/lib/client.js`; `grep` for the office FQDN across the repo → 242 hits, of which this was the load-bearing one |
| **R3** | **Nothing alarmed on a missing reading.** `run-sentinel.sh` **always exits 0 on purpose**, so `cron-wrap`'s ledger reads identically for "senses nothing wrong" and "never ran". | `140 §A1` predicted exactly this and filed it as a defect on 11 October; it happened the next day |
| **R4** | **Root's crontab is a shared read-modify-write.** Found *while fixing*: my own line was deleted 11 seconds after I installed it by another session's `crontab -l … crontab -`, and every individual edit verified its own line. | `crontab -l \| grep -c run-sentinel` → **0** at 03:44Z; the ledger's only row was a manual test; spool mtime `03:15:47Z` (11 s after install) |
| **R5** | **Green lights measuring the wrong thing** — four instances, each diagnosed with a line number or a command. | §5 |

---

## 3. WHAT I CHANGED

### 3.1 The chain that fixes the badge

| # | change | lives at | live? | proof |
|---|---|---|---|---|
| 1 | `ceo-kernel` installed on the authority: git checkout from a bundle (HEAD `7be7fde`, `git status` empty), state seeded from the frozen box so the 3,007-row trend survives, `ck/sources.py` patched to read `CEO_KERNEL_DB`/`CEO_KERNEL_AUTHORITY_HOST` (old values remain the defaults) | `secratary-cloud:/root/ceo-kernel`, `/root/ceo-kernel-var` | **yes** | first run 15 s: `generatedAt`, `host secratary-cloud`, `db /root/authority.db`, `authoritative true` |
| 2 | scheduled every 5 minutes via the estate's own `cron-wrap.sh`, name unchanged, `nice -n 10`, cadence chosen from the measured 15 s run | authority root crontab (backed up first) | **yes** | ledger `2026-10-12T03:45:22Z  run-sentinel  0  17` |
| 3 | **no service was restarted**: `phone-gate.service` defaults `CEO_KERNEL_STATE` to `$HOME/ceo-kernel-var`, exactly where the port put the state | — | **yes** | `curl http://127.0.0.1:3086/dsh-attention.json` → `read true, age_seconds 0.3, host secratary-cloud` |
| 4 | badge v4: the data-origin attribute is a **list**; candidates are asked in order and the **freshest readable reading wins**; a refusal or unreachable source falls through; an all-stale set is still rendered, labelled, naming its host; a refusal with no previous reading no longer claims "last good" | `assets/phone-badge.js` | **yes** (both authority asset paths + this machine) | `node scripts/verify-badge.js` **181/181** (was 163); `python scripts/verify-badge-gate.py` **55/55** |
| 5 | the plugin declares both authorities, authority first, the frozen box only as a stand-in | `packages/plugin-attention-badge/lib/client.js` | **yes** on this machine; needs a page reload elsewhere | profile check: `dsh-plugin-attention-badge LINK bundles=True`; published to the vault |
| 6 | the fixed asset deployed to **both** paths the gate could read (`resolve_asset()` searches `/usr/local/assets/` *before* the checkout) | `/usr/local/assets/phone-badge.js` **and** `/root/code/harness-config/assets/phone-badge.js`, each with a `*.pre-multisource-*` backup | **yes** | served sha256 `46fb7f1f…`, `var VERSION = '4'` |
| 7 | **the absence monitor** — `scripts/mesh/sentinel-freshness-check.py`, every 5 min: 20-minute threshold on the newest `history.jsonl` row, a status file, **one** journal `pain` entry per 6 h, exit **2** (never 1), and `--expect-cron` so a *lost schedule* is an absence finding too | authority `/usr/local/bin/` + cron `sentinel-freshness` | **yes** | ledger `sentinel-freshness 0 2`; detector proved against the real machine (`unscheduled … the schedule is GONE`, rc=2) before the re-install |
| 8 | the port's idempotent installer moved out of a session staging directory into the repo | `scripts/mesh/168-port-sentinel-to-authority.sh` | repo | — |

Two bugs in my own monitor were found by its tests and fixed before it was scheduled: the rate-limit marker
was keyed on the alarm's *wording* (an alarm loop), and the row counter re-read the whole history file every
run (bounded now — it grows ~62 MB a year).

### 3.2 What the six mesh children changed

| workstream | result | live? |
|---|---|---|
| phone web bundle typeset money as LaTeX (`web_currency_math`) | **both** copies patched (the one the check names and the one `phone-engine` actually serves); verified over the phone URL with a fresh cookie session | **yes** — kernel reads `ok`, "currency is text" |
| dead model lanes (`model_lane_health`) | the three provably dead lanes retired in `model_registry`; a **runtime** lane-health gate written in `smart_router.py` (+200 lines, 84 tests pass, a real routed call succeeded) | data **yes**; the gate **no** — needs a `company-api` restart |
| `agent_dead_weight` | proved `frontier_risk_board` does real governance work and must **not** be retired; the defect is the planner handing it doomed work; a guard written (+106 lines) | **no** — needs a restart; the bad ticks age out ~23 October |
| `app_voice`, `model_failover` (both `unknown`) | unit name resolved from `ExecStart` instead of a hardcoded office unit; the model-failover watch ported to the authority (`/etc/cron.d/model-failover-watch`) | **yes** — `unknown → info`, `unknown: 0` |
| `config_sync` (was blind) | a status writer that measures local HEAD against the canonical remote | **yes** — `config converged … at 83d4897` |
| transcript archive failed pass | fixed and green: exit `3 → 0`, the false ALARM file removed, `zabz-yoga` proved to be a *transient* reported as a failure | **yes** — and §5.3 says what its green light still cannot see |

---

## 4. THE STATE OF THINGS, AS MEASURED AT 04:15Z

**The owner's surface** — `https://secratary-cloud.tail93e6e6.ts.net/dsh-attention.json`:

```
{"read": true, "at": "2026-10-12T03:55:04Z", "host": "secratary-cloud",
 "total": 19, "healthy": 15, "ok_count": 15, "attention": 3, "unknown": 0, "highest": "high"}
```

| severity | check | what it says |
|---|---|---|
| high | `agent_dead_weight` | `frontier_risk_board` 30 ticks / 0 completions — diagnosed, fix written, not live |
| high | `attention_debt` | 7 held owner items, oldest ~8 days, **none critical or urgent** |
| high | `owner_queue` | **160** decisions waiting, 6 deferrals expired; head is #228 (blocking, 10.5 days) |

**Quiet (i.e. ok) and worth naming**, because each was a finding earlier tonight: `db_writable`,
`web_currency_math`, `model_lane_health`, `app_voice`, `model_failover`, `config_sync`, `session_archive`,
`comms_freshness`, `delivery`, `liveness`, `tick_completion`, `empty_ticks`, `telemetry_gaps`,
`replication`, `phone_endpoint`, `evolution`.

**The schedule** (all three counted back after the lost-line incident): `run-sentinel` 1,
`sentinel-freshness` 1, `config-sync-status` 1.
**The monitor:** `state ok, newest row 2 s old`, `--expect-cron` armed on both jobs.
**Verifiers:** `verify-badge.js` **181/181**; `verify-badge-gate.py` **55/55**.
**The frozen office box:** untouched, still serving badge v3 and the `20:20:06Z` reading to anything that
asks it — which is why a page that has not been reloaded still shows the old pill.
**Repos:** the canonical remote is the **vault** (`root@2.28.33.58:/srv/git/harness-config.git`); this
session's changes are on `main` from `16058e5` (badge asset + monitor) → `1abfb1a` (plugin list) →
`0b6428f` (verifier + docs) → `83d4897` (schedule detector + `168 §7.3`). This laptop also carries the same
changes as local commits (`8c00270d`, `5041aa24`) because its `origin` is still the frozen office box and it
has **no vault access at all** (`Permission denied (publickey)`).
**Archive:** 43,711 objects; per machine and kind — `zabz-tech copilot-chats` 32,103 files / 18.07 GB,
`zabz-yoga copilot-chats` 8,184 / 5.00 GB, `zabz-tech dsh-sessions` 3,727 / 4.55 GB,
`zabz-tech-linux` 434 / 0.05 GB, `secratary` (the authority's own corpus) 1,868 / 1.28 GB.
`--check` exits **0**. **Yisroel's Mac has never contacted the archive: zero rows, ever.**
**The API:** `_db_lock contended` **71 times in 30 minutes**; `/v1/models` 4.1 s (a 60 s stall was observed
04:00–04:11); `/health` ok in 0.72 s; a fresh interpreter builds the same catalogue in 0.5 s.

---

## 5. THE GREEN LIGHTS THAT MEASURE THE WRONG THING (R5)

These are the audit's most valuable output: each is a surface that reports health while the thing it exists
to watch is broken. All four are diagnosed; none is patched, deliberately, because each needs a threshold or
a design decision that a wrong patch would replace one wrong number with another.

### 5.1 `liveness` prints a constant
`ck/sentinel.py:452` — `age = pkt.data_age_seconds or 0`. `sources.scalar` leaves `data_age_seconds` **None**
for a raw SQL scalar (its provenance prints the known `age=?`), so `None → 0` and the check cannot go stale.
Measured: the report said *"ticking: newest tick 0.0m ago"* while a direct query made the true age
**3,059 s**. It would still say "ticking" at 59 minutes.
**Fix shape:** compute the age from the timestamp; then calibrate the threshold from the real tick-gap
distribution (24 h: median 22.2 min, max 186.2 min) rather than the current 60 min — otherwise the honest
number simply trades a lie for spurious attention items.

### 5.2 `db_writable` escalates on a 6-second probe
The check's `BEGIN IMMEDIATE` probe fails at 6 s and reports HIGH *"the authoritative database refuses
writes"*. Measured: with a **25 s** timeout, **30/30** acquires succeeded (max wait 9.0 s); the API commits
250-row transactions every few minutes; the whole box logged **3** real `database is locked` events in 24 h.
The file lock is **contended, never stuck** — and the contention is the app's own global lock (§5.4).
**Fix shape:** re-probe at 60 s before declaring HIGH.

### 5.3 The transcript archive's `--check` measures staleness, not completeness
It compares **one newest-source-mtime per machine** and derives its supervised set from machines that have
already reported. Consequence, measured: the desktop's Copilot chats sit at **18.07 GB archived against
~37.9 GB on the machine** (the child's count on that machine), and Yisroel's Mac has **never** been archived
— while `--check` prints `gaps=[]`, `silent=[]` and exits **0**. The backfill *is* draining (a run every
~8 minutes, 0.45–0.5 GB each, `ok=1`, *"truncated; more to pull"*), so this is a window, not a loss — but a
green light that cannot see it is the defect.
**Fix shape:** completeness per (machine, kind) against the machine's own `--list`, and supervise the
*configured* machine list rather than the machines that happened to report.

### 5.4 The API serialises every connection behind one process-wide lock
`app.database._db_lock`: **71 waits in 30 minutes** (04:13Z), 36 threads on PID 332682. It is the mechanism
under the `db_writable` reading and under the `/health` *"db check timed out (lock contention)"* recorded a
day earlier in `140 §B1`. See the pain entry `P3139`. **The next probe is a stack dump inside the process**
(`py-spy dump` on 332682 while a request is stalled) — the holder of the lock has never been named, only the
queue it creates. **Do not "fix" this by shrinking a busy timeout or restarting the process.**

---

## 6. WHAT TO DO NEXT

**6.1 Yours (the only thing blocking anything)**
Your queue's head — `owner_decision_queue` #228, 10.5 days old, **blocking 117 of the 160 waiting items**:
the business is taking roughly 4,500 a month out of your personal accounts and you are out of personal
money. **Recommendation: set the 90-day test — zero subsidy by 1 January.** Reading it, and the two that
follow it, is one command: `ssh secratary-cloud "python3 /root/bin/owner-queue.py next"` (or
`journal/state/owner-questions.md`, mirrored every 15 minutes).

**6.2 Yours, but only because it is someone else's machine**
The Mac has never been archived. Either our key goes onto Yisroel's machine, or a *push* counterpart is
shipped to it. **Recommendation: push** — the Mac flaps (offline 04:20 → active 04:30 → dead 04:35) and a
pull that must catch it awake is the mechanism that has never once worked. Both options put a credential on
an employee's machine, which is why it is yours to name and not mine to choose.

**6.3 Mine, next session, in this order**
1. **`company-api` restart** — makes the lane-health gate and the board-seat guard live. Tested (84 + 16
   tests, one real routed call in a fresh process) but **not exercised in-process**; deliberately not done at
   04:30 unattended. One command, then re-run the sentinel and one real completion.
2. **`liveness`** and **`db_writable`** (§5.1, §5.2) — two small kernel changes with the thresholds derived
   from the measurements above.
3. **Archive completeness** (§5.3) and the Mac's push mechanism.
4. **The `_db_lock` holder** (§5.4) — one stack dump while stalled.
5. **The canonical-remote migration** — four machines still fetch config from the frozen office box
   (`laptop origin=secretary-ts:`, `bench origin=secretary:`), and the kernel repo's canonical copy is a bare
   repo *on that box*. Decided as `D3034`/`162`; it is a migration (four HEADs disagree, journal ids
   collide), not a hostname swap.
6. **Retire the stand-in**: drop `secratary.tail93e6e6.ts.net` from `BADGE_AUTHORITIES` when the office box
   is decommissioned. Until then it is a labelled fallback, not a second truth.
7. **`journal/` holds a stale mirror of this repo** — 598 files, including a
   `packages/plugin-attention-badge/lib/client.js` that names the old authority, committed as a block on
   2026-09-17. Left in place deliberately (removing 598 committed paths needs its own decision); named so a
   grep finds the real file, not the shadow.
8. **Delete the unused `run.err`/`run.log` seeding artefacts** on the authority and the `*.pre-*` backups
   once this record is a week old, so `/root` does not turn into a junk drawer.
9. **`AGENTS.md` §1 still names the frozen office box as the archive host** (`secratary:/home/zabz/
   lpt-transcripts/`, pulled by `cron on secratary`) — the archive moved to `/opt/company/archive/
   lpt-transcripts/` on the authority and is pulled by `transcript-archive-pull.timer` there. That file is
   read by every agent and it is currently wrong about where the company's memory lives. Fold it into the
   canonical-remote work in 6.3.5 (both are "the docs still face the old world"), and note that another
   session currently holds uncommitted edits to `AGENTS.md`, so editing it needs its own quiet moment rather
   than a sweep.

---

## 7. EVERY DOCUMENT

| document | what it answers |
|---|---|
| **`docs/mesh/170-MASTER-RECORD-ATTENTION-BADGE-AND-FLEET-AUDIT.md`** | **this file** — the whole session: what was wrong, what changed, the state, what is next |
| `docs/mesh/168-ATTENTION-AUTHORITY.md` | the badge incident in full: the port, the fidelity of every claim, the two follow-on fixes, the lost schedule, the lessons (§7.3 is the crontab incident) |
| `docs/badge/README.md` | the badge as a system: the wire contract, the six rendered states (incl. the frozen-source row), how to verify it, deployment, and **§10** — this incident |
| `packages/plugin-attention-badge/README.md` | the plugin contract: the authorities list, the fallback pill, the failure table with the frozen-source case |
| `assets/phone-badge.js` (header) | why the origin is a list, in the code that implements it |
| `scripts/mesh/sentinel-freshness-check.py` (docstring) | why an absence monitor exists, what it measures, and what it refuses to do |
| `scripts/mesh/168-port-sentinel-to-authority.sh` | the idempotent installer for the kernel port |
| `scripts/verify-badge.js` | the 181 checks, including the frozen-first/live-second case as a test |
| `docs/mesh/169-CLOUD-VS-OFFICE-AUDIT.md` | *another session, same night*: cloud vs office on every metric (which is faster, which is more robust), and the finding that **the rollback anchor has been written to** |
| `docs/mesh/140-PORT-CORE-AND-GAPS.md` §A1 | the port that was prepared on 11 October and never installed — and the sentence *"what would notice its failure: nothing"* |
| `docs/mesh/131-MIGRATION-BRIEF.md` | the estate's standard of success: *"a monitor that reports absence instead of silence"* — the sentence this session implemented |
| `docs/mesh/162-MESH-SYNC-WHAT-MOVED-AND-WHAT-COULD-NOT.md` | where the canonical harness-config remote is (the vault) and what could not move |
| `docs/mesh/166-web-profile-office-references.md` | the class this whole night belongs to: config still facing the old world |
| `AGENTS.md` §5 + `settings/machines/host-posture.tsv` | which machine may be touched, and why the office box is read-only (`142-ANCHOR-WRITE-NOTICE.md`) |
| `packages/plugin-remote-fanout/`, `docs/parallel-agent-orchestration.md` | how the six children were dispatched and how their pressure was routed off this laptop |

---

## 8. EVERY JOURNAL ENTRY FROM THIS SESSION

Written by me on **ZABZ-YOGA** (in this checkout):

| id | kind | one line |
|---|---|---|
| `L3736` | lessons | a moved authority moves its producers; a reading that says "stale" is not a monitor |
| `D3051` | decisions | the findings are computed on the authority; the badge reads a list and takes the freshest |
| `P3133` | pain | nothing alarms when the kernel sentinel dies, and the badge is not that alarm |
| `H3569` | handoff | state of play for the whole session (CHANGED / IN FLIGHT / BROKEN / NEXT / EVIDENCE) |
| `L3742` | lessons | a shared crontab is a read-modify-write, and it will eat your line |
| `P3139` | pain | the authority API waits on its own process-wide database lock ~2.4 times a minute |

Written by the mesh children **on `zabz-tech-linux` and `ZABZ-TECH`** (their own checkouts — see §6.3.5,
the journal is diverged across machines and the entries below are *not* on the authority yet):

| id | machine | one line |
|---|---|---|
| `W2733` | zabz-tech-linux | the currency-math patch: two bundle copies had to be patched, not one |
| `D3034` | zabz-tech-linux | the canonical remote is the vault; `D3035`/`D3036` — the model-failover watch and the app_voice unit resolution |
| `L3506` | zabz-tech-linux | why `autosync` should not be ported to the authority |
| `L3613` / `L3614` | zabz-tech-linux / ZABZ-TECH | the model-failover check's second branch; the lock is a queue |
| `D3037` / `D3038`, `L3617` / `L3618` | zabz-tech-linux | the lane-health gate and the board-seat guard |
| `P2930` / `P2931` | zabz-tech-linux | the vault's broken HEAD (fixed: §4); the write-lock probe is a queue |
| archive entries ×4 | ZABZ-TECH | 2 pain, 1 lessons, 1 wins for the transcript-archive pass |

---

## 9. HOW TO VERIFY ALL OF IT YOURSELF

```bash
# the badge's own reading, from any tailnet machine
curl -s https://secratary-cloud.tail93e6e6.ts.net/dsh-attention.json | head -c 200
curl -s https://secratary-cloud.tail93e6e6.ts.net/dsh-attention.js | grep -o "var VERSION = '[0-9]*'"

# the sentinel and its schedule, on the authority
ssh secratary-cloud 'date -u; ls -l --time-style=full-iso /root/ceo-kernel-var/latest.json; \
  tail -2 /root/ceo-kernel-var/run.log; cat /root/.sentinel-freshness/status.json; \
  for n in run-sentinel sentinel-freshness config-sync-status; do \
    printf "%-20s %s\n" "$n" "$(crontab -l | grep -cE "cron-wrap.sh $n( |$)")"; done; \
  tail -3 /root/.cron-status/runs.tsv'

# the contract test (needs node)
node scripts/verify-badge.js && python scripts/verify-badge-gate.py

# the archive's green light, and what it cannot see
ssh secratary-cloud 'python3 /root/code/harness-config/scripts/transcript-archive-server.py --check; \
  echo "check exit=$?"; \
  python3 -c "
import sqlite3; c=sqlite3.connect(\"/opt/company/archive/lpt-transcripts/manifest.sqlite\")
for r in c.execute(\"select machine, kind, count(*), sum(raw_bytes) from arrival group by machine, kind order by 4 desc\"):
    print(\"%-18s %-16s %7d files %8.2f GB\" % (r[0], r[1], r[2], r[3]/1e9))"'

# the API's own lock
ssh secratary-cloud 'journalctl -u company-api --since "-30min" | grep -c "_db_lock contended"; \
  curl -s -m 60 -o /dev/null -w "models %{http_code} %{time_total}s\n" http://127.0.0.1:8002/v1/models'
```

---

## 10. WHAT I COULD NOT VERIFY, AND THE RISKS I DID NOT CLOSE

1. **I could not see a browser render.** The badge's contract is proved by 181 checks and the live bytes are
   proved by `curl`, but the last link — a human looking at the pill — needs a page reload and your eyes.
2. **The `company-api` fix is unexercised in-process.** The lane-health gate and the board-seat guard passed
   84 + 16 tests and one real routed call in a *fresh* process; the running API still has the old code.
3. **The `_db_lock` holder is unnamed.** I proved the queue, not the thread that holds the key.
4. **The archive's completeness is unverified for every machine except the desktop** (the child's count) —
   the check cannot tell me, which is the finding.
5. **The Mac is unarchived and unmeasured beyond reachability.** Its fix is staged, not applied.
6. **Two of my claims tonight were wrong before they were right**, and both are corrected in the record
   rather than quietly dropped: I read a 39-second cron refusal as a standing fault (`168 §6.5`), and my own
   install of `run-sentinel` was silently deleted by a concurrent edit while I reported it as verified
   (`168 §7.3`, `L3742`). The second is why the monitor now checks the schedule.
7. **The office box still answers the old badge**, and the rollback anchor's state is a separate open
   finding in `169 §4` (it has been written to and is no longer the cutover-point image).

<!-- tags=attention-badge,kernel,sentinel,cutover,audit,master-record,deadman,archive,db-lock refs=131,140,162,166,168,169,L3736,D3051,P3133,H3569,L3742,P3139 -->
