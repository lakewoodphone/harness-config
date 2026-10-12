# 172 — CRON PORT INVENTORY: the 93 jobs the demoted office box was running

**Provenance.** Produced 2026-10-12 by a mesh child on `ZABZ-TECH` dispatched from ZABZ-YOGA, from the
**loaded** office crontab. It lived only at `/root/cron-port-inventory.md` on `secratary-cloud` until it
was copied here; it existed in no repository, which is the same hole `173` §2.8 describes. The body below
is verbatim except for this preamble and the two corrections marked in it.

**Why it exists.** `173` §2.7 replaced the office crontab with a banner and emptied it. That closed a
hazard (93 company jobs, demonstrably fired for 1 h 19 m on 11 October when a session unmasked cron by
accident) and opened a question: **which of those jobs did real work that nothing has replaced?** This
answers it job by job. Read §B before touching anything, and §C before porting anything.

**Two corrections applied after the fact, by the session that dispatched the child.**

1. The inventory's headline says every human-contact and money script is "already sitting on the cloud
   with no schedule", naming `company-offsite-push.sh` among them. **That script is NOT on the
   authority** — measured, `ls /usr/local/bin/company-offsite-push.sh` → absent, and it is scheduled
   nowhere there. The rest of the staged scripts it names were verified present-or-absent individually;
   the staged set is real, that one member of it is not.
2. Its §B ranks the office `company-offsite-push` as able to destroy the offsite copy you would restore
   from. Checked: `SRC_DIR` defaults to `/home/zabz/secretary-backups` (frozen data, so the direction is
   right) but it pushes into the **restic repo `psm-backups/company-offsite`**, a different location from
   the verified object `lpt-authority-backups/authority/secretary.db.gz`. It would pollute the restic
   lineage, not overwrite the database restore source. Ranked lower than the inventory puts it; still
   impossible now that its cron line is gone.

---
Source of truth: the **loaded** office crontab (`/tmp/cron.txt` on `secratary-ts`, 177 lines = 93 real
jobs / 76 comments / 8 blank), read 2026-10-12. Every job line was base64-decoded (the wrapper's
`# decode:` comments agree with the decode). Read-only throughout: nothing was started, unmasked,
enabled or edited on either box.

**Precedence used so a table row is never ambiguous** (the task's categories overlap, because a job
that writes the frozen office DB satisfies both `MUST-NEVER-RUN-AGAIN` and the hazard clause):
1. sends to a human, moves money, or ships/overwrites data off-box → `HAZARD-IF-UNMASKED`
2. an equivalent job runs on the authority → `PORTED`
3. reads/writes the company DB or company state that has moved to the cloud → `MUST-NEVER-RUN-AGAIN`
4. reads only, or targets a service still live on the office box / office LAN → `STILL-NEEDED-UNPORTED`
5. provably obsolete, with the missing path shown → `DEAD`

**Two facts that decide most of this table**
- `runs.tsv` (96078 rows) shows **all 93 office jobs last executed between 2026-10-11T00:00Z and
  2026-10-11T20:23:01Z**. The last second of activity is `20:23:01Z` — the exact end of the accidental
  unmask window (19:04→20:23Z). The unmask was not hypothetical: the whole crontab demonstrably fired.
- The **loaded** crontab differs from the pre-freeze `/home/zabz/cutover/crontab.before` by exactly
  **one added line**: `plaid-sync-catchup` (5,35 * * * *), which `runs.tsv` shows running twice at
  20:05Z, inside the window. A `crontab.frozen-20261012T031240Z` snapshot also exists — the office
  crontab has been written to **after** the freeze.
- Live on the office box (proof: `systemctl list-units --state=running`): `phone-gate.service`,
  `mesh-broker.service`, `actions.runner.lakewoodphone-phone-and-tech-full.secratary-lpt.service`,
  `vscode-tunnel.service`, `tailscaled.service`, `xvfb-login.service` (headed browser).
- The office app tree `/home/zabz/personal-secretary-mvp/` holds **no company DB** — only
  `budget.db`, `unused.db`, `work.db`, all stale (Sep 28–Oct 7). The company DB is
  `/home/zabz/cutover/office-frozen.db` (23.7 GB, dated Oct 11 04:27).
