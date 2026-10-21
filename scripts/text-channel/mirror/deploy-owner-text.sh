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
#   3. copies to a TEMPORARY file beside the target, re-hashes it, and only then MOVES it
#      into place, so the live path gets a NEW INODE
#   4. refuses (exit 3) if the hash does not match after the move
#
# WHY THE MOVE AND NOT `install` (added 2026-10-19)
# -------------------------------------------------
# `install` and `cp` open the destination and truncate it IN PLACE, keeping the inode. Python
# does not load a module once into memory: it reads the .py file as it compiles, and a process
# that is part-way through an import (or a running script, which bash reads incrementally by
# byte offset) can then execute whatever now sits at the offset it expects — a mixture of old
# and new that no single version of the file can produce. `owner_text_relay.py` is invoked by
# cron every five minutes and `sms-responder.py` by the wake loop, so a truncating deploy has a
# real window in which to produce exactly that. AGENTS.md §8 states the rule for the wake tree;
# this script is where the owner-text tree has to obey it.
#
# Proven on this estate 2026-10-18: after an `mv`, the running instances keep the unlinked old
# inode and finish on consistent code (`/proc/<pid>/fd/255` shows `path (deleted)`), while every
# new invocation reads the new one.
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
    # The mirror holds Python tools and small shell wrappers.  A Python-only check here
    # refused model-catalog-refresh.sh with a SyntaxError, which is a check that cannot
    # see the file it is checking.
    case "$name" in
        *.py) python3 -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$src" \
                  || { echo "REFUSED: $name does not byte-compile — nothing deployed"; exit 1; } ;;
        *.sh) bash -n "$src" \
                  || { echo "REFUSED: $name has a shell syntax error — nothing deployed"; exit 1; } ;;
        *)    echo "REFUSED: $name has no syntax check in this deployer"; exit 1 ;;
    esac
    [ -f "$live" ] && cp -p "$live" "$BACKUP/$name"
    want=$(md5sum "$src" | cut -d' ' -f1)

    # Stage beside the target, verify the STAGED copy, then move. A failed copy or a full
    # disk therefore leaves the live file untouched rather than half-written.
    stage="$live.new.$$"
    cp -p "$src" "$stage"
    have=$(md5sum "$stage" | cut -d' ' -f1)
    if [ "$want" != "$have" ]; then
        rm -f "$stage"
        echo "FAILED: $name hash mismatch on the staged copy (want ${want:0:12} have ${have:0:12})"
        exit 3
    fi
    chmod 0755 "$stage"
    chown root:root "$stage" 2>/dev/null || true
    mv "$stage" "$live"

    after=$(md5sum "$live" | cut -d' ' -f1)
    if [ "$want" != "$after" ]; then
        echo "FAILED: $name hash mismatch after the move (want ${want:0:12} have ${after:0:12})"
        echo "        live copy backed up at $BACKUP/$name"
        exit 3
    fi
    printf 'deployed %-24s %s  inode=%s  (backup: %s)\n' \
        "$name" "${after:0:12}" "$(stat -c %i "$live")" "$BACKUP/$name"
done

echo "backup of replaced originals: $BACKUP"
echo "reminder: a deployed file is not a running system. Verify the behaviour, not the copy."
