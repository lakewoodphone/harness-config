# 132 — CRON INVENTORY: everything the OFFICE box ran on a schedule, and what must move

**Workstream:** migration inventory (one of six). **Author:** Zabz, ZABZ-YOGA session, 2026-10-11 ~06:20Z.
**Scope:** produce the complete, evidence-based inventory of every scheduled item on the office box with a
migration verdict. **This is an inventory, not a verification: NO item below was run, and nothing on any
machine was modified.** Every reading carries the machine and command that produced it.

**Primary evidence:** `/home/zabz/cutover/crontab.before` on `secratary-ts` — the office crontab as it stood at
the freeze. Copied locally once and decoded in a single local pass (`scp secratary-ts:/home/zabz/cutover/crontab.before`
then a local node/PowerShell decode), never one ssh round trip per line.

## 0. Headline numbers and how they were measured

| reading | value | evidence (machine · command) |
|---|---|---|
| lines in the frozen crontab | **176** | `secratary-ts: wc -l /home/zabz/cutover/crontab.before` |
| scheduled jobs in it | **92** | local decode of the copied file (92 lines that are not blank and not `#`) |
| base64 payloads decoded | **92 of 92, zero failures** | local decode; every line matches `cron-wrap.sh <name> <b64>` except 6 plain lines |
| office crontab installed right now | identical to the frozen file, **176 lines** | `secratary-ts: crontab -l \| wc -l` |
| office `cron.service` | **masked, inactive** (since 2026-10-11 04:01:34Z) | `secratary-ts: systemctl status cron` |
| office custom systemd timers | **5 active + 3 disabled** | `secratary-ts: systemctl list-timers --all` |
| office box load during this inventory | **0.01–0.35** | `secratary-ts: cut -d' ' -f1 /proc/loadavg` |
| cloud box `crontab -l` | **empty — "no crontab for root"** | `secratary-cloud: crontab -l` |
| cloud box `/etc/cron.d` | **only `.placeholder` and `e2scrub_all`** (distro default) | `secratary-cloud: ls -la /etc/cron.d/` |
| cloud box custom timers | **none** (18 timers, all distro OS) | `secratary-cloud: systemctl list-timers --all` |
| cloud box disk | **68G used, 4.4G avail, 94%** | `secratary-cloud: df -h /` |

**A warning I have to record against myself.** While taking the reading above I ran
`sqlite3 … ".tables"` against the frozen office database to find scheduler tables. That is a heavy read of a
23 GB schema and it hung; I killed the background job at once (`job_kill pwsh-7631`) and moved the query to the
cloud authority. It is exactly the class of operation §RULE 1 forbids, I committed it, and the office load was
verified back down to 0.35 immediately afterwards. Every office command after that point was a `wc`, `ls`,
`grep`, `cut` or a Python script over small text files.

---

## §1 — THE FAMILY TABLE

Verdict key: **PORT-AS-IS** runs unchanged on the new authority · **PORT-ADAPT** needed but names office
paths / the office DB / localhost ports / credentials that must exist on the cloud box · **IN-PROCESS** already
provided by the company app's own autopilot loop and MUST NOT be duplicated by cron · **DEAD** superseded,
target missing, or failed ~100% for weeks · **OFFICE-ONLY** bound to hardware or the office LAN ·
**DANGEROUS-ON-CLOUD** would write to or ship the FROZEN office database, create a second writer against the
company database, or delete the real `/root/authority.db`.

| # | family | count | jobs | schedule | what it does | verdict |
|---|---|---|---|---|---|---|
| 1 | **Offsite backup + retention + age reporting** | 5 | `push-db-offsite` (147), `company-offsite-push` (148), `report-offsite-age` (149), `prune-backups` (15), `db-integrity-check` (7) | daily 05:10 · 4×/day · */30 · daily 05:20 · daily 04:17 | the only copies that survive the machine; retention; integrity | **DANGEROUS-ON-CLOUD** (the 2 pushers + prune + integrity) **PORT-ADAPT** (`report-offsite-age` reads R2 only) |
| 2 | **External dead-man switch** | 1 | `deadman` (117) | */5 | pings healthchecks.io so an alarm arrives when the authority is dead | **PORT-ADAPT** |
| 3 | **Service/pipeline freshness monitors** | 12 | `production-comms-freshness` (47), `comms-refresh-2` (50), `lpt-report-freshness` (166), `lpt-audit-freshness` (157), `lpt-freshness-watchdog` (155), `lpt-deploy-drift` (153), `ai-gateway-health` (146), `site-uptime-check-cron` (14), `monitor-hetzner-backups` (12), `box-health-check` (45), `engine-watch` (131), `disk-guard` (94) | */15, */5, hourly, daily | the estate's "is this still producing" layer | **PORT-ADAPT** ×10, **DEAD** ×2 (`lpt-deploy-drift`, `box-health-check`) |
| 4 | **Company-data ingestion (money + orders)** | 6 | `nightly-plaid-sync` (8), `daily-finance-sync-cron` (13), `supplier-order-ingest` (34), `supplier-delivery-watch` (35), `auto-categorize` (176), `lpt-daily-track` (168) | daily, */6h, daily 23:30 | bank/ledger/order/finance series | **IN-PROCESS** ×1 (`nightly-plaid-sync` — `plaid_sync` ticks in autopilot) **PORT-ADAPT** ×3, **DEAD** ×2 (`supplier-delivery-watch`, `lpt-daily-track` needs the ledger) |
| 5 | **Communications ingestion + index (Dialpad / SMS / comms)** | 12 | `dialpad-harvest-cron` (23), `dialpad-sms-harvest-cron` (61), `dialpad-recording-gap` (37), `dialpad-transcript-gap` (39), `dialpad-call-fresh` (154), `lpt-retranscribe` (156), `comms-refresh` (30), `reconcile-sms-status` (172), `family_chat_watchdog` (44), `lpt-recon-check` (48), `lpt-dialpad-daily` (151), `lpt-dialpad-apply` (158) | */30, 15,45, */5, */10, 1min, 23h, 7,37 | the whole customer-comms record | **PORT-ADAPT** ×8, **DEAD** ×2 (`lpt-recon-check`, `lpt-dialpad-daily`), **PORT-AS-IS** ×1 (`comms-refresh`) |
| 6 | **Owner text channel (SMS inbox / responder / asks)** | 10 | `sms-inbox` (59), `mirror-owner-sms` (77), `reconcile-sent-status` (83), `promote-owner-texts` (88), `run-wake-sources` (60), `wake-fanout` (58), `wake-cost` (70), `wake-balance` (101), `owner-ask` (122), `cfo-ask` (107) | */5, */15, */30, 1min, hourly | the owner's own line, wake dispatcher, spend ceiling, owner questions | **PORT-ADAPT** ×9, **DEAD** ×1 (`cfo-ask` — ledger absent on cloud) |
| 7 | **CFO money layer** | 3 | `cfo-shift` (152), `cfo-scoreboard` (110), `hours-drift` (160) | */2h, */6h, */6h | CFO shifts, spending scoreboard, published-hours drift | **PORT-ADAPT** ×2, **DEAD** ×1 (`hours-drift`, 100% failure) |
| 8 | **The LPT shop ops (Dialpad → production Postgres, reports)** | 6 | `audit` (52), `website-comms-push-cron` (49), `lpt-audit-weekly` (150), `lpt-business-report` (164), `lpt-hub-refresh` (31), `work-integrator` (92) | */30, 9,39, weekly Mon, weekly Sun, */15, daily 23h | the shop's customer records, reports and repo integration | **DEAD** ×2 (`audit` 100%, `lpt-audit-weekly` never logged), **PORT-ADAPT** ×3, **PORT-AS-IS** ×1 (`lpt-hub-refresh`) |
| 9 | **AI gateway + model registry** | 2 | `model-failover-watch` (28), `profile-gate` (64) | */5, */15 | provider liveness and DSH profile composition | **PORT-ADAPT** ×1, **DEAD** ×1 (`profile-gate`) |
| 10 | **Guards and self-checks (do the guards still hold?)** | 8 | `cron-target-guard` (93), `cron-script-guard` (161), `guard-registry` (130), `store-write-check` (159), `pain-check` (111), `tree-integrity-check` (90), `text-channel-check` (127), `tmpfs-reaper` (135) | */5–*/15, daily | a *different* process verifying the guards that matter | **DEAD** ×4 (`pain-check`, `text-channel-check`, `store-write-check`, `tmpfs-reaper`), **PORT-ADAPT** ×4, **DANGEROUS** ×1 (`store-write-check`) |
| 11 | **Home Assistant / office LAN** | 3 | `check-security-absence` (53), `run-ha-truth` (17), `run-ha-behaviour` (19) | */15, */30, daily | HA physical security, HA truth and behaviour | **OFFICE-ONLY** ×3 (all three address `192.168.50.34`) |
| 12 | **Phone / DSH engine serving** | 6 | `serve-phone` (20), `serve-phone-2` (21), `probe-phone` (24), `check-phone-ui` (27), `mesh-health` (2), `mesh-node-probe` (162) | @reboot, */2, */5, daily, */5, */15 | the owner's phone view and the mesh surface | **OFFICE-ONLY** ×4, **DEAD** ×2 (`mesh-health`, `mesh-node-probe`) |
| 13 | **ceo-kernel (sentinel / estate monitor)** | 2 | `run-sentinel` (16), `converge-authority` (65) | */5, */15 | the CEO kernel's sensing loop and authority convergence | **PORT-ADAPT** ×1, **DEAD** ×1 (`converge-authority`, 53% failure) |
| 14 | **Journal + harness sync** | 1 | `journal-commit` (18) | */15 | commits the journal and autosyncs harness-config | **PORT-ADAPT** |
| 15 | **Transcript archive** | 1 | `transcript-archive` (169) | hourly | pulls every machine's DSH/Copilot transcripts into the raw archive | **PORT-ADAPT** (archive root does not exist on cloud) |
| 16 | **DSH session shipping** | 1 | `push-dsh-sessions` (22) | */30 | ships this fleet's DSH sessions into the company DB | **PORT-ADAPT** (must target the cloud API, not office `127.0.0.1:8002`) |
| 17 | **Node agent (repo ingest)** | 1 | `node-agent-cron` (9) | */30 | ingests VS Code chat / node context | **PORT-ADAPT** |
| 18 | **Owner attention digest** | 1 | `owner-attention-digest` (10) | */30 | one digest of what needs the owner | **IN-PROCESS** (`owner_attention_sweep` ticks in autopilot) |
| 19 | **Unified search index** | 1 | `sync` (51) | */30 | refreshes the `~/.usearch` index | **DEAD** (the checkout is not on the cloud box and the tool is desk-scoped) |
| 20 | **Presence sampling** | 1 | `sampler` (26) | */15 | owner home/office resolution | **OFFICE-ONLY** (reads office LAN presence) |
| 21 | **Phoenix evidence (HA recorder)** | 2 | `backup-phoenix-evidence` (40), `check-phoenix-evidence` (41) | daily 03:30, hourly | copies HA history off the office server | **OFFICE-ONLY** ×2 (source is `root@192.168.50.34`) |
| 22 | **Chip / business side-cars** | 1 | `chip-resume` (96) | */15 | resumes a scheduled side-car per owner instruction 2026-09-30 | **PORT-ADAPT** |
| 23 | **Owner SMS ↔ work queue bridge** | 1 | `promote-owner-texts` (88) — counted in family 6 | */15 | repair-only promotion of owner texts | **PORT-ADAPT** |
| — | **retired names still in the ledger** | 6 | `secretary-startup`, `selftest-ok`, `selftest-fail`, `selftest-redir`, `probe-unwrapped`, `capture-test` | — | rows in `runs.tsv` with **no crontab line and no systemd unit** | **DEAD** (not scheduled) |

**Count per verdict (92 scheduled jobs):**

| verdict | n | which |
|---|---|---|
| PORT-AS-IS | **2** | `comms-refresh` (30), `lpt-hub-refresh` (31) |
| PORT-ADAPT | **48** | see §2 |
| IN-PROCESS | **2** | `nightly-plaid-sync` (8), `owner-attention-digest` (10) |
| DEAD | **21** | see §3 |
| OFFICE-ONLY | **13** | see §4 |
| DANGEROUS-ON-CLOUD | **6** | see §5 |
| | **92** | |

---

## §1a — EVERY JOB, ONE ROW EACH

Machine is `secratary-ts` (the office box) for all rows; the crontab lives at
`/home/zabz/cutover/crontab.before`, line number in the `L` column. Full decoded commands for every
non-DEAD item are given again in §2; commands here are abbreviated only in the middle.

