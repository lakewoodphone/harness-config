# 137 — THE OFFICE BOX'S SYSTEMD TIMERS: PORT, ADAPT, RETIRE

**Workstream:** the systemd-timer gap in the 2026-10-11 authority cutover (one of the migration
workstreams). **Author:** Zabz, ZABZ-YOGA session. **Written:** 2026-10-11, 06:20–07:00 UTC.
**Authorities measured:** `secratary-cloud` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`
(**THE AUTHORITY**); `secratary` = `ssh secratary-ts` (frozen rollback anchor, **READ-ONLY, bounded
commands only**).

**The problem this closes.** `135-PARITY-AND-ROBUSTNESS.md` §6.4 measured that the freeze stopped the
office box's **cron** and its company writers but never touched its **systemd timers**: "`H3408`'s
'Office box `secratary-ts` confirmed frozen and not writing' is true of the *company database* and false
of the *box*." Five timers were still enabled and active, two of them firing within ten minutes of the
measurement, and one (`company-outcome-monitor`) had already run since the freeze — reporting a frozen
company as the company's outcome. This workstream implements the migration decision the 132 inventory
already took for that family.

**No office unit was stopped, disabled, masked or restarted by this workstream, and nothing on the
office box was written.** Every office command was one of: `cat`, `head`, `grep`, `ls`, `wc`, `ps`,
`df`, `findmnt`, `cut`, `systemctl show`, `systemctl is-enabled`, `systemctl is-active`,
`systemctl list-timers`, `systemctl list-unit-files`, `scp <office>:<path> <local>`. The exact commands
that WOULD retire each office unit if the box is ever used as a plain worker are in
[§6](#6-the-cold-store-retirement-list--stated-not-run).

---

## 0. Verdicts at a glance

| # | office unit | verdict implemented | where it lives now |
|---|---|---|---|
| 1 | `estate-monitor.timer` / `.service` | **PORT-ADAPT** — rewritten for the authority, same unit name, same design contract | `secratary-cloud:/etc/systemd/system/estate-monitor.{timer,service}` + `/usr/local/bin/estate-monitor.py` |
| 2 | `company-outcome-monitor.timer` / `.service` | **PORT-ADAPT** (paths translated, **plus one real defect fixed**) | `secratary-cloud:/etc/systemd/system/company-outcome-monitor.{timer,service}` + `/usr/local/bin/run-company-outcome-monitor.sh` |
| 3 | `tmp-reaper.timer` / `.service` | **RETIRE** the deleter; its *visibility* is preserved as a metric in `estate-monitor` | — (no cloud unit) |
| 4 | `fa-index.timer` / `.service` | **RETIRE** | — |
| 5 | `trunk-check.timer` / `.service` | **RETIRE** | — |
| 6 | `/home/zabz/heartbeat.sh` (`@reboot`, not a unit) | **RETIRE** — office-only orphan | — (in [§6](#6-the-cold-store-retirement-list--stated-not-run)) |

**Two ported, four retired, all six with the evidence stated below.** The retired four are not "not done
yet": three of them cannot do their job from Ashburn at all, and the fourth is an unattended `find
-delete` on the box that holds the only copy of the company. The port brief's own Definition of Done
#2 applies directly — "a job enabled with a missing dependency is worse than one that is off, because
it manufactures failures."

**Why systemd timers and not `cron-wrap.sh`.** The port brief says to use cron for ported jobs because
the estate's "did it actually run" ledger is built on it. It also says: "Anything that must survive a
reboot and is not a cron job (a service, a socket, a timer that already exists) keeps its own mechanism;
say what you chose and why." These five already exist as timer units on the office box, they were
deliberately chosen as timers (the `estate-monitor.timer` header says so: *"A timer, not cron: this box
already has ~40 cron entries competing for a starved disk, and the brief asks for a timer"*), and for a
monitor, `Persistent=true` plus journald timestamps is strictly better evidence than a `runs.tsv` row:
`systemctl list-timers` shows LAST **and** NEXT, and `journalctl -u <unit>` timestamps every run. The
run ledger is therefore journald plus the monitor's own state file, and both are quoted below.

---

## 1. What was read, and where

The unit files and the scripts behind them, read on the office box and copied to a local staging
directory for reading (one `scp`, never one ssh round trip per file):

| office path | size / mtime | read as |
|---|---|---|
| `/etc/systemd/system/estate-monitor.{timer,service}` | — | full `cat` |
| `/etc/systemd/system/trunk-check.{timer,service}` | — | full `cat` |
| `/etc/systemd/system/tmp-reaper.{timer,service}` | — | full `cat` |
| `/etc/systemd/system/fa-index.{timer,service}` | — | full `cat` |
| `/etc/systemd/system/company-outcome-monitor.{timer,service}` | — | full `cat` |
| `/home/zabz/bin/estate-monitor.py` | 56,417 B, 2026-10-07 13:38 | 1,218 lines, read in full |
| `/home/zabz/bin/run-company-outcome-monitor.sh` | 2,840 B, 2026-09-20 15:46 | full |
| `/home/zabz/bin/tmp-reaper.sh` | 4,634 B, 2026-10-05 14:57 | full |
| `/home/zabz/bin/build-indexes.sh` | 4,000 B, 2026-10-08 02:32 | full |
| `/home/zabz/bin/trunk-check.sh` | 2,836 B, 2026-10-08 00:26 | full |
| `/home/zabz/heartbeat.sh` | 99 B, 2026-06-28 02:20 | full |

Live state, `secratary-ts`, `systemctl list-timers --all --no-legend` and
`systemctl is-enabled` / `is-active`, read 06:26–06:40Z:

```
estate-monitor.timer             enabled=enabled  active=active   OnCalendar=*:0/2                       LAST 06:26:07Z
tmp-reaper.timer                 enabled=enabled  active=active   OnCalendar=*:0/15                      LAST 06:15:03Z
fa-index.timer                   enabled=enabled  active=active   OnBootSec=5min/OnUnitActiveSec=15min   LAST 06:17:02Z
trunk-check.timer                enabled=enabled  active=active   OnBootSec=3min/OnUnitActiveSec=30min   LAST 06:14:32Z
company-outcome-monitor.timer    enabled=enabled  active=active   OnCalendar=*-*-* 00/4:07:00            LAST 04:07:00Z
secretary-backup.timer           enabled=disabled active=inactive
secretary-backup.service         enabled=static   active=failed
secretary-api-watchdog.timer     enabled=disabled active=inactive
secretary-access-watchdog.timer  enabled=disabled active=inactive
mesh-broker.service              enabled=disabled active=inactive
```
`systemctl show -p FragmentPath` for all five → `/etc/systemd/system/<name>.timer`. That matters and is
carried into §6: per `135` §6.5, `systemctl mask` **fails** for a unit whose fragment is in
`/etc/systemd/system` (*"Failed to mask unit: File '…' already exists"*), which is why the retirement
list uses `disable --now`.

Office box load around every reading: **0.01–0.42** (`cut -d' ' -f1 /proc/loadavg`), i.e. well under the
brief's stop-at-8 line. No bulk operation was run on it.

---

## 2. PORTED AND PROVEN

### 2.1 `estate-monitor` — PORT-ADAPT, rewritten for the authority

**Cloud paths.** `/usr/local/bin/estate-monitor.py` (mode 755, 66,753 B);
`/etc/systemd/system/estate-monitor.service`; `/etc/systemd/system/estate-monitor.timer`;
state `/root/.estate-monitor/{state.json,monitor.log,alerts.jsonl,last-run}`.

**Timer line** (no crontab line by design — see §0):

```
[Timer]
OnCalendar=*:0/2
OnBootSec=90s
Persistent=true
AccuracySec=15s
RandomizedDelaySec=5s
Unit=estate-monitor.service
```

**`estate-monitor.service`:** `Type=oneshot`, `User=root`, `WorkingDirectory=/root`,
`ExecStart=/usr/local/bin/estate-monitor.py`, `Nice=15`, `CPUSchedulingPolicy=batch`,
`IOSchedulingClass=best-effort`, `IOSchedulingPriority=7`, `CPUWeight=20`, `IOWeight=20`,
`MemoryMax=256M`, `TimeoutStartSec=110`, `StandardOutput=journal`, `SyslogIdentifier=estate-monitor`.

**What was kept from the office file — deliberately, in full.** Its three stated rules, which are the
reason it found things nothing else found:

1. *A reading with no timestamp is not a reading.* Every metric carries the age of the value shown; age
   is seconds since the last **successful** measurement, so a metric that stops arriving keeps its last
   value and its age climbs until it goes red on its own (`max_age` per metric).
2. *An empty result is a refusal, not health.* "could not measure" is the distinct state `NODATA`, never
   `ok`, and `NODATA` never counts toward `ok`.
3. *It cannot text the owner.* No outbound message of any kind; escalation is
   `syslog(daemon.err)` + `alerts.jsonl` + an `ESCALATED` file, gated by `--no-alert`, and exactly one
   condition is allowed to escalate: **the company being unreachable from outside this box.**

Also kept: the `for_runs` confirmation counter, the hysteresis `clear` fraction, the monotone
`classify()`, the atomic state write, the "the monitor measures its own gap" metric, and the
`--json` / `--no-alert` / `--thresholds` interface.

**What changed, and why each change is a fix and not a translation.** The office collectors measure the
office box's diseases. None of them are this box's diseases. The office box's were a 2013 consumer SATA
SSD behind LUKS at 92 % full, I/O-starved three times, with sshd penalising its own tailnet and a 23 GiB
box whose backup peaked at 16.5 GiB. This box's *measured* diseases are three, and the monitor now
measures exactly those:

| new metric | the measurement that made it necessary |
|---|---|
| `api_rss_gib`, `api_peak_gib`, `api_memmax_infinite`, `api_restarts`, `swap_used_pct`, `oom_kills_24h` | the kernel's **global** OOM killer killed `company-api` at **2026-10-11 05:47:24Z**, four minutes after the cutover: `oom-kill:constraint=CONSTRAINT_NONE … task_memcg=/system.slice/company-api.service`, `Killed process 54912 (python) … anon-rss:7544976kB`. Measured now: `MemoryMax=infinity`, `MemoryPeak=6.673 GiB` on a 7.7 GiB box, `MemAvailable=4.79 GiB`, swap 41 % used with `si/so` non-zero. |
| `disk_used_pct`, `disk_free_deficit_gb`, `disk_util_pct` | one 75 GB disk holding a 23.7 GB database, measured at **94 % used / 4.4 GB free at 06:09:32Z** and **65 % / 26 GB free at 06:20:50Z** on the same machine eleven minutes apart — so the space reading must be suppressed while the offsite backup is in flight or it fires on every legitimate run. |
| `authority_db_gib`, `authority_db_growth_mb_h`, `authority_db_shrink_mb`, `authority_wal_mb` | the authority database is now the single copy of everything and **nothing measured it**. A database that gets *smaller* means the monitor is looking at a different file or the file was truncated — this estate's worst recorded failure is reading a stale copy and believing it, and this is the cheapest possible detector for its recurrence. `os.stat` only: never opened, so it takes no lock and cannot write. |
| `offsite_object_age_h`, `offsite_lastrun_age_h`, `offsite_lastrun_not_ok`, `offsite_running_stale` | `authority/secretary.db.gz` in R2 measured at `last_modified 2026-10-10T05:20:09Z`, i.e. ~25 h stale at port time because the office pusher died with the freeze. Two legs are kept separate on purpose so a healthy one cannot hide a dead one. |
| `deadman_check_lapse`, `deadman_ping_age_s`, `deadman_local_run_age_s`, `deadman_local_last_ok` | **the dead-man switch was already silent 5 h 15 min before the cutover and nothing noticed** (`135` §6.7): on a `*/5` schedule the last `deadman` run was `2026-10-10T22:45:02Z`, and the 3 h 29 min outage that followed produced no external alarm because the thing that raises it had stopped. This is the detector for the detector, from both sides — healthchecks.io's own verdict on the check (polled at most every 10 min, key read from `/root/.sms-inbox/deadman.env` and **never printed**) and the age of this box's last `authority-deadman.service` run from systemd. |
| `tmp_used_pct` | the office `tmp-reaper` exists because a 3-byte write to a `usrquota`'d `/tmp` failed with `EDQUOT` and broke things machine-wide. `/tmp` here **is** a 3.8 GB tmpfs with `usrquota` (`findmnt`), so the *visibility* is ported — and the *deleter* is not (§4). |

Dropped, each with its reason in the file's header: the `secretary-backup.service` metrics (that unit
does not exist here); the `sshd_exempt_*` and `sshd_penalty_*` metrics (the 2026-10-07
`PersSourcePenaltyExemptList` incident was an office-LAN incident — `192.168.50.0/24`, `100.64.0.0/10`
exempt ranges — and this box's sshd is on the public internet behind ufw + fail2ban with no such list);
the `dispatch_*` metrics (they read `~/.sms-inbox/wake-cron.log` and `~/.cron-status/runs.tsv`, neither
of which existed here at port time — they belong to the workstream that ports the wake fan-out, and they
should be re-added then against `/root/.cron-status/runs.tsv`); and the office `offsite_push_*` metrics
(they read `~/logs/company-offsite-push.log`, the restic "Box 2" leg).

**The outside probe is still taken from outside.** `public_health_status`, `public_health_ttfb_ms` and
`offsite_object_age_h` are read over ssh from the vault — `lpt-apps-01`, `root@2.28.33.58`, key
`/root/.ssh/id_ed25519_hetzner` — the same machine the office version used. A reporter that lives on the
thing it reports on is not a reporter. The ssh to the vault is cached for 300 s and the healthchecks.io
call for 600 s, because this box is measuredly at its CPU and I/O pressure lines and a monitor must not
become a load source; a cached run costs **0.17–3.4 s** and a cache-miss run **5.9 s**.

**Dependencies checked — every one, exists or missing:**

| dependency | state |
|---|---|
| `/usr/bin/python3` (3.14.4), stdlib only | **exists** |
| `/root/authority.db` | **exists** (23,707,291,648 B) |
| `/root/.ssh/id_ed25519_hetzner` → `root@2.28.33.58` | **exists**, vault reachable: `ssh … root@2.28.33.58 hostname` → `lpt-apps-01` |
| `/var/lib/company-offsite/authority-push.json` on the vault | **exists** (written 06:21:54Z by `authority-report-offsite-age.service`) |
| `/var/lib/company-heartbeat/state.json` on the vault | **exists** (checked_at 06:32:01Z, `http_code 200`) |
| `/root/.sms-inbox/deadman.env` (mode 600, 133 B) with `HEALTHCHECKS_API_KEY` | **exists** — value never read into any output |
| healthchecks.io reachable, check `secratary authority alive` present | **exists** — `status=up`, `timeout=900`, `grace=300`, `last_ping 2026-10-11T06:30:07Z` |
| `authority-deadman.service` | **exists** (installed 06:19Z by another workstream) |
| `/var/lib/authority-backup/running` | **exists** (a run in flight since 06:18:04Z) |
| `/var/lib/authority-backup/last-run` | **MISSING** — the first run had not finished. Reported as `NODATA`, never as `ok`; becomes a reading on the first run after it lands (§7) |
| `/root/company-reports` (for the outcome monitor, §2.2) | created by the ported wrapper |

**The evidence of the first runs.** `systemctl enable --now estate-monitor.timer`, then one deliberate
`systemctl start`, then the timer's own scheduled runs:

```
secratary-cloud# systemctl list-timers --no-pager estate-monitor.timer company-outcome-monitor.timer
NEXT                            LEFT       LAST                         PASSED      UNIT
Sun 2026-10-11 06:42:01 UTC  1min 38s  Sun 2026-10-11 06:40:02 UTC  20s ago     estate-monitor.timer           estate-monitor.service
Sun 2026-10-11 08:07:00 UTC  1h 26min  Sun 2026-10-11 06:34:35 UTC  5min ago    company-outcome-monitor.timer  company-outcome-monitor.service
```
```
secratary-cloud# journalctl -u estate-monitor.service -o short-iso --since -12min
2026-10-11T06:34:35+00:00 systemd[1]: Starting estate-monitor.service - Estate monitor: silent-failure metrics for the AUTHORITY secratary-cloud …
2026-10-11T06:34:36+00:00 estate-monitor[97251]: estate-monitor: verdict=DEGRADED ok=20 info=5 warn=2 crit=0 nodata=4 metrics=31 escalated=0 gap=25.8s dur=0.17s host=secratary-cloud
2026-10-11T06:34:43+00:00 systemd[1]: Starting estate-monitor.service - …
2026-10-11T06:34:44+00:00 estate-monitor[97492]: estate-monitor: verdict=DEGRADED ok=20 info=5 warn=2 crit=0 nodata=4 metrics=31 escalated=0 gap=7.2s dur=0.37s host=secratary-cloud
2026-10-11T06:36:02+00:00 systemd[1]: Starting estate-monitor.service - …
2026-10-11T06:36:02+00:00 estate-monitor[99664]: estate-monitor: verdict=DEGRADED ok=20 info=5 warn=2 crit=0 nodata=4 metrics=31 escalated=0 gap=78.6s dur=0.17s host=secratary-cloud
```
The 06:36:02 and 06:40:02 runs were **the timer's own schedule**, not a manual start (the manual one was
06:34:44), and `estate-monitor.service` shows `Result=success ExecMainStatus=0` each time.

**A real reading, not a claim — 31 metrics, `secratary-cloud`, 2026-10-11T06:40:03Z, from
`/root/.estate-monitor/state.json`:**

| metric | value | state |
|---|---|---|
| `disk_used_pct` | 62.75 % (25.05 GiB free) | info — suppressed, offsite backup running; the number is still recorded |
| `disk_free_deficit_gb` | 0.0 GiB (warn < 8 GiB free, crit < 4 GiB) | ok |
| `disk_util_pct` | **56.54 %** busy (io_ticks delta) | info — suppressed, backup running |
| `authority_db_gib` | 22.079 GiB (23,707,291,648 B) | info |
| `authority_db_shrink_mb` | 0.0 MB (delta 0 B) | ok |
| `authority_wal_mb` | 99.34 MB (104,161,872 B), shm 458,752 B | ok (warn 512 MB) |
| `api_rss_gib` | 3.743 GiB (`MemoryPeak` 6.673 GiB, `MemoryMax` infinity, `NRestarts` 1) | ok (warn 5.0, crit 6.0) |
| `swap_used_pct` | 40.93 % of 4 GiB | ok |
| `oom_kills_24h` | **1** | **WARN** — the 05:47:24Z kill, verbatim line carried in the note |
| `psi_io_full_avg60` | 9.21 % | ok |
| `load_per_cpu` | 1.89 (load1 3.78 on 2 vCPU) | ok |
| `dstate_count` | 0 | ok |
| `tmp_used_pct` | 0.28 % of a 3.8 GB tmpfs | ok |
| `offsite_object_age_h` | 25.332 h | ok (warn 26 h) |
| `offsite_running_stale` | 0 | ok |
| `public_health_status` | 0 (HTTP 200 from `lpt-apps-01`) | ok |
| `public_health_ttfb_ms` | **2422.4 ms** | **WARN** (warn 2000, crit 5000) |
| `deadman_check_lapse` | 0 (`status=up`) | ok |
| `deadman_ping_age_s` | 244 s | ok |
| `deadman_local_run_age_s` | 244 s | ok |
| `deadman_local_last_ok` | 0 | ok |
| `monitor_run_gap_s` | 78.6 s | ok |

Verdict `DEGRADED`, `ok=20 info=6 warn=2 crit=0 nodata=3`, run time 3.4 s.

**Two faults the office file had were found by building this, and both are fixed here.** They are the
same shape — *a baseline that resets itself, so a metric can never be computed* — and the first one is
visible in the office box's own `monitor.log`:

```
estate-monitor: … disk_util_pct=5.0 for_runs=2) age=140038s src=/proc/diskstats (io_ticks delta)
                 -- reading stopped arriving (no usable previous io_ticks sample …)
