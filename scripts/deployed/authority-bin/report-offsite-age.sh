#!/usr/bin/env bash
# report-offsite-age.sh — tell the VAULT how old the company's real offsite copy is.
#
# WHY THIS EXISTS (2026-10-06, the night it was needed):
#   For twelve hours the outside heartbeat alarmed "there is NO FRESH OFFSITE COPY of
#   the company". It was comparing against a restic repository I had built that same
#   night - which was empty - while the copy the company actually depends on lives in
#   the lpt-authority-backups bucket and was simply going stale (today's daily upload
#   failed when the office lost its network). A monitor that cannot see the thing it is
#   monitoring is not a monitor, it is an opinion.
#
#   The monitor runs OUTSIDE the office, on purpose - it has to survive the office
#   being dark. But it cannot read that bucket. So the office reports the fact to it:
#   one small JSON file on the vault, holding the object's size and its LastModified.
#   The heartbeat then alarms on the AGE OF THE REAL OBJECT, wherever it is read from.
#
# Reads only. Sends one small file. Installed by cron every 30 minutes.
set -uo pipefail

CRED="${CRED:-$HOME/.lpt-r2.env}"
KEY="${KEY:-authority/secretary.db.gz}"
VAULT="${VAULT:-root@2.28.33.58}"
VAULT_KEY="${VAULT_KEY:-$HOME/.ssh/id_ed25519_hetzner}"
VENV_PY="${VENV_PY:-$HOME/personal-secretary-mvp/.venv/bin/python}"
LOG="${LOG:-$HOME/report-offsite-age.log}"

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

if [ ! -f "$CRED" ]; then
  echo "$(ts) MISSING $CRED - cannot read the offsite bucket" >> "$LOG"
  exit 1
fi

# shellcheck disable=SC1090
set -a; . "$CRED"; set +a

JSON=$(
  KEY="$KEY" "$VENV_PY" - <<'PY'
import json, os, sys, datetime

try:
    import boto3
    from botocore.config import Config
except Exception as exc:
    print(json.dumps({"key": os.environ["KEY"], "error": f"no boto3: {exc}"}))
    sys.exit(0)

out = {"key": os.environ["KEY"]}
try:
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    o = s3.head_object(Bucket=os.environ["R2_BUCKET"], Key=os.environ["KEY"])
    lm = o["LastModified"]
    if isinstance(lm, datetime.datetime):
        lm = lm.astimezone(datetime.timezone.utc).isoformat()
    out["bytes"] = o["ContentLength"]
    out["last_modified"] = str(lm)
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"

out["reported_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
out["reported_by"] = os.uname().nodename
print(json.dumps(out))
PY
)

echo "$(ts) $JSON" >> "$LOG"

printf '%s\n' "$JSON" | ssh -i "$VAULT_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=accept-new "$VAULT" \
  'mkdir -p /var/lib/company-offsite && chmod 755 /var/lib/company-offsite && cat > /var/lib/company-offsite/authority-push.json' \
  && echo "$(ts) reported to the vault" >> "$LOG" \
  || echo "$(ts) REPORT FAILED (could not reach the vault)" >> "$LOG"

