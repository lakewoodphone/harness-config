"""Stagnation detector — find departments that have stopped producing anything.

WHY THIS EXISTS
---------------
The owner asked for "a department that makes sure all other departments keep
evolving". What existed was a scorecard: `mashgiach_dept_scores` records weekly
autonomy/quality/initiative/accuracy per department. A scorecard *describes*
quiet; nothing acted on it. And until 2026-10-26 it could not even describe
quiet, because `findings_count` was a literal 0 in all 6,244 rows.

Two distinct kinds of stagnation, and they must not be conflated:

  * SILENT   — the department produced no tick at all in the window. It is not
               working, and a score alone never said so.
  * IDLE     — it ticked, but produced no findings. It is working and finding
               nothing, which for a monitoring or audit desk is its own failure.

A department that has never been ticked cannot be judged by findings, so SILENT
is tested first and IDLE only applies to a department that is actually running.

This writes one `mashgiach_audit_log` row per stagnant department, deduplicated
per (department, window) so an hourly run does not flood the log. It fixes
nothing and escalates nothing: closing a finding is a separate capability the
mashgiach still does not have (`auto_fixes` is 0 everywhere).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

#: Window in days. A week is the cadence the weekly scorecard already uses.
WINDOW_DAYS = 7

#: A department whose most recent tick is older than this is SILENT.
SILENT_AFTER_DAYS = 3


def _connect(db_url: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_url.replace("sqlite:///", ""), timeout=10.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def detect(db_url: str, *, window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """Find stagnant departments. Returns the verdicts; also logs findings."""
    conn = _connect(db_url)
    silent: list[dict[str, Any]] = []
    idle: list[dict[str, Any]] = []
    logged = 0
    errors: list[str] = []
    try:
        depts = [
            r["agent_id"]
            for r in conn.execute(
                """
                SELECT DISTINCT assigned_agent AS agent_id FROM goal_plans
                 WHERE assigned_agent LIKE 'dept_%'
                UNION
                SELECT DISTINCT department AS agent_id FROM standing_work_orders
                 WHERE department LIKE 'dept_%'
                """
            ).fetchall()
            if r["agent_id"] and str(r["agent_id"]).startswith("dept_")
        ]

        for dept in depts:
            try:
                tick = conn.execute(
                    """
                    SELECT MAX(started_at) AS last, COUNT(*) AS n
                    FROM tick_telemetry
                    WHERE agent_id = ?
                      AND started_at > datetime('now', ?)
                    """,
                    (dept, f"-{window_days} days"),
                ).fetchone()
                ticks = int(tick["n"] or 0) if tick else 0
                last = tick["last"] if tick else None

                if ticks == 0:
                    silent.append({"department": dept, "last_tick": last})
                    kind, text = (
                        "stagnant_silent",
                        f"{dept} has not ticked in {window_days} days. "
                        "It is not working, and no score reported that.",
                    )
                else:
                    finds = conn.execute(
                        """
                        SELECT COUNT(*) AS n FROM mashgiach_audit_log
                        WHERE (department = ? OR agent_id = ?)
                          AND created_at > datetime('now', ?)
                        """,
                        (dept, dept, f"-{window_days} days"),
                    ).fetchone()
                    n = int(finds["n"] or 0) if finds else 0
                    if n == 0:
                        idle.append({"department": dept, "ticks": ticks})
                        kind, text = (
                            "stagnant_idle",
                            f"{dept} ticked {ticks} times in {window_days} days and "
                            "produced zero findings.",
                        )
                    else:
                        continue

                # Deduplicate per (department, kind) inside the window so an
                # hourly run cannot flood the audit log.
                dup = conn.execute(
                    """
                    SELECT 1 FROM mashgiach_audit_log
                    WHERE finding_type = ?
                      AND (department = ? OR agent_id = ?)
                      AND created_at > datetime('now', '-1 day')
                    LIMIT 1
                    """,
                    (kind, dept, dept),
                ).fetchone()
                if dup:
                    continue

                conn.execute(
                    """
                    INSERT INTO mashgiach_audit_log
                        (agent_id, department, finding_type, severity,
                         auto_fixed, finding_text, correction_text, created_at)
                    VALUES ('dept_mashgiach', ?, ?, 'warning', 0, ?, '', datetime('now'))
                    """,
                    (dept, kind, text),
                )
                logged += 1
            except Exception as exc:  # noqa: BLE001 - one dept must not stop the sweep
                errors.append(f"{dept}: {exc}")
        conn.commit()
    finally:
        conn.close()

    result = {
        "ok": True,
        "departments_checked": len(depts),
        "silent": silent,
        "idle": idle,
        "findings_logged": logged,
        "window_days": window_days,
        "errors": errors[:5],
    }
    if silent or idle:
        log.warning(
            "stagnation: %d silent, %d idle, %d finding(s) logged over %d days",
            len(silent),
            len(idle),
            logged,
            window_days,
        )
    return result
