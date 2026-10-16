#!/usr/bin/env python3
"""Ping the EXTERNAL dead-man switch (healthchecks.io) from the authority itself.

Ported from `secratary:~zabz/bin/deadman.py` at the 2026-10-11 cutover rather than rebuilt: the
check "secratary authority alive" (period 900 s, grace 300 s) already existed and had been
alarming since 04:00:06Z, because the check is driven by a cron job and cron is exactly what the
freeze masked. An external check is the ONLY mechanism that can report the authority being dead,
because the report does not come from the authority.

WHAT CHANGED IN THE PORT: the ping body used to describe the office wake queue. It now describes
what THIS authority believes - the offsite backup's own last-run, and whether a run is in flight -
so an alert arrives with context rather than as a bare failure.

2026-10-16 - THE SECOND OFFSITE LEG, AND SYSTEMD'S OWN FAILURE LIST (P-THE-DATA-LEG-BLIND-SPOT)
Measured on 2026-10-16: `authority-data-offsite.service` (the /opt/company/data copy, ~4 GB, to
`authority/data/authority-data.tar.gz`) refused to start at 06:39:28Z - `exit 3`, its log line
`FATAL: only 1582332 KiB free under /var/tmp; refusing to start` - and then did not run again for
14 h. **This switch stayed GREEN through all of it**, and so did every other monitor, because
`freshness_verdict()` read `/var/lib/authority-backup/last-run` - the DATABASE leg - and nothing on
this box read `/var/lib/authority-backup/data-last-run` at all. Measured in the same minute: R2
`authority/secretary.db.gz` age 14.96 h (`estate-monitor` said `offsite_object_age_h ... st=ok`)
while `authority/data/authority-data.tar.gz` was **38.16 h** stale. Three monitors, one object
between them, and it was the wrong object - the defect this file's own docstring names, one layer
down from where it was written.

So this switch now also asks the two questions that would have caught it:
  * `systemctl is-failed` on BOTH offsite units. The 16th's run was sitting in `systemctl --failed`
    for 14 hours and no monitor read systemd's own failure list. This is the immediate signal, and
    it needs no new state file and no change to the writer.
  * the `/opt/company/data` leg's own evidence, `data-last-run`, against a 27 h limit (its producer
    is daily at 06:30 UTC + up to 10 min jitter and takes ~12 min, so a healthy age oscillates over
    ~24.5 h; 27 h is one missed cycle plus margin). 30 h - the limit used for the database leg -
    would have told nobody until the next afternoon.

Never prints a credential. Exit 0 always - a dead-man switch that breaks its own caller is worse
than none.
"""
import datetime
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("HEALTHCHECKS_API_KEY") or ""
NAME = "secratary authority alive"
PERIOD, GRACE = 900, 300
ENVF = "/root/.sms-inbox/deadman.env"
LASTRUN = "/var/lib/authority-backup/last-run"
DEPLOYED = "/var/lib/authority-backup/deployed-at"
STALE_SECONDS = 30 * 3600

# --- the /opt/company/data offsite leg, and systemd's own failure list (2026-10-16) ------------
# Overridable so the ALARM CAN BE TESTED without touching the live evidence of the last good
# backup. `a monitor that has never fired is not a monitor`: plant a stale file in /tmp, point
# DEADMAN_DATA_LASTRUN at it, and watch the verdict flip - the real data-last-run is never edited.
DATA_LASTRUN = os.environ.get("DEADMAN_DATA_LASTRUN",
                              "/var/lib/authority-backup/data-last-run")
DATA_STALE_SECONDS = int(os.environ.get("DEADMAN_DATA_STALE_SECONDS", 27 * 3600))
DATA_UNIT = os.environ.get("DEADMAN_DATA_UNIT", "authority-data-offsite.service")
DB_UNIT = os.environ.get("DEADMAN_DB_UNIT", "authority-offsite-backup.service")
SYSTEMCTL = "/usr/bin/systemctl"


