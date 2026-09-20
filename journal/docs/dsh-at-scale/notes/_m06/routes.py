"""Route audit: request/header config + request/context model, per session. Read-only.

Usage: python routes.py <sessiondir> [max_size] [limit]
"""
import json
import os
import sys

import zstandard

ROOT = sys.argv[1]
MAXB = int(sys.argv[2]) if len(sys.argv) > 2 else 2_000_000
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 40

rows = []
for name in os.listdir(ROOT):
    p = os.path.join(ROOT, name, "session.v3.jsonl.zstd")
    if os.path.isfile(p):
        rows.append((os.path.getmtime(p), name, p, os.path.getsize(p)))
rows.sort(reverse=True)

models = {}
configs = {}
titles = []
for mtime, name, p, size in rows[:LIMIT]:
    if size > MAXB:
        continue
    with open(p, "rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        pending = b""
        while True:
            buf = reader.read(1 << 20)
            if not buf:
                break
            pending += buf
            *lines, pending = pending.split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = ev.get("type")
                if t == "request/context":
                    m = (ev.get("data") or {}).get("model")
                    models[m] = models.get(m, 0) + 1
                elif t == "request/header":
                    cfg = json.dumps(((ev.get("data") or {}).get("header") or {}).get("config"))
                    configs[cfg] = configs.get(cfg, 0) + 1
                elif t == "session/title-llm-request":
                    d = ev.get("data") or {}
                    titles.append({
                        "session": name,
                        "model": (d.get("route") or {}).get("model"),
                        "provider": (d.get("route") or {}).get("provider"),
                        "titleProvider": d.get("titleProvider"),
                        "system_chars": len(d.get("system") or ""),
                        "keys": sorted(d.keys()),
                    })
print("request/context model counts:", json.dumps(models, indent=1))
print("request/header config variants:")
for k, v in sorted(configs.items(), key=lambda kv: -kv[1]):
    print("  x%d %s" % (v, k[:600]))
print("title llm requests:")
for t in titles:
    print(" ", json.dumps(t))
