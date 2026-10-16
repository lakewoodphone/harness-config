#!/usr/bin/env python3
"""40-clobber-proof.py -- prove, on a throwaway fixture, that `journal.py dedupe` destroys a
file when two entries inside one dedupe group carry the SAME id.

Why it matters here: the round-6 brief's step 3 says to overlay every tree's `entries/` "so all
17,386 files are present". In a tree where the file stem must equal the marker id (verify.py
enforces it), 17,387 files can only coexist if the colliding copies are given second-copy names
(<id>b.md, <id>c.md ...) WHILE KEEPING the marker id inside. That is exactly the state that
makes several files in one dedupe group share one id_full.

cmd_dedupe moves each surplus copy to
    archive/duplicates/<kind>/<dup id_full>.md
with no collision-avoidance loop (unlike cmd_repair_ids, which HAS one:
`while dest.exists(): dest = <id_full>-<n>.md`). Two surplus copies of one id therefore land on
the same path and the second move overwrites the first.

This script builds a four-file fixture in its OWN directory (nothing live is touched), runs the
real dedupe --apply, and counts what survived.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

R7 = pathlib.Path("/root/work/r7")
FIX = R7 / "scratch" / "dedupe-clobber"
TOOL_SRC = R7 / "trees" / "yoga" / "journal" / "tools" / "journal.py"

BODY = ("\nCHANGED\n- one line of body, identical in every copy, so identity() groups them.\n"
        "\nNEXT\n- nothing.\n")


def entry(heading: str) -> str:
    return ("<!-- e:lessons|L900|2026-10-15 12:00 UTC|ZABZ-TECH|open -->\n"
            + heading + "\n" + BODY)


def main() -> int:
    if FIX.exists():
        aside = FIX.with_name(FIX.name + ".prev")
        if aside.exists():
            shutil.rmtree(aside)
        FIX.rename(aside)
        print("previous fixture moved aside to %s (not deleted)" % aside)
    for d in ("entries/lessons", "entries/decisions", "entries/handoff", "entries/pain",
              "entries/wins", "index", "state", "alloc", "log", "archive", "tools"):
        (FIX / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(TOOL_SRC, FIX / "tools" / "journal.py")

    # THREE files, ONE id, ONE identity (same body), DIFFERENT headings.
    heads = {
        "L900.md":  "## 2026-10-15 12:00 UTC · AAAA the survivor heading",
        "L900b.md": "## 2026-10-15 12:00 UTC · BBBB second copy heading",
        "L900c.md": "## 2026-10-15 12:00 UTC · CCCC third copy heading",
    }
    for name, h in heads.items():
        p = FIX / "entries" / "lessons" / name
        p.write_text(entry(h), encoding="utf-8")
        print("BEFORE  entries/lessons/%-9s %6d bytes  heading=%s" % (name, p.stat().st_size, h[26:34]))

    before = {p.name: p.read_bytes() for p in (FIX / "entries" / "lessons").glob("*.md")}
    tool = FIX / "tools" / "journal.py"
    for cmd in (["dedupe"], ["dedupe", "--apply"]):
        r = subprocess.run([sys.executable, str(tool), "--root", str(FIX), "--no-color"] + cmd,
                           capture_output=True, text=True)
        print("\n--- journal.py --root <fixture> %s  (exit %d) ---" % (" ".join(cmd), r.returncode))
        print(r.stdout.strip() or r.stderr.strip())

    left = sorted((FIX / "entries" / "lessons").glob("*.md"))
    arch = sorted((FIX / "archive" / "duplicates" / "lessons").glob("*.md")) \
        if (FIX / "archive" / "duplicates" / "lessons").is_dir() else []
    print("\nAFTER   entries/lessons: %s" % [p.name for p in left])
    for p in arch:
        print("ARCHIVE archive/duplicates/lessons/%-9s %6d bytes" % (p.name, p.stat().st_size))
    print("\nSURVIVING BYTES: %d of 3 copies" % (len(left) + len(arch)))
    print("BEFORE bytes total = %d ; AFTER bytes total = %d"
          % (sum(len(v) for v in before.values()),
             sum(p.stat().st_size for p in left) + sum(p.stat().st_size for p in arch)))
    survived_heads = set()
    for p in left + arch:
        survived_heads.add(p.read_text(encoding="utf-8").split("\n")[1][26:34])
    print("headings that survived: %s" % sorted(survived_heads))
    loss = len(before) - (len(left) + len(arch))
    print("\nVERDICT: %d of %d copies survived; %d file(s) destroyed."
          % (len(left) + len(arch), len(before), loss))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
