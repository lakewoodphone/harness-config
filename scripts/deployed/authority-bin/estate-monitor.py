#!/usr/bin/env python3
# estate-monitor.py -- the silent-failure monitor for the AUTHORITY (secratary-cloud).
# ===========================================================================
# PORTED 2026-10-11 by workstream 137 from the office box's
# /home/zabz/bin/estate-monitor.py (56,417 B, mtime 2026-10-07 13:38) — the
# estate's instrument for silent failure. It was watching the wrong machine:
# after the 05:43:36Z cutover it kept measuring the FROZEN office box
# (`secratary`) while the company ran here.
#
# The office file's three design rules are kept EXACTLY, because they are the
# reason it found things nothing else found:
#   1. A READING WITH NO TIMESTAMP IS NOT A READING. Every metric carries the
#      age of the value shown; age is seconds since the last SUCCESSFUL
#      measurement, so a number that stops arriving keeps its last value and its
#      age climbs until it goes red on its own (max_age per metric).
#   2. AN EMPTY RESULT IS A REFUSAL, NOT HEALTH. "could not measure" is the
#      distinct state NODATA, never `ok`.
#   3. IT CANNOT TEXT THE OWNER. Nothing here opens a socket to a person. The
#      only escalation is syslog(daemon.err) + alerts.jsonl + an ESCALATED flag
#      file, and exactly ONE condition is allowed to escalate: the company
#      being unreachable from OUTSIDE this box. Everything else is log-only.
#
# WHAT CHANGED, AND WHY EACH CHANGE IS A FIX AND NOT A TRANSLATION
# ---------------------------------------------------------------
# The office collectors measured the office box's disease (a 2013 SATA SSD
# behind LUKS at 92 % full, I/O-starved three times, sshd penalising its own
# tailnet, a 23 GiB box with a backup that peaked at 16.5 GiB). None of those
# are this box's diseases. This box's measured diseases are:
#   * 7.7 GiB of RAM running a 7.54 GiB application with MemoryMax=infinity —
#     the kernel's global OOM killer killed company-api 4 minutes after the
#     cutover (journalctl -k, 05:47:24Z). NEW: api_rss_gib, api_peak_gib,
#     api_memmax_infinite, oom_kills_24h, swap_used_pct.
#   * ONE disk, 75 GB, holding a 23.7 GB database, with 4-27 GB free depending
#     on what is in flight. NEW: disk_used_pct, disk_free_deficit_gb, and the
#     new offsite script's own `running` marker, because a disk-fill during a
#     backup is the failure this estate has already taken down twice.
#   * the authority database itself is now the single copy of everything, and
#     NOTHING measured it. NEW: authority_db_gib, authority_db_growth_mb_h and
#     authority_db_shrink_mb — a database that gets SMALLER is either the wrong
#     file or a truncation, and this estate's worst recorded failure was reading
#     a stale copy and believing it.
#   * the external dead-man switch is the only thing that can report this box
#     being dead, and it was already silent for 5 h 15 min before the cutover
#     and nothing noticed (135-PARITY-AND-ROBUSTNESS.md 6.7). NEW:
#     deadman_check_lapse, deadman_ping_age_s, deadman_local_run_age_s,
#     deadman_local_last_ok — the detector for the detector, from both sides.
#
# DROPPED, with the reason (these are the office box's own instruments and are
# still running on the office box, which stays its own monitor of record):
#   * backup_duration_s / backup_peak_rss_gib / backup_running /
#     backup_memmax_infinite against secretary-backup.service — that unit does
#     not exist here; the offsite leg is measured instead.
#   * sshd_exempt_missing_ranges / sshd_penalty_* — the 2026-10-07
#     PersSourcePenaltyExemptList incident was an office-LAN incident
#     (192.168.50.0/24, 100.64.0.0/10 exempt ranges). This box's sshd is on the
#     public internet behind ufw+fail2ban and has no such list.
#   * dispatch_shift_no_work_product_24h / dispatch_rc_nonzero_24h — they read
#     ~/.sms-inbox/wake-cron.log and ~/.cron-status/runs.tsv, neither of which
#     existed here at port time. They belong to the workstream that ports the
#     wake fan-out; re-add them then, against /root/.cron-status/runs.tsv.
#   * the office's offsite_push_* metrics read
#     ~/logs/company-offsite-push.log (the restic "Box 2" leg). This box's legs
#     are the R2 object and the new authority-offsite-backup.sh.
#
# THE OUTSIDE PROBE IS STILL TAKEN FROM OUTSIDE. A reporter that lives on the
# thing it reports on is not a reporter, so `public_health_status` and
# `offsite_object_age_h` are still read over ssh from the vault (lpt-apps-01,
# root@2.28.33.58) — the same machine the office version used. That ssh and the
# healthchecks.io call are CACHED (see REMOTE_TTL_S / DEADMAN_TTL_S) so a
# 2-minute cadence on a box already at 26-32 % CPU pressure and 11-18 % full I/O
# stall does not spend its headroom on monitoring.
#
# Stdlib only. Run: estate-monitor.py [--json] [--no-alert] [--thresholds F]
# ===========================================================================
import argparse
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

HOME = os.path.expanduser("~")                      # /root
BASE = os.environ.get("ESTATE_MONITOR_DIR", "/root/.estate-monitor")
STATE_PATH = os.path.join(BASE, "state.json")
LOG_PATH = os.path.join(BASE, "monitor.log")
ALERTS_PATH = os.path.join(BASE, "alerts.jsonl")
ESCALATION_PATH = os.path.join(BASE, "ESCALATED")
HEARTBEAT_PATH = os.path.join(BASE, "last-run")
THRESHOLDS_PATH = os.path.join(BASE, "thresholds.json")

# --- what we watch ----------------------------------------------------------
DB_PATH = os.environ.get("AUTHORITY_DB", "/root/authority.db")
API_UNIT = os.environ.get("COMPANY_API_UNIT", "company-api.service")
BACKUP_DIR = os.environ.get("AUTHORITY_BACKUP_DIR", "/var/lib/authority-backup")
OFFSITE_LAST_RUN = os.path.join(BACKUP_DIR, "last-run")
OFFSITE_RUNNING = os.path.join(BACKUP_DIR, "running")
# 2026-10-16: the SECOND leg. `authority-data-offsite.service` copies /opt/company/data (~4 GB) to
# `authority/data/authority-data.tar.gz` daily and writes `data-last-run`. It refused to start at
# 06:39:28Z on the 16th (exit 3, "only 1582332 KiB free under /var/tmp; refusing to start") and did
# not run again for 14 h - and NO metric here moved, because every offsite metric below reads the
# DATABASE leg's `last-run`. Measured the same minute: this box reported
# `offsite_object_age_h=14.952 st=ok` while the data object in R2 was 38.16 h stale.
OFFSITE_DATA_LAST_RUN = os.path.join(BACKUP_DIR, "data-last-run")
DEADMAN_UNIT = "authority-deadman.service"
DEADMAN_ENVF = "/root/.sms-inbox/deadman.env"

# The vault: the machine OUTSIDE this box that does the probing, and the place
# the offsite reporter leaves the R2 object's own LastModified.
VAULT_HOST = os.environ.get("ESTATE_VAULT", "root@2.28.33.58")
VAULT_KEY = os.environ.get("ESTATE_VAULT_KEY", "/root/.ssh/id_ed25519_hetzner")
VAULT_OFFSITE_JSON = "/var/lib/company-offsite/authority-push.json"
VAULT_HEARTBEAT_JSON = "/var/lib/company-heartbeat/state.json"
PUBLIC_URL = os.environ.get("ESTATE_MONITOR_HEALTH_URL",
                            "https://api.abletelsolutions.com/health")

# Cache lifetimes. The heavy collectors are the two that leave the box.
REMOTE_TTL_S = int(os.environ.get("ESTATE_MONITOR_REMOTE_TTL", "300"))
DEADMAN_TTL_S = int(os.environ.get("ESTATE_MONITOR_DEADMAN_TTL", "600"))
OOM_TTL_S = int(os.environ.get("ESTATE_MONITOR_OOM_TTL", "300"))

