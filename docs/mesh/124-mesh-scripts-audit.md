# 124 — Mesh scripts audit: cron vs. filesystem, and the known hazard patterns

Run **2026-10-09** by a mesh child agent on host **`zabz-tech`** (`COMPUTERNAME=ZABZ-TECH`). Repo
audited: `harness-config` (`C:\Users\ezabz\code\harness-config`; deployed on the authority at
`/home/zabz/code/harness-config`). One file written, this one. The only script executed anywhere was
`cron-target-guard.py --json` (its no-write form); everything else was `ls/grep/head/tail/du/df/find`
plus a base64 decoder run on the host itself.

## 1. Method

* `harness-config/scripts/` enumerated with `glob`, read with `read` — 382 tracked files.
* Crontabs pulled from `secratary-ts`, `lpt-apps`, `secratary-cloud`. `secratary-ts` resolves to a host
  whose own `hostname` is `secratary`; `lpt-apps` says `lpt-apps-01`; `secratary-cloud` does not
  resolve at all (§6).
* `secratary-ts` wraps every job as `/home/zabz/bin/cron-wrap.sh <name> <base64>` (169 non-blank crontab
  lines). The payloads were decoded **on the host** by piping `crontab -l` into a remote `python3 -c`
  that also resolved `~`, `$HOME` and the `cd X && …` cwd and tested each path with `os.path.exists` —
  which is why the *exists* column is authoritative rather than derived.

**Weakness, stated up front.** `ssh` stdout through a pipe is truncated on `zabz-tech` — already
documented in `scripts/assert-bin-matches-repo.py:27-35` as measured here on 2026-09-29. It reproduced:
four remote commands returned only their first section, or nothing. Everything that mattered was
re-obtained by making the *remote* process consume stdin, which flushes cleanly; still missing: §6.

## 2. Headline findings

1. **Two live defects.** `order-feed-refresh.sh` and `text-line-check.sh` are named by the live crontab
   and absent from the deployed tree; both were deleted on **2026-10-02** and cron was never updated
   (forensics in §3.1). Every other target on all three hosts resolves.
2. **`cron-target-guard.py` cannot see into `cron-wrap.sh`.** It parses raw crontab text, so for a
   wrapped job the first script token it finds is `/home/zabz/bin/cron-wrap.sh` and it stops. At
   `2026-10-09T19:39:02Z` it returned `ok: true, checked: 94, missing: []` while two targets were gone;
   ~60 of its 94 checked targets are that same wrapper file.
3. **A second guard does see them, and is shouting.** `cron-script-guard.py` (cron line 162, `*/5`)
   decodes the payloads, watches 29 cron scripts, and logged at `2026-10-09T19:45:02Z`: `ALERT missing
   and NOT tracked at HEAD: /home/zabz/code/harness-config/scripts/text-line-check.sh (used by cron:
   text-line-check) - a branch switch cannot be healed for this one; fix the cron path`, with
   `~/.cron-scripts/status.json` = `{cron_scripts_watched: 29, present: 27, ok: false}`. The defects
   are *known and loud*; what consumes that status file is not established (§6.7).
4. **The record of a failing job has no reader.** `cron-wrap.sh:58` appends
   `<time>\t<name>\t<rc>\t<secs>\t<stderr>` to `~/.cron-status/runs.tsv`; a repo-wide grep finds one
   writer and **no reader** — every other match is prose in `docs/` and `journal/`.
5. **`/tmp` on the authority is RAM-backed and quota'd** — `tmpfs (rw,nosuid,nodev,size=11992032k,usrquota)`
   (`tmpfs-reaper.sh`; `df` this run: `tmpfs 12G 34M 12G 1% /tmp`), with `/` at 467 G / 81%. It has
   already killed production processes twice (§5).
6. The multi-GB `/tmp` writers are **not in this repo**: the largest `/tmp` staging in
   `harness-config/scripts` is bounded at ~58 MB. The named 6.6 GB case (`push-db-offsite.sh`) is in
   `/home/zabz/bin/` and **has been fixed** — its own comments quote the dated failure (§5).

## 3. Every cron entry, host by host

### 3.1 `secratary-ts` (host `secratary`) — 93 entries, 2 broken

`resolved command` is the decoded base64 payload; `…` elides log redirections only — the target path
is always complete. `line` = line number in `crontab -l`. All 93 are listed.