- **The dangerous payload is already sitting on the cloud with no schedule.** The authority's
  `/usr/local/bin/` contains ~30 of the office scripts that the 27-line crontab does *not* run —
  including every human-contact and money script: `cfo-ask.py`, `owner-ask.py`, `wake-balance.py`,
  `deadman.py`, `cfo-shift-cron.sh`, `chip-resume.py`, `sms-responder.py`, `company-offsite-push.sh`,
  `store-write-check.py`, `work-integrator.py`, `reconcile-sms-status.py`, `promote-owner-texts.py`,
  `wake-cost.py`, `auto-categorize.py`, `nightly-plaid-sync.sh`, `daily-finance-sync-cron.sh`,
  `supplier-order-ingest.py`, `supplier-delivery-watch.py`, `hours-drift-check.py`,
  `cfo-scoreboard.py`, `lpt-audit-weekly.sh`, `lpt-business-report.sh`, `lpt-report-freshness.py`.
  `/root/bin/wake-fanout.sh` — the row-1 hazard dispatcher — is staged there too. So the exposure is
  not only "the office crontab might fire": on the cloud the same behaviour is **one added cron line**
  away, with no review gating it. Prove with
  `ssh root@178.156.194.1 "ls /usr/local/bin/ | grep -E 'cfo-ask|owner-ask|wake-balance|deadman|sms-responder'"`.

---

## The table (93 rows)

