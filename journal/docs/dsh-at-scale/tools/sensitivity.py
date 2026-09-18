"""Price the same measured token totals under every candidate DeepSeek price table.

Prices are USD per 1M tokens. All candidate tables are stated explicitly so the
result can be re-derived when the official page is re-read.
"""
import json

d = json.load(open(r"C:\Users\ezabz\code\_dsh-scale\data\usage-yoga.json", encoding="utf-8"))
by_day = d["by_day"]


def tot(days):
    c = {}
    for day in days:
        for k, v in by_day[day].items():
            c[k] = c.get(k, 0) + v
    return c


RECENT = ["2026-09-14", "2026-09-15", "2026-09-16"]     # last 3 days with traffic
D15 = ["2026-09-15"]

# (label, cache-hit price, cache-miss price, output price)
TABLES = [
    ("A  secretary app/pricing.py deepseek-flash OFF-PEAK (0.15/0.60, hit@10%)",
     0.015, 0.15, 0.60),
    ("B  secretary app/pricing.py deepseek-flash PEAK (0.30/1.20, hit@10%)",
     0.030, 0.30, 1.20),
    ("C  DeepSeek V3.2-style published table (0.28/0.42, hit 0.028)",
     0.028, 0.28, 0.42),
    ("D  cache-hit at 20% of miss (0.30/1.20 miss, hit 0.06)",
     0.060, 0.30, 1.20),
    ("E  pessimistic: cache-hit at 50% of miss (0.30/1.20 miss, hit 0.15)",
     0.150, 0.30, 1.20),
    ("F  no caching at all would cost, at 0.30 miss / 1.20 out",
     0.300, 0.30, 1.20),
]


def cost(c, hit_p, miss_p, out_p):
    return (c.get("miss", 0) * miss_p + c.get("hit", 0) * hit_p
            + c.get("out", 0) * out_p) / 1_000_000.0


print("MEASURED TOTALS (source: C:\\Users\\ezabz\\.dsh\\sessions, ZABZ-YOGA)")
for label, days in (("2026-09-15", D15), ("last 3 days 09-14..09-16", RECENT)):
    c = tot(days)
    print(f"  {label:<28} reqs={c.get('n',0):>6,}  miss={c['miss']:>11,}  "
          f"hit={c['hit']:>13,}  out={c['out']:>10,}")
allc = tot(sorted(by_day))
print(f"  {'ALL 09-10..09-16':<28} reqs={allc.get('n',0):>6,}  miss={allc['miss']:>11,}  "
      f"hit={allc['hit']:>13,}  out={allc['out']:>10,}")

print()
print("=== COST OF EACH PERIOD UNDER EACH CANDIDATE PRICE TABLE ===")
print(f"{'price table':<62}{'09-15':>10}{'3 days':>10}{'all 6d':>10}")
c15, c3, c6 = tot(D15), tot(RECENT), allc
for label, hp, mp, op in TABLES:
    print(f"{label:<62}{cost(c15,hp,mp,op):>10.2f}{cost(c3,hp,mp,op):>10.2f}"
          f"{cost(c6,hp,mp,op):>10.2f}")

print()
print("=== WHY: TOKEN SHARE VS COST SHARE (table B) ===")
hp, mp, op = 0.030, 0.30, 1.20
for name, days in (("2026-09-15", D15), ("all 6d", None)):
    c = tot(days) if days else allc
    inb = c["miss"] + c["hit"]
    m = c["miss"] * mp / 1e6
    h = c["hit"] * hp / 1e6
    o = c["out"] * op / 1e6
    s = m + h + o
    print(f"  {name}:")
    print(f"    cache-MISS input  {c['miss']:>13,} tok  {100*c['miss']/inb:5.2f}% of prompt  "
          f"-> ${m:7.2f}  {100*m/s:5.1f}% of cost")
    print(f"    cache-HIT  input  {c['hit']:>13,} tok  {100*c['hit']/inb:5.2f}% of prompt  "
          f"-> ${h:7.2f}  {100*h/s:5.1f}% of cost")
    print(f"    OUTPUT            {c['out']:>13,} tok                        "
          f"-> ${o:7.2f}  {100*o/s:5.1f}% of cost")

print()
print("=== THE STRUCTURAL MULTIPLIER ===")
c6 = allc
reqs = c6.get("n", 0)
prompt_tok = c6["miss"] + c6["hit"]
print(f"  requests            : {reqs:,}")
print(f"  prompt tokens sent   : {prompt_tok:,}")
print(f"  mean prompt/request  : {prompt_tok/reqs:,.0f} tokens")
print(f"  => each request re-sends the whole conversation; the bill is"
      f" ~(steps x mean context)")
print()
print("=== IF MEAN CONTEXT WERE HALVED (same step count) ===")
for frac, label in ((0.5, "half"), (0.25, "quarter")):
    saved = c6["hit"] * (1 - frac)
    print(f"  {label:<8} cache-hit tokens {c6['hit']:,} -> {int(c6['hit']*frac):,}  "
          f"saving ${saved*hp/1e6:6.2f} at ${hp}/M  (of ${c6['hit']*hp/1e6:.2f})")