# --- thresholds -------------------------------------------------------------
# `clear` is the fraction of the trigger at which a raised state may drop again
# (hysteresis). `max_age` is the longest a stale reading may be shown before it
# becomes CRIT. `mode` is "log" or "alert" — and only public_health_status is
# allowed to be "alert". `for_runs` is how many consecutive breaches are needed
# before the state is believed, against a 120 s cadence.
DEFAULTS = {
    # ---- host pressure -----------------------------------------------------
    "psi_io_full_avg60": dict(
        warn=30.0, crit=60.0, clear=0.75, max_age=900, for_runs=2, unit="%",
        why="The office box read 78.4 here at its 2026-10-07 I/O starvation. "
            "THIS box measured full avg10 0.77 / avg60 3.33 / avg300 8.13 at "
            "rest (06:27Z) while carrying the company and the migration fleet, "
            "so 30 % still means 'a third of wall time fully stalled'.",
        mode="log"),
    "psi_io_full_avg300": dict(
        warn=25.0, crit=45.0, clear=0.75, max_age=1200, for_runs=1, unit="%",
        why="The 5-minute average separates a burst from a condition. Rest "
            "measured 8.13 here, so 25 is 3x rest and 45 is the point where "
            "this is no longer a backup.",
        mode="log"),
    "psi_cpu_some_avg60": dict(
        warn=40.0, crit=70.0, clear=0.75, max_age=900, for_runs=2, unit="%",
        why="2 vCPU. Measured 26-32 % at rest with the migration fleet "
            "running; there is no spare capacity on this box, so a sustained "
            "reading above 40 % means new work has nowhere to go.",
        mode="log"),
    "load_per_cpu": dict(
        warn=3.0, crit=6.0, clear=0.75, max_age=900, for_runs=2, unit="",
        why="load1/nproc, nproc=2 here. Measured 0.97 (1.93 load) at rest.",
        mode="log"),
    "dstate_count": dict(
        warn=3.0, crit=6.0, clear=0.6, max_age=900, for_runs=2, unit="",
        why="Processes uninterruptible on I/O. 8-10 at the office incident; "
            "3 is already not normal for a 2-vCPU box whose only disk holds "
            "the company's database.",
        mode="log"),
    "dstate_max_age_s": dict(
        warn=45.0, crit=90.0, clear=0.6, max_age=900, for_runs=1, unit="s",
        why="Age is time continuously observed in D by THIS monitor, so it "
            "under-reports by at most one sampling interval and resets if a "
            "process leaves D and returns.",
        mode="log"),

    # ---- the disk ----------------------------------------------------------
    "disk_used_pct": dict(
        warn=90.0, crit=95.0, clear=0.9, max_age=900, for_runs=2, unit="%",
        why="75 GB total against a 23.7 GB database. Measured 94 % at 06:09:32Z "
            "and 65 % at 06:20:50Z on the same machine eleven minutes apart, so "
            "this MUST be suppressed while the offsite backup is in flight or "
            "it would fire on every legitimate run. The unsuppressed number is "
            "still recorded in the note.",
        mode="log", suppress_when_backup_active=True),
    "disk_free_deficit_gb": dict(
        warn=2.0, crit=6.0, clear=0.8, max_age=900, for_runs=2, unit="GiB",
        why="max(0, 10 - free_GiB): so warn means less than 8 GiB free and crit "
            "means less than 4 GiB free. Deliberately NOT suppressed during a "
            "backup — SQLite does not degrade gracefully when its disk fills "
            "(office, 2026-09-30: / at 99 %, 7.6 GB free, SIGBUS) — and "
            "crit=6.0 uses for_runs=1 because below 4 GiB there is no time to "
            "wait for a second opinion. The 06:09:32Z reading would have been "
            "crit=6.0 at 4.4 GB free. RAISED TO ALERT 2026-10-15: on 2026-10-14 this box reached 0 bytes free three times (00:15Z, 14:45Z, 23:00Z) and this metric stayed mode=log, so no alarm reached a person. It is the right one to raise because it is NOT suppressed during a backup by design, and for_runs=1 is already set for it.",
        mode="alert"),
    "disk_util_pct": dict(
        warn=85.0, crit=95.0, clear=0.85, max_age=900, for_runs=2, unit="%",
        why="Device busy % from the io_ticks delta — this is utilisation, not "
            "space; the space gauge is disk_used_pct. Suppressed while the "
            "offsite backup runs, which legitimately drives it up.",
        mode="log", suppress_when_backup_active=True),
    "tmp_used_pct": dict(
        warn=70.0, crit=90.0, clear=0.85, max_age=900, for_runs=2, unit="%",
        why="/tmp is a 3.8 GB tmpfs with usrquota (findmnt, measured). The "
            "office box's tmp-reaper exists because a 3-byte write to a "
            "usrquota'd /tmp failed with EDQUOT and broke things machine-wide. "
            "This metric is that visibility WITHOUT the deleter: the office "
            "tmp-reaper's --apply is deliberately NOT ported (see 137's report "
            "— it does not exclude *.lock, and the ported cron jobs guard "
            "themselves with `flock /tmp/<name>.lock`).",
        mode="log"),

    # ---- the authority database -------------------------------------------
    "authority_db_gib": dict(
        warn=None, crit=None, clear=1.0, max_age=900, for_runs=1, unit="GiB",
        why="Informational: the size of the single copy of everything.",
        mode="log", info=True),
    "authority_db_growth_mb_h": dict(
        warn=None, crit=None, clear=1.0, max_age=3600, for_runs=1, unit="MB/h",
        why="Informational: bytes gained per hour between two readings, and "
            "only measured when the gap is 10 minutes or more. A growth figure "
            "makes 'the disk will fill on <date>' arithmetic instead of a "
            "feeling.",
        mode="log", info=True),
    "authority_db_shrink_mb": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=900, for_runs=1, unit="MB",
        why="Megabytes the MAIN database file LOST since the previous reading. "
            "warn == crit == 1 because it is never legitimate live: it means "
            "the monitor is looking at a different file (the wrong path, a "
            "restored copy) or the file was truncated. This estate's worst "
            "recorded failure was reading a stale copy and believing it, and "
            "this is the cheapest possible detector for its recurrence.",
        mode="log"),
    "authority_wal_mb": dict(
        warn=512.0, crit=1024.0, clear=0.8, max_age=900, for_runs=2, unit="MB",
        why="Measured 64 MiB and moving (a healthy WAL checkpoints). A WAL that "
            "climbs past 512 MB is a reader or a writer that has stopped the "
            "checkpoint, which is the first visible sign of a stuck writer.",
        mode="log"),

    # ---- the offsite copy --------------------------------------------------
    "offsite_object_age_h": dict(
        warn=26.0, crit=30.0, clear=0.85, max_age=1800, for_runs=1, unit="h",
        why="Age of the REAL object in R2 (authority/secretary.db.gz), read "
            "from the vault's authority-push.json — i.e. from outside this box. "
            "Its producer runs daily (authority-offsite-backup.timer, 05:20 "
            "UTC + up to 10 min jitter), so a healthy age oscillates over 24 h "
            "and the threshold must be a whole cycle. 26 h is one missed day; "
            "30 h is the limit the vault's own company-offsite-status.sh uses. "
            "Measured at port time: last_modified 2026-10-10T05:20:09Z, i.e. "
            "~25 h old and climbing, because the office pusher died with the "
            "freeze.",
        mode="log"),
    "offsite_lastrun_age_h": dict(
        warn=26.0, crit=30.0, clear=0.85, max_age=1800, for_runs=1, unit="h",
        why="The same question asked of THIS box's own record "
            "(/var/lib/authority-backup/last-run, written by "
            "authority-offsite-backup.sh). Kept separate from the R2 object on "
            "purpose: two records, two numbers, so a successful local run that "
            "never arrived cannot hide behind the object's age.",
        mode="log"),
    "offsite_lastrun_not_ok": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=3600, for_runs=1, unit="",
        why="The offsite run's own status field is anything other than `ok`. "
            "warn == crit == 1: this is the copy that survives the machine.",
        mode="log"),
    "offsite_running_stale": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=900, for_runs=1, unit="",
        why="A `running` marker older than 4 h. authority-offsite-backup.sh "
            "removes the marker on success and leaves it on failure so an "
            "abandoned run cannot look like an idle one; this is what makes "
            "that promise true, and what the dead-man switch's own freshness "
            "verdict reads.",
        mode="log"),
    # ---- the SECOND offsite leg: /opt/company/data (added 2026-10-16) -------
    "offsite_data_lastrun_age_h": dict(
        warn=26.0, crit=27.0, clear=0.85, max_age=1800, for_runs=1, unit="h",
        why="The same question the three metrics above ask, asked of the OTHER "
            "leg: /var/lib/authority-backup/data-last-run, written by "
            "authority-data-offsite.sh. Its producer is daily at 06:30 UTC + up "
            "to 10 min jitter and takes ~12 min, so a healthy age oscillates "
            "over ~24.5 h and one missed cycle is 26 h. It had NO reader at all "
            "before this metric: on 2026-10-16 the data object in R2 reached "
            "38.16 h stale while every offsite metric here read `ok`, because "
            "they all read the database leg's `last-run`.",
        mode="log"),
    "offsite_data_lastrun_not_ok": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=3600, for_runs=1, unit="",
        why="The DATA leg's own status field is anything other than `ok`. "
            "warn == crit == 1, as for the database leg: this copy holds "
            "family_chat.db, agent_identities.json and the Google credentials, "
            "none of which can be regenerated.",
        mode="log"),

    # ---- the application process ------------------------------------------
    "api_rss_gib": dict(
        warn=9.0, crit=10.0, clear=0.85, max_age=900, for_runs=2, unit="GiB",
        why="company-api's OWN process RSS (VmRSS, /proc/MainPID/status). This "
            "USED to read the cgroup's MemoryCurrent, which adds RECLAIMABLE "
            "PAGE CACHE: on 2026-10-14 05:30-05:34Z it read 6.31-7.85 GiB for a "
            "process whose VmRSS was about 3 GiB, i.e. the alarm tracked cache "
            "the kernel drops for free. The box has 7.7 GiB "
            "and MemoryMax is infinity, so at 6.0 GiB the kernel's global OOM "
            "killer is choosing a victim from the whole box — and on 2026-10-11 "
            "05:47:24Z it chose company-api. warn is 5.0 rather than a tick above "
            "the current value on purpose: a threshold that fires continuously is "
            "the 37-texts failure mode the office file already records. "
            "RETHRESHOLDED 5.0/6.0 -> 9.0/10.0 on 2026-10-14 17:2xZ, because the "
            "old pair repeated exactly that failure: over the 1,126 readings this "
            "instrument took while MemoryMax was infinity, VmRSS was p50 6.49 GiB "
            "and p90 8.86 GiB, so a crit at 6.0 GiB was below the app's MEDIAN and "
            "was therefore always on. crit is now set AT MemoryMax (10 GiB, "
            "company-api.service.d/30-memory.conf) so it means what it should mean: "
            "'this service is at the ceiling and a kill is imminent'. warn is one "
            "GiB below it. IF THE APP'S APPETITE IS EVER FIXED — its median is 6.5 "
            "GiB for 618 routes and 203 tables, which is its own defect — bring "
            "both numbers back down in the same commit.",
        mode="log"),
    "api_peak_gib": dict(
        warn=None, crit=None, clear=1.0, max_age=900, for_runs=1, unit="GiB",
        why="Informational: MemoryPeak since the unit started. Cannot be "
            "thresholded — a peak does not come down, so any trigger would stay "
            "fired for ever.",
        mode="log", info=True),
    "oom_kills_24h": dict(
        warn=1.0, crit=3.0, clear=1.0, max_age=3600, for_runs=1, unit="",
        why="Processes the kernel's OOM killer has killed in the last 24 h "
            "(journalctl -k). Measured: exactly one event, 2026-10-11 "
            "05:47:24Z, four minutes after the cutover — `global_oom`, "
            "`constraint=CONSTRAINT_NONE`, so the victim is chosen box-wide and "
            "next time it can be sshd, cloudflared, or the process holding the "
            "database.",
        mode="log"),
    "swap_used_pct": dict(
        warn=60.0, crit=85.0, clear=0.8, max_age=900, for_runs=2, unit="%",
        why="4 GiB of swap, measured 41 % used at 06:21Z with vmstat showing "
            "active si/so — the box is swapping under ordinary load, which is "
            "what makes api_rss_gib the metric that matters.",
        mode="log"),

    # ---- the public door, from OUTSIDE ------------------------------------
    "public_health_status": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=1800, for_runs=3, unit="",
        why="1 == not HTTP 200, probed from the vault (lpt-apps-01), i.e. from "
            "OUTSIDE this box, so an outage of this host cannot hide it. THE "
            "ONLY CONDITION ALLOWED TO ESCALATE; for_runs=3 matches the vault "
            "heartbeat's own consecutive-failure guard, so a single blip wakes "
            "nobody.",
        mode="alert"),
    "public_health_ttfb_ms": dict(
        warn=2000.0, crit=5000.0, clear=0.75, max_age=1800, for_runs=1, unit="ms",
        why="Time to first byte as seen from outside. Measured from the laptop "
            "2026-10-11: median 221 ms to this endpoint via Cloudflare; the "
            "office box read 15,161 ms at its starvation incident. 2 s is 9x "
            "healthy, 5 s is customer-visible.",
        mode="log"),

    # ---- the dead-man switch, from both sides ------------------------------
    "deadman_check_lapse": dict(
        warn=1.0, crit=2.0, clear=1.0, max_age=2400, for_runs=1, unit="",
        why="healthchecks.io's own verdict on the check 'secratary authority "
            "alive' (period 900 s, grace 300 s): 0=up, 1=grace/late, 2=down or "
            "new. This is the DETECTOR FOR THE DETECTOR. It is not the "
            "dead-man switch — if this box dies, so does this metric — but it "
            "is the only thing that notices the switch going quiet while the "
            "box is still alive, which is exactly what happened on the office "
            "box: the pinger last ran 2026-10-10T22:45:02Z and nothing said so "
            "for 5 h 15 min, straight through the 3 h 29 min outage that "
            "followed. Needs the API key, so healthchecks.io has to be "
            "reachable; when it is not, this is NODATA, never ok.",
        mode="log"),
    "deadman_ping_age_s": dict(
        warn=900.0, crit=1500.0, clear=0.8, max_age=2400, for_runs=1, unit="s",
        why="Age of the switch's own last_ping. The check is 900 s with a 300 s "
            "grace, so at 900 s it is one interval late and at 1500 s it is "
            "inside grace and about to alarm.",
        mode="log"),
    "deadman_local_run_age_s": dict(
        warn=900.0, crit=1500.0, clear=0.8, max_age=1800, for_runs=1, unit="s",
        why="Age of the last run of authority-deadman.service on THIS box, from "
            "systemd. Separate from the external verdict on purpose: a timer "
            "that stopped and a network that stopped look identical from "
            "outside, and they are fixed by different people.",
        mode="log"),
    "deadman_local_last_ok": dict(
        warn=1.0, crit=1.0, clear=1.0, max_age=1800, for_runs=1, unit="",
        why="1 when the dead-man unit's last run did not exit 0. It swallows "
            "its own failures by design (a dead-man switch that breaks its "
            "caller is worse than none), which means its exit code is the only "
            "local evidence that it ran at all.",
        mode="log"),

    # ---- the monitor itself ------------------------------------------------
    "monitor_run_gap_s": dict(
        warn=420.0, crit=900.0, clear=0.8, max_age=900, for_runs=1, unit="s",
        why="Gap since this monitor's own previous run against a 120 s timer. "
            "If this monitor stops, its own metrics stop arriving, so it "
            "measures that too. 420 s is two missed runs. The same fact is "
            "readable from outside in the journald timestamps of "
            "estate-monitor.service.",
        mode="log"),
}

