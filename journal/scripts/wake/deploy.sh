#!/usr/bin/env bash
# deploy.sh -- install the wake pieces on secratary's ~/bin, and PRINT the cron lines.
#
# It never touches a crontab. It never deletes anything. It backs up every file it
# overwrites, and it will not change a single byte unless you say --apply.
#
#   deploy.sh --check                 read-only report (this is the default; changes nothing)
#   deploy.sh --dry-run               say exactly what --apply would change, change nothing
#   deploy.sh --apply                 install (and pause the queue unless --no-pause)
#
# Optional, each one explicit:
#   --migrate-wake-table   bring an existing, older `wake` table up to CONTRACT.md §3.
#                          REQUIRED on a box where the v0 was installed by hand: the
#                          contract's DDL is CREATE TABLE IF NOT EXISTS, so against an
#                          existing table it is a silent no-op and every lease/cap/attempt
#                          guard is dead. Takes an atomic .backup of inbox.db first.
#   --with-desktop-runner  copy scripts/wake/runner.ps1 to the desktop as ~/bin/wake-run.ps1
#   --no-pause             do not create the kill-switch file on install
#   --bin DIR              target bin dir           (default: $HOME/bin)
#   --state DIR            state dir                (default: $HOME/.sms-inbox)
#   --src DIR              source dir              (default: the dir holding this script)
#   --desktop HOST         desktop ssh alias            (default: zabz-tech-ts)
#   --help                 this text
#
# WHY THE 'APPLY' FLAG EXISTS: this script runs on the machine that is the company's
# authoritative store. A deploy that happened because someone typed the script's name is
# how you lose a machine, so the safe mode is the default one and the mode that writes
# says so out loud, twice, before and after.
set -uo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="check"
SRC_DIR="$SELF_DIR"
BIN_DIR="${HOME}/bin"
STATE_DIR="${HOME}/.sms-inbox"
DESKTOP="zabz-tech-ts"
DO_MIGRATE=0
DO_RUNNER=0
DO_PAUSE=1
CHANGED=0

# --------------------------------------------------------------------------- #
# 0. refuse to run if this file was transferred with Windows line endings.
#    Measured on secratary 2026-09-18: a live crontab line already ends with a
#    literal CR, so this failure is present in the wild and it is silent.
# --------------------------------------------------------------------------- #
if [ "$(head -1 "${BASH_SOURCE[0]}" | od -An -c | tr -d ' ' | grep -c '\\r')" != "0" ]; then
  printf 'FATAL: %s has CRLF line endings. Transfer it as LF:\n' "${BASH_SOURCE[0]}" >&2
  printf '  scp it, then:  sed -i "s/\\r$//" %s\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi

# Print the header comment block (lines 2..the first non-comment line), stripped of
# its leading '# '. Derived rather than hard-coded so it cannot drift out of date.
usage() { awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print; next } else { exit } }' "${BASH_SOURCE[0]}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check)                MODE="check" ;;
    --dry-run)              MODE="dry" ;;
    --apply)                MODE="apply" ;;
    --migrate-wake-table)   DO_MIGRATE=1 ;;
    --with-desktop-runner)  DO_RUNNER=1 ;;
    --no-pause)             DO_PAUSE=0 ;;
    --bin)                  BIN_DIR="$2"; shift ;;
    --state)                STATE_DIR="$2"; shift ;;
    --src)                  SRC_DIR="$2"; shift ;;
    --desktop)              DESKTOP="$2"; shift ;;
    --help|-h)              usage; exit 0 ;;
    *) printf 'unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

DB="${SMS_INBOX_DB:-$STATE_DIR/inbox.db}"
CRON_TXT="$SRC_DIR/cron.txt"

say()  { printf '%s\n' "$*"; }
run()  { if [ "$MODE" = "apply" ]; then "$@"; else printf '        would run: %s\n' "$*"; fi; }

note_change() { CHANGED=$((CHANGED + 1)); say "  CHANGED  $*"; }

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
backup_of() {   # print a backup path that does not exist yet; never overwrites a backup
  local p="$1.bak-wake-deploy-$STAMP" n=0
  while [ -e "$p" ]; do n=$((n + 1)); p="$1.bak-wake-deploy-$STAMP.$n"; done
  printf '%s' "$p"
}

