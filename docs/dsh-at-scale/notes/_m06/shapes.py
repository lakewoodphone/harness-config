"""Print the shape of the first N event types in one session log. Read-only."""
import json
import sys

import zstandard

PATH = sys.argv[1]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 40

seen = {}
with open(PATH, "rb") as fh:
    reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
    pending = b""
    n = 0
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
            t = ev.get("type")
            if t in seen:
                continue
            d = ev.get("data")
            keys = sorted(d.keys()) if isinstance(d, dict) else type(d).__name__
            seen[t] = (ev.get("seq"), keys)
            print(t, "| seq", ev.get("seq"), "| top:", sorted(ev.keys()), "| data keys:", keys)
            n += 1
            if n >= LIMIT:
                raise SystemExit(0)
