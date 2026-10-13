# 30 — Systems and autonomy plumbing, audited

**Prepared:** 2026-10-13 · **Method:** one mesh child audited what is running versus what is claimed,
on the authority and across the mesh, read-only. `[M]` = measured live by the child during
13:07-13:12Z; `[D]` = a document claim it read rather than reproduced.

**Posture:** the authority is `secratary-cloud` (`company-api`, `/root/authority.db` 25.86 GB). The
office box `secratary` is **frozen** and was never touched. The child reached the authority only
through the retired key `~/.ssh/retired-20260914/id_ed25519_hetzner root@178.156.194.1` — the route
`docs/mesh/176` §0 records — because `ssh secratary-cloud` from the Mac mini is
`Permission denied (publickey)`. **That is finding #6 below, not an inconvenience.**

---

## 1. What is running

| system | where | verdict | evidence |
|---|---|---|---|
| `company-api` | cloud | **live** | systemd running; `NRestarts=0`; **`MemoryMax=infinity`**, peak 9.09 GiB `[M]` |
| `/root/authority.db` | cloud | **live, growing 2.3 MB/h** | 25.85 GB; integrity check ok 05:49Z (703 s, read-only) `[M]` |
| autopilot (900 s tick) | in the API | **live** | `last_run 13:06:31Z`, run_count 15, `consecutive_failures 0`; 39 subsystem rows `[M]` |
| `tick_telemetry` | authority.db | **live** | 34,139 rows, newest `13T12:40:22Z`, 85 agents `[M]` |
| `mesh-broker` :3091 | cloud | **live, partly blind** | answers; **2 of 5 nodes `unreachable HTTP 403`**; `reads 45 / readFailures 18` `[M]` |
| 3 mesh nodes | tailnet | **live** | zabz-tech / yoga-1 / tech-linux `state=ok`, 143 / 197 / 96 ms `[M]` |
| `secratary` · `lakewooechsmini` | tailnet | frozen · live-but-gated | both `HTTP 403` from the broker `[M]` |
| cron | cloud | **live** | `runs.tsv` 11,374 rows, last 13:08:01Z, no empty hour since 10-12T08 `[M]` |
| timers | cloud | **live** | estate-monitor 2 min · deadman 5 min · offsite daily · transcript-archive hourly `[M]` |
| `estate-monitor` | cloud | **live, log-only** | `verdict=CRITICAL crit=4 … escalated=0` every 2 min `[M]` |
| sentinel + absence monitor | cloud | **live** | `run-sentinel` 401 runs; `sentinel-freshness ok "newest row 285s old"` `[M]` |
| `fa` + journal + comms indexes | cloud | **live/fresh** | paths 13:08:01Z, tags 13:08:02Z, comms.db 224.9 MB 13:07:17Z `[M]` |
| session ingest | authority.db | **live** | `dsh_sessions` 6,935, max `ingested_at 13:08:36Z` `[M]` |
| `wake-fanout` (owner loop) | cloud | **live, cannot claim** | 205 `wake-failed/` dirs; claim `blocked_by:"daily-cap"` every minute `[M]` |
| `mesh-health` · `harness-verify` · `mesh-e2e.ps1` · `profile-gate.mjs` | repo only | **dead / unreferenced** | no scheduler; print-and-exit; `132:141` marks them DEAD `[D]` |
| `engine-vitals.mjs` | worktree only | **unreferenced** | 0 hits in 135 docs; last touched 2026-09-28 `[D]` |
| 6 launchd agents | the Mac mini | **3 failing silently** | `launchctl list` exits 1: autosync, repo-sync, nodeagent; no ledger `[M]` |

**Two claims in the brief could not be reproduced and are reported as such:** `175-STATE-OF-THE-ESTATE`
**exists in no ref** the child could reach, and **`work_metrics` does not exist** at all
(`sqlite_master` returns nothing for it).

---

## 2. Recurring failures, ranked by number of independent recordings

