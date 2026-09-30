#!/usr/bin/env python3
"""Wire the external dead-man switch: a check that shouts when the authority itself stops.

WHY THIS EXISTS. Every heartbeat this system keeps is read by something ON the authority. If the authority
dies, its own health checks die with it, and the owner learns nothing - the operation's oldest failure is
reading a live-looking thing as work-happening. An external check is the only mechanism that can report the
authority being dead, because the report does not come from the authority.

MEASURED 2026-09-30: the owner's account carries one check, "My First Check", status new, n_pings 0, never
pinged. The 20-character string supplied as a ping key answers HTTP 400 invalid url format, so it was never
a usable ping key; the API key works and is what creates and reads the real check.

WHAT IT DOES
  --setup   create the check if absent (period 900s, grace 300s, all notification channels), store the ping
            URL in a 600 file, ping once, and print the resulting status. Idempotent by name.
  default   read the stored ping URL and ping it, with a short body carrying what the authority currently
            believes, so an alert arrives with context rather than as a bare failure.
  --fail    ping the same check's /fail endpoint, for a condition the authority knows is bad.

Never prints a credential. Exit 0 always - a dead-man switch that breaks its own caller is worse than none.
"""
import json
import os
import stat
import sys
import urllib.error
import urllib.request

API = os.environ.get("HEALTHCHECKS_API_KEY") or ""
NAME = "secratary authority alive"
PERIOD, GRACE = 900, 300
ENVF = "/home/zabz/.sms-inbox/deadman.env"


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
    code = ping_it(ping + "?create=1", "setup ping from the authority")
    print("%s check %s (period %ss grace %ss); stored in %s (600); first ping http %s"
          % ("created" if created else "existing", c.get("slug"), c.get("timeout"), c.get("grace"),
             ENVF, code))
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
    import sqlite3
    out = []
    try:
        c = sqlite3.connect("file:%s?mode=ro" % os.path.expanduser("~/.sms-inbox/inbox.db"), uri=True,
                            timeout=10)
        st = dict(c.execute("select state, count(*) from wake group by state").fetchall())
        c.close()
        out.append("wake=" + ",".join("%s:%s" % (k, v) for k, v in sorted(st.items())))
    except Exception as exc:
        out.append("wake=unreadable(%s)" % type(exc).__name__)
    try:
        import subprocess
        p = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, timeout=15).stdout
        out.append("dispatch_procs=%d" % p.count("bash /home/zabz/bin/wake-dispatch.sh"))
    except Exception:
        pass
    return " ".join(out) or "alive"


def main():
    if "--setup" in sys.argv:
        return setup()
    ping = load()
    if not ping:
        print("no stored ping URL - run --setup first")
        return 0
    if "--fail" in sys.argv:
        print("fail ping http %s" % ping_it(ping + "/fail", "reported bad: " + body_now()))
        return 0
    print("ping http %s :: %s" % (ping_it(ping, body_now()), body_now()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
