"""Final authoritative breakdown from the console export.

Replaces all estimated pricing with the ledger's own observed price x amount.
"""
import collections, csv, json, os

D = r"C:\Users\ezabz\code\_dsh-scale\data\usage-export"


def rows(p):
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


amt = rows(os.path.join(D, "amount-2026-08-18_2026-09-16.csv"))
cost = rows(os.path.join(D, "cost-2026-08-18_2026-09-16.csv"))


def price_of(model, typ):
    """The single off-peak/peak pair observed; return the pair (low, high)."""
    seen = sorted({float(r["price"]) for r in amt
                   if r["model"] == model and r["type"] == typ and r["price"]})
    return seen


print("=== OBSERVED PRICES (USD per token, from the ledger itself) ===")
for m in ("deepseek-flash", "deepseek-v4-pro"):
    for t in ("input_cache_hit_tokens", "input_cache_miss_tokens", "output_tokens"):
        ps = price_of(m, t)
        print(f"  {m:<18} {t:<26} {[f'{p:.9f} = ${p*1e6:.4f}/M' for p in ps]}")

print()
print("=== RATE TIERS, AS THE LEDGER CHARGES THEM ===")
print("  deepseek-flash  off-peak: miss $0.15/M  hit $0.003/M  out $0.60/M")
print("  deepseek-flash  peak    : miss $0.30/M  hit $0.006/M  out $1.20/M")

# ---- THE $54 DAYS ----
print()
print("=== 2026-09-15: THE $54.92 DAY, BY API KEY ===")
agg = collections.defaultdict(lambda: collections.Counter())
for r in amt:
    if r["start_time_iso"][:10] != "2026-09-15":
        continue
    k = r["api_key_name"]
    t = r["type"]
    v = int(r["amount"] or 0)
    if t == "request_count":
        agg[k]["reqs"] += v
    else:
        agg[k][t] += v
        agg[k]["cost"] += float(r["price"] or 0) * v
tot = sum(c["cost"] for c in agg.values())
print(f"{'api key':<24}{'reqs':>8}{'cost$':>9}{'share':>8}{'mean ctx':>12}")
for k, c in sorted(agg.items(), key=lambda x: -x[1]["cost"]):
    mean = (c["input_cache_miss_tokens"] + c["input_cache_hit_tokens"]) / max(c["reqs"], 1)
    print(f"{k:<24}{c['reqs']:>8,}{c['cost']:>9.2f}{100*c['cost']/tot:>7.1f}%"
          f"{mean:>12,.0f}")
print(f"{'TOTAL':<24}{sum(c['reqs'] for c in agg.values()):>8,}{tot:>9.2f}")

print()
print("=== 2026-09-14: THE $44.88 DAY, BY API KEY ===")
agg2 = collections.defaultdict(lambda: collections.Counter())
for r in amt:
    if r["start_time_iso"][:10] != "2026-09-14":
        continue
    k = r["api_key_name"]
    t = r["type"]
    v = int(r["amount"] or 0)
    if t == "request_count":
        agg2[k]["reqs"] += v
    else:
        agg2[k][t] += v
        agg2[k]["cost"] += float(r["price"] or 0) * v
tot2 = sum(c["cost"] for c in agg2.values())
for k, c in sorted(agg2.items(), key=lambda x: -x[1]["cost"]):
    print(f"  {k:<24}{c['reqs']:>8,}{c['cost']:>9.2f}{100*c['cost']/tot2:>7.1f}%")
print(f"  {'TOTAL':<24}{sum(c['reqs'] for c in agg2.values()):>8,}{tot2:>9.2f}")

# ---- the harness keys only ----
print()
print("=== THE TWO HARNESS KEYS, PER DAY ===")
HK = ("deepseek harness", "zabz-tech-harness")
per = collections.defaultdict(lambda: collections.defaultdict(float))
for r in amt:
    if r["api_key_name"] not in HK:
        continue
    per[r["start_time_iso"][:10]][r["api_key_name"]] += float(r["price"] or 0) * int(r["amount"] or 0)
print(f"{'day':<12}{'ZABZ-YOGA':>12}{'ZABZ-TECH':>12}{'both':>10}")
for day in sorted(per):
    a = per[day].get("deepseek harness", 0.0)
    b = per[day].get("zabz-tech-harness", 0.0)
    print(f"{day:<12}{a:>12.2f}{b:>12.2f}{a+b:>10.2f}")

# ---- composition of spend across the whole export ----
print()
print("=== SPEND COMPOSITION ACROSS THE WHOLE EXPORT (all keys) ===")
comp = collections.Counter()
for r in amt:
    if r["type"] == "request_count":
        continue
    comp[r["type"]] += float(r["price"] or 0) * int(r["amount"] or 0)
s = sum(comp.values())
for t, v in comp.most_common():
    print(f"  {t:<26} ${v:8.2f}   {100*v/s:5.1f}%")

print()
print("=== COMPOSITION, THE TWO HARNESS KEYS ONLY (the DSH spend) ===")
comp2 = collections.Counter()
for r in amt:
    if r["api_key_name"] not in HK or r["type"] == "request_count":
        continue
    comp2[r["type"]] += float(r["price"] or 0) * int(r["amount"] or 0)
s2 = sum(comp2.values())
for t, v in comp2.most_common():
    print(f"  {t:<26} ${v:8.2f}   {100*v/s2:5.1f}%")

print()
print("=== IS COST/REQUEST RISING? (harness keys, per day) ===")
pd = collections.defaultdict(lambda: collections.Counter())
for r in amt:
    if r["api_key_name"] not in HK:
        continue
    v = int(r["amount"] or 0)
    if r["type"] == "request_count":
        pd[r["start_time_iso"][:10]]["reqs"] += v
    else:
        pd[r["start_time_iso"][:10]][r["type"]] += v
        pd[r["start_time_iso"][:10]]["cost"] += float(r["price"] or 0) * v
print(f"{'day':<12}{'reqs':>8}{'cost$':>9}{'$/req':>9}{'mean ctx':>12}{'miss%':>8}")
for day in sorted(pd):
    c = pd[day]
    if not c["reqs"]:
        continue
    pin = c["input_cache_miss_tokens"] + c["input_cache_hit_tokens"]
    print(f"{day:<12}{c['reqs']:>8,}{c['cost']:>9.2f}"
          f"{c['cost']/c['reqs']:>9.4f}{pin/max(c['reqs'],1):>12,.0f}"
          f"{100*c['input_cache_miss_tokens']/max(pin,1):>7.2f}%")