Method: the complete pain set is the worktree journal's **475 pains**; the checkout named in the
brief has **198**, a strict subset, **missing 277 pains and ~1,906 entries**. The authority's own
checkout is a third count (3,474). Counts are distinct entries whose root failure matches; the groups
overlap. **Ranking is by recordings, not severity.**

| # | class | n | representative ids | still live? |
|---|---|---:|---|---|
| 1 | **Silent failure — an alarm with no transport** | **45** | `P2` (3,246 ticks, zero completions, "nothing routes a finding to a human") · `P167` (alarm piped to a nonexistent `mail`) · **`P3006` dead-man green on a stale marker — NOT fixed** · **`P2948` rc=0 for 2,991 runs — NOT fixed** | **yes** |
| 2 | **Mesh / subagent dispatch dead** | 39 | `P2834` 3/3 dispatches fail · `P2887` broker down + `mcp.jina.ai ENOTFOUND` · `P2937` failover "not in effect" · `P2141` an unreachable node shown *running* for 30 min | **yes** |
| 3 | **Repo / git divergence, unlanded work** | 38 | `P183` clone 61 ahead / 138 behind · `P230` deployed vs repo each miss 7 functions · `P2875` "merged to test ≠ reached customers" · `P3135` "every push half-fails" | **yes** |
| 4 | **Journal id collisions / divergent lineages** | 32 | `P233` "**third** occurrence" (not done) · `P2561b` "37 ids each mean two" | **yes** |
| 5 | **SSH / auth lockout** | 22 | `P2946`, `P3002`, `P3003`, `P3005`, `P3007` — on 10-11 the authority refused every key around 06:40Z with a 105-byte `authorized_keys` | recurring |
| 6 | **SMS duplication** | 20 | `P2542` 26 identical SMS in 17 h (26 message_ids) · `P2862` four SMS → 168 rows · `P3143` 389 comms really 16 | **no landed guard** |
| 7 | **Wrong host / placement** | 16 | `P3134` one unreachable node = 4,000 ms per placement · `P2260` ×18 held owner messages | **yes** |
| 8 | **Stale search index** | 14 | `P2899` dead 21 days (`NextRunTime` empty) · `P3138` zabz-tech 27 days — the "third dead-search-clock" | authority fresh; zabz-tech open |
| 9 | **Disk full / tmpfs / worktree bloat** | 12 | `P2553` office 447/467 GB with no valid backup · `P2892` `/tmp` is a RAM tmpfs · `P2900` 133 worktrees, 130 GB | **P0, live** |
| 10 | **SQLite lock contention** | 11 | `P2127` `BEGIN IMMEDIATE` failed at 10.022 s, the timeout fix "no effect" · `P3139` 71 waits in 30 min, "holder never named" | **yes** |
| 11 | **Memory / OOM** | 11 | `P211` fixes "only shortened the interval" · `P3136` 7.7 GB / 3 OOM | **live** |
| 12 | **A cron job that never fires** | 10 | `P172` reminders die on `ImportError` (fix not done) · `P82` sync dead 18 days | **yes** |
| 13 | **Leaked credentials** | 10 | `P160` live AWS `AdministratorAccess` + Twilio tokens (rotation not done) · `P344` world-readable `.env.bak*`, "**fourth** instance" | **yes** |
| 14 | **Owner attention** | 10 | `P2942` 160 questions / 78 unanswered texts, no approved path | **yes** |
| 15 | **Concurrent writers with no lease** | 9 | `P2564` concurrent deploys silently revert · `P246` a second session moved `lpt-hub` main | **yes** |

---

## 3. Autonomy, measured

`work_metrics` does not exist; the stored sources are `tick_telemetry` and `anomaly_log`. Read-only
query at 13:07Z, last 24 h:

