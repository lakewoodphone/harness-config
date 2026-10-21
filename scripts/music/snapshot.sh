#!/usr/bin/env bash
# Nightly local snapshot of the music ledger.
#
# WHY: /opt/company/music has no offsite path (see README "Known gaps"). This is the only thing
# standing between a corrupt write and losing every play older than Spotify's 50-item window, so it
# uses sqlite's own .backup (consistent under a live writer) rather than cp.
set -uo pipefail

SRC=/opt/company/music/taste.db
DEST=/var/lib/authority-snapshots/music
SHIPPED=/opt/company/data/music
KEEP_DAYS=14
SQLITE=$(command -v sqlite3 || echo /usr/bin/sqlite3)

mkdir -p "$DEST" "$SHIPPED"
chmod 700 "$DEST" "$SHIPPED"
DAY=$(date -u +%Y%m%d)
OUT="$DEST/taste-$DAY.db"

if [ ! -f "$SRC" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR ledger missing: $SRC"
  exit 1
fi

"$SQLITE" "$SRC" ".backup '$OUT'" || { echo "[$(date -u +%FT%TZ)] ERROR sqlite backup failed"; exit 1; }
chmod 600 "$OUT"

# verify the snapshot opens and has the table we care about, rather than trusting the copy
ROWS=$("$SQLITE" "$OUT" "select count(*) from plays;" 2>/dev/null)
if [ -z "${ROWS:-}" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR snapshot does not open or has no plays table: $OUT"
  exit 1
fi

find "$DEST" -name 'taste-*.db' -mtime +$KEEP_DAYS -delete

# Second copy, into /opt/company/data, because authority-data-offsite.timer archives that whole
# directory to R2 (bucket lpt-authority-backups) every morning at ~06:37 UTC. That is the only path
# by which this ledger leaves the machine. The credential file is deliberately NOT copied: a token in
# a tar on R2 is a leaked token, and re-auth is the recovery path instead.
cp -p "$OUT" "$SHIPPED/" || { echo "[$(date -u +%FT%TZ)] ERROR could not stage into $SHIPPED"; exit 1; }
chmod 600 "$SHIPPED/$(basename "$OUT")"
find "$SHIPPED" -name 'taste-*.db' -mtime +$KEEP_DAYS -delete

echo "[$(date -u +%FT%TZ)] snapshot $OUT $(stat -c %s "$OUT") bytes, plays=$ROWS | staged for offsite: $SHIPPED/$(basename "$OUT")"
