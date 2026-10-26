#!/usr/bin/env python3
"""Never defer an agent that has real work waiting.

TWO DELIBERATE POLICIES THAT CONTRADICT EACH OTHER
--------------------------------------------------
1. `SCHEDULE_MODE=cheap` / `SCHEDULE_PRIORITY_MODE=ladder` defer department agents
   out of DeepSeek's peak bands (01:00-04:00 and 06:00-10:00 UTC Mon-Fri) to halve
   token cost. Longest single wait: 180 minutes.
2. `lifecycle_sweep.STUCK_WORK_ORDER_PROGRESS_WINDOW_MINUTES = 90` releases a goal
   that has made no progress after 90 minutes.

So a work order created inside a peak block is killed at 90 minutes — before its
department is permitted to run at all. MEASURED: the two `dept_security` goals were
created 2026-10-25T00:54:54Z and released 2026-10-25T02:26:29Z, 91.6 minutes later,
with all 9 steps `attempts=0, claimed_by=null, started_at=null`. They were never
attempted. That is not a department failing; it is the scheduler deleting work
before it was allowed to start.

WHY THIS GUARD, AND NOT A LONGER SWEEP WINDOW
---------------------------------------------
Raising the sweep window would let genuinely stuck goals live longer and jam the
queue. The narrower true statement is: **deferral is for idle reflection.** An agent
holding claimable work is not idle, and waiting is not free — a work order that is
killed and re-created every cycle pays goal-creation tokens forever and delivers
nothing, which is strictly more expensive than running it at the peak rate once.

So: if the agent has a pending, unclaimed step on an active goal, it runs now,
whatever the cost policy would have preferred. On any failure of the check the agent
is kept — never starve work to save a query.
"""
import io
import sys

PATH = "app/workforce.py"
src = io.open(PATH, encoding="utf-8").read()

if "_has_claimable_work" in src:
    print("ALREADY PATCHED - no change")
    sys.exit(0)

anchor = """        for aid, depth in active_agents:
            if _ladder_decide is not None:"""
if anchor not in src:
    print("FATAL: decision-loop anchor not found")
    sys.exit(10)
if src.count(anchor) != 1:
    print("FATAL: anchor not unique (%d)" % src.count(anchor))
    sys.exit(11)

replacement = """        for aid, depth in active_agents:
            # ── A deferral must never outlive the work it defers ──
            # The cheap-window policy can defer a department for up to 180
            # minutes; lifecycle_sweep releases a no-progress goal after 90.
            # A work order created during peak was therefore killed before its
            # department was allowed to run (measured: both dept_security goals,
            # created 2026-10-25T00:54:54Z, released 02:26:29Z, 9/9 steps
            # attempts=0). Deferral is for idle reflection; an agent holding
            # claimable work runs now.
            if _has_claimable_work(aid):
                kept.append((aid, depth))
                continue
            if _ladder_decide is not None:"""

src = src.replace(anchor, replacement, 1)

# Insert the helper immediately before _filter_by_schedule.
helper = '''def _has_claimable_work(agent_id: str) -> bool:
    """True when this agent has a pending, unclaimed step on an active goal.

    Used by the schedule policy so a cost deferral can never outlive the work it
    is deferring. Fails OPEN (returns True) on any error: starving real work to
    save one query is the wrong trade.
    """
    try:
        from app.database import _get_conn

        conn = _get_conn(_db())
        row = conn.execute(
            """
            SELECT 1
            FROM goal_steps gs
            JOIN goal_plans gp ON gs.goal_id = gp.id
            WHERE gp.assigned_agent = ?
              AND gp.status = 'active'
              AND gs.status = 'pending'
              AND gs.claimed_by IS NULL
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 - never starve work over a query
        return True


'''

marker = "def _filter_by_schedule("
if marker not in src:
    print("FATAL: _filter_by_schedule not found")
    sys.exit(12)
src = src.replace(marker, helper + marker, 1)

io.open(PATH + ".new", "w", encoding="utf-8", newline="\n").write(src)
print("wrote %s.new" % PATH)
