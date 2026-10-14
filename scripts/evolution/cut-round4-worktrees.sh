#!/usr/bin/env bash
# Cut round-4 builder worktrees on the authority, each from the PRESERVED live tree
# (`preserve/live-tree-20261014`, commit 14ebb2322) so every builder starts from the code
# that is actually running rather than from a stale branch.
#
# One worktree per workstream, one owner per file. Do not reuse an existing worktree.
set -uo pipefail
BASE=/root/work/r4-preserve
cd "$BASE" || exit 1

BASE_COMMIT=$(git rev-parse HEAD)
echo "base commit: $BASE_COMMIT  ($(git log -1 --format=%s))"

cut() {
  local name="$1" branch="$2"
  local dir="/root/work/r4-$name"
  if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then
    echo "  $name: already exists -> $branch"
    return 0
  fi
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git worktree add "$dir" "$branch" >/dev/null 2>&1 && echo "  $name: branch $branch (existing)"
  else
    git worktree add -b "$branch" "$dir" "$BASE_COMMIT" >/dev/null 2>&1 && echo "  $name: branch $branch (new, from $BASE_COMMIT)"
  fi
  test -f "$dir/app/autopilot.py" && echo "     app/autopilot.py present, md5 $(md5sum "$dir/app/autopilot.py" | cut -c1-16)"
}

cut loop      r4/loop-convergence
cut bridge    r4/session-bridge
cut transport r4/silent-failure-transport
cut model     r4/model-runtime
cut memory    r4/memory-read

echo
echo "=== disk per worktree"
du -sh /root/work/r4-* 2>/dev/null
echo
echo "=== free"
df -h / | tail -1
free -m | head -2
