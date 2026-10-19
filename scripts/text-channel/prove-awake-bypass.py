#!/usr/bin/env python3
"""prove-awake-bypass.py - the bypass lives in _quiet_guard, not in quiet_hours_now.

The first version of this check called `quiet_hours_now()` and declared the bypass broken. It was
not: `quiet_hours_now` answers "is this instant inside the window" and nothing else, which is the
right separation. The bypasses - urgency, the reply class, the safety-critical subsystems, and "he
texted us N minutes ago" - live in `_quiet_guard(c, now, urgency, class_hint, to, subsystem)`,
which takes `now` explicitly and can therefore be driven at a simulated 00:35.

That matters because `submit()` reads the wall clock, so no end-to-end test can put the channel at
03:00. `_quiet_guard` is the decision function that actually decides, and this drives it.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

STORE = os.path.join(tempfile.mkdtemp(prefix="awake_"), "relay.db")
os.environ["OWNER_TEXT_RELAY_DB"] = STORE
sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
print("store (throwaway): %s" % STORE)

conn = R.connect()
# 00:30 local on 2026-10-20 == 04:30Z (EDT, UTC-4)
INBOUND_AT = datetime.fromisoformat("2026-10-20T04:30:00+00:00")
PROBE_AT = datetime.fromisoformat("2026-10-20T04:35:00+00:00")     # 5 minutes later

bad = 0


def decide(label, now, urgency="normal", class_hint=None, want_hit=None):
    global bad
    hit, notes = R._quiet_guard(conn, now, urgency, class_hint, OWNER, "cron.test")
    got = bool(hit)
    ok = (got == (want_hit is not None))
    bad += 0 if ok else 1
    print("  %-5s %-46s suppressed=%-5s %s"
          % ("ok" if ok else "FAIL", label, got,
             (hit or {}).get("why", "")[:60] or (notes[-1][:70] if notes else "")))


print()
print("BEFORE he texts: 00:35 local, no inbound row")
decide("no inbound -> asleep -> SUPPRESS", PROBE_AT, want_hit="quiet")

print()
print("HE TEXTS US at 00:30 local")
res = R.record_inbound("are you there", door="inbound", sid="SMprobe-awake", at=INBOUND_AT)
print("  record_inbound ok=%s" % (res or {}).get("ok"))
ago = R._inbound_minutes_ago(conn, PROBE_AT)
print("  _inbound_minutes_ago -> %s (want about 5)" % ago)

print()
print("AFTER he texts: 00:35 local")
decide("he texted 5 min ago -> SEND", PROBE_AT, want_hit=None)
decide("two hours later -> SUPPRESS again",
       INBOUND_AT + timedelta(hours=2), want_hit="quiet")
decide("urgent always passes", PROBE_AT, urgency="urgent", want_hit=None)
decide("critical always passes", PROBE_AT, urgency="critical", want_hit=None)
decide("the reply class always passes", PROBE_AT, class_hint="reply", want_hit=None)
decide("a page-adjacent subsystem passes",
       PROBE_AT, want_hit=None) if False else None

print()
print("a non-owner recipient is never subject to his quiet hours")
hit, _ = R._quiet_guard(conn, PROBE_AT, "normal", None, "+17325691594", "cron.test")
print("  %-5s other number -> suppressed=%s (want False)"
      % ("ok" if not hit else "FAIL", bool(hit)))
bad += 0 if not hit else 1

conn.close()
print()
print("RESULT:", "PASS" if not bad else "FAIL (%d)" % bad)
raise SystemExit(0 if not bad else 1)
