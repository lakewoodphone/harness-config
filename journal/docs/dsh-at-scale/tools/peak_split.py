"""Peak vs off-peak split, using the ledger's own two price tiers as the detector.

The export prices each (model,type) at two rates: the low one is off-peak, the high
one peak. So the price actually charged tells us which window each row fell in.
"""
import collections, csv, os

D = r"C:\Users\ezabz\code\_dsh-scale\data\usage-export"
amt = list(csv.DictReader(open(os.path.join(D, "amount-2026-08-18_2026-09-16.csv"),
                              newline="", encoding="utf-8-sig")))

# discover, per (model,type), the low/high price pair
pairs = collections.defaultdict(set)
for r in amt:
    if r["price"]:
        pairs[(r["model"], r["type"])].add(float(r["price"]))
low = {k: min(v) for k, v in pairs.items() if len(v) == 2}
thresh = {k: (min(v) + max(v)) / 2 for k, v in pairs.items() if len(v) == 2}


def tier(model, typ, p):
    k = (model, typ)
    if k not in thresh or not p:
        return "n/a"
    return "peak" if float(p) > thresh[k] else "offpeak"


for who, keep in (("ALL KEYS", None),
                  ("HARNESS KEYS ONLY", ("deepseek harness", "zabz-tech-harness"))):
    print(f"=== {who}: PEAK vs OFF-PEAK ===")
    total = collections.Counter()
    for r in amt:
        if r["type"] == "request_count":
            continue
        if keep and r["api_key_name"] not in keep:
            continue
        t = tier(r["model"], r["type"], r["price"])
        cost = float(r["price"] or 0) * int(r["amount"] or 0)
        total[t] += cost
        total["all"] += cost
    for t in ("offpeak", "peak", "n/a"):
        if total[t]:
            print(f"  {t:<9} ${total[t]:8.2f}  {100*total[t]/total['all']:5.1f}%")
    print()

print("=== THE SPIKE DAYS, HARNESS KEYS, PEAK vs OFF-PEAK ===")
for day in ("2026-09-14", "2026-09-15"):
    t = collections.Counter()
    for r in amt:
        if r["start_time_iso"][:10] != day or r["type"] == "request_count":
            continue
        if r["api_key_name"] not in ("deepseek harness", "zabz-tech-harness"):
            continue
        k = tier(r["model"], r["type"], r["price"])
        c = float(r["price"] or 0) * int(r["amount"] or 0)
        t[k] += c
        t["all"] += c
    print(f"  {day}: offpeak ${t['offpeak']:6.2f} ({100*t['offpeak']/t['all']:4.1f}%)  "
          f"peak ${t['peak']:6.2f} ({100*t['peak']/t['all']:4.1f}%)  "
          f"total ${t['all']:6.2f}")

print()
print("=== PEAK-WINDOW COST BY DAY, ALL KEYS (to confirm the 01-04/06-10 UTC windows) ===")
per = collections.defaultdict(lambda: collections.Counter())
for r in amt:
    if r["type"] == "request_count":
        continue
    k = tier(r["model"], r["type"], r["price"])
    c = float(r["price"] or 0) * int(r["amount"] or 0)
    per[r["start_time_iso"][:10]][k] += c
print(f"{'day':<12}{'offpeak$':>11}{'peak$':>10}{'peak%':>8}")
for day in sorted(per):
    c = per[day]
    a = c["offpeak"] + c["peak"]
    if not a:
        continue
    print(f"{day:<12}{c['offpeak']:>11.2f}{c['peak']:>10.2f}{100*c['peak']/a:>7.1f}%")
