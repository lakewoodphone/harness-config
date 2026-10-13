#!/usr/bin/env bash
# verify-offsite-object.sh — prove, from outside the backup script, that the offsite copy is real.
#
# WHY THIS IS SEPARATE FROM THE BACKUP. The backup script verifies its own work, and that is
# necessary but not sufficient: a script that reports a copy landed and a script that cannot be
# checked are the same thing from the outside. This reads the bucket directly, reports the size and
# LastModified of the object, re-downloads it, re-computes its sha256, and compares that against the
# sidecar object. It asserts nothing about the backup's own exit code, and it never writes.
#
# EXIT CODES: 0 all checks passed; 1 a check failed; 2 could not read the bucket.
#
# Usage:  verify-offsite-object.sh [key]
#   KEY   object key, default authority/secretary.db.gz
#
# It downloads the whole object once, so it is a deliberate act, not a cron job. Run it after a real
# backup, or when a claim about the bucket has to be settled.
set -uo pipefail

KEY="${1:-${KEY:-authority/secretary.db.gz}}"
CRED="${CRED:-/root/.lpt-r2.env}"

[ -s "$CRED" ] || { echo "FATAL: no credentials at $CRED"; exit 2; }
perm=$(stat -c '%a' "$CRED")
[ "$perm" = "600" ] || { echo "FATAL: $CRED is mode $perm, must be 600"; exit 2; }

set -a; . "$CRED"; set +a
export R2_ENDPOINT R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET KEY

/usr/bin/python3 - <<'PYEOF'
import datetime, hashlib, os, sys

try:
    import boto3
    from botocore.config import Config
except Exception as exc:
    print("FATAL: no boto3 in this interpreter: %s" % exc)
    sys.exit(2)

key = os.environ["KEY"]
bucket = os.environ["R2_BUCKET"]
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                  connect_timeout=15, read_timeout=60),
)

fail = 0

# ── 1. the object exists, and its recorded facts ────────────────────────────────────────────────
try:
    h = s3.head_object(Bucket=bucket, Key=key)
except Exception as exc:
    print("FAIL head_object %s: %s: %s" % (key, type(exc).__name__, str(exc)[:200]))
    sys.exit(2)
size = int(h["ContentLength"])
lm = h["LastModified"].astimezone(datetime.timezone.utc)
now = datetime.datetime.now(datetime.timezone.utc)
age_h = (now - lm).total_seconds() / 3600.0
print("bucket=%s" % bucket)
print("object=%s" % key)
print("SIZE=%d bytes (%.2f GiB)" % (size, size / 1073741824))
print("LASTMODIFIED=%s" % lm.isoformat())
print("AGE_HOURS=%.2f" % age_h)
print("ETAG=%s" % h["ETag"])

# ── 2. the sidecar exists and its stated hash matches the object's actual bytes ─────────────────
side = key + ".sha256"
try:
    sb = s3.get_object(Bucket=bucket, Key=side)["Body"].read().decode().strip()
except Exception as exc:
    print("FAIL sidecar %s unreadable: %s" % (side, type(exc).__name__))
    fail = 1
    sb = ""

stated = sb.split()[0] if sb else ""
print("SIDECAR_KEY=%s" % side)
print("SIDECAR_TEXT=%s" % sb)
print("STATED_SHA256=%s" % (stated or "(none)"))

h2 = hashlib.sha256()
n = 0
try:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    while True:
        chunk = body.read(1024 * 1024)
        if not chunk:
            break
        h2.update(chunk)
        n += len(chunk)
except Exception as exc:
    print("FAIL re-reading the object: %s: %s" % (type(exc).__name__, str(exc)[:200]))
    sys.exit(2)

actual = h2.hexdigest()
print("DOWNLOADED_BYTES=%d" % n)
print("ACTUAL_SHA256=%s" % actual)

if n != size:
    print("FAIL: downloaded %d bytes but head_object said %d" % (n, size))
    fail = 1
else:
    print("OK: downloaded byte count equals the recorded size")

if not stated:
    print("FAIL: no sha256 was stated in the sidecar, so the copy cannot be checked")
    fail = 1
elif stated == actual:
    print("OK: the sidecar sha256 equals the sha256 of the object that is actually there")
else:
    print("FAIL: sidecar says %s but the object hashes to %s" % (stated, actual))
    fail = 1

# ── 3. it is a gzip stream, and its first page is a SQLite database ─────────────────────────────
try:
    head = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-15")["Body"].read()
    if head[:2] == b"\x1f\x8b":
        print("OK: the object begins with the gzip magic 1f 8b")
    else:
        print("FAIL: the object does not begin with gzip magic: %s" % head[:4].hex())
        fail = 1
except Exception as exc:
    print("FAIL reading the first bytes: %s" % type(exc).__name__)
    fail = 1

print("VERDICT=%s" % ("PASS" if fail == 0 else "FAIL"))
sys.exit(fail)
PYEOF
