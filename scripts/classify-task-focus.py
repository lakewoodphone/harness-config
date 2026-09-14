"""What is the company actually working on: the business, or itself?

The question the owner's money is buying. Read-only SELECTs.

Two things are already established and shape this measurement:
  * `tasks` are created in volume (135-285/day) and essentially all get closed
    (1,831 done against 7 open and 3 in_progress since 2026-09-06), so "the
    company produces no tasks" is FALSE -- and my earlier reading of
    activity_log's 8 `task_created` rows as the real count was wrong, because
    activity_log does not log every creation.
  * the titles sampled are mostly about the AI system itself ("Audit agent memory
    usage", "Review and update stale prompts", "Implement automated regression
    tests for core routing logic") rather than the phone repair business.

This counts the split instead of eyeballing it.

Labels are keyword-based and deliberately generous to "business": a task that could
be either is counted as business, so the self-share is a floor, not a ceiling.
"""

from __future__ import annotations

import collections
import re
import sqlite3
import sys

DB = "data/secretary.db"
DAYS = 14

BUSINESS = (
    r"customer|repair|voicemail|phone|tech|part|order|invoice|payroll|price|pricing|"
    r"sale|sales|lead|listing|ebay|amazon|deal|flip|shlomo|shlok|mark|vendor|"
    r"dialpad|sms|call|text|screen|battery|device|inventory|revenue|refund|"
    r"quickbooks|plaid|bank|tax|quote|estimate|appointment|schedule with"
)
SELF = (
    r"\bagent\b|\bagents\b|prompt|monitor|threshold|memory|routing|router|regression|"
    r"test|schema|index|workflow|synth|evolution|self|tick|telemetry|"
    r"orchestrat|tool|delegat|heartbeat|lifecycle|sentinel|kernel|guardrail|"
    r"coverage|hygiene|reconcil|dedup|stale|cache|embedding|retrieval|context|"
    r"autonomy|budget|circuit|goal|department|departmental|architect|"
    # added after inspecting the first run's 44.5% unclassified bucket, which was
    # dominated by these: the classifier was under-counting self-work, not the
    # company under-doing it.
    r"ghost_agent|unresolved|proposal|snapshot|improvement|reliability|integrity|"
    r"planning|sensor|door contact|phoenix|provider strategy|error|incident|"
    r"provision|uptime|availability|dashboard|api |sqlite|postgres|database|"
    r"roster|blueprint|identity|neshama|persona|autopilot|loop|review workflow"
)


def label(title: str) -> str:
    t = (title or "").lower()
    biz = re.search(BUSINESS, t)
    slf = re.search(SELF, t)
    if biz and not slf:
        return "business"
    if slf and not biz:
        return "self"
    if biz and slf:
        return "both"
    return "unclear"


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        f"""SELECT id, status, title, created_at FROM tasks
            WHERE created_at > datetime('now', '-{DAYS} days')
            ORDER BY id DESC"""
    ))
    print(f"tasks in the last {DAYS} days: {len(rows)}\n")

    counts = collections.Counter()
    for r in rows:
        counts[label(r["title"])] += 1
    total = max(len(rows), 1)
    for k in ("business", "self", "both", "unclear"):
        n = counts[k]
        print(f"  {k:<9} {n:>5}  {n*100/total:5.1f}%")

    selfish = counts["self"]
    print(f"\n  purely about the AI system itself: {selfish*100/total:.1f}%")
    print(f"  touching the business at all   : "
          f"{(counts['business']+counts['both'])*100/total:.1f}%")

    print("\n== sample of SELF tasks (the company's actual focus) ==")
    shown = 0
    for r in rows:
        if label(r["title"]) == "self" and shown < 10:
            print(f"  #{r['id']}  {r['title'][:96]}")
            shown += 1

    print("\n== sample of BUSINESS tasks ==")
    shown = 0
    for r in rows:
        if label(r["title"]) in ("business", "both") and shown < 10:
            print(f"  #{r['id']}  {r['title'][:96]}")
            shown += 1

    print("\n== sample of UNCLEAR tasks (the bucket that decides this) ==")
    shown = 0
    for r in rows:
        if label(r["title"]) == "unclear" and shown < 14:
            print(f"  #{r['id']}  {r['title'][:96]}")
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