| # | name | schedule | what it does in the world / script | class | evidence |
|---|---|---|---|---|---|
| 1 | heartbeat | @reboot | boot liveness marker, `~/heartbeat.sh &` | STILL-NEEDED-UNPORTED | runs.tsv `heartbeat` n=5 last 2026-10-11T02:42:11Z; office boot is still real (phone-gate). **§D** |
| 2 | mesh-health | */5 | writes office mesh health JSON, `~/mesh-health.sh` | STILL-NEEDED-UNPORTED | runs.tsv n=3007 rc=0 last 20:20:01Z while `mesh-broker.service` is active |
| 3 | db-integrity-check | 17 4 * * * | integrity check + status file, `/home/zabz/bin/db-integrity-check.py` | PORTED | auth line 21 `db-integrity-check`, but against `SECRETARY_DB=/root/authority.db` |
| 4 | nightly-plaid-sync | 30 4 * * * | pulls bank data into the company ledger | MUST-NEVER-RUN-AGAIN | writes the company ledger; ledger now `/root/authority.db`, office copy frozen |
| 5 | node-agent-cron | */30 | office mesh node agent, `personal-secretary-mvp/scripts/mesh/node-agent-cron.sh` | STILL-NEEDED-UNPORTED | `mesh-broker.service` active; script in `scripts/mesh/` (subdir not enumerated) **§D** |
| 6 | owner-attention-digest | */30 | builds the owner's attention digest → `/home/zabz/secretary-attention-digest/latest.txt` | HAZARD-IF-UNMASKED | builds an **owner-facing** digest from the frozen ledger; whether it also pushes unverified **§D** |
| 7 | git-health-check | */30 | office repo health, `.../scripts/mesh/git-health-check.sh` | STILL-NEEDED-UNPORTED | read-only; `scripts/mesh/` exists **§D** |
| 8 | monitor-hetzner-backups | 0 */6 | checks Hetzner backup freshness | PORTED | auth line 35 `monitor-hetzner-backups` |
| 9 | daily-finance-sync-cron | 0 5 * * * | daily finance sync into the company ledger | MUST-NEVER-RUN-AGAIN | writes the company ledger; moved to the cloud |
| 10 | site-uptime-check-cron | 7 * * * * | site uptime probe | PORTED | auth line 22 `site-uptime-check-cron` |
| 11 | prune-backups | 20 5 * * * | prunes `/home/zabz/secretary-backups` | PORTED | auth line 20 `prune-backups` (now `/var/lib/authority-snapshots`) |
| 12 | run-sentinel | */5 | ceo-kernel sentinel, `/home/zabz/ceo-kernel/scripts/run-sentinel.sh` | STILL-NEEDED-UNPORTED | script present (2026-09-11); read-only **§D — content unread** |
| 13 | run-ha-truth | */30 | Home Assistant truth run | STILL-NEEDED-UNPORTED | `ha-config-live/scripts/run-ha-truth.sh` present; HA is LAN-only |
| 14 | journal-commit | */15 | commits journal + harness autosync | PORTED | auth line 17 `journal-commit` |
| 15 | run-ha-behaviour | 20 4 * * * | HA behaviour harvest | STILL-NEEDED-UNPORTED | `ha-config-live/scripts/run-ha-behaviour.sh` present; LAN-only |
| 16 | serve-phone | @reboot | starts the phone surface, `harness-config/scripts/serve-phone.sh` | STILL-NEEDED-UNPORTED | `phone-gate.service` active on the office box |
| 17 | serve-phone-2 | */2 | keeps the phone surface up | STILL-NEEDED-UNPORTED | same script; n=7509, last 20:22:01Z |
| 18 | push-dsh-sessions | */30 | pushes DSH sessions to `http://127.0.0.1:8002/api/v1/owner/dsh-sessions/ingest` | STILL-NEEDED-UNPORTED | endpoint is the office box's **own** loopback API |
| 19 | dialpad-harvest-cron | */30 | harvests Dialpad calls into the DB | PORTED | auth line 28 `dialpad-harvest-cron` (`SECRETARY_DB=/root/authority.db`) |
| 20 | probe-phone | */5 | probes the office phone gate, `probe-phone.py` | STILL-NEEDED-UNPORTED | read-only probe of a live office service |
| 21 | sampler | */15 | presence sampler (owner home/office), `presence-runtime/sampler.py` | STILL-NEEDED-UNPORTED | `sampler.log` 352 KB, touched 2026-10-11; presence is office-LAN state |
| 22 | check-phone-ui | 30 5 * * * | checks the office phone UI | STILL-NEEDED-UNPORTED | `harness-config/scripts/check-phone-ui.sh` present; probes office phone-gate |
| 23 | model-failover-watch | */5 | watches model failover for the office engine | STILL-NEEDED-UNPORTED | `harness-config/scripts/model-failover-watch.py` (2026-10-08) **§D** |
| 24 | comms-refresh | 7,37 * * * * | rebuilds the comms full-text index | PORTED | auth line 43 `comms-refresh` |
| 25 | lpt-hub-refresh | */15 | refreshes the LPT hub | STILL-NEEDED-UNPORTED | script present; **authority already has `/root/.lpt-hub-refresh`** — port is a schedule, not code |
| 26 | supplier-order-ingest | 10 */6 | ingests supplier order ledger from mail, `--apply` | MUST-NEVER-RUN-AGAIN | `--apply` writes company ledger/tasks; state moved to the cloud |
| 27 | supplier-delivery-watch | 17 */6 | ages supplier orders, `--create-tasks` | MUST-NEVER-RUN-AGAIN | `--create-tasks` writes company tasks; last rc=3 |
| 28 | dialpad-recording-gap | */5 | fetches missing Dialpad recordings | PORTED | auth line 30 `dialpad-recording-gap` |
| 29 | dialpad-transcript-gap | */10 | fills missing transcripts | PORTED | auth line 31 `dialpad-transcript-gap` |
| 30 | backup-phoenix-evidence | 30 3 * * * | backs up HA/Phoenix evidence | STILL-NEEDED-UNPORTED | `bin/backup-phoenix-evidence.sh` + `ha-config-live/scripts/` present; evidence is LAN state |
| 31 | check-phoenix-evidence | 25 * * * * | checks Phoenix evidence health | STILL-NEEDED-UNPORTED | `bin/check-phoenix-evidence.py`; n=251 rc=0 |
| 32 | family_chat_watchdog | */30 | family chat drift watchdog (read-only) | PORTED | auth line 48 `family-chat-watchdog` |
| 33 | box-health-check | 15 5 * * * | office box hardware health | STILL-NEEDED-UNPORTED | checks the office box itself; last rc=1 |
| 34 | stripe-key-watch | 17 */6 | watches the Stripe key | PORTED | auth line 36 `stripe-key-watch` |
| 35 | production-comms-freshness | */15 | production comms freshness | PORTED | auth line 25 `production-comms-freshness` |
| 36 | lpt-recon-check | 23 */4 | LPT/Dialpad reconciliation | STILL-NEEDED-UNPORTED | `/opt/company/scripts/lpt-recon-check.sh` (2026-10-11) + `/root/.lpt-recon` exist on auth — **code already ported, no cron line** |
| 37 | website-comms-push-cron | 9,39 | pushes website comms | PORTED | auth line 40 `website-comms-push-cron` |
| 38 | comms-refresh-2 | 12,42 | comms index staleness check | PORTED | auth line 44 `comms-refresh-2` |
| 39 | sync | */30 | unified-search index sync into `$HOME/.usearch/usearch.db` | STILL-NEEDED-UNPORTED | **authority already has `/root/.usearch`** — no cron line |
| 40 | audit | */30 | four-surface customer audit → `~/.lpt-verify/four-surface.json` | STILL-NEEDED-UNPORTED | **authority already has `/root/.lpt-verify`** — no cron line; last rc=1 |
| 41 | check-security-absence | */15 | HA security-absence alarm vs `http://192.168.50.34:8123` (private LAN) | STILL-NEEDED-UNPORTED | URL is RFC1918 — the cloud **cannot** reach it; needs a home on the LAN |
| 42 | wake-fanout | * * * * * | dispatches up to 8 concurrent AI wake shifts | HAZARD-IF-UNMASKED | `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /home/zabz/bin/wake-fanout.sh`; n=15024. **And the dispatcher is already copied to the authority at `/root/bin/wake-fanout.sh` with no cron line** |
| 43 | sms-inbox | */5 | 4 chained commands: `sms-inbox.py sync`; **`sms-responder.py run --send --max-sends 2`**; `learn --apply`; `textdecide.py --refresh-catalog` | HAZARD-IF-UNMASKED | sends real SMS; auth line 8 ports **only** the read-only `sync` and says the other three are "deliberately NOT installed" |
| 44 | run-wake-sources | */15 | builds the wake engine's input work | HAZARD-IF-UNMASKED | feeds the spend/send engine (money); `/home/zabz/bin/run-wake-sources.sh` |
| 45 | dialpad-sms-harvest-cron | 15,45 | harvests Dialpad SMS | PORTED | auth line 29 `dialpad-sms-harvest-cron` |
| 46 | mesh-placement-monitor | */5 | mesh placement decisions monitor | STILL-NEEDED-UNPORTED | `mesh-broker.service` ("placement decisions for the DSH mesh") is active on the office |
| 47 | profile-gate | */15 | proves every DSH profile composes (office engine boot gate) | STILL-NEEDED-UNPORTED | `harness-config/scripts/profile-gate.mjs` (2026-10-08); office engine profiles |
| 48 | converge-authority | */15 | drives the box to agree with the authority | MUST-NEVER-RUN-AGAIN | its whole purpose is to converge an **authority**; last rc=3 at 20:15:01Z |
| 49 | wake-cost | */15 | measures wake spend for the daily cap guard | MUST-NEVER-RUN-AGAIN | measures the **office** wake ledger, which is frozen; the cloud guard must measure cloud spend |
| 50 | mirror-owner-sms | */5 | mirrors owner texts into the responder store, `--apply` | PORTED | auth line 10 `mirror-owner-sms` |
| 51 | reconcile-sent-status | */10 | reconciles send status with the provider, `--apply` | PORTED | auth line 12 `reconcile-sent-status` |
| 52 | promote-owner-texts | */15 | promotes owner texts to priority 1, `--apply` | MUST-NEVER-RUN-AGAIN | `--apply` writes the responder/inbox store that moved to the cloud |
| 53 | tree-integrity-check | */30 | runs the deploy gate on the office tree and alerts if broken | HAZARD-IF-UNMASKED | "and **alert**" — notifies; plus it gates the office tree |
| 54 | work-integrator | 23 * * * * | files unmerged branches as work items | MUST-NEVER-RUN-AGAIN | writes work items into company state that moved |
| 55 | cron-target-guard | 7 * * * * | verifies cron targets exist | PORTED | auth line 14 `cron-target-guard` |
| 56 | disk-guard | */15 | disk space guard | PORTED | auth line 23 `disk-guard` |
| 57 | chip-resume | */15 | scheduled return of the "Chip" agent | HAZARD-IF-UNMASKED | resumes agent work = starts spend (`bin/chip-resume.py`, `/tmp/chip-resume.lock`) |
| 58 | wake-balance | 41 * * * * | warns the owner by text at 75.00, pauses work below 10.00 | HAZARD-IF-UNMASKED | comment: "warns the owner at 75.00"; texts a human against frozen spend |
| 59 | cfo-ask | */30 | asks the owner about ONE unclear purchase, by text, `--send` | HAZARD-IF-UNMASKED | `cfo-ask.py --send`; texts the owner about **frozen** charges |
| 60 | cfo-scoreboard | 20 */6 | CFO backfill scoreboard | MUST-NEVER-RUN-AGAIN | reads/writes CFO state now in `/root/authority.db` |
| 61 | pain-check | 20 6 * * * | pain/status check, `--write-status` | MUST-NEVER-RUN-AGAIN | checks company state that moved; last rc=1 |
| 62 | deadman | */5 | pings an **external** dead-man switch, "all notification channels" | HAZARD-IF-UNMASKED | from the office it would report the *office* alive and **mask the cloud's death**; notifies humans |
| 63 | owner-ask | */30 | asks the owner ONE question, by text, `--send` | HAZARD-IF-UNMASKED | `owner-ask.py --send`; n=399, last 20:00:01Z |
| 64 | text-channel-check | */15 | runs the text-channel instruments; "raises at most ONE owner row" | HAZARD-IF-UNMASKED | raises owner rows (a human receives); last rc=1 |
| 65 | guard-registry | */15 | verifies the registered guards | PORTED | auth line 16 `guard-registry` |
| 66 | engine-watch | */5 | watches the office DSH engine | STILL-NEEDED-UNPORTED | `bin/engine-watch.py`; the office engine is its subject |
| 67 | tmpfs-reaper | */20 | reaps `/home/zabz/tmp-rescue` before tmpfs fills | PORTED | auth line 18 `tmpfs-reaper` (retargeted to `/root/tmp-rescue`) |
| 68 | order-feed-refresh | 20 5 * * * | Amazon/eBay order feed refresh, `--refresh --apply` | DEAD | last run rc=**127** (2026-10-10T05:20:02Z); no `order-feed-refresh.sh` in `/home/zabz/harness-config/scripts/` or `/home/zabz/code/harness-config/scripts/` |
| 69 | text-line-check | 40 6 * * * | the four text-line objectives, appended to a log | DEAD | last run rc=**127** (2026-10-10T06:40:01Z); only `.bak-*` copies of `text-line-check.sh` survive |
| 70 | ai-gateway-health | */30 | AI gateway health, `--days 7` | PORTED | auth line 26 `ai-gateway-health` |
| 71 | push-db-offsite | 10 5 * * * | ships the DB to the offsite store | HAZARD-IF-UNMASKED | would upload the **frozen** office DB over the live offsite snapshot |
| 72 | company-offsite-push | 40 1,7,13,19 | ships the company DB offsite 4×/day | HAZARD-IF-UNMASKED | same family; ran 19:40:01Z inside the window and saw rc=127 historically |
| 73 | report-offsite-age | */30 | reports offsite snapshot age | PORTED | auth line 19 `report-offsite-age` |
| 74 | lpt-audit-weekly.sh | 0 6 * * 1 | weekly LPT audit | MUST-NEVER-RUN-AGAIN | company audit against state that moved |
| 75 | lpt-dialpad-daily.sh | 30 6 * * * | daily Dialpad report | MUST-NEVER-RUN-AGAIN | company reporting against state that moved |
| 76 | cfo-shift | 15 */2 | the AI CFO shift loop | HAZARD-IF-UNMASKED | `cfo-shift-cron.sh` drives spend and the CFO's outbound channel |
| 77 | lpt-deploy-drift | 17 * * * * | detects deploy drift | PORTED | auth line 27 `lpt-deploy-drift` |
| 78 | dialpad-call-fresh | * * * * * | keeps recent Dialpad calls fresh, `--hours 2` | PORTED | **proof of a live authority run, not of a crontab line**: `/root/.dialpad-call-fresh.last_run` mtime 2026-10-12 02:57. Scheduler is **not** the 27-line crontab **§D** |
| 79 | lpt-freshness-watchdog | * * * * * | Dialpad freshness watchdog | PORTED | auth line 24 `lpt-freshness-watchdog` |
| 80 | lpt-retranscribe | 23 * * * * | re-transcribes Dialpad calls in a drip, 20/run | MUST-NEVER-RUN-AGAIN | writes transcripts into state that moved |
| 81 | lpt-audit-freshness.py | 45 7 * * * | LPT audit freshness | MUST-NEVER-RUN-AGAIN | company reporting against moved state |
| 82 | lpt-dialpad-apply.sh | */15 | applies Dialpad reconciliations | MUST-NEVER-RUN-AGAIN | writes company state that moved |
| 83 | store-write-check | */5 | probes the store write path, `--slow-seconds 5` | MUST-NEVER-RUN-AGAIN | probes the company store, which moved |
| 84 | hours-drift | 17 */6 | hours drift check, output to `~/.hours-drift/last.txt` | MUST-NEVER-RUN-AGAIN | computes over company data that moved; last rc=3 |
| 85 | cron-script-guard | */5 | verifies cron scripts exist | PORTED | auth line 15 `cron-script-guard` |
| 86 | mesh-node-probe.sh | */15 | probes mesh nodes | STILL-NEEDED-UNPORTED | `bin/mesh-node-probe.sh` (2026-10-08); probes the live office mesh |
| 87 | lpt-business-report | 35 5 * * 0 | weekly money & customer report for the shop | MUST-NEVER-RUN-AGAIN | company reporting against moved state |
| 88 | lpt-report-freshness | 45 7 * * * | is the weekly money/customer pipeline alive | MUST-NEVER-RUN-AGAIN | guards a report whose inputs moved |
| 89 | lpt-daily-track | 30 23 * * * | daily analytics capture into `~/.lpt-reports/daily` | MUST-NEVER-RUN-AGAIN | company series against moved state |
| 90 | transcript-archive | 23 * * * * | archives company transcripts | MUST-NEVER-RUN-AGAIN | writes company transcript state that moved |
| 91 | reconcile-sms-status | */15 | reads Twilio's verdict back into `sms_log` | MUST-NEVER-RUN-AGAIN | writes the company `sms_log` in the frozen DB. (Distinct from the ported `reconcile-sent-status`.) |
| 92 | auto-categorize | 25 */6 | runs the app's sanctioned writer, `--apply` | MUST-NEVER-RUN-AGAIN | `auto-categorize.py --apply` writes the company ledger, now `/root/authority.db` |
| 93 | plaid-sync-catchup | 5,35 * * * * | Plaid sync catch-up | MUST-NEVER-RUN-AGAIN | writes bank data into the frozen ledger; **added to the crontab inside the unmask window** (runs.tsv 20:05:01Z) |

