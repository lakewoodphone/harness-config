# 55 — The company, redesigned

**2026-10-14.** The design that the build in `60-company-changes.md` is held to. Every claim below
traces to a measurement in `40-company-map.md` or `50-company-failures.md`, or to a command recorded
in one of them.

---

## 1. What is actually wrong, in one paragraph

The company is not idle and it is not cheap — it runs **~120 work sessions a day and 165 ticks a day**,
and it spends **119.10 USD of model money in a week**. It succeeds at roughly **29%** of the work it
attempts, and that 29% is a lie: **not one of the 236 "completed" work sessions in the last seven days
used the completion path**; every one of them fired because the task row happened to be *already
closed*. So there is no evidence, in a week, of a single work session finishing the work it was given.
Meanwhile the company is **confident**: `tick_telemetry` grades 89% of ticks `complete` because
`tick_quality` counts *one meaningful tool call* as a productive tick. The company is therefore
optimised to look busy and is structurally unable to tell whether it did anything.

The failures are **control flow, not intelligence** — which is the good news, because control flow is
fixable this week.

---

## 2. The eight defects, each with its evidence

### D1 — The work budget is fixed at 5 steps, and progress means "mutation", so investigation can never finish

`_WORK_MAX_STEPS = 5` (`autopilot.py:2779`). The only extension path is
`_maybe_extend_work_session_budget` (`:3030`) gated on `_work_session_is_progressing` (`:3184`),
which requires **a non-read-only action in the last three steps**. Measured consequence: **379 of 580
failures (65.3%)** are `STEP_BUDGET_EXHAUSTED`; the median failed session made **10 tool calls** and
the dominant tools are `repo_search` (157 sessions), `list_tasks` (132), `memory_search` (108),
`repo_list_dir` (104) — reconnaissance, which by this rule is *not progress*. The canonical example is
session `77803`: "reached 5/5 work steps … 10 tool call(s) over **1 distinct tool**: `repo_search`".

For an estate whose measured work is **56% investigation and repair**, a budget that punishes
investigation is aimed exactly backwards.

### D2 — Three identical tool failures abort the session, and the marker misreports it

`_note_tool_failure` (`agent_worker.py:882-912`), limits at `:734-775` (3 strikes / 300 s). **156
failures (26.9%)** are `TOOL_LOOP_DEADLOCK`. Every one of the 156 carries the detail **"failed
identically 0/3 times"** — the counter is read from the wrong field (`autopilot.py:4202-4214` vs
`tool_loop_snapshot` `agent_worker.py:950-961`) — so the *report of why it died is itself wrong*.
Worse, the strike rule cannot tell a **dead tool** from a **bad argument**: `gmail_read` with a
malformed `message_id` and `repo_search` with no checkout both burn strikes identically.

### D3 — Two empty turns end the session

`ledger.charge()` returns `EMPTY_TURN` on a turn with zero actions (`work_step_ledger.py:79-81`);
after **two in a row** the loop breaks and closes the session failed (`autopilot.py:4477-4488`). **38
sessions** died this way. The prompt itself documents a JSON envelope for tool calls
(`autopilot.py:4865-4867`) — the loop never falls back to it. One provider formatting hiccup ends a
session.

### D4 — Completion is a token the model never emits

`[WORK_DONE]` is checked at `autopilot.py:4560` and asked for in the prompt at `:4871`. **Zero
sessions emitted it.** Every apparent completion came from `_task_is_closed` (`:3252-3270`) or
`_complete_if_task_closed` (`:3388`) — i.e. the session discovered someone *else* had already closed
the task. Completion is therefore not measured; it is stumbled into.

### D5 — Retry is a brand-new session that remembers nothing

A failed task is retried as a fresh `work_sessions` row with `output_log = ''`, `steps_completed = 0`
and a fresh 5-step budget (`create_work_session`, `:3784`). `progress_checkpoints` holds **3,156 prose
rows across 745 sessions** and **nothing in the loop reads it**. Measured: **233 tasks had 2+ attempts;
0 succeeded.** Every retry re-pays for the same reconnaissance and then dies at the same 5/5.

