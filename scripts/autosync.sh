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
# DIVERGENCE: PRESERVE FIRST, THEN REPORT (2026-09-14) — same fix as autosync.ps1, same reason.
# Refusing to merge was right; refusing to *preserve* was the defect. Measured four times in one day:
# the moment a machine held a commit the remote did not have, `git pull --ff-only` refused, the run
# ended 'attention'/1, and that machine kept its OLD settings, OLD presets and OLD launcher
# indefinitely — a blind machine also cannot receive a model-failover flip, so it can sit on a dead
# model. It LOOKED healthy while frozen, because the report went to a file nothing consumed.
#
# So the refusal now applies to the DESTINATION, not to the commits. When this checkout is ahead:
#   1. a plain `git push` is attempted first (the same refspec this script always used). If it is
#      accepted there was no real divergence and the machine has simply converged.
#   2. if it is REFUSED, the local commits are pushed to a normal, non-forced side ref
#          refs/heads/diverged-<host>-<UTC date>
#      which cannot fail a fast-forward and destroys nothing. The run then stops 'attention'/1,
#      because a machine that cannot fast-forward is not syncing and that must be visible.
# Still no merge, no rebase, no reset, no force, no guess (LESSONS L33, PAIN P8/P47c).
# Recovery, exactly:  git fetch origin 'refs/heads/diverged-*:refs/remotes/origin/diverged-*'
#                     git log origin/diverged-<host>-<date>   ·   git cherry-pick <sha>
#
# Status contract (kept in step with scripts/autosync.ps1):
#   * $STATE/status.json        the per-host run record. Its shape is UNCHANGED — the attention plugin
#                               and the CEO-kernel sentinel read result/detail/at from it — so fields
#                               are only ever added, never renamed or removed.
#   * ~/.dsh-sync-status/status.json  machine-readable health for a monitor, mirroring the model-watch
#                               idiom: updated, result, detail, behind, ahead, branch,
#                               local_commits_preserved (+ host, diverge_refs, check_failed).
#
# FOLLOW-UP (deliberately NOT done here — it belongs in the kernel, not in the deploy path): another
# session holds ~/ceo-kernel dirty and mid-deploy, so this script only WRITES the status. When that
# tree is quiet, a `sync_frozen` sentinel check should read ~/.dsh-sync-status/status.json and
# escalate to the owner when `ahead > 0` or `local_commits_preserved` is true.
#
# Exit codes: 0 clean · 1 attention · 2 cannot run.
set -uo pipefail

REPO="${HARNESS_REPO:-$HOME/harness-config}"
STATE="${HARNESS_STATE:-$HOME/.harness-config-autosync}"
SYNC_STATUS_DIR="${HARNESS_SYNC_STATUS_DIR:-$HOME/.dsh-sync-status}"
PY="${HARNESS_PYTHON:-python3}"
LOG="$STATE/autosync.log"
STATUS="$STATE/status.json"
SYNC_STATUS="$SYNC_STATUS_DIR/status.json"
HOST="$(hostname)"
mkdir -p "$STATE" 2>/dev/null || exit 2

log() { echo "$1"; }

# JSON without a dependency: jq is not guaranteed on this box.
json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n'; }

# write_sync_status <result> <detail> <behind> <ahead> <preserved-bool> [halfwritten-json]
# The fixed machine-readable schema. Written on EVERY outcome — a frozen machine has to be able to
# say so. Values are tokens and numbers (except the free-text detail), so escaping the detail is
# enough to keep the document valid.
write_sync_status() {
  local result="$1" detail="$2" behind="$3" ahead="$4" preserved="$5" extra="${6:-}"
  [ -n "$result" ] || result=unknown
  [ -n "$behind" ] || behind=0
  [ -n "$ahead" ]  || ahead=0
  [ -n "$preserved" ] || preserved=false
  [ -n "$BRANCH" ] || BRANCH=unknown
  local at; at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$SYNC_STATUS_DIR" 2>/dev/null
  printf '{"updated":"%s","result":"%s","detail":"%s","behind":%s,"ahead":%s,"branch":"%s","local_commits_preserved":%s%s}\n' \
    "$at" "$result" "$(json_str "$detail")" "$behind" "$ahead" "$(json_str "$BRANCH")" "$preserved" \
    "${extra:+,$extra}" > "$SYNC_STATUS" 2>/dev/null
}