```
`age=140,038 s` = 38.9 hours of a permanently unmeasurable metric. The baseline was written **only
inside the branch that required a baseline to already exist**, so on a fresh install it was never
captured. Fixed: the baseline is now advanced unconditionally when the collector succeeds, and only the
*previous* baseline is used for the delta. Measured after the fix: `disk_util_pct = 56.54 %`. The same
defect was latent in `authority_db_growth_mb_h`, where anchoring on the previous run would have made the
interval permanently ~120 s against a 600 s minimum; it now has its own anchor that advances only when a
rate is actually emitted.

**What would notice if it fails.** (a) `systemctl list-timers` shows LAST stop advancing and NEXT pass;
(b) `journalctl -u estate-monitor.service` stops gaining runs; (c) the monitor's own
`monitor_run_gap_s` and `max_age` staleness pass turn every metric `CRIT` — *"reading stopped arriving"*
— after two missed runs, and `public_health_status` escalates to `syslog(daemon.err)` + `alerts.jsonl` +
`ESCALATED`; (d) `/root/.estate-monitor/last-run` stops advancing, which is the file an external reader
should watch. **Nothing outside this box currently reads that file** — that is the gap that remains, and
it is recorded as `pain` in the journal rather than glossed (see §7).

---

### 2.2 `company-outcome-monitor` — PORT-ADAPT, with one real defect fixed

**Cloud paths.** `/usr/local/bin/run-company-outcome-monitor.sh` (mode 755);
`/etc/systemd/system/company-outcome-monitor.{timer,service}`; reports to `/root/company-reports/`.

**Timer line** — cadence ported unchanged, with the office comment that explains it:

```
[Timer]
OnCalendar=*-*-* 00/4:07:00
OnBootSec=10min
Persistent=true
AccuracySec=1min
Unit=company-outcome-monitor.service
```

**Path translation, exactly per 133-PORT-BRIEF.md:** `APP_DIR` `/home/zabz/personal-secretary-mvp` →
`/opt/company`; `DB` `…/data/secretary.db` → **`/root/authority.db`**; `OUT_DIR` `~/company-reports` →
`/root/company-reports`; venv `…/.venv/bin/python` → `/opt/company/.venv/bin/python` (a symlink to
`/usr/bin/python3`). The service adds `Environment=HOME=/root`,
`Environment=COMPANY_OUTCOME_JOURNAL_UNIT=company-api`, `MemoryMax=1G`, `CPUQuota=50%`,
`IOSchedulingClass=idle`, `Nice=10`, `TimeoutStartSec=900`, `SyslogIdentifier=company-outcome-monitor`.

**The defect the port had to fix, because porting it unchanged would have moved a false green onto the
new authority.** `app/services/company_outcome_monitor.py` reads the *true* `database is locked` count
from `journalctl -u secretary-api` — a hardcoded literal. `secretary-api` is the **office** unit name;
on the authority the company runs as **`company-api.service`**. Measured on `secratary-cloud` before the
patch:

```
lock_contention_7d
    source=systemd journal (secretary-api) + error_log floor
    journal_command = journalctl -u secretary-api --since '7 days ago' --no-pager -o cat
    journal_provenance = `journalctl -u secretary-api …` -> 0 matching lines
    journal_events = 0
    undercount_factor = 0.0
