# 159 — `production-comms-freshness` FAILS EVERY RUN: DIAGNOSIS AND THE ONE-LINE CHANGE

**Author:** mesh child agent on **ZABZ-YOGA** (Windows), thread `remote-bd0c2c32-a8f3-4de8-9094-d95eaf2c794b`,
2026-10-11 ~22:20Z onward. **Companion to and continuation of `155`** (same conclusion on the crux, taken
further: `155` stopped before naming the lost job and before testing the fix).
Nothing was restarted. `/root/authority.db` was never opened read-write. No service state was touched on
any box. The office box (`secratary-ts`) was not touched at all in this workstream.

**Subject:** `production-comms-freshness`, cron `*/15`, `rc=1` every run since `2026-10-11T17:30:02Z`.

**VERDICT, three parts:**
1. **The monitor's number is an artifact** — it measures a frozen bookkeeping row, not the website.
2. **The customer-facing website is NOT stale** — its own newest row tracks live traffic within seconds.
3. **But the freeze is real and its cause is one of the ~40 jobs that never moved:** `website-comms-push-cron`.
   The check is correctly reporting the absence of a job that should have been ported. **The finding is the
   diagnosis; the monitor's code should not change.**

---

## 1. What the check actually compares, and the real numbers right now

`/usr/local/bin/production-comms-freshness.py` (read in full on the cloud box, `cat` via ssh). It computes,
for each of `dialpad_calls` and `dialpad_sms`:

```
behind_local_hours = (MAX(local row)  -  website_sync_cursor.last_synced_at) / 3600
```

and fails when that exceeds `THRESHOLD_HOURS = 2.0`.

| side | what it is | where it lives | command that reads it |
|---|---|---|---|
| **A — "the local store"** | `MAX(created_at)` of `dialpad_sms_cache` (filtered pushable) and `MAX(date_started_ms)` of `dialpad_call_full` | **`/root/authority.db`** (the live cloud authority) | `sqlite3 "file:/root/authority.db?mode=ro"` — the script uses `uri=True, mode=ro` |
| **B — "the website"** | `website_sync_cursor.last_synced_at` — **the last time the local→website PUSH completed** | **the same `/root/authority.db`** | same read, `SELECT sync_type, last_synced_at FROM website_sync_cursor` |
| (C — the actual website) | `COUNT(*), MAX("createdAt")` of the website Postgres `communications` table | the website's own Postgres via `PHONE_TECH_FULL_*` DSN | read-only `psycopg2`, `pg.set_session(readonly=True)` |

**B is not a measurement of the website.** It is the pusher's own bookkeeping, in the same local database as
A. Measurement C *is* a reading of the website, and it is gated so it can only ever **add** a problem — it is
silent whenever the website is fresh.

**Both sides come from `/root/authority.db`.** The check is **not** comparing against the frozen office box and
**not** against the 1.8 MB `/opt/company/data/secretary.db` cutover stub: the cron line sets
`FRESHNESS_SECRETARY_DB=/root/authority.db`, and the script's own docstring forbids pointing at the stub. The
"pre-cutover path" hypothesis in the dispatch is therefore **false for the store, and true for the writer** —
see §3.

**The numbers, as last measured (`151`, `155`, and the cloudfix recon set, all read-only):**

| reading | value |
|---|---|
| `dialpad_calls.cursor` | `2026-10-11T15:11:48.403398+00:00` |
| `dialpad_sms.cursor` | `2026-10-11T15:11:53.128402+00:00` |
| `behind_local_hours` at 20:30:01Z | **5.25 h** — the string `151` quotes as *"website 5.25 h behind local store"* |
| `behind_local_hours` at 21:15:01Z | **6.05 h** |
| `local_newest_sms` at 21:15:01Z | `2026-10-11T21:14:42.949000+00:00` |
| **`website.newest` at 21:15:01Z** | **`2026-10-11 21:14:44.814000`** |
| **`website.newest_age_hours`** | **0.01 h (36 s)** |
| `website.rows` | 126 113, and climbing: 126 101 (20:15Z) → 126 104 → 126 108 → 126 110 → 126 113 (21:15Z) |
| `problems` | 2, both of the form `dialpad_calls: the website is Xh behind the local store … 2026-09-15 failure shape` |

