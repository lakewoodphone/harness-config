"""search — the fast, scope-aware search tool for every DSH agent.

Registered as a dynamic tool in data/tools/, so it is reachable as
`ps_action("search", {...})` from EVERY agent session that has the secretary
MCP server mounted -- Windows, Linux and macOS alike. That reachability is the
whole point: a CLI only helps an agent that already knows it exists; an MCP
tool appears in the agent's tool list.

It shells out to the `find-anything` engine (the single coherent surface), located on this node by
`_resolve_fa()`. There is exactly ONE grammar and ONE implementation; this module adds no second
grammar, and no second absolute path.

Args:
    what:   code | data | journal | files | symbol | auto   (default: auto)
    query:  the thing to find.
    limit:  max hits (default 8).
    fresh:  bypass every index (use when you are about to edit).
    max_age: staleness ceiling in seconds for indexed answers. LEAVE IT UNSET unless you mean
            it. Each index already carries its own ceiling (path/ctags 1200 s; comms 2100 s) and,
            more importantly, an unset ceiling lets `fa journal` answer from CONTENT COVERAGE
            instead of age. Setting it forces an age test on the journal, and because that index
            is written only when the journal changes, a healthy but quiet index then reports
            STALE. Measured 2026-10-08: the previous forced 1200 returned stale=true ("the index
            is behind") for an index holding 3157 of 3157 entries - a false alarm that fires for
            ~15 minutes of every 30-minute comms cycle.
    all:    opt OUT of the curated scope. Slow. Prints a warning.

Returns:
    {"ok": bool, "result": str, "source": str, "ms": int, "stale": bool,
     "exit_code": int, "searched": bool}
      ok=False with searched=False means NOTHING WAS SEARCHED (exit 4/5/2): a refusal, not a
      negative. A real negative is ok=True with exit_code=1, and says so in `result`.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time


def _resolve_fa() -> str:
    """Where the search engine is on THIS node, resolved rather than assumed.

    ORDER, and why each step is here:
      1. `FIND_ANYTHING_BIN` -- an operator's explicit override always wins.
      2. `fa` / `find-anything` on PATH -- true on every node that has the engine installed
         (`/usr/local/bin/fa` on secratary-cloud; `/home/zabz/bin/find-anything` on the office box).
      3. The two absolute paths, last, so a node that worked before this change still works.

    WHY THIS IS A FUNCTION AND NOT A CONSTANT. It used to be
    `os.environ.get("FIND_ANYTHING_BIN", "/home/zabz/bin/find-anything")`. Measured 2026-10-12 on the
    authority after the cloud cutover: that path exists on no cloud node, so every search from every
    agent returned `search backend missing` -- and because a module-level constant is bound once, a
    long-lived API process could never pick up a corrected PATH either. Resolving per call costs one
    `shutil.which` and cannot go stale.
    """
    env = os.environ.get("FIND_ANYTHING_BIN")
    if env:
        return env
    found = shutil.which("fa") or shutil.which("find-anything")
    if found:
        return found
    for p in ("/usr/local/bin/find-anything", "/home/zabz/bin/find-anything"):
        if os.path.exists(p):
            return p
    return "/usr/local/bin/find-anything"


TIMEOUT = 45

_WHAT = {"code", "data", "journal", "files", "symbol", "auto"}


def run(
    query: str = "",
    what: str = "auto",
    limit: int = 8,
    fresh: bool = False,
    max_age: int | None = None,
    all: bool = False,
    **kwargs,
) -> dict:
    what = (what or "auto").strip().lower()
    if what not in _WHAT:
        return {"ok": False, "result": f"unknown 'what': {what!r}. Use one of: {', '.join(sorted(_WHAT))}"}
    query = (query or kwargs.get("q") or "").strip()
    if not query:
        return {"ok": False, "result": "no query given. Example: search(query='owner sms gate')"}

    if all:
        banner = ("WARNING: all=True walks the WHOLE tree and ignores the curated scope. "
                  "This is the 101-second habit. Narrow it: what='code' (default scope) is ~110 ms.")
    else:
        banner = ""

    fa = _resolve_fa()
    cmd = [fa]
    if what != "auto":
        cmd.append(what)
    cmd += [query, "--limit", str(int(limit)), "--json"]
    if max_age is not None:
        # An explicit ceiling is the caller's business. Omitting it is what lets each index apply
        # its own rule, and lets the journal answer from coverage rather than from age.
        cmd += ["--max-age", str(int(max_age))]
    if fresh:
        cmd.append("--fresh")
    if all:
        cmd.append("--all")

    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        ms = int((time.time() - t0) * 1000)
        out, rc = p.stdout, p.returncode
    except subprocess.TimeoutExpired:
        return {"ok": False, "ms": TIMEOUT * 1000, "source": "timeout",
                "result": f"search exceeded {TIMEOUT}s and was killed. Narrow the scope: what='code' or what='journal'."}
    except FileNotFoundError:
        return {"ok": False, "source": "unavailable",
                "result": f"search backend missing at {fa}. This search fell back to nothing -- do not fall back to `grep -r`."}

    stale = rc == 3
    # 0 = hits, 1 = a real negative, 2 = bad usage, 3 = stale index, 4 = NOTHING was searched,
    # 5 = the index failed. Only 3 was read before, so a refusal (4/5) reached the agent as
    # ok:true "(no hits)" - the exact lie this tool exists to prevent. Measured 2026-10-08 with a
    # stub backend: exits 4, 5 and 1 all returned {"ok": true, "result": "(no hits)"}, and the
    # stderr explanation that `fa` writes for each was captured and then never looked at.
    refused = rc in (2, 4, 5)
    negative = rc == 1
    err = (p.stderr or "").strip()

    parsed = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except Exception:
            pass

    body = out.strip()
    if len(body) > 4000:
        body = body[:4000] + "\n... (truncated)"

    if refused:
        body = (f"REFUSED (exit {rc}) - NOTHING WAS SEARCHED, this is not 'no match'.\n"
                + (err + "\n" if err else "") + body)
    elif negative:
        body = ("NO MATCH (exit 1: the scope was searched and holds nothing)."
                + ("\n" + body if body else ""))

    result = {"ok": not refused, "result": (banner + "\n" + body).strip() or "(no hits)",
              "source": _source_of(parsed, what), "ms": ms, "stale": stale,
              "exit_code": rc, "searched": not refused}
    if refused:
        result["error"] = f"search backend refused (exit {rc}): nothing was searched"
    if err:
        result["stderr"] = err[:500]
    if stale:
        result["result"] = ("STALE: the index is older than its ceiling; treat this as a hint, "
                            "not truth. Re-run with fresh=True before editing.\n" + result["result"])
    return result


def _source_of(parsed, what):
    for row in parsed:
        if isinstance(row, dict) and row.get("source"):
            return str(row["source"])
    return what
