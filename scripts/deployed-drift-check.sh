#!/bin/bash
# deployed-drift-check.sh — run the script-half drift check on the authority and TELL SOMEONE.
#
# WHY THIS EXISTS (2026-10-13). Two drift checkers were written this week, both correct, and NEITHER
# WAS SCHEDULED. `sync.py` now verifies the INSTRUCTION half on every machine (W2803). This closes
# the other half: the scripts the authority actually executes out of /usr/local/bin.
#
# The reason it matters was measured, not assumed: `journal/tools/journal.py` on this box was the
# older lineage that four deployed tools call, and two other scripts turned out to be AHEAD of the
# repo -- real work that existed only in the running location. Nobody notices that direction, because
# the running copy works and nothing is visibly broken.
#
# THE REFERENCE IS THE CAPTURE, NOT THE CHECKOUT. This box's own checkout is a different lineage, so
# comparing against it would report drift for files that are correct. `scripts/deployed/authority-bin/`
# holds byte-exact captures with a two-read protocol behind them; that is what this compares to.
#
# A refusal must not be silent. Exit 1 (drift) files ONE journal entry, deduplicated by the drift
# signature so it does not fire every fifteen minutes -- the same shape as `estate-alerts-to-journal`
# and `sync.py`'s own guard. Exit 2 (could not run) is reported as UNVERIFIED, never as clean.
set -u

REF_ROOT="${DEPLOYED_DRIFT_ROOT:-/root/deployed-drift-ref}"
TOOL="$REF_ROOT/scripts/deployed-drift.py"
JOURNAL="${JOURNAL_PY:-/root/code/harness-config/journal/tools/journal.py}"
STAMP=/root/.deployed-drift-last-signature

[ -x "$(command -v python3)" ] || { echo "deployed-drift-check: no python3"; exit 2; }
[ -f "$TOOL" ] || { echo "deployed-drift-check: $TOOL missing -- UNVERIFIED, not clean"; exit 2; }

OUT=$(python3 "$TOOL" --repo "$REF_ROOT" --local --quiet 2>&1)
RC=$?
echo "$OUT"

if [ $RC -eq 0 ]; then
  echo "deployed-drift-check: every compared script matches the capture."
  exit 0
fi

if [ $RC -ne 1 ]; then
  echo "deployed-drift-check: the check could not run (rc=$RC) -- UNVERIFIED, not clean."
  exit 2
fi

# rc=1: drift. File it once per distinct drift.
SIG=$(printf '%s' "$OUT" | grep -E '^(DRIFT|ONLY-DEPLOYED)' | sha256sum | cut -c1-16)
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$SIG" ]; then
  echo "deployed-drift-check: drift unchanged since the last run ($SIG); a journal entry already exists."
  exit 1
fi

BODY=$(mktemp)
{
  echo "Filed by \`/usr/local/bin/deployed-drift-check.sh\` on $(hostname) at $(date -u +%Y-%m-%dT%H:%M:%SZ)."
  echo
  echo "A script this host RUNS does not match the captured reference. Direction matters:"
  echo "REPO-IS-AHEAD means deploy it; DEPLOYED-IS-AHEAD means the running copy has work the"
  echo "reference does not -- RECOVER it, because nobody notices that direction."
  echo
  echo '```'
  printf '%s\n' "$OUT" | grep -E '^(DRIFT|ONLY-DEPLOYED|EXCLUDED|[a-z].*-- )' | head -30
  echo '```'
  echo
  echo "Reference: \`$REF_ROOT/scripts/deployed/authority-bin/\` (byte-exact captures)."
  echo "Fix: read the difference, decide which side is right -- the reference is not automatically"
  echo "correct, and two scripts were recovered FROM the deployed side on 2026-10-13 -- then"
  echo "re-capture with a fresh two-read, and record why."
} > "$BODY"

if [ -f "$JOURNAL" ]; then
  python3 "$JOURNAL" append pain \
    --title "a script this host RUNS does not match the captured reference" \
    --body "$BODY" --quiet --no-fetch --tags "deployed-drift,scripts,drift" >/dev/null 2>&1 \
    && { printf '%s' "$SIG" > "$STAMP"; echo "deployed-drift-check: filed to the journal."; } \
    || echo "deployed-drift-check: NOT FILED -- journal append failed; the drift is in the output above."
else
  echo "deployed-drift-check: NOT FILED -- $JOURNAL missing; the drift is in the output above."
fi
rm -f "$BODY"
exit 1
