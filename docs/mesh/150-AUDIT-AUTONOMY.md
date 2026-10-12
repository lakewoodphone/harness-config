# 150 — AUDIT: AUTONOMY — what silently STOPPED when the authority moved to the cloud

**Workstream:** silent-failure audit (one of the 2026-10-11 migration workstreams).
**Author:** Zabz, ZABZ-YOGA session. **Written:** 2026-10-11 ~15:50Z (all times UTC unless marked).
**Hosts:** authority = `root@178.156.194.1` (`secratary-cloud`, Hetzner CCX13). Reference = `secratary-ts`
(office box, **READ-ONLY**, frozen at 2026-10-11 04:01–04:28Z).

**The question this answers:** which parts of an autonomous company have *stopped producing evidence*
since the cutover, where nothing emits an error? Silence, not failure.

**Method and provenance.** Every number below was read live from the named machine with the named
command during this session (2026-10-11 15:39–15:48Z). The authority clock was verified against the
laptop: `secratary-cloud: date -u` = `2026-10-11T15:46:47Z`, laptop local `11:45 EDT` = the same
instant. Nothing on the office box was started, enabled, unmasked or written; only `cat`, `ls`, `wc`,
`grep`, `awk` and one indexed `sqlite3 -readonly` count were run against it, with `cut -d' ' -f1
/proc/loadavg` checked before and after (0.00 → 0.05).

**Headline.** The company is **working** — the agent loop is live and writing tasks and memory every
few minutes (§4). What is silent is the **enforcement layer around it**: the backup cadence, the
money-ledger consumers, two Dialpad backfills, one guard that reports ok while watching nothing, and
one external freshness reading that went blind. None of them errors; all of them look green.

---

## §1 — THE AUTOPILOT SUBSYSTEM TABLE (all 39, with last-success and verdict)

Source: `/opt/company/data/autopilot_state.json` on the authority (157,591 B, mtime 15:32Z), read with
`python3` on the box. Age is measured from `last_ran_at` to `2026-10-11T15:45Z`. `ok`/`fail` are the
lifetime `successes`/`failures` counters in that file.

**Verdict key:** **OK** = succeeding inside its own cadence · **STALE** = last success older than a day ·
**FAILING** = last status is `failed`, or recent runs fail · **SILENT** = status `ok` / run returns
success but the recorded detail says it did no work, or it never runs · **DISABLED** = superseded by
design, not a migration loss.

