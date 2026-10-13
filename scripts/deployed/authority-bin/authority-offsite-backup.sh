#!/usr/bin/env bash
# authority-offsite-backup.sh — ship the authority's database offsite, from the authority itself.
# v3, 2026-10-11. Deployed to secratary-cloud:/usr/local/bin/authority-offsite-backup.sh.
#
# ══════════════════════════════════════════════════════════════════════════════════════════════
# PEAK EXTRA DISK USAGE IS APPROXIMATELY ZERO. THAT IS THE POINT OF THIS FILE.
# ══════════════════════════════════════════════════════════════════════════════════════════════
# This host is 75 GB with a 23.6 GB live database on it; free space runs 4-27 GB. Any design that
# materialises the database, or its compressed form, as a file, does not fit here. This one
# materialises neither: the consistent copy exists only as bytes in flight.
#
#     read-pages.py  ──►  gzip -6  ──►  upload-multipart.py  ──►  R2 object
#     (SQLite dbpage      (stdout)      (64 MiB parts, hand-     authority/secretary.db.gz
#      inside ONE read                  rolled because boto3's
#      transaction)                     upload_fileobj wants a
#                                       seekable file object)
#
# The only bytes this script writes to a filesystem are its log, its state file and ~24 KB of
# helper sources under /run (tmpfs). It never takes a snapshot file, never writes a .gz file, and
# never writes a part file.
#
# ── WHY NOT `sqlite3 .backup` INTO A FIFO (v2's design — MEASURED IMPOSSIBLE) ───────────────────
# v2 piped `sqlite3 .backup <fifo>` into gzip, on the claim that `.backup` writes front-to-back and
# never seeks, so a FIFO is a legal destination. THAT CLAIM IS FALSE ON THIS HOST. Measured
# 2026-10-11 06:13Z with sqlite3 3.46.1:
#     $ mkfifo -m 600 /tmp/t.fifo; sqlite3 /tmp/t.db ".backup /tmp/t.fifo"
#     Error: cannot open "/tmp/t.fifo"           (backup_rc=1; /tmp/t.copy 0 bytes)
# The unix VFS refuses to open a non-regular file as a database, and the pager writes with pwrite(),
# which a pipe cannot serve. No version of this design can work; do not restore it.
#
# So the consistent copy is taken through SQLite's own `sqlite_dbpage` virtual table (this build has
# ENABLE_DBPAGE_VTAB) inside a single read transaction, which is the same consistent view `.backup`
# reads. MEASURED 2026-10-11 on this host:
#   * the page stream of a 200 MB database is BYTE-IDENTICAL to the database file (`cmp` ok);
#   * the page stream of a WAL database with uncheckpointed content restores to
#     `PRAGMA integrity_check` = ok with every row present;
#   * `EXPLAIN QUERY PLAN SELECT data FROM sqlite_dbpage ORDER BY pgno` is `SCAN ... VIRTUAL TABLE
#     INDEX 0` — no temp B-tree, so nothing is materialised or spilled to disk;
#   * the live 23.6 GB authority database streams at ~357 MB/s (200,000 pages = 819,200,000 bytes
#     in 2.294 s).
#
# ── WHY THE PREVIOUS RUN LOOKED STALLED (v1, started 06:01:38Z) ────────────────────────────────
# Not gzip, and not the disk filling. The launching shell died; the script and its
# `sqlite3 ... PRAGMA integrity_check` child were reparented to init and left in state T (stopped) —
# `/proc/57560/io` rchar byte-for-byte identical across 8 s, CPU frozen at 1:01, forever. The
# snapshot copy had finished (23,622,823,936 B) and the check had read 20.07 GB of it when it was
# stopped. Nothing was ever going to resume it.
#   ⇒ So this script is started by a systemd unit (or under setsid): a backup must not depend on the
#     ssh session that started it staying alive. `systemctl start authority-offsite-backup.service`.
#   ⇒ And v1 would have died on the next step anyway: with the 23.6 GB snapshot on disk, its
#     `gzip -6` needed ~7 GB more and 4.4 GB was free. The office-era object in the same bucket is
#     7,234,886,331 B, so that is arithmetic, not a hypothesis.
#
# ── WHAT IS CHECKED, AND WHAT EACH CHECK IS FOR ────────────────────────────────────────────────
#   0. the source is a readable SQLite database, and the reader refuses a short stream: bytes
#      streamed must equal page_size * page_count taken in the same read transaction. A gzip whose
#      input cannot be read writes ZERO bytes and exits 0; without this the result is a 0-byte
#      object on R2, the purest form of "looks like success, is nothing".
#   1. compressed size between 10% and 100% of the source, checked locally AND against the object
#      that landed (head_object ContentLength). A truncated upload looks exactly like success.
#   2. the object is read BACK from R2 and, in one streaming pass, gunzipped in memory: the sha256
#      of the compressed object must equal what was uploaded, the sha256 and length of the
#      decompressed stream must equal what the reader emitted, and the first 16 bytes must be the
#      SQLite file magic. A byte count cannot tell you the bytes are a database; this can.
#   3. a sha256 sidecar (of the COMPRESSED object) beside the copy, in the office format
#      `<sha256>  <basename>\n`, so the existing convention survives byte for byte.
#   On any failure the object this run created is REMOVED, so a bad copy is never left in place
#   looking like a good one, and the run exits non-zero so a monitor sees it.
#
# ── WHY MULTIPART MAKES RE-RUNNING SAFE ────────────────────────────────────────────────────────
# An S3/R2 multipart upload is invisible until CompleteMultipartUpload, and it is completed only
# after every part is in and the stream has ended. A killed run leaves no partial object.
#
# DAILY, not hourly: the upload is ~7 GB against an object overwritten in place. RPO for "this
# machine is gone" is therefore up to 24 h. A considered number, not a default.
set -uo pipefail

