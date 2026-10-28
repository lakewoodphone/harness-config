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
  # STDOUT AND STDERR ARE CAPTURED SEPARATELY, AND THAT IS THE FIX (ledger item 392,
  # 2026-10-18). MEASURED: with `2>&1` in a command substitution, Python's stderr is
  # unbuffered while its stdout is block-buffered when piped, so the FIRST captured line
  # is a stderr note, not the stdout summary. roadmap-supply prints the summary
  # ("roadmap-supply: docs=... unchecked_boxes=...") to stdout and every per-box note
  # ("NOT-MAPPED ...", "STALE-MAPPING ...") to stderr. On a run with any unmapped box the
  # log therefore showed only "  NOT-MAPPED ..." and never the summary -- so a bridge that
  # was dead or reading a stale tree still looked like a routine NOT-MAPPED line. Capturing
  # stderr to its own file keeps the summary in $out and still lets the FAILED branch quote
  # the actual reason. Reproduced before the change: merged head -1 == "  NOT-MAPPED ...";
  # separated stdout head -1 == "roadmap-supply: docs=git unchecked_boxes=40".
  RSMAP_ERR=$(mktemp "${TMPDIR:-/tmp}/roadmap-supply.XXXXXX")
  out=$(timeout 180 /usr/bin/python3 "$HOME/bin/sources/roadmap-supply.py" --project "$RSPROJ" 2>"$RSMAP_ERR")
  rc=$?
  err=$(cat "$RSMAP_ERR" 2>/dev/null)
  rm -f "$RSMAP_ERR"
  if [ $rc -ne 0 ]; then
    echo "$STAMP  roadmap-supply  FAILED rc=$rc [$RSPROJ]: $(printf '%s\n%s\n' "$err" "$out" | grep -v '^$' | head -2 | tr '\n' ' ')" >> "$LOG"
  elif [ "$out" != "quiet" ]; then
    echo "$STAMP  roadmap-supply  [$RSPROJ] $(printf '%s\n' "$out" | head -1)" >> "$LOG"
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
         session-sweep owner-text-scorecard; do
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

# LPT PROMOTION READINESS, ON A SCHEDULE (added 2026-10-28). The owner's answer to row 1107 was
# "that is totally your domain", so promoting test to production is the loop's own job - but nothing ran
# lpt-promote.py, so the moment the gates opened would have been noticed by nobody. This block runs it in
# CHECK mode: it prints the four gates and their measurements every tick and changes NOTHING. The first
# real promotion is watched once by hand; flipping this to `--yes` afterwards is a one-word change, and
# the tool itself still refuses on a red/BLOCKED/pending head, a deploy that does not match, a run in
# flight, or nothing to promote.
promo_out=$(timeout 300 /usr/bin/python3 /root/bin/lpt-promote.py --yes 2>&1)
promo_rc=$?
promo_line=$(printf '%s' "$promo_out" | grep -E "VERDICT|test head is GREEN" | tr '\n' ' ' | cut -c1-230)
if [ "$promo_rc" -ne 0 ]; then
  echo "$STAMP  lpt-promote  NOT READY: $promo_line" >>"$LOG"
else
  echo "$STAMP  lpt-promote  READY: $promo_line" >>"$LOG"
fi

# LPT BILLING WATCH - a bill is not a code failure (added 2026-10-28).
# GitHub refuses hosted jobs with "The job was not started because recent account payments have
# failed or your spending limit needs to be increased" and reports it as a CHECK FAILURE, so the
# website head goes red for a reason no repository change can fix. It has now happened three times
# (owner rows 940 on 10-21, 1028 on 10-25, 1108 on 10-28) and every time a human noticed.
# lpt-billing-watch.py reads lpt-ci-status.py, and files exactly ONE deduped owner row when it sees
# state=BILLING. It never raises a wake flag: a session cannot pay a bill, and a flag would spend
# money to say so. It prints one line every run either way, so sources.log carries the state.
bill_out=$(timeout 300 /usr/bin/python3 /root/bin/lpt-billing-watch.py 2>&1)
bill_rc=$?
if [ "$bill_rc" -ne 0 ]; then
  echo "$STAMP  lpt-billing-watch  FAILED rc=$bill_rc: $(printf '%s' "$bill_out" | tail -1 | cut -c1-200)" >>"$LOG"
else
  echo "$STAMP  lpt-billing-watch  $(printf '%s' "$bill_out" | tail -1 | cut -c1-220)" >>"$LOG"
