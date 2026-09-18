"""Reconcile the local DSH session-log measurement against the console ledger.

Local measurement  : ~/.dsh/sessions on ZABZ-YOGA, parsed from data.usage
Authoritative      : the DeepSeek console export, by api_key_name

Pricing applied is the OBSERVED price from the export itself, not the published page,
because the export shows two rate tiers (0.15/0.30 miss, 0.003/0.006 hit, 0.60/1.20 out
for deepseek-flash: off-peak and peak).
"""
import collections, csv, json, os

D = r"C:\Users\ezabz\code\_dsh-scale\data\usage-export"


def rows(p):
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


amt = rows(os.path.join(D, "amount-2026-08-18_2026-09-16.csv"))

# ---- authoritative cost per key, using price x amount ----
key_cost = collections.defaultdict(float)
key_tok = collections.defaultdict(collections.Counter)
key_day_cost = collections.defaultdict(lambda: collections.defaultdict(float))
for r in amt:
    k = r["api_key_name"]
    try:
        p = float(r["price"] or 0)
    except ValueError:
        p = 0.0
    v = int(r["amount"] or 0)
    key_cost[k] += p * v
    key_tok[k][r["type"]] += v
    if r["type"] != "request_count":
        key_day_cost[k][r["start_time_iso"][:10]] += p * v

print("=== AUTHORITATIVE COST, ALL-TIME IN EXPORT (8/18-9/16) ===")
for k, v in sorted(key_cost.items(), key=lambda x: -x[1]):
    print(f"  {k:<24} ${v:8.2f}")

print("\n=== 'deepseek harness' (ZABZ-YOGA) COST PER DAY ===")
for d in sorted(key_day_cost["deepseek harness"]):
    print(f"  {d}  ${key_day_cost['deepseek harness'][d]:8.2f}")

# ---- local measurement ----
d = json.load(open(r"C:\Users\ezabz\code\_dsh-scale\data\usage-yoga.json", encoding="utf-8"))
loc = collections.defaultdict(collections.Counter)
for ts, sid, model, miss, hit, out in d["events"]:
    loc[ts[:10]]["miss"] += miss
    loc[ts[:10]]["hit"] += hit
    loc[ts[:10]]["out"] += out
    loc[ts[:10]]["n"] += 1

print("\n=== RECONCILIATION: local ZABZ-YOGA tokens vs ledger 'deepseek harness' ===")
print(f"{'day':<12}{'local miss':>14}{'ledger miss':>14}{'local hit':>16}"
      f"{'ledger hit':>16}{'local out':>12}{'ledger out':>12}")
for day in sorted(set(list(loc) + list(key_day_cost["deepseek harness"]))):
    l = loc.get(day, collections.Counter())
    print(f"{day:<12}{l['miss']:>14,}{'':>14}{l['hit']:>16,}{'':>16}"
          f"{l['out']:>12,}{'':>12}   (local)")

print("\n  ledger per-day, tokens:")
for day in sorted(key_day_cost["deepseek harness"]):
    print(f"    {day}  ${key_day_cost['deepseek harness'][day]:8.2f}")

# ledger tokens per day for this key
ld = collections.defaultdict(collections.Counter)
for r in amt:
    if r["api_key_name"] != "deepseek harness":
        continue
    ld[r["start_time_iso"][:10]][r["type"]] += int(r["amount"] or 0)

print("\n=== SIDE BY SIDE, tokens, 'deepseek harness' only ===")
print(f"{'day':<12}{'L-miss':>14}{'X-miss':>14}{'L-hit':>16}{'X-hit':>16}"
      f"{'L-out':>12}{'X-out':>12}")
for day in sorted(set(list(loc) + list(ld))):
    l = loc.get(day, collections.Counter())
    x = ld.get(day, collections.Counter())
    print(f"{day:<12}{l['miss']:>14,}{x['input_cache_miss_tokens']:>14,}"
          f"{l['hit']:>16,}{x['input_cache_hit_tokens']:>16,}"
          f"{l['out']:>12,}{x['output_tokens']:>12,}")

# ---- what the local measurement SHOULD have cost ----
print("\n=== LOCAL MEASUREMENT PRICED AT THE LEDGER'S OWN OBSERVED RATES ===")
# deepseek-flash: hit 0.006 peak / 0.003 off-peak; miss 0.30 / 0.15; out 1.20 / 0.60
# Value everything at PEAK (worst case) and at OFF-PEAK (best case).
M = sum(v["miss"] for v in loc.values())
H = sum(v["hit"] for v in loc.values())
O = sum(v["out"] for v in loc.values())
print(f"  local totals over 09-10..09-16: miss={M:,} hit={H:,} out={O:,}")
for label, m, h, o in (("off-peak 0.15/0.003/0.60", 0.15, 0.003, 0.60),
                       ("peak     0.30/0.006/1.20", 0.30, 0.006, 1.20)):
    print(f"  {label} -> ${(M*m + H*h + O*o)/1e6:8.2f}")

print("\n  ledger 'deepseek harness' for the SAME calendar days (09-10..09-16):")
tot = 0.0
for day in ("2026-09-10", "2026-09-11", "2026-09-13", "2026-09-14", "2026-09-15",
            "2026-09-16"):
    v = key_day_cost["deepseek harness"].get(day, 0.0)
    tot += v
    print(f"    {day}  ${v:8.2f}")
print(f"    TOTAL   ${tot:8.2f}")

print("\n=== THE ANSWER TO 'WHICH MACHINE SPENT THE $54' ===")
print("  ZABZ-YOGA  = api_key_name 'deepseek harness'")
print("  ZABZ-TECH  = api_key_name 'zabz-tech-harness'")
for day in ("2026-09-14", "2026-09-15"):
    y = key_day_cost["deepseek harness"].get(day, 0.0)
    t = key_day_cost["zabz-tech-harness"].get(day, 0.0)
    print(f"  {day}: ZABZ-YOGA ${y:7.2f}   ZABZ-TECH ${t:7.2f}   "
          f"combined ${y+t:7.2f}")
