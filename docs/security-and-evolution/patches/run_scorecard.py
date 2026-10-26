import json
import sys

sys.path.insert(0, "/opt/company")

from app.services.mashgiach import weekly_report  # noqa: E402

db = "sqlite:////root/authority.db"
res = weekly_report(db)
print("ok:", res.get("ok"))
print("week_start:", res.get("week_start"))
print("departments_scored:", res.get("departments_scored"))
print("flagged:", res.get("flagged_departments"))

rows = [d for d in res.get("department_scores", []) if d.get("findings") is not None]
print()
print(f"{'dept':<32}{'findings':>9}{'fixes':>7}{'esc':>5}")
shown = 0
for d in rows:
    if d.get("findings") or d["dept_id"] == "dept_security":
        print(f"{d['dept_id']:<32}{d['findings']:>9}{d['auto_fixes']:>7}{d['escalations']:>5}")
        shown += 1
if shown == 0:
    print("(no department had a non-zero finding count this week)")

nonzero = sum(1 for d in rows if d.get("findings"))
print()
print("departments with >=1 finding:", nonzero, "of", len(rows))
