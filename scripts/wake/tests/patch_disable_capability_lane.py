#!/usr/bin/env python3
"""Disable the capability lane by default, because it killed two shifts.

MEASURED 2026-10-18 05:08:04-08. The capability ladder (doc section 62) pinned
`deepseek/deepseek-v4-pro` for high-priority rows, resolved from the LOCAL catalog file
`~/.sms-inbox/model-catalog.json`. The dispatcher's runner on ZABZ-TECH validates against a LIVE
catalog and refused:

    model lane: PINNED by the balance control -> deepseek/deepseek-v4-pro (WAKE_AGENT_MODEL)
    model: FAIL-LOUD UNRESOLVED - refusing to boot on the profile composition default:
           resolver could not validate 'deepseek/deepseek-v4-pro' against a live catalog

So wake #1123 and wake #1186 both FAILED (exit=1, runner_code=3, dur=2s) on a model id that exists
in the authority's catalog file and not in the resolver's live one. Two shifts lost to a lane that
had never been exercised.

THE FIX HERE IS TO STOP THE BLEEDING, NOT TO GUESS A DIFFERENT ID: the pin now requires
`WAKE_CAPABILITY_LANE=1` in the dispatcher's environment, which nothing sets. The ladder code, the
catalog resolution and the new wake-lane.log line all stay, so the work is not thrown away.

THE REAL FIX, for the next round: resolve the lane against the SAME catalog the runner validates
against (the live gateway catalog the runner reports), not the local file -- and prove it by
releasing one high-priority row and reading `model lane:` from its outcome before enabling the env.
"""
import ast
import io
import sys

P = "/root/bin/wake-dispatch.sh"

OLD = '''if [ -z "$LANE" ] && [ "$PRIORITY" = "high" ]; then'''

NEW = '''# DISABLED BY DEFAULT 2026-10-18: this pinned deepseek/deepseek-v4-pro from the LOCAL catalog file
# and the runner validates against a LIVE catalog, so wake #1123 and #1186 FAILED at 05:08 with
# "FAIL-LOUD UNRESOLVED ... could not validate". Two shifts, on a lane that had never been run.
# The code is kept so the next round can point it at the catalog the runner actually reads; it is
# inert until WAKE_CAPABILITY_LANE=1 is exported by whoever has proved the id.
if [ -z "$LANE" ] && [ "$PRIORITY" = "high" ] && [ "${WAKE_CAPABILITY_LANE:-0}" = "1" ]; then'''

src = io.open(P, encoding="utf-8").read()
if "DISABLED BY DEFAULT 2026-10-18" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
if src.count(OLD) != 1:
    print("REFUSED: anchor found %d times" % src.count(OLD))
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