| # | subsystem | last_ran_at (UTC) | status | ok | fail | age | verdict |
|---|---|---|---|---|---|---|---|
| 1 | `llm_checkin` | 2026-10-11T15:45:09 | ok | 21949 | 0 | 0.02 h | OK |
| 2 | `ceo_tick` | 2026-10-11T15:43:57 | ok | 8024 | 1 | 0.04 h | OK |
| 3 | `shadow_learning` | 2026-10-11T15:43:56 | ok | 5463 | 0 | 0.04 h | OK |
| 4 | `self_audit` | 2026-10-11T15:43:47 | ok | 5348 | 116 | 0.04 h | OK |
| 5 | `ambient_bottom_layer` | 2026-10-11T15:43:47 | ok | 5235 | 0 | 0.04 h | OK |
| 6 | `healing` | 2026-10-11T15:43:47 | ok | 5962 | 129 | 0.04 h | OK |
| 7 | `company` | 2026-10-11T15:42:38 | ok | 6654 | 151 | 0.06 h | OK |
| 8 | `work_mode` | 2026-10-11T15:42:01 | ok | 8226 | 168 | 0.07 h | OK |
| 9 | `gmail_decisions` | 2026-10-11T15:42:01 | ok | 1689 | 3 | 0.07 h | OK |
| 10 | `world_context` | 2026-10-11T15:41:47 | ok | 7879 | 23 | 0.07 h | OK |
| 11 | `work_mode_poll` | 2026-10-11T15:41:45 | ok | 230834 | 0 | 0.07 h | OK |
| 12 | `activity_sync` | 2026-10-11T15:34:28 | ok | 2641 | 0 | 0.19 h | OK |
| 13 | `proactive_synthesis` | 2026-10-11T15:32:25 | ok | 7422 | 1 | 0.23 h | OK |
| 14 | `email_catalog` | 2026-10-11T15:31:27 | ok | 237 | 0 | 0.24 h | OK |
| 15 | `world_index` | 2026-10-11T15:30:58 | ok | 2025 | 150 | 0.25 h | OK |
| 16 | `self_prog` | 2026-10-11T15:24:17 | ok | 3061 | 0 | 0.36 h | OK |
| 17 | `weekly_strategy` | 2026-10-11T15:23:14 | ok | 72 | 0 | 0.38 h | OK |
| 18 | `company_evolution` | 2026-10-11T15:23:04 | ok | 1884 | 36 | 0.38 h | OK |
| 19 | `frontier_board_packets` | 2026-10-11T15:23:04 | ok | 1092 | 19 | 0.38 h | OK |
| 20 | `hierarchy_manager_reviews` | 2026-10-11T15:23:04 | ok | 2691 | 56 | 0.38 h | OK |
| 21 | `creativity_scan` | 2026-10-11T15:23:04 | ok | 1097 | 0 | 0.38 h | OK |
| 22 | `initiative` | 2026-10-11T15:22:52 | ok | 1382 | 0 | 0.39 h | OK |
| 23 | `mashgiach` | 2026-10-11T15:20:28 | ok | 1953 | 51 | 0.43 h | OK |
| 24 | `owner_attention_sweep` | 2026-10-11T15:19:09 | ok | 241 | 0 | 0.45 h | OK |
| 25 | **`financial_alert_sweep`** | 2026-10-11T15:17:49 | **ok** | 2851 | 0 | 0.47 h | **SILENT** |
| 26 | `evolution` | 2026-10-11T15:05:00 | ok | 951 | 81 | 0.68 h | OK |
| 27 | `self_improvement` | 2026-10-11T14:18:53 | ok | 1708 | 45 | 1.45 h | OK |
| 28 | `rule_consolidation` | 2026-10-11T14:18:54 | ok | 820 | 0 | 1.45 h | OK |
| 29 | `memory_consolidation` | 2026-10-11T13:44:15 | ok | 429 | 0 | 2.03 h | OK |
| 30 | **`paypal_sync`** | 2026-10-11T05:41:19 | **failed** | 37 | 41 | 10.08 h | **FAILING** |
| 31 | **`amazon_sync`** | 2026-10-11T05:41:19 | **failed** | 23 | 48 | 10.08 h | **FAILING** |
| 32 | **`ebay_sync`** | 2026-10-11T05:41:19 | **failed** | 25 | 48 | 10.08 h | **FAILING** |
| 33 | `plaid_sync` | 2026-10-11T05:41:23 | ok | 68 | 7 | 10.08 h | OK (daily cadence) |
| 34 | `receipt_sync` | 2026-10-11T05:41:47 | ok | 75 | 0 | 10.07 h | OK (daily cadence) |
| 35 | **`google_voice_secretary`** | 2026-10-05T03:33:45 | ok | 14414 | 0 | **156.2 h** | **STALE** |
| 36 | **`fleet_location_poll`** | 2026-09-29T03:44:44 | **failed** | 9347 | 592 | **300.0 h** | **FAILING/SILENT** |
| 37 | `spending_report` | 2026-09-03T05:30:51 | disabled_superseded | 0 | 38 | 922 h | DISABLED |
| 38 | `balance_capture` | 2026-08-04T17:43:35 | disabled_superseded | 0 | 2 | 1630 h | DISABLED |
| 39 | `boa_sync` | 2026-07-21T03:00:37 | disabled_superseded | 0 | 114 | 1981 h | DISABLED |

**Flagged rows, with the evidence inside each entry's own `recent_runs`:**

| subsystem | what its recent runs actually say | why it is flagged |
|---|---|---|
| `fleet_location_poll` | last 10 runs all `0 polled, 1 errors`; `consecutive_failures=414`; last success **2026-09-29T03:44:44Z** | 12.5 days dead, failing 414 times consecutively, and still carrying `status=failed` with nobody acting on it |
| `google_voice_secretary` | 14,414 successes, 0 failures, last **2026-10-05T03:33:45Z** | 6.5 days with no run of any kind. `ok` is the stale last result, not a current one |
| `financial_alert_sweep` | 10 of 10 recent runs: `"Local ledger DB not available"`, each recorded `success: true`; 2,851 lifetime "successes" | **Silent by construction.** It reports ok every ~60 min while reading no ledger. This is the "up and doing nothing" shape the audit exists to find |
| `paypal_sync` / `amazon_sync` / `ebay_sync` | last run 2026-10-11T05:41:19Z: `False … quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent`; the five runs before it all report a completed sync | All three broke **at the cutover instant** and have not run since. They are daily, so "10 h since last run" is not yet lateness — but the daily run has never succeeded on this box |
| `work_mode_poll` | 230,834 successes; `runs=0, notes=0` | Active but idle — recorded here so the count is not read as work |

