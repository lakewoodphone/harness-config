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
# SCHEDULER (measured 2026-10-22, journal H8042/H9143, ledger item 1155).
# On a machine running systemd the schedule is `dsh-archive-local.timer` (hourly at :17), NOT cron.
# The authority has run that timer since 2026-10-18, but the unit, timer and per-machine drop-in
# existed only in /etc/systemd/system -- a rebuild lost the schedule -- and this installer still
# wrote a `*/30` crontab line, so running it on the authority would have double-scheduled the same
# shipper (2.2G peak per run). The three files are now tracked verbatim under scripts/systemd/, and
# this installer installs them, removes the cron line, and enables the timer. cron remains the
# fallback on a Linux box with no systemd. Either way the installer leaves EXACTLY ONE scheduled
# path, and --check reports which one is live and whether the tracked units match the installed ones.
#
# USAGE
#   scripts/Install-DshArchive.sh            # install / repair (idempotent)
#   scripts/Install-DshArchive.sh --check    # report state, change nothing; exit 1 if not exactly one path
#   scripts/Install-DshArchive.sh --dry-run  # print what would be installed
#   scripts/Install-DshArchive.sh --run-now  # install, then ship once
#   scripts/Install-DshArchive.sh --remove   # remove the scheduled path (timer and cron)
#
# ENV
#   DSH_ARCHIVE_REPO          repo holding scripts/push-dsh-sessions.mjs (default: this script's parent)
#   DSH_ARCHIVE_INTERVAL_MIN  cron fallback interval in minutes (default 30)
#   DSH_ARCHIVE_ENDPOINT      ingest endpoint; default is the shipper's own default (public authority)
#   DSH_ARCHIVE_MACHINE       archive identity (default: hostname -s, lowercased); written to the drop-in
#   DSH_ARCHIVE_SCHEDULER     auto (default) | systemd | cron
#   DSH_ARCHIVE_UNIT_DIR      unit directory (default /etc/systemd/system)
set -u

REPO_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${DSH_ARCHIVE_REPO:-$REPO_DEFAULT}"
INTERVAL="${DSH_ARCHIVE_INTERVAL_MIN:-30}"
LOG="$HOME/.dsh-session-ship.log"
MARK="push-dsh-sessions.mjs"

UNIT_NAME="dsh-archive-local"
UNIT_DIR="${DSH_ARCHIVE_UNIT_DIR:-/etc/systemd/system}"
UNIT_SRC="$REPO/scripts/systemd"
MACHINE="$(printf '%s' "${DSH_ARCHIVE_MACHINE:-$(hostname -s 2>/dev/null || hostname)}" | tr '[:upper:]' '[:lower:]')"

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

cron_lines() {
  crontab -l 2>/dev/null | grep -c "$MARK" || true
}

cron_remove() {
  local tmp
  crontab -l >/dev/null 2>&1 || return 0
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v "$MARK" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
}

