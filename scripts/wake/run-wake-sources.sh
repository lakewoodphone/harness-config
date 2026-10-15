#!/bin/bash
# Run every flag source once. Quiet sources say nothing; a source that finds
# something files a flag (or is deduped if the same subject is already open).
#
# Deliberately NOT `set -e`: one broken source must not stop the others, and a
# source that cannot read its signal exits non-zero with the reason on stderr -
# which lands in the log rather than being swallowed.
LOG=/root/.sms-inbox/sources.log
cd /root/bin/sources || exit 1
STAMP=$(date -Is)
# ledger-keepalive runs AFTER project-keepalive on purpose (2026-09-28): it files from the WORK
# LEDGER, which is where work actually lives, and uses the same subject shape so the store
# dedupes the two against each other. project-keepalive reads a per-project JSON blob and goes
# quiet when a shift forgets to rewrite it; this one cannot, because the ledger is the store the
# shift writes to.
#
# checkout-health runs BEFORE project-keepalive on purpose: the store releases
# same-priority rows in id order (wake.py _candidates), so a checkout that cannot
# accept a commit is repaired before the session that needs to commit is woken.
# It reads the same projects.json, does one bounded `git fetch` per project, and
# files at most one row per project per UTC day.
# cfo-backfill is fed by cfo-scoreboard.py: one row per UTC day while the accounting
# backlog is unfinished, or when the last shift retired nothing (a silent stall).
# roadmap-supply runs FIRST (added 2026-10-07, ledger item 501): it turns a project's own
# unchecked roadmap boxes into ledger items, which is what makes ledger-keepalive able to
# file a shift at all. Without it the two keepalives could only disagree about a project
# that already had work.
# EVERY PROJECT THAT HAS A MAPPING, not one hardcoded name (fixed 2026-10-13).
# Measured 2026-10-13: this block named `--project kosher-ai-filter` literally, and
# roadmap-supply.py REQUIRES --project (main() errors without it), so that ONE project was the
# only roadmap ever converted into ledger work by a scheduler. lpt-website's mapping file
# existed and was READY - `roadmap-supply.py --project lpt-website --dry-run` reported
# stale_mapping_rows=0, mapped=6, new=4 - and no scheduled run ever reached it, so the project
# the owner asked to be worked on daily had no automated work supply at all: it ran on four
# manually-filed items and would go quiet the moment they closed. Meanwhile the one project
# that WAS wired, kosher-ai-filter, failed every run because its repo path does not exist on
# this box (27 FAILED lines on 2026-10-13, latest 14:07Z). The glob is the fix: a newly
# authored roadmap-<project>.json is picked up with no second edit here, so a project can no
# longer be scheduled, woken and starved because one line named its neighbour.
for RSMAP in "$HOME/bin/sources"/roadmap-*.json; do
  [ -e "$RSMAP" ] || continue
  RSPROJ=$(basename "$RSMAP"); RSPROJ=${RSPROJ#roadmap-}; RSPROJ=${RSPROJ%.json}
  out=$(timeout 180 /usr/bin/python3 "$HOME/bin/sources/roadmap-supply.py" --project "$RSPROJ" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$STAMP  roadmap-supply  FAILED rc=$rc [$RSPROJ]: $(echo "$out" | head -2 | tr '\n' ' ')" >> "$LOG"
  elif [ "$out" != "quiet" ]; then
    echo "$STAMP  roadmap-supply  [$RSPROJ] $(echo "$out" | head -1)" >> "$LOG"
  fi
done
# THE LOOP'S OWN WATCHDOG (added 2026-10-07, ledger item 501). Everything above judges the
# world; this one judges the build loop. Measured shape of the failure it exists for: on
# 2026-10-03 and 2026-10-04 the kosher-filter loop released ZERO shifts and produced ZERO
# attempts while every component reported health, and nobody noticed for two days. 'STALL' on
# stdout is the signal; the exit code is what the branch tests, and stdout is redirected to
# /dev/null so a quiet pass cannot be mistaken for a filing.
# THE CONTINUATION QUEUE'S DAILY REVIEW (added 2026-10-07, the owner's rule: a session either ends
# with nothing outstanding or leaves a flag the company picks up). exit 1 means something has been
# pending past the window - it is written to the log with the item and its next action, so the
# nightly pass cannot pass by being silent.
cont_out=$(timeout 120 /usr/bin/python3 "$HOME/bin/continuation.py" review --stale-hours 24 2>&1)
cont_rc=$?
if [ $cont_rc -eq 1 ]; then
  echo "$STAMP  continuation-overdue  $(echo "$cont_out" | tail -3 | tr '\n' ' ')" >> "$LOG"
elif [ $cont_rc -ne 0 ]; then
  echo "$STAMP  continuation-review  UNUSABLE rc=$cont_rc: $(echo "$cont_out" | head -2 | tr '\n' ' ')" >> "$LOG"
fi
stall_out=$(timeout 120 /usr/bin/python3 "$HOME/bin/kaf-loop-status.py" --check --stale-hours 6 2>&1)
stall_rc=$?
if [ $stall_rc -eq 1 ]; then
  echo "$STAMP  loop-stall  $stall_out" >> "$LOG"
elif [ $stall_rc -ne 0 ]; then
  echo "$STAMP  loop-stall  UNUSABLE rc=$stall_rc: $(echo "$stall_out" | head -2 | tr '\n' ' ')" >> "$LOG"
fi
# PLAID FRESHNESS (added 2026-10-08, ledger item 231 / journal pain P2926 part 1).
# The nightly money pull failed 6 of 8 nights and nothing alerted; the guard that
# judges ~/.plaid-sync-status.json existed but was invoked by nothing, so a dead
# pull stayed silent. This source turns its verdict into a flag. It is quiet while
# the pull is fresh (measured FRESH, age 8.2h, ok=true on 2026-10-08).
# HOURS DRIFT (added 2026-10-09). `hours-drift-check.py` is a read-only checker that exits 3
# (CONDITION, not fault) when a surface publishing the shop's walk-in hours disagrees, so
# cron-failures deliberately files nothing for a streak of it. This source carries the condition
# instead -- without it the drift would be silent, which is exactly what happened: ten
# consecutive runs found the same Google Maps drift and the finding lived only in a file nobody
# read. It is quiet while the verdict is fresh and ok.
for s in txt-lost-webhook txt-stranded-inbound decision-queue-stale \
         decision-answer-unconsumed comms-freshness \
         cfo-backfill dormant-handoff checkout-health project-keepalive ledger-keepalive wake-tuner \
         cron-targets cron-failures owner-question-audit disk-space db-integrity pain-checks drift-check sms-app-gap plaid-freshness hours-drift; do
  out=$(timeout 90 /usr/bin/python3 "$s.py" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$STAMP  $s  FAILED rc=$rc: $(echo "$out" | head -2 | tr '\n' ' ')" >> "$LOG"
  elif [ "$out" != "quiet" ]; then
    echo "$STAMP  $s  $out" >> "$LOG"
  fi
done
# Liveness for the sources too: the digest reads the dispatcher's heartbeat, and
# a sources run that silently stops is the same class of failure.
# A project with no ledger item AND no real repo is a deadlock: a shift claims nothing, gets
# `nothing-todo`, and stops - so the discovery that would break the deadlock never happens.
# This files the discovery item for those projects so the shift has something to claim.
# Idempotent: it only files when the project has NO items at all. Measured 2026-09-28:
# personality-system, rental-system and chumash were all in that state.
# CHECKOUT-HEALTH SELFTEST (item 129). The loop above runs checkout-health.py as a
# source and never passes --selftest, so nothing executed the lock-detector
# assertions item 74 added: the linked-worktree coverage item 34 introduced could
# be deleted in a refactor and no run would notice. Execute it here on every
# sources pass and log a DISTINCT line, pass or fail, so a regression is visible
# in this log instead of only to a human who thinks to run the test by hand.
selftest_out=$(timeout 120 /usr/bin/python3 /root/bin/sources/checkout-health.py --selftest 2>&1)
selftest_rc=$?
if [ "$selftest_rc" -ne 0 ]; then
  echo "$STAMP  checkout-health-selftest  FAILED rc=$selftest_rc: $(printf '%s' "$selftest_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  echo "$STAMP  checkout-health-selftest  OK rc=0: $(printf '%s' "$selftest_out" | tail -1 | tr '\n' ' ')" >>"$LOG"
fi
timeout 120 /usr/bin/python3 /root/bin/seed-discovery-items.py --apply >>"$LOG" 2>&1 || true
# THE LEDGER REAPS ITS OWN LEASES. The wake store does this inside the dispatcher; the ledger is
# a separate store with its own lease, and NOTHING was reaping it (measured 2026-09-28). A session
# that dies mid-shift would otherwise leave its item `running` for ever - neither done nor
# available - which is silent work loss with no symptom except a backlog that stops moving.
# Idempotent and cheap: it only touches leases that have already expired.
timeout 60 /usr/bin/python3 /root/bin/work.py reap >>"$LOG" 2>&1 || true

# WEEKLY-EVOLUTION (added 2026-10-13; docs/self-evolution/README.md). Files the weekly
# "how did we wildly evolve this week" audit as work, deduped by subject
# self-audit:<ISO-year>-W<ISO-week> so a second attempt in the same week is a `deduped`,
# never a second session. It has its OWN block rather than a place in the 90-second loop
# above, because the measurement runs git log over the repo plus several live queries and
# 90 s would kill it -- and the kill would be a quiet rc=124 in a log nobody reads, i.e. the
# audit would never happen and nothing would say so.
we_out=$(timeout 300 /usr/bin/python3 /root/bin/sources/weekly-evolution.py 2>&1)
we_rc=$?
if [ "$we_rc" -ne 0 ]; then
  echo "$STAMP  weekly-evolution  FAILED rc=$we_rc: $(printf '%s' "$we_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
elif [ "$we_out" != "quiet" ]; then
  echo "$STAMP  weekly-evolution  $we_out" >>"$LOG"
fi

date -Is > /root/.sms-inbox/sources-heartbeat
exit 0
