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

Never prints a credential. Exit 0 always - a dead-man switch that breaks its own caller is worse
than none.
"""
import datetime
import json
import os
import sqlite3
import stat
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

def freshness_verdict():
    """(ok, reason). A backup older than STALE_SECONDS, or one whose last run failed, makes the
    EXTERNAL check fail rather than silently staying green: a switch that only reports "the box is
    powered on" cannot see the thing this box exists to do."""
    import time
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
