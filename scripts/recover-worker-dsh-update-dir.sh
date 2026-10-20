#!/usr/bin/env bash
# RECOVERY: install-engine was invoked with no resolvable live install root, and it fell back to the CURRENT
# DIRECTORY ("$REPO"), so it "swapped" /home/zabz/code/harness-config/dsh-update for an engine tree. That is why
# lib/cli.mjs vanished and promote failed. The real dsh-update is beside it with a `.prev-` suffix.
#
# This puts the tree back, exactly, and proves it before anything else runs.
set -uo pipefail
BASE=/home/zabz/code/harness-config
cd "$BASE" || exit 2

echo "=== candidates ==="
ls -d "$BASE"/dsh-update* 2>/dev/null | sed 's/^/  /'

PREV=$(ls -dt "$BASE"/dsh-update.prev-* 2>/dev/null | head -1)
IMPOSTOR="$BASE/dsh-update"

if [ -z "$PREV" ]; then echo "REFUSED: no dsh-update.prev-* to restore from"; exit 2; fi
if [ -f "$IMPOSTOR/lib/cli.mjs" ]; then echo "the live dir still looks like the tool tree — nothing to restore"; exit 0; fi

echo "=== what is in the impostor (should be an engine prefix) ==="
ls -1 "$IMPOSTOR" | head -5 | sed 's/^/  /'
echo "=== what is in the recorded previous tree (should be lib/ tools/ state/ patches/) ==="
ls -1 "$PREV" | head -8 | sed 's/^/  /'

echo "=== swapping back ==="
mv "$IMPOSTOR" "$BASE/dsh-update.from-engine-$(date -u +%Y%m%dT%H%M%SZ)" && echo "  impostor moved aside"
mv "$PREV" "$IMPOSTOR" && echo "  real dsh-update restored"

echo "=== proof ==="
ls -1 "$IMPOSTOR/lib" 2>/dev/null | head -6 | sed 's/^/  lib: /'
echo "  cli.mjs: $(ls -l "$IMPOSTOR/lib/cli.mjs" 2>/dev/null | awk '{print $5" bytes"}' || echo MISSING)"
echo "  pin: $(python3 -c "import json;print(json.load(open('$IMPOSTOR/state/pin.json'))['version'])" 2>/dev/null || echo MISSING)"
echo "  tools: $(ls -1 "$IMPOSTOR/tools" 2>/dev/null | wc -l) files"
echo "=== engine still the old one, still serving? ==="
python3 -c "import json;print('  engine tree:', json.load(open('/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/package.json'))['version'])" 2>/dev/null
echo "  unit: $(systemctl is-active dsh-engine.service)"
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 6 http://127.0.0.1:3099/ || true
