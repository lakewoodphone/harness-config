#!/usr/bin/env bash
# install-harness-autosync-macos.sh — register harness-autosync.sh as a LaunchAgent on macOS.
#
# WHAT IT INSTALLS
#   ~/Library/LaunchAgents/com.lakewoodphone.harness-autosync.plist
#   runs scripts/harness-autosync.sh at load and every INTERVAL seconds (default 900 = 15 min),
#   which matches the Windows workstations' `PersonalSecretary-HarnessSync` cadence.
#
# WHY A LAUNCHAGENT AND NOT AN INTERVAL-LESS DAEMON
# It runs in the user's own session, so it can write ~/.dsh and the checkout without a privilege
# prompt. Nothing here needs root; running it as root would create root-owned files inside her
# home directory, which is the opposite of helpful.
#
# StandardOut/Err are wired to files under ~/.dsh-sync, because a LaunchAgent that writes nowhere
# is indistinguishable from one that never ran -- the exact failure mode this fleet has hit before.
#
# Usage:  bash install-harness-autosync-macos.sh [--interval 900] [--remove] [--check] [--run-now]
set -uo pipefail

INTERVAL=900
MODE=install
# Plain loop with an explicit index: `shift` inside a `for arg in "$@"` loop loses elements, which
# would silently drop the value after --interval.
while [ $# -gt 0 ]; do
  case "$1" in
    --interval) INTERVAL="${2:-900}"; shift 2 ;;
    --remove) MODE=remove; shift ;;
    --check) MODE=check; shift ;;
    --run-now) MODE=runnow; shift ;;
    *) shift ;;
  esac
done

LABEL="com.lakewoodphone.harness-autosync"
REPO="${HARNESS_REPO:-$HOME/code/harness-config}"
SCRIPT="$REPO/scripts/harness-autosync.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATE="$HOME/.dsh-sync"
UID_N="$(id -u)"

say() { printf '%s\n' "$1"; }

case "$MODE" in
  remove)
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    say "removed $LABEL"
    exit 0
    ;;
  check)
    say "label    : $LABEL"
    say "plist    : $PLIST $([ -f "$PLIST" ] && echo '(present)' || echo '(MISSING)')"
    say "script   : $SCRIPT $([ -f "$SCRIPT" ] && echo '(present)' || echo '(MISSING)')"
    say "loaded   : $(launchctl list 2>/dev/null | grep -c "$LABEL") match(es)"
    launchctl list 2>/dev/null | grep "$LABEL" || true
    [ -f "$STATE/status.json" ] && { say "status   :"; cat "$STATE/status.json"; } || say "status   : (no run yet)"
    exit 0
    ;;
esac

[ -f "$SCRIPT" ] || { say "FATAL: $SCRIPT not found"; exit 2; }
chmod +x "$SCRIPT" 2>/dev/null

mkdir -p "$HOME/Library/LaunchAgents" "$STATE"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SCRIPT</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HARNESS_REPO</key><string>$REPO</string>
    <key>PATH</key><string>$HOME/.local/node-v24.12.0-darwin-arm64/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>StandardOutPath</key><string>$STATE/stdout.log</string>
  <key>StandardErrorPath</key><string>$STATE/stderr.log</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$PLIST" 2>&1 || {
  say "bootstrap failed; falling back to load"
  launchctl load -w "$PLIST" 2>&1
}
launchctl enable "gui/$UID_N/$LABEL" 2>/dev/null || true

say "installed $LABEL (every ${INTERVAL}s)"
launchctl list 2>/dev/null | grep "$LABEL" || say "WARNING: not listed by launchctl"

if [ "$MODE" = "runnow" ]; then
  say "--- running once now ---"
  launchctl kickstart -k "gui/$UID_N/$LABEL" 2>&1 || bash "$SCRIPT"
  sleep 6
  say "--- status ---"
  cat "$STATE/status.json" 2>/dev/null || say "(no status file)"
fi
