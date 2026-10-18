#!/usr/bin/env bash
# verify-owner-text.sh — is the live owner-text stack still what this repo says it is?
#
# Run ON secratary-cloud, from the harness-config checkout:
#   bash scripts/text-channel/mirror/verify-owner-text.sh
#
# Exit: 0 = every live file matches MANIFEST.sha256
#       1 = at least one file differs (someone edited live, or P4254 restored it)
#       2 = a file is missing from /root/bin
#
# Why: /root/bin is not a git repo, and on 2026-10-15 three files were restored to their
# pre-change originals under a session that had just verified them. A change you cannot
# re-read is not a change. This is the re-read.
set -u

LIVE_DIR="${OWNER_TEXT_LIVE_DIR:-/root/bin}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$HERE/MANIFEST.sha256"

[ -r "$MANIFEST" ] || { echo "FAIL: manifest not readable: $MANIFEST"; exit 2; }

rc=0
diff_n=0
miss_n=0
while read -r want name; do
    [ -n "${name:-}" ] || continue
    live="$LIVE_DIR/$name"
    if [ ! -f "$live" ]; then
        printf 'MISSING  %-24s not in %s\n' "$name" "$LIVE_DIR"
        miss_n=$((miss_n+1)); rc=2; continue
    fi
    have=$(md5sum "$live" | cut -d' ' -f1)
    if [ "$have" != "$want" ]; then
        printf 'DIFFERS  %-24s live=%s manifest=%s  mtime=%s\n' \
            "$name" "${have:0:12}" "${want:0:12}" "$(stat -c %y "$live" | cut -c1-19)"
        diff_n=$((diff_n+1)); [ "$rc" -eq 0 ] && rc=1
    fi
done < "$MANIFEST"

if [ "$rc" -eq 0 ]; then
    echo "IN SYNC: every live owner-text file matches the mirror ($(wc -l < "$MANIFEST") files)"
else
    echo "OUT OF SYNC: $diff_n differ, $miss_n missing — read the file before trusting any claim about it"
fi
exit "$rc"
