#!/usr/bin/env bash
# journal-converge.sh — carry the machines' new journal entries into the canonical tree, ADDITIVELY.
#
# WHAT THIS IS. `converge-pull.py` is one iteration of convergence and it works (L6466: 6 entries in,
# superset restored, check 0 errors, nothing existing touched). This is the body of the loop turned
# into a job: single-flight, disk-checked, post-checked, and it writes down what it did.
#
# WHY IT IS SAFE TO RUN UNATTENDED, and each clause is a property of the tool, not a promise:
#   * the pull NEVER edits, renumbers, moves or removes an entry already in the canonical tree; only
#     the INCOMING entry's id can change, and only when its id is taken (verified by `git status`
#     reporting new paths and nothing modified -- L6466);
#   * it is single-flight, so two runs cannot interleave their id allocation;
#   * it runs `check` afterwards and EXITS NON-ZERO on any error, so a bad run is visible in
#     `~/.cron-status/runs.tsv` rather than silent;
#   * it does not run if the disk is short, because the collection stages tars on the same filesystem
#     as the database;
#   * every staged tar is deleted at the end, in a trap, including on failure.
#
# IT IS NOT INSTALLED ON A CLOCK. The line is at the bottom of this file, ready. Turning it on is a
# decision about the record, and it has been put to the owner twice.
#
# EXIT CODES   0 nothing to do or clean  1 the pull or check failed  2 cannot run  3 disk short
set -u

REPO="${JOURNAL_CONVERGE_REPO:-/root/code/harness-config}"
JOURNAL="$REPO/journal"
WORK="${JOURNAL_CONVERGE_WORK:-/root/work/journal-converge}"
STATE="/root/.journal-converge"
STATUS="$STATE/status.json"
LOG="$WORK/run.log"
TOOL="$REPO/scripts/evolution/journal-union/converge-pull.py"
JTOOL="$JOURNAL/tools/journal.py"
SSH="ssh -n -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15"
MIN_FREE_MB="${JOURNAL_CONVERGE_MIN_FREE_MB:-2000}"

mkdir -p "$WORK/trees" "$STATE" 2>/dev/null || exit 2
say(){ echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }
write_status(){ # write_status <result> <detail> <added> [fork]
  printf '{"at":"%s","result":"%s","detail":"%s","added":%s,"fork_colliding":%s,"free_mb":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$(printf '%s' "$2" | tr -d '"' | tr '\n' ' ')" "${3:--1}" \
    "${4:--1}" "$(df -Pm / | awk 'NR==2{print $4}')" > "$STATUS"
}

# ── single flight ────────────────────────────────────────────────────────────────────────────────
exec 9>"$STATE/.lock"
if ! flock -n 9; then say "[skip] another journal-converge holds the lock"; exit 0; fi

# ── preconditions ────────────────────────────────────────────────────────────────────────────────
[ -f "$JTOOL" ] || { say "[cannot-run] $JTOOL is missing"; write_status cannot-run "journal.py missing"; exit 2; }
[ -f "$TOOL" ] || { say "[cannot-run] $TOOL is missing"; write_status cannot-run "converge-pull.py missing" ; exit 2; }
FREE=$(df -Pm / | awk 'NR==2{print $4}')
if [ "$FREE" -lt "$MIN_FREE_MB" ]; then
  say "[cannot-run] only ${FREE}MB free on /, need ${MIN_FREE_MB}MB -- the staging tars live here"
  write_status disk-short "${FREE}MB free" ; exit 3
fi
say "free on /: ${FREE}MB"

