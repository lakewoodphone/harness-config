# 188 — SYSTEM AUDIT AND FIXES: the cloud authority, 2026-10-12

**Audit seat:** `zabz-tech-linux` (Linux 6.8, user `zabz`), reached over the tailnet.
**Target audited:** `secratary-cloud` — the company authority (`100.73.176.126`, Hetzner
`178.156.194.1`), Hetzner CCX23: **4 vCPU, 15.6 GB RAM, 75 GB NVMe**.
**Access:** `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`. The estate mesh key
(`id_ed25519_mesh`) is refused by the authority for every user tried (`root`, `zabz`,
`ezabz`, `ubuntu`) — the same shape as journal `P2944`/`P2946`/`P3003`/`P3005`.
**Window:** 2026-10-12 16:20–16:55Z. **Continued 16:35–16:52Z** by a second
dispatch on the same thread, from the same seat, which re-verified every fix below and
landed one more (F10, the `db_contention` borrowed-connection defect); see §4 and §6.
**Constraints honoured:** no service state, crontab line, timer or host configuration was
changed; `company-api` was not restarted; `/root/authority.db` was opened only as
`file:…?mode=ro` (or through the app's own `connect_db`); scratch files are under `/tmp`.

> **Honesty note on "you are on secratary-cloud".** The brief placed this audit on
> `secratary-cloud`. The shell I was given ran on **`zabz-tech-linux`**; I did not
> pretend otherwise. The audit *target* is the authority and it is reachable, so the work
> was done there remotely.

---

## 0. HEADLINE

| | |
|---|---|
| **findings** | **15** (F1–F15) |
| **fixed and verified** | **4**: `liveness` (F1), `db_writable` (F2), identity-store unbounded growth (F8), `db_contention` closed-on-handout (F10, landed in the continuation) |
| **already fixed before this session** | 4: the two dialpad jobs, `cron-script-guard`'s blind decode, `report-offsite-age`'s exit-0-while-broken duplicate |
| **not fixable by code alone** | `guard-registry` (F5, owner approval + crontab), `owner_queue`/`attention_debt` (owner), `config_sync` divergence (F4, publish decision), `phone_endpoint` (F6, missing probe), FTS `_content` duplication (F15, schema migration) |
| **worst single defect** | `personality.narrative` held **277,734** entries / **22.6 MB** with no cap — 68 % of a 33.4 MB store; a stat-keyed cache added the same day hid the read cost but nothing bounded the growth (F8) |
| **biggest live error source** | `db_contention` "closed on handout": **469 rows in 48 h**, but **415 of them are one 2-minute burst** at 2026-10-12T13:57Z from `GET /api/v1/comms/active-phones` — not a steady rate (F10) |
| **biggest measured reclaimable space** | the FTS5 **`dsh_session_events_fts_content` table is 8.79 GB of duplicated `raw` text** — 36 % of the 22.95 GB database (F15) |

The two checks the brief names as broken (`liveness`, `db_writable`) were **already fixed in
the working tree** of `/root/ceo-kernel` when this session arrived, uncommitted. I verified
them against live data, ran the kernel's own tests, and **committed** them
(`/root/ceo-kernel` @ `91c6f2e`). I did not re-implement them; rule 0 of this estate is
*prove it does not already exist*.

**Continuation re-verification (16:35Z).** Independently re-read on the authority:
`ck/sentinel.py:448` `LIVENESS_MAX_AGE_SECONDS = 4 * 3600.0` and the real
`_age_seconds(pkt.value)` at `:491` (no `or 0`); `ck/sentinel.py:2323/2328`
`DB_WRITE_PROBE_SECONDS = 6.0` / `DB_WRITE_CONFIRM_SECONDS = 60.0` with the confirming
re-probe at `:2392`; `app/identity_store.py:5428-5432` carries the five history caps and
`_enforce_history_caps` is called from the write path at `:2123`. The live
`latest.json` (16:35:04Z) reports **4 non-ok** (`agent_dead_weight`, `attention_debt`,
`owner_queue` HIGH; `phone_endpoint` MEDIUM) — `liveness` and `db_writable` are green
because they now measure the right thing.

The continuation's own new fix is **F10**, §4: the `db_contention` "closed on handout"
noise is a real defect — `unified_comms._conn()` handed back the cached per-thread
connection to three callers that close it. It is fixed in `/opt/company` @ `98c0595b`.

---

## 1. THE SERVICE'S OWN FINDINGS — `~/ceo-kernel-var/latest.json`

Generated `2026-10-12T16:20:04Z`, host `secratary-cloud`, 19 checks, **5 non-ok**:
`agent_dead_weight`, `attention_debt`, `config_sync`, `owner_queue` (all HIGH) and
`phone_endpoint` (MEDIUM).

### F1 — `liveness` printed a constant  ✅ FIXED (committed `91c6f2e`)

* **Was:** `ck/sentinel.py` — `age = pkt.data_age_seconds or 0`. `sources.scalar` leaves
  `data_age_seconds` `None` for a raw SQL scalar, so `None → 0`, `pkt.stale` was always
  `False`, and the check could not go stale at *any* age. `170 §5.1` measured it saying
  *"0.0m ago"* against a true age of 3,059 s.
* **Fix shape (from `170 §5.1`):** parse the age from the returned timestamp and derive the
  threshold from the real tick-gap distribution.
* **After:** `LIVENESS_MAX_AGE_SECONDS = 14400` (240 min), derived from the measured
  tick-**batch** gap distribution (14-day p99 = 123.5 m, 30-day max = 1414.5 m).
* **Evidence (this session, direct invocation):** `newest_tick 2026-10-12T15:45:04Z`,
  `age_seconds = 2462.0`, `max_age_seconds = 14400.0` — and the running report agrees
  (`age_seconds: 2097.7`). Before, the same field was `0`.

### F2 — `db_writable` escalated on a 6-second probe  ✅ FIXED (committed `91c6f2e`)

* **Was:** a single `BEGIN IMMEDIATE` with a 6 s budget; a miss returned HIGH
  *"the authoritative database refuses writes"*. `170 §5.2` measured **30/30** acquires
  succeeding at 25 s (worst wait 9.0 s); the box logged 3 real `database is locked` events
  in 24 h. The lock is *contended, never stuck*.
* **After:** the cheap 6 s probe settles the ordinary case; on a miss a **60 s** confirming
  re-probe runs before anything escalates. A miss that is acquired at, say, 9 s is now
  MEDIUM "contended, not stuck" with both timings recorded.
* **Evidence:** `_db_write_probe` acquired in `0.00 s`; constants
  `DB_WRITE_PROBE_SECONDS=6.0`, `DB_WRITE_CONFIRM_SECONDS=60.0`; kernel tests pass.

### F3 — `agent_dead_weight` (HIGH, open)

`frontier_risk_board`: **30 ticks, 0 completions (0.0 %)** in 14 d (threshold 2 %). Real
but not yet repaired or retired — the same shape as five already-retired indexers named in
the same finding. **Not fixed** (a product/retirement decision; see §8).

### F4 — `config_sync` (HIGH, open)

`local main is 31c650a but root@2.28.33.58:/srv/git/harness-config.git refs/heads/main is
1a5c2fe; the canonical checkout is not published`. The authority is **diverged** from the
canonical harness-config remote. **Not fixed** — publishing a foreign ref is a
repository/ownership decision, not a code repair.

### F5 — `guard-registry` rc=2 on **every** run (100 %, 128/128) — the guard system is dead

* `/root/bin/guards.yaml` does not exist; `/root/.guard-registry/status.json` does not exist.
* `157-DIAGNOSIS-TWO-FAILING-JOBS.md` already proved this is a **config artifact lost in the
  cutover**, whose office bytes hash to exactly the checker's `BOOTSTRAP_REGISTRY_SHA256`
  (`91ea7699…`). Fixing it is **deliberately gated on an owner approval record**
  (`guards.approval.json`, owner row 227) plus a crontab flag
  (`--ledger-db /root/authority.db`). Installing the ported file alone converts rc=2
  ("cannot read inputs") into rc=1 ("guard system tampered") — worse for the same missing
  file. **Not fixed, on purpose:** the approval is the owner's act and the crontab is out of
  bounds for this audit. This is correctly a red light, not a green one.

### F6 — `phone_endpoint` (MEDIUM, open)

Gate (`:3086`) and engine (`:3089`) are listening and `serve` publishes the port, but there
is **no fresh end-to-end probe result**. The check can see the sockets, not that a call
works. **Not fixed** — there is no probe job to repair; one has to be built.

### F7 — `attention_debt` / `owner_queue` (HIGH, open)

`attention_debt`: oldest held question 193.5 h; 7 held, none critical/urgent.
`owner_queue`: **160 actively waiting** owner decisions, next `#228` (11.1 d, BLOCKING,
"the business is taking ~4,500/month out of your personal accounts"). These are the owner's
queue by construction. **Not fixed** (not an engineering defect).

---

## 2. CRON AND TIMER HEALTH

Source: `/root/.cron-status/runs.tsv`, re-read in the continuation: **5,947 rows**,
2026-10-11T06:32Z → 2026-10-12T16:39Z.

| metric | first pass (16:24Z) | continuation (16:39Z) |
|---|---|---|
| non-zero rows, whole ledger | 720 / 5,896 = 12.2 % | **722 / 5,947 = 12.1 %** |
| non-zero rows, last 24 h | 515 / 4,574 = 11.3 % | **512 / 4,595 = 11.1 %** |
| non-zero, since 2026-10-12T00:00Z | — | **314 / 3,398 = 9.2 %** |
| wrapped cron lines (`cron-target-guard` decodes) | 33 | 33 |
| custom systemd timers | all `Result=success`; `systemctl --failed` empty | unchanged |

**Worst offenders (last 24 h):**

| job | non-zero / runs | rc now | cause, from the ledger / own log |
|---|---|---|---|
| `cron-target-guard` | 228 / 287 | **0** | last FAIL 16:10Z; **clean 16:15→16:35Z** (28 targets, 12 critical paths, `ok:true`). The mass failure was a transient **FAIL with every finding list empty** (§3, F12) |
| `guard-registry` | **96 / 96** | **2** | `/root/bin/guards.yaml` missing (F5); still 100 % every run |
| `dialpad-recording-gap` | 60 / 24 h | 0 | **0 failures since 00:00Z** (the 60 are all before midnight) — fixed by moving `SECRETARY_DB=` into the job's environment (doc `156`) |
| `ai-gateway-health` | 48 / 48 | **3** | by design: all findings are CONDITIONs; `tier-collapse` + `unattributed-calls` (`app/code_self_edit.py` logs `model=unknown`). rc=3 is the checker's "condition, not fault" code |
| `dialpad-transcript-gap` | 30 / 24 h | 0 | **0 failures since 00:00Z** — same fix |
| `production-comms-freshness` | 22 / 96 | 0 | intermittent during the harvest window; latest runs `fresh` |
| `website-comms-push-cron` | 10 / 37 | 0 | intermittent; own log empty, reason on stdout |
| `authority-repo-push` | 2 / all-time | **0** | **F13 WITHDRAWN** — crontab line 52 is base64-wrapped
(`L3Vzci9sb2NhbC9iaW4vYXV0aG9yaXR5LXJlcG8tcHVzaC5zaA==` → `/usr/local/bin/authority-repo-push.sh`) and the last run 06:00Z was rc=0; the two rc=2 rows predate the fix |

**Timers (18):** `authority-offsite-backup`, `authority-data-offsite`, `authority-deadman`,
`authority-report-offsite-age`, `estate-monitor`, `company-outcome-monitor`,
`transcript-archive-pull` all last `Result=success, status 0`. The previously-reported
`report-offsite-age` duplicate crontab line is gone (systemd timer only).

---

## 3. DISK, MEMORY, AND THE UNBOUNDED IDENTITY STORE

### 3.1 Disk — not immediately critical, but trending down

| reading | first pass (16:30Z) | continuation (16:42Z) |
|---|---|---|
| `df -h /` | 75 G total, **56 G used, 16 G avail, 79 %** | 75 G total, **63 G used, 9.1 G avail, 88 %** |
| `disk-guard` | 74.9 %, 15.7 GB free; warn 90 %, crit 95 % | (guard not re-run; `df` says 88 %) |
| growth, full guard window (31.9 h) | **+13.7 pts / −10.2 GB free ≈ 7.7 GB/day** | — |
| growth, **last 6 h** | **+0.5 pts / −0.40 GB free ≈ 1.6 GB/day** | 50 s sample: 64,336 → 64,360 → 64,183 MB used (**fell 180 MB**) |
| `/root` | 27.2 GB (the 24.6 GB DB dominates) | **31 GB** (DB 24.6, `work/lpt-hub` 3.6 incl. a 1.6 GB pack written 16:40Z, `.fsearch` 0.2) |
| `/opt/company` | 21 GB — `data` 12.7 (google_voice_profiles 6.8, chromadb 2.9, mem0 1.1), `archive/lpt-transcripts` 6.3, `.venv` 1.5 | **25 GB** — `data` 13 (chromadb 2.4, mem0 1.1, google_voice_profiles), `archive/lpt-transcripts` **9.0** (`objects` 6.2, `incoming` 2.8 staging), `.venv` 1.5 |
| DB growth | 24,232,910,848 B (03:47Z) → 24,608,387,072 B (16:30Z): **≈ 0.7 GB/day** | 24,638,205,952 B (16:34Z) |
| archive growth | 4.1 GB (`151`, 2026-10-11 20:39Z) → 6.3 GB | → **9.0 GB**, hourly `transcript-archive-pull` |

The 79 % → 88 % move in ~12 minutes is **not** a runaway writer: it is the hourly
transcript-archive pull (archive `objects` +2.7 GB) plus a 1.6 GB `lpt-hub` git pack another
actor wrote at 16:40Z, and the archive's `incoming/` staging tarball
(`zabz-tech.tar`, 2.89 GB) is deleted after ingest — the 50-second sample shows used space
*falling* as staging is reaped. The trend is still the concern: **9.1 GB free is ~6 days at
1.6 GB/day and ~1 day at the 7.7 GB/day guard-window average**, so the 90 % warn is
reachable today. `incoming/.unpack-*` leftovers are 9 empty 4 KB dirs (harmless); no stale
bulk data was found in `incoming` beyond the active staging tarball.

### F9 — disk and DB growth trend (open, no code fix)

The two consumers that move the needle are the **database (~0.7–1.0 GB/day)** and
**`archive/lpt-transcripts` (6.3 GB → 9.0 GB in ~15 min of ingest)**. There is no retention
defect to repair: `disk-guard` reports `backup_dirs: 0` and the offsite backup streams
without staging a local copy. The finding is that **only 9.1 GB is free** and the 90 % warn
is reachable today — measured, not inferred.

### 3.2 The database — **`VACUUM` reclaims ~0.0 %; `dbstat` measured** (not guessed)

```
page_size=4096  page_count=6,007,004  freelist_count=119  auto_vacuum=0
db bytes           = 24,604,688,384  (16:30Z)
free (reclaimable) = 119 * 4096 = 487,424 B  =  0.0 %
WAL                = 67,108,864 B (auto-checkpoint 1000)
```

So there is **no free-page bloat to vacuum away**; `VACUUM` would free ~0.5 MB and needs
~24 GB scratch (we have ~9 GB) — it must not be run.

**The `dbstat` breakdown the first pass could not finish (F15).** A second, `nice -n 19
ionice -c3` run completed in ~6 minutes over the 24.6 GB file. `dbstat` reports **637
b-trees, 22.95 GB total**; the distribution is extraordinarily concentrated:

| b-tree | bytes | share | rows/cells |
|---|---|---|---|
| `dsh_session_events` (base table) | **8,890,896,384** | 36.1 % | 1,955,013 rows |
| `dsh_session_events_fts_content` | **8,790,097,920** | 35.7 % | 2,515,338 |
| `dsh_session_events_fts_data` (FTS index) | **3,609,485,312** | 14.6 % | 1,772,103 |
| `sqlite_autoindex_dsh_session_events_1` | 129,482,752 | 0.5 % | 1,955,013 |
| `idx_dsh_session_events_seq` | 129,384,448 | 0.5 % | 1,955,013 |
| `procedural_experiences` | 606,044,160 | 2.5 % | 37,007 |
| `dialpad_stats_record` | 367,304,704 | 1.5 % | 268,342 |
| `memory_vectors_vector_chunks00` | 302,387,200 | 1.2 % | 95 |
| `gateway_trace_span` | 162,217,984 | 0.7 % | 617,076 |
| `work_sessions` | 148,635,648 | 0.6 % | 106,066 |
| **all other 627 b-trees** | **~1.36 GB** | 5.9 % | — |

**F15 — the single largest reclaimable object is a duplicated FTS copy, not stale rows.**

* The FTS table is default-content: `CREATE VIRTUAL TABLE dsh_session_events_fts USING
  fts5(source_machine UNINDEXED, session_id UNINDEXED, ordinal UNINDEXED, raw)`. FTS5 with
  no `content=` option materialises a **second full copy of every `raw` value** in
  `dsh_session_events_fts_content`. The base table's own `raw TEXT NOT NULL` column already
  holds it (`SELECT length(raw)` and `SELECT length(c3)` both returned 96 for the first row).
* **8.79 GB (35.7 % of the database) is therefore pure duplication**; rebuilding the FTS as
  an external-content index (`content='dsh_session_events'`) would remove it, leaving the
  index in `_fts_data` (3.61 GB). The base table + FTS is **~21.3 GB = 93 % of the database**.
* **Not applied.** It is a schema migration that rebuilds a 12 GB index on the live sole
  writer — owner/change-window territory, not a safe in-place fix. It is the measured answer
  to "how much could be pruned", and the answer is *the duplication, not dead rows*.
* Retention is a second, separate lever: `dsh_session_events` is the archive projection
  (AGENTS.md §1 says sessions are kept forever) and no retention defect was proven, so no
  row was deleted. Row count **1,955,013**.


### F8 — `data/agent_identities.json`: one record is growing without bound  ✅ FIXED in source (not live)

* **Measured:** file **39,354,486 B / 126 agents**, `updated_at` rewritten every few minutes.
  `orchestrator` alone is **5,477,592 B**; across all 126 agents the field sizes are:
  * `personality.narrative` — **277,734 entries, 22,586,727 B (22.6 MB)** ← the growth
  * `memory` — 11,799 entries, 3,897,861 B (already capped at 300/agent)
  * `identity_proposals` — **11,528 entries, 2,951,451 B**, *every one* `pending_owner_input`
  * `identity_notes` — **18,836 entries, 2,238,320 B**
  * `hierarchy.stewardship.notes` — 6,988 entries, 459,185 B
  * `voice_history` — 1,957 entries, 37,523 B; `name_history` — 693 entries, 9,289 B
* **The cache that hid it:** commit `17febcd5` (2026-10-12) added a stat-keyed `_load` cache
  ("a 37.5 MB JSON file was re-read and re-parsed on every request"), taking p50 from
  972 ms → 857 ms. It removes the *read cost*; **nothing bounds the file itself**.
  `_enforce_memory_cap` caps `memory` at 300; `personality.narrative` is appended at
  `identity_store.py:5317` with **no cap**, and the identity/proposal/notes/history lists have
  none either.
* **Fix applied** (`/opt/company/app/identity_store.py`, commit **`4d6a606c`**, backup
  `/tmp/identity_store.py.bak-20261012T162944Z`): a new `_enforce_history_caps()` caps
  `personality.narrative` at 500, `identity_proposals` at 500, `identity_notes` at 500,
  `voice_history` at 100, `name_history` at 100 — keeping the **newest** entries — and is
  called from the single write path `_save()` so it holds on every persistence pass.
  `sha256 f326a285… → 8a7defa6…`, `py_compile OK`.
* **Verified on a copy of the live store** (first pass), and **independently re-run in the
  continuation at 16:39Z** by importing the shipped `_enforce_history_caps` and applying it
  to the then-live file: **231,944 narrative + 11,028 proposal + 3,207 note + 1,732 voice +
  462 name entries** pruned, freeing **22,121,308 B = 21.10 MB (66.3 %)** of the 33,389,854 B
  serialised store; a second pass prunes 0 (idempotent). The live file was 39,354,636 B on
  disk with `personality.narrative` = **277,734 entries / 22,586,727 B** across 126 agents
  (recursive field measurement).
* **Not yet live:** `identity_store.py` is loaded by `company-api`; the cap only executes on
  the service's next write after a restart. **`company-api` was not restarted** (per the
  brief), so the live file is still 39.35 MB. The fix is applied, compiled and tested, not
  in effect.

