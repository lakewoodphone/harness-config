# 151 — VERIFYING THE CLOUD AUTHORITY END TO END

**Verifier:** mesh child session on host **`zabz-tech`** (Windows laptop), 2026-10-11 **20:36–20:47Z**.
**Scope:** verify only. Nothing was ported, restarted, enabled, disabled, masked or deleted.
`/root/authority.db` was never opened read-write and never `ls`-modified; only `stat` reads.
**Standard:** every number carries its machine and the command that produced it.

---

## 0. HEADLINE

1. The cloud authority is **up, answering and writing**: `company-api` HTTP 200 on `/health` in
   **9–10 ms**, 21 cron jobs + 7 custom timers installed, **19 of 21 cron jobs have already run**.
2. **27 of the 50 jobs in `132`'s port list, plus 2 office timers, have NO home on the cloud box.**
3. **4 ported jobs fail on every run**; **2 report green while blind**; 2 more **exit 0 while printing an error**.
4. **The office box was un-frozen and re-frozen TODAY.** `cron.service` ran the office crontab from
   **19:04:08Z to 20:23:26Z** and wrote to the anchor database. It is masked again now.
5. Disk is **NOT** the binding constraint today (20 GB free, 73%), but memory is: there was a real
   **OOM kill of `company-api` at 15:17:30Z**.

---

## 1. WHAT IS SUPPOSED TO RUN vs WHAT IS RUNNING (cloud)

`secratary-cloud`: `systemctl list-units --state=running` → 27 units, **`list-units --state=failed` → empty**.
`crontab -l | wc -l` → **31** (10 comment lines + **21 job lines**; `cron-target-guard` independently
decodes "21 wrapped line(s)"). `/root/.cron-status/runs.tsv` → **2 003 rows** since 06:32:33Z, **19 distinct
job names** — so 19 of 21 have run and **2 never have**.

