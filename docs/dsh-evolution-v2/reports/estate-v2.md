MESH-HOST: zabz-tech

# Estate machinery audit v2 — what runs, what is silently dead, what fails to alert

**Measured:** 2026-10-14T00:59Z – 01:15Z (local 2026-10-13T20:59–21:15 EDT) · **Host I ran on:** `zabz-tech` (Windows, `COMPUTERNAME=ZABZ-TECH`) · **Method:** read-only measurement over SSH from `zabz-tech`. `[M]` = measured live by me. `[DOC]` = quoted from a document, not reproduced.

**Two things about this round up front, because they change how the rest reads.**

1. **The brief's own baseline paths do not exist.** `docs/dsh-evolution/30-systems-and-autonomy-audit.md` and `docs/dsh-evolution-v2/PROGRAM.md` are absent from this checkout's HEAD (branch `mesh/broker-host-cloud-default-20261013`). The 30- audit exists only inside commit `75ffbeef` (2026-10-13T13:29Z) and I read it there. There is no `docs/dsh-evolution-v2/` anywhere I reached. **This is not "two days after" that round — the 30- audit measured 2026-10-13 13:07–13:12Z, and I measured 2026-10-14 00:59–01:15Z, i.e. 11.8 hours later.** Every "delta" below is against an ~12-hour-old baseline, not a two-day one.
2. **`/home/zabz/evolution-corpus-v2/` did not exist on the authority** when I started. I created only the directory path needed for the one permitted file. `/home/zabz/evolution-corpus/` (v1) does exist.

---

## 1. Running vs claimed — every service/timer/cron that matters, on every node I reached

### Node reachability — all six answered; none refused

| node | ssh alias | hostname returned | kernel | result |
|---|---|---|---|---|
| authority | `secratary-cloud` | `secratary-cloud` | Linux 7.0.0-38 | **answered** `[M]` |
| frozen anchor | `secratary-ts` | `secratary` | Linux 7.0.0-38 | **answered** `[M]` |
| linux worker | `linux-pc-ts` | `zabz-tech-linux` | Linux 6.8.0-111 | **answered** `[M]` |
| mac worker | `mac-mini-ts` | `LakewooechsMini` | Darwin 25.5.0 (macOS 26.5.2) | **answered** `[M]` |
| this node | `desktop-ts` | `zabz-tech` | Windows | **answered** (local + ssh) `[M]` |
| owner laptop | `laptop-ts` | `zabz-yoga` | Windows | **answered** `[M]` |

No node refused. **The baseline's finding #6 — "the authority was reachable only through the retired key `~/.ssh/retired-20260914/...` because `ssh secratary-cloud` from the Mac mini is `Permission denied (publickey)`" — is not reproduced from this node**: `ssh -o BatchMode=yes -o ConnectTimeout=8 secratary-cloud hostname` returned `secratary-cloud`, rc=0. The key in `~/.ssh/config` for `secratary-cloud` is `~/.ssh/id_ed25519_hetzner`. That may still be true *from the Mac mini* specifically; I measured it from `zabz-tech` only.

### `secratary-cloud` — THE AUTHORITY (Linux) `[M]` 01:02–01:09Z

| system | what it is | running? | last run | last result |
|---|---|---|---|---|
| `company-api` | the company API | **active/enabled** | started 2026-10-13T18:52:23Z | `NRestarts=0`; `MemoryMax=infinity`; `MemoryPeak=9.70 GiB` (9,702,137,856 B) `[M]` |
| `/root/authority.db` | sole company DB | live | mtime 01:07:35Z | **26,960,019,456 B**; WAL 67,108,864 B; shm 327,680 B `[M]` |
| `cron` | the cron daemon | **active/enabled** | runs every minute | `runs.tsv` 15,007 rows; last row 01:03:01Z `[M]` |
| `mesh-broker` | placement broker, loopback `:3091` | **active/enabled** | started **2026-10-12T13:58:34Z** | `/healthz` `ok:true nodes:5 reads:175 readFailures:73`; 6 live leases `[M]` |
| `estate-monitor.timer` | 31-metric silent-failure instrument | **active/enabled** | 01:04:03Z (every 2 min) | `verdict=CRITICAL ok=20 crit=5 escalated=0` `[M]` |
| `estate-alerts-to-journal.timer` | **new** reader: files CRIT metrics as journal entries | **active/enabled** | 01:02:00Z (every 10 min at `:02,:12,…,:52`) | 3 entries filed lifetime `[M]` |
| `authority-deadman.timer` | off-box heartbeat → healthchecks.io | **active/enabled** | 00:57:56Z (every 5 min) | ping body written by `authority-deadman.py` `[M]` |
| `transcript-archive-pull.timer` | hourly transcript archive | **active/enabled** | `LastTrigger=2026-10-14T00:23:15Z`; service actually ran **00:53:18→00:56:36Z** | `Result=success ExecMainStatus=0`; `status.json` `pull_rc=0 check_rc=0 ok=true` `[M]` |
| `authority-report-offsite-age.timer` | offsite freshness | active | 00:55:04Z | `ExecMainStatus=0` `[M]` |
| `deployed-drift-check.timer` | deployed-vs-repo drift | active | 00:47:02Z | — `[M]` |
| `company-outcome-monitor.timer` | outcomes | active | 00:07:01Z | — `[M]` |
| `authority-offsite-backup.timer` / `authority-data-offsite.timer` | offsite copies | active | 05:21Z / 06:33Z on 10-13 | — `[M]` |
| `lpt-email-sweep.timer` / `lpt-marketplace-orders.timer` / `lpt-owner-attention.timer` | business jobs | active | 16:47Z / 05:11Z / 14:21Z on 10-13 | — `[M]` |
| `disk-guard` | cron `*/15`, writes `state.json`+`guard.log` | runs | 01:00:01Z | **rc=1** every run since 10-13T16:00Z `[M]` |
| `fa-index-refresh` | cron `8,23,38,53`, file-path index | runs | 00:53:01Z | **rc=0**; `.faindex/built_at.txt = 2026-10-14T00:53:02Z` `[M]` |
| `fa-index-freshness` | cron `:22`, guards the above | runs | 00:22:01Z | rc=0 `[M]` |
| `comms-refresh` / `comms-refresh-2` | cron `7,37` / `12,42` | runs | 01:07Z | `coverage_ok:true total:180,108`; `comms.db` 226,340,864 B `[M]` |
| `run-sentinel` / `sentinel-freshness` | cron `*/5` | runs | 01:05:01Z | rc=0 / rc=0 `[M]` |
| autopilot (900 s tick, in-API) | the autonomy loop | **live** | `last_run_at 2026-10-14T01:04:22Z`, `run_count 88` | `consecutive_failures 0` `[M]` |
| failing cron jobs, last 400 rows | | | | `config-sync-status` **rc=1/3**, `disk-guard` **rc=1**, `journal-commit` **rc=1**, `guard-registry` **rc=3**, `lpt-deploy-drift` **rc=3** `[M]` |
| `systemctl --failed` | | | | **0 loaded units listed** `[M]` |
| `df` | | | | `/dev/sda1 75G, 68G used, 4.0G avail, 95%`; swap **3561/4095 MB**; Mem 15,605 MB total `[M]` |

### `secratary` — the FROZEN office anchor (Linux) `[M]` 01:03Z — frozen by decision, not broken

`settings/machines/host-posture.tsv` and `AGENTS.md` §5 decide this. Reported as frozen; not "fixed".

| system | running? | note |
|---|---|---|
| `cron.service` / `cron.socket` | **inactive / masked** (`/etc/systemd/system/cron.service -> /dev/null`, since 2026-10-11T20:23Z) | **by design** `[M]` |
| `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard`, `phone-engine` | **inactive / masked** | **by design** `[M]` |
| crontab | present, **zero job lines** — only the FROZEN banner naming the saved copies | by design `[M]` |
| `mesh-broker` | **active/enabled**, MainPID 409399, started **2026-10-11T23:34:49Z**, listening `127.0.0.1:3091` | **not** node-local hygiene — see §2 and §5 `[M]` |
| `fa-index.timer` | active, last **01:07:42Z**, `built_at 2026-10-14T00:52:46Z` | node-local hygiene, named in the crontab banner `[M]` |
| `estate-monitor.timer` | active, last 01:02:04Z | named in the banner `[M]` |
| `tmp-reaper.timer`, `trunk-check.timer` | active, last 01:00:00Z / 00:48:31Z | named in the banner `[M]` |
| `lpt-email-sweep.timer`, `lpt-books-nightly.timer`, `lpt-owner-attention.timer` | active, last 16:49Z / 07:27Z / 14:12Z on 10-13 | **business** timers, not named as node-local in the banner `[M]` |
| `secretary-backup.service` | **failed** since **2026-10-11T03:15:49Z** (2 days), `status=143`, 5 G mem peak, 33.2 G written | `[M]` |
| `systemctl --failed` | 1 unit (`secretary-backup.service`) | `[M]` |
| `df` | 467G, 414G used, 34G free, **93%** | `[M]` |

### `zabz-tech-linux` (`linux-pc-ts`) `[M]` 01:05Z

| system | running? | last run | result |
|---|---|---|---|
| `fa-index.timer` | active | 2026-10-13T20:55:05 EDT = **00:55:05Z** | `.faindex/built_at.txt = 2026-10-14T00:55:11Z`, paths 31,704 `[M]` |
| `lpt-drive-watch.timer` | active | 20:58:54 EDT | — `[M]` |
| crontab | 2 jobs: `node-agent-standalone-cron.sh` `*/30`; `push-dsh-sessions.mjs --transport http` `*/30` | — | `[M]` |
| `systemctl --failed` | **0** | | `[M]` |
| `df` | 468G, 419G used, 25G free, **95%** | | `[M]` |

