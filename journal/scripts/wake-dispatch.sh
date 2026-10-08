#!/bin/bash
# Release ONE wake row: start a fresh DSH session on the always-on desktop and
# bring its result back.
#
# WHY THIS EXISTS. Nothing on a server can start a DSH session, so before this a
# reply that needed work sat in a queue until a human opened one. The primitive is
# `dsh --profile headless "<task>"` - answer one task, print the result, exit -
# verified 2026-09-18. The desktop is always on and has the headless profile;
# secratary reaches it over the mesh; the prompt travels as a FILE so no nested
# quoting is ever constructed.
#
# It does NOT file its own work. A row is only filed by something that knows there
# is work - the responder files one when a reply arrives to an outstanding await.
# Filing on a timer would burn a session every five minutes to be told there is
# nothing to do.
set -u

WAKE="python3 /home/zabz/bin/wake.py"
DESKTOP="zabz-tech-ts"
RUNNER='C:\Users\ezabz\bin\wake-run.ps1'
# Forward slashes on the scp targets: scp reads a Windows path with backslashes
# as escapes. The first version used backslashes here and the result came back
# EMPTY while the file on the desktop was fine - the transfer had silently failed
# and 2>/dev/null hid it.
PROMPT_WIN='C:/Users/ezabz/bin/wake-prompt.txt'
OUT_WIN='C:/Users/ezabz/bin/wake-out.txt'
LOG=/home/zabz/.sms-inbox/wake-dispatch.log
MAX_PER_DAY=${MAX_PER_DAY:-8}

# --- cost guard: a runaway fleet of sessions is the failure mode to prevent ---
TODAY=$(date -u +%Y-%m-%d)
DONE=$(grep -c "^released $TODAY" "$LOG" 2>/dev/null || echo 0)
if [ "$DONE" -ge "$MAX_PER_DAY" ]; then
  echo "$(date -Is) daily wake cap reached ($DONE/$MAX_PER_DAY) - not releasing" >> "$LOG"
  exit 0
fi

CLAIM=$($WAKE claim --by zapz-tech-desktop 2>/dev/null)
if ! echo "$CLAIM" | grep -q '"row": *{'; then
  exit 0          # nothing to do; stay quiet on the quiet path
fi

ID=$(echo "$CLAIM" | python3 -c "import json,sys; print(json.load(sys.stdin)['row']['id'])")
SUBJ=$(echo "$CLAIM" | python3 -c "import json,sys; print(json.load(sys.stdin)['row']['subject'])")
PROMPT=$(echo "$CLAIM" | python3 -c "import json,sys; print(json.load(sys.stdin)['row']['prompt'])")

echo "=== $(date -Is) releasing wake #$ID ($SUBJ) ===" >> "$LOG"

printf '%s' "$PROMPT" > /tmp/wake-prompt.txt
if ! scp -q -o BatchMode=yes /tmp/wake-prompt.txt "$DESKTOP:$PROMPT_WIN"; then
  echo "prompt transfer failed" >> "$LOG"
  $WAKE finish "$ID" --failed --outcome "prompt transfer to the desktop failed"
  exit 1
fi

timeout 900 ssh -o ConnectTimeout=15 -o BatchMode=yes "$DESKTOP" \
  "powershell -NoProfile -ExecutionPolicy Bypass -File $RUNNER -PromptFile $PROMPT_WIN -OutFile $OUT_WIN" \
  >>"$LOG" 2>&1
RC=$?

scp -q -o BatchMode=yes "$DESKTOP:$OUT_WIN" /tmp/wake-out.txt 2>/dev/null
OUTCOME=$(tail -c 700 /tmp/wake-out.txt 2>/dev/null | tr '\n' ' ')
echo "released $TODAY wake #$ID exit=$RC" >> "$LOG"
echo "  outcome: $OUTCOME" >> "$LOG"

if [ $RC -eq 0 ]; then
  $WAKE finish "$ID" --outcome "$OUTCOME"
else
  $WAKE finish "$ID" --failed --outcome "exit $RC: $OUTCOME"
fi
