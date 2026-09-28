#!/usr/bin/env python3
"""Route the shift contract's text step through the gated tool, and close a real hole in the process.

WHAT WAS THERE, measured 2026-09-28 20:34Z. STEP 7 of the woken-shift contract already told a session the
right rule in prose - text only for a question, a warning, or a deadline, never a completion report - and
then handed it these two lines:

    printf %s 'YOUR ONE-LINE QUESTION. I recommend X.' > /tmp/reply.txt
    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send

THAT IS A LIVE PATH BY WHICH A HEADLESS SHIFT CAN TEXT THE OWNER WITH NO APPROVAL STEP AT ALL. The prose
asked nicely; the command had no gate. The owner's rule is that nothing goes outbound without his explicit
per-message approval of the exact words, and the failure it guards against already happened on 2026-09-24 -
a six-item questionnaire he had never seen went to a data-recovery lab. A prompt cannot enforce that. Code
can, and `shift-report.py` was built last round to be that code.

AND NOTHING REFERENCED IT. `grep -c shift-report` over both wake sources returned 0, so the tool I built to
be the gate would never have been called. A mechanism no session knows to use does not exist.

THIS PATCH:
  1. replaces the direct `textsend.py send --send` instruction with `shift-report.py decision`, which files
     the queue row, prints the exact body, and CANNOT send without `--approved-by-owner`;
  2. keeps the prose rule intact - it is correct and worth reading;
  3. states plainly why the send is now gated, so a shift understands it is not being obstructed;
  4. and adds `shift-report.py record` to STEP 4 as the closing step, so a finished job is recorded rather
     than announced.

Usage: python3 wire-shift-report.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")

OLD_SEND = '''        "  question exists somewhere durable, and then send ONE short message naming it. Write",
        "  the body into a file first; never put quotes or newlines on a command line:",
        "",
        "    printf %s 'YOUR ONE-LINE QUESTION. I recommend X.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",'''

NEW_SEND = '''        "  question exists somewhere durable, and then ASK THE GATE TO COMPOSE IT:",
        "",
        "    python3 ~/bin/shift-report.py decision --item <item-id> \\\\",
        "        --question 'YOUR ONE-LINE QUESTION' \\\\",
        "        --recommendation 'I recommend X, because Y.' \\\\",
        "        --context 'the measurement behind it'",
        "",
        "  THAT TOOL WILL NOT SEND. It files the queue row, prints the exact body, and stops -",
        "  and that is deliberate, not an obstacle to work around. Nothing goes to him without",
        "  his approval of those exact words, and a shift is not a person who can approve them.",
        "  The rule was broken on 2026-09-24 by a six-item questionnaire he had never seen; the",
        "  tool is what makes it impossible rather than merely discouraged. Report the body you",
        "  composed in your --result line, and the owner or the next session sends it.",
        "",
        "  Do NOT call `textsend.py send --send` yourself, and do NOT look for another way out.",
        "",'''

ADD_TO_STEP4 = '''        "",
        "  TOLD, NOT ANNOUNCED. When the item is done or declined, say so HERE - the ledger is",
        "  where a finished job is recorded. Do not text him that it finished; he called that",
        "  pointless, twice. If the outcome needs HIM (a question, a warning, a deadline), STEP 7",
        "  has the one supported way to raise it:",
        f"    python3 ~/bin/shift-report.py record --item <item-id> --outcome '<one line>'",
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")

    if "shift-report.py decision" in src:
        print("already wired")
    elif OLD_SEND not in src:
        print("ERROR: could not find the direct-send block - refusing to guess.")
        print("  looked for the exact lines containing 'textsend.py send --to +18483897895'")
        m = re.search(r'.*textsend\.py send.*', src)
        print("  what is actually there: %r" % (m.group(0)[:150] if m else "nothing"))
        return 1
    else:
        src = src.replace(OLD_SEND, NEW_SEND, 1)
        print("1. replaced the direct-send instruction with the gated tool")

    if "shift-report.py record" not in src:
        anchor = '''        "  A close with no --proof and --result is RECORDED AS NOT DONE, on purpose.",
        "",'''
        if anchor in src:
            src = src.replace(anchor, anchor + ADD_TO_STEP4, 1)
            print("2. added the close-out line to STEP 4")
        else:
            print("   WARNING: could not find the STEP 4 anchor; step 2 skipped")
    else:
        print("2. STEP 4 already mentions shift-report")

    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: the result does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-shiftreport-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s" % p)

    print("\n=== PROOF: what a session now reads for the send step ===")
    out = __import__("subprocess").run(
        ["python3", str(p)], capture_output=True, text=True, timeout=120)
    text = out.stdout or ""
    for marker in ("shift-report.py decision", "WILL NOT SEND", "Do NOT call `textsend.py send --send`"):
        i = text.find(marker)
        if i >= 0:
            print("  FOUND: %r at offset %d" % (marker, i))
        else:
            print("  MISSING: %r" % marker)
    if "textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send" in text:
        print("  STILL PRESENT: the ungated send command - the patch did not take")
        return 1
    print("  the ungated send command is GONE from the contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
