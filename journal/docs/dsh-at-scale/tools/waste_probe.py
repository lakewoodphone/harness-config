"""Cheap proxies for wasted spend, computed over all session logs.

(1) Failed/retried attempts: an `assistant/attempt` whose finish reason is an
    error has already billed its input.
(2) Auto-continuation churn: agent/inbox/spliced events.
(3) Split of tokens between root sessions and subagent sessions.
(4) Number of CONTEXT_WINDOW_EXCEEDED errors (these force a full-price re-send).
"""
import collections, json, os, sys
import zstandard as zstd

SESS = r"C:\Users\ezabz\.dsh\sessions"
d = zstd.ZstdDecompressor()

errs = collections.Counter()
by_kind = collections.defaultdict(collections.Counter)
spliced = collections.Counter()
retries = collections.Counter()

for dirpath, _dn, fns in os.walk(SESS):
    for fn in fns:
        if not (fn.startswith("session.") and fn.endswith(".jsonl.zstd")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            text = d.stream_reader(open(p, "rb")).read().decode("utf-8", "replace")
        except Exception:
            continue
        lines = text.splitlines()
        origin = "root"
        try:
            h = json.loads(lines[0])
            origin = h.get("origin") or "root"
        except Exception:
            pass
        day = None
        for ln in lines:
            if "assistant/attempt" not in ln and '"usage"' not in ln \
               and "agent/inbox/spliced" not in ln and "llm/retry" not in ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            ty = o.get("type")
            data = o.get("data") or {}
            t = o.get("time")
            import datetime
            if t:
                day = datetime.datetime.utcfromtimestamp(t / 1000.0).date().isoformat()
            if ty == "assistant/attempt":
                for ch in (data.get("stream") or []):
                    c = ch.get("chunk") or {}
                    if c.get("type") == "finish":
                        r = c.get("reason") or {}
                        if r.get("kind") == "error":
                            code = (r.get("failure") or {}).get("code") or "?"
                            errs[(day, code, origin)] += 1
            elif ty == "llm/retry":
                retries[(day, origin)] += 1
            elif ty == "agent/inbox/spliced":
                spliced[(day, origin)] += 1
            u = data.get("usage")
            if isinstance(u, dict):
                c = by_kind[origin]
                c["n"] += 1
                c["miss"] += int(u.get("inputTokens") or 0)
                c["hit"] += int(u.get("cacheReadTokens") or 0)
                c["out"] += int(u.get("outputTokens") or 0)

print("=== ERRORS BY DAY / CODE / ORIGIN ===")
for (day, code, origin), n in sorted(errs.items()):
    print(f"  {day}  {origin:<9} {code:<28} {n}")
print(f"  total error attempts: {sum(errs.values())}")
print()
print("=== llm/retry BY DAY / ORIGIN ===")
if retries:
    for k, v in sorted(retries.items()):
        print(f"  {k}  {v}")
else:
    print("  (no llm/retry events found)")
print()
print("=== agent/inbox/spliced BY DAY / ORIGIN (top 15) ===")
for k, v in sorted(spliced.items(), key=lambda x: -x[1])[:15]:
    print(f"  {k}  {v}")
print(f"  total spliced: {sum(spliced.values())}")
print()
print("=== TOKENS BY SESSION ORIGIN ===")
for origin, c in sorted(by_kind.items(), key=lambda x: -x[1]["hit"]):
    print(f"  {origin:<9} reqs={c['n']:>6}  miss={c['miss']:>11,}  "
          f"hit={c['hit']:>13,}  out={c['out']:>10,}")
