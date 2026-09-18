"""Per-session cost for one UTC day, using the price table that reconciles to $54."""
import collections, datetime, json, sys

HP, MP, OP = 0.030, 0.30, 1.20          # per 1M tokens
DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-09-15"

d = json.load(open(r"C:\Users\ezabz\code\_dsh-scale\data\usage-yoga.json", encoding="utf-8"))
per = collections.defaultdict(lambda: collections.Counter())
for ts, sid, model, miss, hit, out in d["events"]:
    if not ts.startswith(DAY):
        continue
    c = per[sid]
    c["n"] += 1
    c["miss"] += miss
    c["hit"] += hit
    c["out"] += out

rows = []
for sid, c in per.items():
    cost = (c["miss"] * MP + c["hit"] * HP + c["out"] * OP) / 1e6
    rows.append((cost, sid, c))
rows.sort(reverse=True)
tot = sum(r[0] for r in rows)
print(f"=== {DAY} (UTC) — per-session cost at ${HP}/{MP}/${OP} per 1M ===")
print(f"total ${tot:.2f}   sessions with traffic: {len(rows)}")
print()
print(f"{'cost$':>8}{'reqs':>7}{'miss':>12}{'hit':>14}{'out':>10}{'mean prompt':>13}  session")
run = 0.0
for cost, sid, c in rows:
    run += cost
    prompt = c["miss"] + c["hit"]
    mean = prompt / c["n"] if c["n"] else 0
    print(f"{cost:>8.2f}{c['n']:>7}{c['miss']:>12,}{c['hit']:>14,}{c['out']:>10,}"
          f"{mean:>13,.0f}  {sid[:44]}")
print()
cum = 0.0
for i, (cost, sid, c) in enumerate(rows, 1):
    cum += cost
    if i in (1, 3, 5, 10, 20, len(rows)):
        print(f"  top {i:>3} sessions = ${cum:7.2f}  ({100*cum/tot:5.1f}% of the day)")

print()
print("=== concentration: how many sessions make 80% of the day ===")
cum = 0.0
for i, (cost, sid, c) in enumerate(rows, 1):
    cum += cost
    if cum >= 0.8 * tot:
        print(f"  {i} of {len(rows)} sessions = 80% of spend")
        break

print()
print("=== mean prompt size at which cost accrues (whole day) ===")
buckets = collections.Counter()
for cost, sid, c in rows:
    p = (c["miss"] + c["hit"]) / c["n"] if c["n"] else 0
    b = int(p // 100000) * 100000
    buckets[b] += c["n"]
for b in sorted(buckets):
    print(f"  mean prompt {b/1000:>5.0f}k-{(b+100000)/1000:>5.0f}k : {buckets[b]:>6,} requests")
