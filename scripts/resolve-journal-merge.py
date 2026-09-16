#!/usr/bin/env python3
"""Resolve cross-machine id collisions in a journal merge so NO record is lost.

WHY THIS EXISTS
Two machines both allocated the same journal id to DIFFERENT entries -- measured 2026-09-15 on
ZABZ-TECH: fourteen ids meant two different entries (D185, D186, H322-H328, L1637-L1639, W149,
W150). The cause is fixed at the source now (git_max reads remote-tracking refs, so a fetched
machine sees the other's numbers before choosing its own), but it cannot repair collisions that
already exist. When such a history is merged, every one of those ids appears as an **add/add
conflict**: one path, two different records.

Dropping either side is data loss in the one place this system promises not to lose it, so this
resolves a conflict by KEEPING BOTH and renaming one:
  * the entry with the EARLIER timestamp keeps the id it was given (the id was allocated then);
  * the other is renumbered to the next free id for its kind, with every self-reference inside it
    rewritten to the new id;
  * an alias row (alias_id -> canonical_id) is written so `resolve_alias()` still maps the old id,
    and no id ever means two things again.

USAGE (in a throwaway worktree, never in the live checkout)
    git worktree add --detach <tmp> master
    git -C <tmp> merge origin/master            # expect add/add conflicts on entries/**
    python scripts/resolve-journal-merge.py <tmp>
    git -C <tmp> add -A && git -C <tmp> commit --no-edit
    python <tmp>/journal/tools/journal.py check # must be 0 errors

Read-only outside the given worktree. Prints every decision it makes.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

KINDS = {"lessons": "L", "handoff": "H", "pain": "P", "decisions": "D", "wins": "W"}
MARKER = re.compile(r"<!--\s*e:([a-z]+)\|([A-Za-z0-9]+)\|([^|]*)\|")
CONFLICT = re.compile(r"^<<<<<<< HEAD\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n", re.S | re.M)
ALIAS_HEADER = "alias_id\tkind\tcanonical_id\treason\tdate"


def git(wt: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True).stdout


def stamp_of(text: str) -> str:
    m = MARKER.search(text)
    return m.group(3).strip() if m else ""


def id_of(text: str) -> str:
    m = MARKER.search(text)
    return m.group(2) if m else ""


def kind_of(path: Path) -> str:
    return path.parent.name


def ceiling(wt: Path, kind: str) -> int:
    """Highest number in use for `kind` anywhere in the merged tree."""
    top = 0
    d = wt / "journal" / "entries" / kind
    if d.is_dir():
        for f in d.iterdir():
            m = re.match(r"[A-Z](\d+)", f.stem)
            if m:
                top = max(top, int(m.group(1)))
    return top


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    wt = Path(sys.argv[1]).resolve()
    if not (wt / "journal" / "entries").is_dir():
        print(f"not a journal worktree: {wt}", file=sys.stderr)
        return 2

    conflicted = [Path(p) for p in git(wt, "diff", "--name-only", "--diff-filter=U").split("\n") if p.strip()]
    entries = [p for p in conflicted if p.parts[0] == "journal" and "entries" in p.parts]
    others = [p for p in conflicted if p not in entries]
    print(f"conflicted: {len(conflicted)} total -- {len(entries)} entries, {len(others)} index/other")
    if not entries:
        print("nothing to resolve")
        return 0

    moves = []          # (kind, old_id, new_id, text)
    for rel in entries:
        path = wt / rel
        text = path.read_text(encoding="utf-8")
        m = CONFLICT.search(text)
        if not m:
            print(f"  ! {rel}: no conflict markers (already resolved?)")
            continue
        ours, theirs = m.group(1), m.group(2)
        so, st = stamp_of(ours), stamp_of(theirs)
        # Earlier stamp keeps the id. Ties (same minute) keep HEAD, deterministically.
        if st and so and st < so:
            keeper, mover = theirs, ours
        else:
            keeper, mover = ours, theirs
        path.write_text(keeper, encoding="utf-8", newline="\n")
        kind = kind_of(path)
        old = id_of(mover)
        print(f"  {rel}: keeps {id_of(keeper)} ({stamp_of(keeper) or 'no stamp'}); "
              f"moves {old} ({stamp_of(mover) or 'no stamp'})")
        moves.append([kind, old, None, mover])

    # Allocate AFTER all keepers are written, so the ceiling sees every surviving id.
    used = {k: ceiling(wt, k) for k in KINDS}
    for mv in moves:
        kind, old = mv[0], mv[1]
        used[kind] = used.get(kind, 0) + 1
        mv[2] = f"{KINDS.get(kind, 'X')}{used[kind]}"

    alias_rows = []
    for kind, old, new, text in moves:
        body = re.sub(r"\b%s\b" % re.escape(old), new, text)
        (wt / "journal" / "entries" / kind / f"{new}.md").write_text(body, encoding="utf-8", newline="\n")
        alias_rows.append("\t".join([
            old, kind, new,
            "cross-machine id collision: two machines allocated the same id; renamed on merge",
            "2026-09-16",
        ]))
        print(f"  moved {old} -> {new} ({kind})")

    # aliases.tsv is append-only rows: a union is the correct resolution, then our new rows on top.
    apath = wt / "journal" / "index" / "aliases.tsv"
    raw = apath.read_text(encoding="utf-8") if apath.exists() else ""
    if "<<<<<<<" in raw:
        cm = CONFLICT.search(raw)
        ours = cm.group(1) if cm else ""
        theirs = cm.group(2) if cm else ""
        seen, merged = set(), [ALIAS_HEADER]
        for ln in (ours + theirs).split("\n"):
            ln = ln.rstrip("\r")
            if not ln.strip() or ln.startswith("alias_id\t") or ln in seen:
                continue
            seen.add(ln)
            merged.append(ln)
        raw = "\n".join(merged) + "\n"
        print(f"  aliases.tsv: union resolved -> {len(merged) - 1} rows")
    rows = [ln.rstrip("\r") for ln in raw.split("\n") if ln.strip()]
    if not rows or not rows[0].startswith("alias_id"):
        rows = [ALIAS_HEADER] + rows
    have = set(rows)
    added = [r for r in alias_rows if r not in have]
    apath.write_text("\n".join(rows + added) + "\n", encoding="utf-8", newline="\n")
    print(f"  aliases.tsv: +{len(added)} alias rows")

    # entries.tsv is a generated cache: take one side, then rebuild it from entries/.
    epath = wt / "journal" / "index" / "entries.tsv"
    if epath.exists() and "<<<<<<<" in epath.read_text(encoding="utf-8"):
        cm = CONFLICT.search(epath.read_text(encoding="utf-8"))
        epath.write_text(cm.group(1) if cm else "", encoding="utf-8", newline="\n")
        print("  entries.tsv: took one side; rebuild with `journal.py index` after the merge")

    print(f"\nresolved {len(moves)} collision(s). Next: git add -A, commit, then journal.py index "
          f"and journal.py check (must be 0 errors).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
