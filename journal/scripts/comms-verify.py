#!/usr/bin/env python3
"""Assert the comms read-path end to end, through the live HTTP dispatcher.

Every check is a claim an agent would make. Failure prints what actually came back,
because "the tool is broken" and "the tool answered something else" need different fixes.
"""
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
KEY = ""
for line in (ROOT / ".env").read_text(errors="replace").splitlines():
    if line.startswith("DASHBOARD_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
URL = "http://localhost:8002/tools/run/comms_search"

fails = []


def call(payload: dict) -> dict:
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-ps-api-key": KEY})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def check(name: str, ok: bool, detail: str = ""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   -> " + detail) if detail else ""))
    if not ok:
        fails.append(name)


print("=== HTTP path: parameters an agent actually sends ===")
d = call({"query": "water damage", "limit": 3})
check("int limit is honoured (not dropped)", d.get("count") == 3,
      f"count={d.get('count')} match={d.get('match_mode')}")
check("guessed arg name query= works", d.get("ok") and d.get("query") == "water damage",
      f"query={d.get('query')!r}")

d = call({"mode": "search", "q": "screen replacement?", "limit": 5})
check("trailing punctuation does not break FTS5", bool(d.get("ok")) and d.get("count", 0) > 0,
      f"err={d.get('error')}")

d = call({"mode": "search", "q": "water damage", "exact": True, "limit": 3})
check("bool exact=true survives the endpoint", bool(d.get("ok")),
      f"match={d.get('match_mode')} err={d.get('error')}")

d = call({"mode": "search", "q": "when did we last talk about a cracked iphone screen"})
loose = [r for r in (d.get("results") or [])[:3]]
top = " ".join(str(r.get("match") or r.get("text") or "") for r in loose).lower()
check("a whole sentence falls back to any-term", d.get("match_mode") == "any-term",
      f"match={d.get('match_mode')}")
check("the loose answer is about the question, not the word 'a'",
      ("screen" in top) or ("crack" in top), f"top3={top[:150]!r}")

print()
print("=== the modes an agent needs ===")
d = call({"mode": "thread", "party": "Dovid", "limit": 5})
check("thread by name", bool(d.get("ok")) and d.get("count", 0) > 0,
      f"err={d.get('error')}")
d = call({"mode": "person", "party": "Dovid", "limit": 5})
check("person resolves a name", bool(d.get("ok")) and bool(d.get("people")),
      f"err={d.get('error')}")
d = call({"mode": "waiting", "limit": 3})
check("waiting returns customers", bool(d.get("ok")) and "total_waiting" in d,
      f"err={d.get('error')}")
d = call({"mode": "health"})
check("health reports completeness", bool(d.get("ok")) and d.get("total", 0) > 100000,
      f"total={d.get('total')}")

print()
print("=== failure must be legible, never silent ===")
d = call({})
check("empty call explains what to pass", not d.get("ok") and "pass q" in str(d.get("error")),
      f"err={d.get('error')}")
d = call({"mode": "conversations", "q": "screen"})
check("unknown mode names the valid modes",
      not d.get("ok") and "waiting" in str(d.get("error")), f"err={d.get('error')}")
d = call({"q": "battery", "limit": 2, "sort": "relevant", "format": "markdown", "zzz": 1})
check("unknown arguments are ignored, not fatal", bool(d.get("ok")), f"err={d.get('error')}")
check("sort=relevant is honoured", d.get("rank") == "relevance", f"rank={d.get('rank')}")

print()
print("=== regression: the CLI, as cron and I call it ===")
import subprocess
R = subprocess.run([sys.executable, "/home/zabz/.fsearch/comms-search.py", "--json",
                    "search", "--party", "Dovid", "--limit", "3"],
                   capture_output=True, text=True, timeout=120)
try:
    d = json.loads(R.stdout)
    check("CLI search --party with no positional keywords",
          bool(d.get("ok")) and d.get("match_mode") == "filter-only",
          f"match={d.get('match_mode')} err={d.get('error')}" if d.get("ok")
          else f"err={d.get('error')}")
except Exception as e:
    check("CLI search --party with no positional keywords", False,
          f"{type(e).__name__}: {R.stdout[:120]} {R.stderr[:120]}")
R = subprocess.run([sys.executable, "/home/zabz/.fsearch/comms-search.py", "--json",
                    "health"], capture_output=True, text=True, timeout=120)
try:
    d = json.loads(R.stdout)
    check("CLI health still works", bool(d.get("ok")), f"err={d.get('error')}")
except Exception as e:
    check("CLI health still works", False, f"{type(e).__name__}: {R.stdout[:120]}")

print()
print(f"{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
