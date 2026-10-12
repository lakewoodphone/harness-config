#!/usr/bin/env bash
# Run one transcript-archive pass and watch its memory until it settles.
# Guards against the literal 'not set' that `systemctl show -p MemoryCurrent --value`
# prints for an inactive unit: arithmetic on it aborts the loop (cost two attempts).
set -u
interval="${1:-20}"
rounds="${2:-15}"
UNIT=transcript-archive-pull

echo "ceiling: $(systemctl show "$UNIT" -p MemoryMax --value) bytes"
systemctl start "$UNIT" 2>/dev/null || echo "(start returned non-zero)"
for i in $(seq 1 "$rounds"); do
  sleep "$interval"
  raw=$(systemctl show "$UNIT" -p MemoryCurrent --value 2>/dev/null)
  state=$(systemctl is-active "$UNIT" 2>/dev/null)
  case "$raw" in ''|'[not set]'|*[!0-9]*) mb="-" ;; *) mb=$((raw / 1048576)) ;; esac
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  printf '%s state=%s mem=%sMB avail=%sMB\n' "$(date -u +%H:%M:%S)Z" "$state" "$mb" "$avail"
  if [ "$state" = "inactive" ] || [ "$state" = "failed" ]; then
    break
  fi
done
echo "--- outcome ---"
systemctl show "$UNIT" -p Result -p ExecMainStatus -p MemoryPeak --no-pager
echo "--- journal ---"
journalctl -u "$UNIT" --since "-20 min" --no-pager 2>/dev/null | tail -6
