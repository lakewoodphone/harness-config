#!/bin/bash
# lpt-credential-watch - the LPT API credential must never go unusable silently.
#
# WHAT IT WATCHES. LPT_API_REFRESH_TOKEN in the authority's env file: seat
# agent-verification@lakewoodphoneandtech.com, users.id 300, MANAGER. It is a ROTATING
# one-shot secret - auth.refresh revokes the presented token and issues a new one.
#
# WHAT IT CAN NOW SEE, WHICH IT COULD NOT BEFORE. The old version detected ABSENT,
# EXPIRED and MALFORMED only, and said in its own header that a revoked-but-unexpired
# token was invisible without spending it. That was wrong: refresh_tokens.token is
# PLAIN TEXT, so the row can be looked up and isRevoked read without spending anything.
# 2026-10-26 is the day that mattered - a token was revoked by reuse detection and this
# watchdog would have reported "ok" for the 89 days it had left.
#
# WHAT A DEAD CREDENTIAL DOES AND DOES NOT BREAK. It blocks anything that calls
# api.lakewoodphoneandtech.com as a staff user (for example linking an unlinked terminal
# payment to its order). It does NOT block lpt-pay-notice / owe-notice / the pay rail:
# those docker exec into lpt-backend and call the services directly, with no token at
# all. The previous alarm text claimed the opposite and would have sent a future session
# chasing a pay-rail outage that does not exist.
#
# RESTORE, no password, no human step: python3 /root/bin/lpt-token --mint  (signs a fresh
# refresh token from the backend's own JWT_REFRESH_SECRET, inserts its row, installs it
# atomically), then python3 /root/bin/lpt-token  (one refresh; the rotation is written
# back to the env before the access token is used).
ENV=/root/personal-secretary-mvp/.env
STATE=/root/lpt-credential-watch.state
reason=$(python3 /root/bin/lpt-token --check 2>&1)
printf '%s %s\n' "$(date -Is)" "$reason" > "$STATE"
case "$reason" in
  ok*) exit 0 ;;
esac
MARK=/root/lpt-credential-watch.lastalert
if [ -f "$MARK" ] && [ "$(date -d @$(cat "$MARK") +%F 2>/dev/null)" = "$(date +%F)" ]; then exit 1; fi
date +%s > "$MARK"
cd /root/code/harness-config/journal && /usr/bin/python3 tools/journal.py append pain \
  --title "LPT API credential unusable ($reason) - staff-API calls will 401" \
  --body "lpt-credential-watch on secratary-cloud at $(date -Is): $reason. Seat agent-verification@lakewoodphoneandtech.com (users.id 300, MANAGER). This blocks staff-API calls such as payments.attachPaymentToWorkOrder; it does NOT block lpt-pay-notice or the pay rail, which docker exec into the backend and need no token. Restore with: python3 /root/bin/lpt-token --mint && python3 /root/bin/lpt-token. Never refresh this token by hand: it rotates on use, and a refresh whose result is not persisted is read as reuse and revokes the whole family (measured 2026-10-26)." \
  --tags "payments,lpt,credential" --quiet
exit 1
