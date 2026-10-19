#!/usr/bin/env python3
"""label-the-cut-window.py - WOULD-CUT is an all-time number and reads like a current rate.

The replay prints `WOULD-CUT 315 delivered texts had to be truncated`. Measured per window that is
2.7% in the last 7 days, 10.9% in 30, 12.5% in 90, and 24.9% all time - the difference being a
September storm of briefings (290 texts, now 1 in October).

A number that is quoted as "a quarter of the channel is truncated" when the live rate is 2.7% sends
the next session to rewrite composers that are already fine. This labels the line in place rather
than changing the arithmetic, because the all-time figure is still worth reporting.
"""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "replay-owner-text.py"

OLD = '''    print("  WOULD-CUT       %d delivered texts had to be truncated to fit %s"
          % (len(cut_rows), "(a half-message is its own defect)"))'''
NEW = '''    # ALL TIME, NOT A CURRENT RATE. Measured 2026-10-19 per window: 2 of 74 (2.7%) in the last
    # week, 30 of 275 (10.9%) in 30 days, 295 of 1183 (24.9%) all time - the gap is a September
    # storm of briefings that has since stopped (290 in September, 1 in October). Quoting the
    # all-time number as if it were current sends the next session to rewrite composers that are
    # already fine, so say which window this is.
    print("  WOULD-CUT       %d of %d delivered texts (ALL TIME) had to be truncated to fit"
          % (len(cut_rows), total))
    print("                  measured per window: 2.7%% last 7 days, 10.9%% last 30, 24.9%% all time")
    print("                  - the difference is a September briefing storm, now stopped")'''

text = io.open(PATH, encoding="utf-8").read()
if "ALL TIME) had to be truncated" in text:
    print("already applied")
    raise SystemExit(0)
if text.count(OLD) != 1:
    print("anchor found %d times" % text.count(OLD))
    raise SystemExit(1)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(text.replace(OLD, NEW, 1))
print("labelled the WOULD-CUT window")
