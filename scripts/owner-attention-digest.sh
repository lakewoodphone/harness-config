#!/bin/bash
# owner-attention-digest.sh — assemble "what needs the owner's attention" in one call.
# This is the secretary-side maintainer of the OWNER ATTENTION QUEUE (per owner comms contract 2026-08-30).
# Copilot reads this on "what's up" / "catch me up" — it must always be fresh.
#
# Install: cron every 30 min:  */30 * * * * /home/zabz/personal-secretary-mvp/scripts/server/owner-attention-digest.sh > /home/zabz/secretary-attention-digest/latest.txt 2>&1
# Manual:  Get-Content scripts/server/owner-attention-digest.sh -Raw | ssh secretary-ts "tr -d '\r' | bash -s"
cd /home/zabz/personal-secretary-mvp
DB=data/secretary.db
D=$(date -u +%Y-%m-%dT%H:%MZ)

echo "=== OWNER ATTENTION DIGEST — $D ==="

echo ""
echo ""
python3 "$(dirname "$0")/check-dsh-freshness.py" 2>&1 || true

echo ""
echo "── 0a. WHAT THE COMPANY FOUND WRONG ABOUT ITSELF (ceo-kernel sentinel, every 5 min) ──"
python3 "$(dirname "$0")/sentinel-findings.py" 2>&1 || true

echo ""
echo "── 0b. WORK COMPLETION (honest) — 'completed' split by whether work was actually done ──"
echo "     A session that ran out of budget is not a completion; the old count said it was."
sqlite3 -separator ' | ' "$DB" "
SELECT 'last 24h | finished=' || COUNT(*) ||
       ' | completed=' || SUM(status='completed') ||
       ' genuine=' || SUM(CASE WHEN status='completed' AND output_log LIKE '%[WORK_DONE]%' THEN 1 ELSE 0 END) ||
       ' hollow='  || SUM(CASE WHEN status='completed' AND output_log NOT LIKE '%[WORK_DONE]%' THEN 1 ELSE 0 END) ||
       ' | failed=' || SUM(status='failed')
FROM work_sessions WHERE updated_at > datetime('now','-1 day');" 2>&1

echo ""
echo "── 0c. SEARCH INDEX FRESHNESS (a stale index answers confidently and wrongly) ──"
python3 "$(dirname "$0")/check-search-freshness.py" 2>&1 || true
echo "── 1. URGENT QUEUED ITEMS (owner_message_queue, last 3d, urgent) ──"
sqlite3 -separator ' | ' "$DB" "SELECT urgency, status, substr(body,1,160), created_at FROM owner_message_queue WHERE created_at > datetime('now','-3 days') AND urgency='urgent' ORDER BY id DESC LIMIT 8;" 2>&1

echo "── 1b. DELIVERY — did anything actually REACH the owner? (queue depth is not delivery) ──"
# Measured separately from 1 on purpose: a full queue with no recent sent_at is a
# SEVERED channel, not a busy one. The newest sent row here was 2026-07-19 for 57
# days while 298 messages sat 'held' and every reader assumed the channel was fine.
sqlite3 -separator ' | ' "$DB" "SELECT 'owner_message_queue: newest sent = ' || COALESCE(MAX(sent_at),'NEVER') || ' (' || CAST(ROUND(julianday('now') - julianday(MAX(sent_at)),0) AS INT) || 'd ago); undelivered now = ' || (SELECT COUNT(*) FROM owner_message_queue WHERE status IN ('held','queued')) FROM owner_message_queue WHERE status='sent';" 2>&1
sqlite3 -separator ' | ' "$DB" "SELECT 'email_drafts: newest sent = ' || COALESCE(MAX(sent_at),'NEVER') || '; pending review = ' || (SELECT COUNT(*) FROM email_drafts WHERE status='pending_review') || ' (oldest ' || COALESCE((SELECT MIN(created_at) FROM email_drafts WHERE status='pending_review'),'n/a') || ')' FROM email_drafts;" 2>&1

echo ""
echo "── 1c. CUSTOMERS WAITING ON A REPLY (comms index: Dialpad texts, calls, voicemail, email) ──"
# One line, and only when the number is above zero. The index behind this already
# collapses acknowledgements ("ok", "thanks") and carrier opt-outs (STOP), so what is
# left is "someone asked us something and heard nothing back" -- the most actionable
# single number in this digest. It is read from the one source of truth rather than
# recomputed here, and it is kept to one line on purpose: this digest's readers stop
# reading when a section grows, which is the measured history of this file (P40).
CW=$(python3 /home/zabz/.fsearch/comms-search.py --json waiting --days 3 --limit 1 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('total_waiting',0))" 2>/dev/null)
case "$CW" in
  ''|*[!0-9]*) : ;;
  0) : ;;
  *) echo "🔔 $CW customer(s) waiting on a reply (last 3 days) — python3 /home/zabz/.fsearch/comms-search.py waiting --days 3" ;;