```
while `journalctl -u company-api --since '7 days ago'` held **2,615 lines**. The section's own docstring
says the whole point of it existing *"rather than a bare number"* is that a monitor reporting a zero it
did not read is blind — and it was reporting exactly that, in the instrument built to catch it.

**The fix.** The unit is now **resolved at runtime and never assumed**: env override
(`COMPANY_OUTCOME_JOURNAL_UNIT`) → then the candidate list `("secretary-api", "company-api")` probed
with `systemctl cat` → and if none exists, the section returns `None` and is reported **UNREADABLE**,
never as zero. Where `secretary-api` genuinely is the unit (the office box) the behaviour is unchanged.
Applied by an idempotent, exact-anchor patch script, with the original preserved as
`/opt/company/app/services/company_outcome_monitor.py.before-137`:

```
secratary-cloud# python3 /root/out/migration-review/137-patch-company-outcome-monitor.py --apply
ok  JOURNAL_LOCK_COMMAND const: 1 replacement
ok  journal_lock_command(): 1 replacement
ok  _journal_lock_events() unit resolution: 1 replacement
ok  _journal_lock_events() provenance: 1 replacement
ok  lock_contention section label: 1 replacement
ok  lock_contention source + command: 1 replacement
backed up -> /opt/company/app/services/company_outcome_monitor.py.before-137
WROTE /opt/company/app/services/company_outcome_monitor.py
```
(both the patch script and a 109-line unified diff are kept at
`/root/out/migration-review/137-patch-company-outcome-monitor.{py,diff}`)
then, immediately:

```
secratary-cloud# /opt/company/.venv/bin/python3 -m py_compile app/services/company_outcome_monitor.py   → py_compile OK
secratary-cloud# python3 -c "import app.services.company_outcome_monitor as m; print(m.journal_lock_unit())"
('company-api', 'resolved by `systemctl cat company-api`')
```
and the fix is visible in the report the unit itself wrote:

```
lock_contention_7d
    source=systemd journal (company-api) + error_log floor
    journal_source = systemd journal: company-api unit
    journal_unit_provenance = resolved by `systemctl cat company-api`
    journal_command = journalctl -u company-api --since '7 days ago' --no-pager -o cat
    journal_events = 0
