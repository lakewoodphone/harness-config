#!/usr/bin/env bash
# deploy-owner-text.sh — copy mirrored owner-text files into /root/bin, safely.
#
# Run ON secratary-cloud, from the harness-config checkout:
#   bash scripts/text-channel/mirror/deploy-owner-text.sh owner_text_relay.py
#   bash scripts/text-channel/mirror/deploy-owner-text.sh            # deploy everything in the manifest
#
# What it does, in this order, and refuses to skip a step:
#   1. byte-compiles the mirrored file  (a syntax error never reaches /root/bin)
#   2. backs the live file up to /root/text-deploy-backup/<UTC stamp>/
#   3. copies, then RE-HASHES the live file and compares it to the mirror
#   4. refuses (exit 3) if the hash does not match after the copy
#
# It does NOT restart anything. A restart is a service-state change: read
# settings/machines/host-posture.tsv and record the reason first (AGENTS.md §5).
set -eu

LIVE_DIR="${OWNER_TEXT_LIVE_DIR:-/root/bin}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$HERE/MANIFEST.sha256"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/root/text-deploy-backup/$STAMP"

files=("$@")
if [ ${#files[@]} -eq 0 ]; then
    mapfile -t files < <(awk '{print $2}' "$MANIFEST")
fi

mkdir -p "$BACKUP"
for name in "${files[@]}"; do
    src="$HERE/$name"
    live="$LIVE_DIR/$name"
    [ -r "$src" ] || { echo "REFUSED: not in the mirror: $src"; exit 1; }
    python3 -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$src" \
        || { echo "REFUSED: $name does not byte-compile — nothing deployed"; exit 1; }
    [ -f "$live" ] && cp -p "$live" "$BACKUP/$name"
    install -m 0755 -o root -g root "$src" "$live"
    want=$(md5sum "$src" | cut -d' ' -f1)
    have=$(md5sum "$live" | cut -d' ' -f1)
    if [ "$want" != "$have" ]; then
        echo "FAILED: $name hash mismatch after copy (want ${want:0:12} have ${have:0:12})"
        echo "        live copy backed up at $BACKUP/$name"
        exit 3
    fi
    printf 'deployed %-24s %s  (backup: %s)\n' "$name" "${have:0:12}" "$BACKUP/$name"
done

echo "backup of replaced originals: $BACKUP"
echo "reminder: a deployed file is not a running system. Verify the behaviour, not the copy."