---

**Staged-code note (applies to many rows above).** Where a row's class is `HAZARD-IF-UNMASKED` or
`MUST-NEVER-RUN-AGAIN` and its script also sits in the authority's `/usr/local/bin/`, the office line
is not the only copy: the same program is already on the live box, unscheduled. That is true of
`wake-fanout`, `cfo-ask`, `owner-ask`, `wake-balance`, `deadman`, `cfo-shift`, `chip-resume`,
`company-offsite-push`, `store-write-check`, `work-integrator`, `reconcile-sms-status`,
`promote-owner-texts`, `wake-cost`, `auto-categorize`, `nightly-plaid-sync`, `daily-finance-sync-cron`,
`supplier-order-ingest`, `supplier-delivery-watch`, `hours-drift`, `cfo-scoreboard`, `lpt-audit-weekly`,
`lpt-business-report`, `lpt-report-freshness` and `sms-responder`. Conversely `push-db-offsite.sh`,
`run-wake-sources.sh`, `lpt-retranscribe-drip.py`, `lpt-dialpad-apply.sh`, `lpt-dialpad-daily.sh`,
`lpt-audit-freshness.py`, `plaid-sync-catchup.sh` and `pain-check.py` are **not** staged, so a port of
those is a real copy. The full split was verified with `ls -d` on both boxes.

