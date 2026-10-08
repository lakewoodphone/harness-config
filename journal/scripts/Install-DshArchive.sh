#!/bin/bash
# Install-DshArchive.sh -- register (or remove) the recurring DSH session archive push on a Linux node.
#
# WHY THIS EXISTS (measured 2026-09-24, journal D42/L158b/L2067).
# The DSH session archive exists so that "no conversation is ever only on one laptop": every DSH
# machine runs scripts/push-dsh-sessions.mjs on a timer and ships its sessions to the authority
# (secretary.db, via POST /api/v1/owner/dsh-sessions/ingest). The fleet had an installer for Windows
# (Install-DshArchive.ps1) and for macOS (install-manager-tasks-macos.sh) -- and nothing for Linux.
# So `zabz-tech-linux` ran DSH from 2026-09-16 to 2026-09-18 and shipped NOTHING: no ingest token in
# any .env, no shipper in its (stale) checkout, no scheduled run, no cursor. 94 conversations were
# single-homed for six days. Nothing alarmed, because:
#   * a machine whose shipper never ran looks exactly like a machine with nothing to do; and
#   * check-dsh-freshness.py cannot see it -- with no cursor there is no local-vs-cursor comparison,
#     and with no rows in dsh_sessions it is not in the archive's machine list either.
# This script is the missing provisioning path, so a Linux DSH node cannot be silently single-homed.
#
# USAGE
#   scripts/Install-DshArchive.sh            # install / repair (idempotent)
#   scripts/Install-DshArchive.sh --check    # report state, change nothing
#   scripts/Install-DshArchive.sh --dry-run  # print what would be installed
#   scripts/Install-DshArchive.sh --run-now  # install, then ship once
#   scripts/Install-DshArchive.sh --remove   # remove the scheduled line
#
# ENV
#   DSH_ARCHIVE_REPO          repo holding scripts/push-dsh-sessions.mjs (default: this script's parent)
#   DSH_ARCHIVE_INTERVAL_MIN  schedule interval in minutes (default 30)
#   DSH_ARCHIVE_ENDPOINT      ingest endpoint; default is the shipper's own default (public authority)
set -u

REPO_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${DSH_ARCHIVE_REPO:-$REPO_DEFAULT}"
INTERVAL="${DSH_ARCHIVE_INTERVAL_MIN:-30}"
LOG="$HOME/.dsh-session-ship.log"
MARK="push-dsh-sessions.mjs"

MODE=install
case "${1:-}" in
  --check)   MODE=check ;;
  --dry-run) MODE=dry ;;
  --remove)  MODE=remove ;;
  --run-now) MODE=install; RUN_NOW=1 ;;
  "")        MODE=install; RUN_NOW=0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

say() { echo "$@"; }

find_token() {
  local f
  for f in "$HOME/code/personal-secretary-mvp/.env" "$HOME/Code/personal-secretary-mvp/.env" \
           "$HOME/personal-secretary-mvp/.env" "$REPO/.env"; do
    [ -f "$f" ] || continue
    if grep -q '^DSH_SESSION_INGEST_TOKEN=' "$f" 2>/dev/null; then echo "$f"; return 0; fi
  done
  return 1
}

cron_line() {
  local node="$1"
  printf '*/%s * * * * cd %s && %s scripts/push-dsh-sessions.mjs --transport http >>%s 2>&1' \
    "$INTERVAL" "$REPO" "$node" "$LOG"
}

if [ "$MODE" = "remove" ]; then
  crontab -l 2>/dev/null | grep -v "$MARK" | crontab -
  say "removed the $MARK line from crontab (if present)"
  exit 0
fi

NODE="$(command -v node || true)"
SHIPPER="$REPO/scripts/push-dsh-sessions.mjs"
TOKEN_FILE="$(find_token || true)"

if [ "$MODE" = "check" ]; then
  say "repo        : $REPO"
  say "shipper     : $([ -f "$SHIPPER" ] && echo present || echo MISSING) ($SHIPPER)"
  say "node        : ${NODE:-MISSING}"
  say "ingest token: ${TOKEN_FILE:-MISSING (put DSH_SESSION_INGEST_TOKEN= in $REPO/.env)}"
  say "cursor      : $([ -f "$HOME/.dsh/dsh-archive-state.json" ] && echo present || echo 'MISSING (first run creates it)')"
  say "scheduled   : $(crontab -l 2>/dev/null | grep -c "$MARK") line(s)"
  crontab -l 2>/dev/null | grep "$MARK" | sed 's/^/  /'
  exit 0
fi

fail=0
[ -n "$NODE" ]    || { say "FATAL: node not on PATH -- install Node, then re-run"; fail=1; }
[ -f "$SHIPPER" ] || { say "FATAL: shipper not found at $SHIPPER"; fail=1; }
[ -n "$TOKEN_FILE" ] || say "WARNING: no DSH_SESSION_INGEST_TOKEN found; the push will fail until one is placed in $REPO/.env (chmod 600)"
[ "$fail" = 0 ] || exit 2

LINE="$(cron_line "$NODE")"

if [ "$MODE" = "dry" ]; then
  say "would install: $LINE"
  say "would use token: ${TOKEN_FILE:-<none>}"
  exit 0
fi

# idempotent: replace any existing shipper line, keep every other cron line
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "$MARK" > "$TMP" || true
printf '%s\n' "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
say "installed: $LINE"
say "  token   : ${TOKEN_FILE:-<none>}"
say "  log     : $LOG"

if [ "${RUN_NOW:-0}" = 1 ]; then
  say '--- running once now ---'
  ( cd "$REPO" && "$NODE" scripts/push-dsh-sessions.mjs --transport http )
fi

