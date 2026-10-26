import json

p = "/opt/company/data/agent_identities.json"
d = json.load(open(p))
agents = d.get("agents", d)

orc = agents.get("orchestrator", {})
kids = (orc.get("hierarchy") or {}).get("children") or []
print("orchestrator.children count:", len(kids))
print("dept_security in orchestrator.children:", "dept_security" in kids)

sec = agents.get("dept_security", {})
h = sec.get("hierarchy") or {}
dep = sec.get("department") or {}
print()
print("dept_security.parent_agent_id :", h.get("parent_agent_id"))
print("dept_security.role            :", h.get("role"))
print("dept_security.status          :", sec.get("status"))
print("dept_security.name            :", sec.get("name"))
print("department.department_name    :", dep.get("department_name"))
print("department.parent_department  :", dep.get("parent_department_id"))
print("department.status             :", dep.get("status"))
print("identity_core.mission[:90]    :", (sec.get("identity_core") or {}).get("mission", "")[:90])

# Simulate walk_agent_tree's BFS over hierarchy.children only.
BFS_MAX = 6
queue = [("orchestrator", 0)]
visited = set()
order = []
while queue:
    aid, depth = queue.pop(0)
    if aid in visited or depth > BFS_MAX:
        continue
    visited.add(aid)
    rec = agents.get(aid)
    if not isinstance(rec, dict):
        continue
    order.append((aid, depth))
    for c in ((rec.get("hierarchy") or {}).get("children") or []):
        if c not in visited:
            queue.append((c, depth + 1))

ids = [a for a, _ in order]
print()
print("walk_agent_tree reaches", len(ids), "agents")
print("dept_security reached by the tick walk:", "dept_security" in ids)