| line | job | schedule | resolved command | exists |
|---|---|---|---|---|
| 1 | heartbeat | `@reboot` | `~/heartbeat.sh &` | yes |
| 2 | mesh-health | `*/5 * * * *` | `~/mesh-health.sh > ~/.personal-secretary/mesh-health.json 2>/dev/null` | yes |
| 3 | secretary-startup | `*/5 * * * *` | `pgrep -f "uvicorn app.main" >/dev/null \|\| ~/personal-secretary-mvp/scripts/secretary-startup.sh …` | yes |
| 8 | db-integrity-check | `17 4 * * *` | `/home/zabz/bin/db-integrity-check.py --write-status …` | yes |
| 9 | nightly-plaid-sync | `30 4 * * *` | `/home/zabz/personal-secretary-mvp/scripts/nightly-plaid-sync.sh …` | yes |
| 10 | node-agent-cron | `*/30 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/mesh/node-agent-cron.sh` | yes |
| 11 | owner-attention-digest | `*/30 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh > …/latest.txt` | yes |
| 12 | git-health-check | `*/30 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/mesh/git-health-check.sh` | yes |
| 13 | monitor-hetzner-backups | `0 */6 * * *` | `/home/zabz/scripts/monitor-hetzner-backups.sh` | yes |
| 14 | daily-finance-sync-cron | `0 5 * * *` | `/home/zabz/personal-secretary-mvp/scripts/daily-finance-sync-cron.sh …` | yes |
| 15 | site-uptime-check-cron | `7 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/site-uptime-check-cron.sh` | yes |
| 16 | prune-backups | `20 5 * * *` | `/home/zabz/personal-secretary-mvp/scripts/server/prune-backups.sh /home/zabz/secretary-backups …` | yes |
| 17 | run-sentinel | `*/5 * * * *` | `/home/zabz/ceo-kernel/scripts/run-sentinel.sh` | yes |
| 18 | run-ha-truth | `*/30 * * * *` | `/home/zabz/ceo-kernel/scripts/run-ha-truth.sh >/dev/null 2>&1` | yes |
| 19 | journal-commit | `*/15 * * * *` | `/home/zabz/bin/journal-commit.sh … && /home/zabz/harness-config/scripts/autosync.sh …` | yes |
| 20 | run-ha-behaviour | `20 4 * * *` | `/home/zabz/ha-config-live/scripts/run-ha-behaviour.sh >/dev/null 2>&1` | yes |
| 21 | serve-phone | `@reboot` | `/home/zabz/harness-config/scripts/serve-phone.sh >/dev/null 2>&1` | yes |
| 22 | serve-phone-2 | `*/2 * * * *` | `/home/zabz/harness-config/scripts/serve-phone.sh >/dev/null 2>&1` | yes |
| 23 | push-dsh-sessions | `*/30 * * * *` | `DSH_ARCHIVE_ENDPOINT=http://127.0.0.1:8002/… /home/zabz/node/bin/node /home/zabz/harness-config/scripts/push-dsh-sessions.mjs --transport http …` | yes |
| 24 | dialpad-harvest-cron | `*/30 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/dialpad-harvest-cron.sh` | yes |
| 25 | probe-phone | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/harness-config/scripts/probe-phone.py --quiet --json …` | yes |
| 27 | sampler | `*/15 * * * *` | `…/.venv/bin/python /home/zabz/presence-runtime/sampler.py …` | yes |
| 28 | check-phone-ui | `30 5 * * *` | `/home/zabz/harness-config/scripts/check-phone-ui.sh --quiet …` | yes |
| 29 | model-failover-watch | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/harness-config/scripts/model-failover-watch.py …` | yes |
| 31 | comms-refresh | `7,37 * * * *` | `/usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py …` | yes |
| 32 | lpt-hub-refresh | `*/15 * * * *` | `/home/zabz/harness-config/scripts/lpt-hub-refresh.sh …` | yes |
| 35 | supplier-order-ingest | `10 */6 * * *` | `…/.venv/bin/python …/scripts/supplier-order-ingest.py --apply …` | yes |
| 36 | supplier-delivery-watch | `17 */6 * * *` | `…/.venv/bin/python …/scripts/supplier-delivery-watch.py --create-tasks …` | yes |
| 38 | dialpad-recording-gap | `*/5 * * * *` | `cd /home/zabz/personal-secretary-mvp && flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json …` | yes |
| 40 | dialpad-transcript-gap | `*/10 * * * *` | `cd …/personal-secretary-mvp && flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600 …` | yes |
| 41 | backup-phoenix-evidence | `30 3 * * *` | `/home/zabz/bin/backup-phoenix-evidence.sh` | yes |
| 42 | check-phoenix-evidence | `25 * * * *` | `/usr/bin/python3 /home/zabz/bin/check-phoenix-evidence.py …` | yes |
| 45 | family_chat_watchdog | `*/30 * * * *` | `cd …/personal-secretary-mvp && flock -n /tmp/family-chat-watchdog.lock .venv/bin/python scripts/family_chat_watchdog.py …` | yes |
| 46 | box-health-check | `15 5 * * *` | `/home/zabz/bin/box-health-check.sh` | yes |
| 47 | stripe-key-watch | `17 */6 * * *` | `/usr/bin/python3 /home/zabz/bin/stripe-key-watch.py …` | yes |
| 48 | production-comms-freshness | `*/15 * * * *` | `…/.venv/bin/python3 /home/zabz/bin/production-comms-freshness.py …` | yes |
| 49 | lpt-recon-check | `23 */4 * * *` | `/home/zabz/bin/lpt-recon-check.sh …` | yes |
| 50 | website-comms-push-cron | `9,39 * * * *` | `/home/zabz/bin/website-comms-push-cron.sh` | yes |
| 51 | comms-refresh-2 | `12,42 * * * *` | `…/.venv/bin/python3 /home/zabz/.fsearch/comms-refresh.py --check --max-age-minutes 45 …` | yes |
| 52 | sync | `*/30 * * * *` | `cd $HOME/code/unified-search && python3 scripts/sync.py --db $HOME/.usearch/usearch.db …` | yes |
| 53 | audit | `*/30 * * * *` | `cd /home/zabz/repos/lpt-hub && …/.venv/bin/python3 tools/customer/audit.py --write-report …/four-surface.json …` | yes |
| 54 | check-security-absence | `*/15 * * * *` | `cd …/personal-secretary-mvp && /usr/bin/python3 scripts/ha/check-security-absence.py --url http://192.168.50.34:8123 --env-file …/.env … \|\| logger -t ha-security-absence …` | yes |
| 59 | wake-fanout | `* * * * *` | `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh …` | yes |
| 60 | sms-inbox | `*/5 * * * *` | `python3 sms-inbox.py sync --pages 3; sms-responder.py run --send --max-sends 2; sms-responder.py learn --apply; textdecide.py --refresh-catalog` | yes |
| 61 | run-wake-sources | `*/15 * * * *` | `/bin/bash /home/zabz/bin/run-wake-sources.sh …` | yes |
| 62 | dialpad-sms-harvest-cron | `15,45 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/dialpad-sms-harvest-cron.sh …` | yes |
| 63 | mesh-placement-monitor | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/bin/mesh-placement-monitor.py --quiet …` | yes |
| 65 | profile-gate | `*/15 * * * *` | `DSH_HOME=/home/zabz/.dsh /home/zabz/node/bin/node /home/zabz/code/harness-config/scripts/profile-gate.mjs …` | yes |
| 66 | converge-authority | `*/15 * * * *` | `/home/zabz/bin/converge-authority.sh` | yes |
| 71 | wake-cost | `*/15 * * * *` | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/wake-cost.py --days 1 …` | yes |
| 78 | mirror-owner-sms | `*/5 * * * *` | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/mirror-owner-sms.py --apply …` | yes |
| 84 | reconcile-sent-status | `*/10 * * * *` | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/reconcile-sent-status.py --apply --hours 48 …` | yes |
| 89 | promote-owner-texts | `*/15 * * * *` | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/promote-owner-texts.py --apply …` | yes |
| 91 | tree-integrity-check | `*/30 * * * *` | `/home/zabz/personal-secretary-mvp/scripts/tree-integrity-check.sh …` | yes |
| 93 | work-integrator | `23 * * * *` | `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/work-integrator.py --days 3 --limit 3 …` | yes |
| 94 | cron-target-guard | `7 * * * *` | `/home/zabz/bin/cron-target-guard.py --write-status …` | yes |
| 95 | disk-guard | `*/15 * * * *` | `/home/zabz/bin/disk-guard.py --write-status …` | yes |
| 97 | chip-resume | `*/15 * * * *` | `flock -n /tmp/chip-resume.lock …/.venv/bin/python /home/zabz/bin/chip-resume.py …` | yes |
| 102 | wake-balance | `41 * * * *` | `/usr/bin/python3 /home/zabz/bin/wake-balance.py --guard --warn 75 --repeat-hours 12 …` | yes |
| 108 | cfo-ask | `*/30 * * * *` | `/usr/bin/python3 /home/zabz/bin/cfo-ask.py --send …` | yes |
| 111 | cfo-scoreboard | `20 */6 * * *` | `/usr/bin/python3 /home/zabz/bin/cfo-scoreboard.py …` | yes |
| 112 | pain-check | `20 6 * * *` | `/home/zabz/bin/pain-check.py --write-status` | yes |
| 118 | deadman | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/bin/deadman.py …` | yes |
| 123 | owner-ask | `*/30 * * * *` | `/usr/bin/python3 /home/zabz/bin/owner-ask.py --send …` | yes |
| 128 | text-channel-check | `*/15 * * * *` | `/home/zabz/bin/text-channel-check.sh >/dev/null 2>&1` | yes |
| 131 | guard-registry | `*/15 * * * *` | `/home/zabz/bin/guard-registry-check.py --write-status …` | yes |
| 132 | engine-watch | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/bin/engine-watch.py …` | yes |
| 136 | tmpfs-reaper | `*/20 * * * *` | `mkdir -p /home/zabz/tmp-rescue && /home/zabz/bin/tmpfs-reaper.sh …` | yes |
| **141** | **order-feed-refresh** | `20 5 * * *` | **`/home/zabz/code/harness-config/scripts/order-feed-refresh.sh --refresh --apply >> /home/zabz/.order-feed-refresh.cron.log 2>&1`** | **NO** |
| **146** | **text-line-check** | `40 6 * * *` | **`/home/zabz/code/harness-config/scripts/text-line-check.sh >> /home/zabz/.text-line-check.log 2>&1`** | **NO** |
| 147 | ai-gateway-health | `*/30 * * * *` | `…/.venv/bin/python …/scripts/ai-gateway-health.py --days 7 …` | yes |
| 148 | push-db-offsite | `10 5 * * *` | `/home/zabz/bin/push-db-offsite.sh` | yes |
| 149 | company-offsite-push | `40 1,7,13,19 * * *` | `/home/zabz/bin/company-offsite-push.sh …` | yes |
| 150 | report-offsite-age | `*/30 * * * *` | `/home/zabz/bin/report-offsite-age.sh` | yes |
| 151 | (unwrapped) lpt-audit-weekly | `0 6 * * 1` | `/home/zabz/bin/lpt-audit-weekly.sh …` | yes |
| 152 | (unwrapped) lpt-dialpad-daily | `30 6 * * *` | `/home/zabz/bin/lpt-dialpad-daily.sh …` | yes |
| 153 | cfo-shift | `15 */2 * * *` | `/home/zabz/bin/cfo-shift-cron.sh` | yes |
| 154 | lpt-deploy-drift | `17 * * * *` | `cd …/personal-secretary-mvp && /home/zabz/bin/lpt-deploy-drift.py …` | yes |
| 155 | dialpad-call-fresh | `* * * * *` | `cd …/personal-secretary-mvp && LOG=…; { flock -n 9 \|\| … ; }` | yes |
| 156 | lpt-freshness-watchdog | `* * * * *` | `cd … && flock -n /tmp/lpt-freshness.lock /home/zabz/bin/lpt-freshness-watchdog.py …` | yes |
| 157 | lpt-retranscribe | `23 * * * *` | `cd … && flock -n /tmp/lpt-retranscribe.lock …/.venv/bin/python /home/zabz/bin/lpt-retranscribe-drip.py 20 …` | yes |
| 158 | (unwrapped) lpt-audit-freshness | `45 7 * * *` | `/home/zabz/bin/lpt-audit-freshness.py …` | yes |
| 159 | (unwrapped) lpt-dialpad-apply | `*/15 * * * *` | `/home/zabz/bin/lpt-dialpad-apply.sh …` | yes |
| 160 | store-write-check | `*/5 * * * *` | `/usr/bin/python3 …/scripts/store-write-check.py --slow-seconds 5 …` | yes |
| 161 | hours-drift | `17 */6 * * *` | `python3 /home/zabz/bin/hours-drift-check.py > /home/zabz/.hours-drift/last.txt` | yes |
| 162 | cron-script-guard | `*/5 * * * *` | `/usr/bin/python3 /home/zabz/bin/cron-script-guard.py …` | yes |
| 163 | (unwrapped) mesh-node-probe | `*/15 * * * *` | `/home/zabz/bin/mesh-node-probe.sh …` | yes |
| 165 | lpt-business-report | `35 5 * * 0` | `cd … && bash scripts/lpt-business-report.sh --months 6 …` | yes |
| 167 | lpt-report-freshness | `45 7 * * *` | `cd … && .venv/bin/python3 scripts/lpt-report-freshness.py --file …` | yes |
| 169 | lpt-daily-track | `30 23 * * *` | `cd … && .venv/bin/python3 scripts/finance/lpt-analytics.py track --out …/daily …` | yes |
| 170 | transcript-archive | `23 * * * *` | `/home/zabz/bin/transcript-archive-run.sh >/dev/null 2>>…/cron.err` | yes |
| 173 | reconcile-sms-status | `*/15 * * * *` | `…/.venv/bin/python …/scripts/reconcile-sms-status.py --limit 200 …` | yes |
| 177 | auto-categorize | `25 */6 * * *` | `…/.venv/bin/python …/scripts/auto-categorize.py --apply …` | yes |

**Forensics on the two defects** (read-only `find /home/zabz -xdev`, this run):

* `order-feed-refresh.sh` survives only in `/home/zabz/_dsh020/repo.retired-20261005T064607Z/scripts/`
  and `/home/zabz/code/_worktrees/harness-config/ws-orderfeed/scripts/`.
* `text-line-check.sh` survives only as `…/scripts/text-line-check.sh.bak-popcheck-20261002T183541Z`
  and `.bak-prodcompose-20261002T181055Z` — **deleted from the deployed tree on 2026-10-02**, crontab
  never updated. Both are, per `cron-script-guard.py`, "missing and **NOT** tracked at HEAD", so its
  self-heal (`git checkout` of a tracked file) cannot repair either. This is the *moved/deleted but
  cron not updated* class, not the stale-path class of `company-offsite-push.sh`.

### 3.2 `lpt-apps` (host `lpt-apps-01`) — 7 entries, 0 broken

Plain crontab, no wrapper. `ls -la` returned `-rwxr-xr-x` for all four unique targets
(`backup-status-check.sh` 991 B, `company-heartbeat.sh` 54,259 B, `company-offsite-status.sh`
2,935 B, `lpt-apps-backup.sh` 5,153 B).

| job | schedule | resolved command | exists |
|---|---|---|---|
| lpt-apps-backup | `35 3 * * *` | `/root/lpt-apps-backup.sh >> /var/log/lpt-apps-backup.log 2>&1` | yes |
| company-heartbeat | `*/2 * * * *` | `/root/company-heartbeat.sh >> /var/log/company-heartbeat.log 2>&1` | yes |
| backup-status-check | `15 * * * *` | `/root/backup-status-check.sh >> /var/log/lpt-backup-status.log 2>&1` | yes |
| company-offsite-status | `25 * * * *` | `/root/company-offsite-status.sh >> /var/log/company-offsite-status.log 2>&1` | yes |
| company-heartbeat (backup) | `45 * * * *` | `CHECK_BACKUP=1 /root/company-heartbeat.sh >> /var/log/company-heartbeat.log 2>&1` | yes |
| company-heartbeat (peer) | `*/15 * * * *` | `CHECK_PEER=1 PEER_HOST=87.99.141.172 /root/company-heartbeat.sh >> …` | yes |
| company-heartbeat (standby) | `*/15 * * * *` | `CHECK_STANDBY=1 STANDBY_HOST=2.31.18.142 /root/company-heartbeat.sh >> …` | yes |

### 3.3 `secratary-cloud` — 0 entries checked

`ssh secratary-cloud "crontab -l"` → `ssh: Could not resolve hostname secratary-cloud: No such host is
known.` The name is absent from `~/.ssh/config` and from `tailscale status`, and an estate-wide indexed
search for the literal string returns **NO MATCH**. The brief expected this host empty; that cannot be
confirmed — only that the *name* does not exist from this machine, so one host's schedule is unaudited.

## 4. Hazard patterns, with file:line

### H1 — multi-GB write to `/tmp`, or `mktemp /tmp` (RAM tmpfs)

In `harness-config/scripts/` — hits, none of them multi-GB:

* `scripts/autosync.sh:194-195` `mktemp -d "${TMPDIR:-/tmp}/harness-snap-XXXXXX"` and
  `mktemp "${TMPDIR:-/tmp}/harness-snap-XXXXXX.tar"` — **consequence:** unpacks a full `git archive
  HEAD` into tmpfs; measured bound **58.1 MB / 5,010 tracked files** (~120 MB peak), so not the
  multi-GB class. Cron line 19, every 15 min.
* `scripts/guards/cron-wrap.sh:48` `mktemp "${TMPDIR:-/tmp}/cron-wrap-XXXXXX"` — **consequence:** one
  temp file per run with jobs every minute (lines 59, 155, 156): the continuous tmpfs churn
  `tmpfs-reaper.sh` exists to relieve.
* `scripts/wake/install-deadman-cron.sh:3,13` (`crontab -l > /tmp/cron.before`, then copying it) and
  `scripts/wake/fanout-every-minute.sh:2-3` — **consequence:** the crontab itself is staged through
  tmpfs; if /tmp is full the file is empty/partial and `$C` is installed from it.
* `scripts/wake-dispatch.sh:49` `> /tmp/wake-prompt.txt` (fixed, non-unique name — concurrent
  dispatches overwrite each other) and `scripts/wake/deploy.sh:264` `mktemp -u` (`-u` only names the
  file; it is created later, so the name is racy).
* Smaller, same class — each fails silently rather than large: `journal-daily.sh:41`;
  `guards/health-gate.sh:38`; `mesh-hygiene.sh:418,506,521,777,816,833`;
  `mac-mini-audit.sh:58,98,146,187,239`; `branch-audit.py:94`; `verify-secret-move.py:135`;
  `wake/shift-report.py:190`; `wake/spider-save-and-prove.sh:26,35`;
  `question-card-check.py:57,253,347`; `phone-layout-check.py:257`;
  `question-card-live-probe.py:109`; `install-handy-dictation-macos.sh:133`.
  `provision-mesh-node.sh:426,464,522,523` is the correct pattern (`mktemp "$STATE_DIR/…"`).

On cron targets outside this repo (read this run):

* `/root/lpt-apps-backup.sh` (lpt-apps line 1, `35 3 * * *`) — `BK=$(mktemp -d)` with no `TMPDIR`, so
  **every** Postgres dump, the SQLite snapshot and all `/opt/*/.env` copies stage in `/tmp` before
  restic runs, and `pg_dump … -f "/tmp/${db}.dump"` runs inside the Postgres container.
  **Consequence:** the 6.6 GB-class /tmp staging is this shape, on lpt-apps. Whether lpt-apps' `/tmp` is
  tmpfs was not measured (§6).
* `/home/zabz/bin/push-db-offsite.sh` (cron line 148) — **already fixed.** `:82-85` records the
  incident (12 GB RAM-backed tmpfs; staging the ~6.6 GB gzip there died on **2026-10-09 05:10** with
  `gzip: stdout: No space left on device -> COMPRESS FAILED`) and `:48` a `timeout` leaving a 1.9 GB
  `/tmp/offsite.okuM1b.gz` on a filesystem already at 92%. It now pre-checks free space (`:93-94`) and
  stages via `mktemp "$STAGE_DIR/offsite.XXXXXX.gz"` (`:99`). **Residual:** `:177` still does
  `SNAP="$(mktemp /tmp/offsite-ledger.XXXXXX.db)"` and `:44` puts the lock at
  `/tmp/push-db-offsite.lock` — two /tmp writes remain in the one script that filled it.

### H2 — `dbstat`, or a full-table scan against a large SQLite

Measured DB sizes this run: `secretary.db` **23,138,103,296 B (21.5 GiB)**, `comms.db` 222,720,000 B,
`inbox.db` 8,126,464 B.

* `dbstat`: **zero hits** anywhere in `harness-config`.
* `scripts/owner-attention-digest.sh:133` runs an unfiltered `max(created_at)` over the whole
  `dialpad_sms_cache` table every 30 minutes (cron line 11) — **consequence:** a full scan of the comms
  table the live SMS responder is writing, plus seven more unbounded aggregates/counts at
  `:62,64,92,96,100,101,117` (`email_triage_log`, `dialpad_sms_cache`, `tasks`, `spend_requests`,
  `human_jobs`) in the same job.
* `scripts/guards/db-integrity-check.py:69` `con.execute("PRAGMA quick_check(1)")` at `17 4` —
  **consequence:** a whole-file read of a **21.5 GiB** database while `wake-fanout` fires every minute
  and `sms-inbox` every 5; `quick_check(1)` bounds the *reporting*, not the I/O. The docstring says
  "14 GB" — the real file is 54% larger than the documentation claims.
* Whole-DB read volume, not scans: `scripts/fsearch-refresh.py:88-89` copies the source DB whole into
  `out_path`; `scripts/commsindex.py:1262` plus its `rows_*` generators (`:824-1181`) iterate every comms
  table twice hourly (cron lines 31, 51); `scripts/comms-coverage.py:39` runs `COUNT(*)` per table
  against source **and** index.

### H3 — `.backup` or `VACUUM` of a large database on a machine that is not idle

* In `harness-config/scripts`: **no executed `VACUUM`.** The only occurrence is
  `scripts/guards/sources/db-integrity.py:135`, whose text *forbids* it ("Do NOT run `.recover`,
  `VACUUM`, or any write against the live file"). `scripts/install-handy-dictation-macos.sh:133` copies a
  live system DB to `/tmp` and then writes the live one; macOS-only, not cron, small.
* **On `lpt-apps` this hazard is live:** `/root/lpt-apps-backup.sh`'s `backup_sqlite()` execs
  `VACUUM INTO '/app/data/.nightly-snapshot.sqlite'` against **lakewood-rentals' live production SQLite
  inside the serving container**, daily at `03:35`. **Consequence:** a full rewrite of the DB while the
  app serves traffic, with the snapshot staged inside the app's own `/app/data` volume, and nothing
  checks that the box is idle. The comment correctly defends the choice (a plain copy of a WAL-mode DB
  is not a backup); the point is that it is unbounded in size and lands on the busiest filesystem there.

### H4 — a hardcoded script path that is not the script's own location

* `scripts/guards/api-watchdog.sh:48` `GATE="${WATCHDOG_HEALTH_GATE:-/home/zabz/bin/health-gate.sh}"` —
  repo copy is `scripts/guards/health-gate.sh`. **Consequence:** running the repo file still tests the
  *deployed* one, so a repo fix stays invisible until deployed.
* Same shape, each naming `/home/zabz/bin/…` while the repo copy is the script's own sibling:
  `scripts/website-comms-push-cron.sh:37` (`PUSH` → `scripts/website-comms-push.py`);
  `scripts/lpt-recon-check.sh:45` (`lpt-recon.py`); `scripts/wake-dispatch.sh:18` (`WAKE` →
  `scripts/wake/wake.py`); `scripts/wake/autonomy-status.sh:21-22` (`WAKE_CLI`/`WORK_CLI`);
  `scripts/wake/shift-report.py:59-60` (`QUEUE`/`SEND` → `scripts/owner-queue.py`, `scripts/textsend.py`).
* `scripts/wake/cron.txt:48` states *"`/home/zabz/bin/wake-liveness.sh` DOES NOT EXIST YET"* while
  `:75` proposes a cron line for it — **consequence:** the repo's reference crontab carries a documented
  dead line (correctly absent from the live crontab).
* Root cause worth naming: `scripts/assert-bin-matches-repo.py` is the guard for exactly this class and
  checks **only the 9 entries in `scripts/deployed/bin/MANIFEST.json`**. The ~60 scripts the live crontab
  actually calls from `/home/zabz/bin/` are in no manifest and have no drift check. Its docstring records
  the cost: "there are (at least) three different `sms-responder.py` files in circulation".

### H5 — `restic` with no `--repository`/env and no tag filter

* In `harness-config/scripts`: **zero `restic` invocations** — every repo match is prose in
  `journal/entries/` (wins `W142`, `W175`; pain `P161`, `P2820`; handoff `H308`, `H3184`, `H397`,
  `H448`; lessons `L1557`, `L1610`). Nothing in this tree can be graded against H5.
* On a cron target: `/root/lpt-apps-backup.sh` does `source /root/.restic-env` (supplying
  `RESTIC_REPOSITORY`, keys and password) and tags every run: `restic backup "$BK" --tag
  lpt-apps-nightly --tag "$STAMP"`. **Passes H5** — repository from the environment and a tag filter
  present; `restic forget`/`restic check --no-lock` use the same env file, the intended pattern.
* Repo-side caveat, not a flag issue: `journal/entries/pain/P161.md` records the `psm-backups` restic
  repository's own `config` object being served unauthenticated by the app's uploads route.

## 5. What these findings have already cost

* **The exit-127 class is recorded and unread.** `~/.cron-status/runs.tsv` holds **79,779** runs:
  `rc=0` 72,474 · `rc=1` 5,545 · `rc=3` 1,521 · `rc=2` 216 · **`rc=127` 13** · `rc=124` (timeout) 9 ·
  `rc=7` 1. So 5,781 non-zero runs, 13 of them "command not found" — and (§2.4) no code reads that file.
* **The guard that should price the class says clean.** `cron-target-guard.py --json` on `secratary-ts`,
  `2026-10-09T19:39:02Z`: `"ok": true, "checked": 94, "missing": []` while two targets were absent. Its
  docstring prices the previous occurrence: five scripts missing on 2026-09-30 for **~28 hours**,
  nothing noticing, found only by a consequence check (`comms_freshness`: "call harvest has not
  completed in 27.9h") — the same branch-switch mechanism that produced today's two.
* **The same class killed the offsite backup leg for eight hours** on 2026-10-06, per
  `cron-script-guard.py`'s header: `sh: 1: …/server/company-offsite-push.sh: not found`.
* **`/tmp` filling has killed production processes, twice, with date and errno.** `tmpfs-reaper.sh`'s
  header records the measured incident on **2026-10-02**: at **9.2 GB of 12 GB** the tmpfs user quota
  was hit while DSH's subprocess output collector spilled to `/tmp/dsh-subprocess-*`, raising `EDQUOT`
  (`errno: -122`) out of a synchronous `writeSync()` — an uncaught exception that took the engine down.
  `phone-engine.service` died that way at **01:06:21Z and 02:47:52Z**, "taking every in-flight turn with
  it". An incident, not a theory.
* **And the 6.6 GB staging did fail, dated today:** `push-db-offsite.sh:84-85` — **2026-10-09 05:10**,
  `gzip: stdout: No space left on device -> COMPRESS FAILED`. Priced, then fixed in that file.
* **The disk has filled, twice.** `disk-guard.py:6-14` records `/` at **100%** on 2026-09-27 (17 MB free)
  and **99%** on 2026-09-30 (7.6 GB free, 298 GB of backups because the retention script had been deleted
  and its caller only warned). It samples **/tmp at an 80% threshold** — the estate already treats /tmp as
  a place that fills. Now: `/` 81%, 89 G free. The mitigation is itself evidence of recurrence:
  `tmpfs-reaper.sh` (line 136, every 20 min) has fired — `~/tmp-rescue/` holds three dated rescue sets.
