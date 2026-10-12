# 188 — SYSTEM AUDIT AND FIXES: the cloud authority, 2026-10-12

**Audit seat:** `zabz-tech-linux` (Linux 6.8, user `zabz`), reached over the tailnet.
**Target audited:** `secratary-cloud` — the company authority (`100.73.176.126`, Hetzner
`178.156.194.1`), Hetzner CCX23: **4 vCPU, 15.6 GB RAM, 75 GB NVMe**.
**Access:** `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`. The estate mesh key
(`id_ed25519_mesh`) is refused by the authority for every user tried (`root`, `zabz`,
`ezabz`, `ubuntu`) — the same shape as journal `P2944`/`P2946`/`P3003`/`P3005`.
**Window:** 2026-10-12 16:20–16:55Z.
**Constraints honoured:** no service state, crontab line, timer or host configuration was
changed; `company-api` was not restarted; `/root/authority.db` was opened only as
`file:…?mode=ro`; scratch files are under `/tmp`.

> **Honesty note on "you are on secratary-cloud".** The brief placed this audit on
> `secratary-cloud`. The shell I was given ran on **`zabz-tech-linux`**; I did not
> pretend otherwise. The audit *target* is the authority and it is reachable, so the work
> was done there remotely.

---

## 0. HEADLINE

| | |
|---|---|
| **findings** | **14** (F1–F14) |
| **fixed and verified** | **3**: `liveness` (F1), `db_writable` (F2), identity-store unbounded growth (F8) |
| **already fixed before this session** | 4: the two dialpad jobs, `cron-script-guard`'s blind decode, `report-offsite-age`'s exit-0-while-broken duplicate |
| **not fixable by code alone** | `guard-registry` (F5, owner approval + crontab), `owner_queue`/`attention_debt` (owner), `config_sync` divergence (F4, publish decision), `phone_endpoint` (F6, missing probe), `_db_lock` contention (F11) |
| **worst single defect** | `personality.narrative` held **277,712** entries / **22.6 MB** with no cap — 68 % of a 33.4 MB store; a stat-keyed cache added the same day hid the read cost but nothing bounded the growth (F8) |
| **biggest live error source** | `db_contention` "closed on handout": **461 rows in 24 h**, every one auto-resolved by reconnect (F10) |

The two checks the brief names as broken (`liveness`, `db_writable`) were **already fixed in
the working tree** of `/root/ceo-kernel` when this session arrived, uncommitted. I verified
them against live data, ran the kernel's own tests, and **committed** them
(`/root/ceo-kernel` @ `91c6f2e`). I did not re-implement them; rule 0 of this estate is
*prove it does not already exist*.

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

Source: `/root/.cron-status/runs.tsv`, 5,896 rows, 2026-10-11T06:32Z → 2026-10-12T16:24Z.

| metric | value |
|---|---|
| non-zero rows, whole ledger | **720 / 5,896 = 12.2 %** |
| non-zero rows, last 24 h | **515 / 4,574 = 11.3 %** |
| wrapped cron lines (`cron-target-guard` decodes) | 33 |
| custom systemd timers | all `Result=success`; `systemctl --failed` empty |

**Worst offenders (last 24 h):**

| job | non-zero / runs | rc now | cause, from the ledger / own log |
|---|---|---|---|
| `cron-target-guard` | 228 / 287 | 0 | now clean (28 targets, 12 critical paths, `ok:true`); the mass failure was a transient **FAIL with every finding list empty** (§3, F12) |
| `guard-registry` | **96 / 96** | **2** | `/root/bin/guards.yaml` missing (F5) |
| `dialpad-recording-gap` | 62 / 287 | 0 | **0 / 197 failures since 00:00Z** — already fixed by moving `SECRETARY_DB=` into the job's environment (doc `156`) |
| `ai-gateway-health` | 48 / 48 | **3** | by design: all findings are CONDITIONs; `tier-collapse` + `unattributed-calls` (`app/code_self_edit.py` logs `model=unknown`). rc=3 is the checker's "condition, not fault" code |
| `dialpad-transcript-gap` | 31 / 143 | 0 | **0 / 98 failures since 00:00Z** — same fix |
| `production-comms-freshness` | 22 / 96 | 0 | intermittent during the harvest window; latest runs `fresh` |
| `website-comms-push-cron` | 10 / 37 | 0 | intermittent; own log empty, reason on stdout |
| `authority-repo-push` | 2 / 5 | 0 | `cron-wrap REFUSED: payload … is not valid base64` — a **crontab line that is not wrapped**; a crontab defect, out of scope, reported |

