#!/usr/bin/env bash
# agent-fleet.sh — create, inspect and tear down a fleet of parallel coding-agent worktrees.
#
# The POSIX twin of agent-fleet.ps1, and it exists because the fleet is not a Windows idea: on this
# mesh there is no `pwsh` on secratary, linux-pc or the mac mini, so a PowerShell-only script would
# have made the whole capability unreachable on four of six machines. Same commands, same safety
# posture, same output shape.
#
# Design rationale and the research behind it: docs/parallel-agent-orchestration.md
#
# Safety posture (identical to the .ps1, deliberately):
#   * never touches the repository's main worktree — only worktrees it created under the fleet root
#   * refuses to create a fleet from a dirty base, because a branch cut from uncommitted work produces
#     a merge nobody can reason about
#   * refuses to remove a dirty worktree without --force
#   * never deletes branches; removing a worktree leaves the branch so work stays salvageable
#
# Usage:
#   agent-fleet.sh new   -n lpt-route,egress-wiring -r /path/to/repo
#   agent-fleet.sh status -r /path/to/repo
#   agent-fleet.sh doctor                      # can this machine host a fleet at all?
#   agent-fleet.sh clean  -r /path/to/repo
#   agent-fleet.sh rm    -n lpt-route -r /path/to/repo
#   agent-fleet.sh rmall  -r /path/to/repo
#
# Written for bash 3.2 (macOS) as well as 5.x: no associative arrays, no mapfile, no ${v,,}.

set -euo pipefail

ACTION=""
NAMES=""
REPO="."
ROOT=""
BASE="main"
FORCE=0

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

usage() { sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    new|status|doctor|clean|rm|rmall) ACTION="$1" ;;
    -n|--name) NAMES="${2:-}"; shift ;;
    -r|--repo) REPO="${2:-}"; shift ;;
    --root)    ROOT="${2:-}"; shift ;;
    --base)    BASE="${2:-}"; shift ;;
    -f|--force) FORCE=1 ;;
    -h|--help) usage 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[ -n "$ACTION" ] || usage 2

# ---------------------------------------------------------------- helpers

repo_path() {
  [ -e "$REPO/.git" ] || die "not a git repository: $REPO"
  (cd "$REPO" && pwd)
}

fleet_root() {
  local rp="$1"
  if [ -n "$ROOT" ]; then printf '%s' "$ROOT"; return; fi
  printf '%s/_worktrees/%s' "$(dirname "$rp")" "$(basename "$rp")"
}

slugify() { printf '%s' "$1" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9._-]/-/g'; }

git_ok() { git -C "$1" "${@:2}" >/dev/null 2>&1; }

