#!/usr/bin/env bash
# ca-deployed.sh — correct persona rule 8 in the DEPLOYED profile patch, safely.
#
# The deployed patch is not the repo's (measured 2026-10-26: web 123,851 B in git vs 152,995 B
# loaded) and nothing syncs them, so a rule corrected in the repo stays false in what the engine
# loads. Editing it in place is what broke ZABZ-YOGA earlier the same day: a straight double quote
# inside the double-quoted persona scalar produced
#   dsh: failed to parse overlay ... YAMLException: missed comma between flow collection entries
# and would have stopped the profile booting. So: transform a COPY, prove the copy parses with the
# engine's own loader, and only then move it into place.
set -uo pipefail

LIVE="${LIVE:-$HOME/.dsh/profiles/web/cordis.patch.yml}"
MIRROR="${MIRROR:-/tmp/ca-mirror.py}"
RULE="${RULE:-/tmp/ca-rule8.txt}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [ ! -f "$LIVE" ]; then echo "deployed=absent"; exit 0; fi
if ! grep -q 'The window gets thrown away' "$LIVE" 2>/dev/null; then
  echo "deployed=already_clean (no old rule present)"
  exit 0
fi

cp "$LIVE" "$LIVE.bak-rule8-$STAMP" || { echo "backup=FAILED"; exit 1; }
echo "backup=$LIVE.bak-rule8-$STAMP"

cp "$LIVE" /tmp/ca-deployed-candidate.yml || exit 1
if ! python3 "$MIRROR" --rule 8 --from "$RULE" --only-targets --target /tmp/ca-deployed-candidate.yml; then
  echo "mirror=FAILED"
  exit 1
fi

DSHBIN="${DSHBIN:-$(ls -d "$HOME/.dsh/engine/node_modules/.bin/dsh" 2>/dev/null || command -v dsh || true)}"
if [ -z "$DSHBIN" ]; then
  echo "validate=SKIPPED (no dsh binary — refusing to install unvalidated)"
  exit 1
fi
read -r -a DSHCMD <<< "$DSHBIN"; "${DSHCMD[@]}" --profile web --dump-config --patch /tmp/ca-deployed-candidate.yml >/tmp/ca-dump.log 2>&1
rc=$?
echo "dump_rc=$rc"
if [ "$rc" -ne 0 ]; then
  echo "installed=no (the candidate does not parse; live file untouched)"
  grep -E 'Error|failed to parse' /tmp/ca-dump.log | head -3
  exit 1
fi

cp /tmp/ca-deployed-candidate.yml "$LIVE" || exit 1
echo "installed_new=$(grep -c 'You can see your own context' "$LIVE" 2>/dev/null || echo 0)"
echo "installed_old=$(grep -c 'The window gets thrown away' "$LIVE" 2>/dev/null || echo 0)"
