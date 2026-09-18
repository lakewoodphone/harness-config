"""Find seeded (fork) sessions and report their first-request input tokens. Read-only.

Also reports descriptor mode. Usage: python seeded.py <sessiondir> [max_size]
"""
import json
import os
import sys

import zstandard

ROOT = sys.argv[1]
MAXB = int(sys.argv[2]) if len(sys.argv) > 2 else 2_000_000

rows = []
for name in os.listdir(ROOT):
    p = os.path.join(ROOT, name, "session.v3.jsonl.zstd")
    if os.path.isfile(p):
        rows.append((os.path.getmtime(p), name, p, os.path.getsize(p)))
rows.sort(reverse=True)
print("sessions:", len(rows), "newest:", rows[0][1], "oldest:", rows[-1][1])

seeded = 0
for mtime, name, p, size in rows:
    if size > MAXB:
        continue
    hdr = None
    first = None
    n = 0
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
                if t == "session" and hdr is None:
                    hdr = ev
                elif t == "assistant/message" and first is None:
                    u = (ev.get("data") or {}).get("usage") or {}
                    first = (u.get("inputTokens"), u.get("cacheReadTokens"),
                             u.get("totalTokens"))
                    n += 1
                    if hdr is not None:
                        break
            if hdr is not None and first is not None:
                break
    if hdr is None:
        continue
    if hdr.get("isSeeded"):
        seeded += 1
    print(json.dumps({
        "session": name,
        "size": size,
        "isSeeded": hdr.get("isSeeded"),
        "parentSession": hdr.get("parentSession"),
        "delegationDepth": hdr.get("delegationDepth"),
        "agentPreset": hdr.get("agentPreset"),
        "origin": hdr.get("origin"),
        "first_assistant": first,
    }))
print("total seeded sessions:", seeded)
