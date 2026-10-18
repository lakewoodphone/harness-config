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

# PIN THE PROJECT-STATE DIRECTORY, BECAUSE IT HAD SPLIT IN TWO. MEASURED 2026-10-16.
# Every project-state path is written in one of TWO ways, and under cron they disagree:
#   * projects.json `state_file` hardcodes   /home/zabz/.wake-projects/<id>.json
#   * shift-packet.py (and project-keepalive.py:571, which invokes it) build
#     `Path.home() / ".wake-projects"`, and cron runs these as root with HOME=/root,
#     so the packet is built from /root/.wake-projects/<id>.json instead.
# The result, measured file by file: /home/zabz/.wake-projects holds 11 live project
# files; /root/.wake-projects holds only cfo.json and housekeeping.json, and BOTH have
# diverged. housekeeping is the worst case and the two are not merely out of date - they
# are SCHEMA-INCOMPATIBLE, written by two different producers:
#   /home/zabz/.../housekeeping.json  8429 B, `work_remaining` is a BOOLEAN true, plus
#                                      a `remaining` list - the shape work_remaining()
#                                      in project-keepalive.py requires;
#   /root/.../housekeeping.json      22780 B, `work_remaining` is a STRING, plus
#                                      `updated_by` / `facts` / `finding_*` keys and no
#                                      `remaining` at all - a different document.
# So a handoff written to /root/.wake-projects is a handoff NOTHING in the wake loop reads,
# and a reader that lands there instead gets Unreadable rather than an answer.
# WAKE_STATE_DIR is the override shift-packet.py already documents; pinning it here makes
# every HOME-relative reader in this cron loop resolve to the directory the registry names,
# so a newly written state file cannot fork again. It does not migrate the two files that
# have already diverged - that needs their two producers reconciled, and they are left
# exactly where they are until then.
export WAKE_STATE_DIR=/home/zabz/.wake-projects
# OWNER-ESCALATION CADENCE — 30 days was one shot and a month of silence.
# Both escalation sources ask for a 30-DAY cooldown by default (decision-queue-stale.py:174 sets
# 2592000; decision-answer-unconsumed.py:183 does the same) and both document it as deliberate:
# "combined with a 30-day cooldown, the worst case for a row is one release a month". Measured
# 2026-10-18, that is what it actually produced, and it is the wrong shape for this owner:
#   wake #44 odq-stale:78          filed 2026-09-28, not_before 2026-10-28, attempts 1, never released
#   wake #7  odq-answer-open:61    filed 2026-09-28, not_before 2026-10-28, attempts 1, never released
# The underlying owner rows were 31 days old. So an escalation that had ONE attempt, lost it, and
# then waited a month was indistinguishable from no escalation at all — and "things that are not
# finished come back to me" is the owner's stated requirement. Seven days repeats the escalation
# while the condition is STILL TRUE; the generic dedupe, the per-subject cooldown and the
# per-source hourly cap all still bound the volume, and there are exactly three such rows today.
# Configuration, not code: both sources read these names.
export ODQ_STALE_COOLDOWN_SEC=604800
export ODQ_ANSWER_COOLDOWN_SEC=604800
# THE THIRD `Path.home()` VICTIM, FIXED AS CONFIGURATION RATHER THAN CODE (2026-10-18).
# `cron-targets.py:55` defaults the guard to `Path.home()/"bin"/"cron-target-guard.py"`, and cron runs
# these sources as root with HOME=/root — so it looked for /root/bin/cron-target-guard.py, which does
# not exist, and every tick logged `SIGNAL UNREADABLE -- the guard itself is missing`. The guard is
# real: /usr/local/bin/cron-target-guard.py, 27,212 B, and the crontab already calls it from there.
# Same defect as dormant-handoff's repo path and _flag.app_db's store — a file that exists, looked for
# under a home directory that cron does not have. The source already reads CRON_TARGET_GUARD, so this
# is one export and no code change.
export CRON_TARGET_GUARD=/usr/local/bin/cron-target-guard.py
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
# RETIRED 2026-10-18. kaf-loop-status.py has NEVER existed on this host: absent from
# /root/bin (where $HOME points under cron), /home/zabz/bin and /usr/local/bin, and the
# estate file search finds no match under any path. H3417 recorded it months ago. The
# sources log holds 245 UNUSABLE rc=2 lines for this source -- every run it has ever had.
# A source that always cries wolf trains everyone to ignore the log, which is precisely how
# cron-targets stayed broken for weeks while printing SIGNAL UNREADABLE every tick.
# The signal is not deleted: if the detector ever appears, this runs it. Otherwise the
# absence is announced ONCE and then stays silent.
STALL_DET="$HOME/bin/kaf-loop-status.py"
if [ -f "$STALL_DET" ]; then
  stall_out=$(timeout 120 /usr/bin/python3 "$STALL_DET" --check --stale-hours 6 2>&1)
  stall_rc=$?
  if [ $stall_rc -eq 1 ]; then
    echo "$STAMP  loop-stall  $stall_out" >> "$LOG"
  elif [ $stall_rc -ne 0 ]; then
    echo "$STAMP  loop-stall  UNUSABLE rc=$stall_rc: $(echo "$stall_out" | head -2 | tr '\n' ' ')" >> "$LOG"
  fi