**Cross-check against the office box** (`secratary-ts:
/home/zabz/personal-secretary-mvp/data/autopilot_state.json`, 156,688 B, mtime 03:25Z): the same
**39 subsystems, the same names** — the set did not shrink in the move. The differences are statuses
and recency, which is exactly the point: a subsystem cannot go missing from the autopilot, it can only
go quiet, and `last_status` alone will not show it.

---

## §2 — WHAT IS SILENTLY NOT RUNNING, RANKED BY HOW LONG IT HAS BEEN SILENT

Evidence is a machine plus a command plus a file or row. "Silent" means: no error surfaces anywhere a
human looks, or the error is a single line in a log nobody reads.

| # | silent item | silent since (duration at 15:46Z) | how we know it is not running | consequence if left |
|---|---|---|---|---|
| 1 | `dialpad-call-fresh` (office L154, every minute) — the shop's newest-call freshness keeper | last office run **2026-10-11T04:01:01Z**; not installed on the authority at all (**~11.8 h**) | authority `crontab -l` has 21 jobs, none is `dialpad-call-fresh`; no timer; `/root/.cron-status/runs.tsv` has no such row in 1,226 lines | newest calls are only as fresh as the 30-min harvest; the 1-min keeper is gone |
| 2 | `push-dsh-sessions` as a *server-side* job (office L22, */30) | last office ledger row **04:00:02Z** (~11.8 h) | authority `crontab -l`, `/etc/cron.d`, `/etc/cron.hourly` contain nothing matching dsh/vscode/push. The work itself moved to the laptop: `Get-ScheduledTask` shows `PersonalSecretary-PushDSHSessions` + `PersonalSecretary-PushVSCodeChats`, hourly, last run 11:26 local | covered by the laptop, but the always-on host no longer guarantees it: if the laptop sleeps, session ingest stops with no server-side alarm |
| 3 | **OAuth token refresh** (`nightly-plaid-sync` etc. as a *mint token in advance* job) | `financial_alert_sweep` has produced no ledger reading since the copy, **2026-10-11T06:52Z** (~9 h) | 10/10 recent `financial_alert_sweep` runs say `Local ledger DB not available` with `success: true`; root cause proven below | the money picture is stale and *reported as healthy* |
| 4 | **The local-ledger consumers as a family** (`financial_alert_sweep`, `cfo-shift`, `cfo-scoreboard`, `cfo-ask`, `hours-drift`, `auto-categorize`, `daily-finance-sync-cron`) | **~9–12 h** (post-cutover), and the family was already partly dead before it | root cause, proven: `app/services/quickbooks_service.py:44-52` `_repo_path()` raises when `qb_agent_repo_path` is not a directory, and `_open_local_ledger()` returns `None` on `FileNotFoundError` **before** it resolves any ledger path. The ledger *is* on the box (`/root/accounting-data/live/accounting.db`, 21,995,520 B, copied from the office) but is unreachable through this resolver | every CFO/finance consumer silently returns "not available"; `hours-drift` and `cfo-*` are not installed here at all |
| 5 | **`lpt-deploy-drift` as a detector** (installed, running, detecting nothing) | last log write **2026-10-11T15:17:01Z** after 7 runs, all rc 0 | `/var/log/lpt-deploy-drift.log`: `VERDICT: IN SYNC — long-running services … company-api.service Sun 2026-10-11 08:25:04 UTC`. The office had it at 98% non-zero; here its baseline is whatever on this host | probably *correct*, not silent — recorded so it is not read as parity. On the office it was DEAD (98% failures); here it is green |
| 6 | **`financial_alert_sweep`'s ledger read** (same root cause as #4, listed separately because it is the only one that runs) | **~9 h** | as #4 | as #4 |
| 7 | **`dialpad-transcript-gap`** (*/10) — the 1,117 calls with no transcript at all | **100% of runs since install**: 43 runs, 43 non-zero, last `2026-10-11T15:40:02Z` rc=1 | reproduced by hand on the authority:
`cd /opt/company && .venv/bin/python scripts/dialpad-transcript-gap.py --limit 5 --dry-run` →
`sqlite3.OperationalError: no such table: dialpad_call_retranscript`. Root cause: line 45 of that script is `DB = ROOT / "data" / "secretary.db"` = **`/opt/company/data/secretary.db`, a 1.8 MB STALE STUB** (mtime 2026-10-11 01:18, `select count(*) from dialpad_sms_cache` → 0), while the live authority is `/root/authority.db` (`dialpad_call_retranscript` = 2,417 rows, `dialpad_sms_cache` = 135,435 rows) | customer conversations stay unsearchable; the job fails every 10 minutes and only the ledger knows |
| 8 | **`dialpad-recording-gap`** (*/5) — the 1,375 calls whose audio was never fetched | **100% of runs since install**: 87 runs, 87 non-zero, last `2026-10-11T15:45:02Z` rc=1 | same proven root cause: `/opt/company/scripts/dialpad-recording-gap.py` line 50 `DB = ROOT / "data" / "secretary.db"`, the same stub | 1,948 calls have neither audio nor transcript and cannot be recovered by the transcriber |
| 9 | **`ai-gateway-health`** (*/30) — the monitor that exists to catch a silently dead model lane | **14 runs, 14 non-zero (100%)**, last 15:30:01Z rc=1 | `/var/log/ai-gateway-health.log` (23,086 B, mtime 15:30): `tier-collapse — model_tier1, model_tier2, model_tier3 all point at deepseek/deepseek-v4-flash`, graded as a CONDITION=exit 3; three models at 100% failure over 7 days; `no traffic in 6h` on all of them | the estate's only model-health signal is *firing into a log*. This is the exact failure that ran for a week unnoticed on 2026-09-17 |
| 10 | **`guard-registry`** (*/15) — "a different process verifies the guards that matter" | **every run since install**: 30 runs, 30 non-zero, last 15:45:02Z rc=2 | `/root/.guard-registry/cron.log` is 28 identical lines: `registry does not exist: /root/bin/guards.yaml`. The office file exists: `secratary-ts:/home/zabz/bin/guards.yaml` (2,463 B, 2026-10-01) | every guard is unverified, and the verifier's own failure is a log line with no status file (`--write-status` wrote no `status.json`) |
| 11 | **`cron-script-guard` as a guard** — reports `ok: true` while watching nothing | every run since install (**88 runs, rc 0**) | `/root/.cron-scripts/status.json` (15:35:03Z): `cron_scripts_watched: 0, present: 0, wrapped_cron_lines: 0, payloads_decoded: 0, ok: true` | a 100%-blind guard that says ok. `cron-target-guard` beside it does decode (19 checked, 21/21 payloads decoded, `missing: []`) — so the two guards are not redundant, one of them is inert |
| 12 | **`transcript-archive-pull`** (hourly, replaces office L169) | pull works; the **check** has failed **every hour since install** | `journalctl -u transcript-archive-pull`: `2026-10-11T15:23:27Z archive holds no gap; a machine is silent (idle or unreachable — cannot be told apart here)`, `run.sh exit=2`, `ExecMainStatus=2`; the run consumed **6 min 45 s CPU over 11 min 28 s wall, 4.3 GB peak RSS**, and removed 4.46 GB of spool — so bytes really did move | the archive is *growing* but the staleness judgement is exit 2 (SILENCE) every hour, and nothing consumes exit 2. Also: 11–23 min of heavy I/O per hour on the box that also serves the company |
| 13 | **The offsite-copy freshness reading** (external dead-man / `report-offsite-age`) | the object age is **8.7 h and climbing**; `report-offsite-age` itself runs fine (`15 runs, 0 non-zero`, last 15:30Z) | `/root/.estate-monitor/monitor.log`: `NODATA offsite_object_age_h=8.684h (warn>=26.0 crit>=30.0) … {'key': 'authority/secretary.db.gz', 'error': "no boto3: No module named 'boto3'"}`. The vault box *does* have boto3 1.34.46 (`ssh root@2.28.33.58 python3 -c "import boto3"`), so the failing interpreter is on the authority side of that ssh | the only automated freshness number for the copy that must survive the machine is **NODATA**, and NODATA does not alarm |
| 14 | **Backup cadence** (`authority-offsite-backup`) | last run **2026-10-11T06:49:06Z**; next **2026-10-12T05:23:46Z** | `/var/lib/authority-backup/last-run`: `status=ok, database_verified=ok, gz_bytes=6278791492, remote_last_modified=2026-10-11T06:46:57Z, duration_s=1858` | *not silent* — but it is **once a day**, where the office family ran a copy 4×/day and a ledger/companion push beside it. A day of RPO is a deliberate-looking regression nobody wrote down |
| 15 | **`db-integrity-check`** | **never run on the authority** | crontab on the authority: `17 4 * * 0` (Sundays) — first due **2026-10-18**, and the office ran `17 4 * * *` daily. The target is now a 23.7 GB live database | the 23.7 GB authority has no integrity verification for 6 more days, on a weekly schedule that silently relaxed from daily |
| 16 | **`prune-backups`** | **never run on the authority** | crontab: `45 5 * * *`, first due **2026-10-12 05:45Z**. `disk-guard` reports `backup_dirs: 0`, `retention.invocation_allowed: false` | correct so far — nothing to prune. Recorded because "in crontab" is not "has run" |

