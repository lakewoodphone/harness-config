#!/usr/bin/env python3
"""Prove the session-sweep classifier fix BEFORE and AFTER, on real text.

Loads the backup (old) and the patched file, calls classify() on four cases that
reproduce the measured defects, and prints a PASS/FAIL per case. Exits non-zero if
any AFTER expectation fails, so this is a gate, not a narrative.
"""
import importlib.util
import sys

OLD = "/root/bin/sources/session-sweep.py.bak-sweepfix-20261018"
NEW = "/root/bin/sources/session-sweep.py"


def load(path, name):
    # The backup keeps a non-.py suffix, which spec_from_file_location refuses, so
    # name the loader explicitly rather than renaming a backup to suit a test.
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


CASES = [
    (
        "fenced draft must not count (row 1184's real cause)",
        'Here is the body I would send:\n```\nOne line and I\u2019ll file it for good.\n```\n'
        'Sent and recorded. Nothing else outstanding.',
        False,
    ),
    (
        "fenced draft with a STRAIGHT apostrophe (isolates the fence strip)",
        "Here is the body I would send:\n```\nOne line and I'll file it for good.\n```\n"
        "Sent and recorded. Nothing else outstanding.",
        False,
    ),
    (
        "a real promise must still be caught, and must be READABLE",
        "Status: the restart is held. I'll bring you the determination once #536 lands, "
        "and I am still waiting on the filing.",
        True,
    ),
    (
        "a promise written with a typographic apostrophe",
        "Status: the restart is held. I\u2019ll bring you the determination once #536 lands.",
        True,
    ),
    (
        "an H-number in prose is not a written handoff",
        'Recall that H7071 covers this area. Next I will re-read the audit.',
        True,
    ),
    (
        "a real handoff write is still skipped",
        'Done. python journal.py append handoff --body "..." H7274 records it.',
        False,
    ),
]

old = load(OLD, "sweep_old")
new = load(NEW, "sweep_new")

fail = 0
for label, text, want in CASES:
    o = old.classify(text)[:2]
    n = new.classify(text)[:2]
    ok = (n[0] == want)
    if not ok:
        fail += 1
    print("%s  %s" % ("PASS" if ok else "FAIL", label))
    print("      old: interesting=%s reason=%r" % o)
    print("      new: interesting=%s reason=%r" % n)
    if n[0] and len(n[1]) < 18:
        print("      FAIL: reason is still unreadable (%d chars)" % len(n[1]))
        fail += 1

print("\n%s  %d case(s) failed" % ("RESULT: FAIL" if fail else "RESULT: PASS", fail))
sys.exit(1 if fail else 0)
