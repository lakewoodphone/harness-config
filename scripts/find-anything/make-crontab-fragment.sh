#!/usr/bin/env bash
# Generate the crontab fragment for the search indexes, with the base64 payloads the estate's
# install-crontab-fragment.sh requires. Prints the fragment on stdout; writes nothing.
#
# Payloads carry no output redirect: cron-wrap.sh is the estate's wrapper and it owns the log and the
# run ledger (~/.cron-status/runs.tsv), which is what makes a dead clock findable.
set -uo pipefail

enc() { printf '%s' "$1" | base64 -w0; }

REFRESH_CMD='/usr/local/bin/find-anything-build-indexes'
FRESH_CMD='/usr/local/bin/check-faindex-freshness'
GUARD_CMD='/root/bin/tool-body-guard.py --write-status'

# WHY THESE MINUTES AND NOT */15. `journal-commit`, `guard-registry`, `production-comms-freshness`
# and `disk-guard` all run on `*/15`, and `comms-refresh` on :07/:37. A first cut of this fragment
# used `*/15` and `:37` and collided with both: the index builder calls `journal.py status`, which
# rebuilds the journal cache, and two rebuilds landing on the same minute measured a
# `ps_search what=journal` at **21,902 ms** against a 5 s budget (2026-10-12). These minutes are
# congruent to 8 mod 15 and are not multiples of 5, 20 or 30, so they collide with nothing on this
# crontab.
cat <<EOF
# Search subsystem clocks. Installed 2026-10-12 by the search audit (journal H3571).
# WHY TWO JOBS AND NOT ONE. This estate shipped a silently dead search refresh twice: P2899 D2 (a
# trigger whose repetition pattern expired after one day) and H3376 (21 days stale, NextRunTime
# empty). A refresh job cannot report that it stopped running; only a job that MEASURES the index
# can. The first line keeps the indexes current, the second alarms when they are not, and the third
# asserts that every active registered tool still has a body file -- the defect that took the whole
# search surface down at the cutover (599 of 607 tools had no implementation).
# Source of truth: harness-config/scripts/find-anything/ and harness-config/scripts/guards/
8,23,38,53 * * * * /usr/local/bin/cron-wrap.sh fa-index-refresh $(enc "$REFRESH_CMD")
22 * * * * /usr/local/bin/cron-wrap.sh fa-index-freshness $(enc "$FRESH_CMD")
47 * * * * /usr/local/bin/cron-wrap.sh tool-body-guard $(enc "$GUARD_CMD")
EOF