**Two things that LOOK silent and are not — stated so the opposite error is not made:**

- The **external dead-man switch is alive.** `authority-deadman.timer` fires every 5 min;
  `journalctl -u authority-deadman` (15:39:29Z):
  `ping http 200 :: offsite=ok age=31823s sent=yes verified=ok db_tables=654 offsite=fresh age=31823s`.
  The office's own `deadman` pings stopped at **04:00:02Z** (office ledger, last `deadman` row), so the
  external alarm covered the gap.
- The **DSH session ingest is alive**, just not from this box: `dsh_sessions` max
  `ingested_at = 2026-10-11T15:25:25.642718Z` (6,384 rows), `dsh_session_events` max rowid 1,876,538 —
  driven by the laptop's hourly scheduled tasks, not by any server-side job (§3, item 2).

---

## §3 — WHAT EXISTED ON THE OFFICE BOX AND HAS NO COUNTERPART NOW

Cross-checked against `132-CRON-INVENTORY.md` §1a (92 scheduled jobs) and the live authority
(`crontab -l` = 21 jobs, 8 systemd timers, 3 of them the new estate ones) plus
`secratary-ts:crontab.before`.

**The sentinel itself — the thing the brief asked about (§3 of the ask):**

- `run-sentinel` (office L16, `*/5`) → `/home/zabz/ceo-kernel/scripts/run-sentinel.sh`. **2991 ledger
  runs, first 2026-09-30T16:15:01Z, last 2026-10-10T22:45:02Z.** It therefore stopped **17 hours
  BEFORE the box froze** — the sentinel was already silent, and the freeze merely made it permanent.
