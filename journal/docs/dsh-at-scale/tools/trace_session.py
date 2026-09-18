"""Trace how one session's prompt grows, and where compaction fires."""
import datetime, json, sys
import zstandard as zstd

path = sys.argv[1]
d = zstd.ZstdDecompressor()
text = d.stream_reader(open(path, "rb")).read().decode("utf-8", "replace")

rows = []
marks = []
for ln in text.splitlines():
    try:
        o = json.loads(ln)
    except Exception:
        continue
    ty = o.get("type")
    data = o.get("data") or {}
    t = o.get("time")
    if ty in ("assistant/message", "compaction/summary"):
        u = data.get("usage")
        if not isinstance(u, dict):
            continue
        rows.append((t, ty, int(u.get("inputTokens") or 0),
                     int(u.get("cacheReadTokens") or 0),
                     int(u.get("outputTokens") or 0),
                     int(u.get("totalTokens") or 0)))
    elif ty in ("compaction/start", "compaction/end", "turn/start", "agent/inbox/spliced"):
        marks.append((t, ty, data.get("turn")))
    elif ty == "assistant/attempt":
        for chunk in (data.get("stream") or []):
            c = chunk.get("chunk") or {}
            if c.get("type") == "finish":
                r = c.get("reason") or {}
                if r.get("kind") == "error":
                    marks.append((t, "ERROR:" + str((r.get("failure") or {}).get("code")), None))

print(f"events with usage: {len(rows)}")
print(f"{'#':>5} {'prompt':>10} {'hit':>10} {'miss':>8} {'out':>7}  {'day hh:mm':<12}")
last = None
for i, (t, ty, miss, hit, out, tot) in enumerate(rows):
    prompt = miss + hit
    ts = datetime.datetime.utcfromtimestamp(t / 1000.0).strftime("%m-%d %H:%M") if t else "?"
    if i < 8 or i % max(1, len(rows) // 40) == 0 or i >= len(rows) - 5:
        print(f"{i:>5} {prompt:>10,} {hit:>10,} {miss:>8,} {out:>7,}  {ts:<12}")
print()
print("=== PEAK PROMPTS ===")
for t, ty, miss, hit, out, tot in sorted(rows, key=lambda r: -(r[2] + r[3]))[:8]:
    ts = datetime.datetime.utcfromtimestamp(t / 1000.0).strftime("%m-%d %H:%M") if t else "?"
    print(f"  prompt={miss+hit:>10,}  hit={hit:>10,} miss={miss:>8,} out={out:>7,}  {ts}")
print()
print("=== MARKERS (compaction / errors / turns) ===")
for t, ty, tn in marks:
    if ty in ("turn/start", "agent/inbox/spliced"):
        continue
    ts = datetime.datetime.utcfromtimestamp(t / 1000.0).strftime("%m-%d %H:%M") if t else "?"
    print(f"  {ts}  {ty}  turn={tn}")
