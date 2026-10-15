# 40 — COMPANY BASELINE (round 6, child R6-COMPANY)

**Host this was measured from:** `ZABZ-TECH` (Microsoft Windows 11 Pro, 10.0.26200, PowerShell 7.6.6).
**Authority:** `secratary-cloud`, reached over `ssh secratary-cloud` (bash on the far side).
**Database:** `/root/authority.db`, SQLite **3.46.1**, opened `-readonly` for every query below.
**Method:** every number on this page comes from a `sqlite3 -readonly` statement whose text is printed
with it, run against the authority over ssh. Nothing was written to the authority except
`/root/work/r6/40-company-baseline.md`. No deploys, no restarts, nothing under `/opt/company` touched.
**Time windows** are built with `strftime('%Y-%m-%dT%H:%M:%S','now',...)`, never
`datetime('now','-N days')` (lesson `L3801`). Every boundary value is printed beside the predicate.
**Deploy anchor:** round 4 deployed at `2026-10-14T20:16:07Z`; the anchor used everywhere below is
`2026-10-14T20:16:00` (`strftime` output: `2026-10-14T20:16:00`).

---

## 0. Where each thing actually lives (read this before the tables)

| what | table.column | written by |
|---|---|---|
| session outcome | `work_sessions.status` | `app/database.py::update_work_session` (line 9265); closed set `_WORK_SESSION_STATUSES = {completed, failed, paused, expired, cancelled}` (`app/autopilot.py:79`) |
| terminal marker | `work_sessions.output_log` | `update_work_session(..., output_append=...)` → `output_log = output_log || ?` |
| `failure_reason` | **does not exist** | `work_sessions` has no such column; a `pragma_table_info` sweep for `%reason%`/`%failure%`/`%error%` returned no `work_sessions` column |
| tick self-grade | `tick_telemetry.outcome`, `tick_telemetry.tick_quality` | tick loop |
| spend | `model_usage.estimated_cost_usd` | LLM gateway |
| attempt seed | `work_sessions.output_log` lines beginning `attempt-context:` | `app/services/attempt_context.py:628` (retry) / `:109` (no prior) |
| proof | `work_sessions.output_log` markers `[ARTEFACT:`, `[OUTBOUND:`, `[TASK-CLOSED-BY-SESSION:` | `app/autopilot.py:4110-4131`; read back by `_completion_evidence` (`app/autopilot.py:4133`) |

Command used for the "does `failure_reason` exist" claim:

```sql
SELECT m.name AS tbl, p.name AS col FROM sqlite_master m
  JOIN pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%reason%' OR p.name LIKE '%failure%' OR p.name LIKE '%error%')
 ORDER BY m.name;
```
→ no `work_sessions` row. (The statement errors out early on this database — `Runtime error: no such
module: vec0` — because a `memory_vectors` virtual table cannot be opened read-only by this sqlite3
build. The per-table `pragma_table_info` on `work_sessions` itself succeeds and is the evidence used:
`work_sessions` columns are `id, task_id, agent_id, title, status, steps_completed, total_steps,
progress_pct, context_json, output_log, started_at, updated_at, completed_at`. An empty result here is
a **refusal**, not health, and is reported as such.)

---

## 1. `work_sessions` by status — 24 h / 7 d / 30 d, and the same three windows before the deploy

**Read at `2026-10-15T14:15:06Z`.** Window boundaries as printed by the query:
`now=2026-10-15T14:15:06`, `now-1day=2026-10-14T14:15:06`, `now-7day=2026-10-08T14:15:06`,
`now-30day=2026-09-15T14:15:06`, `deploy_anchor=2026-10-14T20:16:00`, `deploy-1day=2026-10-13T20:16:00`,
`deploy-7day=2026-10-07T20:16:00`, `deploy-30day=2026-09-14T20:16:00`.

```sql
SELECT win, win_lo, win_hi, SUM(n) AS total,
       SUM(CASE WHEN status='completed' THEN n ELSE 0 END) AS completed,
       SUM(CASE WHEN status='failed'    THEN n ELSE 0 END) AS failed,
       SUM(CASE WHEN status='paused'    THEN n ELSE 0 END) AS paused,
       SUM(CASE WHEN status='expired'   THEN n ELSE 0 END) AS expired,
       ROUND(100.0*SUM(CASE WHEN status='completed' THEN n ELSE 0 END)/SUM(n),1) AS pct_completed
FROM (
  SELECT 'AFTER 24h' AS win, strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')  AS win_lo, strftime('%Y-%m-%dT%H:%M:%S','now') AS win_hi, status, COUNT(*) n FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')  AND started_at < strftime('%Y-%m-%dT%H:%M:%S','now') GROUP BY status
  UNION ALL SELECT 'AFTER 7d',  strftime('%Y-%m-%dT%H:%M:%S','now','-7 day'), strftime('%Y-%m-%dT%H:%M:%S','now'), status, COUNT(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day')  AND started_at < strftime('%Y-%m-%dT%H:%M:%S','now') GROUP BY status
  UNION ALL SELECT 'AFTER 30d', strftime('%Y-%m-%dT%H:%M:%S','now','-30 day'),strftime('%Y-%m-%dT%H:%M:%S','now'), status, COUNT(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-30 day') AND started_at < strftime('%Y-%m-%dT%H:%M:%S','now') GROUP BY status
  UNION ALL SELECT 'BEFORE 24h (pre-deploy)', strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-1 day'),  strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z'), status, COUNT(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-1 day')  AND started_at < strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z') GROUP BY status
  UNION ALL SELECT 'BEFORE 7d (pre-deploy)',  strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-7 day'),  strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z'), status, COUNT(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-7 day')  AND started_at < strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z') GROUP BY status
  UNION ALL SELECT 'BEFORE 30d (pre-deploy)', strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-30 day'), strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z'), status, COUNT(*) FROM work_sessions WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-30 day') AND started_at < strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z') GROUP BY status
) GROUP BY win ORDER BY win;
```

| window | win_lo | win_hi | sessions | completed | failed | paused | expired | %completed |
|---|---|---|---:|---:|---:|---:|---:|---:|
| AFTER 24h | 2026-10-14T14:15:06 | 2026-10-15T14:15:06 | 141 | 77 | 44 | 20 | 0 | **54.6** |
| AFTER 7d | 2026-10-08T14:15:06 | 2026-10-15T14:15:06 | 830 | 293 | 487 | 50 | 0 | 35.3 |
| AFTER 30d | 2026-09-15T14:15:06 | 2026-10-15T14:15:06 | 3327 | 1305 | 1869 | 153 | 0 | 39.2 |
| BEFORE 24h (pre-deploy) | 2026-10-13T20:16:00 | 2026-10-14T20:16:00 | 153 | 61 | 65 | 27 | 0 | 39.9 |
| BEFORE 7d (pre-deploy) | 2026-10-07T20:16:00 | 2026-10-14T20:16:00 | 872 | 261 | **578** | 33 | 0 | 29.9 |
| BEFORE 30d (pre-deploy) | 2026-09-14T20:16:00 | 2026-10-14T20:16:00 | 3382 | 1300 | 1939 | 143 | 0 | 38.4 |

**The `BEFORE 7d` row reproduces round 4's published `578 failed` exactly** (`HANDOFF-ROUND4.md` §4,
`PROGRAM.md` §2). Its `completed` is 261 here against round 4's 259 — a 2-session residue of a
different capture instant, reported rather than smoothed.

