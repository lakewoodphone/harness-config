#!/usr/bin/env bash
# order-feed-refresh.sh — keep the ledger's Amazon order history fresh, and say so
# when it cannot be.
#
# WHY: the scrapers that read the owner's Amazon accounts live on his desktop
# (scripts/finance/account-scrapers/) and write JSON; something has to move that JSON
# into the accounting ledger the CFO asks from. On 2026-10-02 nothing did: the
# ledger's newest order was 2026-09-10 while charges kept arriving, so no Amazon
# charge could be matched to an item -- which is exactly what the owner asked for.
#
# This runs the ingest and, when the feed is stale, raises ONE owner question with
# the one action only he can take. It never scrapes (the scrape needs a live browser
# session on his desktop); it only ingests what is there and reports honestly.
#
# Exit codes: 0 fresh, 3 stale (an owner question was filed), 1 the ingest failed.
set -uo pipefail

INGEST="/home/zabz/code/harness-config/scripts/ingest-order-history.py"
[ -f "$INGEST" ] || INGEST="/home/zabz/harness-config/scripts/ingest-order-history.py"
QUEUE="$HOME/bin/owner-queue.py"
LOG="$HOME/.order-feed-refresh.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG"; }

if [ ! -f "$INGEST" ]; then
  log "ERROR: ingest script not found at $INGEST"
  exit 1
fi

out="$(/usr/bin/python3 "$INGEST" 2>&1)"
rc=$?
echo "$out" | tail -20 >> "$LOG"

if [ "$rc" -eq 3 ]; then
  newest="$(echo "$out" | sed -n 's/.*newest order in the ledger: \([0-9-]*\).*/\1/p' | head -1)"
  log "STALE (newest order ${newest:-unknown}); raising one owner question"
  # owner-queue.py dedupes on the question text, so this stays ONE row however
  # often the cron fires.
  /usr/bin/python3 "$QUEUE" add \
    --question "Amazon order history in the ledger is stale (newest order ${newest:-unknown}). Re-login on the desktop so charges can be matched to items again?" \
    --recommendation "On the desktop (ZABZ-YOGA) run scripts/finance/account-scrapers/login_amazon.py --label personal, then --label business, then re-run the scrape. It takes about two minutes and needs your MFA; nothing else can refresh the session." \
    --options "I will log in now|Log in later, keep asking|Stop asking about this" \
    --context "The AI text line and the CFO both answer money questions from /home/zabz/accounting-data/live/accounting.db. Order detail (item, ASIN, order id) comes from amazon_orders/amazon_order_items, filled by this job. When the feed is stale every Amazon charge question can name only the amount and the card." \
    --blocks "every Amazon charge question that should name an item" \
    --severity high \
    --source order-feed-refresh >> "$LOG" 2>&1
  exit 3
fi

if [ "$rc" -ne 0 ]; then
  log "ERROR: ingest exited $rc"
  exit 1
fi
log "fresh - nothing to do"
exit 0