**Timers (18):** `authority-offsite-backup`, `authority-data-offsite`, `authority-deadman`,
`authority-report-offsite-age`, `estate-monitor`, `company-outcome-monitor`,
`transcript-archive-pull` all last `Result=success, status 0`. The previously-reported
`report-offsite-age` duplicate crontab line is gone (systemd timer only).

---

## 3. DISK, MEMORY, AND THE UNBOUNDED IDENTITY STORE

### 3.1 Disk — not immediately critical, but trending down

| reading | value |
|---|---|
| `df -h /` | 75 G total, **56 G used, 16 G avail, 79 %** |
| `disk-guard` (used/total, 16:30Z) | **74.9 %**, 15.7 GB free; warn 90 %, crit 95 % |
| growth, full guard window (31.9 h) | **+13.7 pts / −10.2 GB free ≈ 7.7 GB/day** |
| growth, **last 6 h** | **+0.5 pts / −0.40 GB free ≈ 1.6 GB/day** |
| `/root` | 27.2 GB (the 24.6 GB DB dominates) |
| `/opt/company` | 21 GB — `data` 12.7 (google_voice_profiles 6.8, chromadb 2.9, mem0 1.1), `archive/lpt-transcripts` 6.3, `.venv` 1.5 |
| DB growth | register baseline 24,232,910,848 B (03:47Z) → 24,608,387,072 B (16:30Z): **≈ 0.7 GB/day**; a 5-minute sample gives ≈ 1.0 GB/day |
| archive growth | 4.1 GB (`151`, 2026-10-11 20:39Z) → **6.3 GB** now; `transcript-archive-pull.timer` writes hourly (newest 16:27Z) |

At the recent ~1.6 GB/day the 15.7 GB free lasts ~10 days; the 31.9-hour average would
say ~2 days. Nothing is unbounded in the *filesystem* sense — the driver is the DB and the
actively-draining transcript archive, both by design — but the headroom is thin enough that
the 90 % warn is reachable within the week if the archive backfill accelerates.

### F9 — disk and DB growth trend (open, no code fix)

The two consumers that move the needle are the **database (~0.7–1.0 GB/day)** and
**`archive/lpt-transcripts` (4.1 GB → 6.3 GB in ~20 h)**. There is no retention defect to
repair: `disk-guard` reports `backup_dirs: 0` and the offsite backup streams without staging
a local copy. The finding is simply that 15.7 GB free is ~10 days at the recent rate, and
the 90 % warn threshold is within reach — measured, not inferred.

### 3.2 The database — **~0 % is reclaimable by `VACUUM`** (measured, not guessed)

```
page_size=4096  page_count=6,007,004  freelist_count=119  auto_vacuum=0
db bytes           = 24,604,688,384
free (reclaimable) = 119 * 4096 = 487,424 B  =  0.0 %
WAL                = 67,108,864 B (auto-checkpoint 1000)
```

So there is **no free-page bloat to vacuum away**; `VACUUM` would free ~0.5 MB and needs
~24 GB scratch (we have 15.7 GB) — it must not be run. A per-table `dbstat` breakdown was
started but did **not finish** (killed after 187 s); it is not claimed.

### F8 — `data/agent_identities.json`: one record is growing without bound  ✅ FIXED in source (not live)

* **Measured:** file **39,354,486 B / 126 agents**, `updated_at` rewritten every few minutes.
  `orchestrator` alone is **5,477,592 B**; across all 126 agents the field sizes are:
  * `personality.narrative` — **277,712 entries, 22,584,929 B (22.6 MB)** ← the growth
  * `identity_proposals` — **11,526 entries, 2,950,687 B**, *every one* `pending_owner_input`
  * `personality` (name/personality payloads) — 1.9 MB
  * `identity_notes` — 1,159; `voice_history` — 1,831; `name_history` — 562
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
* **Verified on a copy of the live store:** with the caps applied, **231,922 narrative +
  11,026 proposal + 3,207 note + 1,731 voice + 462 name entries** would be pruned, freeing
  **22,119,113 B = 21.09 MB (66.3 %)**; a second pass prunes 0 (idempotent); a malformed
  agent returns `{}` rather than raising inside `_save`.
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

