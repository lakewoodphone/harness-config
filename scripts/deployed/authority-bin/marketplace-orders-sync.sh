#!/usr/bin/env bash
# marketplace-orders-sync.sh — keep the marketplace purchase-order store fed from Gmail.
#
# WHAT IT DOES, once a day:
#   1. reads Amazon and eBay receipt mail from Gmail (READ-ONLY; this never sends anything),
#   2. parses it and upserts `marketplace_orders` / `marketplace_order_items` plus the legacy
#      `amazon_orders` / `amazon_order_items` and the new `ebay_orders` / `ebay_order_items`,
#   3. matches the orders to card charges in the ledger's `transactions` table and writes the
#      accepted links as `transaction_evidence` rows.
#
# INSTALL (the manager applies this; the fleet agent that wrote it did not):
#     sudo install -m 0755 /root/personal-secretary-mvp/scripts/finance/marketplace-orders-sync.sh \
#          /usr/local/bin/marketplace-orders-sync.sh
#     sudo crontab -l -u root | { cat; echo "10 5 * * * /usr/local/bin/marketplace-orders-sync.sh"; } | sudo crontab -u root -
#
#   or, as a systemd timer (files delivered alongside this script):
#     sudo install -m 0644 deploy/systemd/lpt-marketplace-orders.service /etc/systemd/system/
#     sudo install -m 0644 deploy/systemd/lpt-marketplace-orders.timer   /etc/systemd/system/
#     sudo systemctl daemon-reload && sudo systemctl enable --now lpt-marketplace-orders.timer
#
# SCHEDULE. 05:10 UTC. The Amazon Playwright ingest this replaces was configured for 04:00 local
# and never ran because its scraper repo is absent. Gmail arrives when it arrives, so the only
# requirement is that the run is after the day's mail; 05:10 UTC leaves room for the 04:30 Plaid
# sync to finish so the charge side of the match is already in the ledger.
#
# WINDOW. `--window-days 90` searches the last 90 days of mail rather than the whole history. The
# store is a permanent accumulator, so a narrower window loses nothing and keeps the daily run
# cheap; 90 days rather than 30 so a clock that is down for two months still catches up. Set
# MARKETPLACE_ORDERS_FULL=1 to force an unwindowed backfill.
#
# RETRY, because a transient lock is not a reason to lose a day of money. The house measured this
# on the 13.2 GiB secretary.db (scripts/nightly-plaid-sync.sh, 2026-09-30): the first attempt fails
# with "database is locked" and the second succeeds. Same treatment here.
#
# FAIL LOUD. Exit non-zero when a step ultimately fails and write a status JSON, so a health check
# can read the truth without parsing a log.
set -uo pipefail

APP_DIR="${MARKETPLACE_ORDERS_APP_DIR:-/root/personal-secretary-mvp}"
LEDGER="${ACCOUNTING_DB_PATH:-/root/accounting-data/live/accounting.db}"
LOG_FILE="${MARKETPLACE_ORDERS_LOG:-/root/marketplace-orders-sync.log}"
STATUS_FILE="${MARKETPLACE_ORDERS_STATUS:-/root/.marketplace-orders-status.json}"
LOCK_FILE="${MARKETPLACE_ORDERS_LOCK:-/run/marketplace-orders-sync.lock}"
ACCOUNT="${MARKETPLACE_ORDERS_ACCOUNT:-lakewoodphoneandtech@gmail.com}"
WINDOW_DAYS="${MARKETPLACE_ORDERS_WINDOW_DAYS:-90}"
ATTEMPTS="${MARKETPLACE_ORDERS_ATTEMPTS:-3}"
RETRY_SLEEP="${MARKETPLACE_ORDERS_RETRY_SLEEP:-25}"
VENV_PY="$APP_DIR/.venv/bin/python"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1" | tee -a "$LOG_FILE"; }

# One run at a time. A second run trampling the first is how a store ends up half-written.
exec 9>"$LOCK_FILE" || { log "FATAL cannot open lock $LOCK_FILE"; exit 2; }
if ! flock -n 9; then
  log "another marketplace-orders run holds $LOCK_FILE — exiting without doing anything"
  exit 0
fi