have_systemd() { [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" != 0 ]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    SUDO="sudo -n"
  fi
fi

can_use_systemd() {
  have_systemd || return 1
  [ -d "$UNIT_DIR" ] || return 1
  [ -w "$UNIT_DIR" ] && return 0
  [ -n "$SUDO" ] && return 0
  return 1
}

install_units() {
  $SUDO install -d "$UNIT_DIR" "$UNIT_DIR/$UNIT_NAME.service.d" || return 1
  $SUDO install -m 0644 "$UNIT_SRC/$UNIT_NAME.service" "$UNIT_DIR/$UNIT_NAME.service" || return 1
  $SUDO install -m 0644 "$UNIT_SRC/$UNIT_NAME.timer"   "$UNIT_DIR/$UNIT_NAME.timer"   || return 1
  # Copy the tracked drop-in verbatim when it already names this machine, so the tracked
  # file and the installed bytes are identical. Otherwise render the same shape for this host.
  if [ -f "$UNIT_SRC/$UNIT_NAME.service.d/20-machine.conf" ] && \
     grep -qx "Environment=DSH_ARCHIVE_MACHINE=$MACHINE" "$UNIT_SRC/$UNIT_NAME.service.d/20-machine.conf"; then
    $SUDO install -m 0644 "$UNIT_SRC/$UNIT_NAME.service.d/20-machine.conf" \
      "$UNIT_DIR/$UNIT_NAME.service.d/20-machine.conf" || return 1
  else
    printf '[Service]\n# The same variable the unit already sets; a later Environment= wins for that name.\nEnvironment=DSH_ARCHIVE_MACHINE=%s\n' "$MACHINE" \
      | $SUDO tee "$UNIT_DIR/$UNIT_NAME.service.d/20-machine.conf" >/dev/null || return 1
  fi
  $SUDO systemctl daemon-reload || return 1
}

unit_drift() {
  local f out=""
  for f in "$UNIT_NAME.service" "$UNIT_NAME.timer"; do
    [ -f "$UNIT_SRC/$f" ] || { out="$out missing:$f"; continue; }
    [ -f "$UNIT_DIR/$f" ] || { out="$out absent:$f"; continue; }
    cmp -s "$UNIT_SRC/$f" "$UNIT_DIR/$f" || out="$out differs:$f"
  done
  # The drop-in is per-machine. Where the tracked file names this machine it must match
  # byte-for-byte; elsewhere only the machine line is expected to agree.
  f="$UNIT_NAME.service.d/20-machine.conf"
  if [ ! -f "$UNIT_DIR/$f" ]; then
    out="$out absent:$f"
  elif [ -f "$UNIT_SRC/$f" ] && grep -qx "Environment=DSH_ARCHIVE_MACHINE=$MACHINE" "$UNIT_SRC/$f"; then
    cmp -s "$UNIT_SRC/$f" "$UNIT_DIR/$f" || out="$out differs:$f"
  elif ! grep -qx "Environment=DSH_ARCHIVE_MACHINE=$MACHINE" "$UNIT_DIR/$f"; then
    out="$out differs:$f(machine)"
  fi
  printf '%s' "$out"
}

if [ "$MODE" = "remove" ]; then
  if have_systemd; then
    $SUDO systemctl disable --now "$UNIT_NAME.timer" 2>/dev/null || true
    $SUDO rm -f "$UNIT_DIR/$UNIT_NAME.timer" "$UNIT_DIR/$UNIT_NAME.service" \
      "$UNIT_DIR/$UNIT_NAME.service.d/20-machine.conf" 2>/dev/null || true
    $SUDO rmdir "$UNIT_DIR/$UNIT_NAME.service.d" 2>/dev/null || true
    $SUDO systemctl daemon-reload 2>/dev/null || true
    say "removed the $UNIT_NAME systemd timer (if present)"
  fi
  cron_remove
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
  say "machine     : $MACHINE"

  timer_installed=no
  if [ -f "$UNIT_DIR/$UNIT_NAME.timer" ] && [ -f "$UNIT_DIR/$UNIT_NAME.service" ]; then
    timer_installed=yes
  fi
  timer_scheduled=no
  if [ "$timer_installed" = yes ]; then
    en="$(systemctl is-enabled "$UNIT_NAME.timer" 2>/dev/null || echo unknown)"
    ac="$(systemctl is-active "$UNIT_NAME.timer" 2>/dev/null || echo unknown)"
    say "scheduled   : systemd timer $UNIT_NAME.timer (enabled=$en active=$ac)"
    [ "$en" = enabled ] && timer_scheduled=yes
  else
    say "scheduled   : no systemd timer installed"
  fi

  cron_n="$(cron_lines)"
  say "cron        : $cron_n $MARK line(s)"
  crontab -l 2>/dev/null | grep "$MARK" | sed 's/^/  /' || true

  drift=""
  if [ "$timer_installed" = yes ]; then
    drift="$(unit_drift)"
    if [ -n "$drift" ]; then
      say "units       : DRIFT:$drift"
    else
      say "units       : match (service timer drop-in)"
    fi
  else
    say "units       : n/a (no systemd timer installed)"
  fi

  paths=0
  [ "$timer_scheduled" = yes ] && paths=$((paths + 1))
  [ "${cron_n:-0}" -gt 0 ] && paths=$((paths + 1))
  if [ "$paths" -eq 1 ] && [ -z "$drift" ]; then
    say "check       : PASS (scheduled_paths=$paths)"
    exit 0
  fi
  say "check       : FAIL (scheduled_paths=$paths drift=${drift:-none})"
  exit 1
fi

fail=0
[ -n "$NODE" ]    || { say "FATAL: node not on PATH -- install Node, then re-run"; fail=1; }
[ -f "$SHIPPER" ] || { say "FATAL: shipper not found at $SHIPPER"; fail=1; }
[ -n "$TOKEN_FILE" ] || say "WARNING: no DSH_SESSION_INGEST_TOKEN found; the push will fail until one is placed in $REPO/.env (chmod 600)"
[ "$fail" = 0 ] || exit 2

SYSTEMD=no
case "${DSH_ARCHIVE_SCHEDULER:-auto}" in
  cron)    SYSTEMD=no ;;
  systemd) can_use_systemd || { say "FATAL: DSH_ARCHIVE_SCHEDULER=systemd but systemd cannot be used here"; exit 2; }
           SYSTEMD=yes ;;
  auto)    can_use_systemd && SYSTEMD=yes || SYSTEMD=no ;;
  *)       say "FATAL: DSH_ARCHIVE_SCHEDULER must be auto, systemd or cron"; exit 2 ;;
