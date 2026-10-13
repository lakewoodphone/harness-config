#!/usr/bin/env bash
# run-company-outcome-monitor.sh — the scheduled outcome check for the AI company.
# PORTED 2026-10-11 by workstream 137 from secratary:/home/zabz/bin/run-company-outcome-monitor.sh
# (2,840 B, mtime 2026-09-20 15:46). Every `/home/zabz` path is translated per
# 133-PORT-BRIEF.md: repo -> /opt/company, database -> /root/authority.db, state -> /root.
#
# WHY: the 2026-09-11 autopsy found that every monitor on the office box checked
# *liveness*, not *outcomes*: `/health` returned 200 throughout a six-day outage in which
# 3,246 ticks completed nothing. This is the missing instrument, run on a timer so that
# nobody has to remember to ask. Between the 05:43:36Z cutover and this port it ran on the
# office box against the FROZEN database and reported the frozen company as the outcome.
#
# It is deliberately INDEPENDENT of the FastAPI app: it runs from the venv directly, so a
# broken API cannot hide a broken company. It is read-only (the monitor opens the DB with
# mode=ro — company_outcome_monitor.py line 173) so it can never damage what it measures.
#
# WHAT CHANGED IN THE PORT, AND WHY
#   The one hardcoded office name that matters is the SYSTEMD UNIT the lock-contention
#   section reads its true count from: `journalctl -u secretary-api`. On this box that unit
#   does not exist, so the deployed module returned
#       journal_events = 0, undercount_factor = 0.0, journal_provenance = "... -> 0 matching lines"
#   while 2,499 journal lines sat in `company-api` — a false green in the very instrument
#   built to catch false greens. This wrapper therefore exports
#   COMPANY_OUTCOME_JOURNAL_UNIT=company-api, and the module (patched 2026-10-11, backup at
#   company_outcome_monitor.py.before-137) resolves its unit at runtime: env override
#   first, then the first candidate that exists on the host, and NEVER a fabricated zero.
set -u

APP_DIR="${APP_DIR:-/opt/company}"
OUT_DIR="${OUT_DIR:-/root/company-reports}"
DB="${DB:-/root/authority.db}"
KEEP_DAYS="${KEEP_DAYS:-90}"
JOURNAL_UNIT="${COMPANY_OUTCOME_JOURNAL_UNIT:-company-api}"
export COMPANY_OUTCOME_JOURNAL_UNIT="$JOURNAL_UNIT"

mkdir -p "$OUT_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TXT="$OUT_DIR/outcome-$STAMP.txt"
JSON="$OUT_DIR/outcome-$STAMP.json"

cd "$APP_DIR" || { echo "FATAL: no app dir $APP_DIR"; exit 1; }
if [ ! -x .venv/bin/python ]; then echo "FATAL: no venv python in $APP_DIR"; exit 1; fi
if [ ! -r "$DB" ]; then echo "FATAL: authority database $DB not readable"; exit 1; fi

# Bounded: if the monitor cannot finish in 5 minutes the box is in trouble and we want a
# loud timeout, not a hung timer unit.
timeout 300 .venv/bin/python -m app.services.company_outcome_monitor \
    --db "$DB" --windows 1,7,30 > "$TXT" 2>&1
rc=$?

# Machine-readable copy for anything that wants to trend it (JSON mode is a second run
# rather than a redirect of the first, so a crash in rendering cannot lose the data).
timeout 300 .venv/bin/python -m app.services.company_outcome_monitor \
    --db "$DB" --windows 1,7,30 --json > "$JSON" 2>/dev/null

VERDICT=$(grep -m1 '^VERDICT:' "$TXT" 2>/dev/null | awk '{print $2}')
[ -z "$VERDICT" ] && VERDICT="UNKNOWN"

# One line to the journal every run, so `journalctl -u company-outcome-monitor` is a
# trend line and not just a pile of files.
SUMMARY=$(grep -m1 'work sessions fail' "$TXT" 2>/dev/null | sed 's/^ *//')
echo "verdict=$VERDICT rc=$rc host=$(hostname) db=$DB ${SUMMARY:-no-summary} report=$TXT"

# Anything other than OK is a finding, and findings get a louder level. The exit code
# stays 0 so the timer unit does not go failed and get disabled — but the journal level
# and the presence of a NON-OK report file is what a human or agent greps for.
case "$VERDICT" in
  OK)        ;;
  INFO)      ;;
  WARN)      echo "WARN: company outcome degraded: $SUMMARY" ;;
  CRITICAL)  echo "CRITICAL: company work is failing: $SUMMARY" ;;
  STALE|UNMEASURED)
             echo "CRITICAL: company outcome NOT MEASURABLE ($VERDICT) — treat as blind, not healthy" ;;
  *)         echo "WARN: unrecognised verdict '$VERDICT'" ;;
esac

# Prune old reports so this cannot itself become a disk problem. THE ONLY DELETE IN THIS
# PORT: scoped to this script's own output directory and to files it named itself
# (`outcome-*`), never to a path a caller supplies.
PRUNED=$(find "$OUT_DIR" -maxdepth 1 -name 'outcome-*' -type f -mtime +"$KEEP_DAYS" -print -delete 2>/dev/null | wc -l)
[ "$PRUNED" -gt 0 ] && echo "pruned $PRUNED report(s) older than ${KEEP_DAYS}d from $OUT_DIR"

exit 0
