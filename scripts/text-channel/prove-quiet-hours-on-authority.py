#!/usr/bin/env python3
"""prove-quiet-hours-on-authority.py - the real timezone branch, at real instants.

The guard's author could only test the FIXED-OFFSET FALLBACK (their host has no tz database).
The authority has zoneinfo, so the branch that actually governs the owner's phone is this one,
and until now nobody had run it there.

Calls the deployed `quiet_hours_now(now)` at instants whose local time is arithmetic, plus the
awake bypass through `record_inbound()` on a throwaway store.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

STORE = os.path.join(tempfile.mkdtemp(prefix="quiet_"), "relay.db")
os.environ["OWNER_TEXT_RELAY_DB"] = STORE
sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

print("store (throwaway, NOT the live relay): %s" % STORE)
try:
    import zoneinfo
    NY = zoneinfo.ZoneInfo("America/New_York")
    print("zoneinfo: AVAILABLE")
except Exception as exc:                                       # noqa: BLE001
    NY = None
    print("zoneinfo: UNAVAILABLE (%s) - fallback would be used" % exc)
print()

# 2026-10-19 is EDT (UTC-4). Instants chosen so the local time is unambiguous.
CASES = [
    ("2026-10-19T07:00:00+00:00", "03:00 local - deep in the window", True),
    ("2026-10-19T10:59:00+00:00", "06:59 local - still in", True),
    ("2026-10-19T11:00:00+00:00", "07:00 local - still in", True),
    ("2026-10-19T11:29:00+00:00", "07:29 local - last minute in", True),
    ("2026-10-19T11:30:00+00:00", "07:30 local - window CLOSES", False),
    ("2026-10-19T15:00:00+00:00", "11:00 local - he is awake", False),
    ("2026-10-19T20:00:00+00:00", "16:00 local - the shop", False),
    ("2026-10-20T02:59:00+00:00", "22:59 local - one minute before", False),
    ("2026-10-20T03:00:00+00:00", "23:00 local - window OPENS", True),
    ("2026-10-20T04:00:00+00:00", "00:00 local - midnight", True),
]
bad = 0
print("quiet_hours_now() on the deployed module")
for ts, label, want in CASES:
    now = datetime.fromisoformat(ts)
    quiet, why = R.quiet_hours_now(now)
    local = now.astimezone(NY).strftime("%H:%M") if NY else "?"
    ok = (quiet == want)
    bad += 0 if ok else 1
    print("  %-5s %s  %-38s quiet=%-5s local=%s"
          % ("ok" if ok else "FAIL", ts[11:16], label, quiet, local))
    if not ok:
        print("        want quiet=%s :: %s" % (want, why))

print()
print("the awake bypass: he texts us at 00:30, may we reply at 00:35?")
now = datetime.fromisoformat("2026-10-20T04:35:00+00:00")          # 00:35 local
quiet, _ = R.quiet_hours_now(now)
print("  before his text: quiet=%s (want True)" % quiet)
res = R.record_inbound("are you there", door="inbound", sid="SMprobe",
                       at=datetime.fromisoformat("2026-10-20T04:30:00+00:00"))
print("  record_inbound -> ok=%s" % (res or {}).get("ok"))
quiet2, why2 = R.quiet_hours_now(now)
print("  after his text : quiet=%s (want False)  %s" % (quiet2, why2))
bad += 0 if quiet2 is False else 1

print()
print("RESULT:", "PASS" if not bad else "FAIL (%d)" % bad)
raise SystemExit(0 if not bad else 1)