### `LakewooechsMini` (`mac-mini-ts`, macOS 26.5.2) `[M]` 01:05Z

| system | running? | note |
|---|---|---|
| `com.lakewoodphone.harness-autosync` | **failing, status 1** | baseline said failing; **still failing** `[M]` |
| `com.lakewoodphone.repo-sync` | **failing, status 1** | **still failing** `[M]` |
| `com.personalsecretary.nodeagent` | **failing, status 1** | **still failing** `[M]` |
| `com.lakewoodphone.journal-daily` | ok, status 0 | `[M]` |
| `com.lakewoodphone.dsh-session-sync` | ok, status 0 | `[M]` |
| `com.lakewoodphone.yocheved-harness` | renamed `.disabled-by-mesh-20260916` | deliberately disabled `[M]` |
| crontab | none (`crontab: no crontab for lpt`) | `[M]` |
| `~/.faindex`, `~/.fsearch` | **do not exist** | no search index on this node `[M]` |
| `~/.dsh/skills` | **present**, 7 skills | **contradicts the baseline** ("`~/.dsh/skills` is not installed on the Mac") `[M]` |
| `df /` | 228Gi, 12Gi used, 38Gi avail, 24% | `[M]` |

### `zabz-tech` — this node (Windows) `[M]` 01:07Z

| task | state | last run (UTC) | LastTaskResult |
|---|---|---|---|
| `DSH search index refresh` | Ready | 2026-10-14T00:39:01Z | **1 (fail)** |
| `DSH Engine Vitals (5m)` | Ready | 2026-10-14T01:03:06Z | **3 (fail)** |
| `DSH Metrics Sampler` | Ready | 2026-10-14T01:06:01Z | **2147942667 / 0x800710E0 (refused)** |
| `LPT-greenfeld-copy` | Ready | 2026-10-14T01:02:58Z | **3 (fail)** |
| `PersonalSecretary-DailyPartnerSync` | Ready | 2026-10-13T22:00:01Z | **1 (fail)** |
| `DshChatScan` | Ready | 2026-09-10T23:59:00Z | **1**, and 34 days stale |
| `PersonalSecretary-PushDSHSessions` | Ready | 2026-10-14T01:05:01Z | 0 |
| `PersonalSecretary-PushVSCodeChats` | Ready | 2026-10-14T00:30:17Z | 0 |
| `DSH Origins Proxy`, `PersonalSecretary-DesktopSshCloudflareTunnel(Logon)` | **Running** | 10:53–10:55 EDT | 267009 (running) |
| `~/.faindex` | **absent** | | |
| `~/.fsearch/index.db` | 4,885,487,616 B | mtime 2026-10-11T23:57:48 EDT = **2026-10-12T03:57Z** | **~45 h stale** |
| `~/.fsearch/RETIRED-*.db` | **~21 GB** of retired indexes | 2026-09-14 | `[M]` |
| `C:` | free 193,862,045,696 / total 1,021,821,579,264 (19%) | | `[M]` |

### `zabz-yoga` (`laptop-ts`, Windows, the owner's machine) `[M]` 01:06Z

| task | state | last run (UTC) | LastTaskResult |
|---|---|---|---|
| `DSH unified-search refresh` | Ready | 2026-10-14T00:05:52Z | **1 (fail)** |
| `DSH Engine Vitals (5m)` | Ready | 2026-10-14T01:03:41Z | **1 (fail)** |
| `DSH MCP Health (5m)` | Ready | 2026-10-14T01:05:51Z | **64** |
| `DSH Engine Pin Install` | Ready | 2026-09-30T19:26:48Z | **1** |
| `DSH Mesh 0700 Restart` | Ready | 2026-09-17T07:00:00Z | **1** |
| `DSH Multi-Window Launcher` | Ready | 2026-10-07T19:41:06Z | **1** |
| `VSCodeUpdate-20260803` | Ready | 2026-08-03T15:50:59Z | **1** |
| `DSH Metrics Sampler Watchdog` | **Running** | 2026-10-14T01:06:01Z | 2147946720 |
| `DSH Phone Gate` | Ready | 2026-10-14T01:07:01Z | 267009 |
| `PersonalSecretary-PushDSHSessions` | **Running** | 2026-10-14T01:05:01Z | 267009 |
| `PersonalSecretary-PushVSCodeChats` | Ready | 2026-10-14T00:26:15Z | **0 — success** (see §5, it is not) |
| `~/.faindex` | **absent**; `~/.dsh/skills` present | | `[M]` |
| `C:` | free **8,570,925,056** / total 510,915,506,176 → **1.8% free** | | `[M]` |

---

## 2. Delta against the 2026-10-13 baseline (commit `75ffbeef`, measured 13:07–13:12Z)

Row by row against that audit's §1 table. Baseline numbers are `[DOC]`; mine are `[M]`.

| baseline row | baseline claim `[DOC]` | measured now `[M]` | verdict |
|---|---|---|---|
| `company-api` | live, `NRestarts=0`, **`MemoryMax=infinity`**, peak 9.09 GiB | live, `NRestarts=0`, **`MemoryMax=infinity`**, peak **9.70 GiB** | **unchanged; peak up 0.61 GiB** |
| `/root/authority.db` | 25.85 GB, growing 2.3 MB/h | **26,960,019,456 B**; monitor's own `authority_db_shrink_mb` note: `previous size 26,806,702,080 B at 01:06:02Z; delta +153,317,376 B` (+153 MB in 68 s during activity) | **grew; the 2.3 MB/h figure is not the rate I see when the box is busy** |
| autopilot | last_run 13:06:31Z, run_count 15 | `last_run_at 2026-10-14T01:04:22Z`, **`run_count 88`**, cf 0 | **live** |
| `tick_telemetry` | 34,139 rows, 85 agents | not re-counted (see §8, could-not-determine) | not reproduced |
| `mesh-broker :3091` | live on the **office box**; the **cloud unit is `inactive`/`disabled` with nothing on `:3091`** | **BOTH are active and both are listening on `127.0.0.1:3091`** — cloud pid 20544 since 2026-10-12T13:58:34Z, office pid 409399 since 2026-10-11T23:34:49Z | **CHANGED — split-brain, see §5** |
| 3 mesh nodes live | zabz-tech / yoga-1 / tech-linux ok 143/197/96 ms | broker reports **nodes:5**, `reads 175 readFailures 73` (**42% of capacity reads fail**) | **changed: 5 nodes, but the read-failure rate is worse than the baseline's 18/45** |
| `secratary` · `lakewooechsmini` | frozen · live-but-gated, both `HTTP 403` from the broker | not re-tested per-node from the broker (no `/nodes?fresh=1` dump captured for those two) | not reproduced |
| cron | `runs.tsv` 11,374 rows, last 13:08:01Z | **15,007 rows**, last 01:03:01Z | **live and growing** |
| timers | estate-monitor 2 min · deadman 5 min · offsite daily · transcript-archive hourly | all four confirmed **plus** two that did not exist in the baseline: **`estate-alerts-to-journal.timer`** (10 min) and **`deployed-drift-check.timer`** | **changed: 2 new timers** |
| `estate-monitor` | `verdict=CRITICAL crit=4 … escalated=0` every 2 min | **still exactly that**: `verdict=CRITICAL ok=20 crit=5 escalated=0`, `escalated=0` on every run measured; code still hard-codes `conditions_allowed_to_escalate:["public_health_status"]` | **unchanged in the producer; superseded by a new consumer — §5** |
| sentinel + absence monitor | live | `run-sentinel` rc=0, `sentinel-freshness` rc=0, last 01:05:01Z | **live** |
| `fa` + journal + comms indexes | paths 13:08:01Z, tags 13:08:02Z, comms.db 224.9 MB | `.faindex` built **00:53:02Z**; `comms.db` **226,340,864 B** mtime 01:07Z, `coverage_ok:true` | **live/fresh** |
| session ingest | `dsh_sessions` 6,935, max ingested 13:08:36Z | not re-counted | not reproduced |
| `wake-fanout` | 205 `wake-failed/` dirs; blocked `daily-cap` while spend was 5.18/25 | `wake-fanout` run hourly-ish, `wake-balance` and `wake-cost` present and rc=0; the 25-vs-5 cap drift note is still quoted in the crontab comment; not re-counted | partially reproduced |
| `mesh-health` · `harness-verify` · `mesh-e2e.ps1` · `profile-gate.mjs` | dead/unreferenced | not re-checked | not reproduced |
| `engine-vitals.mjs` | unreferenced | `DSH Engine Vitals (5m)` **is scheduled and failing on both Windows nodes** (rc 3 on `zabz-tech`, rc 1 on `zabz-yoga`) | **changed: it runs now — and fails** |
| 6 launchd agents, "3 failing silently" | autosync, repo-sync, nodeagent exit 1 | **all three still exit 1**, unchanged, still no ledger | **unchanged** |
| **`175-STATE-OF-THE-ESTATE` "does not exist"** | **retracted claim** | **IT EXISTS.** Authority HEAD contains `docs/mesh/175-STATE-OF-THE-ESTATE-2026-10-12.md`, added in commit `e2322825` ("175: the state of the estate as measured 2026-10-12 05:05-05:20Z …") | **baseline was WRONG** |
| **`work_metrics` "does not exist"** | claim | **still does not exist**: authority.db has 235 tables, none named `work_metrics`; nearest are `agent_metrics`, `anomaly_log`, `tick_activity`, `tick_telemetry`. The office `secretary.db` likewise has only `agent_metrics`. `git log --all -S work_metrics` returns **only** `75ffbeef` — the audit commit that says it is absent | **true now, and it was never true that it existed** |
| journal: ~120 divergent refs, 121 base-id collisions, open pain 162/366/373/393 | `[DOC]` | **canonical authority checkout: 0 collisions in 4,006 entries.** Divergence has moved to the peripherals: desktop 106 remote refs, yoga 119, office 102, linux-pc 97, mac 139; authority clone has **13 refs total** (7 remotes, 6 heads). Open pain: authority 545, yoga 539, desktop 511, linux-pc 446, office 433, mac 191 | **collisions FIXED on the canonical clone; ref divergence unchanged elsewhere** |
| `journal-union.py` exists, nothing schedules it | `[DOC]` | **could not reproduce: `find / -xdev -name "journal-union*"` on the authority returns nothing, and a recursive search on the desktop returns nothing.** | **baseline claim not reproducible** |
| `cron-liveness.py` exists, not scheduled | `[DOC]` | **still exactly true** — `/root/bin/cron-liveness.py`, 6,076 B, mtime 2026-10-13T07:04Z; `crontab -l \| grep -c cron-liveness` = **0** | **unchanged** |
| "~/.dsh/skills is not installed on the Mac" | `[DOC]` | `mac-mini-ts:~/.dsh/skills` **exists with 7 skills** (mtime 2026-10-13T10:23) | **baseline was wrong** |

