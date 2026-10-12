#!/usr/bin/env python3
"""Register `search` in the dynamic-tool registry so agents can SEE it.

WHY THIS IS NEEDED. The action dispatcher falls through to `_exec_dynamic_tool(action_name, params)`
(`app/chat_action_runtime.py`), which runs `data/tools/<name>.py`, so an agent that already knows the
name can call it. But `list_tools()` only returns builtins plus registry entries with status `active`
(`app/tool_factory.py`), and `get_tool_summary()` is what goes into the LLM's context -- so an
unregistered tool is invisible to every agent that was not told about it by hand.

MEASURED 2026-10-12 on secratary-cloud, after the cloud cutover: `data/tools/search.py` was missing
entirely, and even once restored the registry held no `search` entry -- 608 tools registered, `search`
not among them. `ps_search` called `/tools/run/search` and got `Tool search not found`. The
`fast-search` skill tells every agent on the estate to call exactly that name.

Idempotent: re-running updates the description and bumps the version, leaving the rest alone. It uses
the app's own `_save_registry`, which keeps a `.bak` of the previous JSON.

USAGE
    register-search-tool.py [--checkout DIR] [--dry-run]
    (run it with the CHECKOUT's interpreter: /opt/company/.venv/bin/python)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path


def resolve_checkout(explicit: str | None) -> Path | None:
    """The APP checkout -- which is NOT the repo this script lives in.

    harness-config and the app are two repositories with two different roots. Reading the app root off
    `__file__` (parents[2] of this script) resolves to harness-config, so `import app.tool_factory`
    raises ModuleNotFoundError and the tool silently stays unregistered. Probed instead, exactly as
    `find-anything` and `tool-body-guard.py` resolve theirs.
    """
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    for var in ("FA_CHECKOUT", "TOOL_BODY_ROOT"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
    home = Path(os.path.expanduser("~"))
    cands += [
        home / "personal-secretary-mvp",
        home / "code" / "personal-secretary-mvp",
        Path("/opt/company"),
    ]
    for c in cands:
        if (c / "app" / "tool_factory.py").is_file():
            return c
    return None


DESCRIPTION = (
    "SEARCH THE ESTATE (code, business data, journal, files, symbols). Use this instead of a "
    "recursive grep, `rg -uuu`, or a filesystem walk. ONE grammar, every machine, indexed where an "
    "index exists. Reach for it before any other way of looking for something."
)
SPECIFICATION = (
    "Backed by the `find-anything` engine (harness-config/scripts/find-anything/find-anything), which "
    "this node resolves via FIND_ANYTHING_BIN, then `fa` on PATH, then two legacy absolute paths. "
    "Params: query, what (code|data|journal|files|symbol|auto), limit, fresh. "
    "what='symbol' is ALWAYS a live scan and must be used before editing. what='data' reads the comms "
    "FTS index (~/.fsearch/comms.db). Every indexed answer carries provenance: source, index_age_s, "
    "and for the journal covers_through. Exit codes are the contract: 0 hits, 1 a real negative, "
    "2 bad usage, 3 answered but possibly stale, 4 NOTHING was searched, 5 the index failed. A 4 is a "
    "refusal, never a negative."
)


def main() -> int:
    ap = argparse.ArgumentParser(description="register the `search` dynamic tool")
    ap.add_argument("--checkout", help="the app checkout holding data/tool_registry.json")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, write nothing")
    a = ap.parse_args()

    root = resolve_checkout(a.checkout)
    if root is None:
        print("register-search-tool: no app checkout found (tried --checkout, $FA_CHECKOUT, "
              "$TOOL_BODY_ROOT, ~/personal-secretary-mvp, ~/code/personal-secretary-mvp, "
              "/opt/company); NOTHING was registered", file=sys.stderr)
        return 2
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from app.tool_factory import _load_registry, _save_registry
    except Exception as exc:  # noqa: BLE001
        print(f"register-search-tool: cannot import the tool factory from {root} -- {exc}; "
              f"NOTHING was registered", file=sys.stderr)
        return 2

    reg = _load_registry()
    tools = reg.setdefault("tools", {})
    existing = tools.get("search")

    # A `search` entry pointing at a file that does not exist is the exact defect this whole exercise
    # is about, so refuse to write one.
    body = root / "data" / "tools" / "search.py"
    if not body.is_file():
        print(f"register-search-tool: refusing to register -- the body is missing at {body}. "
              f"Run scripts/find-anything/install.sh first.", file=sys.stderr)
        return 2

    entry = {
        "name": "search",
        "description": DESCRIPTION,
        "specification": SPECIFICATION,
        "category": "search",
        "file": "data/tools/search.py",
        "status": "active",
        "created_at": (existing or {}).get("created_at")
                      or dt.datetime.now(dt.timezone.utc).isoformat(),
        "version": int((existing or {}).get("version", 0)) + 1,
        "builtin": False,
    }
    if a.dry_run:
        print(f"would register (checkout {root}):")
        print(json.dumps(entry, indent=2))
        return 0

    tools["search"] = entry
    _save_registry(reg)
    print(f"registered search (version {entry['version']}) in {root}; "
          f"registry now holds {len(tools)} tools")
    print("previous entry:", "updated" if existing else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