* **H2 — not yet observed.** Nothing found attributes a slowdown, lock timeout or missed run to
  `owner-attention-digest.sh`'s unbounded queries or to `quick_check` on the 21.5 GiB DB. **H3 —
  partially observed:** `lpt-apps-backup.sh`'s comments record two real failures it fixes (empty DB
  list from `-d $PGUSER`, 2026-08-31; the WAL plain-copy hazard that motivated `VACUUM INTO`,
  2026-09-15) but no incident is attributed to the `VACUUM` itself. **H5 — nothing to price:** no
  malformed restic invocation exists in this tree.

## 6. What I could not check, and what I deliberately did not do

1. **`secratary-cloud` was not audited.** It does not resolve from `zabz-tech`, is absent from
   `~/.ssh/config` and `tailscale status`, and an indexed estate search finds no such string. "Expected
   empty" is unconfirmed; candidate hosts seen elsewhere (`hetzner` 87.99.141.172, standby
   `2.31.18.142`) were **not** substituted without instruction.
2. **`systemd` timers and `/etc/cron.d/*` were not checked.** "Every cron entry" means the three users'
   `crontab -l`; a job can also be scheduled outside the DB this audit read.
3. **`/tmp` on `lpt-apps` was not classified** (tmpfs vs. disk) — the most important unmeasured fact
   left, since that host's backup stages every DB dump in `/tmp`.
