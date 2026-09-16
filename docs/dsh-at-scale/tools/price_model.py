"""Per-session, per-day cost model over the measured DSH usage, plus prefix probes.

Reads the JSON produced by day_usage.py. Prices are supplied on the command line
so the model can be re-run when the published table is known.
"""
import argparse, collections, datetime, json, sys


def money(tok, per_m):
    return tok / 1_000_000.0 * per_m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--miss-price", type=float, default=0.28)
    ap.add_argument("--hit-price", type=float, default=0.028)
    ap.add_argument("--out-price", type=float, default=0.42)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    d = json.load(open(args.data, encoding="utf-8"))
    print(f"# host {d['host']}   prices used: miss=${args.miss_price}/M  "
          f"hit=${args.hit_price}/M  out=${args.out_price}/M")

    print("\n=== PRICED BY DAY (UTC) ===")
    print(f"{'day':<12}{'reqs':>7}{'miss$':>10}{'hit$':>10}{'out$':>9}{'TOTAL$':>10}"
          f"{'$/req':>8}")
    tot = collections.Counter()
    for day in sorted(d["by_day"]):
        c = d["by_day"][day]
        m = money(c.get("miss", 0), args.miss_price)
        h = money(c.get("hit", 0), args.hit_price)
        o = money(c.get("out", 0), args.out_price)
        s = m + h + o
        print(f"{day:<12}{c.get('n',0):>7}{m:>10.2f}{h:>10.2f}{o:>9.2f}{s:>10.2f}"
              f"{(s/c['n'] if c.get('n') else 0):>8.4f}")
        for k, v in c.items():
            tot[k] += v
    m = money(tot["miss"], args.miss_price)
    h = money(tot["hit"], args.hit_price)
    o = money(tot["out"], args.out_price)
    print(f"{'TOTAL':<12}{tot['n']:>7}{m:>10.2f}{h:>10.2f}{o:>9.2f}{m+h+o:>10.2f}")

    print("\n=== SHARE OF SPEND ===")
    s = m + h + o
    print(f"  cache-MISS input  {m:8.2f}  {100*m/s:5.1f}%")
    print(f"  cache-HIT  input  {h:8.2f}  {100*h/s:5.1f}%")
    print(f"  OUTPUT            {o:8.2f}  {100*o/s:5.1f}%")

    print("\n=== PRICED BY MODEL ===")
    rows = []
    for mod, c in d["by_model"].items():
        mm = money(c.get("miss", 0), args.miss_price)
        hh = money(c.get("hit", 0), args.hit_price)
        oo = money(c.get("out", 0), args.out_price)
        rows.append((mm + hh + oo, mod, c, mm, hh, oo))
    for s2, mod, c, mm, hh, oo in sorted(rows, reverse=True):
        print(f"  {mod:<32} reqs={c.get('n',0):>6}  ${s2:8.2f} "
              f"(miss ${mm:.2f} + hit ${hh:.2f} + out ${oo:.2f})")

    print(f"\n=== TOP {args.top} SESSIONS PRICED ===")
    ev = d.get("events") or []
    per_sess = collections.defaultdict(lambda: collections.Counter())
    first_of_sess = {}
    for ts, sid, model, miss, hit, out in ev:
        c = per_sess[sid]
        c["miss"] += miss
        c["hit"] += hit
        c["out"] += out
        c["n"] += 1
        if sid not in first_of_sess:
            first_of_sess[sid] = (ts, miss, hit, out)
    rows = []
    for sid, c in per_sess.items():
        s2 = (money(c["miss"], args.miss_price) + money(c["hit"], args.hit_price)
              + money(c["out"], args.out_price))
        rows.append((s2, sid, c))
    for s2, sid, c in sorted(rows, reverse=True)[:args.top]:
        f = first_of_sess[sid]
        print(f"  ${s2:8.2f}  reqs={c['n']:>5}  miss={c['miss']:>10,}  "
              f"hit={c['hit']:>12,}  out={c['out']:>9,}  "
              f"1st[miss={f[1]:,} hit={f[2]:,}]  {sid[:44]}")

    print("\n=== COLD-START PREFIX PROBE (first request of each session) ===")
    print("  the first request's hit+miss is the minimum prefix every request re-sends")
    vals = []
    for sid, (ts, miss, hit, out) in first_of_sess.items():
        vals.append((miss + hit, sid, miss, hit))
    vals.sort(reverse=True)
    print(f"  sessions sampled: {len(vals)}")
    if vals:
        import statistics
        tot_pref = [v[0] for v in vals]
        print(f"  mean first-request prompt : {statistics.mean(tot_pref):,.0f} tokens")
        print(f"  median                    : {statistics.median(tot_pref):,.0f}")
        print(f"  10th/90th pct             : "
              f"{tot_pref[int(.1*len(tot_pref))]:,} / {tot_pref[int(.9*len(tot_pref))]:,}")
        print(f"  mean first-request cache HIT: "
              f"{statistics.mean([v[3] for v in vals]):,.0f} tokens")
        for p, sid, miss, hit in vals[:10]:
            print(f"    {p:>9,}  (miss={miss:>8,} hit={hit:>9,})  {sid[:44]}")

    print("\n=== CACHE HIT RATE PER SESSION (worst 15) ===")
    rr = []
    for sid, c in per_sess.items():
        inb = c["miss"] + c["hit"]
        if inb < 100000:
            continue
        rr.append((c["hit"] / inb, sid, c["miss"], c["hit"]))
    for r, sid, miss, hit in sorted(rr)[:15]:
        print(f"  {100*r:6.2f}%  miss={miss:>12,}  hit={hit:>13,}  {sid[:44]}")


if __name__ == "__main__":
    main()