### D6 — The autonomy gate is fail-open, so anything the framework forgot is maximally autonomous

`autonomy.should_execute` consults `autonomy_levels`; the comment at `:376` says *"Unknown actions
default to L4 (autonomous) — bias towards action"*. Measured: the dispatcher has **147** action names,
`DEFAULT_MATRIX` has **56**, and **28 actions exist in the DB but not in the matrix**. So
`hire_department`, `fire_agent`, `reactivate_agent`, `send_directive`, `propose_mission`,
`update_mission`, `schedule_action`, `deep_research`, `ask_advisor`, `delete_tool`, `gv_send_sms` and
**the whole `shop_*` / `website_*` family** resolve to **L4 — execute immediately, no human**.
A graduated-autonomy framework whose default is maximum autonomy is not a safety system; it is a
safety system's opposite. (`dept_*` scope gating still applies, so the blast radius is bounded by the
department allow-list — but only where a department allow-list exists.)

### D7 — Memory is written and almost never read

`memories` holds **25,047** rows (12,462 `observation`, 12,022 `summary`), `procedural_experiences`
**18,526**, Chroma **393,112** embeddings, mem0 **130,983**. But: `store_memory_entry`
(`database.py:3967`), `vector_search_memories` (`:4015`) and `upsert_knowledge` (`:6531`) have **zero
callers**; `from app.services.memory_consolidation import run_consolidation` (`agent_bus.py:493`) names
**a function that does not exist** and is swallowed by an `except`; three Chroma collections hold **0
embeddings**; a whole legacy Chroma tree (May 4) sits unreferenced on disk. `mem0` is installed, has
130k embeddings, and **no caller on the tick** — only chat turns. The company is writing a diary it
does not read, at a real token cost, and calling it memory.

### D8 — It cannot improve itself, and it cannot tell a human it is broken

`code_self_edit.py` has proposed many times (`data/code_proposals.json`: 25 proposals, 82 offers, 96
dedup keys, **22 no-ops**) and applied **essentially never**: `evolution_changelog` holds **exactly 1
row in 175 days** with `commit_sha` NULL, `CODE_EDIT_AUTO_APPLY=false`, and the live checkout is
refused by construction. Separately, the estate's own alarms do not reach a human: `estate-monitor`
computes `crit=5` every two minutes and logs `escalated=0` because only one condition is allowed to
escalate; `cron-liveness.py` exists and is unscheduled; the authority's journald **does not persist**
(the logs that would explain a 4 h 33 min disk-full window are gone); and five subsystems report `ok`
with **500–5,281 consecutive empty ticks** (`self_prog` 2,773, `ambient_bottom_layer` 5,281).

---

## 3. The design

**The governing idea: the company must be judged on outcomes, and it must be structurally unable to
report success it has not earned.** Everything below serves that.

### P1 — The budget belongs to the TASK, not the session
A session gets a budget derived from the task, and a retry inherits what the previous attempt already
spent and learned. Concretely: raise the working budget to **20 steps with a hard ceiling of 40**, and
make the task row carry `steps_spent_total` so a retry resumes rather than restarts.

### P2 — Reconnaissance is progress
Replace `_work_session_is_progressing`'s "a mutating action happened" with **information gain**: a step
that produced a *new* fact counts. Operationally: a step counts as progress if it called a tool whose
`(tool, normalised-args)` signature has not been seen before in this session **and** it returned
something non-empty. Ten identical `repo_search` calls are not progress; four different useful ones are.

### P3 — A stall changes strategy; it does not end the session
* **Repeated identical tool call (≥3 same signature in a row)** → do not abort. Inject a directive:
  *"you have called X with the same arguments 3 times; the approach is not working — do Y or explain
  why X must be repeated."*
* **Two empty turns** → re-prompt once with the JSON envelope the prompt already documents; only a
  second consecutive failure escalates.
* **A tool failing 3 times** → classify first: an **argument error** (the error text names a bad
  parameter) gets one retry with the error fed back; a **missing dependency / moved script** (rc=127,
  `not found`, `not configured`) is *not retryable* and must escalate with the exact stderr.