---

## §A Counts

| classification | count |
|---|---|
| `PORTED` | 27 |
| `MUST-NEVER-RUN-AGAIN` | 27 |
| `STILL-NEEDED-UNPORTED` | 24 |
| `HAZARD-IF-UNMASKED` | 13 |
| `DEAD` | 2 |
| **total** | **93** |

**Neither `PORTED` nor `DEAD`: 64** (93 − 27 − 2). The independent crude regex comparison guessed ~66
office names with no authority counterpart; 64 is consistent, and this pass resolves those 64 into
13 hazards, 27 must-never-run-again and 24 genuinely-needed.

`DEAD` = 2 is an honest **floor**, not a population: it counts only rows where `runs.tsv` recorded
`rc=127` (script not found) on the last run *and* the path is provably absent.

---

## §B The five worst rows if the office crontab is unmasked by accident

Ranked by (harm × onset speed). `* * * * *` and `*/5` rows are listed first because they act within
seconds and repeat, so there is no window in which a human notices and intervenes.

**1. `wake-fanout` — `* * * * *`, every minute.**
`* * * * * /home/zabz/bin/cron-wrap.sh wake-fanout V0FLRV9GQU5PVVRfVEFSR0VUPTUgV0FLRV9GQU5PVVRfTUFYPTg…`
→ `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh`
60 firings an hour, each keeping up to **8 concurrent autonomous AI shifts** in flight. Those shifts
spend model money and can text customers. Its guard rails (spend ceiling, one-row-per-claim lease,
backstop, pause file) sit in office state that is frozen, so the ceilings it enforces are the wrong
ceilings. *Receiver: the owner's money and, through the workers, customers on the text line.*
Lifetime `runs.tsv` count 15024; it fired ~79 times inside the 20:23 window.