LOG="${LOG:-/var/log/authority-offsite.log}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
exec >>"$LOG" 2>&1
echo "===== $(date -u '+%Y-%m-%d %H:%M:%S') authority-offsite-backup v3 start (pid $$)"

CRED="${R2_ENV:-/root/.lpt-r2.env}"
DB="${DB:-/root/authority.db}"
STATE_DIR="${STATE_DIR:-/var/lib/authority-backup}"
RUNDIR="${RUNDIR:-/run/authority-offsite}"
HELP="$RUNDIR/helpers"
DB_KEY="${DB_KEY:-authority/secretary.db.gz}"
LEDGER_KEY="${LEDGER_KEY:-authority/accounting.db.gz}"
PY="${PY:-/usr/bin/python3}"
GZIP_LEVEL="${GZIP_LEVEL:-6}"
PART_MB="${PART_MB:-64}"
# The floor exists ONLY so we do not write logs into a filesystem with nothing left. This run adds
# no bytes to the disk, so it does not need room for a copy — 256 MiB, not the 2 GiB a file-based
# design would demand, and it deliberately does NOT refuse when the disk is nearly full, because
# that is exactly when an offsite copy matters most.
FLOOR_KB=$(( ${FLOOR_MIB:-256} * 1024 ))
LOCK="/run/authority-offsite-backup.lock"
VERIFY="${ZABZ_VERIFY_STREAM:-1}"
RC=0

# The ledger moved boxes at the cutover and the canonical path is NOT the one v1 guessed. v1's
# default was /opt/company/data/accounting.db, which on this host is a 0-BYTE decoy written
# 2026-08-28 — v1 would have "sent" an empty ledger and reported success. MEASURED 2026-10-11 06:12Z:
#   /opt/company/data/accounting.db           0 B      2026-08-28  (decoy)
#   /root/accounting-data/live/accounting.db  16,384 B  2026-10-11 05:41  (real, integrity ok)
LEDGER_CANDIDATES="${LEDGER:-/root/accounting-data/live/accounting.db /opt/company/data/accounting.db}"