record() {  # record <result> <detail> [extra-json]
  local result="$1" detail="$2" extra="${3:-}"
  local at; at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"result":"%s","detail":"%s","host":"%s","at":"%s"%s}\n' \
    "$result" "$(json_str "$detail")" "$HOST" "$at" "${extra:+,$extra}" > "$STATUS"
  printf '%s [%s] %s\n' "$at" "$result" "$(json_str "$detail")" >> "$LOG"
  log "$at [$result] $detail"
}

# ── 0. preconditions ────────────────────────────────────────────────────────────────────────────────
[ -d "$REPO/.git" ] || { record cannot-run "not a git repo: $REPO"; write_sync_status cannot-run "not a git repo: $REPO" 0 0 false; exit 2; }
command -v git >/dev/null 2>&1 || { record cannot-run "git not on PATH"; write_sync_status cannot-run "git not on PATH" 0 0 false; exit 2; }
"$PY" -c 'import yaml' 2>/dev/null || { record cannot-run "no python3 with PyYAML ($PY)"; write_sync_status cannot-run "no python3 with PyYAML ($PY)" 0 0 false; exit 2; }

cd "$REPO" || { record cannot-run "cannot cd $REPO"; write_sync_status cannot-run "cannot cd $REPO" 0 0 false; exit 2; }

# ── 1. fetch, and report a dirty tree without letting it block ──────────────────────────────────────
git fetch --quiet --prune 2>/dev/null || {
  record attention "git fetch failed (offline or remote down)"
  write_sync_status attention "git fetch failed (offline or remote down)" 0 0 false
  exit 1
}

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo master)"
COUNTS="$(git rev-list --left-right --count "origin/$BRANCH...HEAD" 2>/dev/null || echo '0 0')"
BEHIND="$(echo "$COUNTS" | awk '{print $1}')"
AHEAD="$(echo "$COUNTS" | awk '{print $2}')"
[ -n "$BEHIND" ] || BEHIND=0
[ -n "$AHEAD" ] || AHEAD=0
DIRTY="$(git status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
DIRTY_NAMES="$(git status --porcelain --untracked-files=no | head -5 | cut -c4- | paste -sd ', ' -)"

# ── 2. AHEAD ⇒ PRESERVE FIRST, before any pull can move HEAD. This is the fix ───────────────────────
#  A plain `git push` first (the same refspec this script always used): if origin accepts it, the
#  branch fast-forwarded, there was no real divergence, and the machine has simply converged.
#  A REFUSED push is the divergence signal; then the local commits go to a new, non-forced ref that
#  cannot fail a fast-forward. Nothing is merged, rebased, reset or forced — only the destination
#  changed, and the run still ends 'attention' because a machine that cannot fast-forward is not
#  syncing.
if [ "$AHEAD" -gt 0 ]; then
  SAFE_HOST="$(printf '%s' "$HOST" | tr -c 'A-Za-z0-9._-' '-')"
  DIVERGE_REF="refs/heads/diverged-$SAFE_HOST-$(date -u +%Y%m%d)"
  HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"

  if git -c core.autocrlf=false push --quiet 2>/dev/null; then
    log "    $AHEAD commit(s) ahead went to origin — fast-forwardable, nothing to preserve"
  else
    if git -c core.autocrlf=false push --quiet origin "HEAD:$DIVERGE_REF" 2>/dev/null; then
      DETAIL="histories diverged ($BEHIND behind / $AHEAD ahead) — local commits are SAFE on $DIVERGE_REF (HEAD $HEAD_SHA); fast-forward refused, so this machine is NOT syncing. Needs a human."
      record attention "$DETAIL" "\"behind\":$BEHIND,\"ahead\":$AHEAD,\"local_commits_preserved\":true,\"preserved_ref\":\"$DIVERGE_REF\""
      write_sync_status attention "$DETAIL" "$BEHIND" "$AHEAD" true "\"host\":\"$(json_str "$HOST")\",\"repo\":\"$(json_str "$REPO")\",\"commit\":\"$(json_str "$HEAD_SHA")\",\"preserved_ref\":\"$DIVERGE_REF\""
      log "    recover with: git fetch origin 'refs/heads/diverged-*:refs/remotes/origin/diverged-*'  then  git log origin/diverged-$SAFE_HOST-*"
      exit 1
    fi

    # Could not even create the side ref (no push rights, remote read-only, network died mid-run).
    # The commits are then NOT recoverable from anywhere but this checkout, and saying only
    # "diverged" would hide that. This is worse than a plain refusal, not better. preserved_ref is
    # left out on purpose — naming a ref that was never created sends a future session to look for
    # something that is not there.
    DETAIL="histories diverged ($BEHIND behind / $AHEAD ahead) AND the local commits could NOT be pushed to $DIVERGE_REF — they exist only in this checkout; nobody else can see them. Needs a human."
    record attention "$DETAIL" "\"behind\":$BEHIND,\"ahead\":$AHEAD,\"local_commits_preserved\":false"
    write_sync_status attention "$DETAIL" "$BEHIND" "$AHEAD" false "\"host\":\"$(json_str "$HOST")\",\"repo\":\"$(json_str "$REPO")\",\"commit\":\"$(json_str "$HEAD_SHA")\""
    exit 1
  fi