esac

if [ "$MODE" = "dry" ]; then
  if [ "$SYSTEMD" = yes ]; then
    say "would install: $UNIT_DIR/$UNIT_NAME.service"
    say "would install: $UNIT_DIR/$UNIT_NAME.timer"
    say "would install: $UNIT_DIR/$UNIT_NAME.service.d/20-machine.conf (DSH_ARCHIVE_MACHINE=$MACHINE)"
    say "would enable : $UNIT_NAME.timer (hourly at :17)"
    say "would remove : $(cron_lines) $MARK crontab line(s)"
  else
    say "would install: $(cron_line "$NODE")"
  fi
  say "would use token: ${TOKEN_FILE:-<none>}"
  exit 0
fi

if [ "$SYSTEMD" = yes ]; then
  install_units || { say "FATAL: could not install the systemd units in $UNIT_DIR"; exit 2; }
  cron_remove
  $SUDO systemctl enable --now "$UNIT_NAME.timer" \
    || { say "FATAL: could not enable $UNIT_NAME.timer"; exit 2; }
  say "installed: systemd timer $UNIT_NAME.timer (hourly at :17)"
  say "  units   : $UNIT_DIR/$UNIT_NAME.service"
  say "            $UNIT_DIR/$UNIT_NAME.timer"
  say "            $UNIT_DIR/$UNIT_NAME.service.d/20-machine.conf"
  say "  machine : $MACHINE"
  say "  cron    : removed any $MARK line (exactly one scheduled path remains)"
  say "  token   : ${TOKEN_FILE:-<none>}"
  say "  log     : journalctl -u $UNIT_NAME.service"
else
  # cron fallback. Refuse to add a second path if a timer is already enabled here.
  if have_systemd && systemctl is-enabled "$UNIT_NAME.timer" >/dev/null 2>&1; then
    say "FATAL: $UNIT_NAME.timer is enabled; refusing to add a cron line (exactly one scheduled path)."
    say "       Run --remove first, or leave DSH_ARCHIVE_SCHEDULER=auto."
    exit 2
  fi
  LINE="$(cron_line "$NODE")"
  # idempotent: replace any existing shipper line, keep every other cron line
  TMP="$(mktemp)"
  crontab -l 2>/dev/null | grep -v "$MARK" > "$TMP" || true
  printf '%s\n' "$LINE" >> "$TMP"
  crontab "$TMP"
  rm -f "$TMP"
  say "installed: $LINE"
  say "  machine : $MACHINE (cron fallback; no systemd on this host)"
  say "  token   : ${TOKEN_FILE:-<none>}"
  say "  log     : $LOG"
fi

if [ "${RUN_NOW:-0}" = 1 ]; then
  say '--- running once now ---'
  ( cd "$REPO" && "$NODE" scripts/push-dsh-sessions.mjs --transport http )
fi
