#!/usr/bin/env python3
"""Tighten the shift contract: a text carries a QUESTION or a WARNING. Never a status report.

THE OWNER'S CORRECTION, 2026-09-28, and it is sharper than my own rule. I asked to send him a
completion report ("Kosher filter #10 is done: 112 tests passing, branch pushed...") to prove the
channel worked. He asked:

    "why would it text me this, whats the point, is there a question or clarification you need from
     me or a warning you need to give me?"

There was none. The message existed to demonstrate my own plumbing, and demonstrating plumbing is
not a reason to spend his attention. So:

    A TEXT HAPPENS ONLY WHEN IT CARRIES A QUESTION, A WARNING, OR A DECISION.
    A FINISHED JOB IS RECORDED IN THE LEDGER. "IT FINISHED" IS NOT A REASON TO TEXT.

This patch removes the two places the shift contract told sessions to text him:
  * STEP 7 previously told a shift to text him after filing an owner-queue row. An owner-queue row
    is exactly how he is asked something, so a duplicate text is noise. STEP 7 now says: file the
    row, do NOT text, and text only if the row is a WARNING he must act on today.
  * The old wording also implied a reply to "when a job you asked for finishes". That is gone.

It also states the three legitimate reasons positively, so a future shift does not have to
re-derive them from a prohibition.

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

OLD = '''        "STEP 7 - TELL HIM, IF YOU ASKED HIM ANYTHING. If you filed an owner-queue row (step",
        "  (b) below), the owner will NOT see it until something reaches his phone, and a",
        "  question he never sees is a question he never answers. So after filing it, send him",
        "  ONE short text with the question and your recommendation. This is the only outbound",
        "  message a shift may send, it may go ONLY to the owner, and it must be short:",
        "",
        "    printf '%s' 'THE QUESTION IN ONE LINE. I recommend <what you would do>.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",
        "  (Create the file with a heredoc or printf, then send it - never put a body with",
        "  quotes or newlines on the command line.) The send is gated: the owner's own number",
        "  is OPEN by construction, and anything else is refused. Read the result line back and",
        "  quote it. Never write a price, a date, a commitment or a legal posture into it.",
        "",'''

NEW = '''        "STEP 7 - THE ONLY REASONS TO TEXT HIM, AND THE REASON NOT TO.",
        "  A text to the owner carrying anything else is a WASTE OF HIS ATTENTION, and he has",
        "  said so sharply (2026-09-28): asked why he would receive a completion report, he",
        "  answered - \\"whats the point, is there a question or clarification you need from me",
        "  or a warning you need to give me?\\" There was none. Do not repeat that.",
        "",
        "  TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE:",
        "    (1) A QUESTION ONLY HE CAN ANSWER, with your recommendation in the same line.",
        "    (2) A WARNING HE MUST ACT ON TODAY - something about to break, be lost, or cost",
        "        money, where waiting for him to look would be too late.",
        "    (3) A DECISION WITH A DEADLINE - a reply is genuinely needed before time runs out.",
        "",
        "  DO NOT TEXT HIM: that a job started, that a job finished, that tests passed, that a",
        "  branch was pushed, that you filed a queue row, or to prove the channel works. A",
        "  FINISHED JOB IS RECORDED IN THE LEDGER, which is where it is useful. \\"It finished\\"",
        "  is not a reason to text.",
        "",
        "  If it IS one of the three, then: file the owner-queue row FIRST (step (b) below) so the",
        "  question exists somewhere durable, and then send ONE short message naming it:",
        "",
        "    printf '%s' 'Kosher filter broker channel is blocked: it needs the per-phone token that',
        "    only exists root-only on lpt-apps. I recommend you tell me to use the test token.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",
        "  (Create the body in a file - never put quotes or newlines on the command line.) The",
        "  recipient is gated: the owner's own number only, and it may go NOWHERE ELSE. Quote the",
        "  result line back. Never write a price, a date, a commitment or a legal posture into it,",
        "  and never send anything outbound to a customer, vendor or colleague.",
        "",'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)

    # 1. Fix the SOURCE OF THE PROMPT: patch the patcher, then re-run it.
    patcher = Path("/home/zabz/bin/patch-shift-contract.py")
    src = patcher.read_text(encoding="utf-8")
    if "TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE" in src:
        print("patcher already carries the text discipline; re-running it to update the source")
    else:
        if OLD not in src:
            print("STEP 7 block not found verbatim in the patcher; searching loosely")
            m = re.search(r'        "STEP 7 - TELL HIM.*?\n        "",\n', src, re.S)
            if not m:
                raise SystemExit("ERROR: could not find STEP 7 in the patcher - refusing to guess")
            src = src[:m.start()] + NEW + src[m.end():]
        else:
            src = src.replace(OLD, NEW, 1)
        compile(src, str(patcher), "exec")
        if not a.apply:
            print("dry run ok (use --apply)")
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(patcher, patcher.with_name(patcher.name + ".bak-textdisc-" + stamp))
        patcher.write_text(src, encoding="utf-8")
        print("patched the patcher %s" % patcher)

    # 2. Apply it, which rewrites standing_contract() in the deployed source.
    r = subprocess.run([sys.executable, str(patcher), "--apply"], capture_output=True, text=True, timeout=180)
    print(r.stdout.strip()[-400:] or (r.stderr or "").strip()[-400:])

    # 3. PROVE it, by rendering the contract for a real project.
    probe = r'''
import importlib.util, sys, datetime
spec = importlib.util.spec_from_file_location("pk", "/home/zabz/bin/sources/project-keepalive.py")
pk = importlib.util.module_from_spec(spec); sys.modules["pk"] = pk; spec.loader.exec_module(pk)
_reg, projects = pk.load_registry()
p = [x for x in projects if x["id"] == "kosher-ai-filter"][0]
t = pk.standing_contract(p, pk.load_state(p), ["x"], datetime.datetime.now(datetime.timezone.utc))
print("  contract renders:", len(t), "bytes")
print("  states the three reasons :", "TEXT HIM ONLY IF THE MESSAGE IS ONE OF THESE THREE" in t)
print("  forbids completion texts :", "DO NOT TEXT HIM: that a job started" in t)
print("  still has the ledger call:", "claim-next" in t and "close <item-id>" in t)
print("  no completion-report promise left:", "when a job you asked for finishes" not in t)
'''
    r2 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=180)
    print(r2.stdout.strip() or (r2.stderr or "").strip()[-800:])
    return 0 if r2.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