fi

# ── 2b. fast-forward; never merge ───────────────────────────────────────────────────────────────────
if [ "$BEHIND" -gt 0 ]; then
  if ! git -c core.autocrlf=false pull --ff-only --quiet 2>/dev/null; then
    # Unreachable in practice while the block above stands: with AHEAD=0 a refused pull cannot be a
    # divergence. Kept as the honest fallback if that ever changes.
    DETAIL="pull --ff-only refused: histories diverged ($BEHIND behind / $AHEAD ahead) and nothing was preserved. Needs a human."
    record attention "$DETAIL" "\"behind\":$BEHIND,\"ahead\":$AHEAD"
    write_sync_status attention "$DETAIL" "$BEHIND" "$AHEAD" false
    exit 1
  fi
fi

# ── 3. apply a snapshot of HEAD, then prove it converged ────────────────────────────────────────────
SNAP="$(mktemp -d "${TMPDIR:-/tmp}/harness-snap-XXXXXX")"
TAR="$(mktemp "${TMPDIR:-/tmp}/harness-snap-XXXXXX.tar")"
cleanup() { rm -rf "$SNAP" "$TAR" 2>/dev/null; }
trap cleanup EXIT

if ! git archive --format=tar --output="$TAR" HEAD 2>/dev/null; then
  record attention "could not export HEAD (git archive failed)"
  write_sync_status attention "could not export HEAD (git archive failed)" "$BEHIND" "$AHEAD" false
  exit 1
fi
if ! tar -xf "$TAR" -C "$SNAP" 2>/dev/null; then
  record attention "could not unpack the HEAD snapshot"
  write_sync_status attention "could not unpack the HEAD snapshot" "$BEHIND" "$AHEAD" false
  exit 1
fi

APPLY="$("$PY" "$SNAP/scripts/sync.py" 2>&1)"
if [ $? -ne 0 ]; then
  record attention "sync.py failed against the committed snapshot"
  write_sync_status attention "sync.py failed against the committed snapshot" "$BEHIND" "$AHEAD" false
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
  write_sync_status clean "at $COMMIT; $APPLIED" "$BEHIND" "$AHEAD" false \
    "\"host\":\"$(json_str "$HOST")\",\"repo\":\"$(json_str "$REPO")\",\"commit\":\"$(json_str "$COMMIT")\""
  exit 0
fi
record attention "apply did NOT converge — a second run still reports pending changes; dirty files: $DIRTY_NAMES" \
  "\"commit\":\"$COMMIT\",\"converged\":false,\"dirty\":$DIRTY"
write_sync_status attention "apply did NOT converge — a second run still reports pending changes" "$BEHIND" "$AHEAD" false \
  "\"host\":\"$(json_str "$HOST")\",\"repo\":\"$(json_str "$REPO")\",\"commit\":\"$(json_str "$COMMIT")\""
exit 1