### 3.3 Memory — no longer the binding constraint

`free -m`: **15,605 total, 4,022 used, 11,431 buff/cache, 11,582 available; swap 8 MB used
of 4,095.** Docs `170`/`175` describe a 7.7 GB box at 4.5 GB RSS with 2 GB of swap in use
and a real OOM kill. The instance is now **16 GB** (the owner's resize happened); swap is
effectively untouched. Memory is **not** a current finding.

---

## 4. ERROR LOGS

Source: `error_log` (2,494 rows, 1,196 unresolved all-time) and the journal.

**The `db_contention` line, re-measured by minute (continuation).** The first pass read
"461 in 24 h" as a steady rate. It is not: per-hour grouping of all 1,034 `db_contention`
rows shows **417 in the 13:00Z hour**, of which **415 are at 13:57:45–13:58:xxZ**; every
other hour in the 2-day window holds 1–4. The background rate is **~1/hour**, and the
"loudest error in the log" was one incident.

| window | rows |
|---|---|
| all-time `db_contention` | 1,034 (`closed_on_handout` 845, `other` 156, `leaked_transaction` 31, `closed_in_use` 2) |
| 48 h ending 16:39Z | 469 |
| 2026-10-12T13:00Z hour | 417 |
| 2026-10-12T13:57–13:58Z | **415** |
| any other hour, last 48 h | 1–4 |
| last 30 min before the fix (16:12–16:39Z) | **1** (16:23:42Z) |

### F10 — `unified_comms._conn()` closed the cached per-thread connection  ✅ FIXED (not live)

* **Root cause (new).** Every `closed_on_handout` row in the burst is
  `site=app/database.py:_get_conn` / `closed by explicit_close_by_owner`. The journal for
  the burst names the source: `company-api` (pid 1084) logged ~415 `DB connection for
  sqlite:////root/authority.db:128919727059456 was closed by explicit_close_by_owner;
  reconnecting` lines interleaved with ~415 `GET /api/v1/comms/active-phones` (127.0.0.1)
  200s. `app/services/unified_comms.py:_conn()` returned `app.database._get_conn(...)` —
  the cached per-thread connection that callers MUST NOT close (`database.py:1090`) — but
  all three callers close it in a `finally` (`:1831`, `:2093`, `:2343`, including
  `list_active_customer_phones`, which that endpoint calls). Each request closed its
  thread's connection; the next request on that thread reconnected and logged a row.
  The first pass's diagnosis (idle-TTL vs. live owner) was the wrong path: the live TTL
  loop already skips live owners (`database.py:1276`); the closer was the caller.
* **Fix.** `_conn()` now returns an **owned** `app.database.connect_db(...)` connection —
  the documented precedent from `owner_attention_sweep.py:42`. `/opt/company` @
  **`98c0595b`**, backup `/tmp/unified_comms.py.bak-188-20261012T163708Z`,
  `sha256 4ea779c1… → e8a16a2f…`, `py_compile OK`.
* **Measured before/after** (live `/root/authority.db`, two calls on one thread, the app's
  own `_record_contention` captured):
  * **before:** `call2 events=['closed_on_handout']`
  * **after:**  `call2 events=[]`, rows identical (`5/5`, first phone `8456712943`)
* **Not yet live:** the running process started 14:14:39Z and loaded the old module;
  `company-api` was **not** restarted. Cron jobs importing `unified_comms` pick it up on
  their next run. Until a restart the endpoint keeps churning.
* The *load* side — ~3.5 req/s of a heavy 60-day `GROUP BY` from localhost — is a client
  polling loop; only the server closing a borrowed handle is fixed here.

Secondary genuine defects in the log, unfixed and reported: **stripe package not installed**
(1), **ghost_agent** (tasks assigned to ids absent from the identity store, 5 in 24 h),
**wo_failure_streak** on seed work orders.

---

## 5. GREEN LIGHTS THAT MEASURE THE WRONG THING

| surface | says | truth | verdict |
|---|---|---|---|
| `liveness` | "ticking" at any age | age forced to 0 by `or 0` | **was green, fixed (F1)** |
| `db_writable` | "refuses writes" (HIGH) | 30/30 acquired at 25 s | **was red, fixed (F2)** |
| **`db_contention` / `error_log`** | the unresolved-error view is quiet (every row is written `resolved=1`, `resolution='…auto-reconnect'`) | 415 rows in one 2-minute burst were a real caller defect that the resolution field pre-labels as "handled" | **green because it resolves itself, not because it is fixed** — root-caused and fixed (F10) |
| **`authority-repo-push`** | (was reported red) | crontab line 52 *is* base64-wrapped now (`…L3Vzci9sb2NhbC9iaW4vYXV0aG9yaXR5LXJlcG8tcHVzaC5zaA==` → `/usr/local/bin/authority-repo-push.sh`); latest run 06:00Z rc=0 | **not a current defect** — the earlier rc=2 rows were pre-fix; F13 withdrawn |
| **`lpt-deploy-drift`** | `VERDICT: IN SYNC`, fetch `True` | simultaneously prints `dirty files: 137 <-- unpushed local edits` — the running API is not any committed revision | **green ignoring the thing that matters**; verdict logic tracks only ahead/behind, deliberately (its own docstring). Reported, not changed |
| **`agent_identities.json` cache** | requests are fast | the file grew to 39.35 MB / 22.6 MB of it a single unbounded list | **cost hidden, growth unexplained**; fixed (F8) |
| **`cron-target-guard`** | `FAIL` with `missing=[] unreadable=[] not_executable=[] crit=[]` (15:50–16:10Z) | a failure verdict carrying **no finding at all** | observed transient, self-resolved to `ok`. Reported; not reproducible to fix |
| `guard-registry` | (red, not green) | the guard system has been dead 128/128 runs | correctly red, owner-gated (F5) |
| `session_archive` | `ok:true`, 4 machines shipping | now **does** list `contact_unmeasured_machines` (`lakewooechsmini`, `mac`) — improved since `170 §5.3` | improved; noted |
| provenance `age=?` | every DB-backed check | `sources.scalar` cannot age a raw scalar; only `liveness` writes its age back | systemic; not fixed beyond `liveness` |

---

## 6. FIXES APPLIED AND VERIFIED

| # | fix | where | before → after | live? |
|---|---|---|---|---|
| F1 | `liveness` real age + measured 240-min threshold | `/root/ceo-kernel` commit **`91c6f2e`** | `age=0` (always) → `age=2462 s`, `max=14400 s` | **yes** (cron reads the working tree) |
| F2 | `db_writable` 60 s confirming re-probe | same commit | 6 s miss → HIGH; now 6 s + 60 s confirm, MEDIUM if acquired | **yes** |
| F8 | identity-store history caps | `/opt/company/app/identity_store.py`, commit **`4d6a606c`** (backup `/tmp/identity_store.py.bak-20261012T162944Z`) | 33,389,854 B → **11,268,546 B** projected (−22.12 MB, −66.3 %) | **no — needs a `company-api` restart, which was not performed** |
| **F10** | `unified_comms._conn()` returns the cached per-thread connection to three callers that close it → `closed_on_handout` burst | `/opt/company/app/services/unified_comms.py`, commit **`98c0595b`** (backup `/tmp/unified_comms.py.bak-188-20261012T163708Z`) | 2-call test: `events=['closed_on_handout']` → `events=[]`; 415-row burst was the live form | **no — same restart; cron importers pick it up next run** |

**Already fixed before this session** (verified, left alone): `dialpad-recording-gap` /
`dialpad-transcript-gap` (0 failures since 00:00Z; the fix was moving `SECRETARY_DB=` into
the job environment, doc `156`), `cron-script-guard`'s blind decode (now
`decoded=33, undecoded=[]`), and the duplicate `report-offsite-age` crontab line.

