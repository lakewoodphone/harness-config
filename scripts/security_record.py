#!/usr/bin/env python3
"""security-record — read the shop's security record, and say plainly what it does and does not know.

WHY. The rebuild writes nine tables (`security_event`, `security_decision`, `security_label`,
`security_action`, `replay_run`, `replay_episode`, `subject`, `credential`, `entry_event`) and until now the only
things that could read them were the scripts that wrote them. A department whose mission names the building
could not see it. This is the door.

READ-ONLY, ALWAYS. Opens `/root/authority.db` with `mode=ro`. It never writes, never pages, never touches Home
Assistant.

THE FOUR QUESTIONS IT ANSWERS
  mode=recent      what has been judged lately, rules beside model   (default)
  mode=episodes    every episode with its verdicts and its label
  mode=unlabelled  episodes that have no evidence-based label yet    <- the backlog that blocks learning
  mode=health      is anything being written at all, and how stale

The distinction it refuses to blur: **an empty table means no writer, never a quiet week.** Every reply carries
`last_event_at` and `counts` so a reader cannot mistake silence for safety.
"""
from __future__ import annotations

import json
import os
import sqlite3

DB = os.environ.get("AUTHORITY_DB", "/root/authority.db")


def _conn(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def _counts(conn) -> dict:
    q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    return {
        "events": q("SELECT COUNT(*) FROM security_event"),
        "decisions": q("SELECT COUNT(*) FROM security_decision"),
        "labels": q("SELECT COUNT(*) FROM security_label"),
        "actions": q("SELECT COUNT(*) FROM security_action"),
        "entry_events": q("SELECT COUNT(*) FROM entry_event"),
        "last_event_at": q("SELECT MAX(occurred_at) FROM security_event"),
        "last_decision_at": q("SELECT MAX(created_at) FROM security_decision"),
    }


def run(mode: str = "recent", limit: str = "20", episode: str = "", days: str = "7", db: str = DB,
        **extra) -> dict:
    """Called by POST /tools/run/security_record with string params. Tolerant of unknown keys."""
    mode = (mode or extra.get("what") or "recent").strip().lower()
    try:
        n = max(1, min(int(str(limit or 20)), 200))
    except ValueError:
        n = 20
    try:
        d = max(1, min(int(str(days or 7)), 365))
    except ValueError:
        d = 7
    window = f"-{d} days"

    try:
        conn = _conn(db)
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"cannot open the record read-only: {exc}"}

    try:
        counts = _counts(conn)

        if mode == "health":
            return {"ok": True, "mode": mode, "counts": counts,
                    "note": "an empty or stale record means nothing is writing — it does not mean nothing "
                            "happened. Check `last_event_at` against the clock before concluding anything."}

        if mode in ("recent", "decisions", "latest"):
            rows = _rows(conn, """
                SELECT episode_id,
                       MIN(created_at) AS first_at,
                       MAX(CASE WHEN decided_by='fallback:shadow' THEN decision END) AS rule_verdict,
                       MAX(CASE WHEN decided_by='fallback:shadow' THEN avs_level END) AS rule_avs,
                       MAX(CASE WHEN decided_by LIKE 'agent%' THEN decision END) AS agent_verdict,
                       MAX(CASE WHEN decided_by LIKE 'agent%' THEN avs_level END) AS agent_avs,
                       MAX(CASE WHEN decided_by LIKE 'agent%' THEN reason_one_line END) AS agent_reason,
                       MAX(CASE WHEN decided_by='fallback:shadow' THEN reason_one_line END) AS rule_reason
                FROM security_decision
                WHERE episode_id IS NOT NULL AND created_at > datetime('now', ?)
                GROUP BY episode_id ORDER BY first_at DESC LIMIT ?""", (window, n))
            return {"ok": True, "mode": mode, "days": d, "counts": counts, "episodes": rows,
                    "disagreements": [r for r in rows if r["rule_verdict"] and r["agent_verdict"]
                                      and r["rule_verdict"] != r["agent_verdict"]]}

        if mode in ("episodes", "episode"):
            args = ()
            where = "WHERE 1=1"
            if episode:
                where += " AND d.episode_id = ?"
                args = (episode,)
            rows = _rows(conn, f"""
                SELECT d.episode_id,
                       MIN(d.created_at) AS first_at,
                       MAX(CASE WHEN d.decided_by='fallback:shadow' THEN d.decision END) AS rule_verdict,
                       MAX(CASE WHEN d.decided_by LIKE 'agent%' THEN d.decision END) AS agent_verdict,
                       (SELECT label FROM security_label l WHERE l.episode_id=d.episode_id
                         ORDER BY l.id DESC LIMIT 1) AS label,
                       (SELECT evidence_class FROM security_label l WHERE l.episode_id=d.episode_id
                         ORDER BY l.id DESC LIMIT 1) AS label_evidence
                FROM security_decision d {where}
                GROUP BY d.episode_id ORDER BY first_at DESC LIMIT ?""", args + (n,))
            return {"ok": True, "mode": mode, "counts": counts, "episodes": rows}

        if mode in ("unlabelled", "backlog", "unlabeled"):
            rows = _rows(conn, """
                SELECT d.episode_id, MIN(d.created_at) AS first_at,
                       MAX(CASE WHEN d.decided_by='fallback:shadow' THEN d.decision END) AS rule_verdict,
                       MAX(CASE WHEN d.decided_by LIKE 'agent%' THEN d.decision END) AS agent_verdict
                FROM security_decision d
                WHERE d.episode_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM security_label l WHERE l.episode_id = d.episode_id)
                GROUP BY d.episode_id ORDER BY first_at DESC LIMIT ?""", (n,))
            return {"ok": True, "mode": mode, "counts": counts, "unlabelled": rows,
                    "note": "no label can be written without evidence (credential, frame, or the owner's word); "
                            "a disarm alone is never evidence."}

        return {"ok": False, "error": f"unknown mode {mode!r}",
                "modes": ["recent", "episodes", "unlabelled", "health"]}
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"record query failed: {exc}"}
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    out = run(**{k: v for k, v in zip(sys.argv[1::2], sys.argv[2::2])}) if len(sys.argv) > 1 else run()
    print(json.dumps(out, indent=2, default=str))