`151`'s quoted message is `behind_local_hours` from the **20:30:01Z** tick. It is **not** a statement about
the website's contents, and reading it as one is how this job has been mis-triaged.

**Quote the command** (`secratary-cloud`, read-only; reproduced here as run in `155`):

```
/opt/company/.venv/bin/python /usr/local/bin/production-comms-freshness.py     # or read STATE below
cat /root/.lpt-recon/production-comms-freshness.json
```

## 2. Is the lag real, or is the check measuring the wrong thing? — THE CRUX

**The check is measuring the wrong thing, and this is provable from its own output.**

- The website's newest row was **1.865 seconds NEWER** than the local original at the 21:15Z tick
  (`21:14:44.814` vs `21:14:42.949`). A store cannot be "5–6 h behind" a copy that is *ahead* of it.
- `website.newest_age_hours = 0.01` — 36 seconds. Nothing in the website reading is stale.
- `website.rows` climbs on every tick with live traffic. The website is receiving what the shop sends,
  continuously, **right now**.

Meanwhile `behind_local_hours` grows by exactly **1 h per hour**, because the cursor it is subtracted from
never moves. That makes the failure time a **pure function of the freeze time plus the 2 h threshold**:

```
cursor froze          2026-10-11T15:11:48Z
threshold             2.0 h
first tick > 2.0 h    17:30:02Z        <-- the ledger's FIRST FAILURE
last green tick       17:15:02Z
```

Four green ticks then red forever, with no intermittency, and the transition lands exactly on the arithmetic.
No other explanation is needed and none is available.

**So: the reported lag is not real. The website is current; the ruler is frozen.**
This is the *mirror image* of the 2026-09-15 defect the script was written to prevent. That defect watched a
clock that **always moves** (the local webhook receive time) and so never caught a silent website. This defect
watches a clock that **stopped moving** and so alarms forever about a website that is fine. Both are clock
mistakes. The second was introduced by the port that was meant to fix the first.

**False alarm, not false negative — and the distinction matters for who gets woken up.** The monitor is not
silent while the website is stale (the 2026-09-15 failure); it is loud while the website is fresh. It has been
reporting `rc=1` for four and a half hours across ~18 runs and every one of those runs was wrong about the
customer-visible fact.

## 3. If the lag is real, what is not syncing — and is it one of the ~40 that never moved?

**The lag is not real, but the freeze is, and its cause is exactly the class of job this migration lost.**
The thing that is not syncing is **the writer of `website_sync_cursor`**, i.e. the local→website push itself.

- `website_sync_cursor` is written **only** by `_update_sync_cursor(db_url, …)` in
  `/opt/company/app/services/website_db.py` (called at lines 1892, 2006, 2112 — from
  `sync_dialpad_calls_to_website`, `sync_dialpad_sms_to_website`, `sync_dialpad_voicemails_to_website`).