### P4 — Done means an artefact changed or a task closed — never a token
`[WORK_DONE]` becomes an *intent to finish*, not the verdict. A session closes successfully only when
one of these is true and is recorded: a named file changed (with its hash before/after), a task moved to
a closed state **by this session**, or an outbound artefact was produced and recorded. The session
records which one it was. `tick_quality` must stop grading a tick `productive` on one tool call — a
tick whose work session died is not productive.

### P5 — Resumable sessions
Before a retry, build the new session's context from: the task, the previous attempt's last checkpoint,
a **distilled attempt record** (tools tried, what each returned, what failed and why), and any memories
relevant to the task. The tables already hold the raw material; this is a read that does not currently
happen.

### P6 — The autonomy gate fails closed
Every name in the 147-name dispatcher chain gets an explicit row, generated from the chain itself so it
cannot drift. **Unknown actions resolve to L1 (suggest), not L4.** Actions that move money, send
anything outbound, change staff, or touch production become L1/L0 explicitly. A test asserts
`dispatcher_names ⊆ matrix_names` and fails the build when a new action arrives without a level.

### P7 — Memory that is read
Only write a memory a caller will read. Concretely: give the work loop a memory read at session start
(relevant prior attempts and facts), make `memory_consolidation` import something that exists, delete
the zero-caller helpers or wire them, and stop writing the two largest categories
(`observation` 12,462 / `summary` 12,022) unless a read path consumes them. Measure it: a memory that
is written and never retrieved in 7 days should be reported, not stored.

### P8 — Model ids resolve at runtime, always
**181 literal model ids across 13 files** is a standing-instruction violation and the exact shape of
the failure that silently broke every live AI call in `personality-system` for a week. Every
operational default reads the gateway's catalogue and validates against it; unknown ids are dropped
with a loud log; the model that actually served a request is published. Catalogue rows and test
fixtures may keep literals; operational defaults may not.

### P9 — Silent failure gets a transport
Every condition `estate-monitor` already computes gets a route to a human, at a severity that is
allowed to escalate; `cron-liveness.py` is scheduled; the authority's journald persists; subsystems
with N consecutive empty ticks are reported, and `rc=127` is treated as "the script moved" and alerted
specifically.

### P10 — It can improve itself, safely, on evidence
The self-edit machinery is real and well-gated; what is missing is the **loop**: propose → apply into
the isolated root → run the verification command → only then promote, with a snapshot and a rollback,
and a **proposal queue a human can see**. A proposal that does not name its verification command is
refused.

---

## 4. How we will know it worked

Nothing here is claimed on the strength of the change being made. The numbers to move, all already
measurable from `work_sessions`, `tick_telemetry` and `model_usage`:

| measure | today | target |
|---|---|---|
| work sessions ending in real completion (artefact/task closed **by this session**) | **0 of 824 in 7 days** | > 80% |
| `STEP_BUDGET_EXHAUSTED` share of failures | 65.3% | < 10% |
| `TOOL_LOOP_DEADLOCK` share | 26.9% | < 5% |
| tasks with 2+ attempts that eventually succeed | **0 of 233** | > 60% |
| actions resolving to L4 without an explicit row | ≥ 91 (147 − 56) | **0** |
| model ids hardcoded in operational defaults | 181 across 13 files | 0 |
| 7-day model spend | 119.10 USD | down, at equal or better outcome |
| subsystems reporting `ok` with >100 consecutive empty ticks | 5 | 0 (either they produce, or they are retired) |

**The measurement is the deliverable.** A change that does not move one of these rows is not a fix.

---

## 5. Order of work, and why this order

1. **The loop (P1–P5).** This is 92% of the failure population (379 + 156 + 43 + the 0/233 retries).
   Nothing else matters until a session can finish a task.
2. **The gate (P6).** Correctness and safety, and it is a generated file plus a test, so it is cheap.
3. **Memory that is read (P7).** It is what makes a retry worth making, so it lands with P5's benefit.
4. **The model layer (P8).** A time bomb with a known explosion date. Cheap to defuse.
5. **Transport for silent failure (P9).** Cheap, and it is how we find out if any of the above broke.
6. **Self-improvement (P10).** Last, because it should not run on a loop that cannot finish a task.

