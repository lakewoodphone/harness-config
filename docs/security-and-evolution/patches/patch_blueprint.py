#!/usr/bin/env python3
"""Complete the dept_security blueprint entry.

Every other department carries hierarchy_layer / cost_tier / model_tier; the
dept_security entry added 2026-10-25 does not. They degrade to defaults
("department"/"fast"/"fast"), which is why the omission was invisible — but
`reports_to` is load-bearing: `_blueprint_required_children()` and
`bootstrap_company()` both read it to decide the parent, and
`reconcile_blueprint_tree()` reads it too.
"""
import io
import sys

PATH = "app/company_blueprint.py"
src = io.open(PATH, encoding="utf-8").read()

if '"agent_id": "dept_security"' not in src:
    print("FATAL: dept_security entry not found")
    sys.exit(10)

if '"reports_to": "orchestrator"' in src.split('"agent_id": "dept_security"', 1)[1][:1200]:
    print("ALREADY PATCHED - no change")
    sys.exit(0)

old = '''        "agent_id": "dept_security",
        "name": "Security",
        "role": "VP of Security",
'''
new = '''        "agent_id": "dept_security",
        "name": "Security",
        "role": "VP of Security",
        "hierarchy_layer": "vp",
        "reports_to": "orchestrator",
        "cost_tier": "smart",
        "model_tier": "smart",
        "review_gate": "Escalate anything that touches money, customers or the company database",
        "decision_scope": (
            "Measure and patch exposure on writable hosts; rotate only credentials "
            "the system itself generated; never touch the frozen office box."
        ),
'''

if old not in src:
    print("FATAL: exact entry header not found")
    sys.exit(11)

src = src.replace(old, new, 1)
io.open(PATH + ".new", "w", encoding="utf-8", newline="\n").write(src)
print("wrote %s.new" % PATH)