install_file() {  # install_file <src> <dst> <mode>
  local src="$1" dst="$2" mode="$3"
  if [ ! -f "$src" ]; then
    say "  MISSING  $src -- not installing $dst"
    return 1
  fi
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    say "  ok       $dst (identical, nothing to do)"
    return 0
  fi
  if [ -f "$dst" ]; then
    local b; b="$(backup_of "$dst")"
    say "  backup   $dst -> $b"
    run cp -p "$dst" "$b"
  fi
  run install -m "$mode" "$src" "$dst"
  note_change "$dst  (from $src)"
}

verify_script() {  # verify_script <path> -- syntax check only, never executes it
  local p="$1"
  case "$p" in
    *.sh) if bash -n "$p" 2>/dev/null; then say "  ok       bash -n $p"; else say "  FAIL     bash -n $p"; return 1; fi ;;
    *.py) if python3 -m py_compile "$p" 2>/dev/null; then say "  ok       python3 -m py_compile $p"; else say "  FAIL     py_compile $p"; return 1; fi ;;
  esac
  return 0
}

# Does the live wake table carry the column the contract's guards need?
need_col() {  # need_col <db> <column> -> 0 if present
  sqlite3 "$1" "select count(*) from pragma_table_info('wake') where name='$2';" 2>/dev/null | grep -qx '1'
}

# --------------------------------------------------------------------------- #
# 1. what is here, and what this run is
# --------------------------------------------------------------------------- #
say "=============================================================================="
say " wake deploy   host=$(hostname)   mode=$MODE   $STAMP"
say " source  $SRC_DIR"
say " target  $BIN_DIR   state  $STATE_DIR"
say " db      $DB"
say "=============================================================================="
say ""
say "-- 1. source tree"
for f in wake.py dispatch.sh runner.ps1 cron.txt; do
  if [ -f "$SRC_DIR/$f" ]; then say "  present  $SRC_DIR/$f"; else say "  absent   $SRC_DIR/$f"; fi
done
if [ -d "$SRC_DIR/sources" ]; then
  say "  present  $SRC_DIR/sources/ ($(ls -1 "$SRC_DIR/sources"/*.py 2>/dev/null | wc -l) python file(s))"
else
  say "  absent   $SRC_DIR/sources/"
fi
say ""

say "-- 2. existing install"
for f in wake.py wake-dispatch.sh; do
  if [ -f "$BIN_DIR/$f" ]; then
    say "  present  $BIN_DIR/$f  ($(stat -c '%s bytes, %y' "$BIN_DIR/$f" 2>/dev/null | cut -c1-40))"
  else
    say "  absent   $BIN_DIR/$f"
  fi
done
if [ -f "$STATE_DIR/WAKE_PAUSED" ]; then say "  SEALED   $STATE_DIR/WAKE_PAUSED exists -- claim returns nothing"; else say "  open     no $STATE_DIR/WAKE_PAUSED"; fi
say ""

say "-- 3. the live wake table (this decides whether the guards can work at all)"
if ! command -v sqlite3 >/dev/null 2>&1; then
  say "  UNKNOWN  no sqlite3 on PATH -- this check cannot read the table, so it will not"
  say "           guess. Install sqlite3 and re-run --check before --apply."
elif [ ! -f "$DB" ]; then
  say "  no database at $DB -- flag/claim will create it; table migration is not needed"
else
  cols="$(sqlite3 "$DB" "select name from pragma_table_info('wake');" 2>/dev/null | tr '\n' ' ')"
  say "  columns: ${cols:-(no wake table yet)}"
  missing=""
  for c in source not_before attempts max_attempts lease_until cost_usd; do
    need_col "$DB" "$c" || missing="$missing $c"
  done
  if [ -n "$missing" ]; then
    say ""
    say "  ############################################################################"
    say "  # THE GUARDS CANNOT WORK AS INSTALLED."
    say "  # CONTRACT.md 3 requires these columns on wake and they do NOT exist:"
    say "  #$missing"
    say "  #"
    say "  # The contract's DDL is CREATE TABLE IF NOT EXISTS, so re-running it is a"
    say "  # no-op against this table: lease, reap, attempt cap, cooldown, per-source"
    say "  # cap and cost all silently do nothing while the install looks successful."
    say "  #"
    say "  # Fix with:  deploy.sh --apply --migrate-wake-table"
    say "  ############################################################################"
    say ""
  else
    say "  ok       all six contract columns present"
  fi
  n_budget="$(sqlite3 "$DB" "select count(*) from sqlite_master where type='table' and name='wake_budget';" 2>/dev/null)"
  [ "$n_budget" = "1" ] && say "  ok       wake_budget present" || say "  MISSING  wake_budget (guard 3 cannot be counted)"
