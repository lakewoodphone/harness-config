#!/usr/bin/env python3
"""search — the estate's one search tool for every DSH agent.

Registered as a dynamic tool in `data/tools/search.py` on the authority, so it is reachable as
`ps_action("search", {...})` from every agent session whose secretary MCP server is mounted, on
Windows, Linux and macOS alike.

CANONICAL COPY: this file. `data/tools/` is GITIGNORED in the company repo (`.gitignore:58`), and
that is how 599 of 607 registered tool bodies were lost at the 2026-10-12 cutover. Anything that
runs from `data/tools/` must exist here first, and `scripts/guards/tool-body-guard.py` is what
notices when it does not.

WHAT CHANGED 2026-10-18, and why
--------------------------------
Until today this body shelled out to `find-anything` (`fa`) for every request. `fa` is excellent at
what it is for — a live symbol lookup, a scoped ripgrep, a filename index — but it is not a search
*engine*: it has no content index, so it answers "where is this string in code I can see from this
node", not "what did we ever say about the mesh broker, on any machine, in any session".

The estate now has `esearch` (unified-search/server/esearch.py): one read-only HTTP surface over
`authority.db` (every DSH session, memories, VS Code chats — indexed in place) and the central
estate index (documents, code, journal, git, mail). This body calls it, and keeps `fa` for the two
questions an index must never answer:

  * `what="symbol"` — you may be about to edit that definition, so it is always a live scan.
  * `fresh=True`    — bypass every index, by request.

`what` now understands what the owner actually asks for:

    sessions   every session with the agent, on any machine   (new — this did not exist before)
    all        everything, merged, with provenance             (new)
    docs       documents: md, pdf, docx, xlsx, txt, html
    code       source files
    journal    the agent's own journal
    mail       email
    memory     saved memories
    chats      VS Code / Copilot chats
    files      filename search        (fa — path index, ~40 ms)
    data       business comms         (fa — the comms FTS)
    symbol     where is this defined  (fa — always live)

A refusal is never a negative. When a corpus is absent, stale or unanswered, the result says so in
`did_not_answer`, and `ok` stays true only because the answer is "I could not look there", which is
not the same as "it is not there".
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ESEARCH_SCOPES = {"all", "sessions", "docs", "code", "journal", "mail", "comms", "memory",
                  "chats", "estate", "data"}
FA_ONLY = {"symbol", "files"}
WHAT = ESEARCH_SCOPES | FA_ONLY
TIMEOUT = 30
FA_TIMEOUT = 45


def _esearch_url() -> str:
    import os
    return (os.environ.get("ESEARCH_URL") or "http://127.0.0.1:3095").rstrip("/")


def _resolve_fa() -> str:
    """Where the live-scan engine is on THIS node. Resolved per call, never bound at import.

    It used to be a module-level constant pointing at `/home/zabz/bin/find-anything`, a path that
    exists on no cloud node; after the 2026-10-12 cutover every search from every agent returned
    "search backend missing" and a long-lived API process could never pick up a corrected PATH.
    """
    import os
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


def _render(resp: dict) -> str:
    lines = ["%d hit(s) in %d ms · scope=%s · live=false"
             % (resp.get("count", 0), resp.get("ms", 0), resp.get("scope", "all"))]
    ages = []
    for st in resp.get("stores", []):
        if st.get("answered"):
            age = st.get("age_s")
            ages.append("%s %s" % (st["name"], ("%dm" % (age // 60)) if isinstance(age, int) else "age unknown"))
        else:
            ages.append("%s REFUSED" % st["name"])
    if ages:
        lines.append("stores: " + " · ".join(ages))
    for h in resp.get("hits", []):
        lines.append("")
        lines.append("%2d. [%s] %s" % (h.get("rank", 0), h.get("kind"), (h.get("title") or "")[:110]))
        meta = "    %s · %s · %s" % (h.get("host") or "?", h.get("when") or "?", h.get("locator") or "")
        lines.append(meta.rstrip(" ·"))
        if h.get("snippet"):
            lines.append("    " + str(h["snippet"]).replace("\n", " ")[:300])
    if resp.get("did_not_answer"):
        lines.append("")
        lines.append("DID NOT ANSWER (a refusal, not a negative):")
        for d in resp["did_not_answer"]:
            lines.append("  - %s: %s" % (d.get("store"), d.get("reason")))
    return "\n".join(lines)


def _esearch(query: str, what: str, limit: int) -> dict:
    # `data` is the business comms corpus (texts, calls, voicemails). It is a projection of the
    # maintained comms index into the estate index, so it is an indexed scope now, not a live scan.
    scope = "comms" if what == "data" else ("all" if what in ("all", "estate") else what)
    params = {"q": query, "limit": str(int(limit)), "json": "1", "scope": scope}
    url = _esearch_url() + "/search?" + urllib.parse.urlencode(params)
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=TIMEOUT) as fh:
        resp = json.loads(fh.read().decode("utf-8"))
    resp["ms"] = resp.get("ms") or int((time.time() - t0) * 1000)
    return resp


def _fa(query: str, what: str, limit: int, fresh: bool, max_age, all_: bool) -> dict:
    fa = _resolve_fa()
    cmd = [fa]
    if what != "auto":
        cmd.append(what)
    cmd += [query, "--limit", str(int(limit)), "--json"]
    if max_age is not None:
        cmd += ["--max-age", str(int(max_age))]
    if fresh:
        cmd.append("--fresh")
    if all_:
        cmd.append("--all")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=FA_TIMEOUT)
    except FileNotFoundError:
        # THE FALLBACK MUST BE ABLE TO FAIL HONESTLY. Measured 2026-10-18 on ZABZ-YOGA: with the
        # service pointed at a dead port, this raised FileNotFoundError out of the tool body and the
        # caller got a traceback instead of an answer. Windows nodes have no `fa` at all, so the
        # degraded path could never have worked there — and a traceback is the one answer a search
        # tool must never give, because it says nothing about what was and was not searched.
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "source": "no-engine",
                "searched": False, "exit_code": None,
                "result": "NEITHER ENGINE IS AVAILABLE: esearch did not answer, and find-anything is "
                          "not installed on this machine (%s). Nothing was searched — this is a "
                          "refusal, not a negative." % fa}
    except subprocess.TimeoutExpired:
        return {"ok": False, "ms": FA_TIMEOUT * 1000, "source": "timeout", "searched": False,
                "exit_code": None,
                "result": "find-anything did not finish in %ds — the search was aimed at too much; "
                          "narrow it or use scope='sessions'" % FA_TIMEOUT}
    ms = int((time.time() - t0) * 1000)
    out, rc = p.stdout, p.returncode
    if not shutil.which(fa) and not out:
        return {"ok": False, "ms": ms, "source": "missing-backend", "searched": False,
                "exit_code": rc, "result": "search backend missing: %s (and esearch was unreachable)" % fa}
    note = ""
    if rc == 4:
        note = "NOTHING WAS SEARCHED (exit 4): no index on this node, or a root was cut off. Not a negative."
    elif rc == 3:
        note = "answered from a possibly stale index (exit 3)."
    elif rc == 1:
        note = "no match — a real negative from a live scan."
    elif rc not in (0,):
        note = "engine exited %d." % rc
    try:
        payload = json.loads(out) if out.strip().startswith(("{", "[")) else out
    except ValueError:
        payload = out
    if isinstance(payload, dict):
        payload.setdefault("ok", rc in (0, 1, 3))
        payload["searched"] = rc not in (2, 4, 5)
        payload["exit_code"] = rc
        payload["ms"] = ms
        payload["source"] = "find-anything:" + what
        if note:
            payload["note"] = note
        return payload
    return {"ok": rc in (0, 1, 3), "result": out.strip() or "(no output)", "source": "find-anything:" + what,
            "ms": ms, "exit_code": rc, "searched": rc not in (2, 4, 5), "note": note}


def run(query: str = "", what: str = "auto", limit: int = 8, fresh: bool = False,
        max_age: int | None = None, all: bool = False, **kwargs) -> dict:
    what = (what or "auto").strip().lower()
    if what not in WHAT:
        return {"ok": False, "searched": False,
                "result": "unknown 'what': %r. Use one of: %s" % (what, ", ".join(sorted(WHAT)))}
    query = (query or kwargs.get("q") or "").strip()
    if not query:
        return {"ok": False, "searched": False,
                "result": "no query given. Example: search(query='phone gate', what='sessions')"}

    if all:
        banner = ("WARNING: all=True walks the WHOLE tree and ignores the curated scope. "
                  "Narrow it: what='code' or what='sessions'.")
    else:
        banner = ""

    # 1. The two questions an index must never answer.
    if fresh or what in FA_ONLY:
        res = _fa(query, what, limit, fresh, max_age, all)
        if banner:
            res["result"] = banner + "\n" + str(res.get("result", ""))
        return res

    # 2. The indexed surface.
    t0 = time.time()
    try:
        resp = _esearch(query, what, limit)
        text = _render(resp)
        if banner:
            text = banner + "\n" + text
        return {"ok": True, "result": text, "source": "esearch", "ms": resp.get("ms", int((time.time() - t0) * 1000)),
                "stale": any(d for d in resp.get("did_not_answer", [])), "exit_code": 0,
                "searched": bool(resp.get("stores")), "hits": resp.get("hits", []),
                "did_not_answer": resp.get("did_not_answer", []),
                "stores": resp.get("stores", [])}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # 3. Degrade, and SAY SO. A silent fallback is how a stale index became a week of wrong
        #    answers (D2983, P3162): the caller must be able to tell which engine answered.
        fallback = "auto" if what in ("all", "estate", "sessions", "docs", "memory", "chats") else what
        res = _fa(query, fallback, limit, fresh, max_age, all)
        res["degraded"] = "esearch unreachable (%s); answered by find-anything" % str(exc)[:120]
        res["source"] = "find-anything (degraded): " + str(res.get("source"))
        if banner:
            res["result"] = banner + "\n" + str(res.get("result", ""))
        return res


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:])
    print(json.dumps(run(query=q), indent=2)[:4000])