| L | schedule | job | decoded command (abbreviated) | what it does | evidence line | verdict |
|---|---|---|---|---|---|---|
| 1 | `@reboot` | heartbeat | `~/heartbeat.sh &` | infinite `while true; echo Alive; sleep 60` loop from 2026-06-28 | `runs.tsv` `heartbeat 0 0`; script mtime 2026-06-28 02:20, 2523.9h old | DEAD |
| 2 | `*/5 * * * *` | mesh-health | `~/mesh-health.sh > ~/.personal-secretary/mesh-health.json` | pushes a mesh manifest to the laptop | script mtime **2026-06-28 03:32 (2522.7h old)**, `scp … laptop:` target name long gone | DEAD |
| 7 | `17 4 * * *` | db-integrity-check | `/home/zabz/bin/db-integrity-check.py --write-status >> …` | `PRAGMA integrity_check` on the company DB + status file | runs.tsv `10 runs, 0 non-zero, last 2026-10-10T04:17:01Z`; header: "took 715-1784 s (16 589 s on 2026-10-06)" | DANGEROUS-ON-CLOUD |
| 8 | `30 4 * * *` | nightly-plaid-sync | `/home/zabz/personal-secretary-mvp/scripts/nightly-plaid-sync.sh` | nightly Plaid bank sync | autopilot `subsystem_health.plaid_sync last_ran=2026-10-11T05:41:23Z status=ok` | IN-PROCESS |
| 9 | `*/30 * * * *` | node-agent-cron | `…/scripts/mesh/node-agent-cron.sh` | node/chat context into the hub | runs.tsv `499 runs, 53 non-zero (11%)`; script needs `VSCODE_CHAT_INGEST_TOKEN` from office `.env` | PORT-ADAPT |
| 10 | `*/30 * * * *` | owner-attention-digest | `…/scripts/server/owner-attention-digest.sh > …/latest.txt` | builds the owner's attention digest | autopilot `subsystem_health.owner_attention_sweep last_ran=2026-10-11T05:49:30Z status=ok`; `499 runs, 0 non-zero` | IN-PROCESS |
| 11 | `*/30 * * * *` | git-health-check | `…/scripts/mesh/git-health-check.sh` | is the app checkout behind origin | `499 runs, 0 non-zero`; script posts to `http://localhost:8002/api/v1/system/alert` with `DASHBOARD_API_KEY` | PORT-ADAPT |
| 12 | `0 */6 * * *` | monitor-hetzner-backups | `/home/zabz/scripts/monitor-hetzner-backups.sh` | is the restic/Hetzner backup alive | `43 runs, 21 non-zero (49%)`; posts to `http://localhost:8002/ceo/chat` | PORT-ADAPT |
| 13 | `0 5 * * *` | daily-finance-sync-cron | `…/scripts/daily-finance-sync-cron.sh` | daily finance → secretary sync | `10 runs, 2 non-zero`; reads `$HOME/accounting-data/live/accounting.db` | DEAD (ledger absent on cloud) |
| 14 | `7 * * * *` | site-uptime-check-cron | `…/scripts/site-uptime-check-cron.sh` | hourly public-site + local API uptime | `247 runs, 0 non-zero`; checks `local_api\|http://localhost:8002/health` | PORT-ADAPT |
| 15 | `20 5 * * *` | prune-backups | `…/scripts/server/prune-backups.sh /home/zabz/secretary-backups` | GFS + 205 GiB size-budget retention on local snapshots | `10 runs, 0 non-zero`; header records the 2026-09-30 near-outage at 99% disk | DANGEROUS-ON-CLOUD |
| 16 | `*/5 * * * *` | run-sentinel | `/home/zabz/ceo-kernel/scripts/run-sentinel.sh` | ceo-kernel sensing tick | `2991 runs, 0 non-zero` | PORT-ADAPT |
| 17 | `*/30 * * * *` | run-ha-truth | `/home/zabz/ceo-kernel/scripts/run-ha-truth.sh` | HA truth reconciliation | script uses `HA_ENV_FILE=/home/zabz/personal-secretary-mvp/.env`; `499 runs, 0 non-zero` | OFFICE-ONLY |
| 18 | `*/15 * * * *` | journal-commit | `/home/zabz/bin/journal-commit.sh … && /home/zabz/harness-config/scripts/autosync.sh` | commits the journal, syncs harness-config | `1003 runs, 284 non-zero (28%)` | PORT-ADAPT |
| 19 | `20 4 * * *` | run-ha-behaviour | `/home/zabz/ha-config-live/scripts/run-ha-behaviour.sh` | HA behaviour rules | `HA_HOST="${HA_HOST:-192.168.50.34}"`; `10 runs, 0 non-zero` | OFFICE-ONLY |
| 20 | `@reboot` | serve-phone | `…/harness-config/scripts/serve-phone.sh` | starts the phone gate/redirector | `serve-phone 5 runs, last 2026-10-11T02:42:11Z`; binds `127.0.0.1:3086/3087` | OFFICE-ONLY |
| 21 | `*/2 * * * *` | serve-phone-2 | same `serve-phone.sh` | keeps the phone gate up | `7470 runs, 298 non-zero (4%)`; `ss -ltnp` shows `127.0.0.1:3086` and `:3087` on office only | OFFICE-ONLY |
| 22 | `*/30 * * * *` | push-dsh-sessions | `DSH_ARCHIVE_ENDPOINT=http://127.0.0.1:8002/…/ingest …/push-dsh-sessions.mjs --transport http` | ships this machine's DSH sessions into the company DB | `498 runs, 48 non-zero`; log tail "REFUSED: 5 fragment(s) … ingest transport: fetch failed" | PORT-ADAPT |
| 23 | `*/30 * * * *` | dialpad-harvest-cron | `…/scripts/dialpad-harvest-cron.sh` | the shop's Dialpad **call** harvest | `496 runs, 13 non-zero (3%)` | PORT-ADAPT |
| 24 | `*/5 * * * *` | probe-phone | `/usr/bin/python3 …/probe-phone.py --quiet --json` | probes the phone gate/redirector/engine | script constants `GATE=127.0.0.1:3086 REDIRECT=:3087 ENGINE=:3089`; `2991 runs, 54 non-zero` | OFFICE-ONLY |
| 26 | `*/15 * * * *` | sampler | `…/.venv/bin/python /home/zabz/presence-runtime/sampler.py` | owner home/office presence | `999 runs, 72 non-zero`; one of the four jobs that held the DB during the freeze (H3407 §4) | OFFICE-ONLY |
| 27 | `30 5 * * *` | check-phone-ui | `…/check-phone-ui.sh --quiet` | renders the phone UI in a browser to prove it works | script: `URL=${PHONE_URL:-http://127.0.0.1:3086/}` and requires `google-chrome`/`chromium`; `10 runs, 1 non-zero` | OFFICE-ONLY |
| 28 | `*/5 * * * *` | model-failover-watch | `/usr/bin/python3 …/model-failover-watch.py` | probes every model tier and writes failover state | `2991 runs, 0 non-zero`; reads `~/.dsh/.credentials.yaml` and `HARNESS_CONFIG_REPO` | PORT-ADAPT |
| 30 | `7,37 * * * *` | comms-refresh | `/usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py` | rebuilds the comms FTS index beside the live file and swaps it in | `SOURCE=/home/zabz/personal-secretary-mvp/data/secretary.db`, `INDEX_DB=~/.fsearch/comms.db`; `495 runs, 34 non-zero` | PORT-AS-IS |
| 31 | `*/15 * * * *` | lpt-hub-refresh | `…/harness-config/scripts/lpt-hub-refresh.sh` | refreshes the lpt-hub checkout/index | `998 runs, 138 non-zero (14%)`; no office-only marker found in the script | PORT-AS-IS |
| 34 | `10 */6 * * *` | supplier-order-ingest | `…/.venv/bin/python …/supplier-order-ingest.py --apply` | ingests the supplier-order ledger from mail | `DB=…/data/secretary.db`, `API=http://127.0.0.1:8002`; `42 runs, 5 non-zero` | PORT-ADAPT |
| 35 | `17 */6 * * *` | supplier-delivery-watch | `…/.venv/bin/python …/supplier-delivery-watch.py --create-tasks` | ages paid-but-unshipped orders into tasks | same office DB + `127.0.0.1:8002`; `54 runs, **54 non-zero (100%)**` | DEAD |
| 37 | `*/5 * * * *` | dialpad-recording-gap | `cd …/personal-secretary-mvp && flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json` | backfills Dialpad voicemail media | `2992 runs, 1339 non-zero (45%)` | PORT-ADAPT |
| 39 | `*/10 * * * *` | dialpad-transcript-gap | `cd … && flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600` | backfills call transcripts | `1494 runs, **0 non-zero**` | PORT-ADAPT |
| 40 | `30 3 * * *` | backup-phoenix-evidence | `/home/zabz/bin/backup-phoenix-evidence.sh` | copies HA recorder history off the office server | script: `SRC=root@192.168.50.34:/media/phoenix/history/`; `11 runs, 0 non-zero` | OFFICE-ONLY |
| 41 | `25 * * * *` | check-phoenix-evidence | `/usr/bin/python3 /home/zabz/bin/check-phoenix-evidence.py` | is that HA evidence copy still arriving | `HA_HOST="root@192.168.50.34"`; `250 runs, 112 non-zero (45%)` | OFFICE-ONLY |
| 44 | `*/30 * * * *` | family_chat_watchdog | `cd … && flock -n /tmp/family-chat-watchdog.lock .venv/bin/python scripts/family_chat_watchdog.py` | catches a silently broken family-chat hub or a DB that stopped matching the carrier | `DB_PATH=…/data/family_chat.db`, Twilio REST; `499 runs, 55 non-zero` | PORT-ADAPT |
| 45 | `15 5 * * *` | box-health-check | `/home/zabz/bin/box-health-check.sh` | restic snapshot age, rentals snapshot presence, then texts the owner | `11 runs, **8 non-zero (73%)**`; posts via the old `/ceo/chat` path | DEAD |
| 46 | `17 */6 * * *` | stripe-key-watch | `/usr/bin/python3 /home/zabz/bin/stripe-key-watch.py` | watches for a live Stripe secret appearing anywhere | `42 runs, 0 non-zero`; hardcoded office/lpt-apps backup paths | PORT-ADAPT |
| 47 | `*/15 * * * *` | production-comms-freshness | `…/.venv/bin/python3 /home/zabz/bin/production-comms-freshness.py` | reads the DB and reports comms-feed silence | `SECRETARY_DB="/home/zabz/personal-secretary-mvp/data/secretary.db"`; `998 runs, 65 non-zero` | PORT-ADAPT |
| 48 | `23 */4 * * *` | lpt-recon-check | `/home/zabz/bin/lpt-recon-check.sh` | reconciles LPT Dialpad ↔ production Postgres | `65 runs, **53 non-zero (82%)**` | DEAD |
| 49 | `9,39 * * * *` | website-comms-push-cron | `/home/zabz/bin/website-comms-push-cron.sh` | pushes comms to the website | `480 runs, 69 non-zero (14%)`; last 2026-10-11T03:39:04Z | PORT-ADAPT |
| 50 | `12,42 * * * *` | comms-refresh-2 | `…/.venv/bin/python3 …/comms-refresh.py --check --max-age-minutes 45` | fails when the comms index goes stale | `496 runs, 34 non-zero`; same source DB | PORT-ADAPT |
| 51 | `*/30 * * * *` | sync | `cd $HOME/code/unified-search && python3 scripts/sync.py --db $HOME/.usearch/usearch.db` | refreshes the unified search index | `498 runs, 104 non-zero`; `/home/zabz/code/unified-search` is a desk-scoped checkout | DEAD |
| 52 | `*/30 * * * *` | audit | `cd /home/zabz/repos/lpt-hub && …/tools/customer/audit.py --write-report …/four-surface.json` | four-surface customer audit | `500 runs, **500 non-zero (100%), last rc=1**`; log tail "🔴 12 ERROR finding(s)" is content, the rc is the failure | DEAD |
| 53 | `*/15 * * * *` | check-security-absence | `cd … && /usr/bin/python3 scripts/ha/check-security-absence.py --url http://192.168.50.34:8123 --env-file …/.env` | HA physical-security absence alarm | the literal URL in the crontab line; `998 runs, 0 non-zero` | OFFICE-ONLY |
| 58 | `* * * * *` | wake-fanout | `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh` | keeps N wake shifts in flight | `14945 runs, **0 non-zero**` | PORT-ADAPT |
| 59 | `*/5 * * * *` | sms-inbox | 4 chained commands: `sms-inbox.py sync --pages 3`; `sms-responder.py run --send --max-sends 2`; `sms-responder.py learn --apply`; `textdecide.py --refresh-catalog` | the owner's text line end to end | `2989 runs, 307 non-zero`; `sms-responder` last log line "Twilio webhook… database is locked" | PORT-ADAPT |
| 60 | `*/15 * * * *` | run-wake-sources | `/bin/bash /home/zabz/bin/run-wake-sources.sh` | advances the wake sources | `998 runs, 1 non-zero` | PORT-ADAPT |
| 61 | `15,45 * * * *` | dialpad-sms-harvest-cron | `…/scripts/dialpad-sms-harvest-cron.sh` | the shop's Dialpad **SMS** harvest | `499 runs, 32 non-zero` | PORT-ADAPT |
| 62 | `*/5 * * * *` | mesh-placement-monitor | `/usr/bin/python3 /home/zabz/bin/mesh-placement-monitor.py --quiet` | watches the mesh placement broker | `2991 runs, **1742 non-zero (58%), last rc=3**`; script `BROKER=http://127.0.0.1:3091`; `ss -ltnp` on office shows **nothing on 3091** | DEAD |
| 64 | `*/15 * * * *` | profile-gate | `DSH_HOME=/home/zabz/.dsh /home/zabz/node/bin/node …/profile-gate.mjs` | proves every DSH profile composes | `999 runs, 54 non-zero`; needs the DSH tree and node at that exact path | DEAD |
| 65 | `*/15 * * * *` | converge-authority | `/home/zabz/bin/converge-authority.sh` | converges the host to the authority's intent | `999 runs, **527 non-zero (53%)**` | DEAD |
| 70 | `*/15 * * * *` | wake-cost | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/wake-cost.py --days 1` | keeps the SPEND measurement current (owner set spend, not count, as the limit) | header cites D2715 and the 70 USD/day guard enforced against a 3.5× low figure; `998 runs, 109 non-zero` | PORT-ADAPT |
| 77 | `*/5 * * * *` | mirror-owner-sms | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/mirror-owner-sms.py --apply` | bridges the owner's live texts into the store the responder reads | `APP_DB=…/data/secretary.db → INBOX_DB=~/.sms-inbox/inbox.db`; `2991 runs, 9 non-zero` | PORT-ADAPT |
| 83 | `*/10 * * * *` | reconcile-sent-status | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/reconcile-sent-status.py --apply --hours 48` | asks Twilio the real delivery verdict and writes it back | Twilio creds from office `.env`; `1494 runs, 10 non-zero` | PORT-ADAPT |
| 88 | `*/15 * * * *` | promote-owner-texts | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/promote-owner-texts.py --apply` | repair-only priority promotion of owner texts | `DB = "/home/zabz/work/work.db"`; `998 runs, 1 non-zero` | PORT-ADAPT |
| 90 | `*/30 * * * *` | tree-integrity-check | `…/scripts/tree-integrity-check.sh` | runs the deploy gate and alarms if the tree is broken | `REPO=/home/zabz/personal-secretary-mvp`, `API=http://localhost:8002/sms/send`; `499 runs, 2 non-zero` | PORT-ADAPT |
| 92 | `23 * * * *` | work-integrator | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/work-integrator.py --days 3 --limit 3` | reviewed branches not on the integration base become work items | `250 runs, 0 non-zero`; `WORK_REGISTRY=/home/zabz/bin/sources/projects.json` | PORT-ADAPT |
| 93 | `7 * * * *` | cron-target-guard | `/home/zabz/bin/cron-target-guard.py --write-status` | checks every crontab target exists | `247 runs, 1 non-zero`; **the systems register §4.6 records it never decodes the base64** | PORT-ADAPT |
| 94 | `*/15 * * * *` | disk-guard | `/home/zabz/bin/disk-guard.py --write-status` | disk headroom + calls prune-backups | `998 runs, 198 non-zero`; `BACKUP_ROOT=/home/zabz/secretary-backups` | DANGEROUS-ON-CLOUD |
| 96 | `*/15 * * * *` | chip-resume | `flock -n /tmp/chip-resume.lock …/chip-resume.py` | Chip's scheduled return (owner instruction 2026-09-30) | `998 runs, 0 non-zero`; `REPO=Path("/home/zabz/personal-secretary-mvp")` | PORT-ADAPT |
| 101 | `41 * * * *` | wake-balance | `/usr/bin/python3 /home/zabz/bin/wake-balance.py --guard --warn 75 --repeat-hours 12` | warns at 75.00, stops work below 10.00, resumes above 15.00 | header 2026-10-05; `CRED=~/.dsh/.credentials.yaml`; `248 runs, 0 non-zero` | PORT-ADAPT |
| 107 | `*/30 * * * *` | cfo-ask | `/usr/bin/python3 /home/zabz/bin/cfo-ask.py --send` | asks the owner ONE unclear purchase, by text, ≤3/day | `ACCT_DB=…/accounting-data/live/accounting.db`; `398 runs, 73 non-zero` | DEAD (ledger absent on cloud) |
| 110 | `20 */6 * * *` | cfo-scoreboard | `/usr/bin/python3 /home/zabz/bin/cfo-scoreboard.py` | the CFO backfill program's measure | `DEFAULT_LEDGER=/home/zabz/accounting-data/live/accounting.db`; `33 runs, 0 non-zero` | DEAD (ledger absent on cloud) |
| 111 | `20 6 * * *` | pain-check | `/home/zabz/bin/pain-check.py --write-status` | runs the pain-check suite that closes fixed defects | `9 runs, **9 non-zero (100%), rc=1**` | DEAD |
| 117 | `*/5 * * * *` | deadman | `/usr/bin/python3 /home/zabz/bin/deadman.py` | pings an EXTERNAL dead-man switch with a context body | `2378 runs, 0 non-zero`; log tail `ping http 200 :: wake=done:465,… dispatch_procs=0`; needs `~/.sms-inbox/deadman.env` | PORT-ADAPT |
| 122 | `*/30 * * * *` | owner-ask | `/usr/bin/python3 /home/zabz/bin/owner-ask.py --send` | the owner intake: ONE question at a time, with a recommendation | `APP_DB=…/data/secretary.db`, `ACCT_DB=…/accounting.db`; `397 runs, 0 non-zero` | PORT-ADAPT |
| 127 | `*/15 * * * *` | text-channel-check | `/home/zabz/bin/text-channel-check.sh` | runs `text-health.py` (12 checks) + `test-owner-guard.py` | `994 runs, **902 non-zero (91%)**` | DEAD |
| 130 | `*/15 * * * *` | guard-registry | `/home/zabz/bin/guard-registry-check.py --write-status` | a different process verifies the guards that matter | `868 runs, 190 non-zero (22%)`; reads `secretary.db` **read-only** | PORT-ADAPT |
| 131 | `*/5 * * * *` | engine-watch | `/usr/bin/python3 /home/zabz/bin/engine-watch.py` | watches the DSH phone engine | `UNIT=phone-engine.service`, `ENGINE_WATCH_ERR=~/.dsh-phone/engine-3089.err`; `2378 runs, 4 non-zero` | OFFICE-ONLY |
| 135 | `*/20 * * * *` | tmpfs-reaper | `mkdir -p /home/zabz/tmp-rescue && /home/zabz/bin/tmpfs-reaper.sh` | reaps cold scratch off the RAM-backed `/tmp` | office `/tmp` is a 12 GB tmpfs; `644 runs, 1 non-zero` | DEAD |
| 140 | `20 5 * * *` | order-feed-refresh | `/home/zabz/code/harness-config/scripts/order-feed-refresh.sh --refresh --apply` | refreshes Amazon order history for the ledger | `8 runs, **8 non-zero (100%), rc=127**`; **the script does not exist** (checked both `/home/zabz/code/harness-config/scripts/` and the symlinked `/home/zabz/harness-config/scripts/`) | DEAD |
| 145 | `40 6 * * *` | text-line-check | `/home/zabz/code/harness-config/scripts/text-line-check.sh` | re-measures the four text-line objectives daily | `8 runs, 3 non-zero, last rc=127`; **script does not exist**; log last written 2026-10-10 06:40 | DEAD |
| 146 | `*/30 * * * *` | ai-gateway-health | `…/.venv/bin/python …/scripts/ai-gateway-health.py --days 7` | which models are actually working | `401 runs, 397 non-zero (99%)`; `DB=…/data/secretary.db` | PORT-ADAPT |
| 147 | `10 5 * * *` | push-db-offsite | `/home/zabz/bin/push-db-offsite.sh` | the copy that survives the machine — DB + ledger → R2 | `6 runs, 2 non-zero, last 2026-10-10T05:10:01Z`; log last line "OK - both offsite copies verified" 2026-10-10 05:20; **sources `/home/zabz/secretary-backups/<stamp>/sqlite/data/secretary.db` and `…/accounting/data/live/accounting.db` from the OFFICE box** | DANGEROUS-ON-CLOUD |
| 148 | `40 1,7,13,19 * * *` | company-offsite-push | `/home/zabz/bin/company-offsite-push.sh` | streams the newest 6-hourly snapshot to Box 2 / restic | `28 runs, 25 non-zero (89%)`, last `2026-10-11T01:40:01Z`; log: `SKIP 20261011T000001Z - no COMPLETE marker` … `newest COMPLETE snapshot: 20261007T205901Z`; `INGEST_HOST=root@2.28.33.58` | DANGEROUS-ON-CLOUD |
| 149 | `*/30 * * * *` | report-offsite-age | `/home/zabz/bin/report-offsite-age.sh` | tells the outside vault how old the real offsite copy is | `216 runs, 0 non-zero`; log `{"key":"authority/secretary.db.gz","bytes":7234886331,"last_modified":"2026-10-10T05:20:09+00:00"}` at 2026-10-11T04:00:04Z; **reads R2 and writes one JSON — no database** | PORT-ADAPT |
| 150 | `0 6 * * 1` | (direct) | `/home/zabz/bin/lpt-audit-weekly.sh >> /home/zabz/.lpt-ops/audit/cron.log 2>&1` | weekly LPT audit | **log `/home/zabz/.lpt-ops/audit/cron.log` does not exist** (`ls` → "No such file or directory") | DEAD |
| 151 | `30 6 * * *` | (direct) | `/home/zabz/bin/lpt-dialpad-daily.sh >> /home/zabz/.lpt-ops/dialpad/cron.log 2>&1` | daily Dialpad report | log: `lpt-dialpad: 20261010T063002Z exit=1 bytes=1318` on three consecutive days, plus "could not fast-forward the checkout" | DEAD |
| 152 | `15 */2 * * *` | cfo-shift | `/home/zabz/bin/cfo-shift-cron.sh` | runs a CFO shift | `48 runs, 0 non-zero`; `LEDGER=…/accounting-data/live/accounting.db`; `/root/accounting-data/live` is **empty** on cloud | DEAD (ledger absent on cloud) |
| 153 | `17 * * * *` | lpt-deploy-drift | `cd … && /home/zabz/bin/lpt-deploy-drift.py` | long-running services older than the newest commit | `97 runs, **95 non-zero (98%), rc=3**` | DEAD |
| 154 | `* * * * *` | dialpad-call-fresh | `cd … && LOG=…; { flock -n 9 \|\| …; .venv/bin/python scripts/dialpad-call-fresh.py --hours 2 … } 9>/tmp/dialpad-call-fresh.lock` | keeps the newest calls fresh | `5663 runs, 214 non-zero`; log tail `database is locked`, `gave up … after 5 attempt(s) in 52.6s`, then `Terminated`; last rc=**143 (SIGTERM)** | PORT-ADAPT |
| 155 | `* * * * *` | lpt-freshness-watchdog | `cd … && flock -n /tmp/lpt-freshness.lock /home/zabz/bin/lpt-freshness-watchdog.py` | the shop pipeline's freshness watchdog | `5659 runs, 111 non-zero (2%)` | PORT-ADAPT |
| 156 | `23 * * * *` | lpt-retranscribe | `cd … && flock -n /tmp/lpt-retranscribe.lock …/.venv/bin/python /home/zabz/bin/lpt-retranscribe-drip.py 20` | re-transcribes calls from better audio | `94 runs, 0 non-zero`; the in-flight register calls the remainder a quality swap, not a gap | PORT-ADAPT |
| 157 | `45 7 * * *` | (direct) | `/home/zabz/bin/lpt-audit-freshness.py >> /home/zabz/.lpt-ops/audit/freshness.log 2>&1` | is the audit refresh loop alive | log: `lpt-audit-freshness: fresh (state 20261007T040603Z, 3.15 day(s) old)` — **the state has not advanced since 2026-10-07** | DEAD |
| 158 | `*/15 * * * *` | (direct) | `/home/zabz/bin/lpt-dialpad-apply.sh >> /home/zabz/.lpt-ops/dialpad/apply.log 2>&1` | applies Dialpad findings to production Postgres | log tail `psycopg2.errors.InvalidTextRepresentation: invalid input value for enum "OrderStatus": "COMPLETED"` … `lpt-dialpad-apply: exit 1` | DEAD |
| 159 | `*/5 * * * *` | store-write-check | `/usr/bin/python3 …/scripts/store-write-check.py --slow-seconds 5` | proves the company *store* still accepts writes | `1024 runs, 152 non-zero, last rc=143`; `DEFAULT_DB=…/data/secretary.db` | DANGEROUS-ON-CLOUD |
| 160 | `17 */6 * * *` | hours-drift | `python3 /home/zabz/bin/hours-drift-check.py > /home/zabz/.hours-drift/last.txt` | does the published-hours listing match the business | `20 runs, **20 non-zero (100%), rc=3**`; last.txt: `RESULT: DRIFT — 1 surface(s) not agreeing: Google Maps listing` | DEAD |
| 161 | `*/5 * * * *` | cron-script-guard | `/usr/bin/python3 /home/zabz/bin/cron-script-guard.py` | are the scripts cron calls still present and executable | `1005 runs, 0 non-zero`; log: `"cron_scripts_watched": 29, "present": 27, "ok": false` and `ATTENTION: 2 cron script(s) need a real fix` | PORT-ADAPT |
| 162 | `*/15 * * * *` | (direct) | `/home/zabz/bin/mesh-node-probe.sh >> /home/zabz/.mesh-probe/cron.log 2>&1` | probes each mesh node's health surface | not in the ledger under this name; the mesh surface is dead per the brief (`broker-unreachable`, curl exit 7) | DEAD |
| 164 | `35 5 * * 0` | lpt-business-report | `cd … && bash scripts/lpt-business-report.sh --months 6` | weekly money & customer report for the shop | **no ledger row at all**; `/home/zabz/.lpt-reports/cron.log` **does not exist**; added 2026-10-08, first due Sun | DEAD |
| 166 | `45 7 * * *` | lpt-report-freshness | `cd … && .venv/bin/python3 scripts/lpt-report-freshness.py --file` | is the weekly money/customer pipeline + its sources alive | `2 runs, 0 non-zero, last 2026-10-10T07:45:01Z`; log `all three questions answered and current` | PORT-ADAPT |
| 168 | `30 23 * * *` | lpt-daily-track | `cd … && .venv/bin/python3 scripts/finance/lpt-analytics.py track --out …/daily` | daily capture so the long-term series has no 6-in-7 hole | `2 runs, 0 non-zero, last 2026-10-10T23:30:02Z`; log `first_time NULL (not measured)` | PORT-ADAPT |
| 169 | `23 * * * *` | transcript-archive | `/home/zabz/bin/transcript-archive-run.sh >/dev/null 2>>…/cron.err` | pulls every machine's raw DSH/Copilot transcripts | `47 runs, **46 non-zero (98%), rc=3**`; err log `one or more machines could not be pulled` hourly; archive root `/home/zabz/lpt-transcripts` **exists on office (manifest.sqlite 1,544,192 B) and does NOT exist on cloud** | PORT-ADAPT |
| 172 | `*/15 * * * *` | reconcile-sms-status | `…/.venv/bin/python …/scripts/reconcile-sms-status.py --limit 200` | reads Twilio's real verdict back into the record | `180 runs, 1 non-zero`; GET-only, cannot send | PORT-ADAPT |
| 176 | `25 */6 * * *` | auto-categorize | `…/.venv/bin/python …/scripts/auto-categorize.py --apply` | runs the app's sanctioned categorisation writer on a clock | `10 runs, 0 non-zero`; log `categorized 0 of 1264 uncategorized (skipped 1264)` — **idle: it has no work left** | PORT-ADAPT |

### §1b — the office systemd timers (also scheduled, also must move)

| unit | schedule | ExecStart | state | evidence | verdict |
|---|---|---|---|---|---|
| `estate-monitor.timer` | `OnCalendar=*:0/2` (every 2 min) | `/home/zabz/bin/estate-monitor.py` | enabled, **active** | `systemctl list-timers`: `LAST Sun 2026-10-11 06:14:04 UTC` | PORT-ADAPT |
| `trunk-check.timer` | `OnCalendar=*-*-* 00/4:07:00` + `OnBootSec=10min` | `/bin/bash /home/zabz/bin/trunk-check.sh` | enabled, **active** | last `2026-10-11 05:44:32 UTC`, exit 0 | PORT-ADAPT |
| `tmp-reaper.timer` | `OnCalendar=*:0/15` + `OnBootSec=5min` | `/home/zabz/bin/tmp-reaper.sh --apply --age-days 3 --warn-pct 75` | enabled, **active** | last `2026-10-11 06:00:02 UTC`, exit 0 | DEAD (office `/tmp` tmpfs rationale) |
| `fa-index.timer` | `OnCalendar=*:0/15` + `OnBootSec=3min` | `/bin/bash /home/zabz/bin/build-indexes.sh` | enabled, **active** | last `2026-10-11 06:02:02 UTC`, exit 0 | PORT-ADAPT |
| `company-outcome-monitor.timer` | `OnCalendar=*-*-* 00/4:07:00` | `/home/zabz/bin/run-company-outcome-monitor.sh` | enabled, **active** | last `2026-10-11 04:07:00 UTC`, exit 0, ran 4m55s | PORT-ADAPT |
| `secretary-backup.timer` | — | `/home/zabz/personal-secretary-mvp/scripts/server/backup-data.sh` | **disabled**, service **failed** | `systemctl is-enabled` → `disabled`; `is-active` → `failed` | DANGEROUS-ON-CLOUD |
| `secretary-api-watchdog.timer` | — | `/home/zabz/bin/api-watchdog.sh` | **disabled** | `systemctl is-enabled` → `disabled` | DEAD |
| `secretary-access-watchdog.timer` | — | `…/scripts/server/access-watchdog.sh` | **disabled** | `systemctl is-enabled` → `disabled` | DEAD |
| `mesh-broker.service` | — | `/usr/bin/node /home/zabz/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091` | **disabled, inactive** | `is-enabled` → `disabled`; `ss -ltnp` shows **no listener on 3091** | DEAD |

### §1c — what the company app already does on the cloud box (do NOT duplicate)

`secratary-cloud:/opt/company/data/autopilot_state.json`, read with
`python3 -c` on the cloud box (single bounded read of the 157,604-byte JSON; **39 subsystems**):

| subsystem | last_ran_at | last_status |
|---|---|---|
| `plaid_sync` | 2026-10-11T05:41:23Z | ok |
| `receipt_sync` | 2026-10-11T05:41:47Z | ok |
| `paypal_sync` | 2026-10-11T05:41:19Z | **failed** |
| `amazon_sync` | 2026-10-11T05:41:19Z | **failed** |
| `ebay_sync` | 2026-10-11T05:41:19Z | **failed** |
| `financial_alert_sweep` | 2026-10-11T05:47:44Z | ok |
| `owner_attention_sweep` | 2026-10-11T05:49:30Z | ok |
| `activity_sync` / `gmail_decisions` / `email_catalog` | 05:48–05:49 | ok |
| `memory_consolidation` | 2026-10-11T05:42:58Z | ok |
| `world_context` / `world_index` | 2026-10-11T05:48:52Z | ok |
| `ceo_tick` / `company` / `healing` / `initiative` / `mashgiach` | 05:52–05:56 | ok |
| `self_improvement` / `self_audit` / `shadow_learning` / `evolution` | 2026-10-10 21:45–23:50 | ok |
| `rule_consolidation` | 2026-10-10T13:52:18Z | ok |
| `google_voice_secretary` | 2026-10-05T03:33:45Z | ok (stale) |
| `fleet_location_poll` | 2026-09-29T03:44:44Z | **failed** |
| `boa_sync` / `balance_capture` / `spending_report` | old | `disabled_superseded` |

Top-level: `last_run_at 2026-10-11T06:09:42Z`, `run_count 3`, `last_error None`, `consecutive_failures 0`,
`interval_sec 900` (`AUTOPILOT_INTERVAL_SEC=900` in `/opt/company/.env`).

This is the overlap list. **`plaid_sync` and `owner_attention_sweep` already tick in-process** — so
`nightly-plaid-sync` and `owner-attention-digest` must NOT be ported as cron, or the company gets two
writers doing the same job. Everything else cron did is genuinely absent from the cloud box.

---

## §2 — THE PORT LIST, ordered by risk-if-absent

Ordered so that the things whose absence is *silent and unrecoverable* come first: backups, then external
dead-man switches, then freshness monitors, then ingestion, then guards, then the rest. Each entry: name,
machine it must run on, exact decoded command, dependencies that must exist on the cloud box, and how a
verifier proves it ran.

> **Path note for every entry below.** `~` on the office box is `/home/zabz`. The cloud box runs as
> **root** with no `/home/zabz`. Each command must be rewritten onto the cloud layout — the natural root is
> `/opt/company` (repo, venv at `/opt/company/.venv/bin/python`, data at `/opt/company/data`), with
> point state under `/root/`. Every dependency a command needs is listed; where a dependency does **not**
> exist yet on the cloud box it is marked **GAP** and is a blocker.

### Tier 1 — backups and the offsite copy (absence is unrecoverable)

**1. `authority-offsite-backup.sh` — the replacement for `push-db-offsite` (L147). Machine: `secratary-cloud`.**
- Already deployed (`/usr/local/bin/authority-offsite-backup.sh`, 7,165 B, mode 750, mtime 2026-10-11 05:55)
  and **has never run** — `/var/lib/authority-backup/` is empty.
- **Verdict: PORT-ADAPT.** Do **not** port `push-db-offsite.sh`: it reads the FROZEN office snapshot
  directory and would overwrite `authority/secretary.db.gz` with the 2026-10-10 copy (see §4).
- Dependencies: `/root/.lpt-r2.env` (present, mode 600, 643 B), `boto3` 1.40.72 on system python
  (present), `/root/authority.db`, free disk **4.4 GB of 75 GB — this is the binding constraint**; the
  script must take a `.backup` then stream it gzipped without leaving a second full copy.
- Prove it ran: `/var/lib/authority-backup/last-run` gains an mtime; R2 `authority/secretary.db.gz`
  `LastModified` and `ContentLength` advance; `authority/secretary.db.gz.sha256` matches.

**2. `report-offsite-age` (L149) — Machine: `secratary-cloud`, needs no DB.**
- Exact command: `/home/zabz/bin/report-offsite-age.sh`
  (on cloud: install as `/usr/local/bin/report-offsite-age.sh`).
- **Verdict: PORT-ADAPT.** This is the only job in the backup family that touches **no database**: it does
  `head_object` on R2 and writes one small JSON to the vault over ssh. Its whole purpose is that it runs
  OUTSIDE the office so it survives the office being dark — which is now literally true.
- Dependencies: `~/.lpt-r2.env` → `/root/.lpt-r2.env` (present); a python with `boto3` (system python,
  present — the app venv does **not** have boto3); `~/.ssh/id_ed25519_hetzner` → `/root/.ssh/id_ed25519_hetzner`
  (**GAP — verify present on cloud**); `VAULT=root@2.28.33.58`.
- Prove it ran: `report-offsite-age.log` gains an ISO-stamped JSON line per run; the vault file
  `/var/lib/company-offsite/authority-push.json` mtime advances. **Right now that JSON says
  `last_modified 2026-10-10T05:20:09Z`** — so the freshness alarm is currently reading a real number that
  is already ~25 h old and climbing.

**3. `prune-backups` (L15) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh /home/zabz/secretary-backups >> /home/zabz/secretary-backup-prune.log 2>&1`
- **Verdict: DANGEROUS-ON-CLOUD with a PORT-ADAPT successor.** The *policy* must move (a full disk is how
  this estate takes the company down: 2026-09-30, `/` at 99% with 7.6 GB free, SQLite SIGBUS), but pointed
  at the office snapshot directory it would delete the **rollback anchor's** snapshots. Port the script,
  point `ROOT` at the cloud's own backup root, keep the 205 GiB size budget.
