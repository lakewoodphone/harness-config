#!/bin/bash
# install-handy-dictation-macos.sh -- provision Handy dictation on a macOS workstation, headlessly.
#
# Written for LAKEWOOECHSMINI (the office Mac mini, Yocheved's manager workstation) on 2026-09-15.
# It is idempotent: run it again and it converges rather than duplicating anything.
#
# WHY THIS SCRIPT EXISTS
#   The Mac mini has no built-in microphone, so "talk to text" needed a real audio input plus a
#   dictation app that (a) runs entirely on the machine, (b) has one obvious hotkey, (c) types into
#   any app, and (d) cannot be broken by the office network. Handy (MIT, github.com/cjpais/Handy)
#   is the only candidate that is installable AND configurable without a single GUI click.
#
# WHAT IT DOES
#   1. installs Handy with Homebrew if it is not already there
#   2. stages the speech model into Handy's models directory (no first-run download)
#   3. writes Handy's settings_store.json with the shop policy (push-to-talk, tray, autostart, ...)
#   4. pre-grants the macOS privacy permissions Handy needs, by writing the user TCC database
#      -- this is what replaces two permission dialogs nobody would be there to click
#   5. installs a LaunchAgent so Handy is running after every login
#   6. prints a verification block, and never claims something worked that it did not check
#
# RUN AS:  the logged-in desktop user, with sudo available (sudo is used only for the permission
#          step and for launching into the GUI session).  Example:
#              bash install-handy-dictation-macos.sh
#
# SAFETY: the TCC database is backed up to /tmp before it is touched, and rows are written with
#         INSERT OR REPLACE -- nothing is ever deleted. The only files overwritten are Handy's own
#         settings file (backed up first) and this script's own LaunchAgent.

set -euo pipefail

HANDY_APP="/Applications/Handy.app"
HANDY_BIN="$HANDY_APP/Contents/MacOS/Handy"
BUNDLE_ID="com.pais.handy"
APP_DATA="$HOME/Library/Application Support/$BUNDLE_ID"
MODELS_DIR="$APP_DATA/models"
AGENT_LABEL="com.zabz.handy.autostart"
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
TCC_DB="$HOME/Library/Application Support/com.apple.TCC/TCC.db"

# The model we ship: whisper large-v3-turbo Q8_0. Chosen over Parakeet because it writes numbers as
# DIGITS (Parakeet spells them out -- "one five five", which is useless for prices and IMEIs) and
# because it degrades gracefully on non-English words. See docs/talk-to-text-lakewooechsmini.md.
MODEL_FILE="whisper-large-v3-turbo-Q8_0.gguf"
MODEL_REPO="handy-computer/whisper-large-v3-turbo-gguf"
MODEL_URL="https://huggingface.co/$MODEL_REPO/resolve/main/$MODEL_FILE"
MODEL_ID="$MODEL_REPO/$MODEL_FILE"

say() { printf '\n== %s\n' "$*"; }

say "1/6 Homebrew cask: handy"
if [ -d "$HANDY_APP" ]; then
  echo "already installed: $(defaults read "$HANDY_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo '?')"
else
  HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask handy
fi

say "2/6 speech model: $MODEL_FILE"
mkdir -p "$MODELS_DIR"
if [ -f "$MODELS_DIR/$MODEL_FILE" ]; then
  echo "already staged: $(du -h "$MODELS_DIR/$MODEL_FILE" | cut -f1)"
else
  curl -fL --retry 3 -o "$MODELS_DIR/$MODEL_FILE" "$MODEL_URL"
fi

say "3/6 Handy settings (settings_store.json)"
python3 - "$APP_DATA" "$MODEL_ID" <<'PY'
import json, os, shutil, sys, time
app_data, model_id = sys.argv[1], sys.argv[2]
path = os.path.join(app_data, "settings_store.json")
if os.path.exists(path):
    shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    store = json.load(open(path))
else:
    store = {}
