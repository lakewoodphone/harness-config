#!/usr/bin/env python3
"""02-tool-bodies.py -- which ACTIVE registered tools have no implementation on this node.

THE MEASUREMENT THAT FOUND THE OUTAGE. Measured 2026-10-12 on secratary-cloud, hours after the cloud
cutover (docs/mesh/171, root cause R1):

    registry entries total      : 608
    status=active               : 607
      active WITH body file     : 8
      active WITHOUT body file  : 599   <-- unreachable via /tools/run

`run_tool()` answers `Tool <name> not found` from a single `if not tool_path.exists()`, so a
registered tool with no body and a tool that was never registered produce IDENTICAL text. Nothing
detected the difference for a full day, and every agent that called `ps_search` was told its tool did
not exist.

This script is the measurement. The thing that PREVENTS the recurrence is
`scripts/guards/tool-body-guard.py`, which runs on a clock and exits non-zero.

USAGE
    python3 02-tool-bodies.py [--root DIR] [--json] [--only NAME]
    python3 02-tool-bodies.py --diff-a DIR_A --diff-b DIR_B   # compare two checkouts' bodies

Exit: 0 every active tool has a body / 1 at least one does not / 2 could not check (never a pass).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def resolve_root(explicit: str | None) -> Path | None:
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    for var in ("TOOL_BODY_ROOT", "FA_CHECKOUT"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
    home = Path(os.path.expanduser("~"))
    cands += [home / "personal-secretary-mvp", home / "code" / "personal-secretary-mvp", Path("/opt/company")]
    for c in cands:
        if (c / "data" / "tool_registry.json").is_file():
            return c
    return None


def check(root: Path) -> dict:
    reg_path = root / "data" / "tool_registry.json"
    tdir = root / "data" / "tools"
    with open(reg_path, encoding="utf-8") as fh:
        reg = json.load(fh)
    tools = reg.get("tools")
    if not isinstance(tools, dict):
        raise ValueError(f"{reg_path} has no 'tools' object")
    active = {n for n, t in tools.items() if (t or {}).get("status") == "active"}
    missing = sorted(n for n in active if not (tdir / f"{n}.py").is_file())
    return {
        "root": str(root),
        "registered_total": len(tools),
        "deprecated": sum(1 for t in tools.values() if (t or {}).get("status") == "deprecated"),
        "active_total": len(active),
        "active_with_body": len(active) - len(missing),
        "active_without_body": len(missing),
        "missing": missing,
    }


def digest(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def diff_bodies(a: Path, b: Path) -> int:
    """Compare two checkouts' tool bodies. Used to prove a restore is complete without clobbering."""
    ta, tb = a / "data" / "tools", b / "data" / "tools"
    if not ta.is_dir() or not tb.is_dir():
        print(f"02-tool-bodies: both roots need data/tools -- {ta} / {tb}", file=sys.stderr)
        return 2
    na = {p.name for p in ta.glob("*.py")}
    nb = {p.name for p in tb.glob("*.py")}
    print(f"A {ta}  ({len(na)} .py)")
    print(f"B {tb}  ({len(nb)} .py)")
    print(f"\nonly in A: {len(na - nb)}")
    print(f"only in B: {len(nb - na)}")
    same = newer_a = newer_b = 0
    for n in sorted(na & nb):
        if digest(ta / n) == digest(tb / n):
            same += 1
        elif (ta / n).stat().st_mtime > (tb / n).stat().st_mtime:
            newer_a += 1
        else:
            newer_b += 1
    print(f"identical: {same} | A newer: {newer_a} | B newer: {newer_b}")
    print("\nB-only names are the ones a restore from A would ADD; they are the migration loss.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="active registered tools with no implementation")
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="print just this tool's status")
    ap.add_argument("--diff-a")
    ap.add_argument("--diff-b")
    a = ap.parse_args()

    if a.diff_a and a.diff_b:
        return diff_bodies(Path(a.diff_a), Path(a.diff_b))

    root = resolve_root(a.root)
    if root is None:
        print("02-tool-bodies: no checkout with data/tool_registry.json found "
              "(--root, $TOOL_BODY_ROOT, $FA_CHECKOUT, ~/personal-secretary-mvp, /opt/company) "
              "-- NOTHING was checked", file=sys.stderr)
        return 2
    try:
        f = check(root)
    except (ValueError, OSError) as exc:
        print(f"02-tool-bodies: could not check -- {exc}", file=sys.stderr)
        return 2

    if a.only:
        state = "NO BODY" if a.only in f["missing"] else "has a body"
        print(f"{a.only}: {state}")
        return 1 if a.only in f["missing"] else 0

    if a.json:
        print(json.dumps(f, indent=2))
    else:
        print(f"checkout ................ {f['root']}")
        print(f"registered tools ........ {f['registered_total']}  ({f['deprecated']} deprecated)")
        print(f"active tools ............ {f['active_total']}")
        print(f"  with a body ........... {f['active_with_body']}")
        print(f"  WITHOUT a body ........ {f['active_without_body']}")
        if f["missing"]:
            print("\nACTIVE TOOLS WITH NO IMPLEMENTATION -- each is advertised to agents and fails at")
            print("call time with `Tool <name> not found`:")
            for n in f["missing"]:
                print(f"  {n}")
    return 0 if f["active_without_body"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