**2. `sms-inbox` — `*/5`.**
`*/5 * * * * /home/zabz/bin/cron-wrap.sh sms-inbox …`
→ `sms-inbox.py sync --pages 3` **`; sms-responder.py run --send --max-sends 2`** `; sms-responder.py learn --apply ; textdecide.py --refresh-catalog`
The only office line that sends **real SMS to real people**, autonomously, up to 2 per tick (24/hour),
with the decision made by a model. The authority port is explicit that it installed *only* the
read-only `sync` and deliberately **not** the other three commands. *Receiver: customers on the LPT
number and the owner.* The office log proves it was armed every tick — `mode=SEND … decide=ok work=ok
send=ok` — and only an empty decision list (`0 to decide`) prevented a send. That is luck, not a guard.

**3. `company-offsite-push` — `40 1,7,13,19 * * *`.**
`40 1,7,13,19 * * * /home/zabz/bin/cron-wrap.sh company-offsite-push …/company-offsite-push.sh`
Ships the database to the offsite store. From the office it would push the **frozen 23.7 GB
`office-frozen.db`** over the live offsite lineage, silently replacing a good disaster-recovery
snapshot with a stale one — destroying the very copy you would restore from. *What is written: the
offsite backup set (R2).* It fired at 19:40:01Z inside the window.

