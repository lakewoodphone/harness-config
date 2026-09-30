#!/usr/bin/env bash
# install.sh -- put this estate's guards and flag sources on a host, from the repo that owns them.
#
# WHY THIS DIRECTION. Everything here started as a file written on `secratary` in a session: a guard
# that only exists on the machine it was written on is a guard with one disk (journal P2258 measured
# exactly that for 176 operator scripts). harness-config is the shared source of truth and reaches
# every machine, so the canonical copies live here and this script INSTALLS them -- one direction,
# repo -> host, the same direction `scripts/wake/sources/` already uses for `~/bin/sources/`.
#
# WHAT IT INSTALLS
#   guards/*.py, *.sh          -> ~/bin/
#   guards/sources/*.py        -> ~/bin/sources/
#   guards/health-gate.sh      -> ~/bin/ too, because the API watchdog judges with it and must not
#                                 depend on the app tree it is judging
#
# SAFETY
#   * sha256 is compared before and after every copy; a file that does not verify stops the run.
#   * an existing file is backed up to `<name>.bak-install-<timestamp>` before it is replaced.
#   * `--dry-run` prints every action and writes nothing.
#   * it installs FILES ONLY. Cron lines, sources-loop membership and systemd units are deliberate
#     per-host decisions and are listed in --notes rather than applied.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${GUARD_BIN_DIR:-$HOME/bin}"
SRC="${GUARD_SOURCES_DIR:-$BIN/sources}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

sha() { sha256sum "$1" 2>/dev/null | cut -c1-16; }

install_one() {
  local from="$1" to="$2"
  [ -f "$from" ] || { echo "  MISSING IN REPO: $from"; return 1; }
  if [ -f "$to" ] && [ "$(sha "$from")" = "$(sha "$to")" ]; then
    printf "  = %-28s already current (%s)\n" "$(basename "$to")" "$(sha "$to")"
    return 0
  fi
  if (( DRY )); then
    printf "  + %-28s would install (%s)\n" "$(basename "$to")" "$(sha "$from")"
    return 0
  fi
  mkdir -p "$(dirname "$to")"
  [ -f "$to" ] && cp -p "$to" "$to.bak-install-$TS"
  cp -p "$from" "$to"
  chmod +x "$to" 2>/dev/null || true
  # LF IS NOT OPTIONAL for anything with a shebang: a CR turns every line into
  # "$'\r': command not found" on Linux (journal P264, and the guard now checks for it).
  sed -i 's/\r$//' "$to" 2>/dev/null || true
  if [ "$(sha "$from")" = "$(sha "$to")" ]; then
    printf "  + %-28s installed (%s)\n" "$(basename "$to")" "$(sha "$to")"
  else
    printf "  ! %-28s FAILED VERIFICATION: %s -> %s\n" "$(basename "$to")" "$(sha "$from")" "$(sha "$to")"
    return 1
  fi
}

echo "guards from $HERE"
echo "  -> $BIN"
rc=0
for f in "$HERE"/*.py "$HERE"/*.sh; do
  [ -f "$f" ] || continue
  install_one "$f" "$BIN/$(basename "$f")" || rc=1
done
echo "  -> $SRC"
for f in "$HERE"/sources/*.py; do
  [ -f "$f" ] || continue
  install_one "$f" "$SRC/$(basename "$f")" || rc=1
done

cat <<'NOTES'

NOT APPLIED HERE, on purpose -- each is a per-host decision:

  CRON (secratary)
    7 * * * *   ~/bin/cron-target-guard.py --write-status >> ~/.cron-targets/guard.log 2>&1
    */15 * * ** ~/bin/disk-guard.py --write-status         >> ~/.disk-guard/guard.log 2>&1
    17 4 * * *  ~/bin/db-integrity-check.py --write-status >> ~/.db-integrity/cron.log 2>&1
    20 6 * * *  ~/bin/cron-wrap.sh pain-check ~/bin/pain-check.py --write-status
    (the first three are wrapped by cron-wrap.sh on secratary, so their exit codes are recorded)

  DATA the guards read, created once and then maintained:
    ~/.cron-targets/critical.txt     the paths NO crontab names (backup retention, the harvest
                                     scripts, the security-absence alarm, the operator primitives)
    ~/.pain-check/status.json        written by pain-check.py --write-status

  SOURCES LOOP  add to the list in ~/bin/run-wake-sources.sh:
    cron-targets disk-space db-integrity pain-checks

  API WATCHDOG  the unit's ExecStart must be ~/bin/api-watchdog.sh, and it judges with
    ~/bin/health-gate.sh (installed above).
NOTES

echo
echo "verify: python3 ~/bin/cron-target-guard.py --selftest && python3 ~/bin/disk-guard.py --selftest \\"
echo "        && python3 ~/bin/db-integrity-check.py --selftest && python3 ~/bin/pain-check.py --selftest"
exit "$rc"
