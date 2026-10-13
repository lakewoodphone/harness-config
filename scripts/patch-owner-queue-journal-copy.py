#!/usr/bin/env python3
"""Patch owner-queue.py so `answer` also writes the owner's words into the journal.

APPLY THIS AS A PATCH, NEVER BY HAND-EDITING THE LIVE TOOL BLIND. It makes two exact
replacements and refuses if either anchor is not found, so a file that has already been
patched (or has drifted) fails loudly instead of being silently mangled.

Run with --dry-run first: it prints the two anchors and whether they are present.

WHY: measured 2026-10-13 -- of 488 queue rows, 67 carried an answer and **14 had no journal copy
anywhere**. `owner_decision_queue` is mutable (`amend` can overwrite `answer`) and the journal is
append-only, so a decision the owner had given lived in a single table cell. The backfill is
`journal/tools/reconcile-owner-answers.py`; this is the durable half, at the moment of answering.

BEST EFFORT BY DESIGN: if the journal cannot be reached, the answer is still recorded in the queue
and the command says so. His answer must never fail because a secondary copy failed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ANCHOR_SELECT = """def cmd_answer(con, a) -> int:
    row = con.execute("SELECT 1 FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()
"""
ANCHOR_SELECT_NEW = """def _journal_copy(row_id, question, answer) -> None:
    \"\"\"Append the owner's words to the journal so the answer survives the row.

    MEASURED 2026-10-13: 14 of 67 answered rows had NO journal copy anywhere. This table is
    mutable -- `amend` can overwrite `answer` -- and the journal is append-only, and nothing
    connected them, so a decision he had given lived in one cell that a later edit could replace.
    Backfill for the backlog: journal/tools/reconcile-owner-answers.py.

    BEST EFFORT BY DESIGN: if the journal is unreachable the ANSWER IS STILL RECORDED and this
    says so. His answer must never fail because a secondary copy failed.
    \"\"\"
    import os
    import re
    import subprocess
    # An explicit override first, so this is testable against a throwaway journal tree and so an
    # operator can point it somewhere else without editing the tool.
    j = os.environ.get("OWNER_QUEUE_JOURNAL") or None
    if j and not os.path.exists(j):
        print("  note: OWNER_QUEUE_JOURNAL names a path that does not exist; the answer is in the "
              "queue row only")
        return
    if not j:
        for cand in (os.path.expanduser("~/code/harness-config/journal/tools/journal.py"),
                     "/root/code/harness-config/journal/tools/journal.py"):
            if os.path.exists(cand):
                j = cand
                break
    if not j:
        print("  note: journal.py not found -- the answer is in the queue row only")
        return
    title = "Owner answer, queue row #%s: %s" % (
        row_id, re.sub(r"\\s+", " ", question or "")[:80])
    body = ("Recorded by `owner-queue.py answer` on %s. The row is a mutable table; this entry is\\n"
            "the append-only copy. If the two ever disagree, the row was edited.\\n\\n"
            "**Asked**: %s\\n\\n**His answer**: %s" % (now(), question or "(not recorded)", answer or ""))
    try:
        out = subprocess.run(
            [sys.executable, j, "append", "decisions", "--title", title, "--body", body,
             "--quiet", "--no-fetch", "--tags", "owner-answer",
             "--refs", "owner_decision_queue#%s" % row_id],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except Exception as exc:  # noqa: BLE001
        print("  note: could not reach the journal (%s); the answer is in the queue row only" % exc)
        return
    if out.returncode == 0:
        print("  journal: " + (out.stdout or "").strip()[:120])
    else:
        print("  note: journal append failed (%s); the answer is in the queue row only"
              % (out.stderr or "").strip()[:120])


def cmd_answer(con, a) -> int:
    row = con.execute("SELECT question FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()
"""
ANCHOR_TAIL = """    con.commit()
    print(f"#{a.id} -> answered")
    return 0
"""
ANCHOR_TAIL_NEW = """    con.commit()
    print(f"#{a.id} -> answered")
    _journal_copy(a.id, row[0], a.answer)
    return 0
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="owner-queue.py to patch")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    p = Path(a.path)
    src = p.read_text(encoding="utf-8")
    checks = [("SELECT anchor", ANCHOR_SELECT in src),
              ("TAIL anchor", ANCHOR_TAIL in src),
              ("already patched?", "_journal_copy" in src)]
    for name, ok in checks:
        print("%-20s %s" % (name, "found" if ok else "NOT FOUND"))
    if checks[2][1]:
        print("already patched -- nothing to do")
        return 0
    if not (checks[0][1] and checks[1][1]):
        print("REFUSING: an anchor is missing, so the file has drifted. Patch by hand after reading it.")
        return 2
    if a.dry_run:
        print("\ndry run: both anchors present, the patch would apply.")
        return 0

    if not src.startswith("#!/usr/bin/env python3"):
        print("REFUSING: the file does not start with a python3 shebang; not the tool I expect.")
        return 2
    backup = p.with_suffix(p.suffix + ".pre-journalcopy-" + time.strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(p, backup)
    out = src.replace(ANCHOR_SELECT, ANCHOR_SELECT_NEW, 1).replace(ANCHOR_TAIL, ANCHOR_TAIL_NEW, 1)
    p.write_text(out, encoding="utf-8")
    print(f"\npatched {p}\nbackup  {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