fi
say ""

# --------------------------------------------------------------------------- #
# 2. the cron situation, stated before anything is installed
# --------------------------------------------------------------------------- #
say "-- 4. cron (this script NEVER edits a crontab)"
live_wake="$(crontab -l 2>/dev/null | grep -c 'wake-dispatch' || true)"; live_wake="${live_wake:-0}"
say "  crontab lines mentioning wake-dispatch: $live_wake"
if [ "$live_wake" -ge 1 ]; then
  crontab -l 2>/dev/null | grep -n 'wake-dispatch' | sed 's/^/    /'
  say ""
  say "  ############################################################################"
  say "  # A DISPATCHER IS ALREADY ON CRON."
  say "  # Adding the lines below WITHOUT removing the one above gives two"
  say "  # dispatchers, and the v0 shares one fixed prompt/out filename between"
  say "  # releases -- measured live 2026-09-18 03:10Z: pids 2661989/2661990 running"
  say "  # at once, both writing C:/Users/ezabz/bin/wake-prompt.txt."
  say "  #"
  say "  # Back the crontab up and remove the old line FIRST:"
  say "  #   crontab -l > ~/crontab-backup-\$(date -u +%Y%m%dT%H%M%SZ).txt"
  say "  #   crontab -e      # comment out or delete the wake-dispatch line"
  say "  ############################################################################"
fi
line51_cr="$(crontab -l 2>/dev/null | cat -A | grep -c '\^M\$' || true)"; line51_cr="${line51_cr:-0}"
say "  crontab lines ending in a real CR byte (0x0d, CRLF damage): $line51_cr"
[ "$line51_cr" -gt 0 ] && say "    ^ on this line the last command cannot run: a CR ends the word before it"

# The OTHER line-ending failure, and the one actually present on secratary today:
# a line ending in the two literal characters `\` and `r`. Measured 2026-09-18:
# crontab line 51 ends `... 2>&1\r`, and reproducing it gives
#   1r: ambiguous redirect   rc=1
# with the command NOT running. Its log (~/.sms-inbox/learn.log) does not exist.
lit_r="$(crontab -l 2>/dev/null | grep -c '\\r$' || true)"; lit_r="${lit_r:-0}"
say "  crontab lines ending in the literal characters backslash-r: $lit_r"
if [ "$lit_r" -gt 0 ]; then
  crontab -l 2>/dev/null | grep -n '\\r$' | cut -c1-140 | sed 's/^/    /'
  say "    ^ MEASURED BROKEN. bash parses the tail as a redirect to the word 'r':"
  say "      '1r: ambiguous redirect', rc=1, and the command on that line never runs."
  say "      Proven on secratary 2026-09-18 with a reproduction of the exact tail."
fi
say ""

# --------------------------------------------------------------------------- #
# 3. install
# --------------------------------------------------------------------------- #
say "-- 5. install"
if [ "$MODE" = "check" ]; then
  say "  --check: nothing installed. Run --dry-run to see the plan, --apply to execute."