4. **No `No space left on device` sweep over `secratary` logs/`journalctl` completed** (truncated
   response), and `company-offsite-push.sh`'s body was only grepped, not read — so whether its
   receive-side restic call is well-formed is unknown. Likewise `~/.disk-guard/status.json`,
   `~/.db-integrity/status.json` and `~/.cron-targets/status.json` were not retrieved; the guard outputs
   quoted here come from running `cron-target-guard.py` and from the guards' own logs, not those files.
5. **What consumes `~/.cron-scripts/status.json` is not established.** `guard-registry-check.py` (line
   131) is the obvious candidate but lives only in `/home/zabz/bin/` and was not read — so §2.3's "loud"
   means the guard writes an ALERT, not that a human or the ledger has seen it.
6. **`scripts/wake/` holds ~60 unscheduled one-shot patch scripts** (`fix-*.py`, `patch-*.py`,
   `file-*.py`) hardcoding `/home/zabz/bin/…`; their paths are in H4, but I did not read each to separate
   "history, already applied" from "still runnable and dangerous". The hazard grep also covered only
   literal patterns (`/tmp`, `mktemp`, `VACUUM`, `.backup`, `dbstat`, `sqlite3`, `restic`, `gzip`, `tar`,
   `zstd`, `split -b`) — a hazard expressed through a variable resolving to `/tmp` would escape it.

**Deliberately not done.** No file other than this one was created or edited; no script was run with a
writing, deploying, restarting or deleting flag (the only execution was `cron-target-guard.py --json`,
its no-write form, plus read-only inspection and a base64 decoder). No branch was switched; no `git
reset`, `git checkout .`, `git clean` or `git add -A`. Nothing was fixed — both defects are still live.