**Not touched:** services, crontab, timers, host configuration, `/root/authority.db` (read-only).

---

## 7. NOT FIXED, AND WHY

* **F5 `guard-registry`** — needs the owner's approval record (row 227) and a crontab flag;
  both out of bounds. Installing the port without them makes it redder.
* **F4 `config_sync`** — the authority's `harness-config` main diverges from the canonical
  remote; publishing is an ownership decision.
* **F3 `agent_dead_weight`** — retire or repair `frontier_risk_board`; a product call.
* **F6 `phone_endpoint`** — no probe exists to repair; one must be written.
* **F7 `attention_debt`/`owner_queue`** — the owner's queue.
* **F11 `_db_lock` serialisation** (`170 §5.4`) — the maker of the *background* contention
  (1–4 rows/hour); a stack dump inside a stalled request is still the next measurement, not
  a fix. The 2026-10-12T13:57Z burst is F10, now fixed.
* **F12 `cron-target-guard` FAIL-with-empty-lists** — transient; last FAIL 16:10Z, clean
  since 16:15Z; not reproducible now.
* **F14 `lpt-deploy-drift` verdict** — `IN SYNC` while dirty is the script's documented
  design; changing a monitor's contract without the owner was not done.
* **F15 FTS `_content` duplication** — 8.79 GB of duplicated `raw` text; the migration to an
  external-content FTS5 index rebuilds a 12 GB index on the live sole writer, so it is a
  change-window/owner decision, not a safe in-place fix. Measured, not applied.