elif [ ! -f "${STATE_DIR:-/root/.sms-inbox}/.loop-stall-retired" ]; then
  echo "$STAMP  loop-stall  RETIRED: no detector at $STALL_DET on this host (announced once; this source is silent until one exists)" >> "$LOG"
  : > "${STATE_DIR:-/root/.sms-inbox}/.loop-stall-retired"
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
# SESSION-SWEEP reads the day's FINISHED CHATS (added 2026-10-18 — the owner's own requirement:
# "go through that day's sessions and previous day sessions and find goals"). Measured that night:
# 239 sessions in 48 h and ZERO handoffs written, so nothing mapped a session to an obligation and
# a session ending on "I'll do X next" simply evaporated. It reads the archive already on this box
# (/root/authority.db, dsh_sessions + dsh_session_events via the (machine,session,seq) index),
# keeps only the assistant's `text` parts — never the reasoning — and files at most 3 wake rows a
# day. Measured cost of a full pass: 0.23 s wall, 47 MB RSS, so it belongs in this loop.
# DO NOT replace its query with a created_at range over dsh_session_events: that scan does not
# finish on this host (it ran >3 minutes and had to be killed) because the column is unindexed.
for s in txt-lost-webhook txt-stranded-inbound decision-queue-stale \
         decision-answer-unconsumed comms-freshness \
         cfo-backfill dormant-handoff checkout-health project-keepalive ledger-keepalive wake-tuner \
         cron-targets cron-failures owner-question-audit disk-space memory-pressure db-integrity pain-checks drift-check sms-app-gap plaid-freshness hours-drift finance-reconciliation \
         session-sweep; do
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

# INTEGRATION DISCOVERY — the half of the loop that was never scheduled (added 2026-10-18).
# `work-integrator.py` turns "a shift pushed a branch" into a ledger item. It has existed since
# 2026-09-28 and NOTHING REFERENCED IT: `crontab -l | grep -c integrator` = 0 and
# `grep -c integrator run-wake-sources.sh` = 0. So unmerged branches were discovered only when a
# human happened to run it, and the last 7 days hold 304 settled attempts whose `left_over` names a
# merge or a branch. That is the failure this loop exists to prevent, one level up: a fleet that
# builds and never integrates produces branches, not progress. (Measured separately: all three
# currently-blocked integration items are blocked on a RESTART or a maintenance window, not on the
# merge rule — so they are waiting on the same owner decision as the restart class, not on this job.)
# It never edits a repo, never merges and never pushes — it only makes the debt VISIBLE, its merge
# no-op test stops an already-landed branch being re-filed, and `work.py add` dedupes by title.
# Its own block, not the 90 s loop: it does one bounded `git fetch` (and a merge-tree per candidate)
# per project, and a slow remote killed at 90 s would look exactly like a quiet source.
int_out=$(timeout 300 /usr/bin/python3 /root/bin/work-integrator.py 2>&1)
int_rc=$?
if [ "$int_rc" -ne 0 ]; then
  echo "$STAMP  work-integrator  FAILED rc=$int_rc: $(printf '%s' "$int_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
elif [ "$int_out" != "quiet" ]; then
  echo "$STAMP  work-integrator  $(printf '%s' "$int_out" | grep -Ei 'filed' | tail -1)" >>"$LOG"
fi

# STALE-REFERENCE AND REVISIT REPORTING (added 2026-10-18) — two verbs that existed and were never
# run on a clock. Measured the day this was written: `work.py lint-refs` reports 5 STALE + 3 ORPHAN
# and `work.py due` reports 2 items past their revisit time, and NOTHING scheduled either. So a
# blocked item could cite an owner row that was resolved weeks ago, for ever — `work.py` only ran
# that scan on the claim-next `nothing-todo` branch, which never fires while 112 todo items exist.
# DELIBERATELY A REPORT AND NOT A RELEASE, measured 2026-10-18: item 292 cites RESOLVED row 295 and
# that row's resolution reads "I walk them, not you". An automatic "release when the cited row is
# resolved" rule would have handed a shift work the owner had claimed for himself and reported it as
# progress. The finding is logged; a SHIFT reads the text and decides.
lint_out=$(cd /root && timeout 120 /usr/bin/python3 /home/zabz/bin/work.py lint-refs 2>&1)
lint_stale=$(printf '%s\n' "$lint_out" | grep -c "^STALE")
lint_orphan=$(printf '%s\n' "$lint_out" | grep -c "^ORPHAN")
if [ "$lint_stale" -gt 0 ] || [ "$lint_orphan" -gt 0 ]; then
  # ORPHAN LINES ARE COUNTED, NOT QUOTED. Measured 2026-10-18: `work.py lint-refs` offers a
  # copy-pasteable `link it: work.py owner-row <id> --owner-row <n>` for every orphan, and three of
  # eight named owner-queue #2026 — a YEAR scraped out of prose — while the queue holds ~549 rows
  # (`select count(*) where id=2026` -> 0). Quoting those lines into this log hands a shift a wrong
  # command that looks authoritative. STALE lines are quoted (their ids were resolved against the
  # real queue); ORPHAN lines are summarised to a count until work.py can validate the id itself.
  echo "$STAMP  ledger-refs  STALE=$lint_stale ORPHAN=$lint_orphan: $(printf '%s\n' "$lint_out" | grep -E '^STALE' | head -2 | tr '\n' '|')" >>"$LOG"
fi
due_out=$(cd /root && timeout 120 /usr/bin/python3 /home/zabz/bin/work.py due 2>&1)
due_n=$(printf '%s\n' "$due_out" | grep -cE "^[0-9]+[[:space:]]")
if [ "$due_n" -gt 0 ]; then
  echo "$STAMP  ledger-due  $due_n item(s) past their revisit time: $(printf '%s\n' "$due_out" | grep -E "^[0-9]+[[:space:]]" | head -2 | cut -c1-80 | tr '\n' '|')" >>"$LOG"
fi

date -Is > /root/.sms-inbox/sources-heartbeat
exit 0