**Newly dead / newly failing since the baseline (all `[M]`):** `DSH search index refresh` on `zabz-tech` (rc=1), `DSH unified-search refresh` on `zabz-yoga` (rc=1), `DSH Engine Vitals (5m)` failing on both Windows nodes, `LPT-greenfeld-copy` (rc=3), `PersonalSecretary-DailyPartnerSync` (rc=1). **Newly alive:** `estate-alerts-to-journal`, `deployed-drift-check`, both mesh brokers, `DSH Engine Vitals`.

---

## 3. The disk, properly

### 3a. `df` now `[M]` 01:02:51Z

```
/dev/sda1        75G   68G  4.0G  95% /
tmpfs           7.7G  1.4G  6.3G  19% /tmp     # /tmp is a 7.7 GB RAM tmpfs
/dev/sda15      253M  154K  252M   1% /boot/efi
Mem: 15605 total, 3969 used, 11635 available;  Swap: 3561 used of 4095
```

`disk-guard`'s own `status.json` at 01:00:02Z: `free_bytes 4,304,486,400`, `used_pct 90.5`, `free_gb 4.01`. **`disk-guard` says 90.5% and `df` says 95% because they divide by different denominators** (df's `Use%` is `used/(used+avail)`, excluding the reserved blocks). Both are correct; neither is a contradiction, and the baseline's "disagreed by 5–11 points" is this, not a bug.

### 3b. Top consumers by path `[M]` 01:04Z

```
du -xhd1 /root   = 41G      du -xhd1 /opt    = 17G      du -xhd1 /tmp  = 1.4G
du -xhd1 /var    = 178M     du -xhd1 /home   = 3.9G
```
Largest single paths:

| path | size | note |
|---|---|---|
| `/root/authority.db` | **26,960,019,456 B** | the DB. `-wal` 67,108,864 B |
| `/swapfile` | 4,294,967,296 B | |
| `/root/work` | 5.2 G | worktrees |
| `/root/git-rescue-20261012` | 2.4 G | 17+ recovery bundles |
| `/opt/company/data/chromadb/chroma.sqlite3` | 2,404,261,888 B | |
| `/root/repos` | 1.9 G | |
| `/root/finance-fleet-20261013` | 1.3 G | two identical `pack-68a3df3e…` 286,306,048 B packs |
| `/root/code` | 1.2 G | |
| `/opt/company/data/mem0/.../data_level0.bin` | 773,101,668 B | |
| `/root/.dsh` | 891 M | |
| `/opt/company/archive/lpt-transcripts` | **6.8 G** | the archive (baseline: a "6.27 GB temp") |
| `/root/accounting-data`, `/root/.cfo`, `/root/.fsearch` | 431 M / 423 M / 217 M | |
| `/root/backups`, `/root/.sms-inbox`, `/root/.cache` | 34 M / 110 M / 167 M | |

`/root` is 41 G of which the database is 27 G: **the DB is 66% of the home tree, and `/root` + `/opt` + `/home` ≈ 62 G of the 68 G used.** Nothing here is a stray temp file; the growth is the database, the archive, and the accumulating agent scratch (`git-rescue-*`, `finance-fleet-*`, `repos`, `work`).

### 3c. The 4 GB — the timeline, with timestamps `[M]`

**The brief's premise is nearly right but the window is wrong, and the episode was 10× longer than "between 00:23Z and 00:56Z".** Raw readings:

`/root/.disk-guard/guard.log` (cron, `*/15`, timestamps in the file):
```
2026-10-13T20:00:02Z  ALARM  / at 92.9% (2.2 GB free, 2288 MB), warn threshold 90%
2026-10-13T20:15:01Z  ALARM  CRITICAL: / at 96.2% (0.0 GB free, 0 MB)      <-- ZERO FREE
...
2026-10-13T23:45:02Z  ALARM  CRITICAL: / at 96.4% (0.0 GB free, 0 MB)
2026-10-14T00:00:02Z  ALARM  CRITICAL: / at 96.4% (0.0 GB free, 0 MB)
2026-10-14T00:15:03Z  ALARM  CRITICAL: / at 98.5% (0.0 GB free, 0 MB)
2026-10-14T00:30:02Z  ALARM  CRITICAL: / at 97.0% (0.0 GB free, 0 MB)
2026-10-14T00:45:02Z  ALARM  CRITICAL: / at 97.1% (0.0 GB free, 0 MB)
2026-10-14T01:00:02Z  ALARM  / at 90.5% (4.0 GB free, 4105 MB), warn threshold 90%   <-- RECOVERED
```

`estate-monitor` journal (every 2 min, `journalctl -u estate-monitor -o short-iso`):
```
2026-10-14T00:20:13Z  CRIT disk_free_deficit_gb=10.0GiB  (monitor verdict at that run, per P3179)
2026-10-14T00:48:03Z  CRIT disk_free_deficit_gb=10.0GiB "0.0 GiB free"  disk_used_pct=97.08%  (72 GiB of 74)
2026-10-14T00:50:03Z  CRIT disk_free_deficit_gb=6.947GiB "3.053 GiB free"  disk_used_pct=91.81% (68 GiB of 74)
2026-10-14T00:52:06Z  CRIT disk_free_deficit_gb=6.947GiB "3.053 GiB free"  disk_used_pct=91.81%
2026-10-14T00:54:01Z  CRIT disk_free_deficit_gb=5.953GiB "4.047 GiB free"  disk_used_pct=90.48% (67 GiB of 74)
2026-10-14T00:56:07Z  CRIT disk_free_deficit_gb=5.976GiB "4.024 GiB free"  disk_used_pct=90.51%
2026-10-14T01:02:03Z  CRIT disk_free_deficit_gb=6.007GiB "3.993 GiB free"  disk_used_pct=90.55%
2026-10-14T01:04:03Z  CRIT disk_free_deficit_gb=6.012GiB "3.988 GiB free"  disk_used_pct=90.56%
```

**So:**
- The disk was at **literal 0 bytes free continuously from 2026-10-13T20:15:01Z to 2026-10-14T00:48:03Z — 4 h 33 min.** The 00:23:15Z archive refusal was in the *middle* of a long zero-free episode, not a short one.
- **The 4 GB returned in two steps: 00:48:03Z → 00:50:03Z (+3.053 GB) and 00:52:06Z → 00:54:01Z (+0.994 GB).** It has held at ~3.99–4.05 GB since, drifting down ~0.02 GB/2 min (≈14 MB/h).
- **The reclaim finished *before* the archive pass started.** `transcript-archive-pull.service` started at **00:53:18Z**, and the pass's own spool hygiene freed only **11,939,840 B (11.9 MB)**:
  ```
  2026-10-14T00:56:36Z spool: removed secratary.tar (10240 bytes)      -- ok=1
  2026-10-14T00:56:36Z spool: removed zabz-tech-linux.tar (921600)     -- ok=1
  2026-10-14T00:56:36Z spool: removed zabz-tech.tar (3358720)          -- ok=1
  2026-10-14T00:56:36Z spool: removed zabz-yoga.tar (7649280)          -- ok=1
  2026-10-14T00:56:36Z spool: freed 11939840 bytes
  ```
  **So the archive did not free the 4 GB, and did not need to: the space was already there when it started.**

**What freed it: I could not determine, and the reason I could not determine it is itself the finding.** Every automatic reclaim path is either a no-op or forbidden:
- `tmpfs-reaper` (cron `*/20`) targets **`/tmp`, a RAM tmpfs** — freeing it cannot free `/`. Its log shows `ok free=6391MB (floor 600MB) - nothing to do` at 00:20, 00:40, 01:00. `[M]`
- `prune-backups` (cron `45 5 * * *`) — last logged line: `prune-backups: FLOOR BREACHED - only 8057340 KB free on the backup volume (floor 12582912 KB). Pruned NOTHING; investigate what filled the disk. 0 entry/entries present.` It prunes **zero** entries because there are **zero** backup dirs. `[M]`
- `disk-guard`'s own `status.json` records the retention script as **`"invocation_allowed": false`** — the guard is configured *not* to run the reclaim path. `[M]`
- The archive's floor check refused and printed:
  `TRANSCRIPT ARCHIVE REFUSED TO START — not enough free space to stage a pull` / `free : <have_bytes> bytes` / `Lower TRANSCRIPT_MAX_BYTES, free space, or raise the floor deliberately.` `[M]` (from `/opt/company/archive/tools/transcript-archive-run.sh`)