### 1b. The comparison that actually isolates the deploy — matched 18 h before vs 18 h after

`AFTER 7d` is *mostly pre-deploy* (only ~18 h of it is post-deploy), so it is not the before/after the
owner wants. The deploy is `2026-10-14T20:16:00Z`; this read is `2026-10-15T14:16:34Z`, i.e. 18.0 h.

```sql
WITH w AS (
  SELECT status, CASE WHEN started_at >= strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z') THEN 'POST' ELSE 'PRE' END AS phase
  FROM work_sessions
  WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','2026-10-14T20:16:00Z','-18 hours')
    AND started_at <  strftime('%Y-%m-%dT%H:%M:%S','now'))
SELECT phase, COUNT(*), SUM(status='completed'), SUM(status='failed'), SUM(status='paused'),
       ROUND(100.0*SUM(status='completed')/COUNT(*),1) FROM w GROUP BY phase;
```

**Read at `2026-10-15T14:16:34Z`.**

| phase | window | sessions | completed | failed | paused | %completed |
|---|---|---:|---:|---:|---:|---:|
| PRE (18 h before deploy) | 2026-10-14T02:16:00 → 20:16:00 | 117 | 45 | 47 | 25 | **38.5** |
| POST (18 h after deploy) | 2026-10-14T20:16:00 → now | 113 | 62 | 31 | 20 | **54.9** |

`n = 113` post-deploy sessions. `PROGRAM.md` §8's abandon condition asks for **at least 50 work
sessions after the deploy** — that threshold is now met, so the §8 test is decidable, not deferred.

---

## 2. Failure classes over 7 days

**Read at `2026-10-15T14:16:47Z`.** 7-day window lo = `2026-10-08T14:16:47`, hi = `now`.

**Which column, and does it write it.** `work_sessions` has **no `failure_reason` column** (§0). The
only per-failure classification this database holds is the terminal marker in
`work_sessions.output_log`, which is exactly the column `app/database.py::update_work_session` appends
to (`output_log = output_log || ?`) at the call sites `app/autopilot.py::_close_unfinished_work_session`
(:3882), `_write_session_handoff` (:3630), the `BUDGET-PAUSED` path (:5139), `_recon_directive` (:3420),
and `app/services/agent_worker.py:731` (`TOOL_LOOP_DEADLOCK`). Grouped on `output_log`, by literal
marker prefix taken from those writers — not by searching the database blindly.

```sql
WITH f AS (SELECT output_log FROM work_sessions WHERE status='failed'
             AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day')
             AND started_at <  strftime('%Y-%m-%dT%H:%M:%S','now')),
m(marker,literal) AS (VALUES
 ('STEP_BUDGET_EXHAUSTED','[STEP_BUDGET_EXHAUSTED'),('TOOL_LOOP_DEADLOCK','[TOOL_LOOP_DEADLOCK'),
 ('STALLED_REPEATING_OUTPUT','[STALLED_REPEATING_OUTPUT'),('STALLED_NO_TOOL_CALL','[STALLED_NO_TOOL_CALL'),
 ('RECON_BUDGET_EXHAUSTED','[RECON_BUDGET_EXHAUSTED'),('BLOCKED','[BLOCKED'),
 ('HARD-CEILING','[HARD-CEILING'),('TIMEOUT','[TIMEOUT'),('OUT-OF-TURNS','[OUT-OF-TURNS'),
 ('FORCE-EXPIRED','[FORCE-EXPIRED'),('ALREADY-CLOSED','[ALREADY-CLOSED'),('BUDGET-PAUSED','[BUDGET-PAUSED:'),
 ('WORK-DONE-INSUFFICIENT','[WORK-DONE-INSUFFICIENT'),('COMPLETION BLOCKED','[COMPLETION BLOCKED'),
 ('FORCE-COMPLETED','[FORCE-COMPLETED'),('AUTO-COMPLETED','[AUTO-COMPLETED'))
SELECT m.marker, COUNT(*) AS failed_sessions FROM m CROSS JOIN f
 WHERE instr(f.output_log, m.literal)>0 GROUP BY m.marker ORDER BY failed_sessions DESC;
```

**7 d failed sessions: 486. Sessions carrying at least one terminal marker: 486 of 486. Sessions with
no marker: 0.** (A union, not a partition — a session may carry several.)

| named class | marker | failed sessions (7 d) |
|---|---|---:|
| budget exhausted | `[STEP_BUDGET_EXHAUSTED` | **322** |
| tool loop deadlock | `[TOOL_LOOP_DEADLOCK` | **133** |
| stalled | `[STALLED_REPEATING_OUTPUT` | 52 |
| stalled | `[STALLED_NO_TOOL_CALL` | 20 |
| turn allowance (new, not in the brief) | `[OUT-OF-TURNS` | 29 |
| ceiling / timeout | `[TIMEOUT` | 2 |
| budget paused (not a failure class) | `[BUDGET-PAUSED:` | 1 |
| recon budget exhausted | `[RECON_BUDGET_EXHAUSTED` | 0 |
| blocked | `[BLOCKED` | 0 |
| hard ceiling | `[HARD-CEILING` | 0 |
| force expired | `[FORCE-EXPIRED` | 0 |
| already closed | `[ALREADY-CLOSED` | 0 |
| completion blocked | `[COMPLETION BLOCKED` | 0 |
| force/auto completed | `[FORCE-COMPLETED` / `[AUTO-COMPLETED` | 0 |

The zero rows are **measured zeros**, not missing columns: the literal was searched for in a column
that exists and is 486/486 populated with markers.

The exclusive "what did this session end as" view is only available where a `[HANDOFF:]` block exists,
and that block is post-deploy only (§3, §0). Of the 31 failed sessions in the last 7 d that have one:
`OUT-OF-TURNS` 29, `STALLED_NO_TOOL_CALL` 2. 455 of 486 failed sessions (93.6 %) have no handoff at all
and therefore no self-recorded terminal class — that is what pre-deploy means here.

---

## 3. Marker counts, 7 d and 24 h, and where each string lives

**Read at `2026-10-15T14:16:24Z`.** 7 d lo = `2026-10-08T14:16:24`, 24 h lo = `2026-10-14T14:16:24`.

Every one of the eight strings is written into **`work_sessions.output_log`**. Confirmed by finding the
emitting constant and the write path, not by a database-wide search:

| marker (literal counted) | constant / writer | lands in |
|---|---|---|
| `[HANDOFF: did=` | `RECON_HANDOFF_PREFIX`, `app/autopilot.py:74` | `work_sessions.output_log` via `_write_session_handoff` :3630 |
| `[STEP_BUDGET_EXHAUSTED` | `_close_unfinished_work_session(reason="step_budget_exhausted")` `app/autopilot.py:9068` | same, `:3882` |
| `[TOOL_LOOP_DEADLOCK` | `app/services/agent_worker.py:731` (`ToolLoopDeadlock.marker`) | `work_sessions.output_log` |
| `[STALLED_REPEATING_OUTPUT` | repetition guard, `app/autopilot.py` | same |
| `[RECON-DIRECTIVE:` | `RECON_DIRECTIVE_PREFIX`, `app/autopilot.py:73`; text built at `:3420` | same |
| `[RECON_BUDGET_EXHAUSTED` | `_recon_hard_block`, `app/autopilot.py:3493` | same |
| `[TASK-CLOSED-BY-SESSION:` | `app/autopilot.py:4128` | same |
| `[BUDGET-PAUSED:` | `app/autopilot.py:5139` | same |