**Last 24 h: 479 rows**, dominated by one:

| n | type | message | resolution |
|---|---|---|---|
| **461** | `db_contention` | `Cannot operate on a closed database (detected on handout and reconnected; closed by explicit cache eviction)` | auto-resolved (reconnect) |
| 7 | `sms_reply_timeout` | `Timed out after 10.0s` | 3 unresolved |
| 3 | `wo_failure_streak` | `seed_browser_session_health` failed 4 consecutive runs | unresolved |
| 2 | `unhandled_exception` | `database is locked` | unresolved |

All-time, the largest unresolved cluster is **406 `unhandled_exception: database is locked`**
(2026-08-23 → 2026-10-11, median burst size), historically the app's global `_db_lock`
(`170 §5.4`, `P3139`). In the last 24 h only **2** fresh lock errors appeared — the
contention is materially quieter than at the time of `170`.

### F10 — the connection cache evicts connections live threads still hold

`app/database.py:_prune_connection_cache_locked()` closes a cached connection when its
owning thread is gone **or** it has been idle longer than `CONN_CACHE_IDLE_TTL_S`. Because
`_get_conn()` hands out a bare connection the caller keeps using after the call returns, a
long statement can outlive the idle TTL; the cache then closes it, and the next `_get_conn`
records `closed_on_handout` and reconnects. **461/day** is that path. It is instrumented and
recovers, so no customer work is lost — but it is the loudest error in the log and it is a
defect in the cache's liveness assumption. **Not fixed:** tightening it safely needs a
usage/lease signal the cache does not have, and the fix-shape was not proven in this window.

Secondary genuine defects in the log, unfixed and reported: **stripe package not installed**
(1), **ghost_agent** (tasks assigned to ids absent from the identity store, 5 in 24 h),
**wo_failure_streak** on seed work orders.

---

## 5. GREEN LIGHTS THAT MEASURE THE WRONG THING

| surface | says | truth | verdict |
|---|---|---|---|
| `liveness` | "ticking" at any age | age forced to 0 by `or 0` | **was green, fixed (F1)** |
| `db_writable` | "refuses writes" (HIGH) | 30/30 acquired at 25 s | **was red, fixed (F2)** |
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
| F8 | identity-store history caps | `/opt/company/app/identity_store.py`, commit **`4d6a606c`** (backup `/tmp/identity_store.py.bak-20261012T162944Z`) | 33,386,951 B → **11,267,838 B** projected (−21.09 MB, −66.3 %) | **no — needs a `company-api` restart, which was not performed** |

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
* **F10 `db_contention`** — the cache's liveness assumption needs a lease/usage signal and a
  proof not obtained here.
* **F11 `_db_lock` serialisation** (`170 §5.4`) — the maker of the contention; a stack dump
  inside a stalled request is still the next measurement, not a fix.
* **F12 `cron-target-guard` FAIL-with-empty-lists** — transient; not reproducible now.
* **F13 `authority-repo-push` unwrapped crontab line** (`not valid base64`) — a crontab
  defect; crontab is out of scope.
* **F14 `lpt-deploy-drift` verdict** — `IN SYNC` while dirty is the script's documented
  design; changing a monitor's contract without the owner was not done.
* **Disk / DB per-table size** — `VACUUM` free space is measured (0.0 %); the `dbstat`
  per-table breakdown was still running when this was written and is not claimed.

## 8. WHAT I COULD NOT ESTABLISH

* Per-table byte sizes in the 24.6 GB database (`dbstat` did not finish in the window).
* Whether `frontier_risk_board` is repairable or should be retired.
* Which actor, if any, is concurrently editing the same repositories; `identity_store.py`
  was last touched 14:14Z and `ceo-kernel/ck/sentinel.py` 16:02Z, and both changes were
  landed/preserved rather than overwritten.
* The effect of the identity cap on the live process (restart not performed).

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
```
