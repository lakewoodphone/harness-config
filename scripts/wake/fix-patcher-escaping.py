#!/usr/bin/env python3
"""Fix patch-shift-contract.py: proper escaping in the generated text, and a compile gate before writing.

TWO DEFECTS IN MY OWN PATCHER, both found by its own verification pass:

1. ESCAPING. The STEP 7 replacement was written with `\\"` where the GENERATED Python source needs
   `\\\\"` (a backslash-quote in the output string). The result compiled HERE but produced
     SyntaxError: unterminated string literal
   in the deployed source. A patcher that generates code must treat every quote the generated code
   needs as escape-sensitive.

2. NO COMPILE GATE ON WRITE. `patch-shift-contract.py` compiled its candidate, then wrote the file,
   then trusted that the write equalled the candidate - so on any later edit to the fragment it could
   write a file that does not parse, which would stop EVERY project from being woken, not one.
   A patch to the machine that wakes work must not be able to publish a file that cannot load.

This script rewrites the STEP 7 fragment from a raw string (no escaping to get wrong), then patches
the write path so the generated source is compiled immediately before it is written.

Usage: python3 fix-patcher-escaping.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATCHER = Path("/home/zabz/bin/patch-shift-contract.py")

# RAW: what you see is exactly what the generated source gets, backslashes included.
NEW = r'''        "STEP 7 - THE ONLY REASONS TO TEXT HIM, AND THE REASON NOT TO.",
        "  A text to the owner that carries anything else WASTES HIS ATTENTION, and he said so",
        "  sharply on 2026-09-28. Asked why he would receive a completion report, he answered:",
        "  whats the point, is there a question or clarification you need from me, or a warning",
        "  you need to give me? There was none. Do not repeat that.",
        "",
        "  TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE:",
        "    (1) A QUESTION ONLY HE CAN ANSWER, with your recommendation on the same line.",
        "    (2) A WARNING HE MUST ACT ON TODAY - something about to break, be lost, or cost",
        "        money, where waiting for him to look would be too late.",
        "    (3) A DECISION WITH A DEADLINE - a reply is genuinely needed before time runs out.",
        "",
        "  DO NOT TEXT HIM: that a job started, that a job finished, that tests passed, that a",
        "  branch was pushed, that you filed a queue row, or to prove the channel works. A",
        "  FINISHED JOB IS RECORDED IN THE LEDGER, which is where it is useful. It finished is",
        "  not a reason to text.",
        "",
        "  If it IS one of the three: file the owner-queue row FIRST (step (b) below), so the",
        "  question exists somewhere durable, and then send ONE short message naming it.",
        "  Write the body into a file first (never put quotes or newlines on a command line):",
        "",
        "    printf %s 'YOUR ONE-LINE QUESTION, THEN: I recommend X.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",
        "  (Create the body in a file - never put quotes or newlines on the command line.) The",
        "  recipient is gated: the owner's own number only, and NOWHERE ELSE. Quote the result",
        "  line back. Never write a price, a date, a commitment or a legal posture into it, and",
        "  never send anything outbound to a customer, vendor or colleague.",
        "",'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    src = PATCHER.read_text(encoding="utf-8")

    # 1. replace the whole STEP 7 fragment with the raw version
    m = re.search(r'        "STEP 7 - .*?\n        "",\n', src, re.S)
    if not m:
        raise SystemExit("ERROR: STEP 7 fragment not found - refusing to guess")
    new = src[:m.start()] + NEW + src[m.end():]
    compile(new, str(PATCHER), "exec")
    print("STEP 7 fragment replaced (%d -> %d bytes)" % (len(src), len(new)))

    # 2. add the compile gate to the write path, if it is not there
    gate_marker = "GENERATED SOURCE MUST COMPILE BEFORE IT IS WRITTEN"
    if gate_marker in new:
        print("compile gate already present")
    else:
        old = """    new = src[:start] + NEW_FUNC + src[end:]
    compile(new, str(p), "exec")          # never write a file that cannot even parse"""
        if old not in new:
            print("WARNING: could not find the write path verbatim; adding the gate by a looser pattern")
            old_re = re.compile(r"(    new = src\[:start\] \+ NEW_FUNC \+ src\[end:\]\n)(\s*)compile\(new, str\(p\), \"exec\"\)")
            if not old_re.search(new):
                raise SystemExit("ERROR: write path not found - refusing to write")
            new = old_re.sub(
                r"\1" + """    # GENERATED SOURCE MUST COMPILE BEFORE IT IS WRITTEN. The deployed file is what wakes
    # EVERY project, so publishing a file that cannot parse stops the whole operation, not one
    # shift. Compile the exact bytes that are about to be written, and refuse on failure.
    try:
        compile(new, str(p), "exec")
    except SyntaxError as exc:
        raise SystemExit("REFUSING TO WRITE: generated source does not compile: %s" % exc)""",
                new, count=1)
        else:
            new = new.replace(old, """    new = src[:start] + NEW_FUNC + src[end:]
    # GENERATED SOURCE MUST COMPILE BEFORE IT IS WRITTEN. The deployed file is what wakes EVERY
    # project, so publishing a file that cannot parse stops the whole operation, not one shift.
    try:
        compile(new, str(p), "exec")
    except SyntaxError as exc:
        raise SystemExit("REFUSING TO WRITE: generated source does not compile: %s" % exc)""", 1)
        print("compile gate added")
    compile(new, str(PATCHER), "exec")

    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(PATCHER, PATCHER.with_name(PATCHER.name + ".bak-fixesc-" + stamp))
    PATCHER.write_text(new, encoding="utf-8")
    print("patched %s" % PATCHER)

    r = subprocess.run([sys.executable, str(PATCHER), "--apply"], capture_output=True, text=True, timeout=180)
    out = (r.stdout or "").strip()
    print("\n".join(out.splitlines()[-3:]))
    if "patched" not in out:
        print("patcher failed:\n" + (r.stderr or "")[-700:])
        return 1

    comp = subprocess.run([sys.executable, "-m", "py_compile",
                           "/home/zabz/bin/sources/project-keepalive.py"], capture_output=True, text=True)
    if comp.returncode != 0:
        print("DEPLOYED SOURCE BROKEN:\n" + comp.stderr[-700:])
        return 1
    print("deployed source compiles: OK")

    probe = r'''
import importlib.util, sys, datetime
spec = importlib.util.spec_from_file_location("pk", "/home/zabz/bin/sources/project-keepalive.py")
pk = importlib.util.module_from_spec(spec); sys.modules["pk"] = pk; spec.loader.exec_module(pk)
_reg, projects = pk.load_registry()
p = [x for x in projects if x["id"] == "kosher-ai-filter"][0]
t = pk.standing_contract(p, pk.load_state(p), ["x"], datetime.datetime.now(datetime.timezone.utc))
print("  contract renders            :", len(t), "bytes")
print("  states the three reasons    :", "TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE" in t)
print("  forbids completion texts    :", "DO NOT TEXT HIM: that a job started" in t)
print("  keeps the ledger contract   :", "claim-next" in t and "close <item-id>" in t)
print("  no completion promise left  :", "when a job you asked for finishes" not in t)
'''
    r2 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=180)
    print(r2.stdout.strip() or (r2.stderr or "").strip()[-800:])
    return 0 if r2.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
