#!/usr/bin/env bash
# reclaim-disk-zabz-tech-linux.sh — the owner's rule (2026-10-20): customer data older than 30 days may be deleted,
# after PROVING it is older than 30 days. Regenerable/public material may go regardless.
#
# SAFETY, in the order it runs:
#   1. every target is an absolute path spelled out here, never computed;
#   2. `realpath` must equal the intended path, and the target must exist;
#   3. for CUSTOMER DATA the NEWEST file in the tree must be older than the cutoff (30 days), or the target is
#      skipped and the refusal is printed — a directory's own mtime says nothing about what is inside it;
#   4. a manifest is written FIRST (path, file count, bytes, newest file, top-level entries) so the deletion is
#      recorded rather than remembered;
#   5. `rm -rf --one-file-system` on the exact path only, never a glob, never a parent.
#
#   bash reclaim-disk-zabz-tech-linux.sh --dry-run     # prove ages + write the manifest, delete nothing
#   bash reclaim-disk-zabz-tech-linux.sh --execute     # delete the targets that passed
set -uo pipefail

MODE="${1:---dry-run}"
CUTOFF_DAYS=30
NOW=$(date +%s)
CUTOFF=$(( NOW - CUTOFF_DAYS * 86400 ))
CUTOFF_ISO=$(date -u -d "@$CUTOFF" +%Y-%m-%dT%H:%M:%SZ)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
MANIFEST="/home/zabz/disk-reclaim-manifest-$STAMP.txt"

# kind: customer = the 30-day rule must be proved; public = regenerable or publicly re-downloadable
TARGETS=(
  "customer|/home/zabz/shlesinger-recovery-2026-08-13"
  "customer|/home/zabz/laptop-backups/qin-f21-recovery"
  "customer|/home/zabz/sd-diagnostics"
  "public|/home/zabz/mtkclient/stock"
  "public|/home/zabz/tiq-firmware"
  "public|/home/zabz/.cache"
)

say() { echo "$*" | tee -a "$MANIFEST"; }

say "disk reclaim on $(hostname) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "mode: $MODE | customer-data cutoff: $CUTOFF_ISO (files newer than this are NOT deleted)"
say ""
df -Pk / | tail -1 | tee -a "$MANIFEST"
say ""
say "path | kind | files | bytes | newest file | verdict"
say "-----|------|-------|-------|-------------|--------"

DELETE_LIST=()
for entry in "${TARGETS[@]}"; do
  kind="${entry%%|*}"
  target="${entry##*|}"
  if [ ! -e "$target" ]; then
    say "$target | $kind | - | - | - | ABSENT, skipped"
    continue
  fi
  real=$(realpath "$target" 2>/dev/null)
  if [ "$real" != "$target" ]; then
    say "$target | $kind | - | - | - | REFUSED (realpath=$real)"
    continue
  fi
  files=$(find "$target" -xdev -type f 2>/dev/null | wc -l)
  bytes=$(du -sb "$target" 2>/dev/null | cut -f1)
  newest=$(find "$target" -xdev -type f -printf '%T@ %TY-%Tm-%Td %p\n' 2>/dev/null | sort -rn | head -1)
  newest_ts=$(echo "$newest" | cut -d' ' -f1)
  newest_date=$(echo "$newest" | cut -d' ' -f2)
  newest_path=$(echo "$newest" | cut -d' ' -f3-)

  verdict=""
  if [ "$kind" = "customer" ]; then
    if [ -z "$newest_ts" ]; then
      verdict="REFUSED (no files)"; 
    elif awk -v t="$newest_ts" -v c="$CUTOFF" 'BEGIN{exit !(t < c)}'; then
      verdict="OK (>30d)"
    else
      verdict="REFUSED (a file is newer than 30d)"
    fi
  else
    verdict="OK (public/regenerable)"
  fi

  say "$target | $kind | $files | $bytes | $newest_date ${newest_path:0:70} | $verdict"
  if [ "${verdict:0:2}" = "OK" ]; then DELETE_LIST+=("$target"); fi
done

say ""
say "top-level entries of each candidate (for the record):"
for entry in "${TARGETS[@]}"; do
  target="${entry##*|}"
  [ -e "$target" ] || continue
  say "  $target: $(ls -1 "$target" 2>/dev/null | head -8 | tr '\n' ' ')"
done

say ""
if [ "$MODE" != "--execute" ]; then
  say "DRY RUN — nothing deleted. Re-run with --execute to delete the ${#DELETE_LIST[@]} target(s) marked OK."
  echo "manifest: $MANIFEST"
  exit 0
fi

say "DELETING ${#DELETE_LIST[@]} target(s) with rm -rf --one-file-system on the exact paths:"
for t in "${DELETE_LIST[@]}"; do
  [ "$(realpath "$t" 2>/dev/null)" = "$t" ] || { say "  REFUSED at delete time: $t"; continue; }
  say "  rm -rf --one-file-system $t"
  rm -rf --one-file-system "$t"
  say "    -> $([ -e "$t" ] && echo STILL PRESENT || echo removed)"
done

say ""
say "after:"
df -Pk / | tail -1 | tee -a "$MANIFEST"
echo "manifest: $MANIFEST"