fi

# LPT WEBSITE LANDING - the link that lands a green branch instead of filing a note about it
# (added 2026-10-27). MEASURED that evening: lpt-reconcile reported FOURTEEN ledger items `done`
# whose work sits on an unmerged branch, PR #690 was GREEN and unmerged for 21 hours, and nothing
# in cron merges pull requests - work-integrator files an item for the branch and stops there, and
# a shift ends at "branch pushed, awaits integrator merge". So the loop built and never shipped.
# lpt-land.py takes ONE action per tick: it opens a PR for the oldest unlanded branch, or merges
# the oldest such PR once the repository itself says its required checks are green. It refuses to
# act while the test head is red (every new PR would be red on arrival), it can only name `test`
# as a base - production promotion stays the owner's - and it never merges without green checks.
land_out=$(timeout 900 /usr/bin/python3 /root/bin/lpt-land.py 2>&1)
land_rc=$?
if [ "$land_rc" -ne 0 ]; then
  echo "$STAMP  lpt-land  FAILED rc=$land_rc: $(printf '%s' "$land_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  echo "$STAMP  lpt-land  $(printf '%s' "$land_out" | tail -1 | cut -c1-220)" >>"$LOG"
fi

# PROGRESS DEADMAN — the one thing nothing watched (added 2026-10-18 after a 32-hour hole).
# Measured from wake-dispatch.log: 13th 144 ok, 14th 146, 15th 139, 16th 139, **17th ZERO lines**,
# 18th 124. The office desktop every release is dispatched to (`DESKTOP=${WAKE_DESKTOP:-zabz-tech-ts}`,
# one host, no fallback) was asleep; for most of the hole the dispatcher was being refused rc=1 on the
# SSH hop and on the 17th it wrote nothing at all. authority-deadman only proves the AUTHORITY is up
# (it was), wake-tuner emits one cost digest a day, and wake-lock-watch watches the SQLite lock, which
# was never held — so a production stop was recorded only as 133 rc=1 rows in a log nobody reads.
# This source answers the question the owner actually asked ("is it building daily?") on a clock, and
# it separates three states that must never be one: healthy / stalled / all-releases-failing, plus a
# REFUSAL (exit 4) when the log is missing or holds no parsable release, which is NOT "quiet".
prog_out=$(timeout 120 /usr/bin/python3 /root/bin/sources/wake-progress.py 2>&1)
prog_rc=$?
if [ "$prog_rc" -ne 0 ]; then
  echo "$STAMP  wake-progress  FAILED rc=$prog_rc: $(printf '%s' "$prog_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
elif [ "$prog_out" != "quiet" ]; then
  echo "$STAMP  wake-progress  $prog_out" >>"$LOG"
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
# THE TRANSITION THAT WAS BUILT AND NEVER SCHEDULED (added 2026-10-21). `work.py due --reopen` is
# the only thing in this tool that moves a DATE-GATED block back to todo, and it was written today
# with nothing calling it - so items past their own revisit time could not move out of `blocked` at
# all. It is deliberately narrow and refuses any block naming a person, a vendor, a customer or
# hardware; the residue is what `ledger-blockers.py` below spends one shift a day on. The read-only
# form this replaces printed the same 8 items 179 times without changing one of them.
due_out=$(cd /root && timeout 120 /usr/bin/python3 /home/zabz/bin/work.py due --reopen 2>&1)
reopen_line=$(printf '%s\n' "$due_out" | grep -E '^reopened: ' | head -1)
case "$reopen_line" in
  "reopened: none"*|"") : ;;                          # quiet is the expected shape
  *) echo "$STAMP  ledger-reopen  $reopen_line" >>"$LOG" ;;
esac
due_n=$(printf '%s\n' "$due_out" | grep -cE "^[0-9]+[[:space:]]")
if [ "$due_n" -gt 0 ]; then
  echo "$STAMP  ledger-due  $due_n item(s) past their revisit time: $(printf '%s\n' "$due_out" | grep -E "^[0-9]+[[:space:]]" | head -2 | cut -c1-80 | tr '\n' '|')" >>"$LOG"
fi