**The dead subsystems are retired in step 1, not as a separate project.** `fleet_location_poll` (414
consecutive failures, dead since 2026-09-29), `amazon_sync`/`ebay_sync` (`rc=127`, `tsx: not found`),
and the five empty-tick subsystems cannot be fixed by retrying them harder; retrying them is currently
what generates a measurable share of the failure population.

---

# ROUND 3 REVISION — 2026-10-14, written after measuring what is already live

**This section supersedes §5 (the order of work) and revises §4 (the targets). §2's eight defects and
§3's ten changes remain the analysis; what changed is the order, the framing, and two of the facts.**

## R1. Two of the ten changes are already live — applied by another session, not by this program

Verified on `secratary-cloud`, read-only, 2026-10-14 ~12:15Z: `/opt/company/app/autopilot.py` was
modified at **07:23:44Z** (md5 `30a4a185a8e28395092032fc4d367f36`, 522,614 B; backup
`autopilot.py.bak-item80-20261014T072225Z`). The live file now carries:

* **P1, live**, in the exact shape asked for: `_WORK_MAX_STEPS = 20` (was 5), `_WORK_ABSOLUTE_MAX_STEPS = 30`, `_WORK_ABSOLUTE_MAX_TURNS = 60`.
* **P4, live**: `[WORK_DONE]` is documented in the source as *"an intent to finish, never the verdict"*,
  with completion recorded through `[ARTEFACT:`, `[OUTBOUND:` and `[TASK-CLOSED-BY-SESSION:` markers.

`app/services/autonomy.py` — the gate build's target — is **untouched** (Jul 1 04:10), so **P6 is not
live and the safety hole in D6 is open right now**: the dispatcher has 147 action names, the matrix 56,
and an action with no row resolves to L4, *execute immediately, no human*.

## R2. The budget fix moved the failure class and did not move the outcome — measured

`work_sessions` started 2026-10-14, split at 07:23:00:

| window | sessions | completed | failed | completed % | STEP_BUDGET_EXHAUSTED | TOOL_LOOP_DEADLOCK | STALLED_REPEATING |
|---|---:|---:|---:|---:|---:|---:|---:|
| before 07:23 | 65 | 25 | 34 | 38.5 % | 32 (49 %) | 13 (20 %) | 6 (9 %) |
| after 07:23 | 26 | 8 | 14 | 30.8 % | 5 (19 %) | 7 (27 %) | 10 (38 %) |

Budget exhaustion collapsed, exactly as intended. The completion share did not move, and at n=26 that
difference is noise rather than a regression. **Stalling became the dominant residual failure at 38 %
of sessions.** So the next change is **P3, not P2 and not P5.**

Evidence-backed completions (`output_log LIKE '%TASK-CLOSED-BY-SESSION%'`) are **24 today and 0 on each
of the preceding eight days** — a qualitative change did land even though the rate did not move.

## R3. The framing correction: the company is not the only always-alive agent, and it is not the best one

Measured this round, both on the same host, read-only:

| | wake loop (`/root/bin/work.py`, cron) | the company (`/opt/company`, bespoke loop) |
|---|---|---|
| cost | 5.1770 USD / 78 releases (10-13); 9.5870 USD / **136 releases** (10-14) | **~17.5 USD/day**, ~123 USD/7 days (corrected; see `L3801`) |
| per unit | **0.0900 USD per closed-with-proof item**, 0.0689 per release | **~0.53 USD per "completed" work session**, of which **77 of 266** contain a URL or a path |
| discipline | claim → work → **close `--did/--proof/--result/--left`**, or `blocked` with the measurement; `nothing-todo` must be reported and stops the shift | completion keyed on markers; 24 sessions today proved it, 242 did not |
| self-limiting | hard 150 releases/day and 25 USD/day; the log shows it stopping at `daily_cap: 150/150, claimable_now: 0`; pause file; single-flight lock | none found |
| store | `/root/work/work.db`, 214 items (done 164, blocked 25, todo 20, dropped 5), 424 attempts, 412 with a proof | `work_sessions` / `tick_telemetry`; `tick_telemetry.total_cost` ~1.02 USD/week against ~123 actually spent |