esac

echo "── 2. EMAIL TRIAGE (last 48h, by category) ──"
sqlite3 -separator ' | ' "$DB" "SELECT count(*) AS n, category, action_status FROM email_triage_log WHERE created_at > datetime('now','-2 days') GROUP BY category, action_status ORDER BY n DESC LIMIT 12;" 2>&1
echo "── unread email needing action (action_status != done) ──"
sqlite3 -separator ' | ' "$DB" "SELECT account_email, substr(subject,1,60), action_status, created_at FROM email_triage_log WHERE created_at > datetime('now','-2 days') AND action_status NOT IN ('done','archived','filed') ORDER BY id DESC LIMIT 8;" 2>&1

echo ""
echo "── 3. GOOGLE VOICE SYNOPSIS (via Gmail forwarding — works even when GV app is logged out) ──"
# GV numbers: account1 eliyahuzabrowsky = 17325691594, account2 ezabz68 = 17329943420
# Forwarded emails come from the GV number (texts) or voice-noreply@google.com (texts/calls/voicemails)
curl -s -m 25 "http://localhost:8002/gmail/inbox?account=eliyahuzabrowsky@gmail.com&query=(from%3A17325691594%20OR%20from%3Avoice-noreply%40google.com)%20newer_than%3A3d&max=15" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
ms = d.get('messages', [])
if not ms:
    print('(no GV emails in last 3d for account 1)')
for m in ms:
    print(m.get('date','?')[:22], '|', (m.get('from','?').split('<')[0].strip() or m.get('from','?'))[:30], '|', m.get('subject','?')[:45], '|', (m.get('snippet','') or '')[:60].replace(chr(10),' '))
" 2>&1
echo "── voicemails & missed calls specifically (need transcription / callback) ──"
curl -s -m 25 "http://localhost:8002/gmail/inbox?account=eliyahuzabrowsky@gmail.com&query=(%22missed%20call%22%20OR%20voicemail)%20newer_than%3A3d&max=8" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
ms = d.get('messages', [])
if not ms:
    print('(no missed calls / voicemails in last 3d)')
for m in ms:
    print(m.get('date','?')[:22], '|', (m.get('from','?').split('<')[0].strip() or m.get('from','?'))[:30], '|', m.get('subject','?')[:60])
" 2>&1

echo ""
echo "── 4. COMMS CAPTURE FRESHNESS (dialpad/twilio) ──"
sqlite3 -separator ' | ' "$DB" "SELECT direction, count(*) AS n, max(fetched_at) AS last FROM dialpad_sms_cache WHERE fetched_at > datetime('now','-2 days') GROUP BY direction;" 2>&1

echo ""
echo "── 5. OPEN TASKS NEEDING OWNER (high/urgent or approve/decision/pay) ──"
sqlite3 -separator ' | ' "$DB" "SELECT id, substr(title,1,60), priority, substr(description,1,80) FROM tasks WHERE status='open' AND (priority IN ('high','urgent') OR lower(title) LIKE '%approve%' OR lower(title) LIKE '%owner%' OR lower(title) LIKE '%decision%' OR lower(title) LIKE '%pay%') ORDER BY id DESC LIMIT 10;" 2>&1

echo ""
echo "── 6. PENDING APPROVALS (spend_requests / human_jobs) ──"
sqlite3 -separator ' | ' "$DB" "SELECT 'spend', id, substr(title,1,60), status, amount_usd FROM spend_requests WHERE status IN ('pending','proposed') ORDER BY id DESC LIMIT 6;" 2>&1
sqlite3 -separator ' | ' "$DB" "SELECT 'human', id, substr(title,1,60), status FROM human_jobs WHERE status IN ('pending','proposed') ORDER BY id DESC LIMIT 6;" 2>&1

echo ""
echo "── 7. CALENDAR (next 3 days) ──"
curl -s -m 20 "http://localhost:8002/calendar/events?days=3" 2>/dev/null | head -c 600; echo

echo ""
echo "── 7b. LIFE DOMAINS (L1 registry — gaps needing work) ──"
PYTHONPATH=. .venv/bin/python -m app.services.life_domains 2>/dev/null | tail -n +2 || echo "(life_domains unavailable)"

