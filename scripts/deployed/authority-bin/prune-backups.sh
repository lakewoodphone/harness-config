#!/usr/bin/env bash
# prune-backups.sh -- retention for the runtime backups. Ported to the cloud authority
# 2026-10-11 at the cutover; the POLICY is unchanged, the ROOT and the BUDGET are the cloud's.
#
# WHY THIS FILE MATTERS, in the words of the script that calls it on the office box
# (`scripts/server/backup-data.sh`, 2026-09-10):
#
#     Incident: retention used to live at the END of this script. With the disk full,
#     the backup step failed, the script exited non-zero, retention ran -> disk stayed
#     100% full -> SQLite SIGBUS core-dumps every ...
#
# Measured 2026-09-30 15:1xZ on the office box, with this file absent: / was at 99% with 7.6 GB
# free and /home/zabz/secretary-backups held 21 directories and 298 GB. A backup ran every six
# hours at ~18 GB, so the next one would have filled the volume -- and SQLite does not degrade
# gracefully when its disk fills, it takes the whole company down with it.
#
# POLICY (F7, 2026-08-30, unchanged): keep everything under 1 day old, one per day for
# 1-7 days, one per week for 7-30 days, nothing older than 30 days.
#
# ── WHAT CHANGED AT THE CUTOVER, AND WHY (2026-10-11) ─────────────────────────────────────────
# 1. ROOT. The office script was invoked as `prune-backups.sh /home/zabz/secretary-backups`.
#    On the cloud box that path does not exist and MUST NOT: it points at the ROLLBACK ANCHOR --
#    the frozen pre-cutover database, the one place the company's previous state still lives. A
#    retention script pointed there deletes the way back. So ROOT is now the cloud's own backup
#    root, and there is an ALLOWLIST below that refuses any root that is not it. This script
#    deletes directories; an allowlist is the only thing standing between a typo and 199 GB of
#    someone's only copy.
# 2. BUDGET. The office budget was 205 GiB, chosen for a 478 GB disk holding ~180 GB of other
#    data. The cloud box is 75 GB total with a 23.7 GB database and ~26 GB free: a 205 GiB budget
#    is 8x the entire disk, i.e. the budget could never fire. Measured 2026-10-11 06:25Z
#    (`secratary-cloud: df -B1 --output=avail /` -> 27,596,357,632 B = 25.7 GiB):
#        PRUNE_MAX_TOTAL_KB=4194304        (4 GiB)
#    WHY 4 GiB: it is ~15% of the free space, it is larger than any single artefact this box
#    should ever hold in the backup root, and it is smaller than one database -- so the budget
#    FIRES on the first full snapshot that lands here. That is intentional and it is the point:
#    the disk cannot hold even one 23.7 GB copy beside the live 23.7 GB database, so a snapshot
#    in this root is already a disk-full incident in progress and retention is the only thing
#    that can prevent it. The integrity check's own working copy lives under /root/.db-integrity
#    and is deleted in the same run as a matter of design, not of retention.
# 3. FREE-SPACE FLOOR. The GFS tiers are a policy and the budget is a ceiling; neither is a
#    floor. PRUNE_MIN_FREE_KB (default 12582912 = 12 GiB) is checked BEFORE anything is deleted:
#    when free space is already below it, this script says so loudly and prunes NOTHING, because
#    a box that is nearly full is exactly when a delete-everything-older-than-30-days pass is
#    most dangerous. Retention is not a rescue.
#
# USAGE
#   prune-backups.sh <backup-root>              # apply
#   prune-backups.sh <backup-root> --dry-run    # say what would go, delete nothing
set -uo pipefail

ROOT=""
DRY_RUN=0
ALLOW_ROOTS="${PRUNE_ALLOW_ROOTS:-/var/lib/authority-snapshots}"
MAX_TOTAL_KB="${PRUNE_MAX_TOTAL_KB:-4194304}"     # 4 GiB -- see the header
MIN_FREE_KB="${PRUNE_MIN_FREE_KB:-12582912}"      # 12 GiB floor -- see the header
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