- The code and its state live on the **frozen office disk**: `/home/zabz/ceo-kernel/` (7.7 k, `.git`,
  `ck/`, `scripts/`, `tests/`, `.runtime/`; `ck/sentinel.py` 152,930 B, 2026-10-02). There is **no
  state directory** (`/home/zabz/ceo-kernel/state/` does not exist) — state went to `.runtime/`.
- On the authority there is **no counterpart at all**: `ls /root/ceo-kernel` and `/opt/company/ceo-kernel`
  → *No such file or directory*; `find / -maxdepth 4 -name 'run-sentinel*' -o -name 'ceo-kernel' -type d`
  → empty; no cron line, no timer, no unit. `ck` is not present.
- **What absorbed part of its job instead:** the in-process autopilot subsystems `ceo_tick`
  (8,024 successes, last 15:43:57Z) and `company` (last 15:42:38Z), plus two new timers built during
  this migration — `company-outcome-monitor.timer` (`*-*-* 00/4:07:00`, last 12:07:01Z) and
  `estate-monitor.timer` (every 2 min, verdict `DEGRADED ok=24 info=4 warn=1 crit=0 nodata=2`). So the
  *sensing* is replaced; the sentinel's own rule set, its state and its history are not.

**Office jobs with no counterpart on the authority** (all 21 DEAD ones are also absent, correctly):

| family | office job | state now |
|---|---|---|
| ceo-kernel | `run-sentinel` (L16) | **absent** — code frozen on the office disk |
| ceo-kernel | `converge-authority` (L65) | **absent** |
| owner-channel | `wake-fanout` (L58, every minute, 14,945 runs), `run-wake-sources` (L60), `wake-cost` (L70), `wake-balance` (L101) | **absent.** The cutover's own note says wake was left out on purpose (139-PORT-OWNER-CHANNEL, "COULD NOT BE ENABLED") |
| owner-channel | `sms-responder.py run --send`, `sms-responder.py learn --apply`, `textdecide.py --refresh-catalog` (3 of the 4 commands in office L59) | **absent** — only `sms-inbox.py sync` was installed (`*/5`, 108 runs, rc 0). The office `WAKE_PAUSED`/`BALANCE_WARNED` files (2026-10-11 03:41) show spend was paused *before* the move, so this may be deliberate — but it is not documented in the cron block |
| owner intake | `owner-ask` (L122) — the one-question-with-a-recommendation intake; `promote-owner-texts` (L88) | **absent** (scripts present at `/root/bin/owner-ask.py` and `/root/bin/promote-owner-texts.py`, just not scheduled) |
| CFO | `cfo-shift` (L152), `cfo-scoreboard` (L110), `hours-drift` (L160), `cfo-ask` (L107) | **absent** (scripts present at `/root/bin/cfo-*.py`) |
| shop ops | `audit` (L52), `lpt-audit-weekly` (L150), `lpt-business-report` (L164), `work-integrator` (L92), `lpt-retranscribe` (L156) | **absent** |
| comms/ingest | `website-comms-push-cron` (L49), `comms-refresh` + `comms-refresh-2` (L30/L50), `family_chat_watchdog` (L44), `reconcile-sms-status` (L172), `node-agent-cron` (L9), `git-health-check` (L11), `stripe-key-watch` (L46), `supplier-order-ingest` (L34), `lpt-daily-track` (L168), `chip-resume` (L96) | **absent** |
| daily| `owner-attention-digest` (L10) | correctly **not** ported — `owner_attention_sweep` ticks in-process (last 15:19:09Z) |
| backups | `push-db-offsite`, `company-offsite-push`, `monitor-hetzner-backups` | replaced in part by `authority-offsite-backup.timer` (daily) and `authority-data-offsite.timer` (daily); there is no 4×/day company copy and no Hetzner/restic monitor |
| DANGEROUS | `store-write-check`, `disk-guard` (re-tuned), `prune-backups` (re-pointed), `db-integrity-check` (re-pointed) | correctly not ported in their office form |
| OFFICE-ONLY | `sampler`, `engine-watch`, `probe-phone`, `serve-phone/2`, `check-phone-ui`, `check-security-absence`, `run-ha-truth`, `run-ha-behaviour`, `backup-phoenix-evidence`, `check-phoenix-evidence`, `mesh-health`, `mesh-node-probe` | correctly absent — bound to the office LAN / phone engine |