```
**That remaining zero is now a MEASURED zero, and worth stating as one:** `journalctl -u company-api
--since '7 days ago' | wc -l` = 2,615 lines and `… | grep -c 'database is locked'` = **0**. The
unit's journal begins `2026-10-11T00:00:22Z`, so this is a 6½-hour window, not 7 days, and it is not
comparable to the office's recorded 1,846 events in 7 days. Before the patch it was a **fabricated**
zero (the unit did not exist); now it is a real one.

**Dependencies checked — every one:**

| dependency | state |
|---|---|
| `/opt/company/app/services/company_outcome_monitor.py` | **exists** (64,426 B before patch) |
| `/opt/company/.venv/bin/python` | **exists** (`/usr/bin/python3` 3.14.4) |
| `/root/authority.db`, opened `file:…?mode=ro` (line 173) | **exists** — read-only by construction |
| `journalctl` + `company-api.service` | **exists** |
| `/root/company-reports` | created by the wrapper (`mkdir -p`) |
| the currency-ledger / `domains` paths some *other* sections want | see §7 — out of this workstream's scope |

**Evidence of the first run** — `systemctl start company-outcome-monitor.service`, 06:34:35Z:

```
secratary-cloud# systemctl show company-outcome-monitor.service -p Result -p ExecMainStatus -p MemoryPeak -p CPUUsageNSec
Result=success  ExecMainStatus=0  MemoryPeak=225603584  CPUUsageNSec=4855972000
secratary-cloud# journalctl -u company-outcome-monitor.service -o cat
verdict=CRITICAL rc=0 host=secratary-cloud db=/root/authority.db [CRITICAL  ] 69.3% of work sessions fail report=/root/company-reports/outcome-20261011T063435Z.txt
CRITICAL: company work is failing: [CRITICAL  ] 69.3% of work sessions fail
secratary-cloud# ls -la /root/company-reports/
-rw-r--r-- 1 root root 39962 Oct 11 06:34 outcome-20261011T063435Z.json
-rw-r--r-- 1 root root 27677 Oct 11 06:34 outcome-20261011T063435Z.txt
```
12.774 s wall, 4.855 s CPU, 215 MB peak — against a 23.7 GB database, and independent of the API on
purpose so a broken API cannot hide a broken company.

**A finding it produced immediately, which is not this workstream's to fix but must not be lost:** the
live authority's verdict is **CRITICAL — 69.3 % of work sessions fail (606 of 874)**, with 10 tasks
failing repeatedly that have never succeeded and 67.2 points of apparent completion that are the failure
marker quoting `[WORK_DONE]`. The office timer's own comment records the 2026-09-12..14 collapse as
3–4 % success, so this is not a quiet number. It is reported here as the monitor's first real reading;
*why* it is failing is a company workstream's question, not a timer-porting one.

**The one delete in this port.** The wrapper prunes its own reports —
`find "$OUT_DIR" -maxdepth 1 -name 'outcome-*' -type f -mtime +"$KEEP_DAYS" -print -delete` with
`KEEP_DAYS=90`. It is scoped to this script's own output directory and to files this script named
itself; no caller-supplied path, no glob outside that directory. Kept from the office version, and
logged (`pruned N report(s) older than 90d`).

**What would notice if it fails.** `systemctl list-timers` LAST stops advancing;
`journalctl -u company-outcome-monitor` stops gaining a `verdict=` line; the per-run
`outcome-<stamp>.txt` file stops appearing in `/root/company-reports`. Nothing sends a message — the
office design is that *"the exit code stays 0 so the timer unit does not go failed and get disabled —
but the journal level and the presence of a NON-OK report file is what a human or agent greps for."*
**No monitor currently reads that directory.** Filed as `pain` (§7).

---

## 3. `tmp-reaper` — RETIRE the deleter; the visibility is ported as a metric

**Verdict implemented: RETIRE.** No unit is installed on the authority.

**What its `--apply` deletes, exactly — the question the brief asks.** Read in full from
`/home/zabz/bin/tmp-reaper.sh` (4,634 B, 122 lines). `APPLY=1` is passed by the office unit, and the
only delete is `find -- "$p" -xdev -depth -delete` at line 102, where:

* `$p` comes from `find /tmp -mindepth 1 -maxdepth 1 -mmin +$((AGE*1440)) -print0` — **direct children
  of `/tmp` only**, never `/tmp` itself (`[ "$p" = "/tmp" ] && continue`, and `case "$base" in */*)
  continue` rejects anything nested);
* `-xdev` — never crosses a filesystem boundary;
* skipped entirely if any process holds the path open (`fuser -s`), if the path is not owned by the
  running uid (`stat -c %u`), or if it is a mount point (`mountpoint -q`);
* `KEEP_RE` skips X11/ICE/XIM sockets and locks, `systemd-private-*`, `ssh-*`, the Postgres socket,
  `.Xauthority`, `.font-unix`, `.test-unix`;
* the age falls from 3 days to 1 day once `/tmp` is at or above `--warn-pct 75`.

So the blast radius is small and the root is `/tmp`, not `/` and not `/var/tmp`. It is nevertheless
**not** ported, for four measured reasons:

1. **It does not exclude `*.lock`, and on this box `flock` on a `/tmp` file is the ported cron jobs'
   single-flight guard.** The inventory's own port list has `flock -n /tmp/dialpad-dl.lock`,
   `/tmp/dialpad-ts.lock`, `/tmp/family-chat-watchdog.lock`, `/tmp/lpt-freshness.lock`,
   `/tmp/lpt-retranscribe.lock`, `/tmp/chip-resume.lock` and a bare `9>/tmp/dialpad-call-fresh.lock`.
   `flock` opens the lock file without touching its mtime, so a lock file created more than 3 days ago
   is a candidate; `fuser -s` only protects it during the instant a run holds it. Deleting a lock file
   that another process holds lets the next run create a **different inode** and take a lock nobody
   else is blocked by — two concurrent harvesters, which is precisely the "two writers" condition the
   entire cutover exists to prevent. A reaper whose failure mode is *admitting a second writer against
   the company database* is not worth its benefit on the box that holds the only copy.
2. **Its rationale does not exist here in the same form.** The office script's header: a 3-byte write to
   `/tmp` failed with `EDQUOT` because `/tmp` was a **12 GB** RAM-backed tmpfs under `usrquota`. `/tmp`
   on the authority *is* a tmpfs with `usrquota` (`findmnt`: `tmpfs … nr_inodes=1048576,inode64,usrquota`)
   but it is **3.8 GB and 0.28 % used** — measured, on a box up 1 boot since 2026-10-09. The hazard is
   real in kind and absent in degree.
3. **Nothing measured `/tmp` on the authority before this port.** `tmp_used_pct` now does
   (`df -P -k /tmp`, warn 70 %, crit 90 %), at zero delete risk, on a monitor that is already running
   every 2 minutes. The estate's own rule applies: a monitor that reports absence is cheaper than a
   reaper that must be trusted.
4. **It is an unattended deleter on the authority**, and the standing rule for this business is
   *never destroy data* without an explicit per-action yes. Adding one by migration, for a hazard that
   has never been observed on this host, is the wrong direction of risk.

**What would be needed to port it safely**, if it is ever wanted back: add `*.lock` to `KEEP_RE`, run
the first N passes with `--dry-run` only (the script defaults to report-only), and point the unit's
`SuccessExitStatus=10` at the `exit 10` the script already uses for "at or above warn". Not done, because
reason 1 is a design fault in the script and not a configuration choice.

---

## 4. `fa-index` — RETIRE

**Verdict implemented: RETIRE.** No unit is installed on the authority. 132 §1b marked it PORT-ADAPT;
the evidence changed the verdict, and here is the evidence.

`/home/zabz/bin/build-indexes.sh` builds, every 15 minutes, a ctags symbol index and a path list under
`~/.faindex`, for the `fa` command's `fa symbol` / `fa files` fast paths. Every one of the things it
needs fails or is pointless on the authority:

| what it needs | measured on `secratary-cloud` |
|---|---|
| the consumer, `fa` | **MISSING** — `command -v fa` → nothing; `/usr/local/bin/fa` → "No such file or directory" (it exists on the office box at `/usr/local/bin/fa`) |
| `$H/personal-secretary-mvp/{app,scripts,tests}` | **MISSING** — `$H` is `/root` here; the app is `/opt/company` |
| `$H/harness-config/scripts`, `$H/harness-config/journal/tools`, `$H/bin` | **MISSING** — there is no harness-config checkout on this box worth the name: `/root/code/harness-config` is a 3-entry stub containing only `scripts/`, created 06:26Z, and `git -C /root/code/harness-config rev-parse` → *"not a git repository"* |
| `$H/code` — the only root that exists | **exists**, and contains that stub and nothing else |
| `universal-ctags` | **MISSING** — `command -v ctags` → nothing; step 1 of the script would therefore run `sudo apt-get install -y universal-ctags`, i.e. **install a package as root on the authority** on a 15-minute timer |
| the journal index tool, step 7 | **MISSING** — `$H/code/harness-config/journal/tools/journal.py` does not exist here |

A 15-minute timer whose every root is absent and whose consumer is not installed produces an
unfalsifiable index of nothing, and its first action would be an unrequested package install as root.
That is not a ported job; it is a manufactured failure. **It is a desk tool:** it exists to make
*interactive* search fast on the machine a human types on, and the authority is not that machine —
there is no DSH engine on it at all (`135` §2.1: `ps -eo pid,cmd | grep -iE "dsh|mesh"` → nothing). The
same reasoning is already recorded for `sync` (the unified-search job) in 132 §3: *"a desk-scoped
checkout and a per-machine index; not part of the cloud authority's job."* `fa-index` belongs in the same
bucket.

**Cost of getting this wrong** (had it been ported as written): a recursive `ctags -R` over `/opt/company`
plus a `find` over the same tree, every 15 minutes, on a 2-vCPU box measured at 26–32 % CPU-stall and
11–18 % **full** I/O-stall at rest, with `apt-get install` as root on the first run.

**If it is ever wanted here:** install `universal-ctags` and `fa` deliberately, set `H=/opt/company` (or
pass the roots as arguments), and then create the unit by hand. It is not enabled now.

---

## 5. `trunk-check` — RETIRE

**Verdict implemented: RETIRE.** No unit is installed on the authority. 132 §1b marked it PORT-ADAPT;
again the evidence changed the verdict.

`trunk-check.sh` answers a good question — P2881's, *"which machines' harness-config is on the trunk"*,
because **"a rule with no measurement is a wish"** — by ssh-ing to each machine in a hardcoded `NODES`
list and asking it for `git rev-parse --abbrev-ref HEAD`. On the authority **nothing in that list is
reachable, and the authority has no checkout of its own:**

| node in its `NODES` array | how it is addressed | measured from `secratary-cloud` |
|---|---|---|
| `secratary` | `local`, `$H/harness-config` | `$H` is `/root`; **no harness-config checkout** (`/root/code/harness-config` is a stub with no `.git`) — the script's own honest answer would be `no checkout` |
| `linux-pc` | `ssh linux-pc`, key `~/.ssh/id_ed25519_mesh` | **no DNS** — office LAN only, and `.ssh/id_ed25519_mesh` does not exist here |
| `hetzner` | `ssh root@87.99.141.172`, key `~/.ssh/id_ed25519_hetzner` | that literal IP is **not** this box (`178.156.194.1`); the local `id_ed25519_hetzner` points at the vault, and `getent hosts` for the tailnet names returns nothing (`tailscale status` → **"Logged out."**) |
| `lpt-apps-01` | `ssh root@2.28.33.58`, key `~/.ssh/id_ed25519_lpt-apps` | host **reachable** with `id_ed25519_hetzner`, but `/root/.ssh/id_ed25519_lpt-apps` does **not exist** here, and the vault has **no harness-config checkout** (`for d in /root/harness-config /root/code/harness-config /opt/harness-config /home/*/harness-config; do [ -d $d/.git ] && echo FOUND $d; done` → nothing) |

So every single row would print `UNREACHABLE` or `no checkout`, for ever. That is the exact shape the
port brief warns about — *"a job enabled with a missing dependency is worse than one that is off,
because it manufactures failures"* — and it is also `135` §6.7's "guard whose failure has never been
seen": a green-looking guard that has never actually checked anything.

**The blocker is reaching the peers, not the trunk.** Worth recording because it decides where this job
belongs: from the authority the **trunk reference itself is reachable**, measured —
`git ls-remote https://github.com/lakewoodphone/harness-config.git HEAD` → `d8ecbd148f1fc7b1bccbe9ca77a8805d33bba139`,
the same SHA `135` §4.7 recorded from the laptop. It is the *other machines* the authority cannot see.
`harness-config`'s `origin` fetch is the office bare repo (`135` §4.7), so the trunk lives on the office
box and on GitHub, and the check belongs on a machine that has a checkout **and** can reach the fleet —
a laptop, or the office box, which is already running it and which this workstream must not touch.