- Dependencies: cloud backup root (does not exist yet — **GAP**), `PRUNE_MAX_TOTAL_KB` default 215,040,000.
- Prove it ran: prune log line per run; `df -h /` before/after.

**4. `db-integrity-check` (L7) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/bin/db-integrity-check.py --write-status >> /home/zabz/.db-integrity/cron.log 2>&1`
- **Verdict: DANGEROUS-ON-CLOUD in its current form, PORT-ADAPT as a design.** Its `LIVE_DB` default is the
  frozen office path, and its own header records that a check took **715–1,784 s, and 16,589 s on
  2026-10-06**. On the cloud box that is a 4-hour read against the live authority on a disk with 4.4 GB
  free. It must point at `/root/authority.db` and run against the **snapshot it just took**, not the live
  file.
- Dependencies: `SECRETARY_DB` → `/root/authority.db`; `DB_INTEGRITY_BACKUP_ROOT` → a cloud backup root;
  the shared I/O lock `/run/lock/secretary-io.lock`.
- Prove it ran: status file under `~/.db-integrity/` gains an mtime; one line per run in `cron.log`
  carrying `integrity_check ok`.

### Tier 2 — the external dead-man switch (absence is silent by construction)

**5. `deadman` (L117) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/bin/deadman.py >> /home/zabz/.sms-inbox/deadman.log 2>&1`
- **Verdict: PORT-ADAPT.** Every other heartbeat this estate keeps is read by something *on* the authority;
  this is the only mechanism that can report the authority being dead, because the report does not come
  from here. It ran every 5 minutes until the freeze — last good line
  `ping http 200 :: wake=done:465,dropped:16,failed:239,new:6 dispatch_procs=0`.