trap 'echo "===== $(date -u "+%Y-%m-%d %H:%M:%S") interrupted by signal; rc=$RC"; exit 3' INT TERM HUP

# ── preconditions: everything that can refuse, refuses BEFORE anything is sent ──────────────────
[ -f "$CRED" ] || {
  echo "FATAL: credential file $CRED does not exist. Refusing to run: an unconfigured backup that"
  echo "       exits 0 is worse than none, because it is believed."
  exit 3
}
perm=$(stat -c '%a' "$CRED")
[ "$perm" = "600" ] || {
  echo "FATAL: $CRED is mode $perm, must be 600. Refusing to read a token the whole box can read."
  exit 3
}
[ -s "$DB" ] || { echo "FATAL: $DB is missing or empty."; exit 3; }
sqlite3 "file:$DB?mode=ro" 'PRAGMA schema_version;' >/dev/null 2>&1 || {
  echo "FATAL: $DB is not a readable SQLite database; refusing to ship nothing."
  exit 3
}
dbsize=$(stat -c '%s' "$DB")
avail_before_kb=$(df -Pk / | awk 'NR==2{print $4}')
if [ "$avail_before_kb" -lt "$FLOOR_KB" ]; then
  echo "FATAL: ${avail_before_kb} KiB free on /, floor is ${FLOOR_KB} KiB. Refusing to start."
  echo "       (This run needs no disk. Do NOT delete the database or any backup to make room.)"
  exit 3
fi

# Single-flight: two runs would double the uplink load and race on the same object.
exec 9>"$LOCK" || { echo "FATAL: cannot open $LOCK"; exit 3; }
if ! flock -n 9; then
  echo "another run holds $LOCK; exiting without doing anything"
  exit 0
fi

mkdir -p "$STATE_DIR" "$HELP"
# "started, not finished" is a different state from "never started": a backup that stalls must not
# look like one that is idle. A stale `running` marker is what the freshness monitor alarms on.
printf 'started_at=%s\npid=%s\nsource=%s\nsource_bytes=%s\n' \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" "$DB" "$dbsize" > "$STATE_DIR/running"

# shellcheck disable=SC1090
set -a; . "$CRED"; set +a
: "${R2_ENDPOINT:?}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_BUCKET:?}"
export R2_ENDPOINT R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET

# ── helpers, written fresh each run into tmpfs ──────────────────────────────────────────────────
cat > "$HELP/read-pages.py" <<'PYEOF'
#!/usr/bin/env python3
"""Stream a CONSISTENT copy of a SQLite database to stdout, one page at a time, touching no disk.

SQLite cannot write a database to a pipe (`sqlite3 .backup <fifo>` -> "cannot open": the unix VFS
refuses a non-regular file, and the pager writes with pwrite()). So the consistent view is read
through SQLite's own `sqlite_dbpage` virtual table, inside ONE read transaction: every page comes
from the same snapshot, including pages still living in the WAL. Rows arrive in page order with no
temp B-tree (verified: `EXPLAIN QUERY PLAN` = SCAN sqlite_dbpage VIRTUAL TABLE INDEX 0).

Measured 2026-10-11: the stream of a 200 MB database is byte-identical to the file (`cmp`), and a
WAL database's stream restores to integrity_check=ok with every row present.
"""
import hashlib
import io
import os
import sqlite3
import sys


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: read-pages.py <database>\n")
        return 2
    db = sys.argv[1]
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.execute("BEGIN")                      # one snapshot for the whole stream
    psize = con.execute("PRAGMA page_size").fetchone()[0]
    pcount = con.execute("PRAGMA page_count").fetchone()[0]
    out = io.BufferedWriter(io.FileIO(1, "wb", closefd=False), 1 << 20)
    h = hashlib.sha256()
    nbytes = 0
    npages = 0
    for (page,) in con.execute("SELECT data FROM sqlite_dbpage ORDER BY pgno"):
        out.write(page)
        h.update(page)
        nbytes += len(page)
        npages += 1
    out.flush()
    con.execute("ROLLBACK")
    con.close()
    expect = psize * pcount
    status = "ok" if nbytes == expect else "SHORT"
    sys.stderr.write(
        "READER status=%s pages=%d page_size=%d bytes=%d expected_bytes=%d sha256=%s db_bytes=%d\n"
        % (status, npages, psize, nbytes, expect, h.hexdigest(), os.path.getsize(db))
    )
    return 0 if nbytes == expect else 1