STATE_RANK = {"ok": 0, "info": 0, "nodata": 1, "warn": 2, "crit": 3}
RANK_STATE = {0: "ok", 1: "nodata", 2: "warn", 3: "crit"}


# --- helpers ----------------------------------------------------------------
def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_loose(s):
    """Accept '2026-10-11T05:20:09+00:00', 8 fractional digits, Z, or a space."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
                 r"(Z|[+-]\d{2}:?\d{2})?$", s)
    if not m:
        return None
    frac = (m.group(3) or "")[:6].ljust(6, "0")
    tzs = m.group(4) or "Z"
    if tzs == "Z":
        tzs = "+00:00"
    elif re.match(r"^[+-]\d{4}$", tzs):
        tzs = tzs[:3] + ":" + tzs[3:]
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}.{frac}{tzs}")
    except ValueError:
        return None


def parse_systemd_ts(s):
    """'Wed 2026-10-07 12:00:00 UTC' -> datetime, else None."""
    if not s:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", str(s))
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}T{m.group(2)}",
                                 "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def run(cmd, timeout=20, stdin=None):
    """Return (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, input=stdin,
                           timeout=timeout, text=True)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", f"not found: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return 1, "", f"{type(e).__name__}: {e}"


def kv_file(path):
    """Parse a `key=value` evidence file. Returns (dict, None) or ({}, error)."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError as e:
        return {}, f"{path}: {e.strerror or e}"
    return out, None


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, obj):
    """Write state. NEVER fatal.

    Measured 2026-10-14: with the filesystem at 0 bytes free this raised
    OSError(ENOSPC) and the whole run died -- AFTER the escalation block had run, so
    the alarm was emitted and then the run crashed. A monitor's state write must never
    be able to kill the monitor's own alarm.
    """
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            import subprocess as _sp
            _sp.run(["logger", "-p", "daemon.err", "-t", "estate-monitor",
                     "STATE WRITE FAILED (%s): %s" % (type(exc).__name__, exc)],
                    timeout=10)
        except Exception:
            pass


def proc_rss_gib(pid):
    """The process's OWN resident set, VmRSS, not the cgroup total.

    memory.current (systemd MemoryCurrent) counts anon + file pages for the
    whole cgroup, including RECLAIMABLE PAGE CACHE. On 2026-10-14 it read
    6.31-7.85 GiB while company-api VmRSS was about 3 GiB, so a threshold on
    it fires on cache the kernel would drop for free. Ledger item 175.
    """
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return None, "MainPID=%r is not a pid" % (pid,)
    if p <= 0:
        return None, "MainPID=%d (unit not running)" % p
    try:
        with open("/proc/%d/status" % p, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 2 ** 20, 3), None
    except OSError as e:
        return None, "/proc/%d/status: %s" % (p, e.strerror or e)
    return None, "no VmRSS line in /proc/%d/status" % p


def systemd_show(unit, props):
    rc, so, se = run(["systemctl", "show", unit] +
                     [x for p in props for x in ("-p", p)], timeout=15)
    if rc != 0:
        return {}, f"systemctl show {unit} rc={rc}: {se.strip()[:80]}"
    d = {}
    for line in so.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d, None


# --- collectors -------------------------------------------------------------
# Each collector returns a dict, or raises to become NODATA. The two collectors
# that leave the box are cached in the state file so a 120 s cadence does not
# spend this box's thin CPU/IO headroom on monitoring.
def collectors(state, facts, errors):
    out = {}

    def need(name, fn):
        try:
            out[name] = fn()
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"

    # ---- /proc: pressure, load, memory ------------------------------------
    def proc():
        vals = {}
        for kind in ("io", "cpu", "memory"):
            try:
                with open(f"/proc/pressure/{kind}") as f:
                    for line in f:
                        parts = line.split()
                        if not parts:
                            continue
                        tag = parts[0]
                        for p in parts[1:]:
                            if "=" in p:
                                k, v = p.split("=", 1)
                                vals[f"{kind}_{tag}_{k}"] = float(v)
            except OSError:
                pass
        if not vals:
            raise RuntimeError("no /proc/pressure readings")
        with open("/proc/loadavg") as f:
            vals["load1"] = float(f.read().split()[0])
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k.strip()] = int(v.split()[0])  # kB
        vals["mem_total_gib"] = round(mem["MemTotal"] / 1048576.0, 2)
        vals["mem_available_gib"] = round(mem["MemAvailable"] / 1048576.0, 2)
        vals["swap_total_kb"] = mem.get("SwapTotal", 0)
        vals["swap_free_kb"] = mem.get("SwapFree", 0)
        return vals

    need("proc", proc)

    def diskstats():
        rc, so, se = run(["cat", "/proc/diskstats"], timeout=10)
        if rc != 0:
            raise RuntimeError(f"diskstats rc={rc}")
        cur = {}
        for line in so.splitlines():
            p = line.split()
            if len(p) < 14:
                continue
            name = p[2]
            if not re.match(r"^(dm-\d+|sd[a-z]+|nvme\d+n\d+|vd[a-z]+)$", name):
                continue
            cur[name] = int(p[12])  # io_ticks, ms
        if not cur:
            raise RuntimeError("no whole-device rows in /proc/diskstats")
        return cur

    need("diskstats", diskstats)

    def dstate():
        rc, so, se = run(["ps", "-eo", "stat=,pid=,comm="], timeout=15)
        if rc != 0:
            raise RuntimeError(f"ps rc={rc}: {se.strip()[:80]}")
        cur = {}
        for line in so.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            st, pid, comm = parts
            if st.startswith("D"):
                cur[pid] = comm.strip()
        return cur

    need("dstate", dstate)

    def filesystems():
        rc, so, se = run(["df", "-P", "-k", "/", "/tmp"], timeout=15)
        if rc != 0:
            raise RuntimeError(f"df rc={rc}: {se.strip()[:80]}")
        d = {}
        for line in so.splitlines()[1:]:
            p = line.split()
            if len(p) < 6:
                continue
            mount = p[5]
            total, used, avail = int(p[1]), int(p[2]), int(p[3])
            d[mount] = {"total_kb": total, "used_kb": used, "avail_kb": avail,
                        "pct": round(100.0 * used / total, 2) if total else None,
                        "source": p[0]}
        if "/" not in d:
            raise RuntimeError("df produced no row for /")
        return d

    need("filesystems", filesystems)

    # ---- the authority database: stat only, never open ---------------------
    # Opening a 23.7 GB database from a monitor would be the monitor becoming
    # the load source. os.stat is all that is needed for size, growth, shrink
    # and WAL, and it takes no lock, creates no -shm/-wal and cannot write.
    def dbstat():
        d = {}
        for suffix, key in (("", "db"), ("-wal", "wal"), ("-shm", "shm")):
            try:
                st = os.stat(DB_PATH + suffix)
                d[key] = {"bytes": st.st_size, "mtime": int(st.st_mtime)}
            except OSError as e:
                if suffix == "":
                    raise RuntimeError(f"stat {DB_PATH}: {e.strerror or e}")
                d[key] = None
        return d

    need("dbstat", dbstat)

    # ---- the application process ------------------------------------------
    def api():
        props = ["ActiveState", "SubState", "Result", "MainPID", "NRestarts",
                 "MemoryCurrent", "MemoryPeak", "MemoryMax",
                 "ExecMainStartTimestamp"]
        d, err = systemd_show(API_UNIT, props)
        if err:
            raise RuntimeError(err)
        return d

    need("api", api)

    # ---- the offsite backup's own evidence --------------------------------
    def offsite():
        running, rerr = kv_file(OFFSITE_RUNNING)
        lastrun, lerr = kv_file(OFFSITE_LAST_RUN)
        datarun, derr = kv_file(OFFSITE_DATA_LAST_RUN)
        return {"running": running or None, "running_err": rerr if not running else None,
                "last_run": lastrun or None,
                "last_run_err": lerr if not lastrun else None,
                "data_last_run": datarun or None,
                "data_last_run_err": derr if not datarun else None}

    need("offsite", offsite)

    # ---- the kernel's own OOM record (cached) ------------------------------
    def oom():
        cache = state.setdefault("oom_cache", {})
        if time.time() - cache.get("at", 0) < OOM_TTL_S and cache.get("data") is not None:
            facts["oom_cached"] = True
            return cache["data"]
        facts["oom_cached"] = False
        rc, so, se = run(["journalctl", "-k", "--since", "-24h", "--no-pager",
                          "-o", "cat", "-n", "50000"], timeout=45)
        if rc != 0:
            raise RuntimeError(f"journalctl -k rc={rc}: {se.strip()[:80]}")
        killed, oomk = [], []
        for line in so.splitlines():
            if "Killed process" in line:
                killed.append(line.strip())
            elif "oom-kill:" in line:
                oomk.append(line.strip())
        data = {"kills": len(killed), "oom_events": len(oomk),
                "sample": (killed[-1][:200] if killed else "")}
        cache["at"] = time.time()
        cache["data"] = data
        return data

    need("oom", oom)

    # ---- the vault: OUTSIDE this box (cached) ------------------------------
    def remote():
        cache = state.setdefault("remote_cache", {})
        if (time.time() - cache.get("at", 0) < REMOTE_TTL_S
                and cache.get("data") is not None):
            facts["remote_cached"] = True
            return cache["data"]
        facts["remote_cached"] = False
        script = r"""