**And no log survives from the window.** `journalctl --since "2026-10-13 04:00:00" --until "2026-10-14 00:47:00"` returns **exactly 1 line**. The persistent journal is a single 8,388,608-byte file, `/var/log/journal/9ba8daa0e9094672976673925c5af5a0/system.journal`, whose **newest entry is 2026-10-13T03:44:41Z**; active logging is going to the volatile `/run/log/journal` (43 MB), which holds **120,639 lines in the 00:00 hour** (i.e. from 00:47:13Z onward) and 5,462 in the 01:00 hour. `rsyslogd` itself reported the failure at **00:47:19Z**: `file '/var/log/syslog'[7] write error … OS error: No space left on device`. **The disk-full episode deleted the record of itself.**

### 3d. Does the free-space guard have an escalation path that reaches a human? **No. Proven both ways.**

The chain that exists:
1. `disk-guard` (cron `*/15`) → writes `/root/.disk-guard/status.json` + `guard.log`, `rc=1`. Recorded in `/root/.cron-status/runs.tsv`. **No message.** `[M]`
2. `estate-monitor` (systemd, 2 min) → computes `disk_used_pct`, `disk_free_deficit_gb` as **CRIT** with streaks of **552** and **588** consecutive runs, and prints `escalated=0` on every run. `estate-monitor.py` line 1359 still hard-codes `conditions_allowed_to_escalate: ["public_health_status"]`. `[M]`
3. **NEW:** `estate-alerts-to-journal.py --apply`, every 10 min since 2026-10-13T14:07Z, reads `state.json` (all 31 metrics, not just the alert-mode one) and files one journal `pain` entry per episode. Its ledger (`/root/.estate-monitor/journal-filed.json`) shows it has filed exactly three, and **two of them are the disk**:

```
disk_used_pct         episode 1  at 2026-10-13T14:07:23Z  "critical (86.74 %) across 224 consecutive runs"
disk_free_deficit_gb  episode 1  at 2026-10-13T15:32:15Z  "critical (5.546 GiB) across 303 consecutive runs"
swap_used_pct         episode 1  at 2026-10-14T00:12:00Z  "critical (82.56 %) across 124 consecutive runs"
```

**But it stops there, by its own design.** Its docstring: *"It does not text, email or call anyone. It writes a journal entry and stops. If the owner ever needs to know, that is the owner queue's job, one question at a time -- not this."* And `owner_decision_queue` on the authority holds **493 rows, newest at 2026-10-13T19:50:31Z — none of them about disk, memory, the archive, or the broker.** `[M]`

The only escalation that reaches *anything* outside the box is `alerts.jsonl` / the `ESCALATED` flag file, and both hold **exactly one metric, `public_health_status`, three rows lifetime**:
```
{"at": "2026-10-12T09:10:08Z", "metric": "public_health_status", ... "transport": "syslog-only, no outbound message"}
{"at": "2026-10-12T13:14:40Z", "metric": "public_health_status", ... "transport": "syslog-only, no outbound message"}
{"at": "2026-10-13T04:24:03Z", "metric": "public_health_status", ... "transport": "syslog-only, no outbound message"}
```
**The transport field says it: `syslog-only, no outbound message`.** A disk at 0 bytes for 4 h 33 min produced: one `rc=1` in a TSV, two journal file entries no human reads, and no message. **That is the proof, both directions — there is a producer, there is a filter, there is a new reader, and there is still no transport to a human.**

---

## 4. The archive, proved current — run with the deployed environment

**Why this matters:** `AGENTS.md` §1's commands (`ssh secratary-ts 'python3 ~/code/harness-config/scripts/transcript-archive-server.py --stats'`) point at the **frozen office box** and would examine the wrong store. The archive moved to the authority at the 2026-10-11 cutover. The deployed environment is `/etc/transcript-archive.env` plus the exports in `/usr/local/bin/transcript-archive-pass.sh`:

```
HOME=/root
TRANSCRIPT_ARCHIVE_ROOT=/opt/company/archive/lpt-transcripts
TRANSCRIPT_SCRIPTS=/opt/company/archive/tools
TRANSCRIPT_STATE_DIR=/var/lib/transcript-archive
TRANSCRIPT_ALIAS_SECRATARY=secratary-ts   TRANSCRIPT_ALIAS_ZABZ_YOGA=zabz-yoga-1
TRANSCRIPT_ALIAS_ZABZ_TECH=zabz-tech      TRANSCRIPT_ALIAS_ZABZ_TECH_LINUX=linux-pc-ts
TRANSCRIPT_ALIAS_LAKEWOOECHSMINI=mac-mini-ts
TRANSCRIPT_MAX_BYTES=500000000
```
The env file's own comment explains why the alias matters: *"leaving it `local` makes the pull archive the AUTHORITY'S OWN files under the office box's name and record a contact row with `newest_source_mtime=0.0` — which reads as perfectly current forever."*

**The timer `[M]`:**
```
transcript-archive-pull.timer   OnCalendar=*:23  Persistent=true  AccuracySec=1min
LastTriggerUSec = Wed 2026-10-14 00:23:15 UTC
NextElapseUSecRealtime = Wed 2026-10-14 01:23:00 UTC
```

**The last pass `[M]`** — `Result=success`, `ExecMainStatus=0`, `ExecMainExitTimestamp=2026-10-14T00:56:36 UTC`:
```
2026-10-14T00:53:18Z  systemd[1]: Starting transcript-archive-pull.service ...
2026-10-14T00:56:36Z  transcript-archive-pass: run.sh exit=0 at 2026-10-14T00:56:36Z
2026-10-14T00:56:36Z  Finished transcript-archive-pull.service ... (1min 15.359s CPU over 3min 18.370s wall, 593.7M memory peak)
```

**`/var/lib/transcript-archive/status.json` `[M]`:** `"at": "2026-10-14T00:53:18Z"`, `pull_rc: 0`, `check_rc: 0`.

**`manifest.sqlite` `[M]`** (53,362,688 B, mtime 00:59):
```
object 48,797   arrival 55,489   machine_contact 584   ingest_run 384   quarantine 0
machine_contact (max newest_source_mtime, rows): secratary 1791937501.57 (162) · zabz-tech 1791939384.73 (135)
  · zabz-yoga 1791939353.45 (121) · zabz-tech-linux 1791916628.68 (116) · lakewooechsmini 1791903199.48 (50)
```

**The archive's own `--check`, with those variables exported `[M]` 01:05:58Z:**
```
CHECK_RC=0
{ "ok": true, "checked_at": "2026-10-14T01:05:58.916917+00:00",
  "machines_reporting": 5, "gaps": [], "silent": [] , "coverage": [ 13 (machine,kind) rows ] }
```
**Verdict: neither GAP (exit 1) nor SILENCE (exit 2). Exit 0, `gaps: []`, `silent: []`. The archive is current** — and I re-ran the check myself at 01:05:58Z rather than only quoting the 00:53 status file.

**Coverage, all 13 rows `[M]`:** `zabz-tech/dsh-sessions` 4,498 files (last 00:56:34Z) · `zabz-yoga/dsh-sessions` 2,034 (00:56:21Z) · `zabz-tech/copilot-chats` 35,271 (**last 2026-10-12T08:32:28Z**) · `zabz-yoga/copilot-chats` 8,184 (**last 2026-10-11T19:37:05Z**) · `secratary/dsh-attachments` 1,372 (00:53:19Z) · `secratary/dsh-sessions` 613 (00:53:23Z) · `zabz-tech/dsh-attachments` 1,351 (00:54:17Z) · `zabz-yoga/dsh-attachments` 968 (2026-10-13T17:59:11Z) · `zabz-tech-linux/dsh-sessions` 605 (00:54:56Z) · `zabz-tech-linux/dsh-attachments` 198 (2026-10-13T15:24:14Z) · `lakewooechsmini/dsh-sessions` 324 (2026-10-13T15:24:26Z) · `lakewooechsmini/copilot-chats` 42 (2026-10-13T01:55:33Z) · `lakewooechsmini/dsh-attachments` 24 (2026-10-13T14:25:20Z).

**Two live qualifications, both measured, neither reported as health by the check:**
1. **`zabz-yoga/copilot-chats` has not moved since 2026-10-11T19:37:05Z — 30 hours** — while that machine's `PersonalSecretary-PushVSCodeChats` reported **`LastTaskResult=0` (success)** at 2026-10-14T00:26:15Z. This is precisely `AGENTS.md` §1 trap #2, alive: *"Never let a client-side scheduled task be the only thing that ships."* The check does not flag it because the pull is driven from the authority and the machine *does* report (its `dsh-sessions` moved at 00:56Z), so this is a per-kind gap the check's granularity misses.
2. **The archive ran 7 fewer times than the schedule says.** `run.log` shows passes at 10-13T13:38, 14:23, 15:23, 16:23(round 1 only, no completion line), **then 18:23, then a 6 h 30 m gap to 10-14T00:53:18.** Missing: **17:23, 19:23, 20:23, 21:23, 22:23, 23:23, 00:23.** The 00:23:15 miss is the documented floor refusal; the other six are unexplained by anything in the journal, **because the journal covering them does not exist (§3c).** The archive is current *now*; it was not being kept current for 6.5 hours, and nothing alerted.

---

## 5. Silent-death surfaces

**(1) `estate-monitor` still cannot escalate more than one condition — but a new consumer now files everything.** Re-read the deployed code at `/usr/local/bin/estate-monitor.py` (69,337 B, **mtime 2026-10-11T08:37Z — unchanged since before the baseline**):
- line 122: *"`mode` is `"log"` or `"alert"` — and only `public_health_status` is"*
- line 1305: `# --- escalation: exactly one condition may wake anyone ---`
- line 1359: `"conditions_allowed_to_escalate": ["public_health_status"],`
- The baseline cited lines **1355-1359**; they are the same lines and the same content. **The monitor has not been touched.**

