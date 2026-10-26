import sys

sys.path.insert(0, "/opt/company")

from app.services.stagnation_detector import detect  # noqa: E402

res = detect("sqlite:////root/authority.db")
print("departments_checked:", res["departments_checked"])
print("silent             :", len(res["silent"]))
print("idle               :", len(res["idle"]))
print("findings_logged    :", res["findings_logged"])
print()
for d in res["silent"]:
    print("  SILENT", d["department"], "last_tick=", d["last_tick"])
for d in res["idle"]:
    print("  IDLE  ", d["department"], "ticks=", d["ticks"])
if res.get("errors"):
    print("errors:", res["errors"])