| job | schedule on cloud | ran? | last run (ledger) | rc | dur | verdict |
|---|---|---|---|---|---|---|
| `sms-inbox` | `*/5` | yes | 20:35:01Z | 0 | 2 s | OK |
| `mirror-owner-sms` | `*/5` | yes | 20:35:01Z | 0 | 0 s | OK |
| `reconcile-sent-status` | `*/10` | yes | 20:30:01Z | 0 | 1 s | OK |
| `cron-target-guard` | `*/5` | yes | 20:40:02Z | 0 | 0 s | OK — decodes payloads (fixed) |
| `cron-script-guard` | `*/5` | yes | 20:35:01Z | 0 | 2 s | **GREEN WHILE BLIND** — log `watched=0 present=0 decoded=0 ok=True` |
| `guard-registry` | `*/15` | yes | 20:30:01Z | **2** | 1 s | **FAILING** — `registry does not exist: /root/bin/guards.yaml` |
| `journal-commit` | `*/15` | yes | 20:30:01Z | 0 | 2 s | rc 0, effect **not measured** (2 s vs office's slower, 28 %-failing run) |
| `tmpfs-reaper` | `*/20` | yes | 20:20:02Z | 0 | 0 s | wrong box: `132` §3 verdict was DEAD (office tmpfs only) |
| `report-offsite-age` | `*/30` | yes | 20:30:01Z | **0** | 2 s | **EXITS 0 WHILE BROKEN** — log `{"error": "no boto3: No module named 'boto3'"}` at 20:00:02Z **and 20:30:01Z**; the *systemd* copy at 20:11:40Z works |
| `prune-backups` | `45 5 * * *` | **NEVER** | — | — | — | first due 10-12; unproven |
| `db-integrity-check` | `17 4 * * 0` | **NEVER** | — | — | — | first due 10-18; changed from daily to weekly |
| `site-uptime-check-cron` | `7 * * * *` | yes | 20:07:01Z | 0 | 0 s | OK — all 4 endpoints HTTP 200 |
| `disk-guard` | `*/15` | yes | 20:30:01Z | 0 | 1 s | OK — `/` 68.6→71.9 %, `0 backup dir(s)` |
| `lpt-freshness-watchdog` | `* * * * *` | yes | 20:36:01Z | 0/1 | 0–64 s | intermittent rc 1 (2 of last 6) |
| `production-comms-freshness` | `*/15` | yes | 20:30:01Z | **1** | 2 s | **FAILING** — `dialpad_calls age=5.3h behind_local=5.25h … the 2026-09-15 failure shape` |
| `ai-gateway-health` | `*/30` | yes | 20:30:01Z | **1** | **95 s** | **FAILING** — exit 3; `catalogue-unreadable … http://127.0.0.1:8002/v1/models: timed out`; `tier-collapse` (3 tiers on one literal) |
| `lpt-deploy-drift` | `17 * * * *` | yes | 20:17:01Z | 0 | 0 s | **FALSE GREEN** — log says `fetch succeeded : False` then `VERDICT: IN SYNC`, `dirty files: 126` |
| `dialpad-harvest-cron` | `*/30` | yes | 20:30:01Z | 0 | **227 s** | OK on rc; row effect **not measured** |
| `dialpad-sms-harvest-cron` | `15,45` | yes | 20:15:02Z | 0 | 3 s | OK |
| `dialpad-recording-gap` | `*/5` | yes | 20:35:01Z | **1** | 1–4 s | **FAILING EVERY RUN** — traceback `dialpad-recording-gap.py line 199` |
| `dialpad-transcript-gap` | `*/10` | yes | 20:30:01Z | **1** | 4 s | **FAILING EVERY RUN** — SQL error joining `dialpad_call_retranscript` |

### 1b. custom systemd timers on the cloud box

| timer | schedule | last trigger | service result | verdict |
|---|---|---|---|---|
| `authority-offsite-backup` | daily 05:24 | 06:18:04Z | success | **WORKS ONCE** — `/var/lib/authority-backup/last-run` 06:49:06Z `status=ok database_verified=ok`, 6 278 791 492 gz bytes in 94 parts, `remote_last_modified 06:46:57Z` |
| `authority-data-offsite` | daily 06:36 | **never** (`LastTriggerUSec` empty) | — | **TIMER HAS NEVER FIRED**; `data-last-run` shows one *manual* success 09:44:17Z, 3 648 714 505 B archive |
| `authority-deadman` | `*/5` | 20:37:08Z | success | OK — `/root/.sms-inbox/deadman.env` present, 133 B, mode 600 |
| `authority-report-offsite-age` | `*/30` | 20:11:40Z | success | **duplicate of the crontab line** (two schedules, one job) |
| `transcript-archive-pull` | `21 * * * *` | 20:23:23Z | **failed, exit 3** | **PARTIAL** — archived `files_new: 27`, 414 MB, `ingest_rc 0`; 3 machines unpullable (`zabz-yoga`, `zabz-tech-linux`, `lakewooechsmini`: *no working (python, archive-transcripts.py) pair*); mem peak 3.3 GB, CPU 9 min 27 s |
| `estate-monitor` | `*/2` | 20:38:00Z | success | OK |
| `company-outcome-monitor` | 4-hourly | 20:07:33Z | success | OK |

Office timers **`trunk-check`** and **`fa-index`** (both PORT-ADAPT in `132` §1b) have **no cloud equivalent**.

---

## 2. THE OFFICE BOX WAS NOT FROZEN FOR 79 MINUTES TODAY

`secratary-ts`, all measured there:

- `systemctl status cron` → `Active: inactive (dead) since 2026-10-11 20:23:26 UTC; Duration: 1h 19min 18.473s`,
  `Main PID: 174334 (code=killed, signal=TERM)`, **`Memory: 3.1G (peak: 12.2G)`, `CPU: 43min 19.501s`**.
  It is `masked` *now*. So cron was **started 19:04:08Z and ran the office crontab until 20:23:26Z**.
- `/home/zabz/.cron-status/runs.tsv`: `awk '$1>="2026-10-11T05:43:36"'` → **622 rows, first 19:05:01Z,
  last 20:23:01Z, 64 distinct jobs** (413 rows in the 19Z hour, 209 in the 20Z hour).
- **The anchor database was written.** `stat` on
  `/home/zabz/personal-secretary-mvp/data/secretary.db`: mtime **20:20:03Z**, size
  **23 691 915 264 B** — up from the brief's 23 622 823 936 B at cutover, i.e. **+69 091 328 B after the
  freeze**. WAL present at 20:23:29Z, absent again by 20:37:47Z (checkpointed). The genuine frozen copy
  survives intact at `/home/zabz/cutover/office-frozen.db` (23 622 823 936 B).
- The re-freeze is in the journal: `sudo … COMMAND=/usr/bin/systemctl stop cron cron.socket`,
  `disable cron`, `mask cron.service cron.socket` at **20:23:26–27Z**, alongside `stop secretary-dashboard`,
  `stop phone-engine`, `disable secretary-api`, `disable company-api`, `disable presence-sampler`.
- Concurrent-writer evidence in that window: `sampler.py: presence sampler: db write failed:
  OperationalError('database is locked')` at 19:31:36Z.
- **Not established:** which actor started cron at 19:04:08Z. `132`'s claim "office cron masked since
  04:01:34Z" was true at 06:20Z and false by 19:04Z.
- Office commands used were `stat`/`cut`/`awk`/`ps`/`systemctl` over a 4 MB text file only; load stayed
  **0.06–0.81**, no DB query, no `du`, no rsync.

---

## 3. SPEED AND LOAD (cloud, `secratary-cloud`, 20:39–20:41Z)

| reading | value | command |
|---|---|---|
| CPU | 2 vCPU | `nproc` |
| load (1/5/15) | **1.46 / 1.60 / 1.20**; 3 samples 5 s apart: 1.46, 1.34, 1.23 | `cat /proc/loadavg` |
| CPU split | us 23–37 %, sy 5–18 %, **id 45–99 %**, wa 1–4 % | `vmstat 1 5` |
| memory | 7 742 MB total, **3 085 used**, 2 318 free, 2 650 buff/cache, **4 656 available** | `free -m` |
| **swap** | **1 966 of 4 095 MB in use (48 %)**, si/so non-zero | `free -m`, `vmstat` |
| disk | 75 G, **53 G used, 20 G avail, 73 %** | `df -h /` |
| big trees | `/root` 25.7 GB, `/opt/company` 18.6 GB (data 12.7, archive 4.1), `.venv` 1.4 GB | `du -x -m --max-depth=2` |
| API latency | `/health` 200 in **0.0090–0.0103 s**; `/docs` 200 in 0.0016 s | `curl -w '%{time_total}'` |
| **OOM** | **1 real kill in 12 h**: 15:17:30Z `Out of memory: Killed process 1069 (python)` `task_memcg=/system.slice/company-api.service`, `total-vm:16 461 904 kB anon-rss:7 457 924 kB` | `journalctl -k`, `grep -i 'oom\|killed process'` |

**Is 2 vCPU / 7.7 GB adequate? By the numbers: yes for the load that is running, with no headroom.**
The box idles at load 1.2–1.6 on 2 cores (~65 % of capacity), 45–99 % CPU idle depending on the tick,
and has already been pushed into a **global OOM kill of `company-api` at 15:17:30Z** with a 16 GB virtual /
7.1 GB resident python process on a 7.7 GB machine; 48 % of swap is in use. Memory, not CPU and not disk,
is the binding constraint.

Also live in the API journal: `2026-10-11T20:38:53Z WARNING app.assistant_chat: run_assistant_chat blocked
by budget: Budget exceeded for orchestrator: ceo_reserve_exhausted ($5.0064 / $5.00)`.

Log scan: `journalctl -u company-api --since '-3 hours' | grep -icE 'slow|timeout|locked|SIGBUS'` → **180**,
but the sample is dominated by benign matches (`launch_timeout`, `Lifecycle sweep`); the only genuine
slow-path evidence is the 95 s `ai-gateway-health` run and the `/v1/models` `TimeoutError`.

---

## 4. THE FOUR SERVICES THAT MUST NOT BE RESTARTED — NOTHING WAS RESTARTED

`systemctl show <u> -p ActiveState -p ActiveEnterTimestamp -p NRestarts`:

| service | state | up since | NRestarts | health |
|---|---|---|---|---|
| `company-api` | active/running | **15:17:41Z** (5 h 23 m) | **1** | healthy now (200 in 9 ms); the single restart is the **15:17:30Z OOM kill**, not a choice |
| `cloudflared` | active/running | **08:25:04Z** (12 h 15 m) | 0 | healthy — tunnel endpoint 200 in `site-uptime-check` |
| `secretary-dashboard` | active/running | **08:25:04Z** (12 h 15 m) | 0 | healthy (no failed units) |
| `phone-redirector` | active/running | **15:53:55Z** (4 h 46 m) | 0 | healthy; `phone-gate` 15:53:33Z, `phone-engine` **20:16:54Z** |

Box uptime 12 h 11 m at 20:36Z (booted 08:25Z). None of the four was restarted by this verification.
`cloudflared` and `secretary-dashboard` have not restarted since boot; `company-api` and
`phone-redirector` restarted before this window (15:17 / 15:53).

---

## 5. WHAT RAN ON THE OFFICE BOX AND HAS NO HOME ON THE CLOUD BOX

**27 ported jobs are absent from the cloud crontab and from every cloud timer** (checked against
`crontab -l` on `secratary-cloud` and `/etc/systemd/system/*.timer`):

`comms-refresh` (PORT-AS-IS) · `lpt-hub-refresh` (PORT-AS-IS — script `/usr/local/bin/lpt-hub-refresh.sh`
**is present but unscheduled**) · `wake-fanout` · `run-wake-sources` · `wake-cost` · `wake-balance` ·
`owner-ask` · `dialpad-call-fresh` · `reconcile-sms-status` · `comms-refresh-2` · `family_chat_watchdog` ·
`supplier-order-ingest` · `auto-categorize` · `lpt-daily-track` · `lpt-business-report` ·
`lpt-report-freshness` · `monitor-hetzner-backups` · `tree-integrity-check` · `work-integrator` ·
`chip-resume` · `run-sentinel` · `model-failover-watch` · `stripe-key-watch` · `node-agent-cron` ·
`push-dsh-sessions` · `lpt-retranscribe` · `website-comms-push-cron`
**plus office timers `trunk-check` and `fa-index`.**

Named gaps from the brief, item by item:

- **Freshness monitors** — partly there (`production-comms-freshness`, `ai-gateway-health`,
  `site-uptime-check-cron`, `lpt-freshness-watchdog`, `disk-guard`). **Missing:** `lpt-report-freshness`,
  `monitor-hetzner-backups`, `comms-refresh-2`. **Consequence, measured:** `production-comms-freshness`
  reports the website **5.25 h behind** the local store, and the job that would close that gap —
  `website-comms-push-cron` — is one of the 27 missing.
- **Offsite backup** — has a home and **worked once** (§1b); next automatic run 10-12 05:24Z. The
  non-database half (`authority-data-offsite`) **has never been fired by its timer**.
- **Dead-man switch** — has a home, is firing every 5 minutes, `Result=success`.
- **Transcript archive** — moved to `/opt/company/archive/lpt-transcripts`, timer firing hourly, currently
  **exit 3**: 3 of the fleet's machines cannot be pulled.
- **Homeless writers** — `/root/.fsearch` **does not exist** (`comms-refresh`/`comms-refresh-2` have no
  index to refresh); `/root/.lpt-reports/tracking.db` **absent**; `/root/.owner-ask/asks.db` **present but
  nothing schedules `owner-ask`**; `family_chat.db` **is present and being written** (mtime 20:39:42Z) while
  its watchdog is unscheduled; `/root/accounting-data/live/accounting.db` **present** (21 995 520 B) so the
  CFO jobs' blocker is gone but none of `cfo-shift`, `cfo-scoreboard`, `cfo-ask`, `auto-categorize` is
  scheduled; `/root/lpt-transcripts` absent (superseded by the archive path above).
- Not measured / not proven: the **database effect** of any job. I did not run a `mode=ro` query against
  `/root/authority.db`, so for `dialpad-harvest-cron`, `dialpad-sms-harvest-cron`, `reconcile-sent-status`,
  `journal-commit` and `sms-inbox` I can report the exit code and the log, **not** that rows advanced.

---

## 6. COULD NOT ESTABLISH

1. **Who started `cron.service` on the office box at 19:04:08Z.** The re-freeze at 20:23:26Z is fully
   logged; the start is not in the slice of journal I read (bounded `tail -30`).
2. **Whether the office crontab also ran between 06:20Z and 19:04Z.** The cloud-side and office-side
   evidence both start at 19:05:01Z; before that the office ledger has no post-05:43 rows.
3. **The database effect of every cloud job** (see §5, last bullet) — deliberately not measured rather than
   guessed.
4. **`prune-backups` and `db-integrity-check`** have never run on the cloud box, so their correctness is
   unproven, not merely untested.
5. Whether the two *new* cloud defects (`dialpad-recording-gap`, `dialpad-transcript-gap` tracebacks) are
   data-shape problems or missing dependencies: I read the stderr, not the source.