The change is a separate file: **`/usr/local/bin/estate-alerts-to-journal.py`** (10,415 B, mtime **2026-10-13T14:07Z**), `estate-alerts-to-journal.timer` every 10 min, `ExecStart=… --apply`, `After=estate-monitor.service`. It reads `state.json` — "which carries the state of **every** metric" — and files one `pain` entry per episode above `--min-streak`. Live ledger: **3 entries filed** (§3d), two of them disk. Its own docstring names the boundary: *"WHAT THE FIX IS NOT … It is not a louder producer. It is a consumer."* and *"It does not text, email or call anyone."*
**Verdict: the answer to "can `estate-monitor` now escalate more than one condition" is NO for the monitor and YES for a new reader — and the reader files work for a session, not a message to a human. The gap the baseline named is narrowed, not closed.**

**(2) `cron-liveness.py` is still not scheduled.** `[M]`
```
-rwxr-xr-x 1 root root 6076 Oct 13 07:04 /root/bin/cron-liveness.py
crontab -l | grep -c cron-liveness   ->  0
```
The script named for exactly this class ("a job that never runs and a job that runs correctly print nothing different") exists, is executable, and **still has no scheduler** — 12 hours after the baseline reported the same thing.

**(3) The off-box deadman does not watch cron — it watches the *authority's offsite backup*. Worse: it now lives on the authority it is supposed to report dead.** `[M]`
`authority-deadman.timer` (every 5 min) → `authority-deadman.py` → `https://healthchecks.io/api/v3`, check name **`"secratary authority alive"`**, `PERIOD=900 GRACE=300`. Its own docstring: *"An external check is the ONLY mechanism that can report the authority being dead, because the report does not come from the authority."* But the **pinger runs on the authority** — it is ported from `secratary:~zabz/bin/deadman.py` at the cutover, and it pings *out*. `grep -n cron /usr/local/bin/authority-deadman.py` finds **one** hit, in the docstring history (line 6), and **no cron check in the code**. The body it sends describes *"the offsite backup's own last-run, and whether a run is in flight"*.
**So the baseline's #2 is unchanged: if `cron.service` dies on the authority, nothing notices.** The only difference from the baseline is that the timer is no longer the same host as the thing it checks *for* — it never checked cron in the first place.

**(4) Search-index refresh clocks, every node:**

| node | mechanism | last successful run | index | verdict |
|---|---|---|---|---|
| `secratary-cloud` | cron `fa-index-refresh` at `8,23,38,53`; cron `fa-index-freshness` at `:22` | 00:53:01Z rc=0; 00:22:01Z rc=0 | `/root/.faindex` `built_at 2026-10-14T00:53:02Z` | **fresh** `[M]` |
| `secratary-cloud` | cron `comms-refresh` `7,37`; `comms-refresh-2` `12,42` | `comms-state.json at 2026-10-14T01:07:18Z`, `coverage_ok:true` | `comms.db` 226,340,864 B | **fresh** `[M]` |
| `secratary` (frozen) | `fa-index.timer` 15 min | **01:07:42Z** | `built_at 2026-10-14T00:52:46Z`, 42,163 paths | **fresh** — node-local, named in the banner `[M]` |
| `zabz-tech-linux` | `fa-index.timer` 15 min | **00:55:05Z** | `built_at 2026-10-14T00:55:11Z`, 31,704 paths | **fresh** `[M]` |
| `mac-mini-ts` | none | — | `~/.faindex` **does not exist** | **no index at all** `[M]` |
| `zabz-tech` (desktop) | Scheduled Task `DSH search index refresh` | **2026-10-14T00:39:01Z — `LastTaskResult=1`** | `~/.faindex` absent; `~/.fsearch/index.db` mtime **2026-10-12T03:57Z** | **FAILING, 45 h stale** `[M]` |
| `zabz-yoga` (laptop) | Scheduled Task `DSH unified-search refresh` | **2026-10-14T00:05:52Z — `LastTaskResult=1`** | `~/.faindex` absent | **FAILING** `[M]` |

**This is the class the baseline called "the third dead-search-clock" — and there are now TWO more of them, on the two Windows machines, both exiting non-zero with no ledger, no alert, and no reader.** `DSH search index refresh` was left in the desktop's task list at rc=1, and the local `.fsearch/index.db` is 45 hours old, holding an index that is 4.88 GB plus **~21 GB of `RETIRED-*` databases that nothing prunes**.

**(5) The mesh broker is split-brained — two brokers, two loopback ports, two hosts.** `[M]`
```
secratary-cloud :  LISTEN 127.0.0.1:3091  users:(("node",pid=20544,fd=18))
                   ActiveEnterTimestamp=Mon 2026-10-12 13:58:34 UTC   NRestarts=0
                   /healthz: {"ok":true,"startedAt":"2026-10-12T13:58:35.061Z","nodes":5,
                              "reads":175,"readFailures":73,"leases":{"live":6,"running":6}}
secratary       :  LISTEN 127.0.0.1:3091  users:(("node",pid=409399,fd=18))
                   ActiveEnterTimestamp=Sun 2026-10-11 23:34:49 UTC   NRestarts=0
```
`docs/mesh/000-SYSTEMS-REGISTER.md` §2.3 says the broker is **on the office box**, and *"the cloud's `mesh-broker.service` is `inactive`/`disabled` with **nothing** on `:3091`."* **Both halves of that sentence are now false.** The cloud unit's own `/etc/systemd/system/mesh-broker.service` is a purpose-written rewrite *for the cloud box* (`/opt/mesh-broker`, `HOME=/root`), so this was deliberate — but the office copy was never stopped, and the office's own unit header still reads *"as a SUPERVISED SERVICE on the authority."* `readFailures 73 / reads 175` = **42% of capacity reads failing**, worse than the baseline's 18/45. And a placement broker that holds live leases in memory (its own unit comment) now has two memories.

**(6) The authority's own logs of the last day are volatile.** `[M]` `/var/log/journal/9ba8daa0e9094672976673925c5af5a0/` holds one 8,388,608-byte `system.journal`, newest entry **2026-10-13T03:44:41Z**. Active logging is in `/run/log/journal` (43 MB). `journalctl --since "2026-10-13 04:00:00" --until "2026-10-14 00:47:00"` returns **1 line**. **Anything not read before a reboot is gone.**

**(7) Other silent-death surfaces, measured `[M]`:**
- `fleet_location_poll`: `last_status "failed"`, **`consecutive_failures: 414`**, `last_ran_at 2026-09-29T03:44:44Z` — **identical to the baseline, 15 days dead**; its `enabled` flag is now `false` in the autopilot config, so it is disabled *and still counted as failing*.
- `google_voice_secretary`: `last_status "ok"` but `last_ran_at 2026-10-05T03:33:45Z` — **208 h stale** and reporting success (baseline: 201 h).
- `world_context`: `consecutive_empty_ticks: 330`; `work_mode: 508`; `company: 503`; `healing: 585`; `self_prog: **2773**`; `ambient_bottom_layer: **5281**`. **Five subsystems have produced nothing for 500–5,281 consecutive ticks while reporting `ok`.**
- `amazon_sync` / `ebay_sync`: `last_status "failed"`, `rc=127`, `stderr: sh: 1: tsx: not found`, last 2026-10-13T04:00Z / 04:20Z. Exit **127 means the script moved** (`000-SYSTEMS-REGISTER.md` trap 5).
- `financial_alert_sweep`: 2,911 successes, `last_detail "no_new_events (total=0)"` — the baseline's "success despite no work" pattern, unchanged.
- `finance.ok: false` — `"BoA (Plaid) last txn 5d ago: 2026-10-09"`.
- `secratary:secretary-backup.service` — **failed since 2026-10-11T03:15:49Z**, `status=143`, on the frozen box, with no reader.
- `zabz-yoga` **C: 1.8% free** (8.57 GB of 475.8 GB) with no disk monitor on that host at all.

---

## 6. The search and session surfaces — including the wrong-node oddity

**The engine.** `fa` exists at `/usr/local/bin/fa` on `zabz-tech-linux`; on the Windows nodes there is no `fa`, no `~/.faindex`, and (on the laptop) no local index either. The desktop has only the retired `~/.fsearch` corpus.

**What `ps_search` actually did.** From **this Windows desktop**, I called the MCP tool `ps_search(query="harness-config", what="files", limit=10)`. It returned:
```
{"file":"/root/code/harness-config/scripts/commsindex.py","source":"path-index","index_age_s":742}
{"file":"/root/code/harness-config/scripts/port-evolution-dedup.py", …}          … 10 rows
… "source": "path-index", "ms": 228, "stale": false, "exit_code": 0, "searched": true
```
Every path is a **Linux `/root/...` path**.

**Whose index answered — proved, not inferred.** The last line of the authority's own `/root/.find-anything.log` is:
```
{"ts":"2026-10-14T01:05:23Z","sub":"files","ms":206,"n":11,"source":"path-index","age":742,"slow":false,"q":"harness-config"}
```
Same second, same `sub`, same `source`, same `age=742`, same query — and my response said `index_age_s: 742`. **The call executed on `secratary-cloud` as `root` and was logged there.** The index it read is the authority's `/root/.faindex` (`built_at 2026-10-14T00:53:02Z`).

**What that index contains `[M]`:** 8,042 paths total — `/root/bin`, `/root/code`, `/root/personal-secretary-mvp`; **6,512 of the 8,042 are under `/root/code/harness-config`; 0 are under `/opt`; 0 are Windows-shaped.** Compare the other two:
```
secratary-cloud :   8,042 paths, all under /root          (494,115 B)
zabz-tech-linux :  31,704 paths, all under /home/zabz  (2,575,521 B)
secratary       :  42,163 paths, all under /home/zabz  (3,544,783 B)
```

