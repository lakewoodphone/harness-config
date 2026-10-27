#!/usr/bin/env python3
"""security-scorecard — grade the two opinions against each other, and against the labels.

A second opinion nobody grades is just another opinion. This reads the record and answers four questions:

  1. How many episodes were judged, and did both the rules and the model judge each one?
  2. Where they disagreed, what did each say and why?
  3. Of the episodes with a human label, who was right?
  4. Is the record alive — are the two KPIs that cannot be improved by doing less (coverage, latency) moving?

It grades; it changes nothing. Exit code 0 means "ran", not "all good".
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime

FALLBACK = "fallback:shadow"
AGENT = "agent:dept_security"


def rows(conn, sql, args=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args)]


def report(db_path: str, days: int = 7) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
    window = f"-{days} days"

    episodes = rows(conn, """
        SELECT episode_id,
               MIN(created_at) AS first_seen,
               MAX(CASE WHEN decided_by = ? THEN decision END)  AS rule_verdict,
               MAX(CASE WHEN decided_by = ? THEN avs_level END) AS rule_avs,
               MAX(CASE WHEN decided_by = ? THEN decision END)  AS agent_verdict,
               MAX(CASE WHEN decided_by = ? THEN avs_level END) AS agent_avs,
               MAX(CASE WHEN decided_by = ? THEN reason_one_line END) AS agent_reason,
               MAX(CASE WHEN decided_by = ? THEN reason_one_line END) AS rule_reason,
               MAX(CASE WHEN decided_by LIKE 'agent%' AND json_extract(considered,'$.clamped') THEN 1 ELSE 0 END) AS clamped,
               MAX(CASE WHEN decided_by LIKE 'agent%' AND json_extract(considered,'$.injection_suspected') THEN 1 ELSE 0 END) AS injected
        FROM security_decision
        WHERE episode_id IS NOT NULL AND created_at > datetime('now', ?)
        GROUP BY episode_id ORDER BY first_seen
    """, (FALLBACK, FALLBACK, AGENT, AGENT, AGENT, FALLBACK, window))

    labels = {r["episode_id"]: r for r in rows(conn, """
        SELECT episode_id, label, evidence_class, confidence, supersedes_id FROM security_label
        WHERE created_at > datetime('now', ?) ORDER BY id
    """, (window,))}

    counts = rows(conn, """
        SELECT (SELECT COUNT(*) FROM security_event   WHERE created_at > datetime('now', ?)) AS events,
               (SELECT COUNT(*) FROM security_decision WHERE created_at > datetime('now', ?)) AS decisions,
               (SELECT COUNT(*) FROM security_label    WHERE created_at > datetime('now', ?)) AS labels,
               (SELECT COUNT(*) FROM security_action   WHERE attempted_at > datetime('now', ?)) AS actions,
               (SELECT COUNT(*) FROM entry_event       WHERE created_at > datetime('now', ?)) AS entries
    """, (window,) * 5)[0]

    print(f"=== security scorecard — last {days} day(s) — {db_path}")
    print(f"record: events={counts['events']} decisions={counts['decisions']} labels={counts['labels']} "
          f"actions={counts['actions']} entry_events={counts['entries']}")
    if not episodes:
        print("\nno episodes judged in the window. That is a statement about the building, not about the system.")
        return 0

    both = [e for e in episodes if e["rule_verdict"] and e["agent_verdict"]]
    rule_only = [e for e in episodes if e["rule_verdict"] and not e["agent_verdict"]]
    agree = [e for e in both if e["rule_verdict"] == e["agent_verdict"]]
    disagree = [e for e in both if e["rule_verdict"] != e["agent_verdict"]]

    print(f"\nepisodes judged: {len(episodes)}   both opinions: {len(both)}   rules only: {len(rule_only)}")
    if both:
        print(f"agreement: {len(agree)}/{len(both)} ({100*len(agree)//max(len(both),1)}%)")
    if rule_only:
        print(f"WARNING: {len(rule_only)} episode(s) have no agent verdict — the agent was down or over budget")

    graded = [e for e in both if e["episode_id"] in labels]
    if graded:
        def correct(v, lab):
            benign = lab in ("owner", "parent", "wife", "guest", "tenant", "customer", "passer_by",
                             "courier", "worker", "drill", "infrastructure_false")
            return (v == "NO_ALARM") if benign else (v == "ALARM")
        r_ok = sum(1 for e in graded if correct(e["rule_verdict"], labels[e["episode_id"]]["label"]))
        a_ok = sum(1 for e in graded if correct(e["agent_verdict"], labels[e["episode_id"]]["label"]))
        print(f"\nlabelled episodes: {len(graded)}   rules correct: {r_ok}   agent correct: {a_ok}")
    else:
        print("\nlabelled episodes: 0 — neither opinion can be graded yet. A label needs evidence "
              "(credential, frame, or the owner's word), never a disarm.")

    if disagree:
        print(f"\ndisagreements ({len(disagree)}):")
        for e in disagree:
            print(f"  {e['episode_id']}")
            print(f"    rule  : {e['rule_verdict']} lvl {e['rule_avs']} — {(e['rule_reason'] or '')[:90]}")
            print(f"    agent : {e['agent_verdict']} lvl {e['agent_avs']} — {(e['agent_reason'] or '')[:90]}")

    flagged = [e for e in episodes if e["injected"]]
    if flagged:
        print(f"\ninjection flagged on {len(flagged)} episode(s): {[e['episode_id'] for e in flagged]}")
    clamps = [e for e in episodes if e["clamped"]]
    if clamps:
        print(f"model level clamped on {len(clamps)} episode(s) (scale protected)")

    print("\nper-episode:")
    for e in episodes:
        lab = labels.get(e["episode_id"], {}).get("label", "-")
        print(f"  {e['first_seen'][:19]}  {e['episode_id'][:44]:44s}  rule={e['rule_verdict'] or '-':9s} "
              f"agent={e['agent_verdict'] or '-':9s} label={lab}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    return report(args.db, args.days)


if __name__ == "__main__":
    raise SystemExit(main())
