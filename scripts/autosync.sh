#!/usr/bin/env bash
# autosync.sh — the Linux half of harness-config convergence.
#
# Same contract as scripts/autosync.ps1 (which serves the Windows workstations): fast-forward the repo,
# apply the COMMITTED tree into DSH_HOME, prove the apply converged, send commits that were made but
# never pushed, and write down what happened. The always-on server needs this because it now runs a
# harness engine of its own (the phone's), and that engine reads `~/.dsh/.agent-presets`.
#
# Why the snapshot matters (learned the hard way on ZABZ-YOGA, 2026-09-11): applying the *working tree*
# would publish somebody's half-written preset, while refusing to apply while the tree is dirty means
# committed changes never arrive at all — which is how the Yoga sat `dirty` and drifted for hours. So the
# apply runs against `git archive HEAD` in a temp directory: committed changes land, in-flight edits are
# neither published nor lost, and a dirty tree is reported rather than blocking.
#
# It never commits, merges, rebases, stashes, resets or force-pushes. Divergence is reported.
#
# Exit codes: 0 clean · 1 attention · 2 cannot run.
set -uo pipefail

REPO="${HARNESS_REPO:-$HOME/harness-config}"
STATE="${HARNESS_STATE:-$HOME/.harness-config-autosync}"
PY="${HARNESS_PYTHON:-python3}"
LOG="$STATE/autosync.log"
STATUS="$STATE/status.json"
HOST="$(hostname)"
mkdir -p "$STATE" 2>/dev/null || exit 2

log() { echo "$1"; }

# JSON without a dependency: jq is not guaranteed on this box.
json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n'; }
record() {  # record <result> <detail> [extra-json]
  local result="$1" detail="$2" extra="${3:-}"
  local at; at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"result":"%s","detail":"%s","host":"%s","at":"%s"%s}\n' \
    "$result" "$(json_str "$detail")" "$HOST" "$at" "${extra:+,$extra}" > "$STATUS"
  printf '%s [%s] %s\n' "$at" "$result" "$(json_str "$detail")" >> "$LOG"
  log "$at [$result] $detail"
}

# ── 0. preconditions ────────────────────────────────────────────────────────────────────────────────
[ -d "$REPO/.git" ] || { record cannot-run "not a git repo: $REPO"; exit 2; }
command -v git >/dev/null 2>&1 || { record cannot-run "git not on PATH"; exit 2; }
"$PY" -c 'import yaml' 2>/dev/null || { record cannot-run "no python3 with PyYAML ($PY)"; exit 2; }

cd "$REPO" || { record cannot-run "cannot cd $REPO"; exit 2; }

# ── 1. fetch, and report a dirty tree without letting it block ──────────────────────────────────────
git fetch --quiet --prune 2>/dev/null || { record attention "git fetch failed (offline or remote down)"; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo master)"
COUNTS="$(git rev-list --left-right --count "origin/$BRANCH...HEAD" 2>/dev/null || echo '0 0')"
BEHIND="$(echo "$COUNTS" | awk '{print $1}')"
AHEAD="$(echo "$COUNTS" | awk '{print $2}')"
DIRTY="$(git status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
DIRTY_NAMES="$(git status --porcelain --untracked-files=no | head -5 | cut -c4- | paste -sd ', ' -)"

# ── 2. fast-forward; never merge ────────────────────────────────────────────────────────────────────
if [ "$AHEAD" -gt 0 ]; then
  record attention "local commits ahead of origin ($AHEAD) — this checkout is not a place to commit; needs a human"
  exit 1
fi
if [ "$BEHIND" -gt 0 ]; then
  if ! git -c core.autocrlf=false pull --ff-only --quiet 2>/dev/null; then
    record attention "pull --ff-only refused: histories diverged ($BEHIND behind)"
    exit 1
  fi
fi

# ── 3. apply a snapshot of HEAD, then prove it converged ────────────────────────────────────────────
SNAP="$(mktemp -d "${TMPDIR:-/tmp}/harness-snap-XXXXXX")"
TAR="$(mktemp "${TMPDIR:-/tmp}/harness-snap-XXXXXX.tar")"
cleanup() { rm -rf "$SNAP" "$TAR" 2>/dev/null; }
trap cleanup EXIT

if ! git archive --format=tar --output="$TAR" HEAD 2>/dev/null; then
  record attention "could not export HEAD (git archive failed)"; exit 1
fi
if ! tar -xf "$TAR" -C "$SNAP" 2>/dev/null; then
  record attention "could not unpack the HEAD snapshot"; exit 1
fi

APPLY="$("$PY" "$SNAP/scripts/sync.py" 2>&1)"
if [ $? -ne 0 ]; then
  record attention "sync.py failed against the committed snapshot"
  exit 1
fi
VERIFY="$("$PY" "$SNAP/scripts/sync.py" --dry-run 2>&1)"
CONVERGED=true
echo "$VERIFY" | grep -q 'WOULD' && CONVERGED=false

APPLIED="$(printf '%s\n' "$APPLY" | grep -E 'written|applied' | paste -sd ' | ' -)"
[ -n "$APPLIED" ] || APPLIED="nothing to apply"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null)"

if [ "$CONVERGED" = true ]; then
  record clean "at $COMMIT; $APPLIED" "\"commit\":\"$COMMIT\",\"converged\":true,\"dirty\":$DIRTY"
  exit 0
fi
record attention "apply did NOT converge — a second run still reports pending changes; dirty files: $DIRTY_NAMES" \
  "\"commit\":\"$COMMIT\",\"converged\":false,\"dirty\":$DIRTY"
exit 1