sys.exit(main())
PYEOF

cat > "$HELP/upload-multipart.py" <<'PYEOF'
#!/usr/bin/env python3
"""Upload stdin to R2 as ONE multipart object, 64 MiB parts, holding only one part in memory.

Hand-rolled rather than boto3's upload_fileobj, which needs a seekable file object and this is a
pipe. The part is materialised as bytes so a botocore retry can re-send the same part. On ANY
failure the multipart upload is aborted, so nothing half-written is ever visible in the bucket.
"""
import datetime
import hashlib
import os
import sys

import boto3
from botocore.config import Config


def main():
    key = os.environ["OFF_KEY"]
    bucket = os.environ["R2_BUCKET"]
    part_size = int(float(os.environ.get("OFF_PART_MB", "64")) * 1024 * 1024)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"},
                      connect_timeout=20, read_timeout=300),
    )
    src = sys.stdin.buffer
    h = hashlib.sha256()
    total = 0
    nparts = 0
    parts = []
    uid = s3.create_multipart_upload(Bucket=bucket, Key=key,
                                     ContentType="application/gzip")["UploadId"]
    try:
        while True:
            buf = bytearray()
            while len(buf) < part_size:
                chunk = src.read(part_size - len(buf))
                if not chunk:
                    break
                buf += chunk
            if not buf:
                break
            nparts += 1
            r = s3.upload_part(Bucket=bucket, Key=key, UploadId=uid, PartNumber=nparts,
                               Body=bytes(buf))
            parts.append({"ETag": r["ETag"], "PartNumber": nparts})
            h.update(buf)
            total += len(buf)
        if nparts == 0:
            raise RuntimeError("empty input stream: refusing to complete an empty object")
        s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=uid,
                                     MultipartUpload={"Parts": parts})
    except BaseException as exc:
        sys.stderr.write("UPLOAD FAILED %s: %s\n" % (type(exc).__name__, str(exc)[:300]))
        try:
            s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            sys.stderr.write("aborted multipart upload %s\n" % uid)
        except Exception:
            pass
        return 1
    head = s3.head_object(Bucket=bucket, Key=key)
    print("UPLOAD gz_bytes=%d gz_sha256=%s parts=%d remote_bytes=%d remote_last_modified=%s"
          % (total, h.hexdigest(), nparts, head["ContentLength"],
             head["LastModified"].astimezone(datetime.timezone.utc).isoformat()))
    return 0


sys.exit(main())
PYEOF

cat > "$HELP/verify-object.py" <<'PYEOF'
#!/usr/bin/env python3
"""Read the object back off R2 and prove it, in ONE streaming pass and without writing a file, is
exactly what we meant to send and is a SQLite database.

Checks: gzip stream complete; sha256 of the compressed object == uploaded; sha256 and byte length
of the decompressed stream == what the reader emitted; first 16 bytes == SQLite file magic.
A byte count cannot distinguish a database from 7 GB of zeroes. This can.
"""
import hashlib
import os
import sys
import zlib

import boto3
from botocore.config import Config

MAGIC = b"SQLite format 3\x00"