**Can a node get a wrong-node answer? Yes — and that is the whole of the oddity.** The `ps_search` MCP tool takes no node parameter and its response carries **no node field**. A Windows caller gets `/root/...` paths; a caller on `zabz-tech-linux` would get the same authority paths and have no way to tell them from its own. The four `[M]`-distinct indexes that exist are **not addressable through this tool**: the authority's answer is the only one a mesh child gets, and it is the *smallest and narrowest* of the three (`/root` only, 8k paths, nothing under `/opt` — so `ps_search(what="files")` cannot see `/opt/company`, `/opt/mesh-broker`, `/opt/wms`, or any Windows file). **"The estate's file search" is, from every node, the authority's home directory.**

**Session surface.** The authority ingests DSH sessions; `truth` is in the archive, not the index. From the archive's coverage (§4), `zabz-tech/dsh-sessions` is current to 00:56:34Z and `zabz-yoga/dsh-sessions` to 00:56:21Z — the session path is live. **`sessions.mjs`'s node map was not re-read this round** (see §8).

---

## 7. The journal lineage

**All `[M]`, measured by counting `journal/entries/*/*.md` and `<!-- e:pain|…|open -->` markers per checkout:**

| checkout | HEAD branch / commit | entries | pain files | open pain | remote refs |
|---|---|---|---|---|---|
| **`secratary-cloud:/root/code/harness-config`** (canonical) | `hk/28-refresh-deployed-sources-20261013` @ `37c62333`, 2026-10-14T01:00:06Z | **4,006** | 552 | **545** | **7** (+6 heads, 0 tags = **13 refs total**) |
| `zabz-yoga:~…` (laptop) | `fix/shop-device-icons-20261013` @ `77b09b7a`, 2026-10-13T15:25:14Z | 3,971 | 543 | 539 | **119** |
| `zabz-tech:~…` (this desktop) | `mesh/broker-host-cloud-default-20261013` @ `5c8f46ea`, 2026-10-13T22:07:19Z | 3,905 | 515 | 511 | **106** |
| `zabz-tech-linux:~…` | `main` @ `985f9378`, 2026-10-12T16:47:43Z | 3,440 | 453 | 446 | **97** |
| `secratary:~…` (frozen) | — | — | 440 | 433 | **102** |
| `LakewooechsMini:~…` | `master` @ `88cec13a`, 2026-10-13T13:00:23Z | **1,644** | 198 | **191** | **139** |

**Id collisions: 0.** Walked all 4,006 entries on the canonical checkout: `entries: 4006 distinct_ids: 4006 colliding_ids: 0 extra_files: 0`. The baseline's **121 base-id collisions across ~120 divergent refs is now 0 on the canonical clone.** The ref divergence itself is **not** fixed — it has simply moved off the authority: the authority has 13 refs, and every peripheral still carries 97–139.

**Open pain no longer reads four wildly different numbers.** Baseline: 162 / 366 / 373 / 393 depending on the machine. Now: **545 / 539 / 511 / 446 / 433 / 191** — the five live checkouts agree to within 112 entries, and the spread is explained by commit lag, not by divergent id spaces. **The one that is genuinely behind is the Mac mini's `master` (1,644 entries, 191 open pain)** — which is exactly the checkout the *previous* round read, and exactly why it reported `175` and the pain set as missing.

**`journal-union.py` — could not be found.** `find / -xdev -name "journal-union*"` on the authority: nothing. Recursive search of the desktop's `harness-config`: nothing. `journal/tools/journal-union.py` on the authority: `No such file or directory`. The baseline's *"`journal-union.py` exists and nothing schedules it"* is **not reproducible from either checkout I can reach** — and given the collision count is now 0 on the canonical clone, a union tool may have been mooted rather than scheduled.

---

## 8. The failing-and-forgotten list — with the smallest change that makes it signal

Ordered by "how long has this been true without a signal". Every row is `[M]` unless marked.

| # | what fails silently | evidence | smallest change that makes it signal |
|---|---|---|---|
| 1 | **Authority disk → no human.** 0 bytes free for 4 h 33 min. | `guard.log` 20:15:01Z→00:45:02Z `0.0 GB free`; `owner_decision_queue` 493 rows, none about disk | Point `lpt-owner-attention` (already runs daily at 14:10Z) at the top **two** open `estate-monitor` pain entries. No new process; the digest already exists. |
| 2 | **`cron-liveness.py` exists, unscheduled.** | `crontab -l \| grep -c cron-liveness` = **0**; file 6,076 B, mtime 2026-10-13T07:04Z | One crontab line: `*/30 * * * * /usr/local/bin/cron-wrap.sh cron-liveness /usr/bin/python3 /root/bin/cron-liveness.py`. It records into `runs.tsv` like every other job. |
| 3 | **Journal is volatile.** Last 21 h of authority logs live only in `/run`. | `journalctl --since 10-13T04:00 --until 10-14T00:47 \| wc -l` = **1**; persistent file newest entry 2026-10-13T03:44:41Z | `Storage=persistent` + `SystemMaxUse=1G` in `/etc/systemd/journald.conf`. (A config change, so the state-change rule applies — propose, do not apply.) |
| 4 | **`zabz-yoga` copilot-chats unarchived for 30 h while its pusher reports success.** | `last_arrival 2026-10-11T19:37:05Z`; `PersonalSecretary-PushVSCodeChats LastTaskResult=0` at 00:26:15Z | Add a per-(machine,kind) max-age to the archive's own `--check`. The check already computes `last_arrival` per `(machine,kind)`; it just has no threshold. |
| 5 | **Two Windows search clocks failing, no ledger.** | `DSH search index refresh` rc=1 (00:39:01Z); `DSH unified-search refresh` rc=1 (00:05:52Z); `.fsearch/index.db` 45 h old | `fa-index-freshness` already exists and already implements the check. Run its *reader* against the two Windows indexes instead of only the authority's. |
| 6 | **The mesh broker answers twice.** | two `127.0.0.1:3091` listeners, two hosts, both `NRestarts=0`, 42% read failures | One comparison in `company-outcome-monitor` (already runs 4-hourly): assert exactly one broker listener across the fleet. Do not stop either — that is a state change on a frozen host. |
| 7 | **`fleet_location_poll` 415 failures / 15 days.** | `consecutive_failures: 414`, `last_ran_at 2026-09-29T03:44:44Z`, unchanged from the baseline | It is already `enabled: false`. Either delete the row so it stops being counted, or add `consecutive_failures > N` on any *enabled* subsystem to the owner-attention digest. |
| 8 | **Five subsystems report `ok` with 500–5,281 consecutive empty ticks.** | `self_prog 2773`, `ambient_bottom_layer 5281`, `healing 585`, `work_mode 508`, `company 503` | These fields already exist in `autopilot_health.subsystems`. Threshold them the same way `estate-monitor` thresholds its 31 metrics — the pattern is already in the estate. |
| 9 | **Mac's three launchd agents, 3rd consecutive audit.** | `launchctl list`: `com.lakewoodphone.repo-sync` **1**, `com.personalsecretary.nodeagent` **1**, `com.lakewoodphone.harness-autosync` **1** | One scheduled job on the Mac that runs `launchctl list` and writes a row to the archive's `machine_contact`; the archive already pulls from that machine hourly. |
| 10 | **`google_voice_secretary` says `ok`, last ran 208 h ago.** | `last_status "ok"`, `last_ran_at 2026-10-05T03:33:45Z` | `last_ran_at` is already recorded. Age-threshold it. |
| 11 | **`amazon_sync` / `ebay_sync` rc=127 (`tsx: not found`).** | `stderr: sh: 1: tsx: not found`, cf 3, last 10-13T04:00Z | Exit 127 is unambiguous (`000-SYSTEMS-REGISTER.md` trap 5). Alert on rc=127 specifically — it always means "the script moved". |
| 12 | **`zabz-yoga` C: at 1.8% free, no monitor.** | free 8,570,925,056 of 510,915,506,176 | The estate already has `disk-guard.py`. Its consumer list is a variable. |
| 13 | **Authority clone has 13 refs; peripherals carry 97–139.** | §7 table | This is the *converged* end. The smallest change is to stop treating the authority clone as the only truth: `config-sync-status` already runs every 15 min and currently exits rc=1/rc=3 with no reader. |

---

## WHAT I COULD NOT DETERMINE

1. **What actually freed the 4 GB.** It appeared between 00:48:03Z and 00:50:03Z (+3.053 GB) and 00:52:06Z→00:54:01Z (+0.994 GB). Every automatic reclaim path is a no-op or forbidden (`tmpfs-reaper` targets a tmpfs; `prune-backups` has 0 dirs and logs `FLOOR BREACHED`; `disk-guard` records `"invocation_allowed": false`). The journal covering exactly that window **does not exist** (§3c), the persistent journal's newest entry is 2026-10-13T03:44:41Z, and I found no in-window deletion record. **The most likely explanation is an out-of-band manual/session cleanup on the authority; I did not find the record and will not assert it.**
2. **Whether the 21-hour journal hole is retention, `Storage=` policy, or the disk-full event.** I measured the hole and the file state; I did not measure `journalctl --verify` or the rotation policy. The `00:47:19Z` rsyslogd `No space left on device` proves the disk-full half; it does not prove the other 21 hours.
3. **`tick_telemetry` row/agent counts** (baseline: 34,139 rows / 85 agents) and **`dsh_sessions` count** (baseline: 6,935). Not re-counted — I chose to spend the read budget on the disk, the archive, and the broker.
4. **The baseline's "2 of 5 nodes unreachable HTTP 403"** and its `secratary`/`lakewooechsmini` 403 rows. I did not dump `/nodes?fresh=1` per node; I only captured `/healthz` and the head of `/nodes`.
5. **`wake-fanout`'s 205 `wake-failed/` dirs and the 25-vs-5 cap drift.** Not re-counted this round.
6. **`sessions.mjs`'s `DEFAULT_NODES`** — whether the `secratary` → `secratary-ts` mapping and the missing `secratary-cloud` entry were fixed. I did not open the file.
7. **Whether the exact 00:23:15Z archive refusal is recorded anywhere but the timer's `LastTriggerUSec`.** I have the floor-check *code* that refuses, the timer trigger timestamp, and the run.log gap — but **no log line from the refusal itself**, because the journal for that window is gone.
8. **`docs/dsh-evolution-v2/PROGRAM.md`, and the corpus the v2 brief assumes.** It exists on no path I reached, and `/home/zabz/evolution-corpus-v2/` had to be created.
9. **The `secratary` office box's own `lpt-email-sweep`, `lpt-books-nightly` and `lpt-owner-attention` timers** — whether business jobs running on the frozen anchor are a live hazard or an accepted arrangement. `host-posture.tsv` and the crontab banner name only `tmp-reaper`, `fa-index`, `trunk-check`, `estate-monitor` as node-local. **I did not judge and did not touch.**

