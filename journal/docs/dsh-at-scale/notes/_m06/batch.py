"""Compact per-session summary across many logs. Read-only.

Usage: python batch.py <sessiondir> [max] [max_bytes]
"""
import json
import os
import sys

import zstandard

ROOT = sys.argv[1]


def text_len(node):
    """Total text characters under a tool-result payload (recursive)."""
    if isinstance(node, str):
        return len(node)
    if isinstance(node, list):
        return sum(text_len(x) for x in node)
    if isinstance(node, dict):
        total = 0
        for k, v in node.items():
            if k in ("text", "output", "value", "content", "parts", "message"):
                total += text_len(v)
        return total
    return 0

MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 10
MAXBYTES = int(sys.argv[3]) if len(sys.argv) > 3 else 5_000_000
TOP = int(sys.argv[4]) if len(sys.argv) > 4 else 6

rows = []
for name in os.listdir(ROOT):
    p = os.path.join(ROOT, name, "session.v3.jsonl.zstd")
    if not os.path.isfile(p):
        continue
    rows.append((os.path.getmtime(p), name, p, os.path.getsize(p)))
rows.sort(reverse=True)
rows = rows[:MAX]

for mtime, name, p, size in rows:
    if size > MAXBYTES:
        continue
    usage = {"n": 0, "in": 0, "out": 0, "tot": 0, "cache": 0, "reason": 0}
    first = None
    firsts = []
    tr_content = 0
    tr_n = 0
    models = {}
    tools = None
    desc = None
    seeded = None
    system_chars = 0
    retries = 0
    title_llm = None
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
                if t == "session" and seeded is None:
                    seeded = ev.get("isSeeded")
                elif t == "system/message":
                    msg = (ev.get("data") or {}).get("message") or {}
                    system_chars = text_len(msg.get("content"))
                elif t == "llm/retry":
                    retries += 1
                elif t == "assistant/message":
                    d = ev.get("data") or {}
                    u = d.get("usage") or {}
                    usage["n"] += 1
                    usage["in"] += u.get("inputTokens") or 0
                    usage["out"] += u.get("outputTokens") or 0
                    usage["tot"] += u.get("totalTokens") or 0
                    usage["cache"] += u.get("cacheReadTokens") or 0
                    usage["reason"] += u.get("reasoningTokens") or 0
                    if first is None:
                        first = (ev.get("seq"), u.get("inputTokens"),
                                 u.get("cacheReadTokens"), u.get("totalTokens"))
                        firsts.append(first)
                elif t == "tool/result":
                    tr_n += 1
                    tr_content += text_len(ev.get("data"))
                elif t == "request/context":
                    models[(ev.get("data") or {}).get("model")] = \
                        models.get((ev.get("data") or {}).get("model"), 0) + 1
                elif t == "request/header" and tools is None:
                    tl = ((ev.get("data") or {}).get("header") or {}).get("tools")
                    if isinstance(tl, list):
                        tools = (len(tl), len(json.dumps(tl)))
                elif t == "session/title-llm-request":
                    title_llm = json.dumps(ev.get("data") or {})[:400]
                elif t == "subagent/descriptor" and desc is None:
                    desc = (ev.get("data") or {}).get("mode")
    print(json.dumps({
        "session": name,
        "mtime": mtime,
        "size": size,
        "seeded": seeded,
        "descriptor_mode": desc,
        "system_chars": system_chars,
        "retries": retries,
        "msg_reqs": usage["n"],
        "in": usage["in"],
        "cacheRead": usage["cache"],
        "out": usage["out"],
        "reasoning": usage["reason"],
        "total": usage["tot"],
        "first_assistant": first,
        "tool_results": tr_n,
        "tool_result_chars": tr_content,
        "models": models,
        "tools": tools,
        "title_llm_request": title_llm,
    }))
