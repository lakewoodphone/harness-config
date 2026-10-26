#!/usr/bin/env python3
"""Make mashgiach_dept_scores carry REAL finding counts.

The defect: `weekly_report` inserted a literal `0` for `findings_count` and
never wrote `auto_fixes` or `escalations` at all, so those defaulted to 0.
Measured 2026-10-26 over the whole table: 6,244 rows, 88 departments,
SUM(findings_count)=0, SUM(auto_fixes)=0, SUM(escalations)=0 — every row.

`daily_scan()` writes real rows into `mashgiach_audit_log`, so the data existed
and was never joined back onto the scorecard. A scorecard reporting zero
findings for every department every week is a constant, not a measurement, and
it made the mashgiach look healthy by construction.
"""
import io
import sys

PATH = "app/services/mashgiach.py"
src = io.open(PATH, encoding="utf-8").read()

if "_audit_counts" in src:
    print("ALREADY PATCHED - no change")
    sys.exit(0)

old = '''            # Upsert into mashgiach_dept_scores
            conn.execute(
                """
                INSERT OR REPLACE INTO mashgiach_dept_scores
                    (department, week_start, autonomy_score, quality_score,
                     initiative_score, accuracy_score, findings_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dept_id,
                    week_start,
                    round(autonomy, 2),
                    round(quality, 2),
                    round(initiative, 2),
                    round(accuracy, 2),
                    0,
                    _now_utc(),
                ),
            )
'''

new = '''            # ── Real audit rollup (2026-10-26) ────────────────────
            # These three columns used to be a literal 0 / never written, so
            # all 6,244 rows read findings=0, fixes=0, esc=0 and the scorecard
            # could not tell a clean department from a silent one.
            # daily_scan() already writes mashgiach_audit_log; this is the join
            # that was missing.
            _audit_counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS findings,
                    COALESCE(SUM(auto_fixed), 0) AS fixes,
                    COALESCE(SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END), 0) AS esc
                FROM mashgiach_audit_log
                WHERE created_at > ?
                  AND (department = ? OR agent_id = ?)
                """,
                (week_ago, dept_id, dept_id),
            ).fetchone()
            findings_count = int(_audit_counts["findings"] or 0) if _audit_counts else 0
            auto_fixes_count = int(_audit_counts["fixes"] or 0) if _audit_counts else 0
            escalations_count = int(_audit_counts["esc"] or 0) if _audit_counts else 0

            # Upsert into mashgiach_dept_scores
            conn.execute(
                """
                INSERT OR REPLACE INTO mashgiach_dept_scores
                    (department, week_start, autonomy_score, quality_score,
                     initiative_score, accuracy_score, findings_count,
                     auto_fixes, escalations, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dept_id,
                    week_start,
                    round(autonomy, 2),
                    round(quality, 2),
                    round(initiative, 2),
                    round(accuracy, 2),
                    findings_count,
                    auto_fixes_count,
                    escalations_count,
                    _now_utc(),
                ),
            )
'''

if old not in src:
    print("FATAL: upsert block not found verbatim")
    sys.exit(10)
src = src.replace(old, new, 1)

old_entry = '''                    "scores": {
                        "autonomy": round(autonomy, 2),'''
new_entry = '''                    "findings": findings_count,
                    "auto_fixes": auto_fixes_count,
                    "escalations": escalations_count,
                    "scores": {
                        "autonomy": round(autonomy, 2),'''
if old_entry in src:
    src = src.replace(old_entry, new_entry, 1)
else:
    print("WARN: scorecard entry block not found; counts written to DB only")

io.open(PATH + ".new", "w", encoding="utf-8", newline="\n").write(src)
print("wrote %s.new" % PATH)
