#!/bin/bash
# lpt-credential-watch - the pay rail's credential must never go missing silently again.
# Detects ABSENT and EXPIRED (local JWT exp, no network, nothing spent).
# It cannot detect a REVOKED-but-unexpired token without spending it (lpt-ops/docs/web-parity.md 8),
# so absence and expiry - the two states that actually bit us - are what it covers.
ENV=/root/personal-secretary-mvp/.env
STATE=/root/lpt-credential-watch.state
TOK=$(grep -m1 '^LPT_API_REFRESH_TOKEN=' "$ENV" 2>/dev/null | cut -d= -f2-)
reason=""
if [ -z "$TOK" ]; then
  reason="absent from $ENV"
else
  reason=$(/home/zabz/personal-secretary-mvp/.venv/bin/python3 -c "
import base64,json,sys,time
t=sys.argv[1]
try:
    p=t.split('.')[1]; p+='='*(-len(p)%4)
    d=json.loads(base64.urlsafe_b64decode(p))
    left=int(d['exp'])-int(time.time())
    print('ok days=%d' % (left//86400) if left>0 else 'EXPIRED')
except Exception:
    print('malformed')
" "$TOK")
fi
printf '%s %s\n' "$(date -Is)" "$reason" > "$STATE"
case "$reason" in
  ok*) exit 0 ;;
esac
MARK=/root/lpt-credential-watch.lastalert
if [ -f "$MARK" ] && [ "$(date -d @$(cat "$MARK") +%F 2>/dev/null)" = "$(date +%F)" ]; then exit 1; fi
date +%s > "$MARK"
cd /root/code/harness-config/journal && /usr/bin/python3 tools/journal.py append pain \
  --title "lpt-web credential unusable ($reason) - no customer payment notice can be sent" \
  --body "lpt-credential-watch on secratary-cloud at $(date -Is): $reason. The pay rail (lpt-web owe-notice / pay-notice draft / pay-notice approve) fails closed without it, so no customer can be told what they owe until it is restored. Restore: see lpt-ops/docs/web-parity.md; the token is a MANAGER refresh token in $ENV, mode 0600. 2026-10-21 precedent: it was absent and a customer's pay text could not go out." \
  --tags "payments,lpt-web,credential" --quiet
exit 1
