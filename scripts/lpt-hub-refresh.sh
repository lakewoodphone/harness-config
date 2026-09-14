#!/usr/bin/env bash
# Keep the local lpt-hub clone fresh, because app/services/lpt_hub_sync.py reads that
# working tree (docs/customer-operations/sync-records/*.json) as the customer-case corpus.
#
# WHY THIS EXISTS (2026-09-14): the service could see 0 records because its GitHub path was
# dead (PyGithub missing) and its only local candidate path did not exist; a stray directory
# was masking that as "1 record". The fix pointed the service at /home/zabz/repos/lpt-hub,
# which makes that clone the SINGLE source of the corpus. Nothing refreshed it, so it would
# stale silently -- exactly the class of failure the fix removed.
#
# FAST-FORWARD ONLY. It never forces and never discards a local commit: the secretary also
# commits to this clone (chore(secretary): link <case> to WO<n>), so a divergence is a
# REPORTED fact in the status file, not something this script resolves by guesswork.
set -u

REPO=/home/zabz/repos/lpt-hub
RECORDS_DIR="$REPO/docs/customer-operations/sync-records"
STATE_DIR="$HOME/.lpt-hub-refresh"
STATUS="$STATE_DIR/status.json"
LOG="$STATE_DIR/refresh.log"
mkdir -p "$STATE_DIR"

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

git -C "$REPO" fetch --quiet origin 2>>"$LOG"

branch=$(git -C "$REPO" status --short --branch | head -1)
ff="ok"
if ! git -C "$REPO" merge --ff-only origin/main --quiet 2>>"$LOG"; then
    ff="refused"
fi

records=$(find "$RECORDS_DIR" -name '*.json' 2>/dev/null | wc -l)
newest=$(ls -t "$RECORDS_DIR"/*.json 2>/dev/null | head -1 | xargs -r basename)

branch_esc=$(printf '%s' "$branch" | sed 's/\\/\\\\/g; s/"/\\"/g')
newest_esc=$(printf '%s' "$newest" | sed 's/\\/\\\\/g; s/"/\\"/g')

printf '{"updated":"%s","records":%s,"fast_forward":"%s","branch":"%s","newest_record":"%s"}\n' \
    "$now" "$records" "$ff" "$branch_esc" "$newest_esc" > "$STATUS"

echo "$now records=$records ff=$ff $branch" >> "$LOG"