```sql
WITH w AS (SELECT status, output_log,
    CASE WHEN started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-1 day') THEN '24h' ELSE '7d' END AS win
  FROM work_sessions
  WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day')
    AND started_at <  strftime('%Y-%m-%dT%H:%M:%S','now')),
m(marker, literal) AS (VALUES ('HANDOFF','[HANDOFF: did='),('STEP_BUDGET_EXHAUSTED','[STEP_BUDGET_EXHAUSTED'),
  ('TOOL_LOOP_DEADLOCK','[TOOL_LOOP_DEADLOCK'),('STALLED_REPEATING_OUTPUT','[STALLED_REPEATING_OUTPUT'),
  ('RECON-DIRECTIVE','[RECON-DIRECTIVE:'),('RECON_BUDGET_EXHAUSTED','[RECON_BUDGET_EXHAUSTED'),
  ('TASK-CLOSED-BY-SESSION','[TASK-CLOSED-BY-SESSION:'),('BUDGET-PAUSED','[BUDGET-PAUSED:'))
SELECT m.marker, SUM(CASE WHEN w.win='24h' THEN 1 ELSE 0 END) AS hits_24h,
       COUNT(*) AS hits_7d FROM m CROSS JOIN w WHERE instr(w.output_log, m.literal)>0
GROUP BY m.marker ORDER BY hits_7d DESC;
```

| marker | sessions 24 h | sessions 7 d | of the 7 d hits, status = failed |
|---|---:|---:|---:|
| `STEP_BUDGET_EXHAUSTED` | 30 | **342** | 323 |
| `TOOL_LOOP_DEADLOCK` | 71 | **176** | 133 |
| `HANDOFF` | **113** | **113** | 31 |
| `TASK-CLOSED-BY-SESSION` | 77 | 108 | 0 |
| `STALLED_REPEATING_OUTPUT` | 2 | 52 | 52 |
| `BUDGET-PAUSED` | 17 | 42 | 1 |
| `RECON-DIRECTIVE` | 21 | **21** | 7 |
| `RECON_BUDGET_EXHAUSTED` | 4 | 4 | 0 |

Three facts fall out of the 24 h column being equal to the 7 d column: **every `HANDOFF`, every
`RECON-DIRECTIVE` and every `RECON_BUDGET_EXHAUSTED` in the database was written after the deploy** —
those three strings have no pre-deploy history at all.

### 3b. Matched 18 h before vs 18 h after — markers

**Read at `2026-10-15T14:16:34Z`.**

| marker | PRE 18 h (02:16→20:16) | POST 18 h (20:16→now) |
|---|---:|---:|
| `STEP_BUDGET_EXHAUSTED` | 33 | **23** |
| `STALLED_REPEATING_OUTPUT` | 12 | **0** |
| `TOOL_LOOP_DEADLOCK` | 38 | **55** ← worse |
| `TASK-CLOSED-BY-SESSION` | 45 | **62** |
| `BUDGET-PAUSED` | 25 | 17 |
| `RECON-DIRECTIVE` | 0 | **21** |
| `RECON_BUDGET_EXHAUSTED` | 0 | **4** |
| `HANDOFF` | 0 | **113** |
| `OUT-OF-TURNS` | 0 | **95** |

The step-budget class fell 30 %; the repetition class went to zero; the tool-loop class **rose 45 %**
and is now the second-largest failure class post-deploy (55 sessions, against 23 step-budget). The
reconnaissance directive fired 21 times and the hard limit 4 times in 18 hours — against round 4's
"fired once, mechanism UNPROVEN in the field". That is now a field-exercised mechanism (n=21), and
round 4's caveat can be retired.

---

## 4. Spend, and cost per outcome

**Read at `2026-10-15T14:25:13Z`.** Cost column: `model_usage.estimated_cost_usd`.

**The numerator, stated exactly.** `model_usage` has no usable foreign key to a work session.
`model_usage.session_id` holds 32-hex gateway/prompt identifiers — `vsc-ext-...`, `84857708544e...` —
and **0 of the distinct values are all-digit**, so none can be a `work_sessions.id`. The correlated
check `EXISTS (SELECT 1 FROM work_sessions w WHERE CAST(w.id AS TEXT)=m.session_id)` was abandoned as
too slow on a 30 GB database after 5 minutes; the all-digit count answers the same question cheaply and
is the evidence used. **Therefore the numerator is total company spend across every agent and every
call in the window**, split by nothing. `work_sessions` audit rows cannot be costed individually with
this schema. Stated here rather than silently divided.

By agent over 7 d (`SELECT agent_id, ROUND(SUM(estimated_cost_usd),4), COUNT(*) FROM model_usage WHERE
created_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day') GROUP BY agent_id ORDER BY 2 DESC`):
`orchestrator $35.13`, `dept_engineering $32.73`, `dept_finance $15.25`, `dept_business_ops $8.83`,
`dept_scheduling $5.80` … — i.e. the work-session loop is a large part but not all of the numerator.

### 4a. Spend per day, 30 d

```sql
SELECT substr(created_at,1,10) AS day, ROUND(SUM(estimated_cost_usd),4) AS usd, COUNT(*) AS calls
FROM model_usage WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-30 day')
  AND created_at < strftime('%Y-%m-%dT%H:%M:%S','now') GROUP BY day ORDER BY day;
```

| day | USD | calls | | day | USD | calls |
|---|---:|---:|---|---|---:|---:|
| 2026-09-15 | 9.9003 | 1727 | | 2026-09-30 | 3.0001 | 1359 |
| 2026-09-16 | 11.7318 | 3019 | | 2026-10-01 | 2.2108 | 932 |
| 2026-09-17 | 10.3149 | 2914 | | 2026-10-02 | 12.4318 | 1800 |
| 2026-09-18 | 9.8649 | 2609 | | 2026-10-03 | 15.8373 | 1632 |
| 2026-09-19 | 1.2968 | 395 | | 2026-10-04 | 8.8210 | 1349 |
| 2026-09-20 | 9.8596 | 2675 | | 2026-10-05 | 24.7948 | 3057 |
| 2026-09-21 | 3.6172 | 1018 | | 2026-10-06 | 12.1129 | 1688 |
| 2026-09-22 | 6.0335 | 1981 | | 2026-10-07 | 17.5348 | 1908 |
| 2026-09-23 | 5.2268 | 1589 | | 2026-10-08 | 19.7343 | 2110 |
| 2026-09-24 | 5.0816 | 1565 | | 2026-10-09 | 16.7934 | 1762 |
| 2026-09-25 | 4.6392 | 1491 | | 2026-10-10 | 12.2591 | 1337 |
| 2026-09-26 | 0.3008 | 94 | | 2026-10-11 | 15.1986 | 1386 |
| 2026-09-27 | 3.6042 | 1051 | | 2026-10-12 | 13.4434 | 1193 |
| 2026-09-28 | 4.6091 | 1408 | | 2026-10-13 | 23.3229 | 2758 |
| 2026-09-29 | 2.7065 | 1182 | | 2026-10-14 | **34.5341** | 3228 |
| | | | | 2026-10-15 (partial) | 23.2333 | 2373 |

7 d total **$143.4894**; 30 d total **$344.0999**; 24 h **$33.9622**.