# THE RESIDUE BECOMES WORK (added 2026-10-21). Everything above this line REPORTS. The 8 due items
# and the 22 blocked items citing an already-resolved owner row were findings with no consumer:
# `work.py due` had printed them 179 times and `lint-refs` reported STALE=22 every 30 minutes while
# nothing in the loop could act on either. This source files ONE flag a day (subject carries the
# UTC date, so one a day at most) whose prompt makes a shift re-measure each blocker and forbids
# re-dating an item with the sentence it already had. See sources/ledger-blockers.py for why an
# automatic release is wrong here - item 292's resolved row said "I walk them, not you".
lb_out=$(timeout 120 /usr/bin/python3 /root/bin/sources/ledger-blockers.py 2>&1)
lb_rc=$?
if [ "$lb_rc" -ne 0 ]; then
  echo "$STAMP  ledger-blockers  FAILED rc=$lb_rc: $(printf '%s' "$lb_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  echo "$STAMP  ledger-blockers  $(printf '%s' "$lb_out" | tail -1 | cut -c1-220)" >>"$LOG"
fi

# THE MACHINE-CHECKABLE BLOCKERS (added 2026-10-21). `work.py resweep` re-tests the blockers a
# program can settle - CI billing, a merged PR, a deploy, a service state - and releases the ones
# that have cleared. It existed for a day with nothing calling it. Measured on its first dry run:
# 85 blocked items, 3 machine-testable, 81 "no machine-checkable condition", which it says out loud
# rather than reporting quiet. ledger-blockers.py above covers the 81.
rs_out=$(cd /root && timeout 300 /usr/bin/python3 /home/zabz/bin/work.py resweep 2>&1)
echo "$STAMP  ledger-resweep  $(printf '%s' "$rs_out" | grep -E '^resweep: ' | tail -1 | cut -c1-200)" >>"$LOG"

# THE DESKTOP WAS ACCUMULATING TWO FILES PER RELEASE, FOR EVER (added 2026-10-21). Measured
# 4,944 files / 237.5 MB under C:\Users\ezabz\bin, ~300 new a day, and the dispatcher's own log
# line says they "need no cleanup". wake-staging-prune.sh keeps 30 days and runs at most once a
# week, so 335 ticks in 336 cost a stat and no ssh. It prints what the hop said, deleted or not.
pr_out=$(timeout 120 bash /root/bin/wake-staging-prune.sh 2>&1)
[ -n "$pr_out" ] && echo "$STAMP  $(printf '%s' "$pr_out" | tr '\n' ' ' | cut -c1-300)" >>"$LOG"

# NO PR LIVES PAST A DAY WITHOUT A DECISION (added 2026-10-21). Measured that evening: eleven PRs open
# into `test`, four of them green and unmerged (oldest 12 days), five with red required checks and one
# 16 days old with no CI at all - while `lpt-branch-drift.timer` watched only test->main drift and
# nothing measured the open-PR queue. Roadmap RULE 1: a branch that is not merged is work that did not
# happen. Files one flag a day while any PR older than 24 h exists; the shift merges, fixes or closes
# each one with its evidence.
pra_out=$(timeout 180 /usr/bin/python3 /root/bin/sources/lpt-pr-age.py 2>&1)
pra_rc=$?
if [ "$pra_rc" -ne 0 ]; then
  echo "$STAMP  lpt-pr-age  FAILED rc=$pra_rc: $(printf '%s' "$pra_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  echo "$STAMP  lpt-pr-age  $(printf '%s' "$pra_out" | tail -1 | cut -c1-220)" >>"$LOG"
fi

# THE OWNER DECISION QUEUE IS ASSESSED ON A CLOCK (added 2026-10-21). Measured that day:
# `owner_decision_queue` held 111 pending rows with the oldest 34 days old, and nothing
# anywhere looked at it -- `decision-triage.py` existed as a tool but ran only when a session
# remembered to run it. This line makes the queue's state a TREND (queue-history.jsonl)
# instead of something a person has to go and discover, and it files at most one flag a day
# when the queue is genuinely stuck (see decision-queue-health.py for why an absent approval
# is not a fault).
# WRITE THE TRIAGE VERDICT BACK, SO THE QUEUE STAYS THE LIST IT CLAIMS TO BE (added 2026-10-21).
# Measured: 33 rounds of classification left 62 "pending" rows when 20 were decisions -- echoes,
# digests, passive notes and duplicates all still counted as things waiting on him. owner-queue.py
# reads the DATABASE, so every one of those verdicts was invisible to the list he actually opens.
# This writes them (ECHO/INFORM/SYSTEM/DUPLICATE/NOISE/STALE) and leaves SEND_NOW, CONTROL,
# ENGINEERING and JUDGE_GAP alone.
at_out=$(timeout 600 /usr/bin/python3 /root/bin/decision-apply-triage.py --apply 2>&1)
echo "$STAMP  apply-triage  $(printf '%s' "$at_out" | tail -2 | tr '\n' ' ' | cut -c1-200)" >>"$LOG"

