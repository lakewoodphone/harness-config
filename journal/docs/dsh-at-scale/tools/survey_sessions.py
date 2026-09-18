"""Which cwd / preset / machine did the recorded DSH sessions run in?

Cheap: reads only the first line (the session header) of each log.
"""
import collections, glob, json, os, sys
import zstandard as zstd

SESS = r"C:\Users\ezabz\.dsh\sessions"
d = zstd.ZstdDecompressor()
cwds = collections.Counter()
presets = collections.Counter()
origins = collections.Counter()
parented = 0
seen = 0
for dirpath, _dn, fns in os.walk(SESS):
    for fn in fns:
        if not (fn.startswith("session.") and fn.endswith(".jsonl.zstd")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            with open(p, "rb") as fh:
                chunk = fh.read(1 << 20)
            text = d.stream_reader(io := __import__("io").BytesIO(chunk)).read(1 << 20).decode("utf-8", "replace")
        except Exception:
            continue
        first = text.splitlines()[0] if text else ""
        try:
            o = json.loads(first)
        except Exception:
            continue
        if o.get("type") != "session":
            continue
        seen += 1
        cwds[o.get("cwd")] += 1
        presets[o.get("agentPreset")] += 1
        origins[o.get("origin") or "root"] += 1
        if o.get("parentSession"):
            parented += 1

print(f"session headers read: {seen}")
print("\n=== cwd ===")
for k, v in cwds.most_common(15):
    print(f"  {v:>5}  {k}")
print("\n=== agentPreset ===")
for k, v in presets.most_common(15):
    print(f"  {v:>5}  {k}")
print("\n=== origin ===")
for k, v in origins.most_common(15):
    print(f"  {v:>5}  {k}")
print(f"\nchild sessions (has parentSession): {parented}")
