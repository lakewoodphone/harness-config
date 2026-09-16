"""Re-price the measured usage with the OFFICIAL DeepSeek price table.

Official (https://api-docs.deepseek.com/quick_start/pricing), USD per 1M tokens:
  deepseek-flash   cache-hit 0.003 off-peak / 0.006 peak
                   cache-miss 0.15  off-peak / 0.30  peak
                   output     0.60  off-peak / 1.20  peak
  PEAK = 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri. Everything else off-peak.
  (All events here carry their own epoch-ms `time`, so peak/off-peak is decided
   per event, not per day.)
"""
import collections, datetime, json

FLASH = {
    "peak":     {"hit": 0.006, "miss": 0.30, "out": 1.20},
    "offpeak":  {"hit": 0.003, "miss": 0.15, "out": 0.60},
}
PRO = {
    "peak":     {"hit": 0.044, "miss": 1.32, "out": 3.96},
    "offpeak":  {"hit": 0.022, "miss": 0.66, "out": 1.98},
}
PEAK_HOURS = ((1, 4), (6, 10))          # UTC, [start, end)


def window(dt):
    if dt.weekday() >= 5:               # Sat/Sun fully off-peak
        return "offpeak"
    for a, b in PEAK_HOURS:
        if a <= dt.hour < b:
            return "peak"
    return "offpeak"


def table_for(model):
    return PRO if model == "deepseek-v4-pro" else FLASH


d = json.load(open(r"C:\Users\ezabz\code\_dsh-scale\data\usage-yoga.json", encoding="utf-8"))

by_day = collections.defaultdict(lambda: collections.Counter())
by_day_offpeak = collections.defaultdict(lambda: collections.Counter())
by_day_peak = collections.defaultdict(lambda: collections.Counter())

for ts, sid, model, miss, hit, out in d["events"]:
    dt = datetime.datetime.fromisoformat(ts)
    w = window(dt)
    day = ts[:10]
    t = table_for(model)
    c = (miss * t[w]["miss"] + hit * t[w]["hit"] + out * t[w]["out"]) / 1e6
    by_day[day]["cost"] += c
    by_day[day]["n"] += 1
    by_day[day]["miss"] += miss
    by_day[day]["hit"] += hit
    by_day[day]["out"] += out
    by_day[w][day]  # touch
    by_day_offpeak[day]["cost"] += c if w == "offpeak" else 0
    by_day_peak[day]["cost"] += c if w == "peak" else 0
    if w == "peak":
        by_day[day]["npeak"] += 1
    else:
        by_day[day]["noff"] += 1

print("=== OFFICIAL PRICING, PER EVENT'S OWN UTC HOUR ===")
print(f"{'day':<12}{'reqs':>7}{'peak_reqs':>10}{'miss':>12}{'hit':>14}{'out':>10}"
      f"{'peak$':>9}{'offpk$':>9}{'TOTAL$':>9}")
tot = 0.0
for day in sorted(by_day):
    c = by_day[day]
    p = by_day_peak[day]["cost"]
    o = by_day_offpeak[day]["cost"]
    tot += p + o
    print(f"{day:<12}{c['n']:>7}{c.get('npeak',0):>10}{c['miss']:>12,}"
          f"{c['hit']:>14,}{c['out']:>10,}{p:>9.2f}{o:>9.2f}{p+o:>9.2f}")
print(f"{'TOTAL':<12}{'':>7}{'':>10}{'':>12}{'':>14}{'':>10}{'':>9}{'':>9}{tot:>9.2f}")

print()
print("=== 2026-09-15 ALONE (the owner's '$54 day') ===")
c = by_day["2026-09-15"]
p, o = by_day_peak["2026-09-15"]["cost"], by_day_offpeak["2026-09-15"]["cost"]
print(f"  requests           : {c['n']:,}  (peak-hour requests: {c.get('npeak',0):,})")
print(f"  cache-miss input   : {c['miss']:,}")
print(f"  cache-hit  input   : {c['hit']:,}")
print(f"  output             : {c['out']:,}")
print(f"  peak-hour cost     : ${p:.2f}")
print(f"  off-peak cost      : ${o:.2f}")
print(f"  TOTAL              : ${p+o:.2f}")

print()
print("=== COUNTERFACTUALS, all 6 days ===")
M = sum(by_day[dd]["miss"] for dd in by_day)
H = sum(by_day[dd]["hit"] for dd in by_day)
O = sum(by_day[dd]["out"] for dd in by_day)
print(f"  measured totals: miss={M:,}  hit={H:,}  out={O:,}")
t = FLASH["peak"]
print(f"  as measured (per-event peak/off-peak)   : ${tot:8.2f}")
print(f"  if ALL traffic were peak-priced         : "
      f"${(M*t['miss']+H*t['hit']+O*t['out'])/1e6:8.2f}")
print(f"  if ALL traffic were off-peak-priced     : "
      f"${(M*0.15+H*0.003+O*0.60)/1e6:8.2f}")
print(f"  if NOTHING were cached (all miss, peak) : "
      f"${(M+H)*t['miss']/1e6 + O*t['out']/1e6:8.2f}")
print(f"  that is the saving caching already buys : "
      f"{((M+H)*t['miss']/1e6 + O*t['out']/1e6) / tot:.1f}x")

print()
print("=== SENSITIVITY: what halving mean context would save ===")
for frac in (0.75, 0.50, 0.25):
    saved = H * (1 - frac)
    # value the saved tokens at the measured average realised rate for cache-hit input
    realised = sum(by_day_peak[dd]["cost"] + by_day_offpeak[dd]["cost"] for dd in by_day)
    avg_hit_rate = realised / max(H, 1)      # crude blended $/token over the whole mix
    print(f"  context x{frac:<5} -> cache-hit tokens -{saved:>15,}  "
          f"~-${saved*0.0036/1e6:6.2f} at an assumed blended $0.0036/M hit rate")