else
  # NOTE: the target directory is created here and NOT earlier, so that --check and
  # --dry-run are genuinely read-only -- a dry run that creates a directory is a
  # dry run that lied about what it did.
  run mkdir -p "$BIN_DIR"
  install_file "$SRC_DIR/wake.py"     "$BIN_DIR/wake.py"         0755
  install_file "$SRC_DIR/dispatch.sh" "$BIN_DIR/wake-dispatch.sh" 0755
  install_file "$SRC_DIR/cron.txt"    "$BIN_DIR/wake-cron.txt"    0644
  if [ -d "$SRC_DIR/sources" ]; then
    run mkdir -p "$BIN_DIR/wake-sources"
    for s in "$SRC_DIR"/sources/*.py; do
      [ -f "$s" ] || continue
      install_file "$s" "$BIN_DIR/wake-sources/$(basename "$s")" 0755
    done
  fi
fi
say ""

say "-- 6. verify (syntax only; the real database is NOT opened)"
if [ "$MODE" = "apply" ]; then
  for f in "$BIN_DIR/wake.py" "$BIN_DIR/wake-dispatch.sh"; do
    if [ -f "$f" ]; then verify_script "$f" || true; else say "  skipped  $f not installed (see section 5)"; fi
  done
  if [ -f "$BIN_DIR/wake.py" ]; then
    tmpdb="$(mktemp -u "${TMPDIR:-/tmp}/wake-verify-XXXXXX.db")"
    if SMS_INBOX_DB="$tmpdb" python3 "$BIN_DIR/wake.py" stats >/dev/null 2>&1; then
      say "  ok       wake.py stats works against a throwaway db ($tmpdb)"
    else
      say "  FAIL     wake.py stats did not run against a throwaway db"
    fi
  fi
fi
if [ "$MODE" != "apply" ]; then say "  (skipped in $MODE mode)"; fi
say ""

# --------------------------------------------------------------------------- #
# 4. the table migration -- additive only, after an atomic backup
# --------------------------------------------------------------------------- #
say "-- 7. wake table migration"
if [ "$DO_MIGRATE" != "1" ]; then
  say "  not requested (--migrate-wake-table). See section 3 above for whether you need it."
else
  if [ ! -f "$DB" ]; then
    say "  no database at $DB -- nothing to migrate"
  else
    b="$(backup_of "$DB")"
    say "  backup   $DB -> $b   (sqlite3 .backup, atomic, safe on a live db)"
    run sqlite3 "$DB" ".backup $b"
    for pair in \
      "source:TEXT NOT NULL DEFAULT 'manual'" \
      "not_before:TEXT" \
      "attempts:INTEGER NOT NULL DEFAULT 0" \
      "max_attempts:INTEGER NOT NULL DEFAULT 2" \
      "lease_until:TEXT" \
      "cost_usd:REAL" ; do
      c="${pair%%:*}"; ddl="${pair#*:}"
      if need_col "$DB" "$c"; then
        say "  ok       wake.$c already present"
      else
        run sqlite3 "$DB" "ALTER TABLE wake ADD COLUMN $c $ddl;"
        note_change "wake.$c added ($ddl)"
      fi
    done
    run sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS wake_budget (day TEXT PRIMARY KEY, released INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0);"
    run sqlite3 "$DB" "CREATE INDEX IF NOT EXISTS idx_wake_state ON wake(state);"
    if [ "$MODE" = "apply" ]; then
      say "  columns now: $(sqlite3 "$DB" "select name from pragma_table_info('wake');" 2>/dev/null | tr '\n' ' ')"
    fi
  fi
fi
say ""

# --------------------------------------------------------------------------- #
# 5. the kill switch, so the first cron tick does nothing until a human says so
# --------------------------------------------------------------------------- #
say "-- 8. kill switch"
if [ "$MODE" != "apply" ]; then
  say "  (on --apply this creates $STATE_DIR/WAKE_PAUSED unless --no-pause, so the first"
  say "   cron tick releases nothing and you resume deliberately with: wake.py resume)"
elif [ "$DO_PAUSE" = "1" ]; then
  run mkdir -p "$STATE_DIR"
  if [ -f "$STATE_DIR/WAKE_PAUSED" ]; then
    say "  ok       $STATE_DIR/WAKE_PAUSED already present"
  else
    run sh -c "printf 'installed %s by deploy.sh -- remove with: wake.py resume\n' '$STAMP' > '$STATE_DIR/WAKE_PAUSED'"
    note_change "$STATE_DIR/WAKE_PAUSED created (queue is paused)"
  fi
else
  say "  --no-pause: the queue is NOT paused. Flags will be released on the next tick."
fi
say ""

# --------------------------------------------------------------------------- #
# 6. the desktop runner -- verify by default, install only when asked
# --------------------------------------------------------------------------- #
say "-- 9. desktop runner ($DESKTOP)"
if ssh -n -o ConnectTimeout=10 -o BatchMode=yes "$DESKTOP" "echo ok" >/dev/null 2>&1; then
  say "  ok       ssh $DESKTOP reachable"
  say "  ok       $(ssh -n -o ConnectTimeout=10 -o BatchMode=yes "$DESKTOP" \
      "powershell -NoProfile -Command \"if (Test-Path 'C:\\Users\\ezabz\\bin\\wake-run.ps1') {'wake-run.ps1 present'} else {'wake-run.ps1 MISSING'}\"" 2>/dev/null)"
  say "  ok       $(ssh -n -o ConnectTimeout=10 -o BatchMode=yes "$DESKTOP" \
      "powershell -NoProfile -Command \"if (Test-Path (Join-Path \$env:USERPROFILE '.dsh\\profiles\\headless')) {'headless profile present'} else {'headless profile MISSING'}\"" 2>/dev/null)"
  if [ "$DO_RUNNER" = "1" ]; then
    if [ -f "$SRC_DIR/runner.ps1" ]; then
      # Pull the current runner DOWN as the backup, then push the new one. No nested
      # quoting is ever constructed (the repo's own rule), and both files survive.
      say "  backup   pulling desktop:$DESKTOP C:/Users/ezabz/bin/wake-run.ps1 -> $BIN_DIR/wake-run.ps1.desktop-$STAMP"
      run scp -q -o BatchMode=yes "$DESKTOP:C:/Users/ezabz/bin/wake-run.ps1" "$BIN_DIR/wake-run.ps1.desktop-$STAMP"
      run scp -q -o BatchMode=yes "$SRC_DIR/runner.ps1" "$DESKTOP:C:/Users/ezabz/bin/wake-run.ps1"
      note_change "desktop:$DESKTOP C:/Users/ezabz/bin/wake-run.ps1 replaced (old copy at $BIN_DIR/wake-run.ps1.desktop-$STAMP)"
    else
      say "  no $SRC_DIR/runner.ps1 to install (W2 owns it)"
    fi
  else
    say "  not installing (--with-desktop-runner not given; W2 owns runner.ps1)"
  fi
else
  say "  FAIL     ssh $DESKTOP unreachable -- a flag will claim, fail to reach the desktop,"
  say "           and be marked failed. Fix the hop before enabling cron."
fi
say ""

# --------------------------------------------------------------------------- #
# 7. the cron lines, printed and never installed
# --------------------------------------------------------------------------- #
say "=============================================================================="
say " CRON LINES -- NOT INSTALLED. Add them yourself, on purpose."
say "=============================================================================="
if [ -f "$CRON_TXT" ]; then
  cat "$CRON_TXT"
else
  say " $CRON_TXT not found -- see scripts/wake/cron.txt in the repo."
fi
say ""
say " To add them:"
say "   crontab -l > ~/crontab-backup-\$(date -u +%Y%m%dT%H%M%SZ).txt"
say "   crontab -e"
say "   # paste, save, then prove it:   crontab -l | tail -3"
say "   # and prove the ENDINGS:       crontab -l | cat -A | tail -3   ('\$', never '^M\$')"
say ""

say "-- 10. the scripts those cron lines will call"
for f in "$BIN_DIR/dispatch.sh" "$BIN_DIR/wake-dispatch.sh" "$BIN_DIR/wake-cron.txt" "$BIN_DIR/wake-liveness.sh"; do
  if [ -f "$f" ]; then say "  present  $f"; else say "  MISSING  $f"; fi
done
if [ -f "$CRON_TXT" ]; then
  say "  cron.txt names $(grep -c '^\*' "$CRON_TXT") runnable line(s):"
  grep -n '^\*' "$CRON_TXT" | sed 's/^/    /'
  say "  every one of those must exist before its line is added. wake-liveness.sh is"
  say "  NOT owned by this stream -- see the note in cron.txt section 2."
fi
say ""

# --------------------------------------------------------------------------- #
# 8. what this run did
# --------------------------------------------------------------------------- #
say "=============================================================================="
case "$MODE" in
  check) say " RESULT: nothing was changed (--check)." ;;
  dry)   say " RESULT: nothing was changed (--dry-run). $CHANGED item(s) would change on --apply." ;;
  apply)
    if [ "$CHANGED" -eq 0 ]; then
      say " RESULT: APPLIED. Nothing needed changing -- this box already matches the source."
    else
      say " RESULT: APPLIED. $CHANGED change(s) made on $(hostname):"
    fi
    ;;
esac
if [ "$MODE" = "apply" ]; then
  if [ -f "$STATE_DIR/WAKE_PAUSED" ]; then say " The queue is PAUSED. Resume with: python3 $BIN_DIR/wake.py resume"; fi
  say " Verify, do not assume:"
  say "   python3 $BIN_DIR/wake.py stats"
  say "   python3 $BIN_DIR/wake.py list --state new"
  say "   tail -3 $STATE_DIR/wake-dispatch.log   # after the first cron tick"
fi
say "=============================================================================="
exit 0