echo "rh=$(hostname)"
for f in VAULT_OFFSITE VAULT_HB; do
  if [ -f "$f" ]; then
    echo "file|$f|$(stat -c %Y "$f")|$(tr -d '\n' < "$f")"
  else
    echo "missing|$f"
  fi
done
p=$(curl -s -o /dev/null -w '%{http_code} %{time_starttransfer} %{time_total}' --max-time 20 URL_PLACEHOLDER 2>/dev/null)
echo "probe|${p:-000 0 0}"
""".replace("URL_PLACEHOLDER", shlex.quote(PUBLIC_URL)) \
   .replace("VAULT_OFFSITE", VAULT_OFFSITE_JSON) \
   .replace("VAULT_HB", VAULT_HEARTBEAT_JSON)
        rc, so, se = run(
            ["ssh", "-i", VAULT_KEY, "-o", "BatchMode=yes",
             "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
             VAULT_HOST, "bash -s"],
            timeout=60, stdin=script)
        if rc != 0:
            raise RuntimeError(f"ssh {VAULT_HOST} rc={rc}: {se.strip()[:120]}")
        d = {"files": {}, "probe": None, "host": None}
        for line in so.splitlines():
            if line.startswith("rh="):
                d["host"] = line[3:]
            elif line.startswith("file|"):
                _, path, mt, body = line.split("|", 3)
                try:
                    obj = json.loads(body)
                except Exception:
                    obj = None
                d["files"][path] = {"mtime": int(mt), "json": obj}
            elif line.startswith("missing|"):
                d["files"][line.split("|", 1)[1]] = None
            elif line.startswith("probe|"):
                parts = line.split("|", 1)[1].split()
                try:
                    d["probe"] = {"code": parts[0],
                                  "ttfb_ms": round(float(parts[1]) * 1000.0, 1),
                                  "total_ms": round(float(parts[2]) * 1000.0, 1)}
                except (IndexError, ValueError):
                    d["probe"] = {"code": "000", "ttfb_ms": None,
                                  "total_ms": None,
                                  "error": "unparseable curl output"}
        if d["probe"] is None:
            raise RuntimeError("remote probe produced no output")
        cache["at"] = time.time()
        cache["data"] = d
        return d

    need("remote", remote)

    # ---- the dead-man switch, from both sides (cached API call) ------------
    def deadman():
        d = {"external": None, "external_err": None, "local": None, "local_err": None}

        cache = state.setdefault("deadman_cache", {})
        if (time.time() - cache.get("at", 0) < DEADMAN_TTL_S
                and cache.get("data") is not None):
            d["external"] = cache["data"]
            facts["deadman_cached"] = True
        else:
            facts["deadman_cached"] = False
            key = None
            try:
                with open(DEADMAN_ENVF) as f:
                    for line in f:
                        if line.startswith("HEALTHCHECKS_API_KEY="):
                            key = line.split("=", 1)[1].strip()
            except OSError as e:
                d["external_err"] = f"{DEADMAN_ENVF}: {e.strerror or e}"
            if key is None and d["external_err"] is None:
                d["external_err"] = f"no HEALTHCHECKS_API_KEY in {DEADMAN_ENVF}"
            if key:
                try:
                    req = urllib.request.Request(
                        "https://healthchecks.io/api/v3/checks/",
                        headers={"X-Api-Key": key})
                    with urllib.request.urlopen(req, timeout=25) as r:
                        payload = json.load(r)
                    found = None
                    for c in payload.get("checks", []):
                        if (c.get("name") or "").lower() == "secratary authority alive":
                            found = c
                            break
                    if found is None:
                        d["external_err"] = ("the check 'secratary authority alive' "
                                             "is not in the account's check list")
                    else:
                        # Never echo the response: it carries ping/update/pause
                        # URLs, which are credentials.
                        d["external"] = {
                            "status": found.get("status"),
                            "last_ping": found.get("last_ping"),
                            "next_ping": found.get("next_ping"),
                            "timeout": found.get("timeout"),
                            "grace": found.get("grace"),
                            "n_pings": found.get("n_pings"),
                        }
                        cache["at"] = time.time()
                        cache["data"] = d["external"]
                except Exception as e:
                    d["external_err"] = f"healthchecks.io: {type(e).__name__}: {str(e)[:100]}"

        props = ["ActiveState", "Result", "ExecMainStatus", "ExecMainExitTimestamp"]
        l, err = systemd_show(DEADMAN_UNIT, props)
        if err:
            d["local_err"] = err
        else:
            d["local"] = l
        return d

    need("deadman", deadman)
    return out


# --- classification ---------------------------------------------------------
def classify(value, th, prev_state, prev_streak):
    """Return (state, streak). Hysteresis: to ENTER, >= trigger; to STAY,
    >= trigger*clear. for_runs gates how many consecutive breaches are believed.
    """
    if value is None:
        return "nodata", 0
    warn, crit = th.get("warn"), th.get("crit")
    if warn is None or crit is None:
        return "info", 0
    clear = th.get("clear", 0.8)
    staying = prev_state in ("warn", "crit")
    if staying:
        wtrig, ctrig = warn * clear, crit * clear
    else:
        wtrig, ctrig = warn, crit
    raw = "crit" if value >= ctrig else ("warn" if value >= wtrig else "ok")
    if raw == "ok":
        return "ok", 0
    streak = prev_streak + 1
    if streak < int(th.get("for_runs", 1)):
        return (prev_state if prev_state in ("warn", "crit") else "ok"), streak
    return raw, streak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print state JSON and exit")
    ap.add_argument("--no-alert", action="store_true",
                    help="never touch the escalation path (used for proofs)")
    ap.add_argument("--thresholds", default=None,
                    help="JSON file overriding metric thresholds")
    args = ap.parse_args()

    os.makedirs(BASE, exist_ok=True)
    started = time.time()
    now = now_utc()
    prev = load_state()
    prev_metrics = prev.get("metrics", {})

    th = {k: dict(v) for k, v in DEFAULTS.items()}
    if os.path.exists(THRESHOLDS_PATH):
        try:
            with open(THRESHOLDS_PATH) as f:
                for k, v in json.load(f).items():
                    th.setdefault(k, {}).update(v)
        except Exception as e:
            print(f"estate-monitor: thresholds file unreadable: {e}", file=sys.stderr)
    override = args.thresholds or os.environ.get("ESTATE_MONITOR_THRESHOLDS")
    if override:
        with open(override) as f:
            for k, v in json.load(f).items():
                th.setdefault(k, {}).update(v)
        th["_override"] = override

    facts = {}
    errors = {}
    c = collectors(prev, facts, errors)

    metrics = {}
    SRC = {
        "psi_io_full_avg60": "/proc/pressure/io",
        "psi_io_full_avg300": "/proc/pressure/io",
        "psi_cpu_some_avg60": "/proc/pressure/cpu",
        "load_per_cpu": "/proc/loadavg",
        "dstate_count": "ps -eo stat,pid,comm",
        "dstate_max_age_s": "ps -eo stat,pid,comm (monitor-observed)",
        "disk_used_pct": "df -P -k /",
        "disk_free_deficit_gb": "df -P -k /",
        "disk_util_pct": "/proc/diskstats (io_ticks delta)",
        "tmp_used_pct": "df -P -k /tmp",
        "authority_db_gib": f"stat {DB_PATH}",
        "authority_db_growth_mb_h": f"stat {DB_PATH} (delta)",
        "authority_db_shrink_mb": f"stat {DB_PATH} (delta)",
        "authority_wal_mb": f"stat {DB_PATH}-wal",
        "offsite_object_age_h": VAULT_OFFSITE_JSON + " @ " + VAULT_HOST,
        "offsite_lastrun_age_h": OFFSITE_LAST_RUN,
        "offsite_lastrun_not_ok": OFFSITE_LAST_RUN,
        "offsite_data_lastrun_age_h": OFFSITE_DATA_LAST_RUN,
        "offsite_data_lastrun_not_ok": OFFSITE_DATA_LAST_RUN,
        "offsite_running_stale": OFFSITE_RUNNING,
        "api_rss_gib": f"systemctl show {API_UNIT}",
        "api_peak_gib": f"systemctl show {API_UNIT}",
        "oom_kills_24h": "journalctl -k --since -24h",
        "swap_used_pct": "/proc/meminfo",
        "public_health_status": f"curl @ {VAULT_HOST} (outside this box)",
        "public_health_ttfb_ms": f"curl @ {VAULT_HOST} (outside this box)",
        "deadman_check_lapse": "healthchecks.io /api/v3/checks/",
        "deadman_ping_age_s": "healthchecks.io /api/v3/checks/",
        "deadman_local_run_age_s": f"systemctl show {DEADMAN_UNIT}",
        "deadman_local_last_ok": f"systemctl show {DEADMAN_UNIT}",
        "monitor_run_gap_s": "self",
    }

    def emit(mid, value, unit=None, src=None, note="", info=False):
        t = th.get(mid)
        if t is None:
            t = dict(warn=None, crit=None, unit=unit or "", mode="log", max_age=3600)
            th[mid] = t
        src = src or SRC.get(mid, "unknown")
        if info or t.get("info") or t.get("warn") is None or t.get("crit") is None:
            metrics[mid] = dict(v=value, u=unit or t.get("unit", ""), st="info",
                                age_s=0, last_ok=iso(now), src=src, note=note)
            return
        pm = prev_metrics.get(mid, {})
        state, streak = classify(value, t, pm.get("st"), pm.get("streak", 0))
        metrics[mid] = dict(v=value, u=unit or t.get("unit", ""), st=state,
                            age_s=0, last_ok=iso(now), src=src, note=note,
                            streak=streak)

    def staleness_pass():
        """Any metric with no fresh reading this run keeps its last value and its
        age climbs. Past max_age it is CRIT: an empty result is a refusal."""
        for mid, t in th.items():
            if mid.startswith("_") or mid in metrics:
                continue
            pm = prev_metrics.get(mid)
            max_age = t.get("max_age", 3600)
            if pm is None:
                metrics[mid] = dict(v=None, u=t.get("unit", ""), st="nodata",
                                    age_s=None, last_ok=None,
                                    src=SRC.get(mid, "unknown"),
                                    note="never measured" +
                                         (f" ({errors.get(mid)})" if errors.get(mid) else ""))
                continue
            age = int((now - (parse_iso_loose(pm.get("last_ok")) or now)).total_seconds())
            e = errors.get(mid, "not collected this run")
            if age > max_age:
                st, note = "crit", f"reading stopped arriving ({e})"
            else:
                st, note = "nodata", e
            metrics[mid] = dict(v=pm.get("v"), u=pm.get("u", t.get("unit", "")),
                                st=st, age_s=age, last_ok=pm.get("last_ok"),
                                src=pm.get("src") or SRC.get(mid, "unknown"),
                                note=note, streak=0)

    # --- host pressure ------------------------------------------------------
    if "proc" in c:
        p = c["proc"]
        facts["nproc"] = os.cpu_count() or 1
        facts["mem_total_gib"] = p["mem_total_gib"]
        facts["mem_available_gib"] = p["mem_available_gib"]
        emit("psi_io_full_avg60", p.get("io_full_avg60"), "%", None,
             f"some avg10={p.get('io_some_avg10')} avg60={p.get('io_some_avg60')} "
             f"avg300={p.get('io_some_avg300')}")
        emit("psi_io_full_avg300", p.get("io_full_avg300"), "%", None,
             f"full avg10={p.get('io_full_avg10')} some avg300={p.get('io_some_avg300')}")
        emit("psi_cpu_some_avg60", p.get("cpu_some_avg60"), "%", None,
             f"cpu some avg10={p.get('cpu_some_avg10')} avg300={p.get('cpu_some_avg300')} "
             f"full avg10={p.get('cpu_full_avg10')}")
        n = facts["nproc"]
        emit("load_per_cpu", round(p["load1"] / n, 3), "", None,
             f"load1={p['load1']} nproc={n}")
        swap_total = p.get("swap_total_kb") or 0
        if swap_total > 0:
            used = swap_total - (p.get("swap_free_kb") or 0)
            emit("swap_used_pct", round(100.0 * used / swap_total, 2), "%", None,
                 f"{(used // 1024)} MiB of {(swap_total // 1024)} MiB swap in use; "
                 f"MemAvailable={p['mem_available_gib']} GiB of {p['mem_total_gib']} GiB")
        else:
            errors["swap_used_pct"] = "this host has no swap configured"

    if "dstate" in c:
        cur = c["dstate"]
        prev_map = prev.get("dstate_first_seen", {})
        new_map = {}
        t = time.time()
        for pid, comm in cur.items():
            first = prev_map.get(pid, [t, comm])[0] if pid in prev_map else t
            new_map[pid] = [first, comm]
        ages = {pid: int(t - v[0]) for pid, v in new_map.items()}
        max_age = max(ages.values()) if ages else 0
        oldest = max(ages, key=ages.get) if ages else None
        facts["dstate_first_seen"] = new_map
        emit("dstate_count", len(cur), "",
             "ps -eo stat,pid,comm",
             (f"oldest: pid {oldest} {new_map[oldest][1]} in D for {max_age}s")
             if oldest else "none")
        emit("dstate_max_age_s", float(max_age), "s",
             "ps -eo stat,pid,comm (monitor-observed)",
             "age is time continuously observed in D by this monitor; the kernel "
             "does not expose true D-time")
    else:
        facts["dstate_first_seen"] = {}

    # --- disk space ---------------------------------------------------------
    backup_active = bool((c.get("offsite") or {}).get("running"))
    backup_note = ("authority-offsite-backup.sh is RUNNING, which legitimately "
                   "drives device utilisation and transiently the free space; "
                   "the reading is still shown in the note"
                   if backup_active else "")
    if "filesystems" in c:
        fs = c["filesystems"]
        root = fs["/"]
        if backup_active:
            metrics["disk_used_pct"] = dict(
                v=root["pct"], u="%", st="info", age_s=0, last_ok=iso(now),
                src="df -P -k /", note=(backup_note + f" (used={root['pct']}%, "
                f"avail={round(root['avail_kb'] / 1048576.0, 2)} GiB)"), streak=0)
        else:
            emit("disk_used_pct", root["pct"], "%", "df -P -k /",
                 f"{root['used_kb'] // 1048576} GiB used of "
                 f"{root['total_kb'] // 1048576} GiB on {root['source']}")
        free_gib = round(root["avail_kb"] / 1048576.0, 3)
        facts["disk_free_gib"] = free_gib
        emit("disk_free_deficit_gb", round(max(0.0, 10.0 - free_gib), 3), "GiB",
             "df -P -k /",
             f"{free_gib} GiB free (warn below 8 GiB, crit below 4 GiB). "
             + backup_note)
        tmp = fs.get("/tmp")
        if tmp is not None:
            emit("tmp_used_pct", tmp["pct"], "%", "df -P -k /tmp",
                 f"/tmp is a {tmp['total_kb'] // 1048576} GiB tmpfs on "
                 f"{tmp['source']}, {tmp['used_kb'] // 1024} MiB used")

    # --- device utilisation from the io_ticks delta -------------------------
    # MEASURED DEFECT IN THE OFFICE FILE, FIXED HERE. Its own monitor.log on
    # secratary shows `disk_util_pct ... reading stopped arriving (no usable
    # previous io_ticks sample)` with an age of 140,038 s: the baseline was only
    # written inside the branch that required a baseline to already exist, so on a
    # fresh install it was never captured and the metric could never be computed
    # after the first run. The baseline is now advanced unconditionally when the
    # collector succeeded, and only the PREVIOUS baseline is used for the delta.
    if "diskstats" in c:
        cur = c["diskstats"]
        prev_ds = prev.get("diskstats") or {}
        prev_t = prev.get("diskstats_at")
        t = time.time()
        dt_ms = ((t - prev_t) * 1000.0) if prev_t else None
        if prev_ds and dt_ms is not None and dt_ms >= 10000:
            utils = {}
            for dev, ticks in cur.items():
                if dev in prev_ds and ticks >= prev_ds[dev]:
                    utils[dev] = round(100.0 * (ticks - prev_ds[dev]) / dt_ms, 2)
            if utils:
                worst = max(utils, key=utils.get)
                note = f"busiest {worst} over {int(dt_ms / 1000)}s; all: " + ", ".join(
                    f"{k}={v}%" for k, v in sorted(utils.items()))
                if backup_active:
                    metrics["disk_util_pct"] = dict(
                        v=utils[worst], u="%", st="info", age_s=0,
                        last_ok=iso(now), src="/proc/diskstats (io_ticks delta)",
                        note=backup_note + " " + note, streak=0)
                else:
                    emit("disk_util_pct", utils[worst], "%",
                         "/proc/diskstats (io_ticks delta)", note)
        facts["diskstats"] = dict(cur)
        facts["diskstats_at"] = t
        if "disk_util_pct" not in metrics:
            errors.setdefault("disk_util_pct",
                              "no usable previous io_ticks sample yet (first reading "
                              "after install, or the previous gap was under 10 s); the "
                              "baseline has been advanced, so the next run can measure it")
    else:
        # The collector failed. Keep the previous baseline AND its timestamp, so the
        # metric goes stale and CRITs through max_age instead of silently re-anchoring.
        facts["diskstats"] = prev.get("diskstats", {})
        facts["diskstats_at"] = prev.get("diskstats_at")

    # --- the authority database --------------------------------------------
    if "dbstat" in c:
        ds = c["dbstat"]
        nbytes = ds["db"]["bytes"]
        gib = round(nbytes / 2 ** 30, 3)
        emit("authority_db_gib", gib, "GiB", None,
             f"{DB_PATH} mtime "
             f"{iso(datetime.fromtimestamp(ds['db']['mtime'], timezone.utc))}")

        # Shrink: always against the IMMEDIATELY previous reading, whatever the gap.
        prev_bytes = prev.get("authority_db_bytes")
        if prev_bytes is None:
            errors["authority_db_shrink_mb"] = "no previous size reading"
        else:
            emit("authority_db_shrink_mb",
                 round(max(0.0, prev_bytes - nbytes) / 1048576.0, 3), "MB", None,
                 f"previous size {prev_bytes} B at "
                 f"{iso(datetime.fromtimestamp(prev.get('authority_db_bytes_at') or time.time(), timezone.utc))}; "
                 f"delta {nbytes - prev_bytes:+d} B")

        # Growth RATE: needs a >=600 s interval, so it gets its OWN anchor that is
        # advanced ONLY when a rate is actually emitted. Anchoring on the previous
        # run would make the interval permanently ~120 s and the rate permanently
        # unmeasurable — the same self-resetting-baseline defect as disk_util_pct.
        anchor_b = prev.get("growth_anchor_bytes")
        anchor_t = prev.get("growth_anchor_at")
        if anchor_b is None or anchor_t is None:
            facts["growth_anchor_bytes"] = nbytes
            facts["growth_anchor_at"] = time.time()
            errors["authority_db_growth_mb_h"] = "no growth anchor yet (first reading)"
        else:
            gap_s = time.time() - float(anchor_t)
            if gap_s < 600:
                facts["growth_anchor_bytes"] = anchor_b
                facts["growth_anchor_at"] = anchor_t
                errors["authority_db_growth_mb_h"] = (
                    f"growth anchor is only {int(gap_s)}s old (needs 600s)")
            else:
                emit("authority_db_growth_mb_h",
                     round((nbytes - anchor_b) / 1048576.0 / (gap_s / 3600.0), 2),
                     "MB/h", None,
                     f"{nbytes - anchor_b:+d} B over {gap_s / 60:.1f} min "
                     f"(anchor {anchor_b} B)")
                facts["growth_anchor_bytes"] = nbytes
                facts["growth_anchor_at"] = time.time()

        facts["authority_db_bytes"] = nbytes
        facts["authority_db_bytes_at"] = time.time()
        wal = ds.get("wal")
        if wal:
            emit("authority_wal_mb", round(wal["bytes"] / 2 ** 20, 2), "MB", None,
                 f"{DB_PATH}-wal {wal['bytes']} B; shm="
                 f"{(ds.get('shm') or {}).get('bytes')}")
        else:
            errors["authority_wal_mb"] = f"no {DB_PATH}-wal on disk"

    # --- the application process -------------------------------------------
    if "api" in c:
        a = c["api"]
        # PROVENANCE FIX 2026-10-14: this said `systemctl show company-api.service`,
        # which yields the cgroup's MemoryCurrent (RSS **plus reclaimable page cache**).
        # The VALUE emitted is the MainPID's VmRSS read from /proc — a different
        # quantity, and on 2026-10-14T17:14:03Z they disagreed threefold
        # (api_rss_gib=0.835 vs cgroup_current=2.848 GiB). A `src` that names the wrong
        # meter is how a reader rebuilds the wrong series with full confidence; the
        # estate has already paid for that failure class once (journal P3). The label
        # now says what was actually read.
        src = (f"VmRSS /proc/<MainPID>/status (MainPID from systemctl show {API_UNIT}); "
               f"cgroup MemoryCurrent reported separately in the note")
        cur = a.get("MemoryCurrent")
        peak = a.get("MemoryPeak")
        try:
            cgroup_gib = round(int(cur) / 2 ** 30, 3)
        except (TypeError, ValueError):
            cgroup_gib = None
        cur_gib, rss_err = proc_rss_gib(a.get("MainPID"))
        try:
            peak_gib = round(int(peak) / 2 ** 30, 3)
        except (TypeError, ValueError):
            peak_gib = None
        if cur_gib is None:
            errors["api_rss_gib"] = f"MainPID={a.get('MainPID')!r} VmRSS unreadable: {rss_err}"
        else:
            emit("api_rss_gib", cur_gib, "GiB", src,
                 f"ActiveState={a.get('ActiveState')} SubState={a.get('SubState')} "
                 f"MainPID={a.get('MainPID')} NRestarts={a.get('NRestarts')} "
                 f"cgroup_current={cgroup_gib} GiB "
                 f"MemoryPeak={peak_gib} GiB MemoryMax={a.get('MemoryMax')} "
                 f"started {a.get('ExecMainStartTimestamp')}")
        if peak_gib is not None:
            emit("api_peak_gib", peak_gib, "GiB", src,
                 f"peak since the unit started; current {cur_gib} GiB",
                 info=True)
        metrics["api_memmax_infinite"] = dict(
            v=(a.get("MemoryMax") == "infinity"), u="", st="info", age_s=0,
            last_ok=iso(now), src=src,
            note=("MemoryMax is infinity: nothing confines this process to its own "
                  "cgroup, so under pressure the kernel's GLOBAL OOM killer picks "
                  "a victim from the whole box. That is what happened at "
                  "2026-10-11 05:47:24Z and it chose company-api.")
            if a.get("MemoryMax") == "infinity" else
            f"MemoryMax={a.get('MemoryMax')} — a ceiling is configured")
        metrics["api_restarts"] = dict(
            v=a.get("NRestarts"), u="", st="info", age_s=0, last_ok=iso(now),
            src=src, note=f"Result={a.get('Result')}")

    if "oom" in c:
        o = c["oom"]
        facts["oom"] = o
        emit("oom_kills_24h", float(o["kills"]), "", "journalctl -k --since -24h",
             f"{o['kills']} 'Killed process' and {o['oom_events']} 'oom-kill:' "
             f"line(s) in 24h"
             + (f"; last: {o['sample']}" if o["sample"] else "")
             + (" [cached reading]" if facts.get("oom_cached") else ""))

    # --- the offsite copy ---------------------------------------------------
    if "offsite" in c:
        o = c["offsite"]
        running = o.get("running")
        # THE MARKER IS ABSENT BETWEEN RUNS, AND THAT IS THE NORMAL STATE. Measured 2026-10-11: this
        # metric reported CRIT "reading stopped arriving (/var/lib/authority-backup/running: No such
        # file or directory)" at a moment when the backup was IDLE AND HEALTHY - it had finished a
        # verified run and its daily timer was 20 hours away. A monitor that cries wolf on the healthy
        # state is worse than no monitor: it teaches a reader to ignore the one metric that matters.
        if o.get("running_err") and not running:
            facts["offsite_running"] = None
            emit("offsite_running_stale", 0.0, "",
                 OFFSITE_RUNNING, "no backup run in flight (the marker is absent, which is normal between runs)")
        elif o.get("running_err"):
            errors["offsite_running_stale"] = o["running_err"]
        elif not running:
            facts["offsite_running"] = None
            emit("offsite_running_stale", 0.0, "",
                 OFFSITE_RUNNING, "no backup run in flight (the marker is absent, which is normal between runs)")
        else:
            age = int(now.timestamp()) - int(running.get("started_at_epoch") or
                                             _file_mtime(OFFSITE_RUNNING) or
                                             now.timestamp())
            facts["offsite_running"] = running
            emit("offsite_running_stale", 1.0 if age > 4 * 3600 else 0.0, "",
                 OFFSITE_RUNNING,
                 f"a run has been in flight since {running.get('started_at')} "
                 f"({age}s, pid {running.get('pid')}, source "
                 f"{running.get('source_bytes')} B)")
        last = o.get("last_run")
        if o.get("last_run_err"):
            errors["offsite_lastrun_age_h"] = o["last_run_err"]
            errors["offsite_lastrun_not_ok"] = o["last_run_err"]
        else:
            fin = parse_iso_loose(last.get("finished_at"))
            if fin is None:
                errors["offsite_lastrun_age_h"] = (
                    f"no parseable finished_at in {OFFSITE_LAST_RUN}: "
                    f"{last.get('finished_at')!r}")
            else:
                emit("offsite_lastrun_age_h",
                     round((now - fin).total_seconds() / 3600.0, 3), "h",
                     OFFSITE_LAST_RUN,
                     f"status={last.get('status')} "
                     f"database_sent={last.get('database_sent')} "
                     f"database_verified={last.get('database_verified')}")
            emit("offsite_lastrun_not_ok",
                 0.0 if last.get("status") == "ok" else 1.0, "",
                 OFFSITE_LAST_RUN,
                 f"status={last.get('status')!r} "
                 f"(the copy that survives the machine)")

        # The SECOND leg (/opt/company/data). Mirrors the block above exactly, on purpose: the
        # defect being fixed is that this file asked its three offsite questions of one leg.
        data = o.get("data_last_run")
        if o.get("data_last_run_err"):
            errors["offsite_data_lastrun_age_h"] = o["data_last_run_err"]
            errors["offsite_data_lastrun_not_ok"] = o["data_last_run_err"]
        else:
            dfin = parse_iso_loose(data.get("finished_at"))
            if dfin is None:
                errors["offsite_data_lastrun_age_h"] = (
                    f"no parseable finished_at in {OFFSITE_DATA_LAST_RUN}: "
                    f"{data.get('finished_at')!r}")
            else:
                emit("offsite_data_lastrun_age_h",
                     round((now - dfin).total_seconds() / 3600.0, 3), "h",
                     OFFSITE_DATA_LAST_RUN,
                     f"status={data.get('status')} entries={data.get('entries')} "
                     f"archive_bytes={data.get('archive_bytes')}")
            emit("offsite_data_lastrun_not_ok",
                 0.0 if data.get("status") == "ok" else 1.0, "",
                 OFFSITE_DATA_LAST_RUN,
                 f"status={data.get('status')!r} "
                 f"(the /opt/company/data copy: family_chat.db, agent_identities.json, dialpad)")

    # --- the vault: outside this box ---------------------------------------
    if "remote" in c:
        r = c["remote"]
        facts["vault_host"] = r.get("host")
        facts["remote_cached"] = facts.get("remote_cached", False)
        files = r.get("files", {})
        suffix = " [cached reading]" if facts.get("remote_cached") else ""

        aj = files.get(VAULT_OFFSITE_JSON)
        if aj is None or aj.get("json") is None:
            errors["offsite_object_age_h"] = (
                f"{VAULT_OFFSITE_JSON} missing or unparseable on {VAULT_HOST}")
        else:
            j = aj["json"]
            ts = parse_iso_loose(j.get("last_modified"))
            if ts is None:
                errors["offsite_object_age_h"] = (
                    f"{VAULT_OFFSITE_JSON} has no usable last_modified: {j}")
            else:
                emit("offsite_object_age_h",
                     round((now - ts).total_seconds() / 3600.0, 3), "h",
                     VAULT_OFFSITE_JSON + " @ " + VAULT_HOST,
                     f"R2 key={j.get('key')} bytes={j.get('bytes')} "
                     f"reported_at={j.get('reported_at')} by={j.get('reported_by')}"
                     + (f" ERROR={j.get('error')}" if j.get("error") else "")
                     + suffix)

        pr = r.get("probe") or {}
        code = str(pr.get("code", "000"))
        facts["public_probe"] = pr
        hb = files.get(VAULT_HEARTBEAT_JSON)
        hb_code = None
        if hb and hb.get("json"):
            hb_code = hb["json"].get("http_code")
            facts["vault_heartbeat"] = {
                "ok": hb["json"].get("ok"),
                "http_code": hb_code,
                "consecutive_failures": hb["json"].get("consecutive_failures"),
                "checked_at": hb["json"].get("checked_at"),
                "last_outage_seconds": hb["json"].get("last_outage_seconds"),
                "last_recovery_at": hb["json"].get("last_recovery_at"),
            }
        xnote = (f"probe from {r.get('host')} (OUTSIDE this box); "
                 f"ttfb={pr.get('ttfb_ms')}ms total={pr.get('total_ms')}ms; "
                 f"vault heartbeat http_code={hb_code}"
                 + (f" checked_at={facts.get('vault_heartbeat', {}).get('checked_at')}"
                    if hb_code else ""))
        if hb_code is not None and str(hb_code) != code:
            xnote += f" -- DISAGREES with the vault's own heartbeat ({hb_code} vs {code})"
        xnote += suffix
        emit("public_health_status", 1.0 if code != "200" else 0.0, "",
             f"curl @ {VAULT_HOST} (outside this box)", xnote)
        if pr.get("ttfb_ms") is not None:
            emit("public_health_ttfb_ms", pr["ttfb_ms"], "ms",
                 f"curl @ {VAULT_HOST} (outside this box)", xnote)

    # --- the dead-man switch, both sides ------------------------------------
    if "deadman" in c:
        dm = c["deadman"]
        ext = dm.get("external")
        if ext is None:
            errors["deadman_check_lapse"] = dm.get("external_err") or \
                "no external verdict available"
            errors["deadman_ping_age_s"] = dm.get("external_err") or \
                "no external verdict available"
        else:
            status = (ext.get("status") or "unknown").lower()
            lapse = {"up": 0.0, "grace": 1.0, "late": 1.0}.get(status, 2.0)
            src_hc = "healthchecks.io /api/v3/checks/ (check 'secratary authority alive')"
            emit("deadman_check_lapse", lapse, "", src_hc,
                 f"status={status} timeout={ext.get('timeout')}s "
                 f"grace={ext.get('grace')}s next_ping={ext.get('next_ping')} "
                 f"n_pings={ext.get('n_pings')} "
                 f"({ext.get('external_cached_reading', '')})"
                 + (" [cached reading]" if facts.get("deadman_cached") else ""))
            lp = parse_iso_loose(ext.get("last_ping"))
            if lp is None:
                errors["deadman_ping_age_s"] = \
                    f"no parseable last_ping: {ext.get('last_ping')!r}"
            else:
                emit("deadman_ping_age_s",
                     round((now - lp).total_seconds(), 1), "s", src_hc,
                     f"last_ping={ext.get('last_ping')} status={status}"
                     + (" [cached reading]" if facts.get("deadman_cached") else ""))

        loc = dm.get("local")
        if loc is None:
            errors["deadman_local_run_age_s"] = dm.get("local_err") or "unreadable"
            errors["deadman_local_last_ok"] = dm.get("local_err") or "unreadable"
        else:
            src_l = f"systemctl show {DEADMAN_UNIT}"
            ex_ts = parse_systemd_ts(loc.get("ExecMainExitTimestamp"))
            if ex_ts is None:
                errors["deadman_local_run_age_s"] = (
                    f"no ExecMainExitTimestamp ({DEADMAN_UNIT} has not finished a "
                    f"run yet, ActiveState={loc.get('ActiveState')})")
            else:
                emit("deadman_local_run_age_s",
                     round((now - ex_ts).total_seconds(), 1), "s", src_l,
                     f"last finished {loc.get('ExecMainExitTimestamp')} "
                     f"Result={loc.get('Result')} "
                     f"ExecMainStatus={loc.get('ExecMainStatus')}")
            try:
                ok = int(loc.get("ExecMainStatus") or 0) == 0 and \
                    loc.get("Result") == "success"
            except (TypeError, ValueError):
                ok = False
            emit("deadman_local_last_ok", 0.0 if ok else 1.0, "", src_l,
                 f"Result={loc.get('Result')} "
                 f"ExecMainStatus={loc.get('ExecMainStatus')} — the dead-man script "
                 f"always exits 0 when it can ping or cannot, so this is the only "
                 f"local evidence that the timer is still alive")

    # --- self: gap since the previous run ----------------------------------
    gap = None
    if prev.get("generated_epoch"):
        gap = round(time.time() - prev["generated_epoch"], 1)
    if gap is None:
        errors["monitor_run_gap_s"] = "no previous run recorded (first run)"
    else:
        emit("monitor_run_gap_s", gap, "s", "self",
             f"previous run {prev.get('generated_at')}")

    staleness_pass()

    # --- verdict ------------------------------------------------------------
    counts = {"ok": 0, "info": 0, "nodata": 0, "warn": 0, "crit": 0}
    worst = 0
    for m in metrics.values():
        counts[m["st"]] = counts.get(m["st"], 0) + 1
        worst = max(worst, STATE_RANK.get(m["st"], 0))
    verdict = {0: "ok", 1: "degraded", 2: "degraded", 3: "critical"}[worst]
    if counts["crit"] == 0 and counts["warn"] == 0 and counts["nodata"] > 0:
        verdict = "degraded" if verdict == "ok" else verdict

    # --- escalation: exactly one condition may wake anyone ------------------
    escalated, rate_limited = [], []
    notified = dict(prev.get("notified", {}))
    interval = int(os.environ.get("ESTATE_MONITOR_NOTIFY_INTERVAL", "3600"))
    for mid, m in metrics.items():
        t = th.get(mid) or {}
        if t.get("mode") != "alert" or m["st"] != "crit":
            continue
        last = notified.get(mid)
        if last and (time.time() - last) < interval:
            rate_limited.append(mid)
            continue
        escalated.append(mid)
        notified[mid] = time.time()
        line = (f"[{iso(now)}] ESCALATE {mid}={m['v']} {m['u']} "
                f"(warn={t.get('warn')} crit={t.get('crit')} unit={t.get('unit')}) "
                f"src={m['src']} age={m['age_s']}s -- {m.get('note', '')}")
        try:
            with open(ALERTS_PATH, "a") as f:
                f.write(json.dumps({
                    "at": iso(now), "metric": mid, "value": m["v"],
                    "unit": m["u"], "state": m["st"], "src": m["src"],
                    "age_s": m["age_s"], "note": m.get("note", ""),
                    "transport": "syslog-only, no outbound message"}) + "\n")
        except OSError:
            pass
        if not args.no_alert:
            run(["logger", "-p", "daemon.err", "-t", "estate-monitor", line],
                timeout=10)
            try:
                with open(ESCALATION_PATH, "w") as f:
                    f.write(line + "\n")
            except OSError:
                pass
    if args.no_alert:
        escalated, rate_limited = [], []

    duration = round(time.time() - started, 2)
    state = {
        "generated_at": iso(now),
        "generated_epoch": time.time(),
        "host": socket.gethostname(),
        "verdict": verdict,
        "counts": counts,
        "metrics_total": len(metrics),
        "run_duration_s": duration,
        "escalated_this_run": escalated,
        "rate_limited_this_run": rate_limited,
        "alerting": {
            "mode": "log-only except company-unreachable-from-outside",
            "escalation_transport": "syslog(daemon.err) + alerts.jsonl + ESCALATED "
                                    "file. NO outbound message of any kind; this "
                                    "monitor cannot text, email or call anyone.",
            "notify_min_interval_s": interval,
            "conditions_allowed_to_escalate": ["public_health_status", "disk_free_deficit_gb"],
        },
        "thresholds": {k: [v.get("warn"), v.get("crit"), v.get("unit", ""),
                           v.get("mode", "log"), v.get("max_age"),
                           v.get("for_runs", 1)]
                       for k, v in th.items() if not k.startswith("_")},
        "thresholds_override_file": th.get("_override"),
        "metrics": metrics,
        "facts": facts,
        "errors": errors,
        "notified": notified,
        "events": prev.get("events", {}),
        "oom_cache": prev.get("oom_cache", {}),
        "remote_cache": prev.get("remote_cache", {}),
        "deadman_cache": prev.get("deadman_cache", {}),
        "dstate_first_seen": facts.get("dstate_first_seen", {}),
        "diskstats": facts.get("diskstats", {}),
        "diskstats_at": facts.get("diskstats_at"),
        "authority_db_bytes": facts.get("authority_db_bytes"),
        "authority_db_bytes_at": facts.get("authority_db_bytes_at"),
        "growth_anchor_bytes": facts.get("growth_anchor_bytes"),
        "growth_anchor_at": facts.get("growth_anchor_at"),
    }
    for dup in ("dstate_first_seen", "diskstats", "diskstats_at"):
        state["facts"].pop(dup, None)
    save_json(STATE_PATH, state)

    order = sorted(metrics.items(),
                   key=lambda kv: (-STATE_RANK.get(kv[1]["st"], 0), kv[0]))

    def fmt(v, u):
        if v is None:
            return "n/a"
        if isinstance(v, bool):
            return "true" if v else "false"
        return f"{v}{u}"

    lines = [f"estate-monitor: verdict={verdict.upper()} "
             f"ok={counts['ok']} info={counts['info']} warn={counts['warn']} "
             f"crit={counts['crit']} nodata={counts['nodata']} "
             f"metrics={len(metrics)} escalated={len(escalated)} "
             f"gap={gap}s dur={duration}s host={state['host']}"]
    for mid, m in order:
        if m["st"] in ("ok", "info"):
            continue
        t = th.get(mid) or {}
        age = "n/a" if m["age_s"] is None else f"{m['age_s']}s"
        trig = ""
        if t.get("crit") is not None:
            trig = f" (warn>={t.get('warn')} crit>={t.get('crit')}"
            if t.get("for_runs", 1) > 1:
                trig += f" for_runs={t['for_runs']}"
            trig += ")"
        lines.append(f"estate-monitor: {m['st'].upper()} {mid}={fmt(m['v'], m['u'])}"
                     f"{trig} age={age} src={m['src']} -- {m.get('note', '')}")
    text = "\n".join(lines)

    try:
        with open(LOG_PATH, "a") as f:
            f.write(text + "\n")
    except OSError:
        pass
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(f"{iso(now)}\t{verdict}\t{counts['crit']}crit "
                    f"{counts['warn']}warn {counts['nodata']}nodata\t"
                    f"dur={duration}s\n")
    except OSError:
        pass
    print(text)

    if args.json:
        print(json.dumps(state, indent=1))
    return 0


def _file_mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


if __name__ == "__main__":
    sys.exit(main())
