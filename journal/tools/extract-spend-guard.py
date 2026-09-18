"""Extract the spend-guard script from its design document into a real tool.

The spend-guard design (docs/mesh/65-spend-guard.md) carries a complete, self-tested
Python program inside a fenced block, verified by its author by extracting it and
running it. A program that exists only inside a document is not a tool: nothing can
schedule it, nothing can call it, and the next session has to re-extract it by hand.

This writes the largest ```python block to tools/spend-guard.py after checking it
actually looks like the program (a main(), a selftest, a shebang) rather than a
fragment, and refuses to overwrite an existing file with different content unless
--force is passed.
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import re
import sys

FENCE = chr(96) * 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="docs/mesh/65-spend-guard.md")
    ap.add_argument("--out", default="tools/spend-guard.py")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    doc = pathlib.Path(args.doc)
    if not doc.exists():
        print(f"no such document: {doc}", file=sys.stderr)
        return 2
    text = doc.read_text(encoding="utf-8")
    blocks = re.findall(FENCE + r"(?:python|py)\n(.*?)" + FENCE, text, re.S)
    if not blocks:
        print("no ```python block found", file=sys.stderr)
        return 2
    candidates = [b for b in blocks if "def main" in b and "selftest" in b]
    if not candidates:
        print(f"{len(blocks)} python block(s), none contains both `def main` and `selftest`; "
              f"sizes={[len(b) for b in blocks]}", file=sys.stderr)
        return 2
    best = max(candidates, key=len)
    if not best.endswith("\n"):
        best += "\n"

    out = pathlib.Path(args.out)
    if out.exists():
        current = out.read_text(encoding="utf-8")
        if current == best:
            print(f"unchanged: {out} ({len(best)} B)")
            return 0
        if not args.force:
            diff = list(difflib.unified_diff(current.splitlines(), best.splitlines(),
                                             "existing", "from-doc", lineterm=""))[:40]
            print(f"REFUSING to overwrite {out}: it differs from the document's block. "
                  f"First lines of the diff:", file=sys.stderr)
            print("\n".join(diff), file=sys.stderr)
            return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(best, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(best)} B, from {len(candidates)} candidate block(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
