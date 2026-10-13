#!/usr/bin/env bash
# verify-offsite-backup.sh -- prove the AUTHORITY's offsite DB copy is FRESH and OPENABLE.
#
# Run it ON secratary-cloud (it reads /var/lib/authority-backup/last-run, the R2 bucket
# credential /root/.lpt-r2.env, and the box's free space).
#
# WHY IT IS WRITTEN THIS WAY (docs/mesh/000 SYSTEMS-REGISTER "Trap 7": byte-count
# verification proves the TRANSPORT, never the CONTENT)
#   `last-run` records `remote_bytes` and a `gz_sha256`, and the freshness monitor
#   (report-offsite-age.sh) proves the object's LastModified by HEAD. None of that proves
#   the bytes restore. This script therefore:
#     1. reads the recorded run,
#     2. asks the bucket itself for the newest object's size + LastModified (independent
#        of the recorded value),
#     3. pulls a byte range of the object and DECOMPRESSES it, checking the first 16 bytes
#        are the SQLite magic `SQLite format 3\0`,
#     4. prints the exact arithmetic of a full `PRAGMA integrity_check`, which needs the
#        object's uncompressed size on local disk.
#
#   It is READ-ONLY. It never deletes, never uploads, never writes the bucket.
#
# USAGE
#   verify-offsite-backup.sh [--help]
set -euo pipefail

usage() {
  cat <<'U'
verify-offsite-backup.sh -- prove the authority DB offsite copy is fresh AND openable.

USAGE
  verify-offsite-backup.sh          # read-only verification, prints a report
  verify-offsite-backup.sh --help   # this text

READS
  /var/lib/authority-backup/last-run   the last backup's own record
  /root/.lpt-r2.env                    bucket-scoped R2 credential (never printed)
  <bucket>/authority/secretary.db.gz(+.sha256)

EXIT
  0  verification completed (see the printed verdict; a stale object is a finding, not a crash)
  1  environment error (no credential, no boto3, no last-run)
  2  bad usage
U
}

case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  "") : ;;
  *) echo "verify-offsite-backup.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac
[ "$#" -gt 1 ] && { echo "verify-offsite-backup.sh: too many arguments" >&2; exit 2; }

LAST=/var/lib/authority-backup/last-run
CRED=/root/.lpt-r2.env
[ -f "$LAST" ] || { echo "no $LAST -- CANNOT ASK" >&2; exit 1; }
[ -f "$CRED" ] || { echo "no $CRED -- CANNOT ASK" >&2; exit 1; }

PY=""
for p in /usr/bin/python3 python3; do
  command -v "$p" >/dev/null 2>&1 || continue
  "$p" -c 'import boto3' 2>/dev/null && { PY=$p; break; }
done
[ -n "$PY" ] || { echo "no python3 with boto3 -- CANNOT ASK" >&2; exit 1; }

echo "=== recorded run ($LAST) ==="
grep -E '^(finished_at|status|database_sent|database_verified|source_bytes|reader_sha256|gz_bytes|gz_sha256|bucket|remote_key|remote_bytes|remote_last_modified)=' "$LAST"

echo
echo "=== bucket, read independently ==="
set -a; . "$CRED"; set +a
PY="$PY" "$PY" - <<'PY'
import io, gzip, os, datetime
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4"),
)
bucket = os.environ["R2_BUCKET"]
key = "authority/secretary.db.gz"
now = datetime.datetime.now(datetime.timezone.utc)

objs = s3.list_objects_v2(Bucket=bucket, Prefix="authority/").get("Contents", [])
for o in objs:
    age_h = (now - o["LastModified"]).total_seconds() / 3600.0
    print(f'OBJ {o["Key"]} bytes={o["Size"]} last_modified={o["LastModified"].isoformat()} age_h={age_h:.2f} etag={o.get("ETag")}')

head = s3.head_object(Bucket=bucket, Key=key)
age_h = (now - head["LastModified"]).total_seconds() / 3600.0
print(f"NEWEST-FRESHNESS: age={age_h:.2f}h (a DAILY timer; >26h means a missed run)")

# openability: a byte range that decompresses to the SQLite header proves the object is a
# real gzip stream carrying a real SQLite database -- not that every page is intact.
r = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-262143")
d = gzip.GzipFile(fileobj=io.BytesIO(r["Body"].read())).read(16)
print("OPENABLE: SQLite-magic-first-16-bytes =", d == b"SQLite format 3\x00", d[:15])

# arithmetic for a full content check
st = os.statvfs("/")
free = st.f_bavail * st.f_frsize
gz = head["ContentLength"]
# last-run's compressed ratio was 26 %; uncompressed ~= reader_bytes. Read it if present.
reader_bytes = None
with open("/var/lib/authority-backup/last-run") as fh:
    for line in fh:
        if line.startswith("reader_bytes="):
            reader_bytes = int(line.split("=", 1)[1])
        if line.startswith("gz_bytes="):
            gz = int(line.split("=", 1)[1])
est = reader_bytes if reader_bytes else int(gz / 0.26)
print(f"CONTENT-CHECK-ARITHMETIC: free={free} bytes; uncompressed={est} bytes; "
      f"fits={'yes' if free > est + gz else 'NO'}")
if free <= est + gz:
    print("CONTENT-CHECK: COULD NOT ASK -- a materialised PRAGMA integrity_check cannot fit. "
          "reason=free space < (uncompressed db + gz object). Reclaim or verify off-box.")
PY

echo
echo "=== verdict ==="
echo "FRESH  : compare NEWEST-FRESHNESS age against the timer cadence above."
echo "OPENABLE: SQLite-magic-first-16-bytes true is a partial proof (gzip+SQLite header),"
echo "          NOT a full PRAGMA integrity_check; the arithmetic line says whether that fits."
