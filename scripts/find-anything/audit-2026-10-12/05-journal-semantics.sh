#!/usr/bin/env bash
# 05-journal-semantics.sh -- does a multi-word journal query return hits, and does a REAL negative
# stay a negative?
#
# THE DEFECT THIS REPRODUCES. `journal.py`'s search required every query term on the SAME LINE
# (`all(p.lower() in ln for p in pats)` over `text.split("\n")`). Every tool above it inherited that
# and reported the resulting exit 1 -- whose own message is "the scope was searched and holds
# nothing" -- as a real negative. D2983 recorded the pair on 2026-10-09 and cited it as a reason to
# stop telling agents that find-anything was the primary surface. It was never fixed until 2026-10-12
# (docs/mesh/171, root cause R4).
#
# Measured before the fix:   "lpt website" -> 8 hits ; "lpt website deploy" -> exit 1, "no match".
# `search.py` rendered that to agents as `NO MATCH (exit 1: the scope was searched and holds nothing)`.
#
# This script asserts BOTH directions, because a fix that turns every query into a hit is worse than
# the bug: a genuine negative must still exit 1, and `--all-words` must still be strict.
#
# READ-ONLY: a copy of journal.py in /tmp cannot read the journal (the root is derived from __file__),
# so everything here passes an explicit --root.
set -uo pipefail

R="${JOURNAL_ROOT:-$HOME/code/harness-config/journal}"
[ -d "$R" ] || R="$HOME/harness-config/journal"
J="$R/tools/journal.py"
if [ ! -f "$J" ]; then
  echo "05-journal-semantics: no journal.py under $R -- NOTHING was tested." >&2
  exit 4
fi

pass=0; fail=0
chk() { # label expected_rc args...
  local label="$1" want="$2"; shift 2
  local t0 t1 out rc
  t0=$(date +%s%N); out=$(python3 "$J" search "$@" --root "$R" --limit 3 --budget 1500 2>&1); rc=$?; t1=$(date +%s%N)
  if [ "$rc" = "$want" ]; then
    printf '  PASS %-44s rc=%s  %5s ms\n' "$label" "$rc" "$(( (t1-t0)/1000000 ))"; pass=$((pass+1))
  else
    printf '  FAIL %-44s rc=%s (wanted %s)\n' "$label" "$rc" "$want"; fail=$((fail+1))
  fi
}

echo "journal: $R"
echo
echo "=== MUST be hits (the D2983 pair, and my own false negative from 2026-10-12) ==="
chk 'one-arg  "lpt website"'                   0 "lpt website"
chk 'one-arg  "lpt website deploy"'            0 "lpt website deploy"
chk 'one-arg  "cloud migration secretary"'     0 "cloud migration secretary"
chk 'multi-arg cloud migration secretary'      0 cloud migration secretary
echo "  A one-arg query is what ps_search sends; a multi-arg query is what a shell sends."
echo "  Both must mean the same thing. If only one of the two rows above passes, that is the bug."
echo
echo "=== MUST stay REAL NEGATIVES (a fix that makes everything a hit is worse than the bug) ==="
chk 'one-arg  "zzqqnosuchterm9931"'            1 "zzqqnosuchterm9931"
chk 'multi-arg cloud zzqqnosuchterm9931'       1 cloud zzqqnosuchterm9931
echo
echo "=== a single word is unchanged ==="
chk 'one-word battery'                         0 battery
echo
echo "=== --all-words must remain the STRICT, line-level reading ==="
out=$(python3 "$J" search cloud migration --all-words --root "$R" --limit 3 --budget 900 2>&1); rc=$?
echo "  --all-words cloud migration -> rc=$rc  (0 or 1 are both correct; it must not error)"
echo
echo "=== the estate's own health check must still be clean ==="
python3 "$J" check 2>&1 | tail -2
echo
echo "---- $pass passed, $fail failed ----"
[ "$fail" = 0 ] || exit 1
echo
echo "If this is being run to diagnose the ORIGINAL defect: the tell is"
echo "  \"lpt website\" -> 0, \"lpt website deploy\" -> 1."
echo "That pair is a false negative, not an absence. Do not report it as 'the journal has nothing'."
exit 0