**One dependency that the office had and this box does not, which is why §2 item 4 is silent:**
`secratary-ts:/home/zabz/quickbooks-agent/` **exists**; `/opt/company/domains/finance/quickbooks-agent`
**does not** (the app's own error string). `/root/accounting-data/live/accounting.db` was copied and is
present, but the resolver never reaches it (§2 #4). Also absent: `/root/bin/guards.yaml` (office
`/home/zabz/bin/guards.yaml`, 2,463 B) and the office `/home/zabz/.lpt-reports/` tracking DB.

---

## §4 — THE TICKING EVIDENCE (the company IS working)

**Verdict: the company is ticking. It is doing real work, at a real cadence, right now.**

**1. The API process and its loop.** `systemctl is-active company-api` → `active`. The autopilot is
in-process with `interval_sec: 900`; `consecutive_failures: 0`, `crash_count: 0`, top-level
`last_run_at = 2026-10-11T15:41:45.622486Z`.

**2. The tick lines in the API's own log** (`journalctl -u company-api`, last 90 min):
`15:30:58 Self-healing sweep`, `15:31:53 Check-in round 1: 3 action(s) · close_task, update_task, save_memory`,
`15:32:22 Lifecycle sweep`, `15:41:45 Self-healing sweep`, `15:43:47 self_healing`,
`15:45:09 Check-in round 1: 2 action(s) · save_memory, update_task`, `15:45:32 Lifecycle sweep`.
The lifecycle sweep is gated per-120 s and logs its own wait (`waiting for the interval (31s of 120s
elapsed, interval=120)`), and it is completing every ~2 min. **Cadence: the 15-minute autopilot tick,
with a 2-minute lifecycle sweep inside it, plus per-minute APScheduler jobs (`_wrap_shabbat_execute`,
executed successfully at 15:38:53Z).**

**3. Rows added over the last hour — the direct answer to §2 of the ask.** Source:
`/root/authority.db` on the authority, `sqlite3 -readonly`.
- `tasks`: 5 rows in the 15:00 hour, 6 in 14:00, 2 in 13:00, 4 in 12:00 (max id 28,262). Newest:
  `28262 orchestrator in_progress "Verify AMR transcription fix end-to-end…" 15:32:43Z`,
  `28261 orchestrator in_progress "P0: inbound MMS audio (AMR) transcription…" 15:28:18Z`,
  `28260 orchestrator done "P0: fleet_location_poll — 414 consecutive failures" 15:12:17Z`.
  **The company is finding its own broken subsystems and filing tasks about them.**
- `tick_telemetry`: 5 rows in the 15:00 hour, 10 in 14:00, 3 in 13:00, and continuous since 05:00
  (5/4/7/19/9/8/9/5/3/10/5 per hour) across **6 distinct agents in the last hour**. Newest rows:
  `dept_world_index complete 15:42:05Z`, `dept_home_life error`, `dept_engineering error` —
  errors are *recorded*, which is the opposite of silence.
- `tick_activity`: only **32 rows, all stamped 2026-10-11T15:42**, with `tick_number 0` — this table is
  effectively unused on the authority (the previous content is from 2026-08). **It is not a usable
  activity source; `tick_telemetry` is.** Said plainly so a later read of `tick_activity` is not taken
  as "the company stopped on 2026-08-14".
- `dsh_sessions`: 6,384 rows, max `ingested_at 2026-10-11T15:25:25Z`. `dsh_session_events`: 1,876,538
  rows. `agent_working_memory`: 84. `agent_metrics`: 2,347 **rows but last written 2026-07-02** — an
  abandoned table, not a stopped tick.
- `events`: **0 rows** — the same on the frozen office database (`secratary-ts … select count(*) from
  events` → 0). Unused on both; not a cutover loss.

**4. Cron is genuinely running** (`/root/.cron-status/runs.tsv`, 1,226 rows, first
`2026-10-11T06:32:33Z`, last `15:46:01Z` — no hour with zero rows since 06:00: 30/85/161/161/161/161/161/161/136).
19 jobs are registered and every one has a last row inside its own schedule:

| job | schedule | runs | non-zero | last | rc |
|---|---|---|---|---|---|
| `lpt-freshness-watchdog` | */1 | 434 | 0 | 15:46:01Z | 0 |
| `sms-inbox` | */5 | 108 | 0 | 15:45:02Z | 0 |
| `mirror-owner-sms` | */5 | 108 | 0 | 15:45:02Z | 0 |
| `cron-target-guard` | */5 | 88 | 1 | 15:45:02Z | 0 |
| `cron-script-guard` | */5 | 88 | 1 | 15:45:02Z | 0 |
| `dialpad-recording-gap` | */5 | 87 | **87** | 15:45:02Z | 1 |
| `reconcile-sent-status` | */10 | 54 | 0 | 15:40:02Z | 0 |
| `dialpad-transcript-gap` | */10 | 43 | **43** | 15:40:02Z | 1 |
| `disk-guard` | */15 | 30 | 0 | 15:45:02Z | 0 |
| `journal-commit` | */15 | 30 | 1 | 15:45:02Z | 0 |
| `guard-registry` | */15 | 30 | **30** | 15:45:02Z | 2 |
| `production-comms-freshness` | */15 | 30 | 11 | 15:45:02Z | 0 |
| `tmpfs-reaper` | */20 | 22 | 0 | 15:40:02Z | 0 |
| `dialpad-harvest-cron` | */30 | 15 | 0 | 15:30:01Z | 0 |
| `dialpad-sms-harvest-cron` | */30 | 15 | 0 | 15:45:02Z | 0 |
| `report-offsite-age` | */30 | 15 | 0 | 15:30:01Z | 0 |
| `ai-gateway-health` | */30 | 14 | **14** | 15:30:01Z | 1 |
| `site-uptime-check-cron` | hourly | 8 | 0 | 15:07:01Z | 0 |
| `lpt-deploy-drift` | hourly | 7 | 0 | 15:17:01Z | 0 |

**Data freshness confirms the harvests write where the company reads** (authority DB):
`dialpad_call_full` newest `date_started_ms` → **2026-10-11 15:40:00Z** (14,009 rows; 13 rows inside
the last 2 h); `dialpad_sms_cache` max `created_at` **15:31:47Z** (135,435 rows). `/root/dialpad-harvest.log`
shows a pass every 30 min (15:31:03Z: `calls stored 213, sessions 55, transcripts requested 100 found 0`).
**`transcripts … found 0` on every pass is a separate open question** — Dialpad is asked for 100
transcripts per pass and returns none; that is ingestion-quality, not silence, and it is not resolved here.

---

## §5 — WHAT I COULD NOT DETERMINE

1. **Whether the company is working *well*.** I can prove ticks, tasks and memory writes. I cannot
   measure whether the 5 tasks/hour are the right 5. No baseline from the office box post-03:25Z
   exists to compare volume against.
2. **The vault-side freshness path.** `estate-monitor` reads the vault's JSON and gets
   `no boto3: No module named 'boto3'`, while `ssh root@2.28.33.58 python3 -c "import boto3"` returns
   1.34.46. I did not determine **which interpreter** that check shells into, and the estate monitor
   therefore reports NODATA for the offsite copy's age — I could not confirm the offsite copy's
   freshness from a second, independent source. `report-offsite-age` (R2 `head_object`, authority side)
   does give a real number: **6,278,791,492 bytes, last_modified 2026-10-11T06:46:57Z**.
3. **`production-comms-freshness` and `lpt-freshness-watchdog` verdicts.** Both run and both report rc 0
   (30 runs / 11 non-zero, 434 runs / 0 non-zero), but I did not open their log bodies. Their rc is
   *not* proof the feeds are healthy — that file is the place a comms-feed silence would show up.
4. **The two office-only alarms for the money layer.** `hours-drift` (100% failure on the office) and
   `cfo-scoreboard` are not installed, so I cannot tell whether the current ledger state would pass
   their checks even after the §2 #4 path is fixed.
5. **`dialpad-call-fresh`'s actual freshness duty.** I confirmed it is not installed, but I did not
   measure whether the 30-minute harvest alone keeps `dialpad_call_full` inside whatever lag the shop
   requires. The nearest evidence: newest call 15:40:00Z at 15:46Z = 6 min.
6. **The office ledger's own integrity at the freeze.** The office `runs.tsv` shows ~65 jobs all
   stamped `2026-10-11T04:00:02Z` — one timestamp for jobs with different schedules, i.e. the office
   wrap recorded a flush rather than per-run times. Any "the office last ran X at Y" reading from that
   window is approximate.
7. **The external healthchecks.io check's configured grace.** The dead-man pings return HTTP 200, but
   I cannot see from here whether the check would still alert if the pings stopped, and the check is
   still named `secratary authority alive` while watching a different machine.
8. **`events` = 0 rows on both boxes.** Same on both, so not a migration loss — but I do not know
   whether that table is retired or broken, and no event-driven worker is visible either way.

---

## APPENDIX — commands that produced every reading

| reading | machine · command |
|---|---|
| subsystem table | `secratary-cloud: python3` over `/opt/company/data/autopilot_state.json` (157,591 B, mtime 15:32Z) |
| office subsystem set | `secratary-ts: python3` over `/home/zabz/personal-secretary-mvp/data/autopilot_state.json` (156,688 B, mtime 03:25Z); `/proc/loadavg` = 0.00 0.01 0.00 |
| cron jobs + ledger | `secratary-cloud: crontab -l` (21 jobs, 31 lines); `awk`/`grep -c` over `/root/.cron-status/runs.tsv` (1,226 rows) |
| timers and units | `secratary-cloud: systemctl list-timers --all`, `systemctl show -p ActiveState -p ExecMainStatus` |
| tick evidence | `secratary-cloud: journalctl -u company-api --since -90min`; `sqlite3 -readonly /root/authority.db` counts on `tasks`, `tick_telemetry`, `tick_activity`, `dsh_sessions` |
| dialpad root cause | `secratary-cloud: cd /opt/company && .venv/bin/python scripts/dialpad-transcript-gap.py --limit 5 --dry-run` → `no such table: dialpad_call_retranscript`; `sed -n '40,50p'` of both gap scripts (`DB = ROOT / "data" / "secretary.db"`); `sqlite3 -readonly /opt/company/data/secretary.db` (`dialpad_sms_cache` = 0) vs `/root/authority.db` (`dialpad_call_retranscript` = 2,417) |
| ledger root cause | `secratary-cloud: sed -n '95,135p' app/services/quickbooks_service.py` and `:44-52`; `grep -rn "Local ledger DB not available" app/` → `app/services/quickbooks_service.py:676,771`; `/root/accounting-data/live/accounting.db` present (21,995,520 B) |
| guard statuses | `secratary-cloud: cat /root/.cron-scripts/status.json`, `/root/.cron-targets/status.json`, `/root/.disk-guard/status.json`, `/root/.guard-registry/cron.log` |
| ceo-kernel absence | `secratary-cloud: ls /root/ceo-kernel /opt/company/ceo-kernel`, `find / -maxdepth 4 -name 'run-sentinel*' -o -name 'ceo-kernel' -type d`; `secratary-ts: ls -la /home/zabz/ceo-kernel/`, `grep run-sentinel /home/zabz/.cron-status/runs.tsv \| tail -3` (last `2026-10-10T22:45:02Z`, 2,991 runs) |
| office last-run per job | `secratary-ts: awk -F"\t" '{last[$2]=$1} END{for(j in last) print last[j]" "j}' /home/zabz/.cron-status/runs.tsv` (95,456 rows) |
| external dead-man | `secratary-cloud: journalctl -u authority-deadman --since -30min` → `ping http 200 :: offsite=ok … offsite=fresh age=31823s` |
| offsite copy | `secratary-cloud: cat /var/lib/authority-backup/last-run`, `cat /var/lib/authority-backup/data-last-run`, `tail /root/report-offsite-age.log` |
| transcript archive | `secratary-cloud: journalctl -u transcript-archive-pull --since -8h`; `systemctl cat transcript-archive-pull.timer` |
| ai gateway | `secratary-cloud: tail -25 /var/log/ai-gateway-health.log` |
| vault boto3 | `secratary-cloud: ssh root@2.28.33.58 "python3 -c 'import boto3; print(boto3.__version__)'"` → 1.34.46; `cat /var/lib/company-offsite/authority-push.json` |