### 4b. Cost per completed session, and cost per session that closed with proof

**Definition of "closed with proof"** — not invented here: the live code's own definition,
`WorkSessionRunner._completion_evidence` (`app/autopilot.py:4133`), which is the strongest of
`[ARTEFACT:`, `[OUTBOUND:`, `[TASK-CLOSED-BY-SESSION:` found in the session's `output_log`. A session
counts as proven when its `output_log` contains at least one of those three. **Not** the handoff's
`proof=` field — see §4d, that field is unusable.

```sql
WITH win(name, lo, hi) AS (VALUES
 ('POST 18h (since deploy)','2026-10-14T20:16:00',strftime('%Y-%m-%dT%H:%M:%S','now')),
 ('PRE  18h (matching)','2026-10-14T02:16:00','2026-10-14T20:16:00'),
 ('last 24h',strftime('%Y-%m-%dT%H:%M:%S','now','-1 day'),strftime('%Y-%m-%dT%H:%M:%S','now')),
 ('last 7d',strftime('%Y-%m-%dT%H:%M:%S','now','-7 day'),strftime('%Y-%m-%dT%H:%M:%S','now')),
 ('last 30d',strftime('%Y-%m-%dT%H:%M:%S','now','-30 day'),strftime('%Y-%m-%dT%H:%M:%S','now')),
 ('since proof marker (10-14T02:07:49)','2026-10-14T02:07:49',strftime('%Y-%m-%dT%H:%M:%S','now'))),
sess AS (SELECT w.name, COUNT(*) n, SUM(ws.status='completed') c, SUM(ws.status='failed') f,
    SUM(ws.status='paused') p,
    SUM(CASE WHEN instr(ws.output_log,'[TASK-CLOSED-BY-SESSION:')>0 OR instr(ws.output_log,'[ARTEFACT:')>0
              OR instr(ws.output_log,'[OUTBOUND:')>0 THEN 1 ELSE 0 END) proven
  FROM win w JOIN work_sessions ws ON ws.started_at >= w.lo AND ws.started_at < w.hi GROUP BY w.name),
sp AS (SELECT w.name, ROUND(SUM(mu.estimated_cost_usd),4) usd
  FROM win w JOIN model_usage mu ON mu.created_at >= w.lo AND mu.created_at < w.hi GROUP BY w.name)
SELECT sess.name, sess.n, sess.c, sess.f, sess.p, ROUND(100.0*sess.c/sess.n,1), sess.proven, sp.usd,
       ROUND(sp.usd/sess.c,4), ROUND(sp.usd/sess.proven,4)
FROM sess JOIN sp ON sp.name=sess.name ORDER BY sess.name;
```

| window | sessions | completed | failed | paused | %comp | proven | spend USD | **USD / completed** | **USD / proven** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PRE 18 h (matching) | 117 | 45 | 47 | 25 | 38.5 | 45 | 28.1369 | **0.6253** | **0.6253** |
| POST 18 h (since deploy) | 115 | 62 | 31 | 22 | 53.9 | 62 | 25.8635 | **0.4172** | **0.4172** |
| last 24 h | 143 | 77 | 44 | 22 | 53.8 | 77 | 33.9622 | 0.4411 | 0.4411 |
| last 7 d | 829 | 292 | 485 | 52 | 35.2 | 108 | 143.4894 | 0.4914 | 1.3286 |
| last 30 d | 3325 | 1303 | 1869 | 153 | 39.2 | 108 | 344.0999 | 0.2641 | 3.1861 |
| since the proof marker existed | 233 | 108 | 78 | 47 | 46.4 | 108 | 54.4589 | 0.5042 | 0.5042 |

**Two things this table says that a glance will get wrong.**

1. In the two 18 h windows and the 24 h window, `completed` and `proven` are the *same number*. Every
   completed session in that period carries a proof marker, and no other status ever does
   (30 d: `failed` 0 of 1869 proven, `paused` 0 of 151 proven, `completed` 108 of 1303 proven).
   So **for the last day and a half the two metrics the brief asks for are one metric**, and the
   pre/post comparison is apples-to-apples.
2. Over 7 d and 30 d the proof denominator collapses to 108 while the numerator covers the whole
   window, which is why those two `USD / proven` cells are 2.7× and 7.6× the 24 h figure. That is not
   a cost blow-up: `[TASK-CLOSED-BY-SESSION:` **first appears at `2026-10-14T02:07:49Z`** and
   `[ARTEFACT:` never appears at all (0 rows, all-time). Divide by a marker that did not exist and you
   get an artefact. The honest 7 d / 30 d columns are `USD / completed`.

The deploy moved the pre/post pair from **$0.6253 per completed session (PRE) to $0.4172 (POST)** —
**−33 % per completed session on 8 % less spend** ($28.14 → $25.86) for **38 % more completions**
(45 → 62). That is the headline.

### 4c. A column round 4 promised, measured empty

`WS-MODEL` was deployed to "publish which model served". `model_usage.served_by` is **0 of 14 675 rows
populated in the last 7 days** (`SELECT COUNT(*), SUM(served_by IS NOT NULL AND served_by<>'') FROM
model_usage WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day')` → `14675 | 0`). A column
that exists, is empty, and is claimed as delivered is reported here as empty, not as a zero measurement.

### 4d. The handoff's `proof=` field is wrong in 100 % of cases

```sql
SELECT SUM(CASE WHEN instr(substr(hb,1,instr(hb,'| result=')),'| proof=none')>0 THEN 1 ELSE 0 END) AS proof_none,
       SUM(CASE WHEN instr(substr(hb,1,instr(hb,'| result=')),'| proof=none')=0 THEN 1 ELSE 0 END) AS proof_present
FROM (SELECT substr(output_log, instr(output_log,'[HANDOFF: did=')) AS hb
      FROM work_sessions WHERE instr(output_log,'[HANDOFF: did=')>0);
```
→ **`proof_none = 113`, `proof_present = 0`.** 62 of the 113 are sessions that *did* record
`[TASK-CLOSED-BY-SESSION:]` and still say `proof=none` — see §8(b).

---

## 5. Retries

**Read at `2026-10-15T14:18:12Z`.** 30 d lo = `2026-09-15T14:18:12`.

```sql
WITH t AS (SELECT task_id, COUNT(*) AS attempts,
    SUM(status='completed') AS completed_sessions,
    SUM(status='failed')    AS failed_sessions
  FROM work_sessions WHERE task_id IS NOT NULL
    AND started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-30 day')
    AND started_at <  strftime('%Y-%m-%dT%H:%M:%S','now')
  GROUP BY task_id)
SELECT (SELECT COUNT(*) FROM t) AS tasks_with_any_attempt,
       (SELECT COUNT(*) FROM t WHERE attempts>=2) AS tasks_2plus,
       (SELECT COUNT(*) FROM t WHERE attempts>=2 AND completed_sessions>0) AS with_a_completed_session,
       (SELECT COUNT(*) FROM t WHERE attempts>=2 AND failed_sessions=attempts) AS all_failed;
```

| measure | value |
|---|---:|
| tasks with any attempt, 30 d | 1823 |
| **tasks with 2 or more attempts, 30 d** | **784** |
| of those, with at least one `completed` session | **296** |
| of those, where every session `failed` | 470 |

