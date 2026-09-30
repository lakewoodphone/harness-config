#!/usr/bin/env bash
# Per-repo size/state check. Usage: sizecheck.sh <repo> [repo...]
echo "== disk =="
df -h "$HOME" | tail -1
echo "== repos =="
for r in "$@"; do
  [ -d "$r/.git" ] || { printf '%-58s (no .git)\n' "$r"; continue; }
  g=$(du -sm "$r/.git" 2>/dev/null | cut -f1)
  w=$(du -sm --exclude=.git "$r" 2>/dev/null | cut -f1)
  u=$(cd "$r" && git ls-files --others --exclude-standard -z 2>/dev/null | xargs -0 -r du -ck 2>/dev/null | tail -1 | cut -f1)
  st=$(cd "$r" && git stash list 2>/dev/null | wc -l | tr -d ' ')
  br=$(cd "$r" && git for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null | wc -l | tr -d ' ')
  rt=$(cd "$r" && git for-each-ref --format='%(refname:short)' refs/remotes 2>/dev/null | wc -l | tr -d ' ')
  printf '%-58s git=%6sM  wt=%6sM  untracked=%8sK  stashes=%s  branches=%s  remoteRefs=%s\n' \
    "$r" "${g:-?}" "${w:-?}" "${u:-0}" "$st" "$br" "$rt"
done
