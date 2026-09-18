#!/usr/bin/env python3
"""spend-guard - DSH daily spend: measure it, predict it, refuse past a ceiling.

Prices every billed model request recorded in the durable session logs, using the
rate card that plugin-cost already owns (packages/plugin-cost/pricing.json), so
there is exactly one price table in the system.

  spend-guard.py report  [--day YYYY-MM-DD]      today's estimated spend, by session
  spend-guard.py predict --turns N --ctx TOKENS [--model M]
  spend-guard.py check   --ceiling 25 [--warn 18]  exit 0 ok / 2 warn / 1 over
  spend-guard.py selftest                        the arithmetic, on synthetic input

Every number is a LOWER BOUND on the bill: it can only see logs that are still on
this machine. It cannot see another machine, another engine, or a rotated log.
"""
import argparse, collections, datetime, json, os, sys, glob

CARD_ENV = "DSH_SPEND_CARD"


def find_card(explicit):
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    dsh = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    cands = [explicit, os.environ.get(CARD_ENV),
             os.path.join(here, "..", "packages", "plugin-cost", "pricing.json"),
             os.path.join(here, "packages", "plugin-cost", "pricing.json"),
             os.path.join(dsh, "profiles", "web", "node_modules", "dsh-plugin-cost", "pricing.json")]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


class Card:
    def __init__(self, path):
        with open(path, encoding="utf-8") as fh:
            self.raw = json.load(fh)
        self.by_model = {}
        for r in self.raw["routes"]:
            for m in r["models"]:
                self.by_model[m] = r
        self.path = path
        d = self.raw.get("defaultRoute") or {}
        self.default_model = d.get("model") or next(iter(self.by_model))
        self.unpriced = set((self.raw.get("unpriced") or {}).keys())

    def route(self, model):
        """Return (route, priced). An unknown model is priced at the default route
        and flagged, never silently made free."""
        r = self.by_model.get(model)
        return (r, True) if r is not None else (self.by_model[self.default_model], False)

    @staticmethod
    def multiplier(route, ts):
        mult, name = 1.0, "offpeak"
        for t in route.get("tiers") or []:
            days = t.get("days") or []
            if days:
                wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][ts.weekday()]
                if wd not in days:
                    continue
            for a, b in t.get("windows") or []:
                ah, am = (int(x) for x in a.split(":"))
                bh, bm = (int(x) for x in b.split(":"))
                if (ah, am) <= (ts.hour, ts.minute) < (bh, bm):
                    return float(t.get("multiplier", 1)), str(t.get("name", "peak"))
        return 1.0, name


def price_micro(card, usage, model, ts):
    """Exact integer micro-USD for one billed request.
    USD/1M tokens * tokens = micro-USD, so no floating total is accumulated."""
    route, priced = card.route(model)
    mult, tier = Card.multiplier(route, ts)
    rates = route["rates"]
    miss = int(usage.get("inputTokens") or 0)
    hit = int(usage.get("cacheReadTokens") or 0)
    out = int(usage.get("outputTokens") or 0)
    micro = (miss * rates.get("missPer1M", 0) + hit * rates.get("hitPer1M", 0)
             + out * rates.get("outputPer1M", 0)) * mult
    return int(round(micro)), tier, priced


def decode(path):
    """The log is a CONCATENATED multi-frame zstd container. A one-shot
    decompress returns only the first frame - 198 bytes of a 48 MB file - which is
    why this data has been declared missing three times. Read it as a stream."""
    import zstandard as zstd
    with open(path, "rb") as fh:
        with zstd.ZstdDecompressor().stream_reader(fh) as r:
            return r.read().decode("utf-8", "replace")


