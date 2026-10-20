#!/usr/bin/env bash
# text-health-check — the 15-minute safety check of the owner's text channel.
#
# WHY: the office authority ran text-channel-check.sh every 15 minutes; the cloud
# authority had no such job, so the only instrument that proves the text channel is
# clean ran only when somebody remembered (ledger items 97 and 312; owner decision
# owner_decision_queue #489, answered 2026-10-15: "restore it").
#
# WHAT IT DOES: runs /root/bin/text-health.py -- READ-ONLY, it never sends a text --
# captures every line, and writes one JSON status file. The unit exits non-zero on
# any FAIL so `systemctl --failed` is the alarm, not a log nobody reads.
#
# EXIT: 0 all invariants pass | 1 one or more FAIL | 2 could not run the check
#       (missing interpreter or timeout) -- never a silent pass.
set -uo pipefail

STATE="${TEXT_HEALTH_STATE:-/var/lib/text-health}"
PY="${TEXT_HEALTH_PYTHON:-/opt/company/.venv/bin/python}"
CHECK="${TEXT_HEALTH_SCRIPT:-/root/bin/text-health.py}"
LOCK="${TEXT_HEALTH_LOCK:-/run/text-health.lock}"
mkdir -p "$STATE" || exit 2

exec 9>"$LOCK" || exit 2
if ! flock -n 9; then
  printf '%s skip: previous run still holds %s\n' "$(date -u +%FT%TZ)" "$LOCK" >>"$STATE/runs.log"
  exit 0
fi

if [ ! -x "$PY" ]; then
  printf '{"checked_at":"%s","ok":false,"exit_code":2,"result":"interpreter not executable: %s","checks":0,"fail":0}\n' \
    "$(date -u +%FT%TZ)" "$PY" >"$STATE/status.json.tmp"
  mv -f "$STATE/status.json.tmp" "$STATE/status.json"
  printf '%s rc=2 interpreter not executable: %s\n' "$(date -u +%FT%TZ)" "$PY" >>"$STATE/runs.log"
  exit 2
fi

out="$STATE/last-output.tmp"
started=$(date +%s)
timeout 200 "$PY" "$CHECK" >"$out" 2>&1
rc=$?
elapsed=$(( $(date +%s) - started ))
tail -n 200 "$out" >"$STATE/last-output.txt"

result="$(grep -E '^RESULT:' "$out" | tail -1)"
[ -n "$result" ] || result="no RESULT line (rc=$rc)"
checks=$(printf '%s' "$result" | sed -n 's/.*RESULT: \([0-9][0-9]*\) check(s).*/\1/p')
fails=$(printf '%s' "$result" | sed -n 's/.*, \([0-9][0-9]*\) FAIL.*/\1/p')
ok=false
[ "$rc" -eq 0 ] && ok=true
[ "$rc" -eq 124 ] && result="timeout after 200s; $result"

# One atomic JSON write through python3 so quoting can never corrupt the status file.
"$PY" - "$STATE/status.json" "$ok" "$rc" "$checks" "$fails" "$elapsed" "$result" "$out" <<'PYEOF'
import datetime, json, os, socket, sys
path, ok, rc, checks, fails, elapsed, result, out = sys.argv[1:]
try:
    body = open(out, encoding="utf-8", errors="replace").read().splitlines()
except OSError:
    body = []
failed = [ln.split("  ", 1)[1] for ln in body if ln.startswith("FAIL")]
doc = {
    "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "host": socket.gethostname(),
    "ok": ok == "true",
    "exit_code": int(rc),
    "result": result,
    "checks": int(checks or 0),
    "fail": int(fails or 0),
    "failed_checks": failed,
    "duration_s": int(elapsed),
    "stale_after_minutes": 20,
    "cmd": "%s %s" % (
        os.environ.get("TEXT_HEALTH_PYTHON", "/opt/company/.venv/bin/python"),
        os.environ.get("TEXT_HEALTH_SCRIPT", "/root/bin/text-health.py"),
    ),
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
PYEOF

printf '%s rc=%s %s\n' "$(date -u +%FT%TZ)" "$rc" "$result" >>"$STATE/runs.log"
# Keep the run log bounded; this is an alarm ledger, not an archive.
tail -n 2000 "$STATE/runs.log" >"$STATE/runs.log.tmp" && mv -f "$STATE/runs.log.tmp" "$STATE/runs.log"

case "$rc" in
  0) exit 0 ;;
  124) exit 2 ;;
  *) exit 1 ;;
esac
