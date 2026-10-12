#!/usr/bin/env bash
# Watch what company-api and the archive pass actually do to memory.
# "not set" is what `systemctl show -p MemoryCurrent --value` returns for a unit that is
# not running, and it is the value that broke the first attempt at this measurement:
# arithmetic on it aborts the loop. Guard it.
set -u
for i in $(seq 1 "$1"); do
  api_raw=$(systemctl show company-api -p MemoryCurrent --value 2>/dev/null)
  arc_raw=$(systemctl show transcript-archive-pull -p MemoryCurrent --value 2>/dev/null)
  case "$api_raw" in ''|'[not set]'|*[!0-9]*) api_mb="-" ;; *) api_mb=$((api_raw / 1048576)) ;; esac
  case "$arc_raw" in ''|'[not set]'|*[!0-9]*) arc_mb="-" ;; *) arc_mb=$((arc_raw / 1048576)) ;; esac
  avail_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  arc_state=$(systemctl is-active transcript-archive-pull 2>/dev/null)
  printf '%s api=%sMB archive=%sMB(%s) avail=%sMB\n' \
    "$(date -u +%H:%M:%S)Z" "$api_mb" "$arc_mb" "$arc_state" "$avail_mb"
  sleep "$2"
done
