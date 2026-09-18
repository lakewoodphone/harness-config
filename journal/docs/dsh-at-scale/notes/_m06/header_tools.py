"""Measure the request/header tool catalogue: totals and per-tool sizes. Read-only.

Usage: python header_tools.py <session.v3.jsonl.zstd> [--names]
"""
import json
import sys

import zstandard

PATH = sys.argv[1]
SHOW = "--names" in sys.argv

with open(PATH, "rb") as fh:
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
            ev = json.loads(line)
            if ev.get("type") != "request/header":
                continue
            hdr = (ev.get("data") or {}).get("header") or {}
            print("header keys:", sorted(hdr.keys()))
            tools = hdr.get("tools")
            print("reason:", (ev.get("data") or {}).get("reason"))
            if not isinstance(tools, list):
                print("tools not a list")
                raise SystemExit(0)
            total = 0
            rows = []
            for t in tools:
                s = json.dumps(t)
                total += len(s)
                rows.append((t.get("name"), len(s)))
            print("tool count:", len(tools), "serialized chars:", total)
            mcp = [r for r in rows if r[0] and r[0].startswith("mcp__")]
            print("mcp__ prefix count:", len(mcp), "chars:", sum(r[1] for r in mcp))
            servers = {}
            for n, c in mcp:
                srv = n.split("__")[1] if n.count("__") >= 2 else "?"
                a = servers.setdefault(srv, [0, 0])
                a[0] += 1
                a[1] += c
            for srv, (cnt, ch) in sorted(servers.items(), key=lambda kv: -kv[1][1]):
                print(f"  server {srv}: {cnt} tools, {ch} chars")
            print("largest 20 tools by schema chars:")
            for n, c in sorted(rows, key=lambda r: -r[1])[:20]:
                print(f"  {c:7d}  {n}")
            if SHOW:
                print("all tool names:")
                for n, c in sorted(rows, key=lambda r: -r[1]):
                    print(f"  {c:7d}  {n}")
            raise SystemExit(0)
