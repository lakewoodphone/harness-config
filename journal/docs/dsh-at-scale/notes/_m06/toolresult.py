"""Dump the first tool/result event's full JSON shape (truncated). Read-only."""
import json
import sys

import zstandard

PATH = sys.argv[1]
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
            if ev.get("type") != "tool/result":
                continue
            d = ev.get("data") or {}
            print("data keys:", sorted(d.keys()))
            for k, v in d.items():
                s = json.dumps(v)
                print(f"  {k}: {type(v).__name__} len={len(s)} :: {s[:400]}")
            raise SystemExit(0)