if [ ! -x "$VENV_PY" ]; then
  log "FATAL interpreter not executable: $VENV_PY"
  exit 2
fi

# run_step <name> <cli-args...> -> runs the sync CLI, retrying while the failure says "locked".
run_step() {
  local name="$1"; shift
  local out rc attempt
  for attempt in $(seq 1 "$ATTEMPTS"); do
    out=$(cd "$APP_DIR" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$APP_DIR" \
          ACCOUNTING_DB_PATH="$LEDGER" \
          "$VENV_PY" -c 'from app.services.marketplace_order_sync import main; raise SystemExit(main())' \
          "$@" 2>&1)
    rc=$?
    printf '%s\n' "$out" >> "$LOG_FILE"
    if [ "$rc" -eq 0 ]; then
      RUN_OUTPUT="$out"
      return 0
    fi
    if printf '%s' "$out" | grep -qi 'database is locked'; then
      log "$name: attempt $attempt/$ATTEMPTS hit a lock; retrying in ${RETRY_SLEEP}s"
      sleep "$RETRY_SLEEP"
      continue
    fi
    log "$name: attempt $attempt/$ATTEMPTS failed (rc=$rc), not a lock — not retrying"
    RUN_OUTPUT="$out"
    return "$rc"
  done
  log "$name: gave up after $ATTEMPTS attempts"
  RUN_OUTPUT="$out"
  return 1
}

INGEST_ARGS=(ingest --accounts "$ACCOUNT" --json)
if [ "${MARKETPLACE_ORDERS_FULL:-0}" != "1" ]; then
  INGEST_ARGS+=(--window-days "$WINDOW_DAYS")
fi

log "=== marketplace-orders sync start (ledger=$LEDGER account=$ACCOUNT) ==="
STATUS=0

run_step ingest "${INGEST_ARGS[@]}"
INGEST_RC=$?
INGEST_OUT="$RUN_OUTPUT"
[ "$INGEST_RC" -eq 0 ] || { log "ingest FAILED"; STATUS=1; }

if [ "$INGEST_RC" -eq 0 ]; then
  run_step match match --write-evidence --json
  MATCH_RC=$?
  MATCH_OUT="$RUN_OUTPUT"
  [ "$MATCH_RC" -eq 0 ] || { log "match FAILED"; STATUS=1; }
else
  MATCH_RC=99
  MATCH_OUT="{}"
fi

STATUS="$STATUS" INGEST_RC="$INGEST_RC" MATCH_RC="$MATCH_RC" \
INGEST_OUT="$INGEST_OUT" MATCH_OUT="$MATCH_OUT" LEDGER="$LEDGER" ACCOUNT="$ACCOUNT" \
"$VENV_PY" - "$STATUS_FILE" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}

ingest = load(os.environ.get("INGEST_OUT", ""))
match = load(os.environ.get("MATCH_OUT", ""))
report = match.get("report", {})
payload = {
    "ran_at": datetime.now(timezone.utc).isoformat(),
    "ok": os.environ.get("STATUS") == "0",
    "ledger": os.environ.get("LEDGER"),
    "account": os.environ.get("ACCOUNT"),
    "ingest_rc": int(os.environ.get("INGEST_RC", "99")),
    "match_rc": int(os.environ.get("MATCH_RC", "99")),
    "orders_parsed": ingest.get("orders"),
    "canonical": ingest.get("canonical"),
    "legacy": ingest.get("legacy"),
    "evidence": match.get("evidence"),
    "match_status_counts": report.get("status_counts"),
    "by_year": ingest.get("by_year"),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=1)

counts = payload.get("match_status_counts") or {}
print(f"[marketplace-orders] orders={payload['orders_parsed']} "
      f"new={ (payload.get('canonical') or {}).get('new') } "
      f"changed={ (payload.get('canonical') or {}).get('changed') } "
      f"evidence={ (payload.get('evidence') or {}).get('written') } "
      f"matched={counts.get('matched')} unmatched={counts.get('no_candidate')} "
      f"ok={payload['ok']}")
sys.exit(0 if payload["ok"] else 1)
PYEOF
STATUS=$?

log "=== marketplace-orders sync done (status=$STATUS) ==="
exit "$STATUS"
