#!/usr/bin/env bash
# install-manager-macos-extras.sh — the two jobs a manager Mac needs beyond autosync and session sync.
#
#   com.lakewoodphone.repo-sync     keeps the shop's repos current AND makes sure work done here is
#                                   committed and pushed (hourly)
#   com.lakewoodphone.journal-daily one handoff entry per day, answering what changed / what needs HER
#                                   / open pain / next (daily at 09:00, and at load)
#
# WHY THESE ARE SEPARATE FROM harness-autosync
# They are different guarantees. harness-autosync moves CONFIGURATION; repo-sync moves the shop's own
# CONTENT, and journal-daily writes the machine's own history. A failure in one must not be reported as
# a failure of another, and each writes its own log.
#
# WHY repo-sync MATTERS MOST: her agent produced a real customer case file and left it UNTRACKED. The
# work existed and nothing would ever have committed or pushed it. That job is what turns "her agent
# can write files" into "the customer's case is updated in the shop's repo".
#
# Usage: bash install-manager-macos-extras.sh [--remove] [--check] [--run-now] [--dry-run]
set -uo pipefail

MODE=install
REPO_SYNC_INTERVAL=3600
while [ $# -gt 0 ]; do
  case "$1" in
    --remove) MODE=remove; shift ;;
    --check) MODE=check; shift ;;
    --run-now) MODE=runnow; shift ;;
    --dry-run) MODE=dry; shift ;;
    --interval) REPO_SYNC_INTERVAL="${2:-3600}"; shift 2 ;;
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
LABELS=("com.lakewoodphone.repo-sync" "com.lakewoodphone.journal-daily")

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
    launchctl list 2>/dev/null | grep "$L" | sed 's/^/  /' || say "  (not loaded)"
  done
  for f in repo-sync.log journal-daily.log; do
    [ -f "$STATE/$f" ] && { say "--- $f ---"; tail -8 "$STATE/$f" | sed 's/^/  /'; }
  done
  exit 0
fi

[ -n "$NODE" ] || { say "FATAL: no node found"; exit 2; }
[ -f "$REPO/scripts/repo-sync.mjs" ] || { say "FATAL: repo-sync.mjs missing from $REPO"; exit 2; }
[ -f "$REPO/scripts/journal-daily.sh" ] || { say "FATAL: journal-daily.sh missing from $REPO"; exit 2; }
[ "$MODE" = dry ] || { mkdir -p "$AGENTS" "$STATE"; chmod +x "$REPO/scripts/journal-daily.sh" 2>/dev/null; }

write_plist() { # label interval logname program...
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
    printf '    <key>HOME</key><string>%s</string>\n' "$H"
    printf '    <key>HARNESS_REPO</key><string>%s</string>\n' "$REPO"
    printf '    <key>PATH</key><string>%s/.local/node-v24.12.0-darwin-arm64/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>\n' "$H"
    printf '  </dict>\n'
    printf '  <key>RunAtLoad</key><true/>\n'
    if [ -n "$interval" ]; then printf '  <key>StartInterval</key><integer>%s</integer>\n' "$interval"; fi
    printf '  <key>StandardOutPath</key><string>%s/%s.log</string>\n' "$STATE" "$logname"
    printf '  <key>StandardErrorPath</key><string>%s/%s.err.log</string>\n' "$STATE" "$logname"
    printf '  <key>ProcessType</key><string>Background</string>\n'
    printf '</dict>\n</plist>\n'
  } > "$plist"
  if [ "$MODE" = dry ]; then say "  would write $plist"; return; fi
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$plist" 2>&1 || launchctl load -w "$plist" 2>&1
  if launchctl list 2>/dev/null | grep -q "$label"; then say "  $label: registered${interval:+ every ${interval}s}"
  else say "  $label: WARNING not listed by launchctl"; fi
}

say "install-manager-macos-extras"
say "  user : $(whoami)"
say "  repo : $REPO"
say "  node : $NODE"
say ""

write_plist "com.lakewoodphone.repo-sync" "$REPO_SYNC_INTERVAL" "repo-sync" \
  "$NODE" "$REPO/scripts/repo-sync.mjs"

# No StartInterval: this one is daily. launchd needs a calendar interval for that, so the argument list
# carries `--daily` and the plist uses StartCalendarInterval.
write_plist "com.lakewoodphone.journal-daily" "" "journal-daily" \
  /bin/bash "$REPO/scripts/journal-daily.sh"
if [ "$MODE" != dry ]; then
  PLIST="$AGENTS/com.lakewoodphone.journal-daily.plist"
  # Insert a 09:00 calendar trigger beside RunAtLoad, then reload so it takes effect.
  /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval dict" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:Hour integer 9" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:Minute integer 0" "$PLIST" 2>/dev/null || true
  launchctl bootout "gui/$UID_N/com.lakewoodphone.journal-daily" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$PLIST" 2>&1 || launchctl load -w "$PLIST" 2>&1
  say "  com.lakewoodphone.journal-daily: daily at 09:00 + at load"
fi

if [ "$MODE" = "runnow" ]; then
  say ""
  for L in "${LABELS[@]}"; do
    say "  starting $L..."
    launchctl kickstart -k "gui/$UID_N/$L" 2>&1 || say "    kickstart failed"
  done
  sleep 25
  say "--- results ---"
  for f in repo-sync.log journal-daily.log; do
    [ -f "$STATE/$f" ] && { say "$f:"; tail -14 "$STATE/$f" | sed 's/^/  /'; }
  done
fi

say ""
say "$([ "$MODE" = dry ] && echo 'dry run: nothing registered' || echo done.)"
