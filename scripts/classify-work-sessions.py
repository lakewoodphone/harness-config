"""Classify recent work sessions by task SHAPE and by tool REACHABILITY.

P73 left three candidate causes for work sessions exhausting their budget without
completing, and refused to pick between them by preference:

  1. the goals do not fit the budget (initiative-sized tasks given 5 steps)
  2. the work is not reachable from this host (HA is LAN-bound, CI/PR needs the net)
  3. the 41 KB prompt buries the instruction

This is the cheap measurement that separates them. Read-only: SELECTs only.

The reasoning: if failures concentrate in one shape, the lever is the goal
generator; if they spread evenly across shapes, the lever is the loop or the
prompt. A distribution is worth more here than another single example.
"""

from __future__ import annotations

import collections
import re
import sqlite3
import sys

DB = "data/secretary.db"

# Marker -> what it means, in the order the loop can emit them.
MARKERS = [
    ("STALLED_REPEATING_OUTPUT", "stalled_repeating"),
    ("DROPPED-ACTION-TAGS", "dropped_tags"),
    ("STEP_BUDGET_EXHAUSTED", "budget_exhausted"),
    ("COMPLETION BLOCKED", "artifact_blocked"),
    ("HARD-CEILING", "hard_ceiling"),
    ("AUTO-COMPLETED", "auto_completed"),
    ("FORCE-COMPLETED", "force_completed"),
    ("[WORK_DONE]", "work_done"),
]

# Shape heuristics, applied to the session title (the most stable signal).
SHAPES = [
    ("initiative", r"\b(initiative|department|quarterly|strategy|roadmap|improve|"
                   r"ongoing|ensure|maintain|review and|life domain)\b"),
    ("monitor_check", r"\b(hourly|daily|bi-daily|monitor|check .*status|sensor|"
                      r"uptime|freshness|poll)\b"),
    ("fix_or_build", r"\b(fix|build|implement|repair|add|create|wire|deploy|"
                     r"migrate|refactor|tighten|reduce|cut)\b"),
    ("investigate", r"\b(investigate|diagnose|root cause|why|audit|analyse|analyze)\b"),
    ("close_or_triage", r"\b(close|triage|reconcile|dedupe|cleanup|clean up|hygiene)\b"),
]

# Subject reachability: where does the work have to happen?
REACH = [
    ("home_assistant", r"\b(home assistant|ha |hass|door sensor|phoenix_|sensor state)\b"),
    ("ci_pr_github", r"\b(ci/cd|pipeline|open pr|pull request|github|actions|workflow run)\b"),
    ("browser_or_web", r"\b(browser|playwright|scrape|crawl|npm|website|dashboard)\b"),
    ("local_repo", r"\b(repo|file|test|code|script|server|sync|task #)\b"),
]


def classify(title: str, patterns) -> list[str]:
    t = (title or "").lower()
    return [name for name, pat in patterns if re.search(pat, t)]


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = list(
        conn.execute(
            """SELECT id, status, title, output_log, started_at
               FROM work_sessions
               WHERE started_at > '2026-09-07'
               ORDER BY id DESC LIMIT 400"""
        )
    )
    print(f"sessions analysed: {len(rows)}  (since 2026-09-07)\n")

    by_status = collections.Counter(r["status"] for r in rows)
    print("== outcome ==")
    for k, v in by_status.most_common():
        print(f"  {k:<12} {v:>4}  {v*100/len(rows):5.1f}%")

    print("\n== failure markers (failed sessions only) ==")
    failed = [r for r in rows if r["status"] == "failed"]
    marker_counts = collections.Counter()
    for r in failed:
        log = r["output_log"] or ""
        hit = [name for tok, name in MARKERS if tok in log]
        marker_counts[hit[-1] if hit else "no_marker"] += 1
    for k, v in marker_counts.most_common():
        print(f"  {k:<20} {v:>4}  {v*100/len(failed):5.1f}% of failures")

    print("\n== shape x outcome ==")
    shape_tot = collections.Counter()
    shape_fail = collections.Counter()
    for r in rows:
        shapes = classify(r["title"], SHAPES) or ["unshaped"]
        for s in shapes:
            shape_tot[s] += 1
            if r["status"] == "failed":
                shape_fail[s] += 1
    print(f"  {'shape':<18} {'total':>6} {'failed':>7} {'fail%':>7}")
    for s, n in shape_tot.most_common():
        f = shape_fail[s]
        print(f"  {s:<18} {n:>6} {f:>7} {f*100/n:>6.1f}%")

    print("\n== reachability x outcome ==")
    reach_tot = collections.Counter()
    reach_fail = collections.Counter()
    for r in rows:
        targets = classify(r["title"], REACH) or ["unclassified"]
        for t in targets:
            reach_tot[t] += 1
            if r["status"] == "failed":
                reach_fail[t] += 1
    print(f"  {'target':<18} {'total':>6} {'failed':>7} {'fail%':>7}")
    for t, n in reach_tot.most_common():
        f = reach_fail[t]
        print(f"  {t:<18} {n:>6} {f:>7} {f*100/n:>6.1f}%")

    print("\n== did any failed session get a tool call at all? ==")
    no_action = 0
    for r in failed:
        log = r["output_log"] or ""
        if "Work action " not in log:
            no_action += 1
    print(f"  failed sessions with NO executed action logged: {no_action}/{len(failed)} "
          f"({no_action*100/max(len(failed),1):.1f}%)")

    print("\n== longest-title failures (are they initiative-sized?) ==")
    for r in sorted(failed, key=lambda r: len(r["title"] or ""), reverse=True)[:5]:
        print(f"  {len(r['title'] or ''):>4} chars | {str(r['title'])[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