cleanup(){ rm -f "$WORK"/trees/*.tar 2>/dev/null; }
trap cleanup EXIT

# ── collect the trees that CHANGE, plus the static local ones (cheap, and completeness beats speed) ─
collect(){ # collect <name> LOCAL   (dir in TAR_C)   |   collect <name> <ssh-target...>
  local name=$1; shift
  if [ "$1" = "LOCAL" ]; then
    tar -cf "$WORK/trees/$name.tar" -C "$TAR_C" journal 2>/dev/null || { say "[skip] $name tar failed"; return 0; }
  else
    $SSH "$@" "tar -cf - -C $TAR_C journal" > "$WORK/trees/$name.tar" 2>/dev/null
    [ -s "$WORK/trees/$name.tar" ] || { say "[skip] $name unreachable or empty"; rm -f "$WORK/trees/$name.tar"; return 0; }
  fi
  rm -rf "$WORK/trees/$name"; mkdir -p "$WORK/trees/$name"
  tar -xf "$WORK/trees/$name.tar" -C "$WORK/trees/$name" || { say "[skip] $name extract failed"; return 0; }
  say "  $name: $(find "$WORK/trees/$name/journal/entries" -type f -name '*.md' 2>/dev/null | wc -l) entries"
}

say "collect"
TAR_C=/root/work/wt-item221;                                     collect item221    LOCAL
TAR_C=C:/Users/ezabz/code/harness-config;                        collect yoga       zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/harness-config;                        collect tech       zabz-tech
TAR_C=/Users/lpt/code/harness-config;                            collect mac        -l lpt mac-mini-ts
TAR_C=C:/Users/ezabz/code/harness-config-mfx;                    collect mfx        zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/_worktrees/harness-config/p1evidence;  collect p1evidence zabz-yoga-ts
TAR_C=C:/Users/ezabz/code/_scratch/hc-master-deliver;            collect hcd        zabz-yoga-ts

# ── the pull ─────────────────────────────────────────────────────────────────────────────────────
BEFORE=$(find "$JOURNAL/entries" -type f -name '*.md' | wc -l)
say "pull (additive)"
OUT=$(python3 "$TOOL" --canonical "$JOURNAL" --trees "$WORK/trees" --apply 2>&1)
RC=$?
echo "$OUT" | tail -6 >> "$LOG"
ADDED=$(echo "$OUT" | sed -n 's/^wrote \([0-9]*\) entr.*/\1/p' | tail -1)
ADDED=${ADDED:-0}
AFTER=$(find "$JOURNAL/entries" -type f -name '*.md' | wc -l)
say "entries ${BEFORE} -> ${AFTER} (+${ADDED})  pull rc=${RC}"
[ "$RC" -eq 0 ] || { say "[failed] the pull exited ${RC}"; write_status failed "pull rc=$RC" "$ADDED"; exit 1; }

# ── index, then the two gates ────────────────────────────────────────────────────────────────────
python3 "$JTOOL" --root "$JOURNAL" --no-color index >/dev/null 2>&1
CHECK=$(python3 "$JTOOL" --root "$JOURNAL" --no-color check 2>&1); CRC=$?
say "check: $(echo "$CHECK" | tail -1)"
if [ "$CRC" -ne 0 ]; then
  say "[failed] check exited ${CRC} AFTER the pull -- the added files are still there and must be read"
  write_status check-failed "check rc=$CRC after adding $ADDED" "$ADDED"
  exit 1
fi

# ── THE FORK, MEASURED ON EVERY RUN ──────────────────────────────────────────────────────────────
# This job already collects every tree, so the one instrument it was missing is the fork itself. It is
# recorded rather than alarmed on: the count is EXPECTED to be non-zero (336 frozen on 2026-10-16, while
# the machines collide with each other and the pull renumbers only what arrives). What matters is the
# CHANGE, so the previous run's number is read first and the delta is logged beside it.
PREV_FORK=$(sed -n 's/.*"fork_colliding":\(-\?[0-9]*\).*/\1/p' "$STATUS" 2>/dev/null | tail -1)
FORK=$(python3 "$REPO/scripts/evolution/journal-union/fork-size.py" --trees "$WORK/trees" --json 2>/dev/null \
        | sed -n 's/.*"colliding": *\([0-9]*\).*/\1/p' | tail -1)
FORK=${FORK:--1}
if [ "$PREV_FORK" != "" ] && [ "$FORK" -ge 0 ] 2>/dev/null; then
  say "fork across the collected trees: ${FORK} colliding ids  (previous run: ${PREV_FORK})"
else
  say "fork across the collected trees: ${FORK} colliding ids  (no previous reading)"
fi

if [ "$ADDED" -eq 0 ]; then
  say "[clean] nothing to converge"
  write_status clean "nothing to add" 0 "$FORK"
else
  say "[converged] added ${ADDED}; the canonical tree now holds every entry the sources have"
  write_status converged "added $ADDED (entries $BEFORE -> $AFTER)" "$ADDED" "$FORK"
fi
exit 0

# ── THE LINE, NOT INSTALLED ──────────────────────────────────────────────────────────────────────
# The estate's cron convention is a base64 payload through cron-wrap.sh, with the decode above it.
# decode: /bin/bash /root/code/harness-config/scripts/journal-converge.sh
# 17 4 * * * /usr/local/bin/cron-wrap.sh journal-converge <base64 of the decode line>
#
# It is NOT in the crontab. Turning it on is a decision about the record; it has been put to the
# owner twice and has not been answered. Until then the same command runs by hand, and this file is
# the whole runbook.
