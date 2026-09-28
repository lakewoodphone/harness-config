#!/bin/bash
# sync-repos.sh - bring every repo on this machine toward its upstream. Conservative by design.
#
# NEVER: reset, clean, rebase, stash, force, delete a branch, touch a dirty working tree.
# DOES:  fetch | fast-forward when purely behind and the tracked tree is clean |
#        push when purely ahead | report everything else untouched.
#
# Why this exists: harness-config is synced by autosync.sh, but the OTHER repos (lpt-hub,
# personal-secretary-mvp, ha-config, unified-search, ceo-kernel, ...) had no unattended sync at all,
# so each machine drifted on its own. This reports and converges only what git can prove is safe.
#
# Usage:  bash sync-repos.sh            -> applies
#         bash sync-repos.sh --dry-run  -> reports only
set -u

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

printf 'machine\trepo\tbranch\tdirty\tahead\tbehind\taction\tresult\n'

scan_dir() {
  local d="$1"
  [ -d "$d" ] || return 0
  # worktree .git is a file; accept both.
  git -C "$d" rev-parse --git-dir >/dev/null 2>&1 || return 0
  local name; name=$(basename "$d")
  case "$name" in
    harness-config|_*|.*|*-backup-*|*.bak-*|*-pre-unify-*|*worktree*) return 0 ;;
  esac

  local branch dirty up ahead behind
  branch=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ "$branch" = "HEAD" ]; then
    printf '%s\t%s\t%s\t-\t-\t-\tSKIP-DETACHED\tleft as found\n' "$HOSTNAME" "$name" "HEAD"; return 0
  fi
  dirty=$(git -C "$d" status --porcelain --untracked-files=no 2>/dev/null | wc -l)
  up=$(git -C "$d" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
  if [ -z "$up" ]; then
    printf '%s\t%s\t%s\t%s\t-\t-\tNO-UPSTREAM\tleft as found\n' "$HOSTNAME" "$name" "$branch" "$dirty"; return 0
  fi

  # Fetch is the only network step, and it is read-only.
  if ! git -C "$d" fetch --quiet --prune 2>/dev/null; then
    printf '%s\t%s\t%s\t%s\t-\t-\tFETCH-FAILED\tunreachable, untouched\n' "$HOSTNAME" "$name" "$branch" "$dirty"; return 0
  fi
  ahead=$(git -C "$d" rev-list --count "$up"..HEAD 2>/dev/null || echo '?')
  behind=$(git -C "$d" rev-list --count HEAD.."$up" 2>/dev/null || echo '?')

  if [ "$ahead" = "0" ] && [ "$behind" = "0" ]; then
    printf '%s\t%s\t%s\t%s\t0\t0\tOK\tin step with %s\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$up"; return 0
  fi

  if [ "$ahead" -gt 0 ] && [ "$behind" -gt 0 ]; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\tDIVERGED\treport only, nothing moved\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$ahead" "$behind"; return 0
  fi

  if [ "$ahead" -gt 0 ]; then
    if [ "$DRY" = "1" ]; then
      printf '%s\t%s\t%s\t%s\t%s\t0\tWOULD-PUSH\t(dry run)\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$ahead"; return 0
    fi
    if git -C "$d" push --quiet origin HEAD 2>/dev/null; then
      printf '%s\t%s\t%s\t%s\t%s\t0\tPUSHED\t%s local commit(s) now on origin\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$ahead"
    else
      printf '%s\t%s\t%s\t%s\t%s\t0\tPUSH-REFUSED\tnot a fast-forward upstream, untouched\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$ahead"
    fi
    return 0
  fi

  # purely behind
  if [ "$dirty" -gt 0 ]; then
    printf '%s\t%s\t%s\t%s\t0\t%s\tBEHIND-DIRTY\t%s tracked file(s) modified, not pulled\n' "$HOSTNAME" "$name" "$branch" "$dirty" "$behind" "$dirty"; return 0
  fi
  if [ "$DRY" = "1" ]; then
    printf '%s\t%s\t%s\t0\t0\t%s\tWOULD-FF\t(dry run)\n' "$HOSTNAME" "$name" "$branch" "$behind"; return 0
  fi
  local out
  if out=$(git -C "$d" merge --ff-only "$up" 2>&1); then
    printf '%s\t%s\t%s\t0\t0\t0\tFAST-FORWARDED\t%s commits\n' "$HOSTNAME" "$name" "$branch" "$behind"
  else
    printf '%s\t%s\t%s\t0\t0\t%s\tFF-REFUSED\t%s\n' "$HOSTNAME" "$name" "$branch" "$behind" "$(echo "$out" | grep -m1 -E 'error|fatal|would be overwritten' | cut -c1-90)"
  fi
}

for base in "$HOME"/*/ "$HOME"/code/*/; do
  scan_dir "${base%/}"
done
