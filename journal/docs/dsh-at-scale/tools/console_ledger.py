"""Analyse the DeepSeek console usage export (the authoritative ledger).

Two files:
  cost-*.csv   : user_id, start_time_iso, end_time_iso, model, wallet_type, cost, currency
  amount-*.csv : user_id, start_time_iso, end_time_iso, model, api_key_name, api_key,
                 type, price, amount
"""
import collections, csv, os

D = r"C:\Users\ezabz\code\_dsh-scale\data\usage-export"
cost_f = os.path.join(D, "cost-2026-08-18_2026-09-16.csv")
amt_f = os.path.join(D, "amount-2026-08-18_2026-09-16.csv")


def rows(p):
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


cost = rows(cost_f)
amt = rows(amt_f)
print(f"cost rows: {len(cost)}   amount rows: {len(amt)}")

# ---------- 1. cost by day ----------
print("\n=== 1. AUTHORITATIVE COST BY DAY (local -04:00 day boundaries) ===")
print(f"{'day':<12}{'flash$':>12}{'pro$':>10}{'other$':>10}{'TOTAL$':>12}")
byday = collections.defaultdict(lambda: collections.Counter())
for r in cost:
    day = r["start_time_iso"][:10]
    c = float(r["cost"])
    m = r["model"]
    byday[day][m] += c
    byday[day]["TOTAL"] += c
tot = 0.0
for day in sorted(byday):
    c = byday[day]
    flash = sum(v for k, v in c.items() if k in ("deepseek-flash", "deepseek-v4-flash"))
    pro = sum(v for k, v in c.items() if "pro" in k)
    other = c["TOTAL"] - flash - pro
    tot += c["TOTAL"]
    print(f"{day:<12}{flash:>12.2f}{pro:>10.2f}{other:>10.2f}{c['TOTAL']:>12.2f}")
print(f"{'GRAND TOTAL':<12}{'':>12}{'':>10}{'':>10}{tot:>12.2f}")

# ---------- 2. cost by model ----------
print("\n=== 2. COST BY MODEL (whole export) ===")
bymodel = collections.Counter()
for r in cost:
    bymodel[r["model"]] += float(r["cost"])
for m, v in bymodel.most_common():
    print(f"  {m:<32} ${v:10.2f}")

# ---------- 3. tokens by model / key / type ----------
print("\n=== 3. TOKENS BY MODEL AND TYPE (whole export) ===")
tok = collections.defaultdict(collections.Counter)
for r in amt:
    tok[r["model"]][r["type"]] += int(r["amount"] or 0)
for m, c in sorted(tok.items(), key=lambda x: -x[1]["input_cache_miss_tokens"]):
    print(f"  {m}")
    for t in ("request_count", "input_cache_miss_tokens",
              "input_cache_hit_tokens", "output_tokens"):
        if c[t]:
            print(f"      {t:<28} {c[t]:>16,}")

# ---------- 4. THE KEY AXIS: api_key_name ----------
print("\n=== 4. BY API KEY LABEL (whole export) ===")
bykey = collections.defaultdict(lambda: collections.Counter())
for r in amt:
    k = r["api_key_name"]
    t = r["type"]
    v = int(r["amount"] or 0)
    bykey[k][t] += v
    bykey[k]["rows"] += 1
hdr = f"{'api_key_name':<34}{'reqs':>10}{'miss_in':>15}{'hit_in':>15}{'out':>12}"
print(hdr)
for k, c in sorted(bykey.items(), key=lambda x: -x[1]["input_cache_miss_tokens"]):
    print(f"{k[:33]:<34}{c['request_count']:>10,}{c['input_cache_miss_tokens']:>15,}"
          f"{c['input_cache_hit_tokens']:>15,}{c['output_tokens']:>12,}")

# ---------- 5. cost per api key (price x amount) ----------
print("\n=== 5. COST COMPUTED FROM price x amount, BY API KEY ===")
bykey_cost = collections.defaultdict(float)
for r in amt:
    try:
        p = float(r["price"] or 0)
    except ValueError:
        p = 0.0
    v = int(r["amount"] or 0)
    bykey_cost[r["api_key_name"]] += p * v
for k, v in sorted(bykey_cost.items(), key=lambda x: -x[1]):
    print(f"  {k:<34} ${v:10.2f}")

# ---------- 6. distinct prices ----------
print("\n=== 6. EVERY DISTINCT (model, type, price) OBSERVED ===")
prices = collections.Counter()
for r in amt:
    prices[(r["model"], r["type"], r["price"])] += 1
for (m, t, p), n in sorted(prices.items()):
    print(f"  {m:<32} {t:<26} price={p:<12} rows={n}")

# ---------- 7. the two spike days, by key ----------
print("\n=== 7. THE SPIKE DAYS, BY API KEY ===")
for day in ("2026-09-14", "2026-09-15", "2026-09-16"):
    print(f"\n  --- {day} ---")
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in amt:
        if r["start_time_iso"][:10] != day:
            continue
        if "deepseek-flash" not in r["model"]:
            continue
        agg[r["api_key_name"]][r["type"]] += int(r["amount"] or 0)
    for k, c in sorted(agg.items(), key=lambda x: -x[1]["input_cache_miss_tokens"]):
        print(f"    {k[:40]:<42} reqs={c['request_count']:>7,} "
              f"miss={c['input_cache_miss_tokens']:>13,} "
              f"hit={c['input_cache_hit_tokens']:>15,} "
              f"out={c['output_tokens']:>10,}")

# ---------- 8. month-long trend ----------
print("\n=== 8. DAILY TOTAL TREND (whole export) ===")
for day in sorted(byday):
    bar = "#" * int(byday[day]["TOTAL"] * 2)
    print(f"  {day}  ${byday[day]['TOTAL']:7.2f}  {bar}")
