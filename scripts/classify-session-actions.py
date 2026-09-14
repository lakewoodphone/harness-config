"""Did the work happen, or did the session only look around?

The question the audit has been circling. Now answerable because the work loop
records WHICH actions each step executed (`[ACTIONS: n (names...)]`, added this
session), and because two things are settled:

  * task status is useless as evidence -- 659 of 666 failed sessions had their task
    closed AFTER the session ended, by housekeeping (stale auto-close or a
    goal-completion rollup), and zero before or during;
  * the recent "failure spike" is a labelling change: the live tree stopped
    recording budget-exhausted sessions as `completed`, which had been hiding
    620 force-completed and 581 auto-completed sessions in seven days.

So the honest question is not "how many failed" but "of the sessions that hit the
budget, how many actually changed anything". A session whose five steps called only
`system_health` and `list_tasks` produced no work. A session that called
`update_task` or `save_memory` did.

Read-only: SELECTs only. Safe to run against production.
"""

from __future__ import annotations

import collections
import re
import sqlite3
import sys

DB = "data/secretary.db"

# Actions that only look. Anything not listed here is treated as mutating, because
# the failure mode is under-reporting work, not over-reporting it.
READ_ONLY = {
    "system_health", "list_tasks", "list_dynamic_tools", "task_hygiene",
    "repo_read_file", "repo_list_dir", "repo_search", "repo_run_command",
    "github_read_file", "github_list_issues", "web_search", "fetch_url",
    "get_current_datetime", "list_goals", "list_owner_message_queue",
    "list_agents", "list_memories", "read_call_transcript", "check_health",
}
READ_PREFIXES = ("list_", "get_", "read_", "search_", "show_", "view_", "check_", "find_", "query_")

ACTIONS_RE = re.compile(r"\[ACTIONS:\s*\d+\s*\(([^)]*)\)\]")


def classify(action: str) -> str:
    a = (action or "").strip().lower()
    if not a or a == "?":
        return "unknown"
    if a in READ_ONLY:
        return "read"
    if a.startswith(READ_PREFIXES):
        return "read"
    return "mutating"


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT id, status, output_log FROM work_sessions "
        "WHERE output_log LIKE '%[ACTIONS:%' ORDER BY id DESC LIMIT 120"
    ))
    print(f"sessions carrying an [ACTIONS:] marker: {len(rows)}\n")
    if not rows:
        print("No session has yet logged its actions. Nothing can be concluded.")
        return 0

    by_status = collections.defaultdict(lambda: collections.Counter())
    totals = collections.Counter()
    for r in rows:
        acts = []
        for m in ACTIONS_RE.finditer(r["output_log"] or ""):
            acts += [x.strip() for x in m.group(1).split(",") if x.strip()]
        kinds = {classify(a) for a in acts}
        if not kinds:
            verdict = "no-actions"
        elif "mutating" in kinds:
            verdict = "mutated"
        elif kinds == {"read"}:
            verdict = "read-only"
        else:
            verdict = "unknown"
        by_status[r["status"]][verdict] += 1
        totals[verdict] += 1
        totals["all"] += 1

    print(f"{'session status':<14} {'mutated':>8} {'read-only':>10} {'no-actions':>11} {'unknown':>8}")
    for st, c in sorted(by_status.items()):
        print(f"{st:<14} {c['mutated']:>8} {c['read-only']:>10} {c['no-actions']:>11} {c['unknown']:>8}")
    print(f"\n{'TOTAL':<14} {totals['mutated']:>8} {totals['read-only']:>10} "
          f"{totals['no-actions']:>11} {totals['unknown']:>8}   of {totals['all']}")

    mut = totals["mutated"] * 100 / max(totals["all"], 1)
    ro = totals["read-only"] * 100 / max(totals["all"], 1)
    print(f"\n  mutated    : {mut:.0f}%")
    print(f"  read-only  : {ro:.0f}%")

    print("\n== the actions actually used, most common first ==")
    every = collections.Counter()
    for r in rows:
        for m in ACTIONS_RE.finditer(r["output_log"] or ""):
            for a in (x.strip() for x in m.group(1).split(",")):
                if a:
                    every[a] += 1
    for a, n in every.most_common(16):
        print(f"  {n:>4}  {a:<26} {classify(a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