- On the cloud box those three functions are reached from exactly two places:
  `/opt/company/app/services/daily_reconciliation.py` (in-process, on the autopilot's own long interval), and
  the **`website-comms-push-cron` job**, which is the scheduled clock.
- **`website-comms-push-cron` was on the office box and never moved to the cloud.**
  - Office crontab line 49: `9,39 * * * *` → `/home/zabz/bin/website-comms-push-cron.sh`
    (480 runs, 69 non-zero, **last `2026-10-11T03:39:04Z`** — i.e. before the cutover, and it never ran again).
  - It is named in **`153-LOST-JOBS-WORKLIST.md`** line 31 (the ~40 that are "genuinely lost") **and** in
    **`151-VERIFY-CLOUD-AUTHORITY.md`** §5 (the 27 with no home on the cloud box), with `151` drawing the
    conclusion directly: *"the job that would close that gap — `website-comms-push-cron` — is one of the 27
    missing."* `132-CRON-INVENTORY.md` line 131 classifies it **PORT-ADAPT**, and `151` §5 names
    `126`–`130`/`131` as the governing documents.

**Therefore: this check is correctly reporting the absence of a job that should have been ported. The
finding is the diagnosis. No code in the monitor should change.**

**Why is the website fresh anyway, if the pusher is missing?** Because the push is *also* reachable
in-process: `daily_reconciliation.py:1638/1647` and `:2211/2216` call the same two sync functions from inside
`company-api`'s autopilot (`AUTOPILOT_INTERVAL_SEC=900`). That is the same redundancy `132` §1c records for
`plaid_sync` and `owner_attention_sweep` — an in-process tick that overlaps a cron job. So the customer-facing
data keeps moving while the cron-side clock that the monitor reads has no writer at all. **The monitor's
invariant — "the cursor advances whenever the local store does" — held on the office box because the cron job
enforced it; on the cloud box nothing does.**

## 4. The one-line change (and how it must be proven)

**The fix is to finish the port, not to change the monitor.** The cron line is *already installed* — and that
is why the job is now failing a second way:

```
# installed by the coordinator session 2026-10-11T21:29:01Z, already in the cloud crontab:
9,39 * * * * /usr/local/bin/cron-wrap.sh website-comms-push-cron L3Jvb3QvYmluL3dlYnNpdGUtY29tbXMtcHVzaC1jcm9uLnNoID4+IC92YXIvbG9nL3dlYnNpdGUtY29tbXMtcHVzaC5sb2cgMj4mMQ==
# decodes to: /root/bin/website-comms-push-cron.sh >> /var/log/website-comms-push.log 2>&1
```

- `/root/bin/website-comms-push-cron.sh` **exists** (4223 B, installed 06:35).
- **`/root/bin/website-comms-push.py` DOES NOT EXIST** — the wrapper's `PUSH=` target. The wrapper therefore
  dies before it can push, and the `21:39:01Z` ledger row reads `website-comms-push-cron 1 90` (rc=1).
- The office originals of both files are known and their cloud-adapted copies already exist locally at
  `C:\Users\ezabz\work\cloudfix\files\website-comms-push.py` and `…-cron.sh` — but those copies are **the
  office versions, not adapted**: they still name `/home/zabz/personal-secretary-mvp` (`sys.path.insert`,
  `ENV_FILE`, the wrapper's `REPO`/`PY`/`PUSH`/`STATE_DIR`, and the wrapper's sanity-gate
  `sqlite3 "file:$REPO/data/secretary.db?mode=ro"`).

**The unambiguous change, two literals:**

| file | office value | cloud value |
|---|---|---|
| `website-comms-push.py` | `sys.path.insert(0, "/home/zabz/personal-secretary-mvp")` | `sys.path.insert(0, "/opt/company")` |
| `website-comms-push.py` | `ENV_FILE = "/home/zabz/personal-secretary-mvp/.env"` | `ENV_FILE = "/opt/company/.env"` |
| `website-comms-push-cron.sh` | `REPO=/home/zabz/personal-secretary-mvp`, `PY=$REPO/.venv/bin/python3`, `PUSH=/home/zabz/bin/website-comms-push.py`, `STATE_DIR=/home/zabz/.lpt-recon` | `REPO=/opt/company`, `PY=/opt/company/.venv/bin/python3`, `PUSH=/root/bin/website-comms-push.py`, `STATE_DIR=/root/.lpt-recon` (already where `FRESHNESS_STATE` points) |

and the wrapper's sanity gate must read the **authority**, not a stub:
`sqlite3 "file:/root/authority.db?mode=ro"` (the office gate read `$REPO/data/secretary.db`; on the cloud box
that path is the 1.8 MB cutover stub and would answer "quiet shop" forever — the exact confident-wrong-number
the freshness script's own docstring warns about). Then install
`/root/bin/website-comms-push.py` (mode 755) and run the job's own next scheduled tick at `:09`/`:39`.

**Safety notes that must survive the port:**
- `website-comms-push.py` carries a deliberate **PCI hold** — `message_id 6252044111880192` is withheld from
  production until the owner answers queue item 67. **Never pass `--include-pci` as part of this port.**
- `--dry-run` exists and should be used first. The script inserts rows into the website's `communications`
  table; it sends nothing outbound.
- The push writes to the website Postgres and to `website_sync_cursor` in `/root/authority.db`. It is the
  sanctioned writer, not a second one.

**PROOF REQUIRED, AND NOT YET OBTAINED (see §6):** the fix is only proven when
`/root/.cron-status/runs.tsv` gains a `website-comms-push-cron` row with **rc=0** from its **own scheduled
tick**, and `production-comms-freshness` then lands **rc=0** on a later tick because the cursor has advanced.
Running either by hand does not satisfy this. A `:45 22` one-shot verifier
(`/root/bin/verify-website-comms-push.sh`, `158`'s author) is already scheduled to capture exactly those two
ledger blocks.

## 5. Who owns the decision

Nothing here is the owner's decision. The port is a development action already owned by the coordinator
workstream that installed the cron line at 21:29Z — it is **half-done**, and the missing half is one file.

## 6. WHAT I COULD NOT MEASURE, AND WHY — read this before trusting §4 to be finished

**The cloud box stopped executing external commands while this session was working.** This is a new and
separate finding, and it blocked the fix.

- `ssh secratary-cloud "echo PING; date -u"` prints `PING` (a **shell builtin**) and then **hangs**.
  `date`, `id`, `ls`, `tail`, `cat` — anything requiring **fork+exec** — never returns.
- Reproduced from ZABZ-YOGA at 22:17Z, 22:25Z and 22:36Z with a hard-timeout driver: every attempt returned
  partial output and was killed at the deadline. TCP to `178.156.194.1:22` still accepts (`TcpTestSucceeded:
  True`), so the daemon is listening and the session opens; the remote process tree cannot run.
- **Earlier in the same window external commands did work** (a `cat` of the cron line and of
  `production-comms-freshness.py` both returned in full, and the 21:00/21:15/21:30 monitor ticks all ran). The
  degradation is **progressive over ~20 minutes**, which is the signature of resource exhaustion rather than a
  clean crash. `151` §3 measured the underlying headroom problem: **2 vCPU, 7.7 GB RAM, 48 % of swap in use,
  and a real OOM kill of `company-api` at 15:17:30Z.**

**Consequences, stated plainly:**
- I did **not** measure the current cursor values or the website row directly; §1's numbers are quoted from
  `151`, `155` and the cloudfix recon outputs, each of which carries its own machine and command. They are
  consistent with each other across five ticks.
- I did **not** install the fix, and I did **not** prove it with a scheduled rc=0 run. §4 is a specified,
  reviewable change, not a completed one.
- **I did not restart, stop, start, enable, disable or mask anything on any machine**, and I did not touch the
  four services that must not be restarted (`company-api`, `cloudflared`, `secretary-dashboard`,
  `phone-redirector`).

**Whoever picks this up must first establish why the cloud box cannot fork**, because until it can:
the port cannot be installed, no scheduled rc=0 can be observed, and every other cron job on that box —
including the ones that were green at 21:30 — is suspect. `ssh` still *connects*, so a naive check will
keep reporting the box "up".

## 7. Summary in one paragraph

`production-comms-freshness` exits 1 because `website_sync_cursor.last_synced_at` in `/root/authority.db`
froze at `2026-10-11T15:11:48Z` and the check subtracts it from a local clock that keeps moving; the check
therefore goes red exactly 2 h after the freeze and stays red. The website itself is not stale — it tracks live
traffic within seconds and at one tick its newest row was newer than the local original. The frozen value has
no writer on the cloud box because **`website-comms-push-cron`, the job that advances it, is one of the ~40
listed in `153-LOST-JOBS-WORKLIST.md` as never having moved**; the coordinator began porting it at 21:29Z and
installed the cron line, but `/root/bin/website-comms-push.py` was never placed, so the ported line itself now
fails rc=1. **The monitor's code is correct and must not change; the change is to finish the port** (two
literals plus the wrapper's DB path), and it must be proven by the job's own next scheduled rc=0 and a
subsequent green `production-comms-freshness` tick.