**What would be needed to port it:** a harness-config checkout on the authority (or a decision to check
the vault and GitHub only), a working key for the vault, and a route to the laptops — i.e. the tailnet
decision in `135` §2.1 (`install tailscale on secratary-cloud`). **After that decision, this is a
one-file port**, and the script itself needs no change beyond its `NODES` array.

---

## 6. The cold-store retirement list — stated, NOT run

If the office box is ever used as a plain worker, or if the rollback window closes and it stops being the
rollback anchor, this is exactly what has to stop on it. **None of these commands was run.** They are
listed with the exact unit names measured by `systemctl show -p FragmentPath` and
`systemctl is-enabled/is-active`, and `disable --now` is used — **not `mask`** — because
`135` §6.5 measured that `systemctl mask` **fails** for every one of these units: their fragment path is
`/etc/systemd/system/<name>.timer`, and mask writes its `/dev/null` symlink to the same path
(*"Failed to mask unit: File '…' already exists"*). `mask` works on the distro's units and silently
fails on this estate's, which in a hurry is a partial freeze that looks complete.

**6.1 The five enabled, active systemd timers** (all measured `enabled` + `active` at 06:30–06:40Z):

```bash
# run on secratary-ts ONLY if/when it stops being the rollback anchor
sudo systemctl disable --now estate-monitor.timer          estate-monitor.service
sudo systemctl disable --now tmp-reaper.timer              tmp-reaper.service
sudo systemctl disable --now fa-index.timer                fa-index.service
sudo systemctl disable --now trunk-check.timer             trunk-check.service
sudo systemctl disable --now company-outcome-monitor.timer company-outcome-monitor.service

# acceptance test for the whole freeze — the property, not the verb:
#   no process holds a write handle on the database, and no timer can start one
sudo lsof /home/zabz/personal-secretary-mvp/data/secretary.db   # must be EMPTY
```

`systemctl is-active cron` is **not** a valid acceptance test for this box and never was: it reported
`masked, inactive` while five timers kept firing and `heartbeat.sh` kept the cron cgroup alive.

**6.2 `/home/zabz/heartbeat.sh` — the orphan shell loop, and what it costs.**

```bash
# it is NOT a unit, so systemctl cannot retire it. It is an @reboot orphan from crontab line 1 of
# /home/zabz/cutover/crontab.before:  `@reboot ~/heartbeat.sh &`
sudo kill 1673                       # measured PID, 2026-10-11 06:38Z
# and, so it does not come back on the next boot, remove line 1 of the crontab (which is masked now
# anyway, so in practice the line is already inert — the process is the thing that is still running)
```

Measured cost, `secratary-ts`, `ps -o pid,etime,time,times,args -p 1673` at 06:38Z:

```
    PID     ELAPSED    TIME  TIME COMMAND
   1673    03:52:56  00:00:00     0 /bin/bash /home/zabz/heartbeat.sh
```

