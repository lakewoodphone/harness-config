#!/usr/bin/env bash
# install-crontab-fragment.sh — add a crontab FRAGMENT to root's crontab, safely and idempotently.
#
# WHY THIS EXISTS AND NOT `cat fragment | crontab -`
# Because that command REPLACES the whole crontab with whatever the fragment happens to contain. Four
# separate workstreams are each porting a different family of jobs onto the same new authority, and
# the first one to use the obvious command would silently delete the other three's work. This appends,
# de-duplicates by job NAME, refuses to install a line whose base64 payload does not round-trip, and
# keeps a timestamped before-image on every run.
#
# The job name is the second field of a `cron-wrap.sh <name> <base64>` line, which is the key the
# estate's run ledger (`~/.cron-status/runs.tsv`) already uses. Re-running the same fragment therefore
# updates that job's line rather than adding a second copy of it.
#
# USAGE
#   install-crontab-fragment.sh <fragment-file> [--dry-run]
#
# The fragment may carry comment lines (starting with #) and blanks; both are preserved on first
# install and ignored on re-install of an existing name.
set -uo pipefail

FRAG="${1:-}"
DRY=0
[ "${2:-}" = "--dry-run" ] && DRY=1
[ -f "$FRAG" ] || { echo "usage: $0 <fragment-file> [--dry-run]" >&2; exit 2; }

# ── ONE WRITER, EVEN BETWEEN WORKSTREAMS ────────────────────────────────────────────────────────
# Several workstreams install different families into the same crontab. A read-modify-write of a
# crontab that two processes interleave is exactly how one of them vanishes, so this whole script runs
# under a lock and the second caller waits rather than racing. The lock is advisory and costs nothing
# when there is no contention.
LOCK=/tmp/install-crontab-fragment.lock
exec 9>"$LOCK"
if ! flock -w 120 9; then
  echo "another install-crontab-fragment is running and did not finish inside 120 s; refusing" >&2
  exit 3
fi
echo "locked ($LOCK) for $(date -u '+%H:%M:%SZ')"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BACKUP="/root/crontab.before-${STAMP}"
STATE="/root/.cron-status"
mkdir -p "$STATE"

# ── 1. validate every wrapped line's payload BEFORE anything is written ──────────────────────────
TMP_NEW="$(mktemp)"
FAILED=0
ADDED=0
while IFS= read -r line; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  if printf '%s' "$line" | grep -q 'cron-wrap.sh'; then
    payload="$(printf '%s' "$line" | awk '{print $NF}')"
    if ! printf '%s' "$payload" | base64 -d >/dev/null 2>&1; then
      echo "REFUSING: payload does not decode for line:" >&2
      echo "  $line" >&2
      FAILED=1
      continue
    fi
    if [ -z "$(printf '%s' "$payload" | base64 -d 2>/dev/null)" ]; then
      echo "REFUSING: payload decodes to nothing for line:" >&2
      echo "  $line" >&2
      FAILED=1
      continue
    fi
    name="$(printf '%s' "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /cron-wrap.sh$/){print $(i+1); exit}}')"
    printf '%s\t%s\n' "$name" "$line" >> "$TMP_NEW"
    ADDED=$((ADDED+1))
  else
    echo "NOTE: not a cron-wrap line, taken as-is:" >&2
    echo "  $line" >&2
    printf '-\t%s\n' "$line" >> "$TMP_NEW"
  fi
done < "$FRAG"

if [ "$FAILED" -ne 0 ]; then
  echo "nothing installed: at least one payload failed to decode" >&2
  rm -f "$TMP_NEW"
  exit 2
fi
echo "fragment carries $ADDED wrapped job(s), all payloads decode"

# ── 2. take a before-image of whatever is installed now ─────────────────────────────────────────
crontab -l > "$BACKUP" 2>/dev/null || : > "$BACKUP"
echo "before-image: $BACKUP ($(grep -c . "$BACKUP" || true) line(s))"

# ── 3. build the merged crontab: every existing line kept, fragment lines replacing same-name ones ─
MERGED="$(mktemp)"
while IFS= read -r line; do
  [ -n "$line" ] || continue
  name=""
  case "$line" in
    '#'*) printf '%s\n' "$line" >> "$MERGED"; continue ;;
  esac
  if printf '%s' "$line" | grep -q 'cron-wrap.sh'; then
    name="$(printf '%s' "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /cron-wrap.sh$/){print $(i+1); exit}}')"
  fi
  if [ -n "$name" ] && cut -f1 "$TMP_NEW" | grep -qxF "$name"; then
    echo "replacing existing line for job: $name"
    continue
  fi
  printf '%s\n' "$line" >> "$MERGED"
done < "$BACKUP"
cut -f2- "$TMP_NEW" >> "$MERGED"
# de-duplicate names introduced twice inside the fragment itself, keeping the last
awk -F'\t' '{print $2}' "$TMP_NEW" > /dev/null

echo "--- merged crontab ($(grep -c . "$MERGED") non-blank line(s)) ---"
cat "$MERGED"
if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: NOT installed. The merged crontab above is what would be installed."
  rm -f "$TMP_NEW" "$MERGED"
  exit 0
fi

crontab "$MERGED"
rm -f "$TMP_NEW" "$MERGED"
echo "installed: $(crontab -l | grep -c . ) non-blank line(s) in root's crontab"
echo "verify the ledger after the first scheduled run: grep '<job-name>' $STATE/runs.tsv"