# ── THE ALLOWLIST. Refuse to prune anywhere but the cloud's own backup root. ──────────────────
# A retention script is a delete loop with a date filter on it. The failure this prevents is the
# one the migration inventory names as DANGEROUS-ON-CLOUD: `prune-backups.sh /home/zabz/secretary-backups`
# run from anywhere on this estate deletes the rollback anchor. A real path, a plausible path, one
# argument away from being passed by a human at midnight.
ROOT_REAL="$(readlink -f "$ROOT" 2>/dev/null || echo "$ROOT")"
allowed=0
IFS=':' read -ra _ALLOWED <<< "$ALLOW_ROOTS"
for a in "${_ALLOWED[@]}"; do
  [[ -z "$a" ]] && continue
  a_real="$(readlink -f "$a" 2>/dev/null || echo "$a")"
  if [[ "$ROOT_REAL" == "$a_real" ]]; then allowed=1; break; fi
done
if (( allowed == 0 )); then
  echo "prune-backups: REFUSING root '$ROOT' (resolved '$ROOT_REAL') -- not in PRUNE_ALLOW_ROOTS='${ALLOW_ROOTS}'. Nothing was deleted." >&2
  exit 3
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

# ── THE FREE-SPACE FLOOR, checked before a single byte is removed ─────────────────────────────
# On a box this small, "the disk is nearly full" and "run retention" are not the same job. When
# the floor is already breached this reports and stops: the operator/agent needs to know the
# backup root is not the cause, and an aggressive delete is not the cure.
avail_before="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
if (( ${avail_before:-0} < MIN_FREE_KB )); then
  echo "prune-backups: FLOOR BREACHED - only ${avail_before} KB free on the backup volume (floor ${MIN_FREE_KB} KB). Pruned NOTHING; investigate what filled the disk. ${#ENTRIES[@]} entry/entries present." >&2
  exit 4
fi

# ── HARD SIZE BUDGET ──────────────────────────────────────────────────────────────────────────
# The GFS tiers above are a POLICY, not a budget. Measured 2026-10-05 on the office box: the
# policy kept 15 snapshots at ~21 GB each = 253 GB on a 478 GB disk that already held ~180 GB of
# other data, and prune removed NOTHING across five runs while free space fell
# 71 -> 34 -> 23 -> 15 -> 6.4 GB, because every one of the 15 was still inside the GFS window.
# So the tiers have a ceiling, and it is a SIZE budget rather than a count, because each snapshot
# grows as the database grows. The newest snapshot is never dropped.
if (( ${#keep[@]} > 1 )); then
  kept_kb=0
  for k in "${keep[@]}"; do
    kb="$(du -sk "$ROOT/$k" 2>/dev/null | awk '{print $1}')"
    kept_kb=$((kept_kb + ${kb:-0}))
  done
  if (( kept_kb > MAX_TOTAL_KB )); then
    newkeep=()
    running=0
    idx=0
    for k in "${keep[@]}"; do
      kb="$(du -sk "$ROOT/$k" 2>/dev/null | awk '{print $1}')"
      if (( idx == 0 || running + kb <= MAX_TOTAL_KB )); then
        newkeep+=("$k")
        running=$((running + kb))
      else
        drop+=("$k")
      fi
      idx=$((idx + 1))
    done
    echo "prune-backups: over the ${MAX_TOTAL_KB} KB budget by $((kept_kb - MAX_TOTAL_KB)) KB; dropping $(( ${#keep[@]} - ${#newkeep[@]} )) of the oldest kept entries"
    keep=("${newkeep[@]}")
  fi
fi

total_kb=0
for name in "${drop[@]:-}"; do
  [[ -z "$name" ]] && continue
  kb="$(du -sk "$ROOT/$name" 2>/dev/null | awk '{print $1}')"
  total_kb=$((total_kb + ${kb:-0}))
done

echo "prune-backups: ${#ENTRIES[@]} backup(s) present, keeping ${#keep[@]}, removing ${#drop[@]} (~$((total_kb/1048576)) GB) budget=${MAX_TOTAL_KB}KB$( ((DRY_RUN)) && echo ', DRY RUN - nothing will be deleted')"
for name in "${drop[@]:-}"; do
  [[ -z "$name" ]] && continue
  if (( DRY_RUN )); then
    echo "  would remove $name"
  else
    rm -rf -- "$ROOT/$name" && echo "  removed $name"
  fi
done

avail="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
echo "prune-backups: done; ${avail} KB free on the backup volume (was ${avail_before} KB)"
exit 0
