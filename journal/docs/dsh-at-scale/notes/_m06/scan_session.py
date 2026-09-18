"""Read ONE DSH session log (multi-frame zstd) and print compact measurements.

Read-only. Streams frame by frame so a 12 MB log never materializes whole.
"""
import json
import sys

import zstandard

SESSIONS = r"C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--"
PATH = sys.argv[1]


def frames(path, chunk=1 << 20):
    with open(path, "rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        pending = b""
        while True:
            buf = reader.read(chunk)
            if not buf:
                break
            pending += buf
            *lines, pending = pending.split(b"\n")
            for line in lines:
                if line.strip():
                    yield line
        if pending.strip():
            yield pending


def main():
    types = {}
    tool_result_full_chars = 0
    tool_result_content_chars = 0
    tool_result_events = 0
    max_tool_result = 0
    biggest_tool = None
    usage = {
        "events": 0, "inputTokens": 0, "outputTokens": 0,
        "totalTokens": 0, "cacheReadTokens": 0, "reasoningTokens": 0,
    }
    model_counts = {}
    header_tools = None  # from last request/header seen
    header_count = 0
    first_usage = None
    turn_ends = 0
    user_messages = 0
    for raw in frames(PATH):
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        t = ev.get("type")
        types[t] = types.get(t, 0) + 1
        if t == "assistant/message":
            d = ev.get("data", {})
            u = d.get("usage")
            if isinstance(u, dict):
                usage["events"] += 1
                for k in ("inputTokens", "outputTokens", "totalTokens",
                          "cacheReadTokens", "reasoningTokens"):
                    v = u.get(k)
                    if isinstance(v, (int, float)):
                        usage[k] += v
                if first_usage is None:
                    first_usage = dict(u)
                    first_usage["_seq"] = ev.get("seq")
        elif t == "tool/result":
            tool_result_events += 1
            full = len(raw)
            tool_result_full_chars += full
            d = ev.get("data", {})
            msg = d.get("message")
            content = None
            if isinstance(msg, dict):
                content = msg.get("content")
                if content is None and isinstance(msg.get("parts"), list):
                    content = msg["parts"]
            if content is None:
                content = d.get("content")
            n = 0
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict):
                        s = blk.get("text") or blk.get("output")
                        if isinstance(s, str):
                            n += len(s)
                        else:
                            n += len(json.dumps(blk))
            elif isinstance(content, str):
                n = len(content)
            tool_result_content_chars += n
            if n > max_tool_result:
                max_tool_result = n
                biggest_tool = (ev.get("seq"), d.get("name") or d.get("toolName"), n)
        elif t in ("request/context", "request/count-tokens"):
            d = ev.get("data", {})
            m = d.get("model")
            if m is None:
                m = (d.get("route") or {}).get("model") if isinstance(d.get("route"), dict) else None
            if m is not None:
                key = str(m)
                model_counts[key] = model_counts.get(key, 0) + 1
        elif t == "request/header":
            header_count += 1
            d = ev.get("data", {})
            hdr = d.get("header") if isinstance(d.get("header"), dict) else d
            tools = hdr.get("tools")
            if isinstance(tools, list):
                text = json.dumps(tools)
                header_tools = {
                    "count": len(tools),
                    "chars": len(text),
                    "names": [x.get("name") for x in tools if isinstance(x, dict)],
                    "bytes": len(text.encode("utf8")),
                }
            else:
                header_tools = {"count": None, "chars": len(json.dumps(d))}
        elif t == "turn/end":
            turn_ends += 1
        elif t == "user/message":
            user_messages += 1
    out = {
        "path": PATH,
        "usage": usage,
        "first_assistant_usage": first_usage,
        "tool_result_events": tool_result_events,
        "tool_result_full_chars": tool_result_full_chars,
        "tool_result_content_chars": tool_result_content_chars,
        "max_tool_result_content_chars": max_tool_result,
        "biggest_tool_result": biggest_tool,
        "model_counts": model_counts,
        "request_header_count": header_count,
        "header_tools": None if header_tools is None else {
            k: v for k, v in header_tools.items() if k != "names"
        },
        "header_tool_names": (header_tools or {}).get("names"),
        "turn_ends": turn_ends,
        "user_messages": user_messages,
        "types": types,
    }
    if "--full" not in sys.argv:
        out.pop("header_tool_names")
    print(json.dumps(out, indent=1))


main()
