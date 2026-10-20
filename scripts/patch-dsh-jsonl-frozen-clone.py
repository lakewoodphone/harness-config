#!/usr/bin/env python3
"""Stop the session store from deep-cloning events that are already frozen.

WHY THIS EXISTS. `dsh-session-persistence-jsonl` buffers every session event with
`structuredClone(event)` before writing it. Most events arrive frozen (the emitter hands out
read-only objects), and cloning a frozen event buys nothing -- it is a full deep copy of the
message, on the write path, for every event of every session. The estate patched this by hand four
times on 2026-10-05 (the `.bak-harness-2026-10-05T02-36-30-365Z` ... `03-44-24-562Z` siblings) and
never wrote a patcher, so every install since has had to decide by comparison whether the change
survived -- and on 0.2.1-rc.2 it did NOT (line 188 still clones unconditionally, measured
2026-10-20). P3170's close condition is exactly this file.

THE EDIT is one expression: clone only when the event is not already frozen. Behaviour is
identical for unfrozen events; frozen ones take the lock-free path.

Usage:
  patch-dsh-jsonl-frozen-clone.py --root DIR           # apply (idempotent)
  patch-dsh-jsonl-frozen-clone.py --root DIR --check   # 0 present, 1 missing, 4 anchor absent
"""
from __future__ import annotations

import argparse
import pathlib
import sys

OLD = "this.buffered.push(structuredClone(event));"
NEW = "/* harness-patch:per-event-no-redundant-clone */ this.buffered.push(Object.isFrozen(event) ? event : structuredClone(event));"
REL = pathlib.Path("node_modules") / "@deepseek-ai" / "dsh-session-persistence-jsonl" / "lib" / "index.js"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="the DSH install root that holds node_modules")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    target = pathlib.Path(args.root) / REL
    if not target.is_file():
        print(f"absent   {target} does not exist")
        return 4
    text = target.read_text(encoding="utf-8", errors="surrogateescape")
    if NEW in text:
        print(f"already-patched {target.name}")
        return 0
    hits = text.count(OLD)
    if hits != 1:
        print(f"absent   {target.name}: the buffered.push anchor appears {hits} time(s), expected exactly 1 — upstream changed this line; re-author the patcher")
        return 4
    if args.check:
        print(f"missing  {target.name}: the buffer still clones every event")
        return 1
    target.write_text(text.replace(OLD, NEW, 1), encoding="utf-8", errors="surrogateescape")
    print(f"patched  {target.name}: frozen events are no longer deep-cloned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