def scan(card, root, day):
    """Every billed request whose own UTC timestamp falls on `day`.
    mtime >= start-of-day is a sound pre-filter: logs are append-only and events are
    chronological, so a log last written before the day holds no event inside it."""
    lo = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    lo_ms = lo.timestamp() * 1000.0
    rows = collections.defaultdict(lambda: collections.Counter())
    unreadable, unpriced_models = [], collections.Counter()
    files = [p for p in glob.glob(os.path.join(root, "*", "*", "session.v3.jsonl.zstd"))
             if os.path.getmtime(p) >= lo.timestamp()]
    for path in files:
        sid = os.path.basename(os.path.dirname(path))
        try:
            text = decode(path)
        except Exception as exc:
            unreadable.append((sid, str(exc)[:80]))
            continue
        model = card.default_model
        for ln in text.splitlines():
            if '"usage"' not in ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            data = o.get("data") or {}
            if o.get("type") == "request/context":
                if data.get("model"):
                    model = data["model"]
                continue
            u = data.get("usage")
            if not isinstance(u, dict):
                continue
            t = o.get("time")
            if not isinstance(t, (int, float)):
                continue
            if t < lo_ms or t >= lo_ms + 86400000:
                continue
            ts = datetime.datetime.fromtimestamp(t / 1000.0, datetime.timezone.utc)
            micro, tier, priced = price_micro(card, u, model, ts)
            if not priced:
                unpriced_models[model] += 1
            c = rows[sid]
            c["micro"] += micro
            c["n"] += 1
            c["miss"] += int(u.get("inputTokens") or 0)
            c["hit"] += int(u.get("cacheReadTokens") or 0)
            c["out"] += int(u.get("outputTokens") or 0)
            if tier != "offpeak":
                c["peak_n"] += 1
                c["peak_micro"] += micro
    return rows, files, unreadable, unpriced_models


def usd(micro):
    return micro / 1e6


def cmd_report(args):
    card = Card(find_card(args.card))
    day = (datetime.date.fromisoformat(args.day) if args.day
           else datetime.datetime.now(datetime.timezone.utc).date())
    rows, files, unreadable, unpriced_models = scan(card, args.sessions, day)
    total = sum(c["micro"] for c in rows.values())
    print(f"DSH spend, {day.isoformat()} UTC  (LOWER BOUND on the bill)")
    print(f"  card    {card.path}  (updated {card.raw.get('updated')})")
    print(f"  scanned {len(files)} log(s) written since {day.isoformat()} 00:00Z"
          f"   unpriced-route requests: {sum(unpriced_models.values())}")
    print()
    print(f"  {'session':<38}{'req':>6}{'$':>10}{'cache-hit':>11}{'peak$':>8}")
    for sid in sorted(rows, key=lambda s: -rows[s]["micro"])[:args.top]:
        c = rows[sid]
        inp = c["miss"] + c["hit"]
        hr = (100.0 * c["hit"] / inp) if inp else 0.0
        print(f"  {sid[:38]:<38}{c['n']:>6}{usd(c['micro']):>10.4f}{hr:>10.1f}%{usd(c['peak_micro']):>8.4f}")
    print()
    print(f"  TOTAL    ${usd(total):.4f}   sessions {len(rows)}   "
          f"requests {sum(c['n'] for c in rows.values()):,}")
    if unreadable:
        print(f"  UNREADABLE (not priced, so NOT in the total): {len(unreadable)}")
        for sid, err in unreadable[:5]:
            print(f"    {sid}: {err}")
    if unpriced_models:
        print(f"  WARNING unpriced route priced at default and flagged: {dict(unpriced_models)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"day": day.isoformat(), "micro": total, "usd": usd(total),
                       "requests": sum(c["n"] for c in rows.values()),
                       "sessions": {s: dict(rows[s]) for s in rows}, "card": card.path}, fh, indent=1)
    return 0


def cmd_predict(args):
    """$ per step = C/231,300,000 + $0.0005 off-peak, exactly 2x at peak."""
    card = Card(find_card(args.card))
    route, priced = card.route(args.model)
    r = route["rates"]
    miss_frac = args.miss_frac
    hit_frac = 1.0 - miss_frac
    for label, mult in (("off-peak", 1.0), ("peak", 2.0)):
        prompt = args.turns * args.ctx
        micro = (prompt * hit_frac * r.get("hitPer1M", 0)
                 + prompt * miss_frac * r.get("missPer1M", 0)
                 + args.turns * args.out * r.get("outputPer1M", 0)) * mult
        print(f"  {label:<9} ${usd(int(round(micro))):>8.2f}   "
              f"({args.turns:,} steps x {args.ctx:,} ctx, {miss_frac:.1%} miss, "
              f"{args.out:,} out/step)")
    print(f"\n  model {args.model} ({route['provider']})  card {os.path.basename(card.path)}"
          f"{'' if priced else '  [UNPRICED ROUTE - priced at default, flagged]'}")
    print("  Measured reference: a working day ran $0.0015-$0.0020 per request at "
          "189k-263k mean context (console export, 2026-09-10..16).")
    return 0