**4. `deadman` — `*/5`.**
`*/5 * * * * /home/zabz/bin/cron-wrap.sh deadman …/deadman.py`
Pings an **external** dead-man switch ("Period 900s, grace 300s, all notification channels"). Pinging
from the office is worse than noise: the external switch would be told the estate is alive **even if
the cloud authority is dead**, so the one mechanism designed to report "the authority itself died"
would be actively falsified by a machine that is supposed to be off. *Receiver: the owner, via all
notification channels — with a false all-clear.* n=2394.

**5. `cfo-ask` (`*/30`) and `owner-ask` (`*/30`) — together, one hazard family.**
`*/30 * * * * … cfo-ask.py --send` and `*/30 * * * * … owner-ask.py --send`
Text the owner asking him to adjudicate **one unclear purchase** and answer **one question**, from a
**frozen ledger** — so he is re-asked about charges he already resolved on the cloud, and the
never-re-asking / max-3-a-day logic is measured against office state that stopped moving. Both fired
at 20:00:01Z. *Receiver: the owner, by SMS.* n=400 and n=399.

*Runner-up worth naming in the same breath:* `push-db-offsite` (`10 5 * * *`) is row 3's daily twin, and
`chip-resume`/`wake-balance`/`cfo-shift` are the remaining human-contact/spend rows.

---

## §C Port plan — `STILL-NEEDED-UNPORTED` only (24 rows)

Grouped into families that can be ported together. **Nothing was ported.** Credential checks are
`test -f` only; no value is printed. Split by what is actually missing: in most families the *code* is
already on the authority and only a **cron line or path** is absent.

**Credential and runtime state that already exists on the authority** (`test -f`/`ls -d`, no values
printed): `/opt/company/.env` (app credentials), `/root/.lpt-r2.env` (offsite R2), and
`/opt/company/.venv/bin/python` (the interpreter every ported line uses). So **no family below is
blocked by a missing credential.**

**Family 1 — company jobs whose code is already on the authority, awaiting only a schedule (4 rows).**
`lpt-recon-check`, `sync` (usearch), `audit` (four-surface), `lpt-hub-refresh`.
Proof: `/opt/company/scripts/lpt-recon-check.sh` (2026-10-11), `/root/.usearch`,
`/root/.lpt-verify`, `/root/.lpt-hub-refresh`, `/root/.lpt-recon` all exist. Needs: a cron line;
paths change `/home/zabz/...` → `/opt/company/...`; credential is the existing `/opt/company/.env`.
`audit`'s script lives in the office repo `/home/zabz/repos/lpt-hub`, so its path needs the most care.
**This family is the cheapest real work on the list.**

**Family 2 — office-LAN services the cloud cannot reach (6 rows).**
`check-security-absence` (`--url http://192.168.50.34:8123`), `run-ha-truth`, `run-ha-behaviour`,
`backup-phoenix-evidence`, `check-phoenix-evidence`, `sampler`.
These target **private** addresses and office presence state, so the blocker is the network, not
credentials. Note the code is already staged anyway — `/opt/company/scripts/ha/check-security-absence.py`
exists — which makes the wrong port tempting and useless. They need a **systemd timer on the office
box**; the only reason they are at risk is that `cron.service` is the thing being masked. Confirm
whether the cloud can reach the LAN over the existing tailnet before rejecting the port outright.

