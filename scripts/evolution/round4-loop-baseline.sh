#!/usr/bin/env bash
# The round-4 loop measurement: run the SAME query before and after, and show both.
#
# The claim to be tested is narrow and falsifiable: a session that spends its whole budget reading
# should now (a) be told to converge, (b) block honestly with a marker that names the real reason
# instead of a generic step-budget failure, and (c) always leave a handoff.
#
# Usage:  round4-loop-baseline.sh before | after
set -uo pipefail
DB=${AUTHORITY_DB:-/root/authority.db}
WHEN=${1:-now}

echo "=== the failure markers, last 24h, and the completion mechanism (day-grouped)"
sqlite3 -readonly "$DB" "
SELECT 'STEP_BUDGET_EXHAUSTED' AS marker, COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[STEP_BUDGET_EXHAUSTED:%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'TOOL_LOOP_DEADLOCK', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[TOOL_LOOP_DEADLOCK:%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'STALLED_REPEATING_OUTPUT', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[STALLED_REPEATING_OUTPUT:%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'stalled_no_tool_call', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[stalled_no_tool_call:%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'RECON-DIRECTIVE (new)', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[RECON-DIRECTIVE%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'RECON_BUDGET_EXHAUSTED (new)', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[RECON_BUDGET_EXHAUSTED%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'HANDOFF written (new)', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%[HANDOFF: did=%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days')
UNION ALL SELECT 'TASK-CLOSED-BY-SESSION', COUNT(*) FROM work_sessions
  WHERE output_log LIKE '%TASK-CLOSED-BY-SESSION%' AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 days');
"
echo
echo "=== per hour since 20:00 (the deploy was 20:16:07Z)"
sqlite3 -readonly "$DB" "
SELECT substr(started_at,12,2) AS hour, COUNT(*) AS n,
       SUM(status='completed') AS done, SUM(status='failed') AS failed,
       SUM(output_log LIKE '%[STEP_BUDGET_EXHAUSTED:%') AS budget,
       SUM(output_log LIKE '%[RECON-DIRECTIVE%') AS recon,
       SUM(output_log LIKE '%[HANDOFF: did=%') AS handoff
FROM work_sessions WHERE date(started_at)=date('now') AND started_at >= '2026-10-14T20:00:00'
GROUP BY 1 ORDER BY 1;
"
echo
echo "=== sessions since the deploy, with what they recorded"
sqlite3 -readonly "$DB" "
SELECT id, status, steps_completed, total_steps,
       CASE WHEN output_log LIKE '%[RECON_BUDGET_EXHAUSTED%' THEN 'RECON_BLOCK'
            WHEN output_log LIKE '%[RECON-DIRECTIVE%' THEN 'RECON_DIRECTED'
            WHEN output_log LIKE '%[HANDOFF: did=%' THEN 'HANDOFF'
            WHEN output_log LIKE '%[STEP_BUDGET_EXHAUSTED:%' THEN 'STEP_BUDGET'
            ELSE '-' END AS what
FROM work_sessions WHERE started_at >= '2026-10-14T20:16:00' ORDER BY id;
"