---

## EVIDENCE LOG

Exact commands, with the number each produced. All read-only. `[local]` = run on `zabz-tech`; `[ssh]` = run over `ssh -o BatchMode=yes -o ConnectTimeout=10`.

**Recon / reachability**
- `[local] hostname; $env:COMPUTERNAME` → `zabz-tech` / `ZABZ-TECH`
- `[local] Get-Date -Format o` → `2026-10-13T20:59:48.6884881-04:00` (= 2026-10-14T00:59:48Z)
- `[local] for h in secratary-cloud desktop-ts laptop-ts linux-pc-ts mac-mini-ts secratary-ts: ssh … 'hostname; id -un; uname -sr'` → **6 answered / 0 refused**; `secratary-cloud`, `zabz-tech`, `zabz-yoga`, `zabz-tech-linux`, `LakewooechsMini`, `secratary`; Linux 7.0.0-38 / Windows / Windows / Linux 6.8.0-111 / Darwin 25.5.0 / Linux 7.0.0-38
- `[ssh secratary-cloud] date -u` → `Wed Oct 14 01:02:36 AM UTC 2026`

**Baseline documents**
- `[local] git log --all --oneline --diff-filter=A -- docs/dsh-evolution/30-systems-and-autonomy-audit.md` → **1: `75ffbeef`**
- `[local] git cat-file -t HEAD:docs/dsh-evolution/30-systems-and-autonomy-audit.md` → `fatal: … does not exist in 'HEAD'`
- `[local] git ls-tree -r --name-only HEAD -- docs/dsh-evolution` → **0 lines**
- `[ssh secratary-cloud] ls -la /home/zabz/evolution-corpus-v2/` → `No such file or directory`
- `[ssh secratary-cloud] ls -la /home/zabz/evolution-corpus/` → 25 artifacts, `reports/`, `shards/`

**§1 authority**
- `[ssh] systemctl list-timers --all --no-pager` → **30 timers listed**
- `[ssh] systemctl list-units --state=failed --no-pager` → **0 loaded units listed**
- `[ssh] for u in company-api cron …: systemctl is-active/is-enabled` → company-api `active/enabled`, cron `active/enabled`, mesh-broker `active/enabled`, `deadman.timer`/`transcript-archive.timer`/`offsite.timer` `inactive/not-found`
- `[ssh] df -h /; df -i /; free -m` → `75G 68G 4.0G 95%`; inodes 14%; Mem 15605/3969/11635, Swap 3561/4095
- `[ssh] wc -l /root/.cron-status/runs.tsv` → **15,007**
- `[ssh] ss -ltnp | grep 3091` → `127.0.0.1:3091 users:(("node",pid=20544,fd=18))`
- `[ssh] curl -s http://127.0.0.1:3091/healthz` → `ok:true nodes:5 reads:175 readFailures:73 leases.live:6`
- `[ssh] systemctl show mesh-broker -p ActiveEnterTimestamp` → `Mon 2026-10-12 13:58:34 UTC`, `NRestarts=0`
- `[ssh] systemctl show company-api -p NRestarts -p MemoryMax -p MemoryPeak` → `0` / `infinity` / `9702137856`
- `[ssh] tail -400 runs.tsv | awk -F'\t' '$3!=0'` → `config-sync-status rc=1/3`, `disk-guard rc=1`, `journal-commit rc=1`, `guard-registry rc=3`, `lpt-deploy-drift rc=3`

**§1 frozen anchor**
- `[ssh secratary-ts] systemctl is-active/is-enabled` → cron `inactive/masked`, secretary-api `inactive/masked`, dialpad-sms-ws `inactive/masked`, secretary-dashboard `inactive/masked`, phone-engine `inactive/masked`, **mesh-broker `active/enabled`**, sshd `active/alias`
- `[ssh secratary-ts] ls -la /etc/systemd/system/cron.service` → `-> /dev/null`, 2026-10-11T20:23
- `[ssh secratary-ts] crontab -l | wc -l` → banner only, **0 job lines**
- `[ssh secratary-ts] ss -ltnp | grep 3091` → `127.0.0.1:3091 users:(("node",pid=409399,fd=18))`
- `[ssh secratary-ts] systemctl show mesh-broker -p ActiveEnterTimestamp` → `Sun 2026-10-11 23:34:49 UTC`
- `[ssh secratary-ts] systemctl list-units --state=failed` → **1**: `secretary-backup.service`, failed since 2026-10-11T03:15:49Z, `status=143`
- `[ssh secratary-ts] df -h /` → `467G 414G 34G 93%`
- `[ssh secratary-ts] systemctl list-timers` → estate-monitor 01:02:04Z, fa-index 00:52:42Z, tmp-reaper 01:00:00Z, trunk-check 00:48:31Z

**§2 baseline claims**
- `[ssh secratary-cloud] git ls-tree -r --name-only HEAD | grep 175-` → **`docs/mesh/175-STATE-OF-THE-ESTATE-2026-10-12.md`**
- `[ssh] git log --all --oneline --diff-filter=A -- "docs/mesh/175*"` → **`e2322825`**
- `[ssh] git log --all --oneline -S"work_metrics"` → **only `75ffbeef`**
- `[ssh] python3: select name from sqlite_master … like '%work_metric%'` on `authority.db` → `[]`; `table_count: 235`; metrics-ish `['agent_metrics','anomaly_log','tick_activity','tick_telemetry']`
- `[ssh secratary-ts] python3: secretary.db like '%metric%'` → `['agent_metrics']`
- `[ssh] find / -xdev -name "journal-union*"` → **0**
- `[local] Get-ChildItem -Recurse -Filter *journal-union*` → **0**
- `[ssh] crontab -l | grep -c cron-liveness` → **0**; `ls -la /root/bin/cron-liveness.py` → 6,076 B, 2026-10-13T07:04
- `[ssh mac-mini-ts] launchctl list | grep -v com.apple` → `repo-sync 1`, `nodeagent 1`, `harness-autosync 1`
- `[ssh mac-mini-ts] ls ~/.dsh/skills` → **7 skills present** (mtime 2026-10-13T10:23)

**§3 disk**
- `[ssh] df -h` (all) → `/dev/sda1 75G 68G 4.0G 95%`; `tmpfs 7.7G 1.4G 6.3G 19% /tmp`
- `[ssh] du -xhd1 /root|/opt|/var|/tmp|/home` → `41G /root`, `17G /opt`, `178M /var`, `1.4G /tmp`, `3.9G /home`
- `[ssh] find / -xdev -type f -size +200M -printf "%s\t%p\n" | sort -rn | head -40` → top: `26783068160 /root/authority.db`, `4294967296 /swapfile`, `2404261888 …/chroma.sqlite3`, `1612575159 …lpt-hub pack`, `1598145741 …work/lpt-hub pack`
- `[ssh] ls -la /root/authority.db*` → `26,960,019,456` B @01:07; `-wal 67,108,864`; `-shm 327,680`
- `[ssh] tail -40 /root/.disk-guard/guard.log` → `20:15:01Z CRITICAL / at 96.2% (0.0 GB free, 0 MB)` … `00:45:02Z 97.1% (0.0 GB free)` … `01:00:02Z 90.5% (4.0 GB free, 4105 MB)`
- `[ssh] cat /root/.disk-guard/status.json` → `free_bytes 4304486400`, `used_pct 90.5`, `findings: ["/ at 90.5% … warn threshold 90%"]`, `retention.invocation_allowed: false`
- `[ssh] journalctl -u estate-monitor --since "2026-10-14 00:48:00" -o short-iso` → `00:48:03Z 0.0 GiB free / 97.08%`; `00:50:03Z 3.053 GiB / 91.81%`; `00:54:01Z 4.047 GiB / 90.48%`
- `[ssh] tail -25 /root/tmp-rescue/reaper.log` → `00:20:01Z ok free=6393MB (floor 600MB) - nothing to do`
- `[ssh] tail -25 /var/log/authority-backup-prune.log` → `FLOOR BREACHED - only 8057340 KB free … Pruned NOTHING … 0 entry/entries present`
- `[ssh] journalctl -u transcript-archive-pull --since "2026-10-14 00:00" -o short-iso` → `Starting 00:53:18Z`; `run.sh exit=0 at 00:56:36Z`; `spool: freed 11939840 bytes`
- `[ssh] journalctl --since "2026-10-14 00:20:00" --until "2026-10-14 00:26:00"` → `-- No entries --`
- `[ssh] journalctl … | grep -aiE "No space left"` → `00:47:19Z rsyslogd[1295]: file '/var/log/syslog'[7] write error … OS error: No space left on device`
- `[ssh] journalctl --since "2026-10-13 04:00:00" --until "2026-10-14 00:47:00" | wc -l` → **1**
- `[ssh] journalctl --until "2026-10-14 00:47:13" -n 3 -o short-iso` → newest entries `2026-10-13T03:44:41+00:00` (rsyslogd, same `No space left`)
- `[ssh] ls -la /var/log/journal/*/` → one file, `system.journal 8388608`, mtime `Aug 26 09:10`; `du -sh /run/log/journal` → `43M`
- `[ssh] cat /root/.estate-monitor/journal-filed.json` → 3 entries: `disk_used_pct @2026-10-13T14:07:23Z`, `disk_free_deficit_gb @2026-10-13T15:32:15Z`, `swap_used_pct @2026-10-14T00:12:00Z`
- `[ssh] cat /root/.estate-monitor/alerts.jsonl` → **3 rows, all `public_health_status`, all `"transport": "syslog-only, no outbound message"`**
- `[ssh] cat /root/.estate-monitor/ESCALATED` → 1 line, `[2026-10-13T04:24:03Z] ESCALATE public_health_status=1.0`
- `[ssh] python3: owner_decision_queue order by rowid desc limit 6` → newest id 494 @2026-10-13T19:50:31Z; `total: 493`; **none about disk**
- `[ssh] python3 state.json` → `disk_used_pct {st:crit, streak:552}`, `disk_free_deficit_gb {st:crit, streak:588}`, `swap_used_pct {st:crit, streak:150}`, `authority_db_shrink_mb note: "previous size 26806702080 B at 2026-10-14T01:06:02Z; delta +153317376 B"`

