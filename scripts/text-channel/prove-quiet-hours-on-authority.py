#!/usr/bin/env python3
"""prove-quiet-hours-on-authority.py - the real timezone branch, at real instants.

The guard's author could only test the FIXED-OFFSET FALLBACK (their host has no tz database).
The authority has zoneinfo, so the branch that actually governs the owner's phone is this one,
and until now nobody had run it there.

THE WINDOW IS READ FROM THE DEPLOYED MODULE.  The owner ruled on 2026-10-21, verbatim:
"quiet times are 2 am to 8 am est".  This script does not keep a second copy of 02:00-08:00:
it asks `owner_text_relay._quiet_window()` what the live module will enforce, then tests the
minute either side of those two edges.  It separately asserts that the live window is still
the ruled 02:00-08:00, so a module that drifts fails here instead of quietly redefining the
test.

Calls the deployed `quiet_hours_now(now)` at those instants, plus the awake bypass through
`_quiet_guard()` on a throwaway store.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

STORE = os.path.join(tempfile.mkdtemp(prefix="quiet_"), "relay.db")
os.environ["OWNER_TEXT_RELAY_DB"] = STORE
# This test is about the deployed defaults, not a local experiment.
os.environ.pop("OWNER_TEXT_GUARD_QUIET", None)
os.environ.pop("OWNER_TEXT_QUIET_START", None)
os.environ.pop("OWNER_TEXT_QUIET_END", None)
sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

print("store (throwaway, NOT the live relay): %s" % STORE)
try:
    import zoneinfo
    NY = zoneinfo.ZoneInfo("America/New_York")
    print("zoneinfo: AVAILABLE")
except Exception as exc:                                       # noqa: BLE001
    NY = None
    print("zoneinfo: UNAVAILABLE (%s) - the authority should not take this path" % exc)
print()

# 2026-10-19 is EDT (UTC-4). Instants chosen so the local time is unambiguous.
def local_dt(minutes_past_midnight: int) -> datetime:
    hour, minute = divmod(minutes_past_midnight, 60)
    zone = NY or timezone(timedelta(hours=-4))
    return datetime(2026, 10, 19, hour, minute, tzinfo=zone)


def hhmm(minutes_past_midnight: int) -> str:
    return "%02d:%02d" % divmod(minutes_past_midnight, 60)


bad = 0
start_min, end_min, problem = R._quiet_window()
print("live window from owner_text_relay._quiet_window(): %s-%s America/New_York%s"
      % (hhmm(start_min or 0), hhmm(end_min or 0),
         "" if not problem else "  PROBLEM: %s" % problem))
if problem or start_min is None or end_min is None:
    print("FAIL  the live module's quiet window is unreadable")
    bad += 1
elif (start_min, end_min) != (2 * 60, 8 * 60):
    print("FAIL  live window is %s-%s; the owner's 2026-10-21 ruling is 02:00-08:00"
          % (hhmm(start_min), hhmm(end_min)))
    bad += 1
else:
    print("ok    live window is the ruled 02:00-08:00")

cases = []
if start_min is not None and end_min is not None and not problem and start_min != end_min:
    # The five required assertions, generated from the live edges rather than copied.
    cases = [
        (start_min - 1, False, "01:59 local - one minute before OPEN"),
        (start_min + 1, True, "02:01 local - one minute after OPEN"),
        (end_min - 1, True, "07:59 local - one minute before CLOSE"),
        (end_min + 1, False, "08:01 local - one minute after CLOSE"),
        (23 * 60 + 30, False, "23:30 local - outside since the 2026-10-21 ruling"),
    ]

print()
print("quiet_hours_now() on the deployed module")
for minutes, want, label in cases:
    now = local_dt(minutes).astimezone(timezone.utc)
    quiet, why = R.quiet_hours_now(now)
    ok = (quiet == want)
    bad += 0 if ok else 1
    print("  %-5s %s  %-52s quiet=%-5s local=%s"
          % ("ok" if ok else "FAIL", now.strftime("%H:%MZ"), label, quiet,
             hhmm(minutes)))
    if not ok:
        print("        want quiet=%s :: %s" % (want, why))

print()
print("the awake bypass: he texts us at 02:25, may we reply at 02:30?")
conn = R.connect(STORE)
try:
    now = local_dt(start_min + 30) if start_min is not None else local_dt(2 * 60 + 30)
    hit, notes = R._quiet_guard(conn, now, "normal", "", "", "")
    print("  before his text: quiet_guard hit=%r (want a hit) notes=%s" % (hit, notes))
    bad += 0 if hit else 1
    res = R.record_inbound("are you there", door="inbound", sid="SMprobe",
                           at=now - timedelta(minutes=5), conn=conn)
    hit2, notes2 = R._quiet_guard(conn, now, "normal", "", "", "")
    print("  record_inbound -> ok=%s" % (res or {}).get("ok"))
    print("  after his text : quiet_guard hit=%r (want None) notes=%s" % (hit2, notes2))
    bad += 0 if ((res or {}).get("ok") and hit2 is None) else 1
finally:
    conn.close()

print()
print("RESULT:", "PASS" if not bad else "FAIL (%d)" % bad)
raise SystemExit(0 if not bad else 1)