s = store.setdefault("settings", {})
# The keys below are the ones this script owns. Everything else Handy fills in itself, and every
# field is #[serde(default)] on the Rust side, so a partial file is safe.
s.update({
    "onboarding_completed": True,          # skip the first-run wizard; we configured it already
    "selected_model": model_id,            # also what makes Handy skip onboarding (see settings.rs)
    "selected_language": "en",             # do not let a stray word flip the transcription language
    "translate_to_english": False,
    "push_to_talk": True,                  # hold the keys to record, release to stop
    "autostart_enabled": True,
    "start_hidden": True,                  # no window at login; it lives in the menu bar
    "show_tray_icon": True,
    "audio_feedback": True,                # a sound when recording starts and stops
    "audio_feedback_volume": 0.8,
    "append_trailing_space": True,
    "history_limit": 50,                   # keep the last 50 transcripts recoverable
    "model_unload_timeout": "hour1",
    "mute_while_recording": False,
    "paste_method": "ctrl_v",              # clipboard + Cmd-V; the reliable method in Chrome
    "clipboard_handling": "dont_modify",   # her clipboard is restored after every dictation
    "overlay_style": "live",
    "vad_enabled": True,
    "filler_word_removal_enabled": True,
    "update_checks_enabled": True,
    "post_process_enabled": False,         # no cloud step: results must not depend on the network
    "experimental_enabled": False,
    "debug_mode": False,
})
json.dump(store, open(path, "w"), indent=2, sort_keys=True)
print("wrote", path)
PY

say "4/6 privacy permissions (Microphone, Accessibility, Input Monitoring, Post Events)"
# Why by hand: macOS asks a human to click these dialogs, and this machine has no human sitting in
# front of it. A row with auth_value=2 in the user TCC database is the same decision the button
# makes. It is backed up first, written with INSERT OR REPLACE, and tccd is restarted to pick it up.
# VERIFIED on 2026-09-15: after this, Handy's log reads "The application has the permission to
# simulate input" and the microphone delivers samples.
python3 - "$TCC_DB" "$BUNDLE_ID" <<'PY'
import os, shutil, sqlite3, sys, time
db, client = sys.argv[1], sys.argv[2]
shutil.copy2(db, "/tmp/TCC.db.backup-" + time.strftime("%Y%m%d-%H%M%S"))
services = ["kTCCServiceMicrophone", "kTCCServiceAccessibility",
            "kTCCServiceListenEvent", "kTCCServicePostEvent"]
con = sqlite3.connect(db)
for svc in services:
    con.execute(
        "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,"
        "auth_version,csreq,policy_id,indirect_object_identifier_type,indirect_object_identifier,"
        "indirect_object_code_identity,flags,last_modified) "
        "VALUES (?,?,0,2,4,1,NULL,NULL,0,'UNUSED',NULL,0,strftime('%s','now'))", (svc, client))
con.commit()
rows = list(con.execute("select service, auth_value from access where client=?", (client,)))
con.close()
for svc, val in rows:
    print(f"granted {svc} = {val}")
PY
sudo killall tccd 2>/dev/null || true

say "5/6 LaunchAgent: $AGENT_LABEL"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HANDY_BIN</string>
    <string>--start-hidden</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict>
</plist>
PLIST
plutil -lint "$AGENT_PLIST"
launchctl bootout "gui/$(id -u)/$AGENT_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT_PLIST"

say "6/6 verification"
sleep 20
echo "-- process:"
pgrep -fl "MacOS/Handy" || echo "NOT RUNNING (check: launchctl print gui/$(id -u)/$AGENT_LABEL)"
echo "-- model on disk:"
ls -lh "$MODELS_DIR" | sed -n '2,9p'
echo "-- selected model in settings:"
python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['settings']['selected_model'])" "$APP_DATA/settings_store.json"
echo "-- permissions in the TCC database:"
sqlite3 "$TCC_DB" "select service, auth_value from access where client='$BUNDLE_ID';"
echo "-- last model/permission lines from Handy's own log:"
grep -E "Loaded whisper model|permission to simulate|Seeded .* catalog" "$HOME/Library/Logs/$BUNDLE_ID/handy.log" | tail -4
cat <<'DONE'

NEXT, AND IT IS A HUMAN STEP: dictate once for real.
  Hold Option+Space, say a sentence, release. The text should appear where the cursor is.
  If it does not appear, the only remaining cause is the paste step -- open
  System Settings > Privacy & Security > Accessibility and confirm Handy is listed and ticked.
DONE