By the task row's own status (`t JOIN tasks ta ON ta.id=t.task_id GROUP BY ta.status`):
`done 529`, `blocked 240`, `cancelled 8`, `open 4`, `completed 2`, `in_progress 1`.
So **529 of the 784 retried tasks are marked done while only 296 have a completed session** — 233 tasks
closed with no session that completed.

Attempts per task: `1→1039, 2→203, **3→554**, 4→10, 5→3, 6→5, 7→1, 8→2, 9→2, 12→2, 14→1, 55→1`.
The spike at exactly 3 is `_WORK_MAX_FAILED_ATTEMPTS = 3` (`app/autopilot.py:2977`) visible in the data.
**One task, `task_id 27303`, was attempted 55 times in 30 days.** Next: `27207` (14), `25288` (12),
`25289` (12), `26251` (9).

Round 4's published figure was "238 retried, 78 ever completed" (`PROGRAM.md` §2). I could not
reproduce 238 under any definition I tried, and I am reporting mine rather than the old one:

| definition | tasks | with a completed session |
|---|---:|---:|
| ≥2 sessions, 30 d to now | 784 | 296 |
| ≥2 sessions, 30 d ending 2026-10-14T19:26:58 (round 4's capture instant) | 804 | 297 |
| ≥2 **failed** sessions, 30 d ending 2026-10-14T19:26:58 | 590 | 92 |

**`PRIOR_ATTEMPT_STATUSES`** — `app/services/attempt_context.py:79`:

```python
#: Work-session states that count as "the previous attempt ended without completing".
PRIOR_ATTEMPT_STATUSES = ("failed", "expired")
```

**Which terminal states actually occur, and which are in that tuple.** `work_sessions.status` is
written through a closed set — `_WORK_SESSION_STATUSES = {"completed","failed","paused","expired",
"cancelled"}` (`app/autopilot.py:79`) — and `update_work_session` refuses anything else
(`app/database.py:9291`). The statuses that actually occur:

| status | 30 d | 7 d | all-time | in `PRIOR_ATTEMPT_STATUSES`? |
|---|---:|---:|---:|---|
| `failed` | 1869 | 486 | 3462 | **yes** |
| `completed` | 1303 | 293 | 28045 | no (by design — it completed) |
| `paused` | 153 | 50 | 47247 | **no** |
| `expired` | **0** | **0** | 60 | yes |
| `cancelled` | 0 | 0 | 0 | no |

`cancelled` is in the legal set and **has never occurred** (0 all-time) — stated as a measured zero, not
as a missing column. `expired` occurs 60 times all-time and **0 times in the last 30 days**, so half of
the tuple is currently dead and the tuple in practice means `failed` alone.

**Verdict on round 5's J3 — mechanism VERIFIED, magnitude REFUTED.**

- *Verified, and stronger than round 5 could show.* Round 5 argued from the code; the mechanism is now
  reproducible in the field. In the 18 h since the seed deployed:

  ```sql
  WITH o AS MATERIALIZED (SELECT id, task_id, status, started_at, output_log,
      LAG(status) OVER (PARTITION BY task_id ORDER BY id) AS prev_status
    FROM work_sessions WHERE task_id IS NOT NULL)
  SELECT COALESCE(prev_status,'(no earlier session)'), COUNT(*),
      SUM(instr(output_log,'attempt-context: retry')>0),
      SUM(instr(output_log,'attempt-context: no prior attempt')>0)
  FROM o WHERE started_at >= '2026-10-14T20:16:00' GROUP BY 1 ORDER BY 2 DESC;
  ```

  | previous session's status | new sessions | got a retry seed | got "no prior attempt" |
  |---|---:|---:|---:|
  | (no earlier session on this task) | 72 | 0 | 72 |
  | `failed` | 27 | **27** | 0 |
  | `paused` | 14 | 1 | **13** |

  **13 sessions whose immediately-preceding attempt ended `paused` opened with the literal line
  `attempt-context: no prior attempt on this task`** — the empty-context retry round 5 predicted, now
  with instances. (The single `paused`-to-`retry` case is the lookup finding an *older* `failed`
  session on the same task: `_previous_session` filters `status IN ('failed','expired')` and takes
  `ORDER BY id DESC LIMIT 1`, so it skips the paused one rather than stopping at it.)
  The seed itself is 18 h old — first line `2026-10-14T20:16:32Z`, 113 sessions total, all within the
  first 20 minutes of the deploy onward. There is no pre-deploy baseline for it, because
  `attempt_context.py` is the WS-MEMORY round-4 deliverable.

- *Refuted, on the words "the most common terminal state".* `paused` is not the most common terminal
  state in any recent window: over 30 d, `failed` is **12×** `paused` (1869 vs 153). `paused` is the
  most common only *all-time*, and that number is one month's legacy:

  ```sql
  SELECT substr(started_at,1,7) AS month, status, COUNT(*) FROM work_sessions
   WHERE started_at >= '2026-07-01' GROUP BY month, status ORDER BY month, COUNT(*) DESC;
  ```
  `2026-07 paused 36708` · `2026-08 completed 19996, failed 677` · `2026-09 failed 1594, completed 2559,
  paused 57` · `2026-10 failed 1118, completed 535, paused 106`.
  **36 708 of the 47 247 all-time `paused` rows are from July 2026 alone.** The claim is a July artefact,
  and a round that quotes it as the live state will misdirect the next fix.

- *A third defect round 5 did not name, and it is bigger than the one it did.* The `paused` asymmetry is
  not only in the reader; it is in the **writer's own bookkeeping**, and it is checkable:

  ```sql
  SELECT status, SUM(completed_at IS NULL OR completed_at=''), COUNT(*) FROM work_sessions
   WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-30 day') GROUP BY status;
  ```
  → `completed 0/1303`, `failed 0/1869`, **`paused 153/153`**. `update_work_session` sets `completed_at`
  only for `status IN ('completed','failed','cancelled')` (`app/database.py:9298`) — so **every `paused`
  session is a terminal session with no completion timestamp**, while `app/autopilot.py:79` counts
  `paused` as terminal. And `count_recent_failed_work_sessions` (`app/database.py:9750`) counts
  `status = 'failed'` only, so a read-storm task closed `paused` does not even advance the 3-strike
  give-up ceiling. Round 5 spotted the second half of this; the missing `completed_at` is a separate,
  independently measurable symptom of the same one-line omission.

  What closes a `paused` session in the last 30 d: `[BUDGET-PAUSED` **117**, `[RECON_BUDGET_EXHAUSTED`
  **4**, neither **32**. So the round-5 example path (`recon_budget_exhausted`) is 4 sessions in 30 days;
  the volume is the budget-cap path, which is not a loop failure at all.

**Answer to the brief's question.** The terminal states that actually occur are `failed` (1869),
`completed` (1303), `paused` (153) over 30 d, and 0 `expired`. Of those only `failed` is in
`PRIOR_ATTEMPT_STATUSES` in practice. `paused` is genuinely absent and genuinely produced — but it is
**7.6 % of the 30-day non-completing terminal states, not the most common one**, and the 3-strike
give-up counter has the same blind spot.

---

## 6. Tick self-grading versus outcome

**Read at `2026-10-15T14:23:55Z`.** `tick_telemetry.outcome` / `tick_telemetry.tick_quality`.

```sql
SELECT '7d' AS win, SUM(outcome='complete'), SUM(tick_quality='productive'), COUNT(*)
FROM tick_telemetry WHERE started_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-7 day')
  AND started_at < strftime('%Y-%m-%dT%H:%M:%S','now');
```

| window | `outcome='complete'` | `tick_quality='productive'` | ticks | failed work sessions, same window |
|---|---:|---:|---:|---:|
| 7 d | **823** | **821** | 944 | 485 |
| 24 h | 85 | 84 | 105 | 44 |
| 30 d | 3662 | 3663 | 4326 | 1869 |
| PRE 18 h | 77 | 78 | 92 | 47 |
| POST 18 h | 64 | 63 | 81 | 31 |

**The shape is unchanged.** Round 4 measured 901 `complete` / 904 `productive` against 578 failed work
sessions; today it is 823 / 821 against 485. The tick still grades itself successful in ~87 % of ticks
(823+821 of 944 — and the two axes agree with each other in 817 of 944 cases: `outcome=complete,
tick_quality=productive`) while **62 % of the work sessions in the same 7 days `failed`**. A tick is one
step; a session is the work. The tick's own grade has never been a statement about a session's outcome
and is still the wrong instrument for the owner's question.

All-time distribution, for completeness: `outcome` `complete 17890 / escalate 7587 / error 7019 /
suspended 1617 / skip 276`; `tick_quality` `productive 18026 / empty 14038 / reactive 1320 /
unknown 730 / failed 285`.

---

## 7. `bash /root/work/round4-loop-baseline.sh after` — verbatim

The script exists at `/root/work/round4-loop-baseline.sh` (3 167 bytes, mtime `2026-10-14 23:20`).
Run over ssh as `ssh secratary-cloud 'bash /root/work/round4-loop-baseline.sh after'`. Output below is
**complete and verbatim** — all 142 lines, nothing elided. It was run twice about ten minutes apart;
this is the second run, captured at `2026-10-15T14:2xZ`.

```
=== the failure markers, last 24h, and the completion mechanism (day-grouped)
STEP_BUDGET_EXHAUSTED|31
TOOL_LOOP_DEADLOCK|71
STALLED_REPEATING_OUTPUT|2
stalled_no_tool_call|22
RECON-DIRECTIVE (new)|21
RECON_BUDGET_EXHAUSTED (new)|4
HANDOFF written (new)|115
TASK-CLOSED-BY-SESSION|77

=== per hour since 20:00 (the deploy was 20:16:07Z)
00|2|1|1|1|1|2
02|4|3|1|3|2|4
03|7|4|3|0|2|7
04|13|12|1|1|1|13
05|6|6|0|1|0|6
06|4|1|2|1|1|4
07|6|5|1|1|0|6
08|10|6|4|2|0|10
09|7|4|3|2|3|7
10|9|3|6|2|0|9
11|10|8|2|2|3|10
12|6|1|3|4|4|6
13|8|2|1|3|3|8
14|2|0|0|1|0|2

=== sessions since the deploy, with what they recorded
78754|paused|4|20|HANDOFF
78755|paused|0|20|HANDOFF
78756|paused|0|20|HANDOFF
78757|paused|0|20|HANDOFF
78758|completed|3|20|HANDOFF
78759|paused|0|20|HANDOFF
78760|paused|0|20|HANDOFF
78761|completed|8|20|HANDOFF
78762|paused|0|20|HANDOFF
78763|paused|0|20|HANDOFF
78764|completed|3|20|HANDOFF
78765|completed|10|20|RECON_DIRECTED
78766|completed|5|20|HANDOFF
78767|paused|0|20|HANDOFF
78768|paused|0|20|HANDOFF
78769|completed|3|20|HANDOFF
78770|paused|0|20|HANDOFF
78771|paused|0|20|HANDOFF
78772|failed|2|20|HANDOFF
78773|failed|1|20|HANDOFF
78774|failed|2|20|HANDOFF
78775|completed|3|20|HANDOFF
78776|failed|25|29|RECON_DIRECTED
78777|completed|13|20|RECON_DIRECTED
78778|failed|20|23|RECON_DIRECTED
78779|completed|9|20|HANDOFF
78780|completed|4|20|HANDOFF
78781|completed|13|20|RECON_DIRECTED
78782|completed|16|20|RECON_DIRECTED
78783|completed|4|20|HANDOFF
78784|completed|12|20|HANDOFF
78785|failed|1|20|HANDOFF
78786|failed|4|20|HANDOFF
78787|failed|16|20|HANDOFF
78788|completed|6|20|HANDOFF
78789|completed|10|20|HANDOFF
78790|completed|3|20|HANDOFF
78791|completed|3|20|HANDOFF
78792|completed|8|20|HANDOFF
78793|completed|3|20|HANDOFF
78794|completed|3|20|HANDOFF
78795|completed|3|20|HANDOFF
78796|completed|7|20|RECON_DIRECTED
78797|completed|3|20|HANDOFF
78798|completed|4|20|HANDOFF
78799|completed|3|20|HANDOFF
78800|failed|20|23|HANDOFF
78801|completed|5|20|HANDOFF
78802|completed|4|20|HANDOFF
78803|completed|10|20|HANDOFF
78804|completed|3|20|HANDOFF
78805|completed|8|20|HANDOFF
78806|completed|3|20|HANDOFF
78807|paused|10|20|RECON_BLOCK
78808|completed|3|20|HANDOFF
78809|failed|5|20|HANDOFF
78810|failed|20|23|HANDOFF
78811|completed|10|20|HANDOFF
78812|completed|8|20|HANDOFF
78813|completed|3|20|HANDOFF
78814|completed|15|20|HANDOFF
78815|failed|9|20|HANDOFF
78816|completed|7|20|HANDOFF
78817|failed|14|20|HANDOFF
78818|failed|20|23|HANDOFF
78819|completed|6|20|HANDOFF
78820|completed|6|20|HANDOFF
78821|completed|17|20|HANDOFF
78822|completed|3|20|HANDOFF
78823|completed|10|20|HANDOFF
78824|failed|2|20|HANDOFF
78825|failed|4|20|HANDOFF
78826|completed|13|20|HANDOFF
78827|completed|17|20|HANDOFF
78828|completed|7|20|RECON_DIRECTED
78829|failed|20|23|RECON_DIRECTED
78830|completed|18|20|HANDOFF
78831|completed|7|20|HANDOFF
78832|failed|11|20|RECON_DIRECTED
78833|failed|6|20|HANDOFF
78834|completed|3|20|HANDOFF
78835|completed|18|20|HANDOFF
78836|completed|3|20|HANDOFF
78837|failed|5|20|HANDOFF
78838|failed|20|20|HANDOFF
78839|failed|3|20|HANDOFF
78840|failed|3|20|HANDOFF
78841|failed|11|20|HANDOFF
78842|failed|9|20|HANDOFF
78843|completed|3|20|HANDOFF
78844|completed|3|20|HANDOFF
78845|completed|15|20|RECON_DIRECTED
78846|completed|8|20|HANDOFF
78847|completed|3|20|HANDOFF
78848|failed|20|20|HANDOFF
78849|completed|22|23|HANDOFF
78850|completed|17|20|HANDOFF
78851|failed|10|20|RECON_DIRECTED
78852|completed|7|20|RECON_DIRECTED
78853|failed|20|20|RECON_DIRECTED
78854|paused|20|20|RECON_BLOCK
78855|paused|18|20|RECON_BLOCK
78856|completed|12|20|RECON_DIRECTED
78857|failed|18|20|HANDOFF
78858|failed|20|23|HANDOFF
78859|completed|16|20|RECON_DIRECTED
78860|paused|14|20|RECON_BLOCK
78861|failed|27|29|RECON_DIRECTED
78862|paused|0|20|HANDOFF
78863|paused|0|20|HANDOFF
78864|completed|3|20|HANDOFF
78865|paused|0|20|HANDOFF
78866|paused|0|20|HANDOFF
78867|paused|0|20|HANDOFF
78868|paused|0|20|HANDOFF
```

**Cross-check against §3, and the discrepancies — all of them drift, not disagreement.** The script
takes no upper bound on `started_at`; §3 filters `< now`. The two runs were ~10 minutes apart and the
company kept working through them, so the same script returned
`STEP_BUDGET_EXHAUSTED 30 → 31`, `HANDOFF 114 → 115`, `hour 14 sessions 1 → 2` between run one and run
two. §3, read at `14:16:24Z`, sits between them and reports 30 / 113. The script's
`stalled_no_tool_call|22` uses a **lowercase** prefix (`'%[stalled_no_tool_call:%'`) and so does not
match the uppercase `STALLED_NO_TOOL_CALL` literal counted in §3 — two distinct strings, both live,
which is why §3's 7 d figure for that class is 20 and not 22. Every other marker count agrees exactly.

---

## 8. What contradicts the brief, the round-4 and the round-5 documents

These are the findings the brief asked for and they are the most valuable part of this page.

**(a) `docs/dsh-evolution-v6/PROGRAM.md` does not exist. Neither does `docs/dsh-evolution-v4/`.**
The brief's "Read first" list sends the reader to four documents; **one of the four cannot be read at
all and the other three are not on disk**. Evidence: `ls /opt/company/docs/dsh-evolution-v6/` and
`/opt/company/docs/dsh-evolution-v4/` → `No such file or directory`; `find / -maxdepth 6 -type d -name
"dsh-evolution-v*"` on the authority → nothing; `git -C /root/code/harness-config log --all --oneline --
"docs/dsh-evolution-v6/*"` → **empty, no commit on any branch has ever contained that path**. The v4
documents exist **only in git history** of `/root/code/harness-config`: `PROGRAM.md` added by
`b83b1f7c`, `HANDOFF-ROUND4.md` by `242bd5be`, `HANDOFF-ROUND5.md` by `34ee40f7`. I read them with
`git show <sha>:<path>` — no checkout, no branch change, nothing written. A working copy of round 4's
handoff also sits at `/root/work/HANDOFF-ROUND4.md` (19 211 bytes). Every §-reference in this document
resolves to one of those. **A round that cites a v6 program cannot be executed against a v6 program
that does not exist** — either the v6 program was never written or it lives somewhere this brief does
not name, and the next round should name a path that resolves.

**(b) The `[HANDOFF:]` block is a record of a mid-session tick, not of the session's end — and its
`proof=` and `result=` fields are therefore wrong.** This is the largest single defect found.
Round 4's claim "every session now leaves a handoff (was 1 in 24 h)" is **true as a count (113/113)** and
**misleading as a record**:

- The handoff is written by the **`OUT-OF-TURNS`** path with `terminal_status="active"`
  (`app/autopilot.py:6092-6106`) — the exit that deliberately does **not** set a terminal status, because
  "the session is still open". `_session_handoff_block` refuses a second handoff
  (`if RECON_HANDOFF_PREFIX in text: return ""`), so the session's *real* ending never gets one.
- Measured, `SELECT status, <marker quoted in the handoff's left= field>, COUNT(*)` over the 113
  handoffs: **95 of 113 handoffs quote `[OUT-OF-TURNS: … the session is still open]` as `left=`**, and
  **61 of those 95 ended `completed`**. Another 5 `paused` and 29 `failed` also carry the
  "still open" marker. Only 17 sessions have a handoff that names a marker resembling their own ending.
- `proof=none` in **113 of 113** handoffs and `result=partial` throughout — including the **62** of those
  sessions that *did* record `[TASK-CLOSED-BY-SESSION:]`. The handoff is built from
  `accumulated_output` at the moment the tick runs out, before the closing action is appended.
- The handoff is not the last thing in the log either. Measuring `length(output_log) -
  instr(output_log,'[HANDOFF: did=')` — the block is bounded at ~1 200 chars, so anything above that
  proves later appends: **87 of 113 sessions have more than 1 200 characters of their own log after the
  handoff (52 between 1 201 and 5 000, 35 over 5 000); 0 sessions end at the handoff with a 0-length
  tail.** (The 27 sessions in the ≤1 200-char bucket are ambiguous and are not claimed either way — the
  block's own nested `]` from the `left=` marker makes an exact "chars after the block" figure
  unreliable, so the bucket is stated as a bound, not an equality.)

  Consequence for the round-4/5 story: a resumer or a reader that trusts the handoff is told
  `proof=none, result=partial` about 62 sessions that closed a task with evidence. **Fix the moment, and
  the field becomes trustworthy; the mechanism is right and the placement is wrong.**

**(c) `[OUT-OF-TURNS]` is the dominant post-deploy marker and is in none of the brief's eight.** 95 of
113 post-deploy sessions carry it; 29 of the 31 post-deploy `failed` sessions have it as their only
self-recorded terminal marker; and in the 7-day failed population it is the fourth-largest class (29).
The brief's list of markers to count omits it, so a reader following the brief would conclude the
post-deploy failure population is mostly `STEP_BUDGET_EXHAUSTED` (23) when in fact the modal *last*
marker is `OUT-OF-TURNS`.

**(d) `[ARTEFACT:]` has never been written.** `instr(output_log,'[ARTEFACT:')` → **0 rows, all-time**,
`MIN(started_at)` → NULL. One of the three proof markers `_completion_evidence` looks for is dead code
in production. `[OUTBOUND:]` appears exactly **once** (`2026-10-14T18:30:44Z`). So "closes with proof"
today means "the session closed a task", full stop, and the other two-thirds of the proof definition
contribute nothing.

**(e) `TOOL_LOOP_DEADLOCK` got worse after the deploy, not better.** 38 sessions in the 18 h before →
**55** in the 18 h after (+45 %). It is now the second-largest failure class post-deploy while
`STEP_BUDGET_EXHAUSTED` fell 33 → 23. Round 4's loop work moved the step-budget class and left, or
created, this one. §3b's table is the evidence.

**(f) Round 4's "one in sixteen" verdict on the reconnaissance directive is now superseded.**
`RECON-DIRECTIVE` **21** and `RECON_BUDGET_EXHAUSTED` **4** in 18 h, against 1 and 0 at round 4's
capture. The mechanism round 4 said was "UNPROVEN in the field" has now fired 21 times and reached its
hard limit 4 times. The directive is exercised; whether it *converts* is still open, but it is no longer
untested.

**(g) Round 4's `1 in 24 h` handoff baseline and the `HANDOFF` count agree; round 4's `578 failed`
for 7 d agrees exactly.** Where a round-4 number *is* reproducible it is reproduced here, and the two
round-4 numbers that are not reproducible are said so (§5's 238/78 retry figure, §1's 259 vs 261
completed) rather than adjusted.

**(h) `PRIOR_ATTEMPT_STATUSES` half-dead.** `expired` has not occurred in 30 days (0 rows), so the tuple
is in practice `("failed",)`. That is not a counter-argument to adding `paused`; it is context for
sizing the fix (§5).

**(i) `model_usage.served_by` is empty (0/14 675, 7 d) despite round 4 listing "publishes which model
served" as delivered.** §4c.

**(j) `work_sessions.started_at` contains at least one row that is not a timestamp.** `SELECT MIN(started_at)
FROM work_sessions` returns `0`. It never matches a window predicate, so it does not corrupt any number
on this page, but it is a latent trap for anyone who writes `MIN(started_at)` or `ORDER BY started_at`
without a format guard.

---

## APPENDIX — OPINION, NOT MEASUREMENT

Everything above is a command and its output. **Everything below is analysis.** It is labelled
separately on purpose: no line in this appendix is a measurement, and none should be quoted as one.
The three changes are ranked by expected effect on `completed/(completed+failed)` and on cost per proven
outcome, and **nothing has been implemented**.

### 1. Give the handoff a second chance — write it at the real terminal write, or make it amendable

- **Evidence row:** §8(b). 113 handoffs, `proof=none` 113/113, `result=partial` 113/113; 95 quote
  `[OUT-OF-TURNS: … the session is still open]`; 61 of those sessions ended `completed`; 87 of 113 have
  >1 200 chars of log after the block. And §2: 455 of 486 seven-day failures have no handoff at all.
- **Implementation sketch (one line):** in `_session_handoff_block`, allow a *replace* rather than a
  refuse — on a terminal write, if a handoff already exists, rewrite its `proof=`/`result=`/`left=`
  fields from the final `accumulated_output` (the fields are already derived from the trace; only the
  moment is wrong), and stop emitting a handoff from the `OUT-OF-TURNS` path at all, since that path
  explicitly does not terminate the session.
- **Measurement that would show it worked:** `SELECT SUM(proof_none), COUNT(*) FROM <handoffs>` → the
  `113/0` split moves toward `proof_present > 0`; and `SELECT status, <left marker>, COUNT(*)` stops
  pairing `completed` with `[OUT-OF-TURNS … still open]` (today: 61 pairs).

### 2. Count `paused` everywhere `failed` is counted, and stamp `completed_at` on it

- **Evidence row:** §5. `paused 153/153` with `completed_at IS NULL` against `completed 0/1303` and
  `failed 0/1869`; `count_recent_failed_work_sessions` counts `status='failed'` only
  (`app/database.py:9750`); `_WORK_SESSION_TERMINAL_STATUSES` already includes `paused`
  (`app/autopilot.py:79`); 13 field instances of a `paused` attempt retried with
  `attempt-context: no prior attempt on this task`.
- **Implementation sketch (one line):** add `"paused"` to `PRIOR_ATTEMPT_STATUSES`
  (`app/services/attempt_context.py:79`), add it to `update_work_session`'s `completed_at` branch
  (`app/database.py:9298`), and change the give-up counter's `status = 'failed'` to
  `status IN ('failed','paused')` — one tuple, one branch, one predicate, three call sites.
- **Measurement that would show it worked:** the §5 table's `paused`-row cell moves from
  `14 | 1 | 13` to `seed_retry`; `SELECT status, SUM(completed_at IS NULL), COUNT(*) … GROUP BY status`
  returns `paused 0/…`; and the `3-attempt` spike (554 tasks) should stop growing, because the tasks
  that currently loop are the ones whose attempts are invisible to the ceiling.
- **Honest sizing:** this fixes a mechanism worth **153 sessions / 30 d (7.6 % of non-completing
  terminals)**, not the majority. It is ranked second because it is one line and its cost is zero, not
  because it is large. The `task_id 27303` / 55-attempts row is the reason to think the ceiling blind
  spot matters more than the 153 suggests.

### 3. Treat `TOOL_LOOP_DEADLOCK` as the live regression it now is

- **Evidence row:** §3b. 38 sessions (18 h pre) → **55** (18 h post), +45 %, while `STEP_BUDGET_EXHAUSTED`
  fell 33 → 23 and `STALLED_REPEATING_OUTPUT` fell 12 → 0. Over 7 d it is the second-largest failure
  class (133 of 486) and it is the marker that consumes a *successful* session's turns: the sample at
  §3 shows a session spending 20/23 steps and 49 tool calls in seven distinct tools, four of them
  read-only, before the deadlock fires.
- **Implementation sketch (one line):** the deadlock guard says `'repo_read_file' failed identically
  3/3 times` (`failure_class=file not found`) — so route that class to *stop calling the tool* and
  report the missing path as the answer, instead of re-issuing it under a different tool name; the
  counter is per-tool and the session changed tools rather than changed behaviour.
- **Measurement that would show it worked:** §3b's `TOOL_LOOP_DEADLOCK` column in the matched 18 h
  window falls below its pre-deploy 38, and `completed/(completed+failed)` in the same matched window
  rises above the current `62/93 = 66.7 %` (PRE was `45/92 = 48.9 %`).
- **Why it ranks third:** the other two are one-line corrections to an instrument that is currently
  *lying* (§1, §2). This one is a behaviour change with an unknown blast radius, and the round that
  changes loop behaviour without first fixing the record of it produces another unreadable round.

### What I would NOT do next

The tick self-grade (§6) is not worth a fix. It has been 87 % "complete/productive" against a 62 %
session failure rate for three rounds and every round has re-measured it; it is an instrument for a
different question. Deleting it, or renaming its field to say "tick", would be cheaper and more honest
than tuning it.

---

## 9. Scope, and what was not verified

- **Read-only.** Nothing written to the authority except `/root/work/r6/40-company-baseline.md`. No
  deploy, no restart, no `systemctl` verb, no write to `/opt/company`, no write anywhere else under
  `/root`. No `git` state changed on the authority: `git show` and `git log --all` only; no checkout,
  no branch, no reset, no clean, no push, no `main`, no `git add -A`.
- **Single-machine provenance.** All numbers come from `/root/authority.db` on `secratary-cloud`. This
  child ran on `ZABZ-TECH` and reached the authority only over ssh. Nothing here was verified against
  the second or third machine in the fleet.
- **Point-in-time.** Every table carries the UTC instant it was read; the windows differ by up to
  ten minutes across sections (14:15:06 → 14:25:13), which is why §1's `AFTER 30d completed` is 1305 and
  §4b's is 1303. Both are printed; neither is corrected to the other.
- **Not verification-tested.** I read `attempt_context.py`, `autopilot.py`, `agent_worker.py` and
  `database.py` for the write sites cited above; I did not run the company's test suite, did not import
  its modules, and did not execute any of its code paths. Every "written by" claim is a source citation,
  not an executed proof.
- **`model_usage` → `work_sessions` attribution is impossible with this schema** (§4). The cost figures
  are company-wide. A per-session cost requires a schema change or gateway tracing, and I have no such
  measurement.
- **The `vec0` refusal.** The whole-database `pragma_table_info` sweep errors on `memory_vectors`
  read-only; the `work_sessions` half of that sweep is the evidence I used and it succeeds. Stated so
  nobody repeats the query and reads the error as a null result.
- **Not measured, deliberately:** which department or task *shape* fails (round 4's `classify-work-sessions.py`
  exists and I did not run it — the brief did not ask), the second and third machines, and the contents
  of `/opt/company/app/services/attempt_context.py` beyond the two regions cited.
- **Not implemented:** the three changes in the appendix. Nothing in this document was deployed.