- Dependencies: `~/.sms-inbox/deadman.env` (mode 600) holding `HEALTHCHECKS_PING_URL` + `HEALTHCHECKS_API_KEY`
  — **GAP, must be copied from the office box**; `~/.sms-inbox/inbox.db` for the context body (**GAP** —
  it degrades gracefully: the body says `wake=unreadable(...)` rather than failing); `ps -eo args=` to count
  dispatch procs (harmless on cloud).
- Prove it ran: `deadman.log` gains a `ping http 200 :: …` line every 5 minutes. Independently: the
  healthchecks.io check "secratary authority alive" (period 900 s, grace 300 s) stays green — and because
  the check is external, **the only way to prove this is meaningful is to let it lapse and confirm an alert
  arrives.** Note the check's name is still `secratary authority alive` and now watches a different machine;
  that name should be corrected when it is re-armed.

### Tier 3 — freshness monitors (absence means a broken pipeline looks healthy)

**6. `production-comms-freshness` (L47) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python3 /home/zabz/bin/production-comms-freshness.py >> /home/zabz/.lpt-recon/production-freshness.log 2>&1`
- **Verdict: PORT-ADAPT.** Names `SECRETARY_DB="/home/zabz/personal-secretary-mvp/data/secretary.db"`
  (line 37) and `ENV_FILE` (line 38) as literals.
- Dependencies: `SECRETARY_DB` → `/root/authority.db` (**edit required**), env file, venv with the app's
  dependencies at `/opt/company/.venv/bin/python3`. It opens the DB with `mode=ro` — read-only, safe.
- Prove it ran: `production-freshness.log` line per run with the per-feed silence figure
  (`FEED_MAX_SILENCE dialpad_calls 12.0 h, dialpad_sms 6.0 h`).

**7. `lpt-report-freshness` (L166) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && .venv/bin/python3 scripts/lpt-report-freshness.py --file >> /home/zabz/.lpt-reports/freshness-cron.log 2>&1`
- **Verdict: PORT-ADAPT.** Its last good run reports
  `[fresh] source: dialpad SMS feed 12h … [fresh] source: dialpad call feed 13h … all three questions answered and current`.
