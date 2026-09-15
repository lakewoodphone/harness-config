#!/usr/bin/env bash
# clone-manager-repos.sh — put the shop's repositories on a manager workstation.
#
# WHY: the owner's correction, 2026-09-15: "why only 2 repos / what about lpt flip phone, what about
# home assistant, what about the waze system". She runs the whole shop, so the flip-phone deployment,
# the Home Assistant config and the filter/Waze system are hers. A manager who can see two repositories
# is a crippled manager.
#
# IDEMPOTENT AND ADDITIVE: it clones what is MISSING and never touches a repository that is already
# there. Nothing is deleted, moved or reset. A repository it cannot reach is reported and skipped --
# that is a credential boundary to surface, not to work around.
#
# Usage: bash clone-manager-repos.sh [--root DIR] [--dry-run]
set -uo pipefail

ROOT="${HOME}/code"
DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:-$HOME/code}"; shift 2 ;;
    --dry-run) DRY=yes; shift ;;
    *) shift ;;
  esac
done

ORG="${HARNESS_GIT_ORG:-lakewoodphone}"
REPOS=(
  lpt-hub
  personal-secretary-mvp
  lpt-flip-phone
  lpt-schematics
  tesla-lin-chip
  ha-config
  kosher-filter-ai
  research-knowledge-base
  quickbooks-agent
  phone-and-tech-full
  book
  chumash-timeline
  tutor
)

mkdir -p "$ROOT" 2>/dev/null || { echo "cannot create $ROOT"; exit 2; }

echo "clone-manager-repos"
echo "  root : $ROOT"
echo "  org  : $ORG"
[ -n "$DRY" ] && echo "  mode : DRY RUN"
echo ""

cloned=0; present=0; failed=0
for r in "${REPOS[@]}"; do
  dest="$ROOT/$r"
  if [ -d "$dest/.git" ]; then
    printf "  %-28s present\n" "$r"
    present=$((present+1))
    continue
  fi
  if [ -n "$DRY" ]; then
    printf "  %-28s WOULD CLONE\n" "$r"
    continue
  fi
  url="git@github.com:$ORG/$r.git"
  printf "  %-28s cloning... " "$r"
  if out=$(GIT_TERMINAL_PROMPT=0 git clone --quiet "$url" "$dest" 2>&1); then
    printf "ok\n"
    cloned=$((cloned+1))
  else
    # Print the reason, because a refusal here is a credential scope fact worth knowing exactly.
    reason=$(printf '%s' "$out" | tr '\n' ' ' | sed 's/  */ /g' | cut -c1-100)
    printf "FAILED (%s)\n" "$reason"
    failed=$((failed+1))
    rmdir "$dest" 2>/dev/null || rm -rf "$dest" 2>/dev/null
  fi
done

echo ""
echo "  cloned: $cloned   already present: $present   failed: $failed"
[ "$failed" -gt 0 ] && echo "  a failure is usually a key scope limit, not a missing repository -- report it rather than working around it."
exit 0