def main():
    bucket = os.environ["R2_BUCKET"]
    key = os.environ["OFF_KEY"]
    exp_gz_sha = os.environ.get("EXP_GZ_SHA", "")
    exp_gz_bytes = int(os.environ.get("EXP_GZ_BYTES", "0"))
    exp_db_sha = os.environ.get("EXP_DB_SHA", "")
    exp_db_bytes = int(os.environ.get("EXP_DB_BYTES", "0"))
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"},
                      connect_timeout=20, read_timeout=300),
    )
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    dz = zlib.decompressobj(31)
    gz = hashlib.sha256()
    db = hashlib.sha256()
    gzn = dbn = 0
    first = b""
    while True:
        chunk = body.read(1 << 20)
        if not chunk:
            break
        gz.update(chunk)
        gzn += len(chunk)
        try:
            out = dz.decompress(chunk)
        except zlib.error as exc:
            print("VERIFY FAIL reason=gzip-error:%s" % exc)
            return 1
        if out:
            if len(first) < 16:
                first += out[:16 - len(first)]
            db.update(out)
            dbn += len(out)
    try:
        tail = dz.flush()
    except zlib.error as exc:
        print("VERIFY FAIL reason=gzip-flush-error:%s" % exc)
        return 1
    if tail:
        db.update(tail)
        dbn += len(tail)
    bad = []
    if not dz.eof:
        bad.append("gzip-stream-incomplete")
    if gzn != exp_gz_bytes:
        bad.append("gz_bytes=%d-expected=%d" % (gzn, exp_gz_bytes))
    if gz.hexdigest() != exp_gz_sha:
        bad.append("gz_sha256-mismatch")
    if dbn != exp_db_bytes:
        bad.append("db_bytes=%d-expected=%d" % (dbn, exp_db_bytes))
    if db.hexdigest() != exp_db_sha:
        bad.append("db_sha256-mismatch")
    if first[:16] != MAGIC:
        bad.append("not-a-sqlite-header:%r" % first[:16])
    if bad:
        print("VERIFY FAIL reason=%s" % ",".join(bad))
        return 1
    print("VERIFY ok gz_bytes=%d gz_sha256=%s db_bytes=%d db_sha256=%s sqlite_magic=ok"
          % (gzn, gz.hexdigest(), dbn, db.hexdigest()))
    return 0


sys.exit(main())
PYEOF

cat > "$HELP/delete-object.py" <<'PYEOF'
#!/usr/bin/env python3
"""Delete one object from R2. Used only to remove a copy this run proved bad."""
import os
import sys
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 4}),
)
s3.delete_object(Bucket=os.environ["R2_BUCKET"], Key=os.environ["OFF_KEY"])
print("      deleted %s from %s" % (os.environ["OFF_KEY"], os.environ["R2_BUCKET"]))
PYEOF

cat > "$HELP/put-object.py" <<'PYEOF'
#!/usr/bin/env python3
"""Upload one small local file to R2 under OFF_KEY, then read its size back."""
import os
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 4}),
)
with open(os.environ["OFF_FILE"], "rb") as fh:
    s3.put_object(Bucket=os.environ["R2_BUCKET"], Key=os.environ["OFF_KEY"], Body=fh.read())