def cmd_check(args):
    card = Card(find_card(args.card))
    day = (datetime.date.fromisoformat(args.day) if args.day
           else datetime.datetime.now(datetime.timezone.utc).date())
    rows, files, unreadable, unpriced = scan(card, args.sessions, day)
    total = usd(sum(c["micro"] for c in rows.values()))
    state, code = "OK", 0
    if total >= args.ceiling:
        state, code = "OVER", 1
    elif args.warn is not None and total >= args.warn:
        state, code = "WARN", 2
    print(json.dumps({"day": day.isoformat(), "spendUsd": round(total, 6),
                      "ceilingUsd": args.ceiling, "warnUsd": args.warn, "state": state,
                      "requests": sum(c["n"] for c in rows.values()), "sessions": len(rows),
                      "unreadable": len(unreadable),
                      "basis": "local durable logs, lower bound, this machine only",
                      "exit": code}))
    return code


def cmd_selftest(args):
    card = Card(find_card(args.card))
    utc = datetime.timezone.utc
    mp = datetime.datetime(2026, 9, 14, 2, 0, tzinfo=utc)    # Monday 02:00Z - peak
    mo = datetime.datetime(2026, 9, 14, 12, 0, tzinfo=utc)   # Monday 12:00Z - off-peak
    sa = datetime.datetime(2026, 9, 12, 2, 0, tzinfo=utc)    # Saturday - off-peak
    u = {"inputTokens": 1000, "cacheReadTokens": 100000, "outputTokens": 500}
    off = price_micro(card, u, "deepseek-flash", mo)
    pk = price_micro(card, u, "deepseek-flash", mp)
    we = price_micro(card, u, "deepseek-flash", sa)
    hand = round(1000 * 0.15 + 100000 * 0.003 + 500 * 0.60)
    checks = [("offpeak == hand arithmetic", off[0] == hand, f"{off[0]} == {hand}"),
              ("peak == exactly 2x offpeak", pk[0] == 2 * off[0], f"{pk[0]} vs {2 * off[0]}"),
              ("weekend 02:00Z is offpeak", we[1] == "offpeak", we[1]),
              ("Mon 02:00Z is peak", pk[1] == "peak", pk[1]),
              ("unknown model flagged, not free", card.route("no-such-model")[1] is False, "flagged"),
              ("one request is well under a cent", usd(hand) < 0.01, f"${usd(hand):.6f}")]
    bad = 0
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        bad += 0 if ok else 1
    print(f"\n  card {card.path}\n  {len(checks) - bad}/{len(checks)} checks passed")
    return 1 if bad else 0


def main():
    # `--card`/`--sessions` are accepted BOTH before and after the subcommand: a
    # human types both orders, and failing on the more natural one is a trap, not
    # a contract.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--card")
    common.add_argument("--sessions", default=None)
    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", parents=[common])
    r.add_argument("--day")
    r.add_argument("--top", type=int, default=15)
    r.add_argument("--json")
    p = sub.add_parser("predict", parents=[common])
    p.add_argument("--turns", type=int, required=True)
    p.add_argument("--ctx", type=int, required=True)
    p.add_argument("--model", default="deepseek-flash")
    p.add_argument("--out", type=int, default=830)
    p.add_argument("--miss-frac", type=float, default=0.009)
    c = sub.add_parser("check", parents=[common])
    c.add_argument("--day")
    c.add_argument("--ceiling", type=float, required=True)
    c.add_argument("--warn", type=float, default=None)
    sub.add_parser("selftest", parents=[common])
    args = ap.parse_args()
    if args.sessions is None:
        args.sessions = os.path.join(
            os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh"), "sessions")
    return {"report": cmd_report, "predict": cmd_predict,
            "check": cmd_check, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
