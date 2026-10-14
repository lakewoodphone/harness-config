#!/usr/bin/env python3
"""Freeze the company's numbers, with the queries, so a change can be PROVED to have moved them.

WHY THIS EXISTS. Round 2 captured a baseline at `capture_baseline.py`, and that script carries a
defect that made every rolling-window figure it produced **one day too long** (L3801): timestamps in
`model_usage`, `work_sessions` and `tick_telemetry` are stored ISO-8601 `T`-separated
(`2026-10-14T11:05:01.867681+00:00`), while `datetime('now','-7 days')` returns a **space**-separated
string. SQLite compares TEXT byte-wise and `'T'` (0x54) sorts after `' '` (0x20), so
`created_at >= datetime('now','-7 days')` silently matches every row of the eighth day as well.
Measured, same column, same minute: a literal `T` boundary gave 3,218 calls / 33.03 USD where the
`datetime()` form gave 5,023 / 45.45 USD.

So every window in this file is built with `strftime('%Y-%m-%dT%H:%M:%S','now',...)` — the *same*
shape as the stored value — and the file states its own window bounds so a reader can check them
rather than trust them.

SAFETY. Opens the authority database `mode=ro` + `query_only`; never writes it. Read-only queries
only. Intended to run ON the authority (the database is 26 GB and must not cross the network) and to
write its report to a file there; nothing heavy.

USAGE
    python3 capture-company-baseline.py [--db PATH] [--out DIR] [--label TEXT]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

# The stored timestamp shape, reproduced exactly. strftime with this format returns
# '2026-10-14T11:50:00', which compares correctly against '2026-10-14T11:05:01.867681+00:00'
# because the ISO fraction and offset only extend the string to the right.
T = "strftime('%Y-%m-%dT%H:%M:%S','now',{})"

QUERIES: list[tuple[str, str]] = [
    ("the window bounds actually used",
     f"SELECT {T.format(chr(39)+'-7 days'+chr(39))} AS since_7d, "
     f"{T.format(chr(39)+'-1 days'+chr(39))} AS since_1d, "
     f"{T.format(chr(39)+'-30 minutes'+chr(39))} AS since_30m"),

    ("work_sessions by status, 7d",
     "SELECT status, COUNT(*) FROM work_sessions "
     f"WHERE started_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY status ORDER BY 2 DESC"),

    ("work_sessions by status, 24h",
     "SELECT status, COUNT(*) FROM work_sessions "
     f"WHERE started_at >= {T.format(chr(39)+'-1 days'+chr(39))} GROUP BY status ORDER BY 2 DESC"),

    ("work_sessions per calendar day, 10d (date-grouped, cannot leak a day)",
     "SELECT date(started_at) AS d, COUNT(*) AS n, "
     "SUM(status='completed') AS completed, SUM(status='failed') AS failed, "
     "ROUND(SUM(status='completed')*100.0/COUNT(*),1) AS completed_pct "
     "FROM work_sessions WHERE date(started_at) >= date('now','-10 days') GROUP BY 1 ORDER BY 1"),

    ("failure marker actually written, 7d",
     "SELECT CASE "
     " WHEN output_log LIKE '%[STEP_BUDGET_EXHAUSTED:%' THEN 'STEP_BUDGET_EXHAUSTED' "
     " WHEN output_log LIKE '%[TOOL_LOOP_DEADLOCK:%' THEN 'TOOL_LOOP_DEADLOCK' "
     " WHEN output_log LIKE '%[stalled_no_tool_call:%' THEN 'stalled_no_tool_call' "
     " WHEN output_log LIKE '%[STALLED_REPEATING_OUTPUT:%' THEN 'STALLED_REPEATING_OUTPUT' "
     " WHEN output_log LIKE '%[EMPTY_TURN%' THEN 'EMPTY_TURN' "
     " WHEN output_log LIKE '%[TASK-CLOSED-BY-SESSION:%' THEN 'TASK-CLOSED-BY-SESSION' "
     " WHEN output_log LIKE '%[ARTEFACT:%' THEN 'ARTEFACT' "
     " WHEN output_log LIKE '%[OUTBOUND:%' THEN 'OUTBOUND' "
     " WHEN status = 'completed' THEN 'completed_no_marker' "
     " ELSE 'other' END AS marker, COUNT(*) FROM work_sessions "
     f"WHERE started_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY marker ORDER BY 2 DESC"),

    ("completion MECHANISM per day, 10d — the row that proves a real completion happened",
     "SELECT date(started_at) AS d, "
     "SUM(output_log LIKE '%TASK-CLOSED-BY-SESSION%') AS by_session, "
     "SUM(output_log LIKE '%[ARTEFACT:%') AS artefact, "
     "SUM(output_log LIKE '%[OUTBOUND:%') AS outbound, "
     "SUM(output_log LIKE '%[WORK_DONE]%') AS mentions_work_done, "
     "COUNT(*) AS sessions FROM work_sessions "
     "WHERE date(started_at) >= date('now','-10 days') GROUP BY 1 ORDER BY 1"),

    ("tasks retried, and whether a retry ever succeeds, 7d",
     "SELECT COUNT(*) AS tasks_with_2plus, "
     "SUM(succeeded) AS eventually_completed FROM ("
     "  SELECT task_id, MAX(status='completed') AS succeeded FROM work_sessions "
     f"  WHERE started_at >= {T.format(chr(39)+'-7 days'+chr(39))} "
     "  GROUP BY task_id HAVING COUNT(*) >= 2)"),

    ("model_usage, per calendar day, 10d",
     "SELECT date(created_at) AS d, COUNT(*) AS calls, SUM(total_tokens) AS tokens, "
     "ROUND(SUM(estimated_cost_usd),4) AS usd FROM model_usage "
     "WHERE date(created_at) >= date('now','-10 days') GROUP BY 1 ORDER BY 1"),

    ("model_usage, 7d and 24h, corrected windows",
     "SELECT '7d' AS w, COUNT(*), SUM(total_tokens), ROUND(SUM(estimated_cost_usd),4) FROM model_usage "
     f"WHERE created_at >= {T.format(chr(39)+'-7 days'+chr(39))} "
     "UNION ALL "
     "SELECT '24h', COUNT(*), SUM(total_tokens), ROUND(SUM(estimated_cost_usd),4) FROM model_usage "
     f"WHERE created_at >= {T.format(chr(39)+'-1 days'+chr(39))}"),

    ("model ids in use, 7d — and the cost of the ones that fail",
     "SELECT model, COUNT(*) AS calls, ROUND(SUM(estimated_cost_usd),4) AS usd FROM model_usage "
     f"WHERE created_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY 1 ORDER BY 3 DESC LIMIT 15"),

    ("tick_telemetry by outcome, 7d",
     "SELECT outcome, COUNT(*) FROM tick_telemetry "
     f"WHERE started_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY 1 ORDER BY 2 DESC"),

    ("tick_telemetry by tick_quality, 7d",
     "SELECT tick_quality, COUNT(*) FROM tick_telemetry "
     f"WHERE started_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY 1 ORDER BY 2 DESC"),

    ("autonomy_levels rows, and how many are L4",
     "SELECT COUNT(*) AS actions, SUM(current_level = 4) AS at_l4, "
     "SUM(current_level <= 1) AS at_l0_l1 FROM autonomy_levels"),

    ("autonomy_levels distribution",
     "SELECT current_level, COUNT(*) FROM autonomy_levels GROUP BY 1 ORDER BY 1"),

    ("tasks by status, live",
     "SELECT status, COUNT(*) FROM tasks GROUP BY 1 ORDER BY 2 DESC"),

    ("tasks open, and how old the oldest is",
     "SELECT COUNT(*) AS open, MIN(created_at) AS oldest, MAX(created_at) AS newest "
     "FROM tasks WHERE status NOT IN ('completed','cancelled','closed')"),

    ("owner_decision_queue, live",
     "SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY 1 ORDER BY 2 DESC"),

    ("memories written per day, 10d (is the diary still growing)",
     "SELECT date(created_at) AS d, COUNT(*) FROM memories "
     "WHERE date(created_at) >= date('now','-10 days') GROUP BY 1 ORDER BY 1"),

    ("memories by category, all time",
     "SELECT category, COUNT(*) FROM memories GROUP BY 1 ORDER BY 2 DESC LIMIT 12"),

    ("progress_checkpoints — written and never read",
     "SELECT COUNT(*) AS rows_, COUNT(DISTINCT session_id) AS sessions FROM progress_checkpoints"),

    ("error_log last 7d, by message family",
     "SELECT substr(error_message,1,60) AS msg, COUNT(*) FROM error_log "
     f"WHERE created_at >= {T.format(chr(39)+'-7 days'+chr(39))} GROUP BY 1 ORDER BY 2 DESC LIMIT 15"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--out", default="/home/zabz/evolution-corpus-v4/baselines")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = now.replace(":", "").replace("-", "")
    label = args.label or f"company-{stamp}"

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")

    sections: list[str] = []
    raw: dict[str, dict] = {}

    for title, sql in QUERIES:
        block = [f"## {title}", "", "```sql", sql, "```", ""]
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchall()
            block.append("| " + " | ".join(cols) + " |")
            block.append("|" + "---|" * len(cols))
            for r in rows:
                block.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
            raw[title] = {"columns": cols, "rows": rows}
            if not rows:
                block.append("")
                block.append("_(zero rows — this is a real negative: the query ran and matched nothing)_")
        except Exception as exc:  # a missing table is a fact about the database, not a crash
            block.append(f"QUERY FAILED: {type(exc).__name__}: {exc}")
            raw[title] = {"error": f"{type(exc).__name__}: {exc}"}
        block.append("")
        sections.append("\n".join(block))

    con.close()

    os.makedirs(args.out, exist_ok=True)
    md_path = os.path.join(args.out, f"baseline-{label}.md")
    json_path = os.path.join(args.out, f"baseline-{label}.json")

    header = [
        f"# BASELINE — the company, {label}",
        "",
        f"**Captured:** {now}",
        f"**Database:** `{args.db}`, read-only (`mode=ro`, `query_only`).",
        "",
        "Every window in this file is built with `strftime('%Y-%m-%dT%H:%M:%S','now',...)` — the same",
        "shape as the stored timestamps — and **not** with `datetime('now','-N days')`, which is one day",
        "too long against a `T`-format column (`L3801`). The first section prints the window bounds",
        "actually used, so a reader can check them rather than trust them.",
        "",
        "Regenerate with:",
        "",
        "```",
        "ssh secratary-cloud 'python3 /home/zabz/evolution/capture-company-baseline.py'",
        "```",
        "",
        "---",
        "",
    ]
    with open(md_path, "w") as fh:
        fh.write("\n".join(header) + "\n".join(sections))
    with open(json_path, "w") as fh:
        json.dump({"captured_at": now, "db": args.db, "label": label, "sections": raw}, fh, indent=1)

    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