**The proofs are real and I checked them rather than trusting the count.** Sampled from `attempt`:
`GUARD exit 0: OK - 7 annotated-forbidden WO merges are all still refused; unlinked records 199 …`;
`personas: 4 · findings: 42 · blocker 8 · major 20 · minor 9 · note 5 · refused 0 | 4b0faab docs(daily-walk) …`;
`DOD (live Heuristic/personal-checking rows on doc 9757bc2d): 0 -> PASS …`; and one attempt that says
plainly `STARTED, NOT FINISHED … no writes made` with `state_after=todo` and `exit_code=0`. **That last
one is the strongest evidence in this document**: the system records an honest partial as a partial.

## R4. The revised order of work

1. **P6 — the gate fails closed.** It is a live safety hole (`fire_agent`, `hire_department`,
   `delete_tool`, and the whole `shop_*` / `website_*` family can execute unattended), the build exists
   in `/root/work/evolve2-gate`, and `autonomy.py` has not moved since July, so the patch is clean.
2. **P3 — a stall changes strategy.** Now the dominant residual failure at 38 %. Build on the **live**
   `autopilot.py` (07:23 revision), never on a stale base.
3. **Dead weight and the reporting defect.** Retire the genuinely dead (`fleet_location_poll`, dead
   since 2026-09-29); **repair** amazon/ebay (their `tsx` devDependency is simply not installed — this
   is not a dead subsystem, it is a missing `npm install`, and calling it dead would be wrong); fix
   `consecutive_empty_ticks`, which increments on a blank-detail *success* and is read only as a cadence
   throttle, so it cannot mark anything as failing; and fix the timestamp-window bug (`L3801`) that
   inflates every rolling-window figure the company reports.
4. **The bridge — company work sessions close like ledger items.** Every work session must end by
   recording `did` / `proof` / `result` / `left`, or close `blocked` with the measurement. This is the
   single change that converts "completed because someone else closed the task" into a claim that can be
   checked, and it is deliberately a *narrow* version of the architecture change below.
5. **Then** reduce the bespoke always-alive loop to a low-frequency heartbeat that **files ledger items**
   instead of launching its own sessions, and let the ledger own claim/close. This is phase 5 and not
   phase 1 on purpose: a big-bang replacement of a live revenue-adjacent loop is the failure mode this
   estate keeps recording, and the bridge in (4) is what makes (5) safe.
6. **P5** (retries resume from the previous attempt's evidence), then **P7** (memory that is read),
   **P8** (181 hardcoded model ids across 13 files), **P9** (a transport for silent failure — the
   wedged-`company-api` incident of this same morning, `H3660`, is its proof: the unit was `active`,
   `NRestarts=0`, and answered nothing for over 50 minutes).

**The condition under which the ledger direction is abandoned:** if a company work session that closes
with a `did`/`proof`/`result` triple proves no more reliable than one that closes on a marker — measured
over at least 50 sessions — then the ledger discipline is not what is doing the work and phase 5 is off.

## R5. Revised targets, with today's corrected baselines

| measure | baseline 2026-10-14 | target |
|---|---|---|
| work sessions `completed`, 7 days | 237 of 786 (**30.2 %**) | > 80 % |
| evidence-backed completions per day | **24 today, 0 on the 8 preceding days** | all of them |
| `STALLED_REPEATING_OUTPUT` share of sessions | **38 % after the budget fix** | < 5 % |
| actions resolving to L4 with no explicit row | ~91 | **0**, asserted by a test |
| 7-day model spend | ~123 USD | down, at equal or better outcome |
| cost per proven item | company ~0.53 USD, wake loop **0.0900 USD** | measured and published weekly |
| rolling-window figures off by a full day | **every query using `datetime('now',...)`** | 0 |
