#!/usr/bin/env python3
"""Tighten the shift contract: a text carries a QUESTION or a WARNING. Never a status report.

THE OWNER'S CORRECTION, 2026-09-28, sharper than my own rule. I asked to send him a completion
report ("Kosher filter #10 is done: 112 tests passing, branch pushed...") to prove the channel
worked. He asked:

    "why would it text me this, whats the epoint, is there a question or clarification you need
     from me or a warning you need to give me?"

There was none. The message existed to demonstrate my own plumbing, and demonstrating plumbing is
not a reason to spend his attention. So:

    A TEXT HAPPENS ONLY WHEN IT CARRIES A QUESTION, A WARNING, OR A DECISION WITH A DEADLINE.
    A FINISHED JOB IS RECORDED IN THE LEDGER. "IT FINISHED" IS NOT A REASON TO TEXT.

ESCAPING, LEARNED THE HARD WAY IN THIS VERY PATCH: the replacement text is a Python source
fragment, so every quote, backslash and newline in it is escape-sensitive, and the first version of
this patch produced `unterminated string literal` in the deployed file. The replacement is
therefore a RAW string and every generated line is a plain ASCII string with `\\"` used where the
generated code needs a backslash-quote. The patch compiles the result BEFORE writing and renders the
contract AFTER writing; the first failure was caught exactly there, which is why the check exists.

Usage: python3 patch-text-discipline.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")
PATCHER = Path("/home/zabz/bin/patch-shift-contract.py")

# RAW so no escaping is done here; the backslashes below are what the GENERATED source needs.
NEW = r'''        "STEP 7 - THE ONLY REASONS TO TEXT HIM, AND THE REASON NOT TO.",
        "  A text to the owner that carries anything else WASTES HIS ATTENTION, and he has said",
        "  so sharply (2026-09-28). Asked why he would receive a completion report, he answered:",
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
        "  If it IS one of the three, then: file the owner-queue row FIRST (step (b) below), so",
        "  the question exists somewhere durable, and then send ONE short message naming it:",
        "",
        "    printf '%s' 'The kosher filter broker channel is blocked: it needs the per-phone",
        "    token that exists root-only on lpt-apps. I recommend telling me to use the test",
        "    token.' > /tmp/reply.txt",
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
    if "TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE" in src:
        print("patcher already carries the text discipline")
    else:
        m = re.search(r'        "STEP 7 - TELL HIM.*?\n        "",\n', src, re.S)
        if not m:
            m = re.search(r'        "STEP 7 - .*?\n        "",\n', src, re.S)
        if not m:
            raise SystemExit("ERROR: could not find STEP 7 in the patcher - refusing to guess")
        new_src = src[:m.start()] + NEW + src[m.end():]
        compile(new_src, str(PATCHER), "exec")      # the patcher itself must parse
        if not a.apply:
            print("dry run ok (use --apply)")
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(PATCHER, PATCHER.with_name(PATCHER.name + ".bak-textdisc-" + stamp))
        PATCHER.write_text(new_src, encoding="utf-8")
        print("patched the patcher %s" % PATCHER)

    # Re-run it. It compiles the deployed source before writing (compile(new, ...)), so a broken
    # fragment cannot reach the file; if it does anyway, the render check below catches it.
    r = subprocess.run([sys.executable, str(PATCHER), "--apply"], capture_output=True, text=True, timeout=180)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    print("\n".join(tail))
    if "patched" not in (r.stdout or ""):
        print("patcher did not report success:\n" + (r.stderr or "")[-600:])
        return 1

    # PROVE IT: the deployed source must compile, and the contract must render with the new rules.
    comp = subprocess.run([sys.executable, "-m", "py_compile", str(TARGET)], capture_output=True, text=True)
    if comp.returncode != 0:
        print("STILL BROKEN:\n" + comp.stderr[-600:])
        return 1
    print("deployed source compiles: OK")

    probe = r'''
import importlib.util, sys, datetime
spec = importlib.util.spec_from_file_location("pk", "/home/zabz/bin/sources/project-keepalive.py")
pk = importlib.util.module_from_spec(spec); sys.modules["pk"] = pk; spec.loader.exec_module(pk)
_reg, projects = pk.load_registry()
p = [x for x in projects if x["id"] == "kosher-ai-filter"][0]
t = pk.standing_contract(p, pk.load_state(p), ["x"], datetime.datetime.now(datetime.timezone.utc))
print("  contract renders           :", len(t), "bytes")
print("  states the three reasons   :", "TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE" in t)
print("  forbids completion texts   :", "DO NOT TEXT HIM: that a job started" in t)
print("  keeps the ledger contract  :", "claim-next" in t and "close <item-id>" in t)
print("  no completion promise left :", "when a job you asked for finishes" not in t)
'''
    r2 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=180)
    print(r2.stdout.strip() or (r2.stderr or "").strip()[-800:])
    return 0 if r2.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