* **F13 WITHDRAWN** — `authority-repo-push`'s crontab line is correctly wrapped and its
  latest run is rc=0; the two rc=2 rows predate the fix.

## 8. WHAT I COULD NOT ESTABLISH

* Whether `frontier_risk_board` is repairable or should be retired.
* Which actor, if any, is concurrently editing the same repositories; `identity_store.py`
  was last touched 14:14Z and `ceo-kernel/ck/sentinel.py` 16:02Z, and both changes were
  landed/preserved rather than overwritten. In the continuation `unified_comms.py` mtime was
  2026-10-07 and no other editor touched it.
* The effect of the identity cap on the live process (restart not performed) and of the F10
  fix on the live endpoint (same). Both are verified in-process only.
* The row/date range of `dsh_session_events` (a `MIN/MAX(created_at)` scan over 8.9 GB of
  text timed out; row count 1,955,013 is measured) — so whether *rows* (as opposed to the
  FTS copy) are prunable is not established.
* Who or what polls `GET /api/v1/comms/active-phones` at ~3.5 req/s from localhost during
  the burst; the web proxy is `web/app/api/comms/unified/active-phones/route.ts`.

---

## 9. REPRODUCE

```bash
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1

# sentinel report
python3 -c 'import json;d=json.load(open("/root/ceo-kernel-var/latest.json"));
print(d["generatedAt"], [(f["check"],f["severity"],f["ok"]) for f in d["findings"] if not f["ok"]])'

# the two fixed checks, directly
cd /root/ceo-kernel && CEO_KERNEL_DB=/root/authority.db \
  CEO_KERNEL_AUTHORITY_HOST=secratary-cloud python3 -c \
  'from ck import sentinel as s; print(s.check_liveness().summary); print(s.check_db_writable().summary)'

# cron non-zero rate
python3 - <<'PY'
import collections
rows=[l.rstrip().split("\t") for l in open("/root/.cron-status/runs.tsv") if l.strip()]
print("rows",len(rows),"nonzero",sum(1 for r in rows if r[2]!="0"))
PY

# DB free pages
sqlite3 'file:/root/authority.db?mode=ro' \
  'PRAGMA page_size; PRAGMA page_count; PRAGMA freelist_count;'

# identity growth
python3 -c 'import json;d=json.load(open("/opt/company/data/agent_identities.json"))["agents"];
o=d["orchestrator"];print(len(o["personality"]["narrative"]),len(o["identity_proposals"]))'

# F10 — the defect and the fix, two calls on one thread, on a throwaway DB
#   /tmp/test_borrowed_close.py sets DATABASE_URL=sqlite:////tmp/t188.db, calls
#   unified_comms._conn() twice, and captures app.database._record_contention:
cd /opt/company && DATABASE_URL=sqlite:////tmp/t188.db ./.venv/bin/python /tmp/test_borrowed_close.py
#   before (backup module): uc._conn() is the cached connection: True  -> events=['closed_on_handout']
#   after  (98c0595b):      uc._conn() is the cached connection: False -> events=[]

# F15 — per-table sizes (ran ~6 min under nice/ionice; 637 b-trees, 22.95 GB)
nice -n 19 ionice -c3 sqlite3 -readonly 'file:/root/authority.db?mode=ro' \
  'SELECT name, SUM(pgsize) bytes, SUM(ncell) cells FROM dbstat GROUP BY name ORDER BY bytes DESC;'

# F15 — the FTS holds its own copy of raw (default content), so _fts_content duplicates it
sqlite3 -readonly 'file:/root/authority.db?mode=ro' \
  "SELECT sql FROM sqlite_master WHERE name='dsh_session_events_fts';"
```

## 10. CONTINUATION ACCESS AND COMMITS

* **Seat:** `zabz-tech-linux` (the shell this session was given), reached `secratary-cloud`
  over `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`; the estate mesh key is still
  refused for every user tried. This is the same access shape the first pass recorded.
* **Application fix:** `secratary-cloud:/opt/company` @ **`98c0595b`** (F10), on top of
  `4d6a606c` (F8).
* **Kernel fixes:** `secratary-cloud:/root/ceo-kernel` @ **`91c6f2e`** (F1, F2, unchanged).
* **This report:** `secratary-cloud:/root/code/harness-config/docs/mesh/188-SYSTEM-AUDIT-AND-FIXES.md`
  and the mirror `zabz-tech-linux:/home/zabz/code/harness-config/docs/mesh/188-SYSTEM-AUDIT-AND-FIXES.md`.