**Family 3 — the office phone gate / DSH phone surface (5 rows).**
`serve-phone`, `serve-phone-2`, `probe-phone`, `check-phone-ui`, `push-dsh-sessions`.
`phone-gate.service` is live on the office; `push-dsh-sessions` posts to a **loopback** endpoint
(`127.0.0.1:8002`) that only exists there. **None of these five scripts is staged on the authority**
(`serve-phone.sh`, `probe-phone.py`, `check-phone-ui.sh`, `push-dsh-sessions.mjs` all absent from
`/usr/local/bin/`), so this family is a genuine port — and a pointless one unless phone-gate moves too.
Otherwise: systemd timers on the office box.

**Family 4 — office-box and office-mesh instrumentation (9 rows).**
`heartbeat`, `box-health-check`, `engine-watch`, `model-failover-watch`, `profile-gate`,
`run-sentinel`, `mesh-health`, `mesh-node-probe.sh`, `mesh-placement-monitor`, `node-agent-cron`,
`git-health-check`.
These are *about the office box*; a cloud copy would monitor the wrong machine. Not staged on the
authority (except `git-health-check.sh`, which is present at `/opt/company/scripts/mesh/`).
Home: systemd timers on the office box. No authority credential is needed and none would help.

**What does not exist on the cloud at all:** the office LAN itself (Family 2), the office loopback
owner API on `127.0.0.1:8002` (Family 3), and the office hardware (Family 4).

**Largest unowned risk in this section:** 30 staged-but-unscheduled scripts in `/usr/local/bin/`
(Family 1 plus the hazard payload named at the top). A port plan that copies code is the wrong shape
here — the code is already copied. What is missing is a decision about which of those scripts is
*allowed* to have a clock, and that decision is currently made by whoever next edits the crontab.


---

## §D Honest uncertainty

Rows I could not fully classify, each with the one command that would settle it.

1. **`heartbeat`** (`~/heartbeat.sh`) — content unread; only 5 lifetime runs, all at boot.
   Settle: `ssh secratary-ts "cat /home/zabz/heartbeat.sh"`.
2. **`owner-attention-digest`** — classified `HAZARD-IF-UNMASKED` because it builds an owner-facing
   digest, but I did not prove it pushes. Settle:
   `ssh secratary-ts "sed -n '1,80p' /home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh"`.
3. **`run-sentinel`, `model-failover-watch`, `engine-watch`, `profile-gate`** — scripts exist and are
   recent; I inferred office-engine targets from name and location rather than reading them.
   Settle: `ssh secratary-ts "grep -nE 'http|send|sms|mail|curl|POST|DB|db' /home/zabz/bin/engine-watch.py | head -30"`.
4. **`node-agent-cron`, `git-health-check`, `check-security-absence`** — the containing subdirectories
   `personal-secretary-mvp/scripts/mesh/` and `.../scripts/ha/` were **not enumerated**, so my
   existence check is silent rather than negative for these three (unlike `order-feed-refresh` and
   `text-line-check`, whose absence and `rc=127` agree). Settle:
   `ssh secratary-ts "ls -la /home/zabz/personal-secretary-mvp/scripts/mesh/ /home/zabz/personal-secretary-mvp/scripts/ha/"`.
5. **`dialpad-call-fresh` PORTED** — based on `/root/.dialpad-call-fresh.last_run` mtime 2026-10-12
   02:57, which proves an authority run but **not** a scheduler. If that job has no timer, the
   authority's Dialpad freshness is being maintained by something outside both crontabs.
   Settle: `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 "systemctl list-timers --all; ls -la /etc/cron.d/"`.
   (This also bears on whether the authority has jobs beyond the 27 crontab lines.)
6. **`run-wake-sources`** — classified `HAZARD-IF-UNMASKED` for feeding the spend engine; it may
   instead be `MUST-NEVER-RUN-AGAIN` if it only writes company work items. Either way it must not run
   on the office box. Settle: `ssh secratary-ts "grep -nE 'INSERT|UPDATE|DELETE|send|sms' /home/zabz/bin/run-wake-sources.sh"`.
7. **`tree-integrity-check` / `text-channel-check` / `text-line-check`** — the "alert"/"owner row"
   paths decide whether these are hazards or merely stale-state jobs. `text-line-check` is already
   `DEAD` (rc=127), so only the first two matter. Settle:
   `ssh secratary-ts "grep -nE 'owner|send|sms|mail|logger|curl' /home/zabz/bin/text-channel-check.sh"`.

**Deliberately not asserted:** that the masked `cron.service` cannot fire. Masking plus an inactive
unit is not a load-bearing control — the loaded crontab plus one `systemctl unmask` reproduced exactly
this incident for 1h19m. The durable fix is to remove the lines, not to rely on the mask.
