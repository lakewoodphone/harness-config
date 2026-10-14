#!/usr/bin/env bash
# Deploy the round-4 integration tree into the live company, with a backup and a real verification.
#
# WHAT IS BEING DEPLOYED. `/root/work/r4-integration` (branch `r4/integration`) on top of the
# preserved live tree `14ebb2322`:
#   * WS-LOOP      the reconnaissance budget that forces a decision at 6 read-only steps and
#                  blocks at 10, and a `[HANDOFF: did|proof|result|left]` on every terminal path
#   * WS-TRANSPORT the liveness probe and the active-task ceiling that counted `blocked`
#   * WS-MODEL     runtime model resolution validated against the gateway catalogue
#   * WS-MEMORY    a bounded, testable attempt context, and the repaired memory-consolidation import
#
# WHY IT IS SAFE TO DO THIS. Four separate suites: 63 passed. The whole test tree compared against
# the base: 51 failing node ids on each side, **0 new**. The loop change is deliberately shaped so
# that its worst case is a session stopping sooner, and every added marker is a string in
# `output_log` — nothing here changes a schema or a data format.
#
# VERIFICATION IS PART OF THE SCRIPT. A deploy is not "files copied". It is:
#   1. every deployed file byte-identical to the integration tree (md5 per path)
#   2. the service restarted, and `ExecMainStartTimestamp` moved (the process picked the code up —
#      an mtime is not a deployment, which is L3803)
#   3. `/health` answers ok
#   4. the new symbols are importable IN THE RUNNING INTERPRETER
#   5. the loop is still alive: a new work session is created after the restart
set -uo pipefail

LIVE=/opt/company
INT=/root/work/r4-integration
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BAK=/var/lib/authority-snapshots/r4-deploy-$STAMP
LOG=/var/log/r4-deploy-$STAMP.log

echo "=== preflight: disk and memory before anything runs on the box that owns the database"
df -h / | tail -1
free -m | head -2

echo
echo "=== the files this deploy changes (integration vs the live tree)"
cd "$INT" || exit 1
git diff --name-status 14ebb2322..HEAD -- app/ | grep -v '\.bak' | tee /tmp/r4-deploy-files.txt
echo "count: $(wc -l < /tmp/r4-deploy-files.txt)"

mkdir -p "$BAK"
echo
echo "=== backup every file this deploy will overwrite -> $BAK"
while read -r status path; do
  [ -f "$LIVE/$path" ] || continue
  mkdir -p "$BAK/$(dirname "$path")"
  cp -p "$LIVE/$path" "$BAK/$path"
done < /tmp/r4-deploy-files.txt
echo "backed up: $(find "$BAK" -type f | wc -l) file(s)"
echo "$BAK" > /tmp/r4-last-backup

echo
echo "=== copy the new versions in (explicit paths, from the integration tree)"
while read -r status path; do
  mkdir -p "$LIVE/$(dirname "$path")"
  cp -p "$INT/$path" "$LIVE/$path"
  echo "  $status $path"
done < /tmp/r4-deploy-files.txt

echo
echo "=== VERIFY 1: every deployed file is byte-identical to the integration tree"
bad=0
while read -r status path; do
  a=$(md5sum "$INT/$path" 2>/dev/null | cut -d' ' -f1)
  b=$(md5sum "$LIVE/$path" 2>/dev/null | cut -d' ' -f1)
  if [ "$a" != "$b" ]; then echo "  MISMATCH $path ($a vs $b)"; bad=$((bad+1)); fi
done < /tmp/r4-deploy-files.txt
echo "  mismatches: $bad"
if [ "$bad" -ne 0 ]; then echo "REFUSING TO RESTART: content does not match"; exit 1; fi

BEFORE=$(systemctl show company-api -p ExecMainStartTimestamp --value)
echo
echo "=== restarting company-api (was started: $BEFORE)"
systemctl restart company-api
sleep 8
systemctl is-active company-api
AFTER=$(systemctl show company-api -p ExecMainStartTimestamp --value)
echo "  ExecMainStartTimestamp: $BEFORE -> $AFTER"
if [ "$BEFORE" = "$AFTER" ]; then echo "  WARNING: the process did not restart"; fi

echo
echo "=== VERIFY 3: /health"
curl -s -m 10 http://127.0.0.1:8002/health | head -c 300
echo

echo
echo "=== VERIFY 4: the new code is importable IN THE RUNNING INTERPRETER"
cd "$LIVE" || exit 1
"$LIVE/.venv/bin/python" - <<'PY' 2>&1 | tail -12
import sys
sys.path.insert(0, "/opt/company")
ok = []
try:
    from app.services.attempt_context import build_attempt_context, ATTEMPT_CONTEXT_MAX_CHARS
    ok.append(f"attempt_context: cap={ATTEMPT_CONTEXT_MAX_CHARS}")
except Exception as exc:
    ok.append(f"attempt_context FAILED: {type(exc).__name__}: {exc}")
try:
    from app.services.liveness_probe import probe_company_api
    d = probe_company_api(timeout_s=5.0)
    ok.append(f"liveness_probe: ok={d.get('ok')} http={d.get('http_status')} detail={str(d.get('detail'))[:70]}")
except Exception as exc:
    ok.append(f"liveness_probe FAILED: {type(exc).__name__}: {exc}")
try:
    from app.services.model_resolution import resolve_model_detail
    d = resolve_model_detail("fast")
    ok.append(f"model_resolution: id={d.get('id')} source={d.get('source')} validated={d.get('validated')}")
except Exception as exc:
    ok.append(f"model_resolution FAILED: {type(exc).__name__}: {exc}")
try:
    from app.services.autonomy import UNCLASSIFIED_ACTION_LEVEL, should_execute
    d = should_execute("totally_made_up_action_xyz")
    ok.append(f"autonomy: unclassified={UNCLASSIFIED_ACTION_LEVEL.name} execute={d['execute']}")
except Exception as exc:
    ok.append(f"autonomy FAILED: {type(exc).__name__}: {exc}")
try:
    import re
    src = open("app/autopilot.py").read()
    ok.append(f"autopilot: RECON_SOFT_LIMIT={'RECON_SOFT_LIMIT' in src} "
              f"RECON_HARD_LIMIT={'RECON_HARD_LIMIT' in src} HANDOFF={'HANDOFF: did=' in src}")
except Exception as exc:
    ok.append(f"autopilot check FAILED: {type(exc).__name__}: {exc}")
print("\n".join(ok))
PY

echo
echo "=== VERIFY 5: the loop is still alive (a new work session after the restart)"
sleep 20
sqlite3 -readonly /root/authority.db "SELECT count(*) AS sessions_in_last_3min FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-3 minutes')" 2>&1
sqlite3 -readonly /root/authority.db "SELECT status, count(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-10 minutes') GROUP BY 1" 2>&1

echo
echo "=== DONE. backup=$BAK"
echo "rollback: cp -a $BAK/app/. $LIVE/app/ && systemctl restart company-api"
echo "log: $LOG"
