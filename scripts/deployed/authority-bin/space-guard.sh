#!/usr/bin/env bash
# space-guard.sh - refuse a write that would take a filesystem below its floor.
#
# WHY THIS EXISTS (measured 2026-10-14, on the authority secratary-cloud)
#   The filesystem was DOUBLED from ~76 GB to ~152 GB at 01:15Z and given "roughly 40 days of
#   runway" (owner_decision_queue 484, closed 02:11:32Z: "No scratch needed to be deleted").
#   Between 03:22Z and 06:15Z three artefacts consumed ~39 GB of it - a 27.5 GB whole-database
#   VACUUM INTO copy, a 4.18 GB dead partial and a 7.75 GB git pack - and by 23:00Z the same disk
#   read 0 bytes free for the THIRD time that day. The doubling was spent in a day.
#
#   A whole-database copy of a 27 GB store is 18% of the disk in ONE write. The disk alarm now
#   catches the consequence (estate-monitor's disk_free_deficit_gb fires below 4 GiB free); this
#   catches the CAUSE, before it starts.
#
# USAGE
#   space-guard.sh <bytes-you-are-about-to-write> [mount] [label]
#     space-guard.sh 29000000000 / "authority.db VACUUM INTO"
#     space-guard.sh "$(stat -c %s "$F")" / "db copy"
#
# EXIT CODES (this estate's convention: a refusal is a value, never an exception)
#   0  SAFE                - the write fits above the floor
#   3  REFUSED             - it would breach the floor; DO NOT START. Message on stdout.
#   1  USAGE
#   2  COULD NOT MEASURE   - never a pass
#
# THE FLOOR: 8 GiB by default, overridable with SPACE_GUARD_FLOOR_MB. Chosen because at 0 bytes
# free NO channel on this filesystem can record anything - syslog, alerts.jsonl and the ESCALATED
# file all live on / - so the floor has to leave room for the machine to say what happened. That is
# also why the alarm must fire EARLY; an alarm that needs free disk to raise itself is not one.
#
# STATUS: installed on the authority 2026-10-15. ADVISORY until every large-write path calls it -
# say so rather than assuming the rule holds.
set -u
FLOOR_MB="${SPACE_GUARD_FLOOR_MB:-8192}"
NEED="${1:-}"; MOUNT="${2:-/}"; LABEL="${3:-write}"
if [ -z "$NEED" ]; then echo "usage: space-guard.sh <bytes> [mount] [label]"; exit 1; fi
case "$NEED" in *[!0-9]*) echo "usage: bytes must be an integer (got '$NEED')"; exit 1;; esac
AVAIL_KB=$(df -P -k "$MOUNT" 2>/dev/null | awk 'NR==2{print $4}')
if [ -z "${AVAIL_KB:-}" ]; then echo "COULD NOT MEASURE free space on $MOUNT"; exit 2; fi
AVAIL_MB=$(( AVAIL_KB / 1024 ))
NEED_MB=$(( NEED / 1048576 ))
AFTER_MB=$(( AVAIL_MB - NEED_MB ))
printf '%s: avail=%s MiB need=%s MiB after=%s MiB floor=%s MiB '%s'\n' \
       "$(hostname)" "$AVAIL_MB" "$NEED_MB" "$AFTER_MB" "$FLOOR_MB" "$LABEL"
if [ "$AFTER_MB" -lt "$FLOOR_MB" ]; then
  echo "REFUSED: this write would leave ${AFTER_MB} MiB free, below the ${FLOOR_MB} MiB floor."
  echo "  Free space first, or write somewhere else, or lower the size. Do NOT start it."
  echo "  Note: at 0 bytes free nothing on / can record an alarm - syslog, alerts.jsonl and the"
  echo "  ESCALATED file are all on this filesystem."
  exit 3
fi
echo "SAFE: ${AFTER_MB} MiB would remain."
exit 0
