#!/usr/bin/env python3
"""Two lane fixes, from the resolver's own verdict rather than from a catalog file.

MEASURED 2026-10-18 on ZABZ-TECH, running the actual resolver (`wake-model.ps1`) that the runner
uses. It validates against **https://api.deepseek.com/v1/models**, NOT against the secretary
gateway's catalog and NOT against ~/.sms-inbox/model-catalog.json:

    deepseek/deepseek-v4-pro    dropped=["deepseek/deepseek-v4-pro"]  unvalidated=true
    deepseek/deepseek-v4-flash  dropped=[...]                          unvalidated=true
    deepseek-chat               dropped=["deepseek-chat"]              unvalidated=true
    deepseek-v4-pro             dropped=[]                             validated=TRUE
    deepseek-v4-flash           dropped=["deepseek-v4-flash"]          unvalidated=true

TWO CONSEQUENCES.

1. THE CONSERVE LANE IS A LATENT TOTAL OUTAGE. `wake_budget.lane_for("conserve")` returns
   `deepseek/deepseek-v4-flash` -- wrong prefix AND an id the provider catalog does not contain at
   all. The moment the balance tier flips to conserve, EVERY shift would fail exactly as wake #1123
   and #1186 did (2 seconds, FAIL-LOUD UNRESOLVED). That lever has never worked; it has only never
   been pulled. Since no validated CHEAP id exists in this provider's catalog, the honest value is
   `None` -- do not pin -- because pinning an invalid id is strictly worse than using the default
   seat, and "conserve" was never real.

2. THE CAPABILITY LADDER'S ID IS NOW KNOWN. `deepseek-v4-pro` (bare, no prefix) is the validated
   strong lane. The preference chain is corrected to try it first.

The ladder stays INERT (`WAKE_CAPABILITY_LANE` unset) -- proven-valid is not proven-in-a-release,
and this file has already recorded what happens when those are confused.

Idempotent, parse-checked.
"""
import ast
import io
import sys

BUDGET = "/root/bin/wake_budget.py"
DISP = "/root/bin/wake-dispatch.sh"

EDITS = [
    # 1. the conserve lane: no validated cheap id exists, so do not pin
    (BUDGET,
     '''    return None if tier == "ok" else "deepseek/deepseek-v4-flash"''',
     '''    # MEASURED 2026-10-18 by running the resolver the runner actually uses: it validates against
    # https://api.deepseek.com/v1/models, and BOTH `deepseek/deepseek-v4-flash` (the old value) and
    # the bare `deepseek-v4-flash` are absent from it -- unvalidated=true, dropped. Pinning either
    # would make EVERY shift fail the moment the balance tier flipped to conserve, which is the
    # failure wake #1123/#1186 already demonstrated in two seconds. No validated cheap id exists in
    # this provider's catalog, so the honest lane is "do not pin": the default seat is better than
    # a guaranteed FAIL-LOUD, and the conserve lever was never real.
    return None'''),
    # 2. the ladder's preference chain, corrected to the validated id
    (DISP,
     '''PREF = ("deepseek/deepseek-v4-pro", "deepseek-v4-pro", "secretary-smart")''',
     '''# MEASURED 2026-10-18 with the runner's own resolver: only the BARE id validates
# (dropped=[], validated=True). The prefixed forms the gateway catalog lists are rejected by
# https://api.deepseek.com/v1/models, which is what the runner actually reads.
PREF = ("deepseek-v4-pro",)'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED: %s" % path)
        continue
    if src.count(old) != 1:
        print("REFUSED: %s anchor found %d times" % (path, src.count(old)))
        ok = False
        continue
    out = src.replace(old, new, 1)
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("REFUSED: %s would not parse: %s" % (path, exc))
        ok = False
        continue
    io.open(path, "w", encoding="utf-8").write(out)
    print("WROTE %s  %d -> %d chars" % (path, len(src), len(out)))
sys.exit(0 if ok else 1)
