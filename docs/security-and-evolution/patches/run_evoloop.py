import sys

sys.path.insert(0, "/opt/company")

from app.services.evolution_loop import close_the_loop  # noqa: E402

res = close_the_loop("sqlite:////root/authority.db")
for k in ("ok", "backfilled", "measured", "passed", "failed", "metric"):
    print(f"{k:<12}: {res.get(k)}")
if res.get("errors"):
    print("errors      :", res["errors"])
