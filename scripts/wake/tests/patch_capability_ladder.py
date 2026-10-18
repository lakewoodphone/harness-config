#!/usr/bin/env python3
"""Add a capability ladder to the dispatcher: priority now influences the seat model.

MEASURED 2026-10-18 on the authority. The seat model depended on exactly ONE input -- the balance
tier (`wake_budget.lane_for`). Priority and kind were invisible to it, so a customer-facing critical
repair and a routine tidy-up were handed the same model. Distribution measured from the wake store:
4 high vs 25 normal releases in one day (all-time 230 high, 916 normal, 37 low).

WHY A LADDER AND NOT A GLOBAL UPGRADE. A high-priority row that fails costs a whole shift and
re-files; a cheap answer on it is a false economy. Measured cost of a release is 0.05-0.07 USD, so
four upgraded releases a day is cents against a 67.36 USD ceiling, while the existing balance lever
still forces the cheap lane whenever the tier is not `ok`.

THE ID IS RESOLVED FROM THE LIVE CATALOG, NEVER HARDCODED. Standing instruction: models change
constantly and a literal name in code is a time bomb (`journal.py show L1606`: every live AI call
had failed for a week while a deterministic fallback hid it). Preference order is tried against
`model-catalog.json`; if nothing matches, the lane stays EMPTY and the default seat is used. A
missing catalog must not make this guess a model.

Idempotent, backs nothing up on its own (the caller does), and refuses unless its anchor is unique.
"""
import ast
import io
import sys

P = "/root/bin/wake-dispatch.sh"

OLD = '''LANE_ARG=""
[ -n "$LANE" ] && LANE_ARG=" -Model \\"$LANE\\""'''

NEW = '''# --- CAPABILITY LADDER, BY PRIORITY (2026-10-18) ---------------------------
# Until today the seat model depended ONLY on the balance tier, so priority and kind were invisible
# to it and a customer-facing critical repair got the same model as a routine tidy-up. Measured
# distribution: 4 high vs 25 normal releases in one day. Every failure on a high row costs a whole
# shift, so a stronger lane there is worth cents against the daily ceiling; the balance lever above
# still forces the cheap lane whenever the tier is not `ok`.
#
# THE ID COMES FROM THE LIVE CATALOG, NEVER A LITERAL. A hardcoded model name is a time bomb on
# this estate (journal L1606: every live AI call failed for a week while a fallback hid it). If
# nothing in the preference chain is listed, LANE stays empty and the default seat is used --
# a missing or unreadable catalog must never make this guess.
if [ -z "$LANE" ] && [ "$PRIORITY" = "high" ]; then
  LANE=$(python3 - "${WAKE_MODEL_CATALOG:-$HOME/.sms-inbox/model-catalog.json}" <<'PY' 2>/dev/null || true
import json, sys
PREF = ("deepseek/deepseek-v4-pro", "deepseek-v4-pro", "secretary-smart")
try:
    ids = json.load(open(sys.argv[1], encoding="utf-8")).get("ids") or []
except Exception:
    print("")
    raise SystemExit(0)
for cand in PREF:
    if cand in ids:
        print(cand)
        break
else:
    print("")
PY
)
  [ -n "$LANE" ] && LANE_REASON="capability:high-priority"
fi
# Publish which model actually served the shift. Nothing read the choice before, so "the cheaper
# lane is used when balance is low" was unverifiable from the store; this line makes it greppable.
LANE_REASON="${LANE_REASON:-}"
if [ -n "$LANE" ]; then
  echo "$(date -Is) wake #${ID:-?} priority=${PRIORITY:-?} lane=$LANE reason=${LANE_REASON:-balance}" \\
    >> "$HOME/.sms-inbox/wake-lane.log" 2>/dev/null || true
fi
LANE_ARG=""
[ -n "$LANE" ] && LANE_ARG=" -Model \\"$LANE\\""'''

src = io.open(P, encoding="utf-8").read()
if "CAPABILITY LADDER, BY PRIORITY" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
n = src.count(OLD)
if n != 1:
    print("REFUSED: anchor found %d times (expected 1); nothing written" % n)
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
