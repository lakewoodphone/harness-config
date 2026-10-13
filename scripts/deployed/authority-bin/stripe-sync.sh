#!/bin/sh
# /usr/local/bin/stripe-sync.sh -- put the Stripe pull on a clock on the cloud authority.
#
# WHY THIS EXISTS (finance fleet 2026-10-13, slug `money-clock`)
#   The Stripe ingestion on this host is NOT scheduled, and it has not been since the
#   2026-10-11 cutover. Measured 2026-10-13:
#
#     * `scripts/finance/sync-stripe.py` is the one writer of the `lpt-stripe` ledger
#       rows — every one of them carries source_document_id='stripe-api-ingest', which
#       is the value that script stamps (its own module docstring).
#     * nothing on this host invokes it: not the crontab, not a systemd timer, not an
#       autopilot subsystem. Read-only probe: `finance-freshness` reports
#       `pull_state=unscheduled` for `lpt_stripe` for exactly that reason.
#     * the only thing that used to run it was step 4 of the OFFICE box's
#       `nightly-plaid-sync.sh`, and that box has been a frozen read-only rollback
#       anchor since the cutover. Its log stops at 2026-10-10T04:30:31Z.
#     * the consequence is money, not cosmetics: on 2026-10-13 a read-only Stripe
#       query found 7 charges created after the ledger's newest Stripe row, worth
#       1031.86 USD, that the books did not have — plus refunds 7 weeks behind.
#
# WHY A WRAPPER RATHER THAN A LONG CRONTAB LINE
#   The command needs a secret out of `/opt/company/.env` and a widened search window,
#   and every one of those needs shell quoting that a crontab line is a bad place to
#   get right. One file, reviewed once, called by cron. `cron-wrap.sh` records every
#   run of it in ~/.cron-status/runs.tsv, which `sources/cron-failures.py` reads.
#
# PREREQUISITE, MEASURED, AND NOT SATISFIED ON THIS HOST
#   sync-stripe.py needs the `stripe` python package. It is INSTALLED NOWHERE on this
#   box: not in /opt/company/.venv, not in any site-packages on the filesystem.
#   Verified 2026-10-13:
#       /opt/company/.venv/bin/python -c "import stripe"
#       -> ModuleNotFoundError: No module named 'stripe'
#   So this wrapper WILL fail with "ERROR: stripe package not installed" (rc=2) until
#   that dependency is installed into the app venv, which is a package install and
#   therefore the manager's to apply, not this fleet's. The failure is loud and lands
#   in runs.tsv and the log rather than looping silently.
#
# --days 400 IS DELIBERATE
#   sync-stripe.py is idempotent (it skips any external_transaction_id already present,
#   active or duplicate), so a wide window is self-healing: the first run closes the
#   whole cutover gap and every later run still only inserts what is missing. This is
#   the same window the office script used, and the office log shows the step finishing
#   in about 15 seconds, so the cost of the wide window is measured and small. A narrow
#   window would silently leave the 2026-10-09..2026-10-13 gap in the books forever.
#
# Usage: stripe-sync.sh [--dry-run|--days N|--since YYYY-MM-DD]   (extra args appended)
# Exit:  the interpreter's own exit code. 2 = environment/prerequisite problem.
set -u

APP_DIR="${APP_DIR:-/opt/company}"
LEDGER="${LEDGER:-/root/accounting-data/live/accounting.db}"
SECRET_FILE="$APP_DIR/.env"

STRIPE_SECRET_KEY="$(sed -n 's/^STRIPE_SECRET_KEY=//p' "$SECRET_FILE" 2>/dev/null | head -1 | tr -d '"' | tr -d "'")"
export STRIPE_SECRET_KEY

if [ -z "$STRIPE_SECRET_KEY" ]; then
  echo "stripe-sync: STRIPE_SECRET_KEY not found in $SECRET_FILE" >&2
  exit 2
fi

if [ ! -f "$LEDGER" ]; then
  echo "stripe-sync: ledger not found at $LEDGER" >&2
  exit 2
fi

exec env ACCOUNTING_DB_PATH="$LEDGER" \
  "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/finance/sync-stripe.py" \
  --days 400 "$@"