def api(path, method="GET", body=None):
    req = urllib.request.Request("https://healthchecks.io/api/v3" + path, method=method,
                                 headers={"X-Api-Key": API, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def find():
    for c in api("/checks/").get("checks", []):
        if c.get("name") == NAME:
            return c
    return None


def setup():
    c = find()
    created = False
    if c is None:
        c = api("/checks/", "POST", {"name": NAME, "timeout": PERIOD, "grace": GRACE,
                                     "tags": "authority,deadman", "channels": "*"})
        created = True
    ping = c.get("ping_url")
    if not ping:
        print("ERROR: no ping_url in the response - nothing written")
        return 1
    os.makedirs(os.path.dirname(ENVF), exist_ok=True)
    with open(ENVF, "w") as fh:
        fh.write("HEALTHCHECKS_PING_URL=%s\nHEALTHCHECKS_API_KEY=%s\n" % (ping, API))
    os.chmod(ENVF, stat.S_IRUSR | stat.S_IWUSR)
    print("%s check %s; stored in %s (600)"
          % ("created" if created else "existing", c.get("slug"), ENVF))
    return 0


def load():
    if os.path.exists(ENVF):
        for line in open(ENVF):
            if line.startswith("HEALTHCHECKS_PING_URL="):
                return line.split("=", 1)[1].strip()
    return None


def ping_it(url, body):
    try:
        req = urllib.request.Request(url, data=(body or "").encode(), method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:
        return "%s: %s" % (type(exc).__name__, str(exc)[:60])


def body_now():
    """What the authority currently believes, so an alert is not a bare failure."""
    out = []
    try:
        d = {}
        for line in open(LASTRUN):
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
        fin = d.get("finished_at", "")
        age = "?"
        try:
            when = datetime.datetime.strptime(fin, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
            age = "%ds" % int((datetime.datetime.now(datetime.timezone.utc) - when).total_seconds())
        except Exception:
            pass
        out.append("offsite=%s age=%s sent=%s verified=%s" % (
            d.get("status", "?"), age, d.get("database_sent", "?"), d.get("database_verified", "?")))
    except Exception as exc:
        out.append("offsite=no-last-run(%s)" % type(exc).__name__)
    # The /opt/company/data leg, so a page about it says WHAT is stale rather than only that
    # something is. Same shape as the database line above.
    try:
        d = {}
        for line in open(DATA_LASTRUN):
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
        fin = d.get("finished_at", "")
        age = "?"
        try:
            when = datetime.datetime.strptime(fin, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
            age = "%ds" % int((datetime.datetime.now(datetime.timezone.utc) - when).total_seconds())
        except Exception:
            pass
        out.append("data=%s age=%s entries=%s" % (
            d.get("status", "?"), age, d.get("entries", "?")))
    except Exception as exc:
        out.append("data=no-last-run(%s)" % type(exc).__name__)
    if os.path.exists("/var/lib/authority-backup/running"):
        out.append("backup_running=yes")
    try:
        c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True, timeout=10)
        out.append("db_tables=%d" % c.execute("select count(*) from sqlite_master").fetchone()[0])
        c.close()
    except Exception as exc:
        out.append("db=unreadable(%s)" % type(exc).__name__)
    return " ".join(out) or "alive"



RUNNING_MARKER_MAX_AGE_S = 8 * 3600


def running_marker_fresh():
    """A `running` marker must not be taken as "in flight" forever.

    The first version returned True whenever the file existed, so a run that died without cleaning up
    made the external switch stay GREEN for as long as the file remained - the estate's own oldest
    failure (a monitor that reports success while measuring nothing) reproduced inside the thing built
    to catch it. A daily job whose marker is older than eight hours is not running; it is stuck.
    """
    marker = "/var/lib/authority-backup/running"
    try:
        age = time.time() - os.path.getmtime(marker)
    except OSError:
        return False, None
    if age > RUNNING_MARKER_MAX_AGE_S:
        return False, age
    return True, age

def unit_failed(unit):
    """(failed, detail). True when systemd ITSELF is holding `unit` in the failed state.

    This is the cheapest true statement that "the run happened and did not arrive": a `Type=oneshot`
    unit that exits non-zero and whose bounded `Restart=on-failure` retries are exhausted stays
    `failed` in `systemctl --failed` until it next starts successfully. Measured 2026-10-16: the
    data leg sat there for 14 h and nothing on this box read the list.

    A unit that cannot be asked (systemctl missing, timeout, unit not found) returns (None, why) and
    is NOT treated as a failure - an unaskable question is not a fault, and this switch must never
    page on its own blind spot. It is reported in the detail string instead.
    """
    try:
        r = subprocess.run([SYSTEMCTL, "is-failed", unit],
                           capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:60])
    words = (r.stdout or "").strip()
    if words == "failed":
        return True, "failed"
    return False, words or "not-failed"


def data_freshness():
    """(ok, reason) for the /opt/company/data offsite leg - the copy nothing was watching.

    Its producer is `authority-data-offsite.service` (daily, 06:30 UTC + up to 10 min jitter, ~12 min
    of work), writing `data-last-run`. Deliberately a SEPARATE threshold from the database leg's
    30 h: 27 h is one missed cycle plus margin, so a missed data run is reported the same morning
    rather than the next afternoon.
    """
    if not os.path.exists(DATA_LASTRUN):
        return False, "data=no-last-run(%s)" % DATA_LASTRUN
    d = {}
    try:
        for line in open(DATA_LASTRUN):
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except Exception as exc:
        return False, "data=unreadable(%s)" % type(exc).__name__
    if d.get("status") != "ok":
        return False, "data=status:%s" % d.get("status")
    try:
        when = datetime.datetime.strptime(d.get("finished_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
        age = int((datetime.datetime.now(datetime.timezone.utc) - when).total_seconds())
    except Exception:
        return False, "data=unparseable-finished_at"
    if age > DATA_STALE_SECONDS:
        return False, "data=STALE age=%ds (limit %ds)" % (age, DATA_STALE_SECONDS)
    return True, "data=fresh age=%ds" % age


def freshness_verdict():
    """(ok, reason). A backup older than STALE_SECONDS, or one whose last run failed, makes the
    EXTERNAL check fail rather than silently staying green: a switch that only reports "the box is
    powered on" cannot see the thing this box exists to do.

    2026-10-16: it now also fails on systemd's own failure list for either offsite unit, and on the
    `/opt/company/data` leg going stale. It failed on none of those things on the 16th.
    """
    import time
    # The most immediate signal first: systemd says a run happened and did not arrive.
    for unit, label in ((DATA_UNIT, "data"), (DB_UNIT, "db")):
        failed, detail = unit_failed(unit)
        if failed:
            return False, "%s-unit=%s is FAILED (systemctl is-failed: %s)" % (label, unit, detail)
    # Then the leg that had no reader at all.
    ok_data, why_data = data_freshness()
    if not ok_data:
        return False, why_data
    fresh, marker_age = running_marker_fresh()
    if fresh:
        return True, "backup_running=yes"
    if marker_age is not None:
        return False, "backup_running=STALE(%ds)" % int(marker_age)
    if not os.path.exists(LASTRUN):
        try:
            age = time.time() - os.path.getmtime(DEPLOYED)
            if age > STALE_SECONDS:
                return False, "offsite=no-last-run age=%ds" % int(age)
        except Exception:
            pass
        return True, "offsite=no-last-run-yet"
    d = {}
    for line in open(LASTRUN):
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    if d.get("status") != "ok":
        return False, "offsite=status:%s sent:%s verified:%s" % (
            d.get("status"), d.get("database_sent"), d.get("database_verified"))
    try:
        when = datetime.datetime.strptime(d.get("finished_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
        age = int((datetime.datetime.now(datetime.timezone.utc) - when).total_seconds())
    except Exception:
        return False, "offsite=unparseable-finished_at"
    if age > STALE_SECONDS:
        return False, "offsite=STALE age=%ds" % age
    return True, "offsite=fresh age=%ds" % age


def main():
    if "--setup" in sys.argv:
        return setup()
    ping = load()
    if not ping:
        print("no stored ping URL - run --setup first")
        return 0
    body = body_now()
    ok, verdict = freshness_verdict()
    if "--fail" in sys.argv:
        print("fail ping http %s" % ping_it(ping + "/fail", "reported bad: " + body))
        return 0
    if not ok:
        print("fail ping http %s :: %s %s"
              % (ping_it(ping + "/fail", body + " " + verdict), body, verdict))
        return 0
    print("ping http %s :: %s %s" % (ping_it(ping, body + " " + verdict), body, verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