- Dependencies: `TRACKING_DB = REPORTS_ROOT/tracking.db` (**GAP — `~/.lpt-reports/tracking.db` must be copied**),
  the app venv, `/root/authority.db` for the Dialpad tables.
- Prove it ran: `freshness-cron.log` gains its three-line block and `status file: …/freshness.json` mtime
  advances; exit 0.

**8. `lpt-freshness-watchdog` (L155) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/lpt-freshness.lock /home/zabz/bin/lpt-freshness-watchdog.py >> /home/zabz/.lpt-ops/dialpad/watchdog.log 2>&1`
- **Verdict: PORT-ADAPT.** Ran every minute (5,659 runs), 2% non-zero — a healthy guard.
- Dependencies: app venv, `/root/authority.db`, `/tmp` writable for the lock.
- Prove it ran: `watchdog.log` mtime advances at least once a minute.

**9. `ai-gateway-health` (L146) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/personal-secretary-mvp/scripts/ai-gateway-health.py --days 7 >> /home/zabz/.ai-gateway-health/cron.log 2>&1`
- **Verdict: PORT-ADAPT.** This is the monitor that would have caught the hardcoded-model outage that
  silently fell back for a week — and its own last output is alarming: `tier-collapse model_tier1,
  model_tier2, model_tier3 all point at deepseek/deepseek-v4-flash` and three models at 100% failure over 7d.
- Dependencies: `DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"` (line 45, **edit**),
  `CONFIG = "…/app/config.py"` (line 46, → `/opt/company/app/config.py`).
- Prove it ran: `cron.log` gains a run block; `model_usage` in the authority gains rows.

**10. `site-uptime-check-cron` (L14) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/site-uptime-check-cron.sh`
- **Verdict: PORT-ADAPT.** Checks `local_api|http://localhost:8002/health|secretary_api` — on the cloud box
  8002 is the live `company-api`, so the check becomes *more* meaningful, not less.
- Dependencies: nothing beyond the API being up on 127.0.0.1:8002 (**present**). **Watch the IPv4/IPv6 trap
  from H3407 §6** — the tunnel broke because `localhost` resolved to `::1`; keep `127.0.0.1` explicit.
- Prove it ran: run recorded in `~/.cron-status/runs.tsv`, plus the check's own log line.

**11. `disk-guard` (L94) — Machine: `secratary-cloud`, with the disk constraint re-tuned.**
- Exact command: `/home/zabz/bin/disk-guard.py --write-status >> /home/zabz/.disk-guard/guard.log 2>&1`
- **Verdict: DANGEROUS-ON-CLOUD today, and the single most important guard to make correct.** It hardcodes
  `RETENTION_SCRIPT = /home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh` and
  `BACKUP_ROOT = /home/zabz/secretary-backups`. On the cloud box the disk is at **94% with 4.4 GB free** —
  exactly the condition this guard exists to catch — and as written it would run the office retention script
  against the office backup tree.
- Dependencies: `WARN_PCT 90`, `CRIT_PCT 95`, `TMP_WARN_PCT 80`; `BACKUP_ROOT` → a cloud root.
- Prove it ran: `guard.log` line per run with the percentage; and it should be **alarmed right now** —
  94% is above `WARN_PCT`.

**12. `monitor-hetzner-backups` (L12) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/scripts/monitor-hetzner-backups.sh`
- **Verdict: PORT-ADAPT.** 49% non-zero over 43 runs — already half-broken before the cutover.
- Dependencies: posts to `curl -s -m 20 -X POST http://localhost:8002/ceo/chat` (cloud API, present);
  the restic/Hetzner credentials the script reads (**verify**).
- Prove it ran: run row in the ledger plus the script's notification reaching `/ceo/chat`.

**13. `engine-watch` (L131) — Machine: office only.**
- **Verdict: OFFICE-ONLY** — `ENGINE_WATCH_UNIT=phone-engine.service`,
  `ENGINE_WATCH_ERR=/home/zabz/.dsh-phone/engine-3089.err`, queue `~/bin/owner-queue.py`. Listed here only
  so the five downstream workstreams do not try to port it.

### Tier 4 — company-data ingestion (silence = the company stops learning)

**14. `dialpad-harvest-cron` (L23) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/dialpad-harvest-cron.sh`
- **Verdict: PORT-ADAPT.** 3% non-zero — one of the healthiest jobs in the list, and the source of the
  shop's call record.
- Dependencies: app venv, `DIALPAD_API_KEY` from the app `.env`, `/root/authority.db` (writes
  `dialpad_call_full`/`harvest_calls`), a `.dialpad-harvest.last_run` marker.
- Prove it ran: `~/.cron-status/runs.tsv` row with rc 0 **and** `MAX(date_started_ms)` in
  `dialpad_call_full` advances; the log records a healthy pass.

**15. `dialpad-sms-harvest-cron` (L61) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/dialpad-sms-harvest-cron.sh >> /home/zabz/.sms-inbox/dialpad-sms-harvest.log 2>&1`
- **Verdict: PORT-ADAPT.** Depends on the same `.env` key and writes `dialpad_sms_cache`.
- Prove it ran: `MAX(created_at)` in `dialpad_sms_cache` advances (the freshness monitor in #6 watches
  exactly this column).

**16. `dialpad-recording-gap` (L37) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json >> /home/zabz/dialpad-recording-gap.log 2>&1`
- **Verdict: PORT-ADAPT.** 45% non-zero. Design note from the in-flight register: the tool is idempotent and
  small-batched, and the failure family is "runs, exits 0, produces nothing", so a verifier must measure the
  job's **subject** (media files fetched), not the exit code.
- Dependencies: app venv, Dialpad API key, `hunt`/`vault` media store, cloud disk headroom.

**17. `dialpad-transcript-gap` (L39) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600 >> /home/zabz/dialpad-transcript-gap.log 2>&1`
- **Verdict: PORT-ADAPT.** **1,494 runs, zero non-zero** — the cleanest job in the inventory. The
  `--max-minutes 600` budget and the cumulative spend ceiling live inside the tool.
- Dependencies: transcription provider credential, app venv, the media store. This one spends money, so a
  verifier should check the spend ledger, not just the exit code.

**18. `dialpad-call-fresh` (L154) — Machine: `secratary-cloud`.**
- Exact command (full, and it is a compound shell line — reproduced verbatim from the crontab line at
  `L154`; the shell variables are deliberately left as `$…` so the line can be pasted back into a crontab):

```sh
cd /home/zabz/personal-secretary-mvp && LOG=/home/zabz/.lpt-ops/dialpad/call-fresh.log; { flock -n 9 || { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) SKIPPED: previous dialpad-call-fresh run still holds the lock" >> "$LOG"; exit 0; }; ./.venv/bin/python scripts/dialpad-call-fresh.py --hours 2 >> "$LOG" 2>&1; rc=$?; if [ "$rc" -ne 0 ]; then echo "dialpad-call-fresh rc=$rc; last log: $(tail -c 200 "$LOG" | tr '\n\t' '  ')" >&2; fi; exit "$rc"; } 9>/tmp/dialpad-call-fresh.lock
```
- **Verdict: PORT-ADAPT, and this one has a known defect to fix while moving it.** Its log ends
  `dialpad_call_full write gave up for 6453199368921088 after 5 attempt(s) in 52.6s (budget 45s): database is locked`
  then `Terminated`, and the ledger's last row for it is **rc=143 (SIGTERM)**. The in-flight register names
  the family: "three writers where `database is locked` discarded completed work — in one case work already
  paid for (L1484)."
- Dependencies: app venv, `/root/authority.db`, `/tmp` lock. On the cloud box there is only one writer for
  the company DB, which removes a source of that lock contention — but the fix must be verified, not assumed.
- Prove it ran: `SKIPPED:` absence in the log for the last N minutes **and** rc 0 rows in the ledger.

**19. `comms-refresh` (L30) — Machine: `secratary-cloud`. PORT-AS-IS (path-adapted).**
- Exact command: `/usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py >> /home/zabz/.fsearch/comms-cron.log 2>&1`
- **Verdict: PORT-AS-IS.** The only job whose data source is a single literal path and which builds beside
  the live index and swaps it in atomically, so no reader ever sees a half-built table.
- Dependencies: `SOURCE → /root/authority.db` (one literal, line 59-60), `INDEX_DB = ~/.fsearch/comms.db`
  (**GAP — the 166,939-entry index must be copied, or rebuilt on the cloud box**), system python3.
- Prove it ran: `comms_state.json` advances and a `comms_search` query returns current rows.

**20. `comms-refresh-2` (L50) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python3 /home/zabz/.fsearch/comms-refresh.py --check --max-age-minutes 45 >> /home/zabz/.fsearch/comms-check.log 2>&1`
- **Verdict: PORT-ADAPT** (same source-path edit). This is the *check* half: it fails when the index goes
  stale, which is what turns "nobody looked" into an alarm.
- Prove it ran: one line per run in `comms-check.log`; non-zero when the index is stale.

**21. `reconcile-sms-status` (L172) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/personal-secretary-mvp/scripts/reconcile-sms-status.py --limit 200 >> /home/zabz/.sms-inbox/reconcile-sms-status.log 2>&1`
- **Verdict: PORT-ADAPT.** **READ-ONLY at Twilio — it only GETs, it cannot send, resend or cancel.** That
  matters: it is one of the few messaging jobs that is safe to enable without a new outbound-safety review.
- Dependencies: `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` from the app `.env`, `/root/authority.db`.
- Prove it ran: rows in `sms_log` move from `sent` to a terminal Twilio status; log line per run.