h = s3.head_object(Bucket=os.environ["R2_BUCKET"], Key=os.environ["OFF_KEY"])
print("PUTOBJ key=%s remote_bytes=%d" % (os.environ["OFF_KEY"], h["ContentLength"]))
PYEOF
chmod 700 "$HELP"/*.py

for h in read-pages.py upload-multipart.py verify-object.py delete-object.py put-object.py; do
  [ -x "$HELP/$h" ] || { echo "FATAL: helper $h missing"; exit 3; }
done

# value of key= in the first line whose first field is <tag>
field() { awk -v t="$2" -v k="$3" '$1==t{for(i=1;i<=NF;i++){n=index($i,"=");if(n>1&&substr($i,1,n-1)==k){print substr($i,n+1);exit}}}' "$1"; }

delete_object() { OFF_KEY="$1" "$PY" "$HELP/delete-object.py"; }

# ── send_sqlite_object <local-db> <remote-key> <label> ──────────────────────────────────────────
# One pipeline, from the database's pages to a completed R2 object. Nothing touches disk.
send_sqlite_object() {
  local src="$1" key="$2" label="$3"
  local rout="$RUNDIR/$label.reader.err" uout="$RUNDIR/$label.upload.out"
  : > "$rout"; : > "$uout"
  echo "[send] $label: $src -> $R2_BUCKET/$key"
  echo "       page-stream | gzip -$GZIP_LEVEL | multipart ${PART_MB} MiB (no intermediate file)"
  "$PY" "$HELP/read-pages.py" "$src" 2>"$rout" \
    | gzip -"$GZIP_LEVEL" -c 2>>"$rout" \
    | OFF_KEY="$key" OFF_PART_MB="$PART_MB" "$PY" "$HELP/upload-multipart.py" >"$uout" 2>>"$rout"
  local ps=("${PIPESTATUS[@]}")
  S_RC="${ps[0]:-1}"; S_GZRC="${ps[1]:-1}"; S_UPRC="${ps[2]:-1}"
  S_READER_BYTES=$(field "$rout" READER bytes)
  S_READER_SHA=$(field "$rout" READER sha256)
  S_PAGE_SIZE=$(field "$rout" READER page_size)
  S_PAGE_COUNT=$(field "$rout" READER pages)
  S_EXPECT=$(field "$rout" READER expected_bytes)
  S_GZ_BYTES=$(field "$uout" UPLOAD gz_bytes)
  S_GZ_SHA=$(field "$uout" UPLOAD gz_sha256)
  S_PARTS=$(field "$uout" UPLOAD parts)
  S_REMOTE=$(field "$uout" UPLOAD remote_bytes)
  S_REMOTE_LM=$(field "$uout" UPLOAD remote_last_modified)
  [ -n "$S_REMOTE" ] || S_REMOTE=0
  if [ "$S_RC" -ne 0 ] || [ "$S_GZRC" -ne 0 ] || [ "$S_UPRC" -ne 0 ]; then
    echo "       PIPELINE FAILED reader_rc=$S_RC gzip_rc=$S_GZRC upload_rc=$S_UPRC"
    sed 's/^/       | /' "$rout" | tail -6
    return 1
  fi
  echo "       reader: pages=$S_PAGE_COUNT page_size=$S_PAGE_SIZE bytes=$S_READER_BYTES"
  echo "       upload: gz_bytes=$S_GZ_BYTES parts=$S_PARTS remote_bytes=$S_REMOTE object_last_modified=$S_REMOTE_LM"
  echo "       source bytes=$S_READER_BYTES  sha256(uncompressed)=$S_READER_SHA"
  echo "       object bytes=$S_GZ_BYTES      sha256(compressed)=$S_GZ_SHA"
  return 0
}

# ═══ [1/5] the financial ledger, from the live file, FIRST ═════════════════════════════════════
# Smallest and most irreplaceable goes first: a few KB against ~7 GB, and a run killed part-way
# must not leave the unrecoverable one unsent behind the expensive one.
LEDGER_SENT=no; LEDGER_USED=""; LEDGER_NOTE=""
for cand in $LEDGER_CANDIDATES; do
  if [ -s "$cand" ] && sqlite3 "file:$cand?mode=ro" 'PRAGMA schema_version;' >/dev/null 2>&1; then
    LEDGER_USED="$cand"; break
  fi
  [ -e "$cand" ] && LEDGER_NOTE="$LEDGER_NOTE $cand($(stat -c '%s' "$cand")B unusable)"
done
echo "[1/5] ledger"
if [ -z "$LEDGER_USED" ]; then
  echo "      NO USABLE LEDGER FOUND. Candidates:"
  for cand in $LEDGER_CANDIDATES; do
    echo "        $cand: $([ -e "$cand" ] && echo "$(stat -c '%s' "$cand") bytes" || echo absent)"
  done
  echo "      The run fails as a result: an absent ledger is a coverage hole, not a success."
  RC=1
else
  echo "      using $LEDGER_USED ($(stat -c '%s' "$LEDGER_USED") bytes)"
  if send_sqlite_object "$LEDGER_USED" "$LEDGER_KEY" "ledger"; then
    LEDGER_SENT=yes
    printf '%s  %s\n' "$S_GZ_SHA" "accounting.db.gz" > "$RUNDIR/accounting.db.gz.sha256"
    OFF_KEY="$LEDGER_KEY.sha256" OFF_FILE="$RUNDIR/accounting.db.gz.sha256" \
      "$PY" "$HELP/put-object.py" || { echo "      ledger sidecar FAILED"; RC=1; }
    rm -f "$RUNDIR/accounting.db.gz.sha256"
  else
    RC=1
  fi
fi

# ═══ [2/5] the company database, streamed straight through ════════════════════════════════════
echo "[2/5] company database ($(( dbsize / 1048576 )) MiB source)"
DB_SENT=no; DB_VERIFIED=skipped
GZ_BYTES=0; DB_SUM=""; REMOTE_BYTES=0; REMOTE_LM=""; PARTS=0; READER_BYTES=0; READER_SHA=""
PAGE_SIZE=0; PAGE_COUNT=0; S_EXPECT=0
T_START=$(date +%s)
if send_sqlite_object "$DB" "$DB_KEY" "db"; then
  READER_BYTES=$S_READER_BYTES; READER_SHA=$S_READER_SHA; PAGE_SIZE=$S_PAGE_SIZE
  PAGE_COUNT=$S_PAGE_COUNT; GZ_BYTES=$S_GZ_BYTES; DB_SUM=$S_GZ_SHA
  REMOTE_BYTES=$S_REMOTE; REMOTE_LM=$S_REMOTE_LM; PARTS=$S_PARTS
  ratio_ok=1
  if [ "${GZ_BYTES:-0}" -lt $(( dbsize / 10 )) ] || [ "${GZ_BYTES:-0}" -gt "$dbsize" ]; then
    echo "      FAIL: compressed $GZ_BYTES B outside 10%-100% of source $dbsize B"; ratio_ok=0
  fi
  if [ "${REMOTE_BYTES:-0}" != "${GZ_BYTES:-0}" ]; then
    echo "      FAIL: object on R2 is $REMOTE_BYTES B, expected $GZ_BYTES B"; ratio_ok=0
  fi
  if [ "${S_EXPECT:-0}" != "${READER_BYTES:-0}" ]; then
    echo "      FAIL: reader expected $S_EXPECT B, streamed $READER_BYTES B"; ratio_ok=0
  fi
  if [ "$ratio_ok" -eq 0 ]; then
    RC=1
    echo "      REMOVING the failing object so a bad copy is not left in place looking good"
    delete_object "$DB_KEY" || true
  else
    DB_SENT=yes
  fi
else
  echo "      nothing was replaced in the bucket (multipart never completed)"
  RC=1
  DB_SENT=no
fi

# ═══ [3/5] read the object back off R2 and prove it ════════════════════════════════════════════
if [ "$DB_SENT" = yes ] && [ "$VERIFY" = "1" ]; then
  echo "[3/5] verify: streaming $DB_KEY back from R2, gunzip in memory, sha256 both ends"
  if OFF_KEY="$DB_KEY" EXP_GZ_SHA="$DB_SUM" EXP_GZ_BYTES="$GZ_BYTES" \
     EXP_DB_SHA="$READER_SHA" EXP_DB_BYTES="$READER_BYTES" \
     "$PY" "$HELP/verify-object.py" 2>&1 | sed 's/^/      /'; then
    DB_VERIFIED=ok
  else
    DB_VERIFIED=failed; RC=1; DB_SENT=no
    echo "      REMOVING the object that failed verification"
    delete_object "$DB_KEY" || true
  fi
elif [ "$DB_SENT" = yes ]; then
  echo "[3/5] verify: SKIPPED (ZABZ_VERIFY_STREAM=0) - the object is UNVERIFIED"
  DB_VERIFIED=skipped
else
  echo "[3/5] verify: not attempted (nothing was sent)"
fi

# ═══ [4/5] the sha256 sidecar, office format, only for an object that passed ═══════════════════
SIDECAR_SENT=no
if [ "$DB_SENT" = yes ] && [ -n "$DB_SUM" ]; then
  echo "[4/5] sidecar $DB_KEY.sha256"
  printf '%s  %s\n' "$DB_SUM" "secretary.db.gz" > "$RUNDIR/secretary.db.gz.sha256"
  if OFF_KEY="$DB_KEY.sha256" OFF_FILE="$RUNDIR/secretary.db.gz.sha256" \
     "$PY" "$HELP/put-object.py" 2>&1 | sed 's/^/      /'; then
    SIDECAR_SENT=yes
  else
    echo "      sidecar upload FAILED"; RC=1
  fi
  rm -f "$RUNDIR/secretary.db.gz.sha256"
fi

# ═══ [5/5] evidence ════════════════════════════════════════════════════════════════════════════
avail_after_kb=$(df -Pk / | awk 'NR==2{print $4}')
T_END=$(date +%s)
echo "[5/5] evidence -> $STATE_DIR/last-run"
{
  echo "finished_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "status=$([ "$RC" -eq 0 ] && echo ok || echo failed)"
  echo "database_sent=$DB_SENT"
  echo "database_verified=$DB_VERIFIED"
  echo "sidecar_sent=$SIDECAR_SENT"
  echo "ledger_sent=$LEDGER_SENT"
  echo "ledger_source=${LEDGER_USED:-none}"
  echo "ledger_candidates_unusable=${LEDGER_NOTE:-none}"
  echo "source=$DB"
  echo "source_bytes=$dbsize"
  echo "page_size=$PAGE_SIZE"
  echo "pages_streamed=$PAGE_COUNT"
  echo "reader_bytes=$READER_BYTES"
  echo "reader_sha256=$READER_SHA"
  echo "gz_bytes=$GZ_BYTES"
  echo "gz_sha256=$DB_SUM"
  echo "parts=$PARTS"
  echo "compressed_ratio_pct=$(( ${GZ_BYTES:-0} * 100 / (dbsize > 0 ? dbsize : 1) ))"
  echo "remote_bytes=$REMOTE_BYTES"
  echo "remote_last_modified=$REMOTE_LM"
  echo "bucket=$R2_BUCKET"
  echo "remote_key=$DB_KEY"
  echo "disk_free_kb_before=$avail_before_kb"
  echo "disk_free_kb_after=$avail_after_kb"
  echo "peak_extra_disk_bytes=0"
  echo "duration_s=$(( T_END - T_START ))"
  echo "host=$(hostname)"
  echo "exit_code=$RC"
} > "$STATE_DIR/last-run.tmp"
mv -f "$STATE_DIR/last-run.tmp" "$STATE_DIR/last-run"
cp -f "$STATE_DIR/last-run" "$STATE_DIR/last-run.$(date -u +%Y%m%dT%H%M%SZ)"
ls -1t "$STATE_DIR"/last-run.* 2>/dev/null | tail -n +31 | xargs -r rm -f
[ "$RC" -eq 0 ] && rm -f "$STATE_DIR/running"

echo "===== done rc=$RC at $(date -u '+%Y-%m-%d %H:%M:%S') in $(( T_END - T_START ))s, disk free before=${avail_before_kb}KiB after=${avail_after_kb}KiB"
exit "$RC"