```
tick_telemetry WHERE started_at >= '2026-10-12T13:07:00'
 134 ticks | 16 agents | 134 tick_ids | 121 complete | 8 error | 121 steps_completed
 1,639,891 tokens | $0.1395
```

- **134 ticks in 24 h (5.6/h); 121 complete, 8 error, 1 escalate, 18 suspended; 1.64 M tokens; $0.14.**
- Per day (rows / complete / error): 10-13 `91/81/5` · 10-12 `122/109/9` · 10-11 `152/119/23` ·
  10-10 `101/91/5` · 10-09 `167/158/1`.
- **Zero-step ticks: 10/91 (10-13), 13/122 (10-12), 33/152 (10-11) — 10-15% of ticks do no work**,
  against `interval_sec=900` ⇒ ~96 nominal ticks/day.
- **Failures are recorded, not sent.** `anomaly_log` 537 rows: `comms_capture_stale` **504** (newest
  `13T10:29:38Z`, "dialpad_sms age=6.74h>6h", escalated as `owner_message_queued`), `hollow_workflow`
  25 (last 07-02), `velocity_spike` 7, `runaway_loop` 1.
- Autopilot: `amazon_sync` + `ebay_sync` `failed cf=3`; **`fleet_location_poll` failed — 414
  consecutive failures, last success 09-29 (345 h)**; `google_voice_secretary` `ok` but 201 h stale.

**Reading: the company is not idle and is not expensive. It is running work nobody sees, failing in
ways nobody is told about, and spending $0.14 a day doing it.**

---

## 4. Silent-death surfaces — every system that can stop without a signal

1. **`estate-monitor` cannot escalate what it sees.** `estate-monitor.py:1355-1359` hard-codes
   `conditions_allowed_to_escalate:["public_health_status"]`; of 29 thresholds only one has
   `mode=alert` — disk, swap, OOM, API RSS and deadman are all `mode=log`. Live: `verdict=CRITICAL
   crit=4 escalated=0`, every two minutes. **The detector already computes the state; it is a
   one-line routing change.**
2. **cron dying is unobservable.** The estate's only outbound heartbeat, `authority-deadman.timer`, is
   a *systemd* timer on the same host — so if `cron.service` dies, deadman stays green (`168` §7.2;
   `132:300`). Live reading: `ping http 200 … offsite=ok db_tables=662`.
3. **A job that never runs looks installed.** `/root/bin/cron-liveness.py` exists for exactly this
   ("a job that never runs and a job that runs correctly print nothing different") and **is not
   scheduled** (`grep -c` = 0). The ledger still lists `report-offsite-age` at `10-12T03:30:03Z`
   (34 h stale) after a timer replaced it, with no two-way reconciliation.
4. **The P0 — disk and memory on the authority.** Disk swung between **98.7% / 0.0 GB free**
   (`disk-guard` CRITICAL, 13:00:03Z) and **92% / 6.3 GB free** (`df -h`, 13:08Z); `estate-monitor`
   logged 87.5% in the same window. `prune-backups` logged `FLOOR BREACHED … Pruned NOTHING;
   investigate what filled the disk.` Memory: `swap_used_pct` 95-99.6%, **`oom_kills_24h=11`**,
   `api_rss` 5.1-5.8 GiB, and `company-api` has **no `MemoryMax`**. Nothing tells a human.
   *The manager reproduced the disk reading at 13:2xZ: 66G/75G used, 6.1 GB free, swap 3829/4095 MB,
  `/root/authority.db` 25.86 GB. The 0.0 GB reading was not reproducible and is recorded as a past
  reading, not a measurement.*
5. **The offsite copy is transport-proven and content-unproven.** 24.3 GB uncompressed against 14 GB
   free ⇒ a full `PRAGMA integrity_check` "cannot fit" (`176` §4, Trap 7); the external freshness
   reading was `NODATA` (`150:117`).
