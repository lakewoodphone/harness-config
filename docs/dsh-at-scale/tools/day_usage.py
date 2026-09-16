"""Read-only token accounting over DSH session logs.

DSH records real provider usage on `assistant/message` (and `compaction/summary`)
events as data.usage = {inputTokens, outputTokens, totalTokens, cacheReadTokens,
reasoningTokens}, where inputTokens appears to be the cache-MISS input and
cacheReadTokens the cache-HIT input, with totalTokens = full prompt + output.

Usage:  python day_usage.py [--since YYYY-MM-DD] [--until YYYY-MM-DD]
        [--host LABEL] [--json OUT] [--per-session] [--top N]
"""
import argparse, collections, datetime, json, os, sys

import zstandard as zstd

SESS = r"C:\Users\ezabz\.dsh\sessions"
dctx = zstd.ZstdDecompressor()


def read_text(path):
    with open(path, "rb") as fh:
        with dctx.stream_reader(fh) as r:
            return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--host", default=os.environ.get("COMPUTERNAME", "?"))
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    lo = datetime.date.fromisoformat(args.since) if args.since else None
    hi = datetime.date.fromisoformat(args.until) if args.until else None

    files = []
    for dirpath, _dn, fns in os.walk(SESS):
        for fn in fns:
            if fn.startswith("session.") and fn.endswith(".jsonl.zstd"):
                files.append(os.path.join(dirpath, fn))
    files.sort(key=os.path.getmtime)
    print(f"# host={args.host}  log files={len(files)}", file=sys.stderr)

    by_day = collections.defaultdict(lambda: collections.Counter())
    by_model = collections.defaultdict(lambda: collections.Counter())
    by_session = []
    turn_events = []          # (ts, session, inputMiss, cacheRead, out)
    unreadable = []

    for path in files:
        sid = os.path.basename(os.path.dirname(path))
        try:
            text = read_text(path)
        except Exception as exc:
            unreadable.append((sid, str(exc)))
            continue
        sess = collections.Counter()
        model = None
        for ln in text.splitlines():
            if '"usage"' not in ln and "request/context" not in ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            ty = o.get("type")
            data = o.get("data") or {}
            if ty == "request/context":
                model = data.get("model") or model
                continue
            u = data.get("usage")
            if not isinstance(u, dict):
                continue
            ts = o.get("time")
            if ts:
                dt = datetime.datetime.utcfromtimestamp(ts / 1000.0)
            else:
                dt = datetime.datetime.utcfromtimestamp(os.path.getmtime(path))
            day = dt.date().isoformat()
            miss = int(u.get("inputTokens") or 0)
            hit = int(u.get("cacheReadTokens") or 0)
            out = int(u.get("outputTokens") or 0)
            tot = int(u.get("totalTokens") or 0)
            think = int(u.get("reasoningTokens") or 0)
            rec = dict(miss=miss, hit=hit, out=out, tot=tot, think=think)
            by_day[day].update(rec)
            by_day[day][f"n"] += 1
            by_model[model or "unknown"].update(rec)
            by_model[model or "unknown"]["n"] += 1
            sess.update(rec)
            sess["n"] += 1
            turn_events.append((dt.isoformat(), sid, model or "?", miss, hit, out))
        if sess:
            sess["session"] = sid
            sess["mtime"] = datetime.datetime.utcfromtimestamp(
                os.path.getmtime(path)).isoformat() + "Z"
            sess["bytes"] = os.path.getsize(path)
            by_session.append(sess)

    hdr = ("day", "n", "miss", "hit", "out", "tot", "think")
    print()
    print("=== BY DAY (UTC) ===")
    print(f"{hdr[0]:<12}{hdr[1]:>7}{hdr[2]:>12}{hdr[3]:>12}{hdr[4]:>10}{hdr[5]:>12}{hdr[6]:>9}")
    grand = collections.Counter()
    for day in sorted(by_day):
        if lo and datetime.date.fromisoformat(day) < lo:
            continue
        if hi and datetime.date.fromisoformat(day) > hi:
            continue
        c = by_day[day]
        print(f"{day:<12}{c['n']:>7}{c['miss']:>12,}{c['hit']:>12,}{c['out']:>10,}"
              f"{c['tot']:>12,}{c['think']:>9,}")
        grand.update(c)
    print(f"{'TOTAL':<12}{grand['n']:>7}{grand['miss']:>12,}{grand['hit']:>12,}"
          f"{grand['out']:>10,}{grand['tot']:>12,}{grand['think']:>9,}")

    print()
    print("=== BY MODEL ===")
    model_rows = sorted(((m, c) for m, c in by_model.items()),
                        key=lambda x: -(x[1]["miss"] + x[1]["hit"]))
    for m, c in model_rows:
        print(f"{m:<26} n={c['n']:>6}  miss={c['miss']:>12,}  hit={c['hit']:>12,}  "
              f"out={c['out']:>10,}  tot={c['tot']:>13,}")

    print()
    print(f"=== TOP {args.top} SESSIONS BY TOTAL TOKENS ===")
    for s in sorted(by_session, key=lambda x: -x["tot"])[:args.top]:
        print(f"{s['tot']:>13,} tot  n={s['n']:>5}  miss={s['miss']:>11,}  "
              f"hit={s['hit']:>11,}  out={s['out']:>9,}  {s['mtime'][:16]}  "
              f"{s['session'][:46]}")

    print()
    print(f"=== CACHE HIT RATE (whole population) ===")
    in_total = grand["miss"] + grand["hit"]
    if in_total:
        print(f"prompt tokens total : {in_total:,}")
        print(f"cache hit           : {grand['hit']:,} ({100*grand['hit']/in_total:.1f}%)")
        print(f"cache miss          : {grand['miss']:,} ({100*grand['miss']/in_total:.1f}%)")

    if unreadable:
        print()
        print("=== UNREADABLE ===")
        for sid, err in unreadable[:10]:
            print(f"  {sid}: {err}")

    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"host": args.host,
                       "by_day": {d: dict(c) for d, c in by_day.items()},
                       "by_model": {m: dict(c) for m, c in by_model.items()},
                       "by_session": by_session,
                       "events": turn_events}, fh)
        print(f"\nwrote {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
