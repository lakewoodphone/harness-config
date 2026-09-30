#!/usr/bin/env bash
# ADDITIVE-ONLY git safety snapshot, one directory per REPOSITORY (worktrees share it).
# Never checks out, commits, resets, drops or deletes anything.
# Usage: preserve3.sh <backupRoot> [--no-bundle] [--from <listFile>] [path...]
set -u
BK="$1"; shift
NOBUNDLE=0
if [ "${1:-}" = "--no-bundle" ]; then NOBUNDLE=1; shift; fi
if [ "${1:-}" = "--from" ]; then LISTFILE="$2"; shift 2; set -- $(cat "$LISTFILE") "$@"; fi
mkdir -p "$BK"
echo "backup root: $BK   paths: $#   nobundle=$NOBUNDLE"
FREE=$(df -Pm "$BK" | tail -1 | awk '{print $4}')
echo "freeMB: $FREE   started: $(date -u +%FT%TZ)"

slug() { printf '%s' "$1" | sed 's|^[A-Za-z]:||; s|^/||; s|[/.:\\ ]|_|g'; }

for r in "$@"; do
  [ -e "$r/.git" ] || { echo "SKIP (no .git): $r"; continue; }
  cd "$r" 2>/dev/null || { echo "SKIP (cd): $r"; continue; }
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  [ -n "$common" ] || { echo "SKIP (no common): $r"; continue; }
  name=$(slug "$common")
  d="$BK/$name"
  mkdir -p "$d"
  sub="$d/wt-$(slug "$r")"
  mkdir -p "$sub"

  # ---- per working tree ----
  {
    echo "repo: $r"; echo "snapshot: $(date -u +%FT%TZ)"
    echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    echo "head: $(git rev-parse HEAD 2>/dev/null)"
    echo "headDate: $(git log -1 --format=%cI 2>/dev/null)"
    echo "upstream: $(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
    echo "gitdir: $(git rev-parse --git-dir 2>/dev/null)"
    echo "common: $common"
  } > "$sub/state.txt"
  n_dirty=$(git status --porcelain=v1 2>/dev/null | wc -l | tr -d ' ')
  git status --porcelain=v1 > "$sub/status.txt" 2>/dev/null
  git diff > "$sub/worktree-tracked.patch" 2>/dev/null
  git diff --cached > "$sub/worktree-staged.patch" 2>/dev/null
  git ls-files --others --exclude-standard -z 2>/dev/null | xargs -0 -r ls -l --time-style=long-iso > "$sub/untracked-listing.txt" 2>/dev/null
  n_unt=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')

  # ---- repo-level, once ----
  if [ ! -f "$d/.repo-captured" ]; then
    git for-each-ref --format='%(refname)%09%(objectname)%09%(committerdate:iso)' > "$d/refs.tsv" 2>/dev/null
    git reflog --all --date=iso > "$d/reflog.txt" 2>/dev/null
    git remote -v > "$d/remotes.txt" 2>/dev/null
    git count-objects -vH > "$d/count-objects.txt" 2>/dev/null
    touch "$d/.repo-captured"
  fi
  git stash list --format='%gd%09%H%09%ci%09%gs' > "$d/stashes.tsv" 2>/dev/null

  n=0
  for sha in $(git stash list --format='%H' 2>/dev/null); do
    git update-ref "refs/lpt-backup/stash/$n" "$sha" 2>/dev/null && n=$((n+1))
  done
  i=0
  for sha in $(git stash list --format='%H' 2>/dev/null); do
    if [ ! -f "$d/stash-$i.patch" ]; then
      git stash show -p --include-untracked "$i" > "$d/stash-$i.patch" 2>/dev/null || git stash show -p "$i" > "$d/stash-$i.patch" 2>/dev/null
      git ls-tree -r --name-only "$sha" > "$d/stash-$i-tree.txt" 2>/dev/null
      printf 'stash@{%s} %s\n' "$i" "$sha" >> "$d/pinned.txt"
    fi
    i=$((i+1))
  done

  if [ "$NOBUNDLE" -eq 0 ] && [ ! -f "$d/full.bundle" ]; then
    t0=$(date +%s)
    git bundle create "$d/full.bundle" --all > "$d/bundle.log" 2>&1
    git bundle verify "$d/full.bundle" > "$d/bundle-verify.txt" 2>&1
    printf 'bundleMB: %s  bundleSeconds: %s\n' "$(du -m "$d/full.bundle" 2>/dev/null | cut -f1)" "$(( $(date +%s) - t0 ))" >> "$d/state.txt"
  fi
  echo "OK  $(basename "$d")  stashes=$n  dirty=$n_dirty  untracked=$n_unt"
done
echo "PRESERVE3 DONE $(date -u +%FT%TZ)"
