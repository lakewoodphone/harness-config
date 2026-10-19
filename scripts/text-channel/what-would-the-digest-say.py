#!/usr/bin/env python3
"""what-would-the-digest-say.py - run the LIVE composer on the LIVE digest file.

The class he complained about twice - "36 items, 30 urgent" - is now a fallback behind
OWNER_SMS_ONE_ITEM. Rather than assume that, render what the composer would send right now from
the real data file, and check it against the contract the composer's own docstring states: one
item, no counts, no file path, no truncation marker.

Read-only: `compose_sms_body` is documented as not touching disk or sending.
"""
import importlib.util
import os
import sys

SRC = "/opt/company/scripts/owner_attention.py"
DATA = "/opt/company/data/owner-attention/latest.txt"

spec = importlib.util.spec_from_file_location("owner_attention", SRC)
mod = importlib.util.module_from_spec(spec)
sys.modules["owner_attention"] = mod
try:
    spec.loader.exec_module(mod)
except Exception as exc:                                       # noqa: BLE001
    print("could not import the composer: %s: %s" % (type(exc).__name__, exc))
    raise SystemExit(3)

print("OWNER_SMS_ONE_ITEM = %r" % getattr(mod, "OWNER_SMS_ONE_ITEM", "missing"))
print("OWNER_SMS_MAX      = %r" % getattr(mod, "OWNER_SMS_MAX", "missing"))
print()

if not os.path.exists(DATA):
    print("no digest file at %s - nothing to compose today" % DATA)
    raise SystemExit(0)

text = open(DATA, encoding="utf-8", errors="replace").read()
items = [l for l in text.split("\n") if l[:4].strip().rstrip(".").isdigit() and "] " in l]
print("digest file: %d line(s), %d item line(s)" % (len(text.split("\n")), len(items)))
print()

for label, sent in (("first run (nothing sent yet)", {}),):
    body, key = mod.compose_sms_body(text, sent)
    print("== %s" % label)
    print("   key : %s" % (key or "(none)"))
    print("   body: %r" % body)
    print("   chars: %d" % len(body))
    low = body.lower()
    problems = []
    if not body:
        problems.append("EMPTY - nothing would be sent")
    if " items," in low or "urgent" in low and "items" in low:
        problems.append('carries an "N items, M urgent" head')
    if "data/owner-attention" in low or "latest.txt" in low:
        problems.append("carries the digest file path")
    if "cut short" in low or "continue" in low and "ask me" in low:
        problems.append("carries a truncation marker")
    if body and not body.rstrip().endswith(("?", ".")):
        problems.append("does not end on a sentence (looks half-sent)")
    print("   verdict: %s" % ("; ".join(problems) if problems else "clean - one item, no counts, no path"))
    print()

# the no-repeat rule: the same item must not go out twice
body2, key2 = mod.compose_sms_body(text, {mod.item_fingerprint(key): "2026-10-19T12:00:00+00:00"} if key else {})
same = (body2 == body)
print("== second run with that key already sent")
print("   body: %r" % body2)
print("   same item again? %s" % ("YES - THE NO-REPEAT RULE IS NOT WORKING" if same and body
                                 else "no - a different item, as intended"))
