#!/usr/bin/env python3
"""Repair two mechanical classes of `journal.py check` ERROR introduced by the
v2 migration's legacy absorption.

  1. `metadata sha=X does not match the body (Y)`
     The absorbed file kept a stale sha. The checker recomputes the hash from
     heading+body, so an absorbed entry whose bytes changed during filing is
     reported forever.
  2. `heading carries id L57 but the marker says L103, and no legacy_id explains it`
     Filing an entry under a new id while its heading keeps the legacy id is
     legal — but only when metadata records `legacy_id`. The absorption wrote
     the heading without that field, so the checker cannot tell an intentional
     re-filing from a corrupted marker.

Both are fixed by the same round-trip: parse with the tool's own `parse_entry`,
set `sha` to the hash the checker computes and `legacy_id` to the heading's id
token when they differ, then re-emit with the tool's own `entry_bytes`. Nothing
is hand-written, so the output is by construction the canonical form the tool
would have written itself.

Only entries that actually carry one of the two defects are rewritten, so the
blast radius is the broken set and not the whole tree.

    python journal/tools/repair-meta.py            # dry run, prints the plan
    python journal/tools/repair-meta.py --apply    # rewrite
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys


def load_journal(journal_py: pathlib.Path):
    spec = importlib.util.spec_from_file_location("journal_tool", journal_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def heading_id(j, kind: str, heading: str) -> str:
    spec = j.KINDS.get(kind)
    if not spec:
        return ""
    m = spec["regex"].match(heading)
    if not m:
        return ""
    return (m.groupdict().get("id") or "").strip()


def plan_for(j, path: pathlib.Path, kind: str):
    """Return (why, rewritten_text) or (None, original_text)."""
    original = j._rl(path)
    e = j.parse_entry(path, kind)
    if e["problems"] and not any(
        "does not match the body" in p or "no legacy_id explains it" in p
        for p in e["problems"]
    ):
        # Something else is wrong here; leave it for a human.
        return None, original

    token = heading_id(j, kind, e["heading"])
    needs_sha = bool(e["sha"]) and e["sha"] != e["hash"]
    needs_legacy = bool(token) and token != e["id_full"] and not e["legacy_id"]
    if not needs_sha and not needs_legacy:
        return None, original

    reasons = []
    if needs_sha:
        reasons.append("sha")
    if needs_legacy:
        reasons.append(f"legacy_id={token}")

    if needs_legacy:
        e["legacy_id"] = token
    e["sha"] = e["hash"]
    return ",".join(reasons), j.entry_bytes(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="journal directory")
    ap.add_argument("--apply", action="store_true", help="rewrite the files")
    args = ap.parse_args()

    journal_py = pathlib.Path(__file__).resolve().parent / "journal.py"
    j = load_journal(journal_py)
    root = pathlib.Path(args.root).resolve() if args.root else journal_py.parent.parent
    entries = root / "entries"

    if not entries.is_dir():
        print(f"no entries directory at {entries}", file=sys.stderr)
        return 2

    changed = skipped = 0
    by_reason: dict[str, int] = {}
    for kind in sorted(j.KINDS):
        d = entries / kind
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            reason, new_text = plan_for(j, path, kind)
            if reason is None:
                skipped += 1
                continue
            changed += 1
            by_reason[reason] = by_reason.get(reason, 0) + 1
            if args.apply:
                path.write_text(new_text, encoding="utf-8", newline="\n")
            elif changed <= 5:
                print(f"  would repair {path.name}: {reason}")

    verb = "repaired" if args.apply else "would repair"
    print(f"{verb} {changed} entr{'y' if changed == 1 else 'ies'}; left alone {skipped}")
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {reason}")
    if not args.apply and changed:
        print("\nre-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
