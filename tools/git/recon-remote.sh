#!/usr/bin/env bash
# Read-only git recon for one machine. Fetch only (cannot touch a working tree).
# Usage: bash recon-remote.sh /root/to/scan
ROOT="${1:-$HOME}"
printf 'path\tbranch\thead\theadDate\tupstream\tahead\tbehind\tdirty\tuntracked\tstashes\tbranches\tremotes\tfetchExit\n'
find "$ROOT" -maxdepth 3 -name .git \( -type d -o -type f \) 2>/dev/null | sort | while read -r g; do
  repo=$(dirname "$g")
  cd "$repo" 2>/dev/null || continue
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  head=$(git rev-parse --short HEAD 2>/dev/null)
  headdate=$(git log -1 --format=%cI 2>/dev/null)
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)
  git fetch --all --prune --quiet >/dev/null 2>&1
  fe=$?
  ahead=""; behind=""
  if [ -n "$upstream" ] && [ "$fe" -eq 0 ]; then
    c=$(git rev-list --left-right --count "$upstream...HEAD" 2>/dev/null)
    behind=$(printf '%s' "$c" | awk '{print $1}')
    ahead=$(printf '%s' "$c" | awk '{print $2}')
  fi
  dirty=$(git status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')
  untracked=$(git status --porcelain 2>/dev/null | grep -c '^??')
  stashes=$(git stash list 2>/dev/null | wc -l | tr -d ' ')
  branches=$(git for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null | wc -l | tr -d ' ')
  remotes=$(git remote 2>/dev/null | tr '\n' ',' )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$repo" "$branch" "$head" "$headdate" "$upstream" "$ahead" "$behind" "$dirty" "$untracked" "$stashes" "$branches" "$remotes" "$fe"
done