The script is five lines: `while true; do echo " 06/27/2026 22:20:25: Alive" > ~/heartbeat.log; sleep 60; done`.
Its **CPU cost is zero as measured** — `TIME 00:00:00` over 13,976 s of life, because the parent bash
blocks in `sleep` and the `echo` is a builtin. What it actually costs is everything except CPU:

1. **One `sleep` process spawn per minute, for ever** — 1,440 forks a day, ~10 s/day of kernel CPU at
   this estate's measured ~7 ms per trivial spawn, and 1,440 scheduler wake-ups a day that keep the box
   out of deep idle. On a laptop that would matter; on a 2013 desktop that is frozen, it is waste.
2. **1,440 writes a day to a consumer SATA SSD that is 92 % full, for a file nobody reads.** It uses
   `>` not `>>`, so `~/heartbeat.log` is **1 line, 29 bytes** — measured `wc -lc` → `1 29`. No reader
   exists: `grep -rl heartbeat /etc/systemd/system/ /home/zabz/bin/` finds the script and nothing else.
3. **It keeps `cron.service`'s cgroup non-empty, which is the reason the freeze looked complete and was
   not.** `135` §6.4 and 132 §3 both record it: `systemctl status cron` lists the live child
   `1673 /bin/bash /home/zabz/heartbeat.sh` **after** cron was masked, so a reader checking the cgroup
   sees a live process under cron and concludes cron is still doing something. It is a **freeze hazard**,
   not a service, and retiring it is worth more than the CPU it saves.
4. Its timestamp is a hardcoded literal from **2026-06-27** — the file's mtime is 2026-06-28 02:20
   (2,524 h old at the freeze) — so even its content is a lie about when it ran.

**6.3 Already stopped and left alone** (verified, not changed by this workstream):
`secretary-backup.timer` `disabled`/`inactive`, `secretary-backup.service` `failed`,
`secretary-api-watchdog.timer` `disabled`, `secretary-access-watchdog.timer` `disabled`,
`mesh-broker.service` `disabled`/`inactive`. Per 132 §4 and 132 §5, `secretary-backup.service` is the
**second writer** if anyone "fixes" it, and `mesh-broker.service` is out of the rollback set — both are
correctly inert and must stay so.

**6.4 Office-only timers that were never in scope and must not be judged by this list:**
`fwupd-refresh.timer` and `sysstat-collect.timer` are distro units (firmware and host statistics) and
are visible in the same `list-timers` output; they are the OS's, not the company's.

---

## 7. NOT PORTED, AND WHY

| item | verdict | why |
|---|---|---|
| `tmp-reaper.timer` / `.service` (`--apply`) | **RETIRED** | §3 — an unattended `find -delete` that does not exclude `*.lock`, on the box whose ported cron jobs guard themselves with `flock /tmp/<name>.lock`; its rationale is a 12 GB tmpfs that is 3.8 GB and 0.28 % used here. Its visibility is ported as `tmp_used_pct`. |
| `fa-index.timer` / `.service` | **RETIRED** | §4 — every root absent, consumer (`fa`) not installed, first action would be `apt-get install` as root on a 15-min timer, and it is a desk tool on a box with no interactive agent. |
| `trunk-check.timer` / `.service` | **RETIRED** | §5 — every node in its `NODES` array is unreachable from Ashburn and the authority has no checkout; it could only ever print `UNREACHABLE`/`no checkout`. Belongs on a machine that has the trunk and can reach the fleet. |
| `/home/zabz/heartbeat.sh` | **RETIRED** (office-side, §6.2) | a `while true; sleep 60` loop with no reader whose real harm is that it keeps the cron cgroup alive. There is no cloud equivalent and none is wanted. |
| the office `estate-monitor`'s `sshd_exempt_*` / `sshd_penalty_*` metrics | **dropped from the port** | the 2026-10-07 `PersSourcePenaltyExemptList` incident is an office-LAN incident (`192.168.50.0/24`, `100.64.0.0/10` exempt ranges); the authority's sshd is public-internet behind ufw + fail2ban with no such list. The office box keeps these readings for as long as it runs. |
| the office `estate-monitor`'s `dispatch_shift_no_work_product_24h` / `dispatch_rc_nonzero_24h` | **dropped from the port, to be re-added by the wake-fan-out workstream** | they read `~/.sms-inbox/wake-cron.log` and `~/.cron-status/runs.tsv`; neither existed on the authority at port time. They are the metrics that caught *"11 consecutive shifts that started and did nothing"* and they should come back against `/root/.cron-status/runs.tsv` once the fan-out is ported. |
| the office `estate-monitor`'s `backup_duration_s` / `backup_peak_rss_gib` / `backup_running` / `backup_memmax_infinite` | **dropped from the port** | they measure `secretary-backup.service`, which does not exist on the authority. The offsite leg is measured instead (`offsite_*`, `offsite_running_stale`). |

---

## 8. COULD NOT VERIFY

Stated plainly, because an empty result is not health.

1. **`offsite_lastrun_age_h` and `offsite_lastrun_not_ok` are `NODATA`, not `ok`.** `/var/lib/authority-backup/last-run`
   did not exist for the whole of this session: the first `authority-offsite-backup.service` run started
   **2026-10-11T06:18:04Z** and was still streaming at 06:40Z (`running` marker present, log tail
   `[2/5] company database (22609 MiB source) … page-stream | gzip -6 | multipart 64 MiB (no interim
   file)`). Those two metrics become readings on the first run after it lands. They are reported as
   `NODATA` — deliberately not as `ok` — which is why the monitor's verdict is `DEGRADED` rather than
   `ok`. **This is the correct state and not a fault**: the offsite evidence genuinely is not there yet.
2. **`authority_db_growth_mb_h` and `disk_util_pct` were unmeasurable at the moment of writing and are
   now measurable.** Their baselines were planted at 06:39Z; the growth rate needs a 600 s anchor, so its
   first value is due on the run after ~06:49Z. `disk_util_pct` did produce its first real value —
   **56.54 %** at 06:40:03Z — and both will be in `/root/.estate-monitor/state.json`. A later session
   should read them rather than trust this line.
3. **`public_health_ttfb_ms = 2422.4 ms` is a single sample, not a distribution.** It is one `curl` from
   `lpt-apps-01` at ~06:34Z against `https://api.abletelsolutions.com/health`, HTTP 200. `135` §5.1
   measured a **221 ms median** for the same URL from the laptop, so 2422 ms is either a cold
   connection, a route difference from Ashburn, or a real slow-down. I did not repeat it. It is a `WARN`,
   and the metric now takes a sample every ~5 minutes, so the trend will answer it.
4. **The healthchecks.io check's alerting path was not exercised.** I read `status=up`,
   `last_ping=2026-10-11T06:30:07Z`, `next_ping=06:45:07Z`, `timeout=900`, `grace=300` — a *healthy*
   reading. Proving the alarm arrives requires letting it lapse, which pages the owner. So
   *"a lapse is detected"* is proven by the shape of the metric and the value it reads, **not** by
   causing a lapse, and `135` §6.7's own note stands: *"the only way to prove this is meaningful is to
   let it lapse and confirm an alert arrives."*
5. **Nothing outside the authority reads the monitor's own liveness file.**
   `/root/.estate-monitor/last-run` is written every run, and `monitor_run_gap_s` + the `max_age`
   staleness pass will go `CRIT` internally after two missed runs — but if the **whole box** dies, that
   is invisible by construction. The only external check that covers it is the dead-man switch, which
   the monitor now reads from both sides. Recorded as `pain` in the journal; not fixed here.
