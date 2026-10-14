#!/usr/bin/env bash
# harness-config-sync-status.sh - write the authority's config_sync record, truthfully.
#
# WHY THIS EXISTS
#   The CEO-kernel sentinel check `config_sync` reads
#   /root/.harness-config-autosync/status.json and reports UNKNOWN when it is absent:
#   "cannot tell whether config converges". On a CONSUMER host that record is written by
#   scripts/autosync.sh, which fetches a remote, fast-forwards, applies the committed tree
#   into ~/.dsh, and records result/detail/commit/converged.
#
#   The authority is NOT a consumer. It is the SOURCE of harness-config: its canonical
#   checkout is /root/code/harness-config and its canonical remote is the vault
#   (root@2.28.33.58:/srv/git/harness-config.git), a different provider. Porting
#   autosync.sh here would be wrong in three measured ways:
#     1. its default repo is $HOME/harness-config, which does not exist here;
#     2. this checkout's `origin` is /root/hc-main.bundle, a frozen bundle ON THE SAME DISK,
#        and its configured upstream `origin/main` is ee3a7e2f - fast-forwarding the source
#        of truth onto a stale snapshot is backwards;
#     3. no DSH engine on this host reads ~/.dsh, so applying presets is a no-op at best.
#   docs/mesh/140-PORT-CORE-AND-GAPS.md A2 records the same decision for the office's
#   converge-authority job: not ported, with the reason.
#
# WHAT IT MEASURES, AND WHAT "CONVERGED" MEANS HERE
#   On the authority, config converges when the canonical checkout's HEAD is PUBLISHED to the
#   canonical remote: `git ls-remote vault refs/heads/main` must equal local HEAD. That is the
#   same measurement journal-commit.sh makes after it pushes; this script only READS it and
#   writes the record the sentinel expects. It never fetches, commits, merges, resets, applies
#   or pushes anything.
#
#   result=clean     converged=true   local HEAD == canonical remote HEAD
#   result=attention converged=false  remote behind local (unpublished) or unreadable
#
# EXIT: 0 converged, 3 not converged / cannot verify (CONDITION, not fault), 2 cannot run.
#
# CHANGED 2026-10-14 (cron repair for config-sync-status; journal L3620/L3777):
#   * attention exited 1. 1 is ambiguous here; 3 is the reserved CONDITION_EXIT that
#     sources/cron-failures.py reads as "a job WORKING and reporting an external condition"
#     -- it ends a repair streak instead of extending it. The condition is still escalated:
#     the kernel's check_config_sync treats result != "clean" as HIGH.
#   * the DIVERGED message merged three different facts and called a workstream branch
#     "local main". It now names the branch HEAD is really on and says which side moved.
set -uo pipefail

REPO="${HARNESS_REPO:-/root/code/harness-config}"
REMOTE="${HARNESS_REMOTE:-vault}"
BRANCH="${HARNESS_BRANCH:-main}"
STATE="${HARNESS_STATE:-/root/.harness-config-autosync}"
STATUS="$STATE/status.json"
HOST="$(hostname)"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$STATE" 2>/dev/null || true
json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\n'; }

write_status() {  # <result> <detail> <commit> <converged>
  local result="$1" detail="$2" commit="$3" converged="$4"
  printf '{"result":"%s","detail":"%s","host":"%s","at":"%s","commit":"%s","converged":%s}\n' \
    "$result" "$(json_str "$detail")" "$HOST" "$NOW" "$(json_str "$commit")" "$converged" > "$STATUS" 2>/dev/null
  printf '%s [%s] %s\n' "$NOW" "$result" "$detail"
}

if [ ! -d "$REPO/.git" ]; then
  write_status cannot-run "not a git repo: $REPO" "" false
  exit 2
fi

LOCAL_FULL="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
if [ -z "$LOCAL_FULL" ]; then
  write_status cannot-run "cannot read HEAD in $REPO" "" false
  exit 2
fi
LOCAL_SHORT="$(git -C "$REPO" rev-parse --short HEAD)"
HEAD_BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
REMOTE_URL="$(git -C "$REPO" remote get-url "$REMOTE" 2>/dev/null || true)"
if [ -z "$REMOTE_URL" ]; then
  write_status attention "remote '$REMOTE' is not configured in $REPO; cannot verify convergence (HEAD is $HEAD_BRANCH $LOCAL_SHORT)" "$LOCAL_SHORT" false
  exit 3
fi

REMOTE_FULL="$(timeout 30 git -C "$REPO" ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')"
if [ -z "$REMOTE_FULL" ]; then
  write_status attention "cannot verify: $REMOTE_URL does not answer refs/heads/$BRANCH (network or credential); HEAD ($HEAD_BRANCH $LOCAL_SHORT) is UNPUBLISHED" "$LOCAL_SHORT" false
  exit 3
fi

if [ "$REMOTE_FULL" = "$LOCAL_FULL" ]; then
  write_status clean "$BRANCH $LOCAL_SHORT is published to $REMOTE_URL (remote HEAD read back and matches)" "$LOCAL_SHORT" true
  exit 0
fi

# Three different facts were all reported as DIVERGED (journal L3620). Say which one it is,
# and name the branch HEAD is really on: the shared checkout can be switched onto a workstream
# branch mid-session (journal L3777), and the old wording called that branch "local main".
if ! git -C "$REPO" cat-file -e "${REMOTE_FULL}^{commit}" 2>/dev/null; then
  REL="unclassified: $REMOTE_URL refs/heads/$BRANCH is ${REMOTE_FULL:0:7}, which is not in the local object store (this check never fetches)"
elif git -C "$REPO" merge-base --is-ancestor "$LOCAL_FULL" "$REMOTE_FULL" 2>/dev/null; then
  REL="behind: $REMOTE_URL refs/heads/$BRANCH (${REMOTE_FULL:0:7}) is ahead of HEAD ($LOCAL_SHORT)"
elif git -C "$REPO" merge-base --is-ancestor "$REMOTE_FULL" "$LOCAL_FULL" 2>/dev/null; then
  REL="ahead: HEAD ($LOCAL_SHORT) is local work the remote does not have yet (normal between writes and pushes)"
else
  REL="diverged: HEAD ($LOCAL_SHORT) and $REMOTE_URL refs/heads/$BRANCH (${REMOTE_FULL:0:7}) have both moved"
fi
ON_BRANCH=""
[ "$HEAD_BRANCH" = "$BRANCH" ] || ON_BRANCH="; the shared checkout is on '$HEAD_BRANCH', NOT on '$BRANCH' (journal L3777)"
write_status attention "not converged: $REL$ON_BRANCH" "$LOCAL_SHORT" false
exit 3
