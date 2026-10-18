#!/usr/bin/env python3
"""Record the heartbeat function's ACTUAL exit status, because it is not returning through its own code.

MEASURED 2026-10-18 05:24:45, wake #1169:

    ERROR lease for wake #1169 not renewed ... : unknown [decision=unset rc=unset attempt=unset err=none]

Every one of those globals is assigned on heartbeat_lease's `lost` path, immediately before its
`return 1`; its only other exit is `renew`, which returns 0. So the function reported failure WITHOUT
taking either branch -- which means it did not return through its own code. The remaining explanation
is an interrupt (a signal while it sleeps), and a signal shows up as an exit status of 128+N:
143 = SIGTERM, 130 = SIGINT, 137 = SIGKILL.

`if ! func; then` discards that number -- it only tells you "non-zero". This captures it:

    heartbeat_lease; HB_RC=$?
    if [ "$HB_RC" -ne 0 ]; then

which is the same condition and therefore the same behaviour, with the number kept. `set -e` is NOT
in force in this script (`set -u` and `pipefail` only), so a bare invocation is safe.

The log line gains `hbrc=`.
"""
import io
import sys

P = "/root/bin/wake-dispatch.sh"

EDITS = [
    (P,
     '''    if ! heartbeat_lease; then''',
     '''    # Record the ACTUAL status, not just "non-zero": MEASURED 2026-10-18 the function failed without
    # taking either of its own return paths, and only the number can tell an interrupt (128+N) from a
    # decision. Same condition, same behaviour, one datum kept. No `set -e` in this script.
    heartbeat_lease; HB_RC=$?
    if [ "$HB_RC" -ne 0 ]; then'''),
    (P,
     '''[decision=${LEASE_DECISION:-unset} rc=${LEASE_RC:-unset} attempt=${LEASE_ATTEMPT:-unset} err=${_LEASE_LAST_ERR:-none}]''',
     '''[hbrc=${HB_RC:-unset} decision=${LEASE_DECISION:-unset} rc=${LEASE_RC:-unset} attempt=${LEASE_ATTEMPT:-unset} err=${_LEASE_LAST_ERR:-none}]'''),
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
