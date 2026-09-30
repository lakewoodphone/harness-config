#!/usr/bin/env python3
"""Two fixes for the same defect class: an actor that acts without asking, and one number in two places.

FIX 1 - wake-fanout.sh must not start a dispatcher when nothing can be claimed.
Measured 2026-09-30 by the evidence this session's earlier patch started preserving. The preserved
claim.json from the 15:40Z tick says it exactly:

    {"ok": true, "row": null, "blocked_by": "row-gates",
     "gated": {"not_before": 10, "night_quiet": 0, "source_hourly_cap": 4, "new_rows": 14}}

Fourteen rows waiting, ten gated by a date, four by a source cap, and the fan-out started a dispatcher
anyway - which correctly claimed nothing and exited. Repeated every five minutes through a 55-minute
stretch, each tick paying for a process and writing a log line that reads like a failure. Now it asks
first, using the reader this session added, and says "nothing claimable" instead.

Known gap, stated rather than hidden: the reader models the not_before gate and NOT the source hourly cap
or the night gate, so a tick gated only by a cap still costs one start. Closing that needs the reader to
share the claim predicate, which is a bigger change than this one.

FIX 2 - the per-source hourly cap must live in ONE place.
`autonomy-status.sh` printed `source_cap: project-keepalive 3/3 in the last hour` while the sources timer
carried WAKE_MAX_PER_SOURCE_PER_HOUR=12 in its crontab line. Two processes, two answers to one question.
wake.py's own default becomes 12 and the env override is removed from the cron, so every reader and every
writer agrees. 12 per source per hour is bounded by the 500/day backstop and the 70 USD/day ceiling, which
are the limits that mean something.

Both fail closed: every anchor must appear exactly once.
"""
import os
import shutil
import sys
import time

WAKE = "/home/zabz/bin/wake.py"
FANOUT = "/home/zabz/bin/wake-fanout.sh"

GUARD = '''
# DO NOT START A DISPATCHER WHEN NOTHING CAN BE CLAIMED. Measured 2026-09-30: the fan-out started a
# dispatcher every five minutes through a 55-minute stretch in which no row was claimable, and each time
# the dispatcher correctly exited having done nothing. The preserved evidence from one of those ticks:
#   {"ok": true, "row": null, "blocked_by": "row-gates",
#    "gated": {"not_before": 10, "night_quiet": 0, "source_hourly_cap": 4, "new_rows": 14}}
# Ask before starting, and say which gate is in force. Covers the not_before gate; a tick gated only by a
# source cap still costs one start - a known gap, recorded rather than ignored.
if [ "$DRY_RUN" != 1 ]; then
  NCOUT=$(python3 "${WAKE_NEXTCLAIM:-/home/zabz/bin/wake-nextclaim.py}" --json 2>/dev/null || true)
  NCZERO=$(printf '%s' "$NCOUT" | python3 -c 'import json,sys
try:
    print(1 if json.load(sys.stdin).get("claimable_now", 0) == 0 else 0)
except Exception:
    print("")' 2>/dev/null)
  if [ "$NCZERO" = "1" ]; then
    say "fanout: nothing claimable now - starting nothing this tick"
    note "skip: nothing claimable; procs=$PROCS gate=$NCOUT"
    exit 0
  fi
fi
'''

ANCHOR = '''if [ "$STORED" -lt 0 ] || [ "$QUEUED" -lt 0 ]; then
  say "fanout: the store could not be read (locked?) - starting nothing this tick"
  note "abort: store unreadable (claimed=$STORED new=$QUEUED procs=$PROCS)"
  exit 0
fi
'''

OLD_CAP = '_env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 3)'
NEW_CAP = '_env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12)'


def patch(path, pairs, marker):
    src = open(path, encoding="utf-8").read()
    if marker in src:
        print("SKIP %s: already patched" % path)
        return
    for old, _ in pairs:
        n = src.count(old)
        if n < 1:
            sys.exit("FAIL %s: anchor not found: %r - nothing written" % (path, old[:90]))
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    shutil.copy2(path, "%s.bak-%s-%s" % (path, marker.replace("_", "-"), stamp))
    for old, new in pairs:
        src = src.replace(old, new)
    tmp = path + ".tmpnew"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(src)
    os.chmod(tmp, os.stat(path).st_mode)
    os.replace(tmp, path)
    print("patched %s (backup .bak-%s-%s)" % (path, marker.replace("_", "-"), stamp))


patch(FANOUT, [(ANCHOR, ANCHOR + GUARD)], "no-claim-guard")
patch(WAKE, [(OLD_CAP, NEW_CAP),
             ("WAKE_MAX_PER_SOURCE_PER_HOUR(3)    guard 4",
              "WAKE_MAX_PER_SOURCE_PER_HOUR(12)   guard 4 - raised 2026-09-30: one number, every reader")],
      "cap-12")
