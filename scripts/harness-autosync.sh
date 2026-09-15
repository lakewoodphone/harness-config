#!/usr/bin/env bash
# harness-autosync.sh — keep a machine's harness-config checkout current and applied.
#
# WHY THIS EXISTS
# `scripts/autosync.sh` serves the Linux nodes and `scripts/autosync.ps1` the Windows workstations.
# Neither is a macOS citizen, so Yocheved's Mac mini -- the machine she now runs the shop from -- had
# no convergence path at all. That is how its settings drifted into a state her engine could not use
# (a provider name no route defined) with nothing reporting it.
#
# It does three things, in this order, and reports what happened:
#   1. fetch and fast-forward the checkout;
#   2. apply it with scripts/harness-sync.mjs, which self-checks the merged settings and refuses to
#      install a document that names a provider no route defines;
#   3. write a status file a monitor (or the owner) can read.
#
# WHY NOT `--ff-only` ALONE, WHICH IS THE OBVIOUS ANSWER
# This machine is not a read-only mirror. Her agent APPENDS to the journal -- that is the whole point
# of the self-learning design, and an append-only log is exactly the kind of thing that produces a
# local commit. `git pull --ff-only` refuses the moment the local branch is ahead, so a *single* local
# journal commit would freeze her machine on old settings, old presets and an old model indefinitely.
# scripts/autosync.sh documents that failure precisely ("it LOOKED healthy while frozen, because the
# report went to a file nothing consumed") and then had to add divergence preservation for it.
#
# So this script takes the narrowest action that moves forward and never destroys anything:
#   * `git pull --rebase --autostash` -- replays local journal commits on top of the remote. A
#     journal is append-only, so this is the operation that matches what the data actually is.
#   * if the rebase does not apply cleanly, it ABORTS the rebase, leaves the working tree exactly as
#     it found it, and reports attention. It never resolves a conflict by choosing a side.
#   * it never resets, never force-pushes, and never deletes a commit.
#
# Exit codes: 0 clean/up-to-date · 1 attention (applied but something needs a human) · 2 cannot run.
set -uo pipefail

REPO="${HARNESS_REPO:-$HOME/code/harness-config}"
STATE="${HARNESS_STATE:-$HOME/.dsh-sync}"
LOG="$STATE/autosync.log"
STATUS="$STATE/status.json"
HOST="$(hostname)"

mkdir -p "$STATE" 2>/dev/null || exit 2

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }

# Node is what runs the harness, so it is what applies the config. Prefer the launcher's own copy.
NODE=""
for c in "$HOME/.local/node-v24.12.0-darwin-arm64/bin/node" "$(command -v node 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && NODE="$c" && break
done

write_status() { # result detail behind ahead
  cat > "$STATUS" <<JSON
{
  "host": "$HOST",
  "updated": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "repo": "$REPO",
  "result": "$1",
  "detail": "$2",
  "behind": ${3:-0},
  "ahead": ${4:-0},
  "branch": "$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
}
JSON
}

log "=== autosync start on $HOST ==="

if [ ! -d "$REPO/.git" ]; then
  log "FATAL: $REPO is not a git checkout"
  write_status "attention" "repo not a git checkout"
  exit 2
fi
if [ -z "$NODE" ]; then
  log "FATAL: no node found"
  write_status "attention" "node not found"
  exit 2
fi

BEFORE="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
AHEAD_BEFORE="$(git -C "$REPO" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"

# ---- 1. bring the checkout forward ------------------------------------------------------------
FETCH="$(git -C "$REPO" fetch --quiet origin 2>&1)"
if [ $? -ne 0 ]; then
  log "fetch FAILED: $FETCH"
  # A fetch failure is not fatal to the local apply: the tree on disk is at least as new as the last
  # successful run, and refusing to apply would leave the machine on stale settings for no gain.
  write_status "attention" "fetch failed (network?), applied local tree" "${AHEAD_BEFORE:-0}" 0
else
  PULL="$(git -C "$REPO" pull --rebase --autostash --quiet 2>&1)"
  if [ $? -ne 0 ]; then
    git -C "$REPO" rebase --abort >/dev/null 2>&1
    log "rebase did not apply cleanly, aborted; tree left untouched: $PULL"
    write_status "attention" "rebase conflict -- aborted, nothing destroyed"
    exit 1
  fi
  log "pull ok"
fi

AFTER="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
[ "$BEFORE" != "$AFTER" ] && log "moved $BEFORE -> $AFTER" || log "already at $AFTER"

# ---- 2. apply ---------------------------------------------------------------------------------
APPLY="$("$NODE" "$REPO/scripts/harness-sync.mjs" 2>&1)"
APPLY_RC=$?
echo "$APPLY" >> "$LOG"
if [ $APPLY_RC -ne 0 ]; then
  log "apply FAILED (rc=$APPLY_RC) -- settings left as they were"
  write_status "attention" "harness-sync refused: $(printf '%s' "$APPLY" | tail -1)"
  exit 1
fi
SUMMARY="$(printf '%s' "$APPLY" | grep -E '^\s+(install|verify):' | tr '\n' ';' | sed 's/  */ /g')"
log "apply ok: $SUMMARY"

# ---- 3. report --------------------------------------------------------------------------------
AHEAD_AFTER="$(git -C "$REPO" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
if [ "${AHEAD_AFTER:-0}" -gt 0 ]; then
  # Local commits (almost certainly her agent's journal entries) are not on the remote. That is not a
  # failure -- but it is not synced either, so it is reported rather than hidden.
  log "note: $AHEAD_AFTER local commit(s) not yet on the remote"
  write_status "attention" "applied; $AHEAD_AFTER local commit(s) ahead of origin" 0 "$AHEAD_AFTER"
  exit 1
fi

write_status "ok" "${SUMMARY:-applied}"
log "=== autosync done ==="
exit 0
