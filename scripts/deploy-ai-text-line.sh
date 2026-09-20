#!/usr/bin/env bash
# deploy-ai-text-line.sh -- install the AI text line onto secratary, atomically.
#
# One source of truth: harness-config/scripts/*.py. This copies them to ~/bin/,
# where the cron runs them. It never edits in place: every file is staged next to
# its target, syntax-checked, and only then moved into position, so a bad sync can
# never leave a half-written script for cron to execute.
#
# Run ON secratary, from anywhere:
#     bash ~/harness-config/scripts/deploy-ai-text-line.sh            # dry run
#     bash ~/harness-config/scripts/deploy-ai-text-line.sh --apply
#
# Exit 0 = every file verified and (with --apply) in place.
set -uo pipefail

SRC="${HARNESS_CONFIG:-$HOME/harness-config}/scripts"
BIN="$HOME/bin"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# Files that make up the AI text line. The v2 modules are optional: the responder
# degrades without them, so a partial tree is deployable and is reported as such.
REQUIRED=(sms-inbox.py sms-responder.py send-from-ai-line.py)
OPTIONAL=(textstore.py textctx.py textdecide.py textwork.py textsend.py wake.py)

fail=0
declare -a staged=()

echo "== AI text line deploy  src=$SRC  bin=$BIN  apply=$APPLY  $STAMP =="

for name in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do
  src="$SRC/$name"
  if [ ! -f "$src" ]; then
    if printf '%s\n' "${REQUIRED[@]}" | grep -qx "$name"; then
      echo "  MISSING (required): $name"; fail=1
    else
      echo "  absent  (optional): $name"
    fi
    continue
  fi
  # Syntax-check the source before it can ever reach ~/bin. PYTHONPYCACHEPREFIX
  # keeps the .pyc out of the repo - py_compile would otherwise write __pycache__
  # into a tracked tree and dirty it on every deploy check.
  if ! PYTHONPYCACHEPREFIX=/tmp/pycache-deploy python3 -m py_compile "$src" 2>/tmp/pyc.err; then
    echo "  SYNTAX ERROR in $name:"; sed 's/^/      /' /tmp/pyc.err; fail=1; continue
  fi
  sum=$(sha256sum "$src" | cut -c1-12)
  if [ -f "$BIN/$name" ] && cmp -s "$src" "$BIN/$name"; then
    echo "  unchanged        : $name  ($sum)"
    continue
  fi
  echo "  stage            : $name  ($sum)"
  staged+=("$name")
done

if [ "$fail" -ne 0 ]; then
  echo "== refusing to deploy: a required file is missing or does not compile =="
  exit 1
fi

if [ ${#staged[@]} -eq 0 ]; then
  echo "== nothing to do: ~/bin already matches the repo =="
  exit 0
fi

if [ "$APPLY" -ne 1 ]; then
  echo "== dry run: ${#staged[@]} file(s) would be installed: ${staged[*]} =="
  echo "   re-run with --apply to install"
  exit 0
fi

mkdir -p "$BIN/.deploy-backup-$STAMP"
for name in "${staged[@]}"; do
  [ -f "$BIN/$name" ] && cp -p "$BIN/$name" "$BIN/.deploy-backup-$STAMP/$name"
  cp "$SRC/$name" "$BIN/.staged-$name"
  chmod +x "$BIN/.staged-$name"
  mv -f "$BIN/.staged-$name" "$BIN/$name"
  echo "  installed        : $name"
done

echo "== backups in $BIN/.deploy-backup-$STAMP =="
echo "== verifying the installed tree =="
python3 "$BIN/sms-responder.py" report 2>&1 | head -6
echo "== done =="