# A ROW THE SYSTEM SAID IT WOULD HANDLE MUST BECOME LEDGER WORK (added 2026-10-21). The triage
# classifies passive asks ("want me to note the device details?") as SYSTEM so they stop spending
# the owner's attention -- but with no consumer, SYSTEM would be a hidden question rather than a
# handled one, which is worse than asking. This files one item per SYSTEM row; a shift does it.
sw_out=$(timeout 300 /usr/bin/python3 /root/bin/decision-system-work.py --apply 2>&1)
echo "$STAMP  system-work  $(printf '%s' "$sw_out" | tail -1 | cut -c1-200)" >>"$LOG"

# REPORT FINISHED ANSWERS BACK ON THE SAME THREAD (added 2026-10-21). His instruction to #877
# ("make sure all the information is fully documented and ready for me to file") became ledger
# item 941 and a cfo shift closed it in 33 minutes -- and nothing told him. The channel asked,
# he answered, the work finished, and the last mile was silence. This files ONE question per
# completed answer, naming where the deliverable is, so the work does not end in the dark.
rr_out=$(timeout 120 /usr/bin/python3 /root/bin/decision-result-report.py --apply 2>&1)
echo "$STAMP  answer-result  $(printf '%s' "$rr_out" | tail -2 | tr '\n' ' ' | cut -c1-200)" >>"$LOG"

# ACT ON HIS ANSWER ABOUT THE CHANNEL (added 2026-10-21). The one approval that gates all
# delivery was living only in a chat window, which assumes he is reading it at the moment it
# is written -- and chat is not a durable surface, which is the whole reason this queue exists.
# The approval is now a row in owner_decision_queue and this turns his answer, in the queue or
# by text, into the sentinel. It logs EVERY run, including "still waiting", because a gate
# that is silent is indistinguishable from a gate that is broken.
ap_out=$(timeout 60 /usr/bin/python3 /root/bin/decision-approval-watch.py 2>&1)
echo "$STAMP  channel-approval  $(printf '%s' "$ap_out" | tr '\n' ' ' | cut -c1-200)" >>"$LOG"

# CLOSE THE LEARNING LOOP (added 2026-10-21). The queue could record what it SENT and
# nothing captured what he SAID, so `owner_queue_feedback` learned only from closes a human
# happened to perform -- 802 rows, none of them from a texted decision. This pairs each
# delivered question with the inbound reply that answered it (one question open at a time is
# the attribution key, and it is HIS rule), writes the answer onto the row, then lets
# owner-queue.py copy that close into the learning profile. Neither step sends anything.
a_out=$(timeout 120 /usr/bin/python3 /root/bin/decision-answer-capture.py --apply 2>&1)
a_rc=$?
if [ "$a_rc" -ne 0 ]; then
  echo "$STAMP  answer-capture  FAILED rc=$a_rc: $(printf '%s' "$a_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  # ALWAYS LOG, even at zero. A source that writes a line only when it did something is
  # indistinguishable from a source that stopped running -- the failure this whole file
  # keeps rediscovering. "delivered=0 answered=0" is a measurement; silence is not.
  echo "$STAMP  answer-capture  $(printf '%s' "$a_out" | tr '\n' ' ' | cut -c1-220)" >>"$LOG"
  if printf '%s' "$a_out" | grep -q "recorded [1-9]"; then
    l_out=$(cd /root && timeout 120 /usr/bin/python3 /home/zabz/bin/owner-queue.py learning --backfill 2>&1)
    echo "$STAMP  queue-learning   $(printf '%s' "$l_out" | head -2 | tr '\n' ' ')" >>"$LOG"
  fi
fi

q_out=$(timeout 120 /usr/bin/python3 /root/bin/decision-queue-health.py 2>&1)
q_rc=$?
if [ "$q_rc" -ne 0 ]; then
  echo "$STAMP  decision-queue  FAILED rc=$q_rc: $(printf '%s' "$q_out" | tail -2 | tr '\n' ' ')" >>"$LOG"
else
  echo "$STAMP  decision-queue  $q_out" >>"$LOG"
fi

date -Is > /root/.sms-inbox/sources-heartbeat
exit 0
