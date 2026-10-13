#!/usr/bin/env bash
# reclaim-disk.sh -- report (and, only with --apply, remove) REGENERABLE data on the
# authority `secratary-cloud`.
#
# WHY THIS EXISTS
#   2026-10-13: `/` is 75 GB, 58 GB used, 14 GB free, 81 % full (docs/mesh/176). The live
#   company database is ~24.3 GB and the offsite gzip that restores it is ~6.5 GB, so a
#   restore-and-verify needs ~31 GB of free space and cannot run on this box. Every GB that
#   can be reclaimed without losing a unique byte buys back the ability to prove a restore.
#
# WHAT IT WILL TOUCH (regenerable only)
#   package/build caches and extracted tmp trees. Nothing here is a source of truth:
#   npm's content cache, pip/uv HTTP cache, apt's .deb cache, the rebuildable search index,
#   and the scratch copies under /root/work. Everything can be recreated from the network
#   or from the repos that produced it.
#
# WHAT IT WILL NEVER TOUCH
#   /root/authority.db*            (the live database)
#   /var/lib/authority-backup/*    (the backup state and its proof)
#   /opt/company/**                (the LIVE company application)
#   /root/git-rescue-*/**          (rescue bundles -- may be the only copy; reported, never removed)
#   /etc, /boot, /var/lib/systemd, any crontab
#
# DEFAULT IS DRY-RUN. It refuses to remove anything without --apply, prints the exact bytes
# it would free, and prints `df` before and after. It never runs `rm -rf /` style on a target
# that does not resolve under the exact allow-listed path.
set -euo pipefail

usage() {
  cat <<'U'
reclaim-disk.sh -- prove what is regenerable on the authority, then (only if told) free it.

USAGE
  reclaim-disk.sh            # dry run: list targets and the bytes each would free
  reclaim-disk.sh --apply    # remove the allow-listed regenerable targets
  reclaim-disk.sh --help     # this text

EXIT
  0  success (dry run or apply)
  2  bad usage (no argument, unknown argument, or no --apply with a mutating flag)
  3  refusing: a target is a symlink or does not resolve under its allow-listed prefix
U
}

APPLY=0
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --apply)   APPLY=1 ;;
  "")        usage >&2; exit 2 ;;
  *)         echo "reclaim-disk.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac
[ "$#" -gt 1 ] && { echo "reclaim-disk.sh: too many arguments" >&2; exit 2; }

# allow-listed regenerable targets. Each must exist under exactly this path.
TARGETS=(
  "/root/.npm/_cacache"
  "/root/.cache/pip"
  "/root/.cache/uv"
  "/root/.cache"
  "/root/.fsearch"
  "/var/cache/apt/archives"
  "/root/work/lpt-hub/tmp"
  "/root/work/lpt-hub/artifacts"
)
# reported for a human decision, never removed by this script
REVIEW=(
  "/root/git-rescue-20261012"
  "/root/work/lpt-hub/.git"
)

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 B"; }

before_avail=$(df -B1 --output=avail / | tail -1 | tr -d ' ')
echo "free before: $(df -h / | awk 'NR==2{print $4" ("$5" used)"}')"
echo

total=0
present=()
for t in "${TARGETS[@]}"; do
  [ -e "$t" ] || { printf '  %-40s %s\n' "$t" "absent"; continue; }
  if [ -L "$t" ]; then
    echo "reclaim-disk.sh: refusing: $t is a symlink" >&2; exit 3
  fi
  case "$t" in
    /root/*|/var/cache/apt/archives) : ;;
    *) echo "reclaim-disk.sh: refusing: $t is outside the allow-list" >&2; exit 3 ;;
  esac
  sz=$(du -sb "$t" 2>/dev/null | cut -f1 || echo 0)
  printf '  %-40s %s\n' "$t" "$(human "$sz")"
  total=$((total + sz))
  present+=("$t")
done

echo
echo "TOTAL REGENERABLE: $(human "$total") across ${#present[@]} present target(s)"
echo
echo "review candidates (NOT removed by this script; may be unique):"
for r in "${REVIEW[@]}"; do
  [ -e "$r" ] || continue
  printf '  %-40s %s\n' "$r" "$(human "$(du -sb "$r" 2>/dev/null | cut -f1 || echo 0)")"
done

if [ "$APPLY" -eq 0 ]; then
  echo
  echo "DRY RUN: nothing removed. Re-run with --apply to free the $(human "$total") above."
  exit 0
fi

echo
echo "APPLY: removing ${#present[@]} regenerable target(s)..."
for t in "${present[@]}"; do
  rm -rf -- "$t"
  echo "  removed $t"
done
after_avail=$(df -B1 --output=avail / | tail -1 | tr -d ' ')
echo
echo "free after:  $(df -h / | awk 'NR==2{print $4" ("$5" used)"}')"
echo "reclaimed:   $(human $((after_avail - before_avail)))"