**§4 archive**
- `[ssh] cat /etc/transcript-archive.env` → the five `TRANSCRIPT_ALIAS_*` + `TRANSCRIPT_MAX_BYTES=500000000`
- `[ssh] systemctl cat transcript-archive-pull.service` → `EnvironmentFile=-/etc/transcript-archive.env`, `SuccessExitStatus=0 2`, drop-in `MemoryMax=6G MemorySwapMax=1G`
- `[ssh] systemctl show transcript-archive-pull.timer -p LastTriggerUSec` → `Wed 2026-10-14 00:23:15 UTC`
- `[ssh] systemctl show transcript-archive-pull.service -p Result -p ExecMainStatus -p ExecMainExitTimestamp` → `success` / `0` / `Wed 2026-10-14 00:56:36 UTC`
- `[ssh] cat /var/lib/transcript-archive/status.json` → `pull_rc 0`, `check_rc 0`, `ok true`, `gaps []`, `silent []`, 13 coverage rows
- `[ssh, deployed env] python3 /opt/company/archive/tools/transcript-archive-server.py --check` → `CHECK_RC=0`, `ok:true, machines_reporting:5, gaps:[], silent:[]` @2026-10-14T01:05:58Z
- `[ssh] python3 sqlite3 manifest.sqlite` → `object 48797`, `arrival 55489`, `machine_contact 584`, `ingest_run 384`, `quarantine 0`
- `[ssh] grep -n "free\|floor" /opt/company/archive/tools/transcript-archive-run.sh` → `TRANSCRIPT ARCHIVE REFUSED TO START — not enough free space to stage a pull`, `free : %s bytes`, `Lower TRANSCRIPT_MAX_BYTES, free space, or raise the floor deliberately.`
- `[ssh] tail -20 /opt/company/archive/lpt-transcripts/logs/run.log` → passes at 13:38, 14:23, 15:23, 16:23(round 1 only), **18:23**, then **00:53:18** — 7 schedule slots with no pass

**§5 silent death**
- `[ssh] grep -n "conditions_allowed_to_escalate\|mode.*alert\|escalat" /usr/local/bin/estate-monitor.py` → line 122, 1305 `# --- escalation: exactly one condition may wake anyone ---`, **line 1359 `"conditions_allowed_to_escalate": ["public_health_status"],`**
- `[ssh] ls -la /usr/local/bin/estate-monitor.py /usr/local/bin/estate-alerts-to-journal.py` → 69,337 B @2026-10-11T08:37 / 10,415 B @**2026-10-13T14:07**
- `[ssh] systemctl cat estate-alerts-to-journal.service/.timer` → `ExecStart=… --apply`, `OnCalendar=*:02,12,22,32,42,52`
- `[ssh] sed -n "1,45p" /usr/local/bin/authority-deadman.py` → `https://healthchecks.io/api/v3`, `NAME = "secratary authority alive"`, `PERIOD, GRACE = 900, 300`; `grep -n cron` → **1 hit, in the docstring**
- `[ssh] grep -n "cron" /root/bin/cron-liveness.py` — file exists, unscheduled (§2)
- `[ssh] grep -aE "fa-index-refresh|fa-index-freshness" runs.tsv | tail -4` → `00:53:01Z fa-index-refresh 0`, `00:22:01Z fa-index-freshness 0`
- `[ssh] cat /root/.faindex/built_at.txt` → `2026-10-14T00:53:02Z`
- `[ssh] cat /root/.fsearch/comms-state.json` → `at 2026-10-14T01:07:18Z`, `coverage_ok true`, `total 180108`
- `[ssh linux-pc-ts] systemctl list-timers fa-index.timer` → last `20:55:05 EDT`; `built_at 2026-10-14T00:55:11Z`
- `[ssh secratary-ts] systemctl list-timers fa-index.timer` → last `01:07:42Z`; `built_at 2026-10-14T00:52:46Z`
- `[local] Get-ScheduledTask … Get-ScheduledTaskInfo` on `zabz-tech` → `DSH search index refresh` **1** @00:39:01Z; `DSH Engine Vitals (5m)` **3**; `DSH Metrics Sampler` **2147942667**; `LPT-greenfeld-copy` **3**; `PersonalSecretary-DailyPartnerSync` **1**; `DshChatScan` **1**
- `[ssh laptop-ts] Get-ScheduledTask …` → `DSH unified-search refresh` **1** @00:05:52Z; `DSH Engine Vitals (5m)` **1**; `DSH MCP Health (5m)` **64**; `DSH Engine Pin Install` **1**; `DSH Mesh 0700 Restart` **1**; `DSH Multi-Window Launcher` **1**; `PersonalSecretary-PushVSCodeChats` **0**
- `[mcp] ps_health` → `autopilot last_run_at 2026-10-14T01:04:22Z run_count 88 cf 0`; `fleet_location_poll consecutive_failures 414 last_ran_at 2026-09-29T03:44:44Z`; `google_voice_secretary ok last_ran_at 2026-10-05T03:33:45Z`; `amazon_sync`/`ebay_sync` `rc=127 tsx: not found`; empty-tick counts `self_prog 2773`, `ambient_bottom_layer 5281`; `finance.ok false "BoA (Plaid) last txn 5d ago"`

**§6 search**
- `[mcp] ps_search(query="harness-config", what="files", limit=10)` → 10 rows, all `/root/…`, `"source":"path-index","index_age_s":742`
- `[ssh] tail -20 /root/.find-anything.log` → `{"ts":"2026-10-14T01:05:23Z","sub":"files","ms":206,"n":11,"source":"path-index","age":742,"q":"harness-config"}` — **same second, same age**
- `[ssh] wc -l /root/.faindex/paths.txt` → **8,042**; `cut -d/ -f1-3 | sort -u` → `/root/bin`, `/root/code`, `/root/personal-secretary-mvp`; `grep -c "^/root/code/harness-config"` → **6,512**; `grep -c "^/opt"` → **0**; `grep -c "^[A-Za-z]:"` → **0**
- `[ssh linux-pc-ts] wc -l ~/.faindex/paths.txt` → **31,704**, all `/home/zabz`
- `[ssh secratary-ts] wc -l ~/.faindex/paths.txt` → **42,163**, all `/home/zabz`
- `[local] Test-Path ~/.faindex` → `False`; `~/.fsearch/index.db` → `4,885,487,616` B @2026-10-11T23:57:48-04:00; `RETIRED-index-trigram.db` `10,985,168,896` B

**§7 journal**
- `[ssh] python3 walk journal/entries` → `entries: 4006 distinct_ids: 4006 colliding_ids: 0 extra_files: 0`
- `[ssh] git for-each-ref refs/remotes | wc -l` → **7**; `refs/heads` → 6; `refs/tags` → 0
- `[ssh] grep -rh "e:pain" journal/entries/pain/ | grep -c "|open -->"` → **545**
- `[local]` same → **511**; `[ssh laptop-ts]` → 539; `[ssh linux-pc-ts]` → 446; `[ssh secratary-ts]` → 433; `[ssh mac-mini-ts]` → **191**
- `[ssh] git for-each-ref refs/remotes` per peripheral → yoga **119**, desktop **106**, office **102**, linux-pc **97**, mac **139**

---

## State-change statement

**I changed no service state on any host.** No `systemctl start/stop/restart/enable/disable/mask/unmask` was issued on any machine, including the authority. `secratary` (the office box) was read only, reported as **frozen by decision**, and never "fixed"; its masked `cron`, `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard` and `phone-engine` are reported as decisions, not breakage. The authority was read with `df`, `stat`, `du`, `grep`, `find`, `journalctl`, `systemctl status/show/list-timers/is-active`, `crontab -l`, `ss -ltnp`, `curl` to loopback, and read-only SQLite (`file:…?mode=ro`). The one `--check` I ran is the archive's own documented read-and-report pass and its `SuccessExitStatus` treats it as non-mutating; it starts no build, no test, no browser. **The only things I wrote anywhere were the mailbox outbox lines on this machine and the single permitted file `/home/zabz/evolution-corpus-v2/reports/estate-v2.md` on the authority** (plus the two directory components that had to exist for it: `/home/zabz/evolution-corpus-v2/` and `/home/zabz/evolution-corpus-v2/reports/`).

**Measured vs quoted, once more:** every number in §1–§8 that is not explicitly marked `[DOC]` or attributed to the baseline audit is something I ran and read at 2026-10-14T00:59–01:15Z. The three places I quote rather than reproduce are named as such; the nine things I could not determine are listed above rather than guessed at.

