"""Dump system/message + first user/message + request/header shape for one session. Read-only."""
import json
import sys

import zstandard

PATH = sys.argv[1]
WANT = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"system/message", "user/message"}
seen = {}
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
            t = ev.get("type")
            if t not in WANT:
                continue
            d = ev.get("data") or {}
            if t == "user/message":
                c = d.get("content")
                txt = ""
                if isinstance(c, str):
                    txt = c
                elif isinstance(c, list):
                    txt = "".join(
                        b.get("text") or "" for b in c if isinstance(b, dict)
                    )
                print(json.dumps({
                    "type": t, "seq": ev.get("seq"), "source": d.get("source"),
                    "role": d.get("role"), "total_chars": len(txt),
                    "head": txt[:300],
                }))
                seen[t] = seen.get(t, 0) + 1
                if seen[t] >= 2:
                    WANT.discard(t)
                if not WANT:
                    raise SystemExit(0)
                continue
            msg = d.get("message")
            out = {"type": t, "seq": ev.get("seq"), "data_keys": sorted(d.keys())}
            if isinstance(msg, dict):
                out["msg_keys"] = sorted(msg.keys())
                out["role"] = msg.get("role")
                c = msg.get("content")
                out["content_type"] = type(c).__name__
                if isinstance(c, str):
                    out["content_chars"] = len(c)
                    out["head"] = c[:200]
                elif isinstance(c, list):
                    out["blocks"] = [
                        {"type": b.get("type"), "chars": len(b.get("text") or "")}
                        if isinstance(b, dict) else str(b) for b in c
                    ]
                    out["total_chars"] = sum(
                        len(b.get("text") or "") for b in c if isinstance(b, dict)
                    )
                    txt = "".join(b.get("text") or "" for b in c if isinstance(b, dict))
                    out["head"] = txt[:200]
            if t == "request/header":
                hdr = d.get("header") or {}
                out["header_keys"] = sorted(hdr.keys()) if isinstance(hdr, dict) else None
                out["reason"] = d.get("reason")
            print(json.dumps(out)[:1200])
            seen[t] = seen.get(t, 0) + 1
            if t == "system/message" and seen[t] >= 1:
                WANT.discard(t)
            if t == "user/message" and seen[t] >= 2:
                WANT.discard(t)
            if t == "request/header" and seen[t] >= 1:
                WANT.discard(t)
            if not WANT:
                raise SystemExit(0)
