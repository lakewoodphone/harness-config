#!/usr/bin/env python3
"""tool-body-guard — every ACTIVE registered tool must have a body file on disk.

WHY THIS EXISTS, measured 2026-10-12. After the company's authority moved from the office box
`secratary` to the cloud box `secratary-cloud`, `data/tool_registry.json` arrived with 607 active
tools and `data/tools/` arrived with **8** `.py` files. 599 capabilities were registered, listed to
every agent as available, and had no implementation:

    $ curl -s -X POST localhost:8002/tools/run/comms_search -d '{"mode":"search","q":"battery"}'
    {"ok": false, "error": "Tool comms_search not found"}

`run_tool()` returns exactly that string from one line -- `if not tool_path.exists()` -- so "the
registry says it exists" and "the tool is missing" were indistinguishable to every caller. The
`ps_search` MCP tool, which the `fast-search` skill tells every agent to use, failed the same way.
The cause was structural, not accidental: `data/tools/` is in `.gitignore` (line 58), so no deploy
from any branch could ever carry those files, and the only copy in existence was on the box that
was being frozen. Nothing anywhere asserted that a registered tool had a body. This guard is that
assertion.

WHAT IT CHECKS. For every tool in the registry with `status == "active"`, that
`<checkout>/data/tools/<name>.py` exists. A tool with `status == "deprecated"` is not required to
have a body -- that is what the status field is for, and it is how this guard is kept honest rather
than noisy.

EXIT STATUS, so a dispatcher can gate on it:
    0  every active tool has a body
    1  at least one active tool has NO body      <- the regression this exists to catch
    2  the guard could not do its job (no registry, unreadable, bad --root) -- NEVER a pass

    A 2 is not a 0. "I could not check" must never be reported as "it is fine"; that conflation is
    the failure mode this whole estate keeps paying for.

USAGE
    tool-body-guard.py [--root DIR] [--json] [--write-status] [--selftest]

    --selftest   prove the checker can fail: build a synthetic registry that must be reported
                 broken, then fix it and require a pass. Exits 1 if the selftest itself fails.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

DEFAULT_STATUS = Path(os.path.expanduser("~")) / ".tool-body-guard" / "status.json"


def resolve_root(explicit: str | None) -> Path | None:
    """The checkout, resolved rather than assumed -- the mistake that started all of this."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("TOOL_BODY_ROOT")
    if env:
        candidates.append(Path(env))
    home = Path(os.path.expanduser("~"))
    candidates += [
        home / "personal-secretary-mvp",
        home / "code" / "personal-secretary-mvp",
        Path("/opt/company"),
    ]
    for c in candidates:
        if (c / "data" / "tool_registry.json").is_file():
            return c
    return None


def check(root: Path) -> dict:
    """Return the finding. Raises OSError/ValueError when it cannot do its job."""
    reg_path = root / "data" / "tool_registry.json"
    tdir = root / "data" / "tools"
    with open(reg_path, encoding="utf-8") as fh:
        reg = json.load(fh)
    tools = reg.get("tools")
    if not isinstance(tools, dict):
        raise ValueError(f"{reg_path} has no 'tools' object")

    active = [n for n, t in tools.items() if (t or {}).get("status") == "active"]
    missing = sorted(n for n in active if not (tdir / f"{n}.py").is_file())
    return {
        "root": str(root),
        "registry": str(reg_path),
        "tools_dir": str(tdir),
        "registered_total": len(tools),
        "active_total": len(active),
        "active_with_body": len(active) - len(missing),
        "active_without_body": len(missing),
        "missing": missing,
    }


def selftest() -> int:
    """A checker that has never failed is not known to be able to fail."""
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data" / "tools").mkdir(parents=True)
        reg = {
            "tools": {
                "has_body": {"status": "active"},
                "no_body": {"status": "active"},
                "retired_no_body": {"status": "deprecated"},
            }
        }
        (root / "data" / "tool_registry.json").write_text(json.dumps(reg), encoding="utf-8")
        (root / "data" / "tools" / "has_body.py").write_text("x=1\n", encoding="utf-8")

        got = check(root)
        if got["active_without_body"] != 1 or got["missing"] != ["no_body"]:
            print(f"  FAIL broken-case: expected exactly ['no_body'], got {got['missing']}")
            ok = False
        else:
            print("  ok   broken-case: reports exactly the active tool with no body")

        if "retired_no_body" in got["missing"]:
            print("  FAIL deprecated tool was reported as missing")
            ok = False
        else:
            print("  ok   a deprecated tool without a body is not a defect")

        (root / "data" / "tools" / "no_body.py").write_text("x=1\n", encoding="utf-8")
        got = check(root)
        if got["active_without_body"] != 0:
            print(f"  FAIL fixed-case: still reports {got['missing']}")
            ok = False
        else:
            print("  ok   fixed-case: passes once every active tool has a body")

        (root / "data" / "tool_registry.json").write_text("{ not json", encoding="utf-8")
        try:
            check(root)
            print("  FAIL unreadable-registry: no error raised -- a broken registry must not pass")
            ok = False
        except (ValueError, OSError):
            print("  ok   unreadable-registry: raises, so it can never be reported as a pass")

    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="assert every active registered tool has a body file")
    ap.add_argument("--root", help="the checkout holding data/tool_registry.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    root = resolve_root(a.root)
    if root is None:
        print("tool-body-guard: no checkout with data/tool_registry.json found "
              "(tried --root, $TOOL_BODY_ROOT, ~/personal-secretary-mvp, "
              "~/code/personal-secretary-mvp, /opt/company) -- NOTHING was checked", file=sys.stderr)
        return 2
    try:
        finding = check(root)
    except (ValueError, OSError) as exc:
        print(f"tool-body-guard: could not check -- {exc}", file=sys.stderr)
        return 2

    finding["checked_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    finding["verdict"] = "ok" if finding["active_without_body"] == 0 else "MISSING_BODIES"

    if a.json:
        print(json.dumps(finding, indent=2))
    else:
        f = finding
        print(f"checkout ................ {f['root']}")
        print(f"registered tools ........ {f['registered_total']}")
        print(f"active tools ............ {f['active_total']}")
        print(f"  with a body ........... {f['active_with_body']}")
        print(f"  WITHOUT a body ........ {f['active_without_body']}")
        if f["missing"]:
            print("\nACTIVE TOOLS WITH NO IMPLEMENTATION -- every one of these is advertised to agents"
                  " and fails at call time with 'Tool <name> not found':")
            for n in f["missing"]:
                print(f"  {n}")

    if a.write_status:
        DEFAULT_STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = DEFAULT_STATUS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(finding, indent=2), encoding="utf-8")
        tmp.replace(DEFAULT_STATUS)

    return 0 if finding["active_without_body"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
