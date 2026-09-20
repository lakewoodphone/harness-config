"""Quantify the tool-output share of prompt tokens over one session. Read-only.

Model: for each assistant step, the prompt on the wire is ~
      prefix_est + SUM(chars of every tool/result and user/assistant message already in context)
We scale the reconstructed characters to the MEASURED prompt tokens of that same
request (usage.totalTokens - outputTokens), so every step's own prompt is
calibrated and no global chars-per-token constant is invented.

Usage: python tokshare.py <session.v3.jsonl.zstd>
"""
import json
import sys

import zstandard

PATH = sys.argv[1]


def text_len(node):
    if isinstance(node, str):
        return len(node)
    if isinstance(node, list):
        return sum(text_len(x) for x in node)
    if isinstance(node, dict):
        return sum(text_len(v) for k, v in node.items()
                   if k in ("text", "output", "value", "content", "parts", "message"))
    return 0


steps = []
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
            try:
                ev = json.loads(line)
            except Exception:
                continue
            t = ev.get("type")
            if t == "tool/result":
                steps.append(("tool", text_len(ev.get("data"))))
            elif t == "assistant/message":
                u = (ev.get("data") or {}).get("usage") or {}
                steps.append(("req", (
                    (u.get("totalTokens") or 0) - (u.get("outputTokens") or 0),
                    u.get("inputTokens") or 0, u.get("cacheReadTokens") or 0)))
            elif t == "compaction/prune":
                steps.append(("prune", 0))

context = 0
tool_in_context = 0
reqs = 0
measured_prompt = 0
tool_tokens_charged = 0
prefix_est = None
prefix_mode = 0
withctx_total = 0
for kind, val in steps:
    if kind == "tool":
        context += val
        tool_in_context += val
    elif kind == "prune":
        pass
    else:
        prompt, inp, cache = val
        reqs += 1
        measured_prompt += prompt
        withctx_total += context
        if prefix_est is None:
            prefix_est = prompt - context
            if prefix_est <= 0:
                prefix_est = 0
        scale = prompt / (prefix_est + context) if (prefix_est + context) > 0 else 0
        tool_tokens_charged += tool_in_context * scale

print(json.dumps({
    "path": PATH,
    "requests": reqs,
    "measured_prompt_tokens": measured_prompt,
    "est_prefix_tokens_per_request": prefix_est,
    "final_context_chars": context,
    "final_tool_chars_in_context": tool_in_context,
    "est_share_of_prompt_tokens_from_tool_output": round(
        tool_tokens_charged / measured_prompt, 4) if measured_prompt else None,
    "est_tool_tokens_charged": round(tool_tokens_charged),
}, indent=1))
