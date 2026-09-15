#!/usr/bin/env bash
# install-manager-tasks-macos.sh — the macOS counterpart of install-manager-tasks.ps1.
#
# Registers the two recurring jobs a manager workstation needs, as LaunchAgents in the USER's own
# session:
#   com.lakewoodphone.dsh-session-sync   conversations reach the company archive (hourly)
#   com.lakewoodphone.harness-autosync   settings, presets and journal stay current (15 min)
#
# WHY LaunchAgents AND NOT ROOT LAUNCHDAEMONS
# Everything these jobs touch lives in the user's home -- ~/.dsh, the git checkout, the credentials.
# Run as root they would read root's idea of HOME and scatter root-owned files through the user's
# profile, turning a working job into a permissions mystery. User context is not a convenience here;
# it is the thing that makes the job correct.
#
# Both write logs under ~/.dsh-sync, because a scheduled job that writes nowhere cannot be told apart
# from one that never ran.
#
# Usage:
#   bash install-manager-tasks-macos.sh [--session-interval 3600] [--sync-interval 900]
#                                       [--remove] [--check] [--run-now] [--dry-run]
set -uo pipefail

SESSION_INTERVAL=3600
SYNC_INTERVAL=900
MODE=install
while [ $# -gt 0 ]; do
  case "$1" in
    --session-interval) SESSION_INTERVAL="${2:-3600}"; shift 2 ;;
    --sync-interval) SYNC_INTERVAL="${2:-900}"; shift 2 ;;
    --remove) MODE=remove; shift ;;
    --check) MODE=check; shift ;;
    --run-now) MODE=runnow; shift ;;
    --dry-run) MODE=dry; shift ;;
    *) shift ;;
  esac
done

H="$HOME"
REPO="${HARNESS_REPO:-$H/code/harness-config}"
STATE="$H/.dsh-sync"
AGENTS="$H/Library/LaunchAgents"
UID_N="$(id -u)"

NODE=""
for c in "$H/.local/node-v24.12.0-darwin-arm64/bin/node" "$(command -v node 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && NODE="$c" && break
done

say() { printf '%s\n' "$1"; }

declare -a LABELS=("com.lakewoodphone.dsh-session-sync" "com.lakewoodphone.harness-autosync")

if [ "$MODE" = "remove" ]; then
  for L in "${LABELS[@]}"; do
    launchctl bootout "gui/$UID_N/$L" 2>/dev/null || true
    rm -f "$AGENTS/$L.plist"
    say "removed $L"
  done
  exit 0
fi

if [ "$MODE" = "check" ]; then
  for L in "${LABELS[@]}"; do
    say "$L"
    say "  plist : $([ -f "$AGENTS/$L.plist" ] && echo present || echo MISSING)"
    say "  loaded: $(launchctl list 2>/dev/null | grep -c "$L")"
    launchctl list 2>/dev/null | grep "$L" | sed 's/^/  /' || say "  (not listed)"
  done
  for f in session-sync.log autosync.log status.json; do
    [ -f "$STATE/$f" ] && { say "--- $f ---"; tail -6 "$STATE/$f" | sed 's/^/  /'; }
  done
  exit 0
fi

[ -n "$NODE" ] || { say "FATAL: no node found"; exit 2; }
[ -d "$REPO/.git" ] || say "WARNING: $REPO is not a git checkout -- the sync job will still apply, but it cannot pull"

ship="$REPO/scripts/push-dsh-sessions.mjs"
[ -f "$ship" ] || { say "FATAL: shipper not found at $ship"; exit 2; }

if [ "$MODE" != "dry" ]; then mkdir -p "$AGENTS" "$STATE"; fi

write_plist() { # $1 label  $2 interval  $3 logname  $4... program args
  local label="$1" interval="$2" logname="$3"; shift 3
  local plist="$AGENTS/$label.plist"
  {
    printf '<?xml version="1.0" encoding="UTF-8"?>\n'
    printf '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    printf '<plist version="1.0">\n<dict>\n'
    printf '  <key>Label</key><string>%s</string>\n' "$label"
    printf '  <key>ProgramArguments</key>\n  <array>\n'
    for a in "$@"; do printf '    <string>%s</string>\n' "$a"; done
    printf '  </array>\n'
    printf '  <key>WorkingDirectory</key><string>%s</string>\n' "$REPO"
    printf '  <key>EnvironmentVariables</key>\n  <dict>\n'
    printf '    <key>DSH_HOME</key><string>%s/.dsh</string>\n' "$H"
    printf '    <key>HOME</key><string>%s</string>\n' "$H"
    printf '    <key>PATH</key><string>%s/.local/node-v24.12.0-darwin-arm64/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>\n' "$H"
    printf '  </dict>\n'
    printf '  <key>RunAtLoad</key><true/>\n'
    printf '  <key>StartInterval</key><integer>%s</integer>\n' "$interval"
    printf '  <key>StandardOutPath</key><string>%s/%s.log</string>\n' "$STATE" "$logname"
    printf '  <key>StandardErrorPath</key><string>%s/%s.err.log</string>\n' "$STATE" "$logname"
    printf '  <key>ProcessType</key><string>Background</string>\n'
    printf '</dict>\n</plist>\n'
  } > "$plist"
  if [ "$MODE" = "dry" ]; then say "  would write $plist (every ${interval}s)"; return; fi
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$plist" 2>&1 || launchctl load -w "$plist" 2>&1
  launchctl enable "gui/$UID_N/$label" 2>/dev/null || true
  if launchctl list 2>/dev/null | grep -q "$label"; then say "  $label: registered every ${interval}s"
  else say "  $label: WARNING not listed by launchctl"; fi
}

say "install-manager-tasks (macOS)"
say "  user : $(whoami)"
say "  repo : $REPO"
say "  node : $NODE"
say ""

# The session shipper reads its token from the repo .env or DSH_ARCHIVE_TOKEN; /bin/bash is the
# interpreter so the task definition stays free of shell quoting.
write_plist "com.lakewoodphone.dsh-session-sync" "$SESSION_INTERVAL" "session-sync" \
  "$NODE" "$ship"

write_plist "com.lakewoodphone.harness-autosync" "$SYNC_INTERVAL" "autosync" \
  /bin/bash "$REPO/scripts/harness-autosync.sh"

if [ "$MODE" = "runnow" ]; then
  say ""
  for L in "${LABELS[@]}"; do
    say "  starting $L..."
    launchctl kickstart -k "gui/$UID_N/$L" 2>&1 || say "    kickstart failed"
  done
  sleep 10
  say "--- results ---"
  for f in "$STATE/session-sync.log" "$STATE/autosync.log" "$STATE/status.json"; do
    [ -f "$f" ] && { say "$f:"; tail -8 "$f" | sed 's/^/  /'; }
  done
fi

say ""
say "$([ "$MODE" = dry ] && echo 'dry run: nothing registered' || echo done.)"