# Print "path<TAB>branch" per agent/* worktree.
agent_worktrees() {
  local rp="$1"
  git -C "$rp" worktree list --porcelain 2>/dev/null | awk '
    /^worktree /   { path = substr($0, 10) }
    /^branch /     { br = substr($0, 8); sub(/^refs\/heads\//, "", br);
                     if (br ~ /^agent\//) printf "%s\t%s\n", path, br }
  '
}

dirty_count() { git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '; }

dir_mb() {
  [ -d "$1" ] || { printf '0'; return; }
  # BSD and GNU du both accept -sm; awk sums in case of nested output.
  du -sm "$1" 2>/dev/null | awk '{s+=$1} END {printf "%d", s+0}'
}

artifact_count() {
  local n=0
  for pat in '_pt_*' '__pycache__' '.gradle' 'node_modules' '.pytest_cache'; do
    c=$(find "$1" -type d -name "$pat" 2>/dev/null | wc -l | tr -d ' ')
    n=$((n + c))
  done
  printf '%d' "$n"
}

# ---------------------------------------------------------------- actions

cmd_doctor() {
  local rp; rp="$(repo_path)"
  local fr; fr="$(fleet_root "$rp")"
  local ok=1

  echo "repo:       $rp"
  echo "fleet root: $fr"
  echo
  printf '%-28s %s\n' "git"        "$(git --version 2>/dev/null || echo MISSING)"
  printf '%-28s %s\n' "python3"    "$(python3 --version 2>/dev/null || echo 'MISSING (python3 is optional)')"
  printf '%-28s %s\n' "bash"       "${BASH_VERSION:-unknown}"

  if git -C "$rp" worktree list >/dev/null 2>&1; then
    printf '%-28s %s\n' "worktrees supported" "yes"
  else
    printf '%-28s %s\n' "worktrees supported" "NO — git too old"; ok=0
  fi

  # Worktree root must be writable, or 'new' will fail at the worst moment.
  local parent; parent="$(dirname "$fr")"
  mkdir -p "$parent" 2>/dev/null || true
  if [ -w "$parent" ]; then
    printf '%-28s %s\n' "fleet root writable" "yes ($parent)"
  else
    printf '%-28s %s\n' "fleet root writable" "NO ($parent)"; ok=0
  fi

  # This machine must not itself BE a linked worktree — a fleet created inside a worktree nests
  # worktrees, which git supports poorly and nobody can reason about.
  local gitdir; gitdir="$(git -C "$rp" rev-parse --git-dir 2>/dev/null || echo '')"
  case "$gitdir" in
    *"/worktrees/"*) printf '%-28s %s\n' "nested worktree" "YES — do not create a fleet from here"; ok=0 ;;
    *)               printf '%-28s %s\n' "nested worktree" "no" ;;
  esac

  local st; st="$(git -C "$rp" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$st" = "0" ]; then printf '%-28s %s\n' "base clean" "yes"; else printf '%-28s %s\n' "base clean" "NO ($st changed) — 'new' will refuse"; fi

  echo
  if [ "$ok" = "1" ]; then echo "READY: this machine can host a fleet."; else echo "NOT READY: see the failures above."; exit 1; fi
}

cmd_new() {
  [ -n "$NAMES" ] || die "-n is required for 'new' (comma-separated slugs)"

  local rp; rp="$(repo_path)"
  local fr; fr="$(fleet_root "$rp")"

  local st; st="$(git -C "$rp" status --porcelain | wc -l | tr -d ' ')"
  if [ "$st" != "0" ]; then
    die "refusing to create a fleet: '$rp' has $st uncommitted change(s). A branch cut from a dirty base produces a merge nobody can reason about. Commit or stash first."
  fi

  git -C "$rp" fetch --quiet origin 2>/dev/null || echo "warning: fetch failed (continuing against local refs)" >&2
  mkdir -p "$fr"

  local head; head="$(git -C "$rp" rev-parse --short HEAD)"
  echo "base $BASE @ $head — creating worktrees under $fr"
  echo

  local made=0
  local IFS=','
  for raw in $NAMES; do
    unset IFS
    local slug; slug="$(slugify "$(printf '%s' "$raw" | sed 's/^ *//; s/ *$//')")"
    [ -n "$slug" ] || continue
    local path branch
    path="$fr/$slug"
    branch="agent/$slug"

    if [ -e "$path" ]; then echo "SKIP  $slug (path exists)"; continue; fi
    if git -C "$rp" rev-parse --verify --quiet "refs/heads/$branch" >/dev/null; then
      # Attach to an existing branch so an interrupted run can be resumed.
      if git -C "$rp" worktree add --quiet "$path" "$branch" 2>/dev/null; then
        echo "OK    $slug  ->  $path  [$branch]  (existing branch)"
        made=$((made + 1))
      else
        echo "FAIL  $slug"
      fi
    else
      if git -C "$rp" worktree add --quiet -b "$branch" "$path" "$BASE" 2>/dev/null; then
        echo "OK    $slug  ->  $path  [$branch]"
        made=$((made + 1))
      else
        echo "FAIL  $slug"
      fi
    fi
    IFS=','
  done
  echo
  echo "$made worktree(s) ready. Tell each agent its absolute path, and that it may not push."
}

cmd_status() {
  local rp; rp="$(repo_path)"
  local any=0 total=0
  echo "repo:  $rp"
  echo
  printf '%-30s %-34s %-7s %-10s %-8s\n' 'name' 'branch' 'dirty' 'artifacts' 'MB'
  echo "------------------------------------------------------------------------------------------"
  while IFS="$(printf '\t')" read -r path branch; do
    [ -n "$path" ] || continue
    any=1
    local mb; mb="$(dir_mb "$path")"
    total=$((total + mb))
    printf '%-30s %-34s %-7s %-10s %-8s\n' "$(basename "$path")" "$branch" "$(dirty_count "$path")" "$(artifact_count "$path")" "$mb"
  done <<EOF
$(agent_worktrees "$rp")
EOF
  if [ "$any" = "0" ]; then echo "no agent worktrees."; return; fi
  echo "------------------------------------------------------------------------------------------"
  echo "total on disk: ${total} MB"
  echo
  echo "Reminder: dirty > 0 on a branch you intend to merge means the work is not committed."
}

cmd_clean() {
  local rp; rp="$(repo_path)"
  local n=0
  for path in $(agent_worktrees "$rp" | cut -f1); do
    for pat in '_pt_*' '__pycache__' '.pytest_cache'; do
      while IFS= read -r d; do
        [ -n "$d" ] || continue
        rm -rf "$d"; n=$((n + 1))
      done <<EOF
$(find "$path" -type d -name "$pat" 2>/dev/null)
EOF
    done
    echo "cleaned $(basename "$path")"
  done
  echo
  echo "removed $n artifact director(ies)."
}

cmd_rm() {
  [ -n "$NAMES" ] || die "-n is required for 'rm'"
  local rp; rp="$(repo_path)"
  local fr; fr="$(fleet_root "$rp")"
  local IFS=','
  for raw in $NAMES; do
    unset IFS
    local slug; slug="$(slugify "$(printf '%s' "$raw" | sed 's/^ *//; s/ *$//')")"
    local path; path="$fr/$slug"
    if [ ! -e "$path" ]; then echo "SKIP  $slug (no such worktree)"; IFS=','; continue; fi
    if [ "$FORCE" = "1" ]; then
      git -C "$rp" worktree remove --force "$path" && echo "OK    removed $slug  (branch agent/$slug kept)"
    else
      if git -C "$rp" worktree remove "$path" 2>/dev/null; then
        echo "OK    removed $slug  (branch agent/$slug kept)"
      else
        echo "FAIL  $slug — dirty worktree: commit, or pass --force to discard"
      fi
    fi
    IFS=','
  done
}

cmd_rmall() {
  local rp; rp="$(repo_path)"
  local removed=0
  while IFS="$(printf '\t')" read -r path branch; do
    [ -n "$path" ] || continue
    local slug; slug="$(basename "$path")"
    if [ "$FORCE" != "1" ] && [ "$(dirty_count "$path")" != "0" ]; then
      echo "SKIP  $slug (dirty; commit or pass --force)"; continue
    fi
    if [ "$FORCE" = "1" ]; then
      git -C "$rp" worktree remove --force "$path" && { echo "OK    removed $slug  (branch kept)"; removed=$((removed+1)); }
    else
      git -C "$rp" worktree remove "$path" 2>/dev/null && { echo "OK    removed $slug  (branch kept)"; removed=$((removed+1)); }
    fi
  done <<EOF
$(agent_worktrees "$rp")
EOF
  git -C "$rp" worktree prune 2>/dev/null || true
  echo
  echo "$removed removed. Branches are kept on purpose so unmerged work stays salvageable."
  echo "Inspect with: git -C $rp branch --list 'agent/*'"
}

case "$ACTION" in
  new)    cmd_new ;;
  status) cmd_status ;;
  doctor) cmd_doctor ;;
  clean)  cmd_clean ;;
  rm)     cmd_rm ;;
  rmall)  cmd_rmall ;;
esac
