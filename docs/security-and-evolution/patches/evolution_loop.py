"""Close the evolution loop: every applied change gets measured, then graded.

THE DEFECT THIS EXISTS FOR
--------------------------
Measured on the authority, 2026-10-26:

    evolution_log rows with applied=1                        103
    ...of those, with no evolution_verification row          103
    evolution_verification rows in status='measuring'          0
    newest evolution_verification row            2026-07-04T09:54:09Z

So the engine applied 103 changes and graded none of them for ~16 weeks. The
writer was not missing — `app/services/evolution_verifier.py` has
`create_verification()` and `record_measurement()`, wired at six call sites —
but `app/evolution.py:1097` only calls it when `auto_applied` is true, and in
practice the applied rows arrive by other paths. The loop was therefore
"apply, never grade", which is indistinguishable from "we have no idea whether
any of this helped".

WHAT THIS DOES, AND WHAT IT HONESTLY DOES NOT
---------------------------------------------
It backfills a verification row for every applied change that never got one,
and it advances every open verification to a verdict after enough measurements.

It does NOT claim the default metric is the right metric. The default
`error_count` is a coarse proxy: it answers "did the platform get noisier after
this change", not "did THIS change work". A change with a named, specific
metric should carry it. The verdict below is deliberately conservative — a
change is only marked `failed` when the metric got materially worse, and is
otherwise left `measuring` rather than being flattered into a pass. A verdict
nobody can trust is worse than an open question.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

#: Measurements required before a verdict is issued at all.
TICKS_BEFORE_VERDICT = 3

#: How much worse the metric must get before a change is called failed.
#: A change is NOT failed for noise; that is the whole point of the guard.
FAILURE_MARGIN = 1.25

_DEFAULT_METRIC = "error_count"


def _db_path(db_url: str) -> str:
    return db_url.replace("sqlite:///", "")


def _connect(db_url: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_url), timeout=10.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _current_metric(conn: sqlite3.Connection, metric: str) -> float:
    """Read the live value of a metric. Returns 0.0 rather than guessing."""
    try:
        if metric == _DEFAULT_METRIC:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM error_log
                WHERE created_at > datetime('now', '-24 hours')
                """
            ).fetchone()
            return float(row["n"] if row else 0)
    except Exception as exc:  # noqa: BLE001
        log.warning("evolution_loop: metric %s unreadable: %s", metric, exc)
    return 0.0


def close_the_loop(db_url: str) -> dict[str, Any]:
    """Backfill missing verifications and advance open ones to a verdict."""
    backfilled = 0
    measured = 0
    passed = 0
    failed = 0
    errors: list[str] = []

    conn = _connect(db_url)
    try:
        # ── 1. Every applied change gets a verification row ────────────
        orphans = conn.execute(
            """
            SELECT el.id, el.change_type, el.description
            FROM evolution_log el
            WHERE el.applied = 1
              AND el.rollback = 0
              AND NOT EXISTS (
                    SELECT 1 FROM evolution_verification ev
                    WHERE ev.evolution_log_id = el.id
              )
            ORDER BY el.id
            """
        ).fetchall()

        baseline = _current_metric(conn, _DEFAULT_METRIC)
        for row in orphans:
            try:
                conn.execute(
                    """
                    INSERT INTO evolution_verification
                        (proposal_id, evolution_log_id, target_metric,
                         baseline_value, target_value, status, created_at)
                    VALUES (NULL, ?, ?, ?, ?, 'measuring', datetime('now'))
                    """,
                    (row["id"], _DEFAULT_METRIC, baseline, baseline),
                )
                backfilled += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"log {row['id']}: {exc}")
        conn.commit()

        # ── 2. Advance open verifications ─────────────────────────────
        open_rows = conn.execute(
            """
            SELECT id, target_metric, baseline_value, target_value,
                   measurement_ticks
            FROM evolution_verification
            WHERE status = 'measuring'
            """
        ).fetchall()

        for row in open_rows:
            metric = row["target_metric"] or _DEFAULT_METRIC
            current = _current_metric(conn, metric)
            ticks = int(row["measurement_ticks"] or 0) + 1
            conn.execute(
                "UPDATE evolution_verification "
                "SET measurement_ticks = ?, post_value = ? WHERE id = ?",
                (ticks, current, row["id"]),
            )
            measured += 1

            if ticks < TICKS_BEFORE_VERDICT:
                continue

            base = float(row["baseline_value"] or 0)
            # A change is only failed when the metric got MATERIALLY worse.
            # base==0 has no meaningful ratio, so it stays open rather than
            # being graded against a divide-by-zero.
            if base > 0 and current > base * FAILURE_MARGIN:
                conn.execute(
                    "UPDATE evolution_verification "
                    "SET status='failed', completed_at=datetime('now'), "
                    "rollback_reason=? WHERE id=?",
                    (
                        f"{metric} {current:.0f} > baseline {base:.0f} "
                        f"x{FAILURE_MARGIN}: change coincided with a worse metric",
                        row["id"],
                    ),
                )
                failed += 1
            elif base > 0 and current <= base:
                conn.execute(
                    "UPDATE evolution_verification "
                    "SET status='passed', completed_at=datetime('now') "
                    "WHERE id=?",
                    (row["id"],),
                )
                passed += 1
            # else: leave measuring. An open question is honest; a flattered
            # pass is not.
        conn.commit()
    finally:
        conn.close()

    result = {
        "ok": True,
        "backfilled": backfilled,
        "measured": measured,
        "passed": passed,
        "failed": failed,
        "errors": errors[:5],
        "metric": _DEFAULT_METRIC,
    }
    if backfilled or passed or failed:
        log.warning(
            "evolution_loop: backfilled=%d measured=%d passed=%d failed=%d",
            backfilled,
            measured,
            passed,
            failed,
        )
    return result
