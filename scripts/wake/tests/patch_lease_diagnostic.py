#!/usr/bin/env python3
"""Make the next lease kill explain itself, without changing what it does.

MEASURED 2026-10-18 05:18:07, wake #1188:

    ERROR lease for wake #1188 not renewed - killing the session to avoid a double release: unknown

"unknown" means BOTH `LEASE_LOSS_REASON` and `_LEASE_LAST_ERR` were empty at the kill. But the `lost`
branch of `heartbeat_lease` ALWAYS sets `LEASE_LOSS_REASON` before `return 1`, and the `renew` branch
returns 0 -- so a return of 1 with no reason should be impossible, and it happened anyway.

Rather than keep guessing at a 1,300-line script, this records the two facts that will name the path:
the DECISION the state machine returned and the PROBE's rc, carried out of the function as globals and
printed in the kill line. Neither is a control-flow change: one assignment per branch and a longer
message. `bash -n` proves the syntax; the behaviour is identical.

The next kill will therefore read one of:
  * `decision=lost rc=1 ... reason=the store reports the row is no longer claimed by us`  -> normal loss
  * `decision=lost rc=2 ... reason=the store could not be reached before the lease expired` -> lock/timeout
  * `decision=<something else>` -> the state machine produced a decision nobody has seen, which is the
    only remaining explanation for an empty reason.
"""
import io
import sys

P = "/root/bin/wake-dispatch.sh"

EDITS = [
    # carry the decision and rc out of the function
    (P,
     '''      lost)
        if [ "$rc" -eq 1 ]; then
          LEASE_LOSS_REASON="the store reports the row is no longer claimed by us"
        else
          LEASE_LOSS_REASON="the store could not be reached before the lease expired (${LEASE_MARGIN}s margin)"
        fi
        return 1 ;;''',
     '''      lost)
        if [ "$rc" -eq 1 ]; then
          LEASE_LOSS_REASON="the store reports the row is no longer claimed by us"
        else
          LEASE_LOSS_REASON="the store could not be reached before the lease expired (${LEASE_MARGIN}s margin)"
        fi
        # 2026-10-18: a kill printed "unknown" although this branch always sets the reason above, so
        # the decision and the probe's rc are carried out to the kill line to name the path next time.
        LEASE_DECISION="$decision"; LEASE_RC="$rc"; LEASE_ATTEMPT="$attempt"
        return 1 ;;'''),
    # print them in the kill line
    (P,
     '''      log "ERROR lease for wake #$ID not renewed - killing the session to avoid a double release: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}}"''',
     '''      log "ERROR lease for wake #$ID not renewed - killing the session to avoid a double release: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}} [decision=${LEASE_DECISION:-unset} rc=${LEASE_RC:-unset} attempt=${LEASE_ATTEMPT:-unset} err=${_LEASE_LAST_ERR:-none}]"'''),
    # and initialise them beside LEASE_LOSS_REASON so they are never accidentally inherited
    (P,
     '''LEASE_LOSS_REASON=""''',
     '''LEASE_LOSS_REASON=""
LEASE_DECISION=""; LEASE_RC=""; LEASE_ATTEMPT=""'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED")
        continue
    if src.count(old) != 1:
        print("REFUSED: anchor found %d times: %r" % (src.count(old), old.splitlines()[0][:60]))
        ok = False
        continue
    out = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8").write(out)
    print("WROTE %s  %d -> %d chars" % (path, len(src), len(out)))
sys.exit(0 if ok else 1)
