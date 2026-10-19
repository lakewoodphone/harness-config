#!/usr/bin/env python3
"""census-shows-rewrites.py - report both halves: what was refused, and what was repaired."""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "owner-text-scorecard.py"
OLD = '''            print("    %d of %d delivered texts   (%s)"
                  % (conf.get("would_refuse", 0), conf.get("delivered", 0),
                     "%.1f%%" % (rate * 100) if rate is not None else "n/a"))'''
NEW = '''            print("    %d of %d delivered texts   (%s) refused by the guards"
                  % (conf.get("would_refuse", 0), conf.get("delivered", 0),
                     "%.1f%%" % (rate * 100) if rate is not None else "n/a"))
            if conf.get("rewritten"):
                print("    %d more were REMINDERS the gate rewrites and sends - not refused, "
                      "not lost" % conf["rewritten"])'''

text = io.open(PATH, encoding="utf-8").read()
if NEW in text:
    print("already applied")
    raise SystemExit(0)
if text.count(OLD) != 1:
    print("anchor found %d times" % text.count(OLD))
    raise SystemExit(1)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(text.replace(OLD, NEW, 1))
print("patched the census print")
