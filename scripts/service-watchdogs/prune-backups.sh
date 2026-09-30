#!/usr/bin/env bash
# Retention for the runtime backups. Restored 2026-09-30 after this file was DELETED
# by a copy-style deployment, which disabled the only thing standing between the
# machine and a full disk.
#
# WHY THIS FILE MATTERS, in the words of the script that calls it
# (`scripts/server/backup-data.sh`, 2026-09-10):
#
#     Incident: retention used to live at the END of this script. With the disk full,
#     the backup step failed, the script exited non-zero, retention ran -> disk stayed
#     100% full -> SQLite SIGBUS core-dumps every ...
#
# Measured 2026-09-30 15:1xZ, with this file absent: / was at 99% with 7.6 GB free and
# /home/zabz/secretary-backups held 21 directories and 298 GB. A backup runs every six
# hours at ~18 GB, so the next one would have filled the volume -- and SQLite does not
# degrade gracefully when its disk fills, it takes the whole company down with it.
# The caller looks for this exact path and, when it is missing, prints
# "WARN: prune-backups.sh missing; skipping pre-backup retention" and continues.
#
# POLICY (F7, 2026-08-30, unchanged): keep everything under 1 day old, one per day for
# 1-7 days, one per week for 7-30 days, nothing older than 30 days.
#
# USAGE
#   prune-backups.sh <backup-root>              # apply
#   prune-backups.sh <backup-root> --dry-run    # say what would go, delete nothing
set -uo pipefail

ROOT=""
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) if [[ -z "$ROOT" ]]; then ROOT="$arg"; fi ;;
  esac
done

if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "prune-backups: no usable backup root (got '${ROOT}')" >&2
  exit 0   # never fail the caller: a prune that cannot run must not stop a backup
fi

NOW="$(date -u +%s)"
DAY=86400
WEEK=604800
MONTH=2592000

# Every entry whose name looks like <YYYYMMDDTHHMMSSZ>, newest first. Anything else in
# the directory is left strictly alone -- this script deletes only what it can date.
mapfile -t ENTRIES < <(
  find "$ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null \
    | grep -E '^[0-9]{8}T[0-9]{6}Z$' | sort -r
)

keep=()
drop=()
declare -A took_day=()
declare -A took_week=()

for name in "${ENTRIES[@]}"; do
  stamp="${name:0:8} ${name:9:2}:${name:11:2}:${name:13:2}"
  epoch="$(date -u -d "$stamp" +%s 2>/dev/null)" || { keep+=("$name"); continue; }
  age=$((NOW - epoch))
  if (( age < DAY )); then
    keep+=("$name")
    continue
  fi
  if (( age < WEEK )); then
    day_key="${name:0:8}"
    if [[ -z "${took_day[$day_key]:-}" ]]; then
      took_day[$day_key]=1
      keep+=("$name")
    else
      drop+=("$name")
    fi
    continue
  fi
  if (( age < MONTH )); then
    # one per ISO week, keyed on the Monday of that week
    week_key="$(date -u -d "$stamp -$(( ($(date -u -d "$stamp" +%u) - 1) )) days" +%Y%m%d 2>/dev/null || echo "$name")"
    if [[ -z "${took_week[$week_key]:-}" ]]; then
      took_week[$week_key]=1
      keep+=("$name")
    else
      drop+=("$name")
    fi
    continue
  fi
  drop+=("$name")
done

total_kb=0
for name in "${drop[@]:-}"; do
  [[ -z "$name" ]] && continue
  kb="$(du -sk "$ROOT/$name" 2>/dev/null | awk '{print $1}')"
  total_kb=$((total_kb + ${kb:-0}))
done

echo "prune-backups: ${#ENTRIES[@]} backup(s) present, keeping ${#keep[@]}, removing ${#drop[@]} (~$((total_kb/1048576)) GB)$( ((DRY_RUN)) && echo ', DRY RUN - nothing will be deleted')"
for name in "${drop[@]:-}"; do
  [[ -z "$name" ]] && continue
  if (( DRY_RUN )); then
    echo "  would remove $name"
  else
    rm -rf -- "$ROOT/$name" && echo "  removed $name"
  fi
done

avail="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
echo "prune-backups: done; ${avail} KB free on the backup volume"
exit 0