6. **The 21-day precedent, twice.** `AGENTS.md:108-111`: `PersonalSecretary-PushVSCodeChats` reported
   `LastTaskResult=0` hourly for **21 days** while the Copilot archive stood still. `000:96-99` and
   `172:96`: the search refresh died silently **three times**, once for 21 days (`H3376`). It is fixed
   only by a second job (`fa-index-freshness`), which covers search alone.
7. **The owner-channel loop spins and fails.** 205 `wake-failed/` dirs (oldest 10-11 06:39Z); the
   newest claims `blocked_by:"daily-cap"` while spend is **5.18 of a 25 cap**, with a run-log warning
   `USD cap drift … The looser value wins.`
8. **"Success despite no work."** `financial_alert_sweep` recorded `success:true` on 10/10 runs while
   reading no ledger (`150:84`); `ai-gateway-health` fires into a log (`nz=99/107` lifetime,
   `lastrc=0`).
9. **Search completeness regression.** `find-anything` hard-codes
   `JIDX="$HOME_DIR/code/harness-config/journal/index"` (engine:250/258) despite lesson `L3746`; on
   this checkout it reads **1,644 journal entries, not 3,474 or 3,550** — and the freshness guard
   calls the smaller tree "current". **`sessions.mjs`'s `DEFAULT_NODES` maps `secratary` →
   `secratary-ts`, the frozen anchor, and has no `secratary-cloud` at all.**
10. **The Mac's launchd jobs** (`harness-autosync`, `repo-sync`, `nodeagent`) exit 1 with
    `Connection refused` / 403 / rebase-abort — no ledger, no heartbeat.

---

## 5. What is missing

A transport for the authority's own resource CRITs · an off-box "cron itself died" monitor · a
scheduled ledger↔crontab reconciliation (`cron-liveness.py` exists, unused) · **applied disk
retention** (floor breached, nothing reclaims) · a `MemoryMax` cap or serialisation for `company-api`
and the hourly ~6.27 GB `transcript-archive-pull` OOM · off-box content verification of the DB backup ·
one journal lineage · search and session tooling on the checkout agents actually use (`sessions.mjs`
and the two skills are absent from `master`; `~/.dsh/skills` is not installed on the Mac) · a
dedupe/lease layer for outbound SMS, journal ids and crontab writes.

---

## 6. Recommended changes, prioritised

1. **Reclaim the authority's disk now** — a dry run of the existing reclaim path first, unblock
   `prune-backups`' floor, and page on `disk-guard` rc=1. The database grows 2.3 MB/h on a 75 GB disk.
2. **Give `estate-monitor` a transport** for `disk_used_pct`, `disk_free_deficit_gb`, `swap_used_pct`,
   `oom_kills_24h`, `deadman_*`, `offsite_*` — it already computes every one of them.
3. **Cap `company-api` memory** and fix or serialise `transcript-archive-pull` (11 OOM kills in 24 h;
   swap at 95-99.6%).
4. **Schedule `cron-liveness.py`** and add a two-way crontab↔`runs.tsv` reconciliation. This is the
   single most-repeated defect class on the estate.
5. **Make the off-box deadman watch cron**, not only the API.
6. **Converge the journal and checkout lineages**; fix `find-anything`'s hardcoded journal path; add
   `secratary-cloud` to `sessions.mjs`'s node map and point `secratary` at the frozen box honestly.
7. **Triage the wake loop** — reconcile the 25-vs-5 cap drift, clear or explain the 205 failures,
   surface persistent `blocked_by` into the owner queue.
8. **Fix or externally monitor the Mac's three failing launchd agents.**

## 7. Honesty

`175` and `work_metrics` do not exist. The authority was reachable only by a retired key; nothing was
written and no service on any host was touched. The failure ranking curates 475 recorded pains with
grouped overlaps — it is not an automated count. `estate-monitor`'s disk reading disagreed with `df`
by 5-11 points in the same window; both are reported and neither is reconciled. Cloud numbers are one
session at 13:07-13:12Z; the frozen anchor was read only through documents.