echo ""
echo "── 7c. DOC & SUBSCRIPTION REGISTRY (L3 — dates in next 30d) ──"
PYTHONPATH=. .venv/bin/python -m app.services.doc_registry 2>/dev/null || echo "(doc_registry unavailable)"

echo ""
echo "── 7d. LATEST BRIEFING (L4 — surfaced via queue, not SMS) ──"
sqlite3 -separator ' | ' "$DB" "SELECT substr(body,1,400), created_at FROM owner_message_queue WHERE body LIKE '%briefing%' ORDER BY id DESC LIMIT 1;" 2>&1

echo ""
echo "── 8. HEALTH CHECKS ──"
PROBLEMS=0
# API
code=$(curl -s -m 8 -o /dev/null -w "%{http_code}" http://localhost:8002/health 2>/dev/null)
if [ "$code" = "200" ]; then echo "API (8002):        ✅ UP"; else echo "API (8002):        🔴 DOWN ($code)"; PROBLEMS=$((PROBLEMS+1)); fi
# Tunnel / dashboard reachability (out through Cloudflare, back through tunnel)
tcode=$(curl -s -m 15 -o /dev/null -w "%{http_code}" https://ai.abletelsolutions.com/health 2>/dev/null)
if [ "$tcode" = "200" ]; then echo "Tunnel:            ✅ UP"; else echo "Tunnel:            🔴 DOWN ($tcode)"; PROBLEMS=$((PROBLEMS+1)); fi
# Gmail auth (expect >=2 authenticated accounts)
gauth=$(curl -s -m 15 http://localhost:8002/gmail/status 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(sum(1 for a in d.get('accounts',[]) if a.get('authenticated')))" 2>/dev/null)
if [ -n "$gauth" ] && [ "$gauth" -ge 2 ]; then echo "Gmail auth:        ✅ $gauth accounts"; elif [ -n "$gauth" ]; then echo "Gmail auth:        ⚠️ only $gauth account(s)"; PROBLEMS=$((PROBLEMS+1)); else echo "Gmail auth:        🔴 UNKNOWN"; PROBLEMS=$((PROBLEMS+1)); fi
# Dialpad capture: webhook liveness (last 6h) + stored-SMS freshness (>24h = stale)
wh=$(journalctl -u secretary-api.service --since "6 hours ago" 2>/dev/null | grep -c "webhook/dialpad")
dh=$(sqlite3 "$DB" "SELECT CAST((julianday('now') - julianday(substr(max(created_at),1,19)))*24 AS INT) FROM dialpad_sms_cache;" 2>/dev/null)
if [ -n "$wh" ] && [ "$wh" -gt 0 ]; then echo "Dialpad pipe:      ✅ LIVE ($wh webhooks/6h, last SMS ${dh}h ago)"; elif [ -n "$dh" ] && [ "$dh" -gt 24 ]; then echo "Dialpad pipe:      ⚠️ QUIET ${dh}h no SMS (check if expected)"; PROBLEMS=$((PROBLEMS+1)); elif [ -n "$dh" ]; then echo "Dialpad pipe:      ⚠️ no webhooks 6h, last SMS ${dh}h ago"; PROBLEMS=$((PROBLEMS+1)); else echo "Dialpad pipe:      🔴 no data"; PROBLEMS=$((PROBLEMS+1)); fi
# Backup freshness (hours since newest backup dir)
bl=$(ls -dt /home/zabz/secretary-backups/*/ 2>/dev/null | head -1)
if [ -n "$bl" ]; then
  bh=$(python3 -c "import os,time;print(int((time.time()-os.path.getmtime('${bl%/}'))/3600))" 2>/dev/null)
  if [ -n "$bh" ] && [ "$bh" -le 8 ]; then echo "Backup:            ✅ ${bh}h ago"; else echo "Backup:            ⚠️ ${bh}h ago"; PROBLEMS=$((PROBLEMS+1)); fi
else echo "Backup:            🔴 none found"; PROBLEMS=$((PROBLEMS+1)); fi
# Disk (warn >= 85%)
du=$(df -h / | tail -1 | awk '{print $5}' | tr -d '%')
echo -n "Disk:              "; if [ "${du:-0}" -lt 85 ]; then echo "✅ ${du}% used"; else echo "🔴 ${du}% used"; PROBLEMS=$((PROBLEMS+1)); fi
# Swap used in MiB (warn >= 2048)
sw=$(free -m | awk '/Swap:/{print $3}')
echo -n "Swap:              "; if [ -n "$sw" ] && [ "$sw" -lt 2048 ]; then echo "✅ ${sw}Mi of $(free -m | awk '/Swap:/{print $2}')Mi"; else echo "⚠️ ${sw}Mi used"; PROBLEMS=$((PROBLEMS+1)); fi
# WAL (cap 64MB)
wal=$(stat -c%s data/secretary.db-wal 2>/dev/null || echo 0)
echo -n "WAL:               "; if [ "$wal" -lt 67108864 ]; then echo "✅ $(($wal/1024/1024))MB (cap 64MB)"; else echo "⚠️ $(($wal/1024/1024))MB near cap"; PROBLEMS=$((PROBLEMS+1)); fi
# Home Assistant (Shabbat power-down expected)
hcode=$(curl -s -m 5 -o /dev/null -w "%{http_code}" http://homeassistant.local:8123/ 2>/dev/null)
echo -n "Home Assistant:    "; if [ "$hcode" = "200" ]; then echo "✅ UP"; else echo "⚠️ OFFLINE (Shabbat power-down — flip on at office)"; fi
echo ""
echo "── 9. CUSTOMER CORPUS ↔ PRODUCTION ──"
# WHY THIS SECTION EXISTS (added 2026-09-17)
# The owner digest was the ONE failure surface that actually worked, and it covered config, API,
# tunnel, Gmail, Dialpad, backup, disk, swap, WAL and Home Assistant -- everything except the
# customer corpus. Measured the same day: the hub->production case push had been FAILING on every
# run since at least 2026-09-15T23:45Z (rc=1, `would_create` 7-9), and `lpt-hub-refresh` had been
# wedged for 46 hours, and the digest said nothing about either. Three status files held the truth
# and had ZERO consumers. This closes that class: a corpus gap can now only be silent if this
# section itself fails, and it fails loudly (`could not read`).
#
# THE RULE THIS ENCODES: reading a status file is not evidence that the thing it describes is
# alive. `lpt-recon.py` wrote a check log that nothing read; `lpt-hub-refresh` wrote a status file
# that one unread script read. So this section reports the EFFECT (records behind, hours stuck)
# next to the mechanism's own claim (`status`), and it says plainly when it cannot read one.
RECON_STATUS="/home/zabz/.lpt-recon/status.json"
REFRESH_STATUS="/home/zabz/.lpt-hub-refresh/status.json"
CORPUS=$(python3 -c '
import json, os, time
out = {"gap": None, "errors": None, "refresh": "unreadable", "records": None, "ageh": None}
try:
    r = json.load(open("/home/zabz/.lpt-recon/status.json"))
    out["gap"] = int(r.get("push_would_create", 0) or 0)
    out["errors"] = int(r.get("push_errors", 0) or 0)
    out["ageh"] = round((time.time() - os.path.getmtime("/home/zabz/.lpt-recon/status.json")) / 3600, 1)
except Exception:
    out["gap"] = -1
try:
    f = json.load(open("/home/zabz/.lpt-hub-refresh/status.json"))
    out["refresh"] = str(f.get("status", "?"))
    out["records"] = f.get("records")
except Exception:
    pass
print(json.dumps(out))
' 2>/dev/null || echo '{"gap": -1}')
cgap=$(printf '%s' "$CORPUS"      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("gap"))' 2>/dev/null || echo -1)
cage=$(printf '%s' "$CORPUS"      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("ageh"))' 2>/dev/null || echo "?")
crec=$(printf '%s' "$CORPUS"      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("records"))' 2>/dev/null || echo "?")
cref=$(printf '%s' "$CORPUS"      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("refresh"))' 2>/dev/null || echo "?")
if [ "$cgap" = "-1" ] || [ -z "$cgap" ]; then
  echo -n "Corpus push:       "; echo "🔴 COULD NOT READ — the corpus surface is UNMEASURED, not healthy"
  PROBLEMS=$((PROBLEMS+1))
else
  echo -n "Corpus records:    "; echo "$crec in the authority clone (refresh status: $cref)"
  echo -n "Corpus push gap:   "
  if [ "$cgap" -gt 0 ]; then
    echo "🔴 $cgap record(s) in the hub but NOT in production (measured ${cage}h ago)"
    PROBLEMS=$((PROBLEMS+1))
  else
    echo "✅ none — every hub record has a production order (measured ${cage}h ago)"
  fi
fi
echo ""
if [ "$PROBLEMS" -gt 0 ]; then echo "🔴 $PROBLEMS problem(s) — see above"; else echo "✅ All health checks OK"; fi
echo "=== END DIGEST ==="