**22. `family_chat_watchdog` (L44) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/family-chat-watchdog.lock .venv/bin/python scripts/family_chat_watchdog.py >> /home/zabz/family-chat-watchdog.log 2>&1`
- **Verdict: PORT-ADAPT. Read-only; exits non-zero on drift.** Header: a reconciliation over
  2026-08-15..2026-09-16 found **151 of 1,448 carrier messages (10.4%)** absent from our store.
- Dependencies: `DB_PATH = REPO/data/family_chat.db` (**GAP — a separate database; must be shipped**),
  `family_chat_twilio_account_sid` + `family_chat_twilio_auth_token` + hub from settings.

**23. `supplier-order-ingest` (L34) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/personal-secretary-mvp/scripts/supplier-order-ingest.py --apply >> /home/zabz/.personal-secretary/supplier-delivery-watch.log 2>&1`
- **Verdict: PORT-ADAPT.** `DB`, `API=http://127.0.0.1:8002`, `LOOKBACK_DAYS=400`.
- Dependencies: mail credentials to read the supplier ledger, `/root/authority.db`, the cloud API on 8002.

**24. `lpt-daily-track` (L168) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && .venv/bin/python3 scripts/finance/lpt-analytics.py track --out /home/zabz/.lpt-reports/daily >> /home/zabz/.lpt-reports/track-cron.log 2>&1`
- **Verdict: PORT-ADAPT.** Only 2 runs ever — added 2026-10-09, so it is unproven rather than broken. Its log
  already says `first_time NULL (not measured)` and `[STALE, partial]`, which is honest reporting, not a crash.
- Dependencies: `~/.lpt-reports/tracking.db` (**GAP — 819 runs, 6,552 observations; must be copied**),
  app venv, the authority DB, production orders.

**25. `lpt-business-report` (L164) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && bash scripts/lpt-business-report.sh --months 6 >> /home/zabz/.lpt-reports/cron.log 2>&1`
- **Verdict: PORT-ADAPT**, but note it has **no ledger row and its log file does not exist** — added
  2026-10-08, first due Sunday, so it has probably never fired. It must be ported and then **watched for its
  first run**, not assumed working.

**26. `auto-categorize` (L176) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/personal-secretary-mvp/scripts/auto-categorize.py --apply >> /home/zabz/.cfo/categorize.log 2>&1`
- **Verdict: PORT-ADAPT.** Its header records the reason it exists: the app's sanctioned categorisation
  writer "had never been run by anything — no caller, no cron — so the backlog grew for 5.6 years". Last
  four runs all report `categorized 0 of 1264 uncategorized (skipped 1264)`, i.e. **idle, not failing.**
- Dependencies: app venv, the accounting ledger (**GAP**), the authority DB.

### Tier 5 — the owner channel, spend ceiling and the asks

**27. `wake-fanout` (L58) — Machine: `secratary-cloud`.**
- Exact command: `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh >> /home/zabz/.sms-inbox/wake-cron.log 2>&1`
- **Verdict: PORT-ADAPT.** **14,945 runs, zero non-zero** — the single most-exercised job in the estate.
  The comment above it in the crontab is the design record: the fan-out wrapper keeps N shifts in flight,
  every guard still applies (one row per claim, lease, backstop, spend ceiling, pause file), and
  "one-at-a-time was never a policy — it was an accident of the lock."
- Dependencies: `~/.sms-inbox/inbox.db` (**GAP, and it holds the `wake` rows — this is the queue**),
  `~/bin/wake-dispatch.sh`, the DSH engine, `WAKE_MAX_USD_PER_DAY`.
- Prove it ran: `wake.dispatched_at` advances; `dispatch_procs` in the deadman body is > 0 while shifts run.

**28. `run-wake-sources` (L60) — Machine: `secratary-cloud`.**
- Exact command: `/bin/bash /home/zabz/bin/run-wake-sources.sh >> /home/zabz/.sms-inbox/sources-cron.log 2>&1`
- **Verdict: PORT-ADAPT.** 998 runs, **1** non-zero.

**29. `wake-cost` (L70) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/wake-cost.py --days 1 >> /home/zabz/.sms-inbox/wake-cost-cron.log 2>&1`
- **Verdict: PORT-ADAPT, and this one is load-bearing for money.** The crontab comment (D2715, measured
  2026-09-28) records what breaks without it: "with nothing running this, the cost file was 18 hours stale
  and the 70 USD/day guard was enforced against a figure 3.5× too low."
- Dependencies: `~/.sms-inbox/inbox.db` (the `wake` release records), the authority DB's `model_usage`
  table (221,834 rows), `app/pricing.py`.

**30. `wake-balance` (L101) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/bin/wake-balance.py --guard --warn 75 --repeat-hours 12 >> /home/zabz/.sms-inbox/wake-balance.log 2>&1`
- **Verdict: PORT-ADAPT.** Warns the owner at 75.00 (a question, not a pause), stops work below 10.00,
  resumes only above 15.00 and only if the pause file is the one it wrote itself. The provider has no
  auto-recharge, so the early warning is the only control there is.
- Dependencies: `~/.dsh/.credentials.yaml` (**GAP — copy the provider key**), the provider balance endpoint.

**31. `owner-ask` (L122) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/bin/owner-ask.py --send >> /home/zabz/.owner-ask/cron.log 2>&1`
- **Verdict: PORT-ADAPT — and this is the job that exists because he asked for it 87 times since March.**
  ONE question, one at a time, in his hours, with a recommendation, never re-asking.
- Dependencies: `APP_DB` → `/root/authority.db`, `ACCT_DB` → the accounting ledger (**GAP**),
  `ASK_DB=~/.owner-ask/asks.db` (**GAP — must be copied or the de-dup/re-ask history restarts**),
  `~/bin/owner-queue.py` for filing, and a send path that is reviewed before it is enabled.
  **Sending is outbound: per the estate's hard stop this must not be enabled without the owner's explicit
  per-message approval of its first live output.** Enabling the job is not the same as approving its words.

### Tier 6 — guards and self-checks

**32. `cron-target-guard` (L93) — Machine: `secratary-cloud`, and it needs fixing before it is trusted.**
- Exact command: `/home/zabz/bin/cron-target-guard.py --write-status >> /home/zabz/.cron-targets/guard.log 2>&1`
- **Verdict: PORT-ADAPT (necessarily rewritten).** Systems-register §4.6: it "reports `ok / 0 missing`
  because it never decodes the base64 in the crontab; ~60 of its 'checked' targets are the one wrapper."
  Its 247 runs and 1 non-zero, across the weeks when two crontab targets were genuinely **absent**, is the
  proof that it was green while broken. **Port it only pointing at the new crontab AND decoding the payloads —
  otherwise the new authority inherits the same blind spot.**

**33. `cron-script-guard` (L161) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/bin/cron-script-guard.py >> /home/zabz/.cron-scripts/guard.log 2>&1`
- **Verdict: PORT-ADAPT.** This one works and is the honest half of the pair: its log says
  `"cron_scripts_watched": 29, "present": 27, "ok": false` … `ATTENTION: 2 cron script(s) need a real fix`.
  It is the guard that caught `order-feed-refresh.sh` and `text-line-check.sh` missing.

**34. `guard-registry` (L130) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/bin/guard-registry-check.py --write-status >> /home/zabz/.guard-registry/cron.log 2>&1`
- **Verdict: PORT-ADAPT.** 22% non-zero. Opens the company DB **read-only** to read
  `owner_decision_queue`; `DEFAULT_LEDGER_DB` → `/root/authority.db`.

**35. `tree-integrity-check` (L90) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/tree-integrity-check.sh >/dev/null 2>&1`
- **Verdict: PORT-ADAPT.** `REPO` → `/opt/company`; `API=http://localhost:8002/sms/send` (present).
  499 runs, 2 non-zero.

**36. `lpt-hub-refresh` (L31) — Machine: `secratary-cloud`. PORT-AS-IS.**
- Exact command: `/home/zabz/harness-config/scripts/lpt-hub-refresh.sh >> /home/zabz/.lpt-hub-refresh/cron.log 2>&1`
- **Verdict: PORT-AS-IS** — the only job besides `comms-refresh` with no office-only marker at all.
  Dependencies: the `harness-config` checkout and the `lpt-hub` checkout on the cloud box (**GAP**).

**37. `work-integrator` (L92) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/work-integrator.py --days 3 --limit 3 >> /home/zabz/.sms-inbox/integrator.log 2>&1`
- **Verdict: PORT-ADAPT.** 250 runs, **0** non-zero. `WORK_REGISTRY=/home/zabz/bin/sources/projects.json`.

**38. `chip-resume` (L96) — Machine: `secratary-cloud`.**
- Exact command: `flock -n /tmp/chip-resume.lock /home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/bin/chip-resume.py >> /home/zabz/chip-resume.log 2>&1`
- **Verdict: PORT-ADAPT.** `REPO=Path("/home/zabz/personal-secretary-mvp")` → `/opt/company`.

**39. `journal-commit` (L18) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/bin/journal-commit.sh >/dev/null 2>&1 && /home/zabz/harness-config/scripts/autosync.sh >/dev/null 2>&1`
- **Verdict: PORT-ADAPT.** 28% non-zero — the highest failure rate among jobs that are not clearly dead, and
  the reason the journal's continuity depends on a job that fails one run in three. Copy the
  **`journal/` tree state** (especially `journal/.lock` hygiene — the in-flight register records that
  `questions` and `import-legacy` leave a stale lock after exit 0) and wire it to the cloud's git remote.
- Prove it ran: `git log` on harness-config gains commits; `~/.dsh-sync-status/status.json` says
  `result: clean`.

**40. `run-sentinel` (L16) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/ceo-kernel/scripts/run-sentinel.sh`
- **Verdict: PORT-ADAPT.** 2,991 runs, **0** non-zero. Dependencies: the `~/code/ceo-kernel` checkout
  (**GAP**), its state dir, and the owner queue.

**41. `model-failover-watch` (L28) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/harness-config/scripts/model-failover-watch.py >> /home/zabz/.dsh-model-watch/cron.log 2>&1`
- **Verdict: PORT-ADAPT.** 2,991 runs, **0** non-zero. Probes all tiers (one 1-token completion each per run,
  20 s cap). Dependencies: `~/.dsh/.credentials.yaml` (**GAP**), `/usr/bin/python3`, and it writes a mirror
  to `MFW_MIRROR_REMOTE=mirror` (**verify that remote exists from the cloud box**).

**42. `stripe-key-watch` (L46) — Machine: `secratary-cloud`.**
- Exact command: `/usr/bin/python3 /home/zabz/bin/stripe-key-watch.py >> /home/zabz/.lpt-verify/stripe-watch.log 2>&1`
- **Verdict: PORT-ADAPT.** 42 runs, 0 non-zero. It watches for a live Stripe secret appearing anywhere — and
  its comparison paths are office/lpt-apps literals
  (`/home/zabz/personal-secretary-mvp/.env.bak-striperoll-20260915`, `lpt-apps:/opt/lpt/.env.bak-striperoll-20260915`).
  Those references must be kept, not dropped: they are the known-good fingerprints this check compares against.

**43. `node-agent-cron` (L9) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/personal-secretary-mvp/scripts/mesh/node-agent-cron.sh`
- **Verdict: PORT-ADAPT.** 11% non-zero. Needs `VSCODE_CHAT_INGEST_TOKEN` from the app `.env` and posts to
  `--hub http://localhost:8002`.

**44. `push-dsh-sessions` (L22) — Machine: `secratary-cloud`, and the endpoint is the whole point.**
- Exact command: `DSH_ARCHIVE_ENDPOINT=http://127.0.0.1:8002/api/v1/owner/dsh-sessions/ingest /home/zabz/node/bin/node /home/zabz/harness-config/scripts/push-dsh-sessions.mjs --transport http >>/home/zabz/.dsh-session-ship.log 2>&1`
- **Verdict: PORT-ADAPT.** On the cloud box `127.0.0.1:8002` **is** the live authority, so this command is
  correct as written *provided* it runs on the cloud box and not against a stale office listener.
  Its last log line before the freeze: `REFUSED: 5 fragment(s) not accepted by the authority — ingest
  transport: fetch failed`, with cursors correctly left un-advanced so they re-send.
- Dependencies: `~/.dsh` session store on whichever machine runs it, `/home/zabz/node/bin/node` →
  a node path that exists on cloud (**GAP — verify**), the harness-config checkout.
- Prove it ran: `dsh_session_events` row count in `/root/authority.db` advances; the pusher's cursor
  advances; the ship log shows `queued: N session(s)` with no `REFUSED`.

