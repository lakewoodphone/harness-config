#!/bin/sh
# /usr/local/bin/finance-saas-sync.sh -- keep the Twilio and OpenAI spend feeds current.
#
# WHY (finance fleet 2026-10-13): `lpt-twilio-spend` had been frozen at 2026-08-01 and
# `lpt-openai-spend` at 2026-06-12 -- both reported STALE by `finance-freshness` -- because
# nothing on the cloud authority ever ran the SaaS billing ingest. The script lives in the
# quickbooks-agent repo, which was ALSO missing from this host until today.
#
# The script needs the app's own credentials and the live ledger path, and it loads neither
# by itself: its env loader had a hardcoded Windows path and its DB_PATH was a Windows
# literal. Both were fixed on this host 2026-10-13; this wrapper supplies ACCOUNTING_DB_PATH
# explicitly so the script cannot silently fall back to a path that does not exist.
set -eu
REPO=/opt/company/domains/finance/quickbooks-agent
if [ ! -d "$REPO" ]; then
  echo "ERROR: $REPO missing -- cannot run the SaaS spend ingest" >&2
  exit 2
fi
cd "$REPO"
export ACCOUNTING_DB_PATH=/root/accounting-data/live/accounting.db
exec python3 scripts/saas_billing_ingest.py "$@"
