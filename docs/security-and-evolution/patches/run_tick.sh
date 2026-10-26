#!/usr/bin/env bash
set -uo pipefail
echo "=== running company_tick ==="
curl -s -X POST 'http://127.0.0.1:8002/company/tick' -o /tmp/tick2.json -w 'http=%{http_code}\n'
python3 - <<'PY'
import json
try:
    d = json.load(open('/tmp/tick2.json'))
except Exception as e:
    print("could not parse tick response:", e)
    raise SystemExit(0)

print("agents_ticked        :", d.get("agents_ticked"))
print("departments_skipped  :", d.get("departments_skipped"))
defd = d.get("scheduled_deferred") or []
ids = [x.get("agent_id") for x in defd]
print("deferred count       :", len(ids))
print("dept_security deferred?:", "dept_security" in ids)
print()
print("deferred agents:", ", ".join(sorted(i for i in ids if i)))
PY