**45. `transcript-archive` (L169) — Machine: `secratary-cloud` (after moving the archive).**
- Exact command: `/home/zabz/bin/transcript-archive-run.sh >/dev/null 2>>/home/zabz/.transcript-archive/cron.err`
- **Verdict: PORT-ADAPT, and it is currently broken.** 47 runs, **46 non-zero (98%)**, with
  `one or more machines could not be pulled` in the error log every hour for at least the last 6 hours.
  It is also one of the two jobs that satisfies the standing rule that **every DSH session and every VS
  Code Copilot chat is archived forever, with a copy always existing**.
- Dependencies: the archive root. **Measured: `/home/zabz/lpt-transcripts` exists on the office box
  (`manifest.sqlite` 1,544,192 B, `incoming/`, `logs/`, mtime 2026-10-11 06:09) and does NOT exist on the
  cloud box** (`ls /home/zabz/lpt-transcripts` and `/root/lpt-transcripts` both → "No such file or
  directory"). The archive must move, or the job keeps failing while looking scheduled.
- Prove it ran: `--check` exits 0; `manifest.sqlite` advances; and the distinction the tool itself makes —
  **GAP (exit 1) is a real defect, SILENCE (exit 2) is unjudgeable from here — must be reported as such, never
  as health.**

**46. `order-feed-refresh` (L140) — DEAD; see §3.** Its *purpose* (keep the ledger's Amazon order history
fresh, and raise ONE owner question when it cannot be) must be re-implemented, because
`amazon_sync`/`ebay_sync`/`paypal_sync` are all `failed` in the cloud autopilot today.

**47. `lpt-audit-freshness` (L157) — DEAD as a job, but its *question* must survive.** It asks "is the audit
refresh loop alive"; its last answer is `state 20261007T040603Z, 3.15 day(s) old`. See §3.

**48. `lpt-retranscribe` (L156) — Machine: `secratary-cloud`.**
- Exact command: `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/lpt-retranscribe.lock /home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/bin/lpt-retranscribe-drip.py 20 >> /home/zabz/.lpt-ops/dialpad/retranscribe.log 2>&1`
- **Verdict: PORT-ADAPT.** 94 runs, **0** non-zero. Low priority: the in-flight register records this as a
  quality swap on calls that already have Dialpad text, ~45 USD for the remainder, not a gap.

**49. `website-comms-push-cron` (L49) — Machine: `secratary-cloud`.**
- Exact command: `/home/zabz/bin/website-comms-push-cron.sh`
- **Verdict: PORT-ADAPT.** 480 runs, 14% non-zero. Needs the website endpoint credential (**verify**).

**50. `lpt-report-freshness` / `production-comms-freshness` are entries #6/#7 above; no separate work.**

---

## §3 — EVERY DEAD ITEM, WITH ITS EVIDENCE

Rule applied: DEAD = superseded · target missing · or failed ~100% for weeks. **21 jobs.**

| job | L | schedule | the evidence | why it is dead |
|---|---|---|---|---|
| `heartbeat` | 1 | `@reboot` | `runs.tsv`: 5 rows, last `2026-10-11T02:42:11Z` with a corrupted timestamp field; script `/home/zabz/heartbeat.sh` is a 99-byte infinite `while true … sleep 60` loop whose mtime is **2026-06-28 02:20 (2,524 h old)** | a 2013-era liveness toy; it is a process that writes `~/heartbeat.log` and nothing reads it. The `@reboot` line means it only ever starts on boot, and it is the process that kept `cron.service`'s cgroup alive after the freeze (`systemctl status cron` lists `1673 /bin/bash /home/zabz/heartbeat.sh`) — i.e. it is a **freeze hazard**, not a service |
| `mesh-health` | 2 | `*/5` | script mtime **2026-06-28 03:32 (2,522.7 h old)**; the script ends with `scp … "$MANIFEST" laptop:"C:/Users/ezabz/.personal-secretary/mesh-health.json"` | writes a manifest and pushes it to a host named `laptop`, a name that no longer exists in the fleet (it is `ZABZ-YOGA`/`laptop-ts`). 2,991 ledger rows, all rc 0, all pointless |
| `supplier-delivery-watch` | 35 | `17 */6 * * *` | `runs.tsv`: **54 runs, 54 non-zero (100%)**, last `2026-10-11T00:17:01Z` rc=3 | the "pays attention to paid orders that never ship" job (journal pain P132) has **never** had a successful run |
| `cron-target-guard`* | 93 | `7 * * * *` | 247 runs, 1 non-zero, while two crontab targets were genuinely absent | *kept in §2 as PORT-ADAPT because its **purpose** is essential — but as evidence it is dead: register §4.6, it never decodes the base64, so it reports `ok / 0 missing` when ~60 of its targets are one wrapper |
| `mesh-placement-monitor` | 62 | `*/5` | **2,991 runs, 1,742 non-zero (58%)**, last rc=3; script `BROKER=http://127.0.0.1:3091`; `ss -ltnp` on office shows listeners on 3086 and 3087 **only, nothing on 3091**; `mesh-broker.service` is `disabled`/`inactive` | it watches a broker that does not exist. The brief records the same failure from the other end: `broker-unreachable … curl: (7) Failed to connect to localhost:3091` |
| `converge-authority` | 65 | `*/15` | **999 runs, 527 non-zero (53%)** | converges the host to an authority that has moved. Half its runs fail by construction |
| `box-health-check` | 45 | `15 5 * * *` | **11 runs, 8 non-zero (73%)**; script greps `restic ls latest` on the office/lpt-apps path and posts to the pre-cutover `/ceo/chat` | three days of the last four failing |
| `audit` | 52 | `*/30` | **500 runs, 500 non-zero (100%)**, last rc=1; log tail `🔴 12 ERROR finding(s), 145 WARN` | the four-surface customer audit has never once exited 0. Its *finding* (12 real ERRORs incl. revoked pickup promises) is valuable; the cron entry is not working |
| `sync` (unified search) | 51 | `*/30` | 498 runs, 104 non-zero; target `/home/zabz/code/unified-search` | a desk-scoped checkout and a per-machine index; not part of the cloud authority's job |
| `order-feed-refresh` | 140 | `20 5 * * *` | **8 runs, 8 non-zero, rc=127**; the script **does not exist** at `/home/zabz/code/harness-config/scripts/order-feed-refresh.sh` (checked directly, and through the symlink `/home/zabz/harness-config → /home/zabz/code/harness-config`); log last written 2026-10-10 05:20 | rc=127 is "command not found" (register §4.5: "Exit 127 from a cron job means the SCRIPT MOVED"). **The purpose is not dead** — see §2 #46 |
| `text-line-check` | 145 | `40 6 * * *` | **8 runs, 3 non-zero, last rc=127**; script **does not exist**; log last written 2026-10-10 06:40 | same as above; added 2026-10-02 to re-measure the four text-line objectives daily, and it has no target |
| `pain-check` | 111 | `20 6 * * *` | **9 runs, 9 non-zero (100%), rc=1**; `JOURNAL=/home/zabz/harness-config/journal/tools/journal.py`, `CHECKS_DIR=/home/zabz/bin/pain-checks` | the loop that closes fixed defects is silently dead — the crontab itself records this failure at line 568-574 of `cron-wrap.sh`: "the pain check suite had not run for 37 h" |
| `text-channel-check` | 127 | `*/15` | **994 runs, 902 non-zero (91%)** | the job that runs `text-health.py` (12 checks) + `test-owner-guard.py` fails nine runs in ten |
| `tmpfs-reaper` | 135 | `*/20` | 644 runs, 1 non-zero — **healthy, dead by rationale** | its entire reason is `/tmp` being a RAM-backed tmpfs with usrquota on the office box (crontab comment: DSH's output spill raised EDQUOT and `phone-engine` died twice, 01:06:21Z and 02:47:52Z). Nothing on the cloud box has that defect; porting it would reap the wrong filesystem on a box that is already at 94% disk |
| `lpt-recon-check` | 48 | `23 */4 * * *` | **65 runs, 53 non-zero (82%)** | reconciles LPT Dialpad against production Postgres and reconciles a third of the time |
| `lpt-deploy-drift` | 153 | `17 * * * *` | **97 runs, 95 non-zero (98%), rc=3**; log shows long-running services with start times older than the newest commit | a drift detector that always reports drift is not detecting anything |
| `hours-drift` | 160 | `17 */6 * * *` | **20 runs, 20 non-zero (100%), rc=3**; last.txt: `RESULT: DRIFT — 1 surface(s) not agreeing: Google Maps listing` | it works and it is *correct to fail* — the Google listing genuinely disagrees (Mon: expected closed, surface says 10:30-17:30). Keep the finding, do not port the failing cron line unchanged |
| `profile-gate` | 64 | `*/15` | 999 runs, 54 non-zero; needs `DSH_HOME=/home/zabz/.dsh` + `/home/zabz/node/bin/node` at that exact path | a boot gate for a DSH install that is not on the cloud box |
| `lpt-audit-weekly` | 150 | `0 6 * * 1` | **its log `/home/zabz/.lpt-ops/audit/cron.log` does not exist** (`ls` → "No such file or directory") | a weekly job that has never written a line |
| `lpt-dialpad-daily` | 151 | `30 6 * * *` | log: `lpt-dialpad: 20261010T063002Z exit=1 bytes=1318` and the same for 20261009 and 20261008, plus `WARNING - could not fast-forward the checkout` | exit=1 on three consecutive days with a 1,318-byte report each time |
| `lpt-dialpad-apply` | 158 | `*/15` | log tail `psycopg2.errors.InvalidTextRepresentation: invalid input value for enum "OrderStatus": "COMPLETED"` … `lpt-dialpad-apply: exit 1` | a SQL enum mismatch against production Postgres, every run |
| `lpt-audit-freshness` | 157 | `45 7 * * *` | log: `lpt-audit-freshness: fresh (state 20261007T040603Z, 3.15 day(s) old)` | the job that asks "is the audit loop alive" reports a state file that has not advanced since **2026-10-07** — it is answering "fresh" about a dead loop |
| `secretary-startup` | — | **not scheduled** | `runs.tsv`: **2,984 rows**, last `2026-10-11T03:25:02Z`, rc 0 — and **no crontab line and no systemd unit by that name** (`grep -rl secretary-startup /etc/systemd/system/ /home/zabz/bin/` → empty) | 2,984 runs of a job that appears in no schedule anywhere. It is the clearest single example of the estate's core failure mode: a name in a status ledger that nothing can be reconciled against. **Flagged in §5** |
| `selftest-ok` / `selftest-fail` / `selftest-redir` / `probe-unwrapped` / `capture-test` | — | **not scheduled** | 1 row each on 2026-09-30, 2026-10-02, 2026-10-05 | `cron-wrap.sh`'s own self-tests and one deliberate unwrapped-payload test (its rc=2 is the wrapper correctly refusing, documented in the script header). Not jobs |

---

## §4 — EVERY OFFICE-ONLY ITEM

Bound to hardware or the office LAN. **These must NOT be ported; they must either be deleted from the new
crontab or replaced by a cloud-native equivalent.** 13 jobs, plus 2 notes.

| job | L | the binding thing | exact evidence |
|---|---|---|---|
| `check-security-absence` | 53 | HA on the office LAN | crontab line: `--url http://192.168.50.34:8123 --env-file /home/zabz/personal-secretary-mvp/.env` |
| `run-ha-truth` | 17 | HA + office env | script: `ENV_FILE="${HA_ENV_FILE:-/home/zabz/personal-secretary-mvp/.env}"` |
| `run-ha-behaviour` | 19 | HA on the office LAN | script: `HA_HOST="${HA_HOST:-192.168.50.34}"` |
| `backup-phoenix-evidence` | 40 | HA recorder disk on the office LAN | script: `SRC=root@192.168.50.34:/media/phoenix/history/` |
| `check-phoenix-evidence` | 41 | HA on the office LAN | script: `HA_HOST = "root@192.168.50.34"` |
| `serve-phone` | 20 | binds office loopback + office tailnet name | `REDIRECT_PORT=3087`; `ss -ltnp` on office: `127.0.0.1:3086` (pid 1366), `127.0.0.1:3087` (pid 1816) |
| `serve-phone-2` | 21 | same script, same binding | `7,470 runs, 298 non-zero` — the single most-run job after `wake-fanout` |
| `probe-phone` | 24 | probes the office gate/redirector/engine | script constants `GATE=("127.0.0.1",3086) REDIRECT=(…,3087) ENGINE=(…,3089)` |
| `check-phone-ui` | 27 | needs a local Chromium | script: `URL="${PHONE_URL:-http://127.0.0.1:3086/}"` and `command -v google-chrome`/`chromium` |
| `sampler` | 26 | office-LAN presence resolution | `/home/zabz/presence-runtime/sampler.py`; also one of the **four free-standing jobs that still held the database after every unit was down** (H3407 §4) |
| `engine-watch` | 131 | the office DSH phone engine unit | `UNIT=phone-engine.service`, `ERR_FILE=/home/zabz/.dsh-phone/engine-3089.err` |
| `run-ha-truth`/`run-ha-behaviour` are counted once each above | | | |

**Two office-only notes that are not cron lines:**

- **`secretary-backup.service` is `failed` and its timer is `disabled`.** ExecStart is
  `/home/zabz/personal-secretary-mvp/scripts/server/backup-data.sh` — the 6-hourly local snapshot maker whose
  `COMPLETE` marker both offsite pushers require. Its failure is why `company-offsite-push` logs
  `SKIP 20261011T000001Z - no COMPLETE marker` and fell back to `newest COMPLETE snapshot: 20261007T205901Z`.
  Evidence: `systemctl is-active secretary-backup.service` → `failed`; `is-enabled …timer` → `disabled`.
- **The rollback anchor itself.** `crontab.before` line 148's reason for existing is now inverted: it sourced
  `/home/zabz/secretary-backups`, which holds the frozen office snapshots. Nothing in the new crontab may
  point at that tree in a way that **writes**; reading it for a one-time migration copy is fine.

---

## §5 — EVERY DANGEROUS ITEM, WITH THE DAMAGE IT WOULD DO

Rule applied: would write to or ship the **FROZEN** office database · would create a **second writer**
against the company database · or would **delete the real `/root/authority.db`**.

| job | L | what it does if ported as-is | the damage |
|---|---|---|---|
| **`push-db-offsite`** | 147 | sources `/home/zabz/secretary-backups/<newest COMPLETE>/sqlite/data/secretary.db` (the **frozen office** snapshot) and `/home/zabz/accounting-data/live/accounting.db`, gzips, and uploads to `authority/secretary.db.gz` + `authority/accounting.db.gz` in R2 | **It would overwrite the company's only surviving offsite copy with the frozen office snapshot.** Observed value in R2 right now: `{"key":"authority/secretary.db.gz","bytes":7234886331,"last_modified":"2026-10-10T05:20:09+00:00"}` — the newest COMPLETE office snapshot is **2026-10-10T05:20**, the day before the cutover. Ported as-is it would either (a) succeed and publish a pre-cutover database as the current offsite authority, destroying the RPO silently while the freshness monitor reported a *fresh* object, or (b) fail at `NO SNAPSHOT WITH A DATABASE` and leave the company with no offsite copy at all while a green cron row accumulated. **The correct move is already built: `/usr/local/bin/authority-offsite-backup.sh` on the cloud box, which must be scheduled instead** |
| **`company-offsite-push`** | 148 | selects the newest `COMPLETE` snapshot under `/home/zabz/secretary-backups` and streams it with `tar -cf -` over ssh to `root@2.28.33.58` (`/root/company-offsite-backup.sh`), which writes it into the restic repo `psm-backups/company-offsite` | **A second, stale lineage written into the same restic repository the authority's backups live in.** Register §2.2 warns that the nightly `lpt-apps` job runs `restic forget` with no tag filter; a stale streamed snapshot lands beside the real one, byte-verifies, gets stamped **TRUSTED** (the script's own header: "byte equality proves the transport, never the content"), and can push the genuine copy out of retention. Live log evidence of the decay: `SKIP 20261011T000001Z - no COMPLETE marker`, `newest COMPLETE snapshot: 20261007T205901Z`, then `streaming 20261007T205901Z into the company repo` |
| **`prune-backups`** | 15 | `prune-backups.sh /home/zabz/secretary-backups` — deletes dated directories under the office backup root by GFS tier plus a 205 GiB size budget | **Deletes the rollback anchor.** The cloud box is 4.4 GB from full; the office box is the one place the pre-cutover state still exists. This script's header is a record of what a full disk does here: "SQLite does not degrade gracefully when its disk fills. It takes the whole company down with it." Pointing this at the office tree deletes the very snapshots that make the rollback possible |
| **`db-integrity-check`** | 7 | `PRAGMA integrity_check` over `LIVE_DB` (default: the frozen office path) on a 23.6 GB file | **Two harms at once.** (1) Its own header measures the cost: **715–1,784 s, and 16,589 s on 2026-10-06** — a multi-hour disk-hogging read of the office box, which is *exactly* the class of operation that took the box to load 52, 99% iowait and HTTP 502 for 20 minutes (P2936, H3406). (2) Run on the cloud box against `/root/authority.db` it is legitimate — but it must run against the snapshot the offsite script already takes, not the live file, or the check itself becomes the outage |
| **`store-write-check`** | 159 | opens `DEFAULT_DB = …/data/secretary.db` and probes whether the store accepts writes, every 5 minutes (`--slow-seconds 5`) | **A write probe against the company database.** On the office box that is a second writer against the frozen authority; on the cloud box its default points at a path that no longer exists, so it would either fail 100% (making a monitor that cried wolf, which the estate already had to fix once — `cron-wrap.sh`'s header records the `pain-check` line that "had not run for 37 h" while reporting nothing) or, if someone "fixes" the path by copying the office tree onto the cloud box, **create a stale second copy of the company database on a disk with 4.4 GB free.** Last ledger row for it is `rc=143 (SIGTERM)` — it was killed, not completed |
| **`disk-guard`** | 94 | `RETENTION_SCRIPT = /home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh`, `BACKUP_ROOT = /home/zabz/secretary-backups` | **It invokes the delete.** Its whole design is "when disk pressure is high, run retention" (the 2026-10-05 comment: prune "removed NOTHING across five runs while free space fell 71 → 34 → 23 → 15 → 6.4 GB"). Ported unchanged it calls the office retention script against the rollback anchor. This is the item most likely to be ported *by accident*, because "move the disk guard" reads like an obvious good idea — and it must be, but with `BACKUP_ROOT` and `RETENTION_SCRIPT` repointed at the cloud's own tree first |
| **`secretary-backup.service`** (systemd, not cron) | — | `/home/zabz/personal-secretary-mvp/scripts/server/backup-data.sh` — writes a fresh 18–22 GB snapshot into `/home/zabz/secretary-backups/<stamp>/` and writes the `COMPLETE` marker last | **The second writer, if anyone "fixes" the failed unit.** It is currently `failed` (service) and `disabled` (timer), which is the correct frozen state. Enabling it to make the offsite chain work again would write to the office database and fill a 92%-full disk. Register's opening block: "Anything that restarts one of them creates a SECOND WRITER against a database the cloud box is now serving — the one condition this whole design exists to prevent" |

**Explicitly checked and NOT dangerous:** nothing in the 92 decoded commands contains `rm -rf`, a `git reset
--hard`, or any reference to `/root/authority.db`; and no job deletes a database file. The `flock -n` lines
are single-flight guards, not deletions. The one line that contains `rm` is inside `push-db-offsite.sh`
(`_cleanup()` removing its own gzip temporaries under `/home/zabz/.offsite-stage`) and `push_one()`'s
`rm -f "$tmp"` — file-scoped to its own staging directory.

---

## §5b — NOT DETERMINED, STATED PLAINLY

1. **`secretary-startup` — 2,984 ledger rows with no schedule anywhere.** `runs.tsv` records
   `2026-09-30T16:15:01Z secretary-startup 0 1` through `2026-10-11T03:25:02Z`, every row rc 0, and there is
   **no crontab line and no systemd unit by that name** (`grep -rl 'secretary-startup' /etc/systemd/system/`
   → empty; the crontab has no such line). I could not determine what writes it. It is either a
   `cron-wrap.sh` name whose crontab line was renamed or removed before the freeze, or it is written by a
   process outside both cron and systemd. **It is the single best lead for the workstream auditing guard
   coverage** — a name with 2,984 runs and no reconcilable owner is precisely the failure mode
   `cron-target-guard` was built to catch and cannot.
2. **`lpt-business-report` (L164) has no ledger row at all** and its log file does not exist. I read this as
   "added 2026-10-08, weekly on Sunday, has not yet come due" — but I could not prove it never ran. Some
   ledger runs may have been reaped by `cron-wrap.sh`'s 5 MB truncation (`tail -n 20000`), which discards
   the OLDEST rows; with `wake-fanout` alone at 14,945 rows, truncation is plausible.
3. **Whether `~/.ssh/id_ed25519_hetzner` exists on the cloud box.** `report-offsite-age` and
   `company-offsite-push` both need it; I confirmed `~/.lpt-r2.env` exists on cloud (root, mode 600, 643 B)
   but did not read the ssh directory. **GAP to verify before enabling either.**
4. **The accounting ledger's fate.** `/root/accounting-data/live/` exists on the cloud box and is **empty**,
   and `/opt/company/data/accounting.db` is **0 bytes** (mtime 2025-08-28). The office ledger is
   `/home/zabz/accounting-data/live/accounting.db` (21,995,520 B). Every CFO job — `cfo-ask`,
   `cfo-scoreboard`, `cfo-shift`, `auto-categorize`, `daily-finance-sync-cron`, `owner-ask`, and the
   offsite script's second object — needs it. I did not verify whether it was included in the cutover; the
   evidence I have (an empty live directory and a zero-byte file) says **it was not**. This is the largest
   single functional gap I found and it deserves its own workstream.
5. **`~/.lpt-transcripts` (the raw transcript archive) is on the office box and not on the cloud box** —
   measured both. Whether the intent is to move it (1.5 MB manifest, plus `incoming/`) or to re-point the
   job at the office box is a design decision I did not make. Note that pointing the cloud job at the office
   box would make the archive depend on the machine that is about to go dark.
6. **The two missing scripts have no replacement anywhere I looked.** `order-feed-refresh.sh` and
   `text-line-check.sh` are referenced by the crontab, absent from
   `/home/zabz/code/harness-config/scripts/` (checked directly and through the symlink), and the only
   evidence they ever existed is `rc=127` rows plus a stale log. I did not search the whole disk for them,
   because a recursive search of the office box's filesystem is exactly the operation §RULE 1 forbids.
7. **`cron-wrap.sh` truncation as an evidence limit.** It rewrites `runs.tsv` to its last 20,000 rows when
   the file exceeds 5 MB. `runs.tsv` is currently well under that, so the counts in §1a are complete for the
   window 2026-09-30T16:13Z → 2026-10-11T04:01Z — but they are **not** all-time, and a job that failed
   heavily before 2026-09-30 would not show it.
8. **No item in this report was executed, and no verdict is a claim that the item works.** Every exit code
   cited came from `/home/zabz/.cron-status/runs.tsv` as it stood at the freeze; every log line came from a
   `tail` of a log file on `secratary-ts`. Where I say a job is healthy I mean its recorded exit codes were
   0, which is **not** the same as its output having been correct — the in-flight register's own warning
   applies: "a job that runs, exits 0 and produces nothing" is this estate's most productive defect family.
9. **The cloud box's `company-api` was not restarted, and I restarted nothing.** Per §RULE 5 of the brief.
   The only state I changed on any machine is a temporary file under `/tmp` on the office box
   (`/tmp/p.py`, `/tmp/cls.py`, `/tmp/l.py`, `/tmp/u.py`, `/tmp/w.py`, `/tmp/existschk.py`, `/tmp/dump1.py`)
   and `/tmp/aps.py`, `/tmp/aps2.py` on the cloud box — each removed in the same command that created it.

---

## §6 — COUNT SUMMARY

| verdict | count | jobs |
|---|---|---|
| PORT-AS-IS | 2 | `comms-refresh`, `lpt-hub-refresh` |
| PORT-ADAPT | 48 | §2, entries 1–50 (some entries cover a DANGEROUS item's replacement) |
| IN-PROCESS | 2 | `nightly-plaid-sync`, `owner-attention-digest` |
| DEAD | 21 | §3 |
| OFFICE-ONLY | 13 | §4 |
| DANGEROUS-ON-CLOUD | 6 | §5 |
| **total scheduled jobs inventoried** | **92** | of 176 crontab lines (92 jobs, 74 comment lines, 10 blank) |
| **plus systemd** | 5 active timers → PORT-ADAPT ×4 + DEAD ×1; 3 disabled timers → DEAD ×2 + DANGEROUS ×1; `mesh-broker.service` → DEAD | §1b |
| **retired ledger names** | 6 | §3, DEAD (not scheduled) |

**Order of work if the six workstreams start at the same time:** §2 #1–#5 (the offsite copy and its
freshness report, the dead-man switch) are the only items whose absence is both silent and unrecoverable.
Everything else can be late without new data being lost.