6. **Why the company is failing (the outcome monitor's 69.3 %) is not determined by this workstream.**
   The reading is real and comes from the live authority database. Its cause is a company question.
7. **Whether any *other* unit on the authority is still measuring a frozen office path.** This workstream
   read only its own five timers plus the already-installed `authority-*` units it depends on. Sibling
   workstreams had installed `authority-offsite-backup`, `authority-deadman`,
   `authority-report-offsite-age`, `transcript-archive-pull` and `verify-offsite-object.sh` between
   05:55Z and 06:25Z; their contents were read only where my monitor consumes their output
   (`/var/lib/authority-backup/*`, `/var/lib/company-offsite/authority-push.json`). **A sweep of every
   enabled unit and cron line on the authority for `/home/zabz/` literals is still worth doing and was
   not done here.**
8. **The office box's own `estate-monitor` verdict was read, not re-run.** Its `monitor.log` tail at
   06:36Z showed `CRIT dispatch_shift_no_work_product_24h=34.0`, `CRIT offsite_push_incomplete_run=1.0`
   and `WARN offsite_verified_age_h=10.796h` — its last verdicts about a box that no longer runs the
   company. I did not execute it (read-only box) and cannot say whether its verdict would change.
9. **`/root/authority.db.new` (0 bytes, 05:41Z)** still exists. It is a cutover artefact, `135` §7 lists
   it, it is not mine to delete, and nothing reads it. Noted so the next session does not re-discover it.

---

## 9. Provenance

| claim | machine | command |
|---|---|---|
| the five timers are enabled+active | `secratary-ts` | `systemctl list-timers --all --no-legend`; `systemctl is-enabled/is-active <u>` |
| fragment paths are `/etc/systemd/system` (so `mask` fails) | `secratary-ts` | `systemctl show -p FragmentPath <u>.timer` |
| the unit files' exact contents | `secratary-ts` | `cat /etc/systemd/system/<u>.{timer,service}` |
| the scripts' exact contents | `secratary-ts` | `scp secratary-ts:/home/zabz/bin/<s>` then read locally; `wc -l` |
| heartbeat's cost and state | `secratary-ts` | `ps -o pid,etime,time,times,args -p 1673`; `wc -lc /home/zabz/heartbeat.log` |
| office load during every reading | `secratary-ts` | `cut -d" " -f1 /proc/loadavg` → 0.01–0.42 |
| `/tmp` is a 3.8 GB tmpfs with usrquota | `secratary-cloud` | `findmnt -no FSTYPE,SOURCE,OPTIONS /tmp`; `df -h /tmp` |
| the four absent `fa-index` roots and the absent `fa` | `secratary-cloud` | `command -v fa`; `ls /root/.faindex`; `ls /root/code/harness-config`; `git -C … rev-parse` |
| `trunk-check`'s nodes are unreachable | `secratary-cloud` | `getent hosts <each tailnet name>`; `ssh -o ConnectTimeout=6 <node> hostname`; `tailscale status` → *Logged out.* |
| the trunk itself IS reachable | `secratary-cloud` | `git ls-remote https://github.com/lakewoodphone/harness-config.git HEAD` → `d8ecbd148f1fc7b1bccbe9ca77a8805d33bba139` |
| the vault is reachable and holds the two files | `secratary-cloud` | `ssh -i /root/.ssh/id_ed25519_hetzner root@2.28.33.58 hostname` → `lpt-apps-01`; `cat /var/lib/company-offsite/authority-push.json` |
| the OOM kill | `secratary-cloud` | `journalctl -k --since 2026-10-11 00:00 \| grep -iE "out of memory\|oom-kill\|Killed process"` → 3 lines, one event |
| the API's memory ceiling is infinite | `secratary-cloud` | `systemctl show company-api -p MemoryCurrent -p MemoryPeak -p MemoryMax -p NRestarts` |
| the deadman's external verdict | `secratary-cloud` | `GET https://healthchecks.io/api/v3/checks/` with the key from `/root/.sms-inbox/deadman.env`; only `name/status/last_ping/next_ping/timeout/grace/n_pings` printed, **no credential, no ping URL** |
| the outcome monitor's report content | `secratary-cloud` | `grep -A9 '^lock_contention' /root/company-reports/outcome-20261011T063435Z.txt` |
| the patched module resolves the right unit | `secratary-cloud` | `python3 -c "import app.services.company_outcome_monitor as m; print(m.journal_lock_unit())"` |
| the monitor ran on its own schedule | `secratary-cloud` | `journalctl -u estate-monitor.service -o short-iso --since -12min` |
| every ported-metric value quoted in §2.1 | `secratary-cloud` | `/root/.estate-monitor/state.json` read with `python3 -c` |
| disk before/after every write | `secratary-cloud` | `df -h /` → `47G used, 26G avail, 66 %` before install and after |

**Nothing was restarted.** `company-api`, `cloudflared`, `secretary-dashboard` and `phone-redirector`
were not touched. `systemctl daemon-reload` was run twice (installing the units, and once to remove a
`secretary-api` alias symlink I created while testing whether `journalctl -u` follows systemd aliases —
it does not: `journalctl -u secretary-api` returned 0 lines with the alias in place, so the alias was
removed and the module-level fix was made instead). `df -h /` was checked around every write.

**The office box was not modified.** Every command listed above is a read. No unit was enabled, started,
unmasked, disabled, masked or restarted there, and no file on it was written.

---

## 10. Artefacts

| path | what |
|---|---|
| `harness-config/docs/mesh/137-PORT-SYSTEMD-TIMERS.md` (this file) — and **`/root/out/migration-review/137-PORT-SYSTEMD-TIMERS.md` COULD NOT BE WRITTEN** (see §11) | the report |
| `secratary-cloud:/usr/local/bin/estate-monitor.py` (755) | the new authority instrument |
| `secratary-cloud:/usr/local/bin/run-company-outcome-monitor.sh` (755) | the ported outcome wrapper |
| `secratary-cloud:/etc/systemd/system/estate-monitor.{service,timer}`, `company-outcome-monitor.{service,timer}` (644) | the units |
| `secratary-cloud:/root/.estate-monitor/` | `state.json`, `monitor.log`, `alerts.jsonl`, `last-run` |
| `secratary-cloud:/root/company-reports/` | `outcome-*.txt`, `outcome-*.json` |
| `secratary-cloud:/opt/company/app/services/company_outcome_monitor.py.before-137` | the pre-patch original |
| `secratary-cloud:/root/out/migration-review/137-patch-company-outcome-monitor.{py,diff}` | the re-runnable patch and its 109-line diff |
| `ZABZ-YOGA:C:\Users\ezabz\code\_mig137\` | the local staging copies this report was written from |

**Commit provenance, stated because it was not clean.** Six migration workstreams were committing to the
same `harness-config` working tree concurrently. This workstream staged its ten files and, before it
could commit them, another workstream's commit swept them in: this report and its nine journal entries
first landed inside **`9931edd1` ("134: port families 1/2/10/14 …")**. Nothing was lost and no history
was rewritten — but `git log -- docs/mesh/137-PORT-SYSTEMD-TIMERS.md` will show an unrelated message
first, and this note is here so the next session is not confused by it. **If several sessions share one
checkout, `git add <exact paths>` followed immediately by `git commit` is not atomic, and a concurrent
`git add -A` will take your files.**

---

## 11. BLOCKER, RAISED DURING THIS WORK: the authority stopped accepting its only SSH key

**This happened at ~06:44Z, after every install and proof above was complete and recorded, and it is
not caused by anything this workstream did.** It is written here as evidence, with the exact commands,
because it is a control-plane outage of the company and it outranks this workstream's report.

**What was observed.** The last successful command against the authority was the verification run that
produced §2.1's readings at **2026-10-11 06:40:03Z**. The next thing this session tried was
`scp … root@178.156.194.1:/root/out/migration-review/` at **~06:44Z**. Since then, every authentication
attempt with the estate's key fails:

```
ZABZ-YOGA$ ssh -o BatchMode=yes -o ConnectTimeout=15 -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 hostname
root@178.156.194.1: Permission denied (publickey).

ZABZ-YOGA$ ssh -vv … | tail
debug1: Will attempt key: C:\\Users\\ezabz\\.ssh\\id_ed25519_hetzner ED25519 SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg explicit
debug1: Offering public key: … id_ed25519_hetzner ED25519 SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg explicit
debug2: we sent a publickey packet, wait for reply
debug1: Authentications that can continue: publickey
debug1: No more authentication methods to try.
root@178.156.194.1: Permission denied (publickey).
```

**It is not a client problem and not a source-IP problem.** The office box `secratary-ts` holds the
**same keypair** — `ssh-keygen -lf /home/zabz/.ssh/id_ed25519_hetzner.pub` →
`256 SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31 (ED25519)`, the same
fingerprint — and **the same key is refused from the office box too**. It was still refused on a single
further attempt at **07:02Z, after a deliberate 15-minute quiet period with no connection attempts at
all** — which is the test that would have cleared a fail2ban ban:

```
secratary-ts$ timeout 25 ssh -i /home/zabz/.ssh/id_ed25519_hetzner -o BatchMode=yes root@178.156.194.1 hostname
root@178.156.194.1: Permission denied (publickey).
```

So `sshd` on the authority completes key exchange, accepts the user `root`, offers `publickey`, and
**rejects a key it accepted ten minutes earlier**. The three mechanisms that produce exactly that are
(a) `/root/.ssh/authorized_keys` no longer containing the key, (b) an `sshd` config change
(`AuthorizedKeysFile`, `PermitRootLogin`, `AllowUsers`, `Match`), or (c) `StrictModes` refusing the key
because the ownership or mode of `/root`, `/root/.ssh` or `authorized_keys` changed. Which of the three
it is **was not determined** — determining it requires the access that is missing.

**It is not a per-source block, and this workstream holds the cross-check that settles it.** A sibling
workstream (`docs/mesh/135-PORT-FRESHNESS.md` §9, committed 06:48Z) reports the same failure and
concludes *"This is a per-source block, not a key change, and that is measured rather than assumed"*,
naming fail2ban and `sshd`'s `MaxStartups` and asking the next session to read
`/etc/fail2ban/jail.local`. **That conclusion does not survive three of the measurements below, and the
correction matters because the two diagnoses have completely different recovery actions — a ban clears
itself in minutes, a replaced key does not clear itself at all.**

1. **The same key is refused from two independent source addresses.** The attempt above from
   `secratary-ts` left the **office** WAN. This laptop is at **home** — `tailscale status` on ZABZ-YOGA
   shows `secratary … direct 71.104.140.242` and `zabz-tech … direct 71.104.140.242`, i.e. the office
   nodes share one WAN address and this laptop is not behind it. A ban on *one source address* cannot
   refuse a key presented from a second one that had made **exactly one** connection.
2. **No connection-level block is in force.** `Test-NetConnection 178.156.194.1 -Port 22` → `True`, and
   the ssh verbose trace shows kex, `SSH2_MSG_SERVICE_ACCEPT`, `Authentications that can continue:
   publickey`, the key offered, and the refusal — all at the **userauth** layer. fail2ban's `sshd` jail
   acts with a packet DROP, which produces timeouts or `Connection closed`, never a completed handshake
   followed by a key rejection.
3. **The block is not a burst artefact of *this* session, because this session's own ssh calls
   succeeded throughout the window the sibling report says it began.** The sibling report dates the block
   to **06:34Z**. The commands behind §2.1 ran successfully at **06:34:35**, **06:36:02** and
   **06:40:03Z** from this same laptop and this same key — `systemctl list-timers`, `journalctl`, and the
   state-file read that produced the metric table. Whatever failed at 06:34Z for that workstream, it was
   not a ban on this source address, or those three would have failed too.

The sibling report's "measured rather than assumed" evidence is `135-PARITY-AND-ROBUSTNESS.md` §4.6,
which recorded `ssh-keygen -l -f /root/.ssh/authorized_keys` → one key at **~06:20Z**. That is a
*pre-block* reading: it proves what the file contained **before** the failure began, not after, so it
cannot discriminate between "the key is still there and something blocks us" and "the key was replaced".
**It is cited there as proof of the present, and it is evidence only of the past.**

**The company itself is demonstrably alive from outside the whole time**, so this is a door problem and
not a machine problem:

```
ZABZ-YOGA$ curl -s -o NUL -w "%{http_code} %{time_total}" https://api.abletelsolutions.com/health
200 2.271476
ZABZ-YOGA$ curl -s -o NUL -w "%{http_code} %{time_total}" https://ai.abletelsolutions.com/health
200 0.321461
ZABZ-YOGA$ Test-NetConnection 178.156.194.1 -Port 22 -InformationLevel Quiet
True
```

**What is proven, and what is not.** Proven: `sshd` is up and answering; the server completes the
handshake and refuses `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg` from two unrelated networks
with no packet-level block in force, for at least 25 minutes. Not proven: which of the three mechanisms
does it — `authorized_keys` replaced (most likely, given that `135` §4.6 explicitly recommends *"Add a
second key from `zabz-tech`"* and a `>` where an `>>` was meant produces exactly this), an `sshd` config
change, or `StrictModes` refusing a changed ownership or mode. **Do not assume the cause; read the file
on the first successful reconnect.** The recovery action is the same for all three and it needs
out-of-band access, so the cause does not have to be settled to fix it — but it must be read, because
"a ban that will expire" and "the only key to the company is gone" are not the same incident.

**Why it matters more than it looks.** `135` §4.6 recorded this key as a single point of failure with a
count of one: *"`secratary-cloud:/root/.ssh/authorized_keys` holds **exactly one** key,
`SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31`"*, and §4.8 recorded that the
**Hetzner API token is invalid** (`401 unauthorized`). So the two recovery paths the estate documented —
the key and the provider API — were one key and one dead token, and now the key does not work either.
Both the laptop and the office box hold the same private key, so this is not loss of the secret; it is
loss of the server's acceptance of it.

**What still holds, and was verified before the lockout.** The two ported timers are installed, enabled
and active, and both proved a real run (`systemctl list-timers` LAST/NEXT plus journald timestamps plus
`Result=success`, §2). They keep running without SSH: systemd is local to that box. The monitor reads
the vault over the *outbound* ssh key at `/root/.ssh/id_ed25519_hetzner`, which is a different
relationship and was working at 06:40Z — **whether it still works is unverified**, and it is the first
thing to check on regaining access.

**Consequences for this deliverable.**

1. **`/root/out/migration-review/137-PORT-SYSTEMD-TIMERS.md` was NOT written.** The report exists in
   `harness-config` (this file, committed) and in the local staging directory
   `C:\Users\ezabz\code\_mig137\`. Copying it to the authority is a one-line action for whoever restores
   access: `scp -i ~/.ssh/id_ed25519_hetzner docs/mesh/137-PORT-SYSTEMD-TIMERS.md root@178.156.194.1:/root/out/migration-review/`.
   The patch artefacts (`137-patch-company-outcome-monitor.{py,diff}`) **were** copied at 06:42Z, before
   the lockout, and are on the box.
2. **Nothing was retried into a loop.** fail2ban fronts that sshd (`135` §2.1: `ufw` default deny with
   one allow, `22/tcp`, "sshd is on the public internet with fail2ban in front"), and hammering a
   locked-out sshd from a fixed IP is how a second problem is created. Attempts were: 1 `scp`,
   3 retries, 1 verbose retry, 2 config-alias retries over ~20 minutes, plus one attempt from the office
   box. Each was logged above.
3. **The recovery is the owner's and it needs out-of-band access**, because both in-band paths are gone
   and the `secretary` MCP server is disconnected (`mcp-client(secretary): server is disconnected`). The
   Hetzner Cloud **web console** is the remaining route; the token in `/opt/company/.env` is invalid
   (`135` §4.8), so the console login — not the API — is what is needed. Recommended sequence, in order:
   (i) open the Hetzner console for `secratary-cloud` (project Ashburn), (ii) read
   `/etc/ssh/sshd_config.d/*.conf` and `ls -la /root /root/.ssh /root/.ssh/authorized_keys`,
   (iii) append — never replace — the `mesh-hetzner-2026-08-31` public key back into
   `authorized_keys` and `chmod 600` it with `/root/.ssh` at `700` and `/root` not group-writable,
   (iv) `sshd -t && systemctl reload ssh`, (v) immediately add the second key §4.6 asks for, (vi) re-issue
   the Hetzner API token so the next lockout has a second door.
4. **Everything this workstream changed is recoverable from this report.** The two units are plain text
   in §2, the scripts are byte-identical to the local staging directory, and the one app-level patch is
   re-runnable from `/root/out/migration-review/137-patch-company-outcome-monitor.py` (already on the
   box) or from the local copy.

**One thing the owner does not need to decide, and one thing he does.** The engineering is done and
recorded (rule 3: development decisions are mine). Two things are his, and they are the only two in this
file: **restore SSH access to the authority** (the box holding the company's only copy of everything is
currently reachable only through a web console), and **re-issue the Hetzner API token** so it is not
like this again. The outcome monitor's `CRITICAL — 69.3 % of work sessions fail` reading is a third, and
it belongs to the company workstream rather than this one.

