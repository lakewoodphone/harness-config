#!/bin/bash
# Run every flag source once. Quiet sources say nothing; a source that finds
# something files a flag (or is deduped if the same subject is already open).
#
# Deliberately NOT `set -e`: one broken source must not stop the others, and a
# source that cannot read its signal exits non-zero with the reason on stderr -
# which lands in the log rather than being swallowed.
LOG=/home/zabz/.sms-inbox/sources.log
cd /home/zabz/bin/sources || exit 1
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
for s in txt-lost-webhook txt-stranded-inbound decision-queue-stale \
         decision-answer-unconsumed comms-freshness \
         dormant-handoff checkout-health project-keepalive ledger-keepalive wake-tuner; do
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
timeout 120 /usr/bin/python3 /home/zabz/bin/seed-discovery-items.py --apply >>"$LOG" 2>&1 || true
date -Is > /home/zabz/.sms-inbox/sources-heartbeat
exit 0
