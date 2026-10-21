#!/usr/bin/env bash
# model-catalog-refresh.sh -- keep textdecide's model-catalog cache in step with the gateway.
#
# WHY THIS EXISTS (2026-10-21): text-health A3 failed because the cache held 33 ids while
# /v1/models served 26.  The seven extras were exactly the Google ids that
# AI_GATEWAY_EXCLUDE_PROVIDERS=google removed at 02:39Z (docs/GATEWAY-GOOGLE-EXCLUDED.md).
# The cache was correct at 2026-10-20T14:20Z and nothing refreshed it afterwards.
#
# textdecide.catalog() rewrites the cache only as a side effect of a LIVE model read, and
# `--refresh-catalog` is the deliberate form.  The office's old sms-inbox cron chain ended
# with that command; the cloud port deliberately installed only the read-only sync half, so
# the cloud had no scheduled refresh at all.  This wrapper is that missing job.
#
# It is deliberately narrow: one command, one lock, one log line.  It never sends a text.
set -uo pipefail

LOG="${MODEL_CATALOG_REFRESH_LOG:-/root/.sms-inbox/catalog-refresh.log}"
LOCK="${MODEL_CATALOG_REFRESH_LOCK:-/run/textdecide-catalog.lock}"
PY="${MODEL_CATALOG_REFRESH_PYTHON:-/usr/bin/python3}"
CHECK="${MODEL_CATALOG_REFRESH_SCRIPT:-/root/bin/textdecide.py}"

mkdir -p "$(dirname "$LOG")" || exit 2
exec 9>"$LOCK" || exit 2
if ! flock -n 9; then
  printf '%s skip: previous refresh still holds %s\n' "$(date -u +%FT%TZ)" "$LOCK" >>"$LOG"
  exit 0
fi

out="$("$PY" "$CHECK" --refresh-catalog 2>&1)"
rc=$?
printf '%s rc=%s %s\n' "$(date -u +%FT%TZ)" "$rc" "$out" >>"$LOG"
exit "$rc"
