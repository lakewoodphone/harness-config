# Company failure audit — why the AI company on `secratary-cloud` fails most of the work it attempts

HOST: `zabz-tech-linux` (Linux 6.8, user `zabz`; the node contract expected Windows `ZABZ-TECH`, but this seat has a working `bash`, `python3` and `sqlite3`, and `ssh secratary-cloud` prints `secratary-cloud`).

**Snapshot:** 2026-10-14T01:01–01:02Z.
**Authority:** `/root/authority.db` (26.8 GB at read time), opened read-only.
**Window:** `started_at >= datetime('now','-7 days')`.
**Effective lower bound:** the query compares a `T`-separated ISO timestamp against a space-separated `datetime()` string, and `'T'` sorts after `' '`, so the comparison actually includes **all of 2026-10-07T00:00:00Z onward**, not 01:0xZ. Every count below uses this window; the exact commands are in the EVIDENCE LOG.

> **Brief correction.** The task says the failure strings are emitted by `app/services/agent_worker.py` and `app/services/tick_quality.py`. They are **not**. `agent_worker.py:728` only *names* `[STEP_BUDGET_EXHAUSTED …]` and `[STALLED_REPEATING_OUTPUT]` in a docstring; `tick_quality.py` only *grades* ticks (`productive/reactive/failed/empty`, `tick_quality.py:5-14`). Every session-terminal failure marker is written by **`/opt/company/app/autopilot.py`** (`_close_unfinished_work_session`, line 3304) and its detail is built by **`/opt/company/app/services/work_step_ledger.py`** (lines 112-133). I traced the strings to those files instead.

---

## 1. The failure population, counted

### 1.1 Classification rule (explicit, re-runnable)

For every `work_sessions` row in the window, take the **last terminal marker** in `output_log` and map it to a reason. A terminal marker is one of the bracketed strings written by `autopilot.py` `_close_unfinished_work_session()` / `_fail_artifact_required_work_session()`, or one of the `COMPLETED…` inline markers. If no terminal marker is present, `status` decides (`completed` → `completed_no_marker`, else `unknown`). The rule is implemented in `classify_work_sessions.py` (generated the TSV `ws7d.tsv`, one line per session, 824 rows).

The marker-to-reason mapping is not a guess: `_close_unfinished_work_session` builds `marker = f"[{reason.upper()}: {detail}]"` (autopilot.py:3304) and sets `status='failed'` (:3308) for every non-completion it closes.

### 1.2 The population — all 824 sessions in the window

| terminal reason | count | share of 824 | status |
|---|---:|---:|---|
| `STEP_BUDGET_EXHAUSTED` | 379 | 46.0 % | failed |
| `completed` (task-closed paths; **not** `[WORK_DONE]`) | 236 | 28.6 % | completed |
| `TOOL_LOOP_DEADLOCK` | 156 | 18.9 % | failed |
| `STALLED_REPEATING_OUTPUT` | 43 | 5.2 % | failed |
| `BLOCKED-ON-OWNER` | 8 | 1.0 % | paused |
| `COMPLETION BLOCKED` (artifact-required) | 1 | 0.1 % | failed |
| `BUDGET_EXHAUSTED` (bare, not `STEP_`) | 1 | 0.1 % | failed |
| **total** | **824** | **100 %** | |

The task's headline numbers reproduce: **580 failed / 235–236 completed / 8 paused**. My export read 236 completed; the task's earlier read saw 235 — one session flipped between reads on a live DB. The failed count is exactly 580.

Within the **580 failed**: `STEP_BUDGET_EXHAUSTED` 379 (65.3 %), `TOOL_LOOP_DEADLOCK` 156 (26.9 %), `STALLED_REPEATING_OUTPUT` 43 (7.4 %), artifact-blocked 1, bare `BUDGET_EXHAUSTED` 1.

Within the **236 "completed"** there are exactly two shapes, and **none is a real completion**:
| completion marker | count |
|---|---:|
| `COMPLETED: the task itself is closed; no [WORK_DONE] token was required` | 204 |
| `COMPLETED: the step budget was spent and the task's own status is closed` | 32 |
| `COMPLETED by LLM signal` (`[WORK_DONE]`) | **0** |

So the "29 % success rate" is **29 % of sessions discovering that a task row was already `done`**, not 29 % of work finishing. Every one of the 236 completions fired on `_task_is_closed()` (autopilot.py:3252-3270) or `_complete_if_task_closed()` (:3388); not one model emitted `[WORK_DONE]`.

`agent_id` is `orchestrator` for **all 824** rows (verified), confirming the brief.

---

## 2. The three dominant shapes, explained from source

### 2.1 `STEP_BUDGET_EXHAUSTED` — 379 sessions (65.3 % of failures)

* **Emitted by:** `_close_unfinished_work_session` at **autopilot.py:3304** (`marker = f"[{reason.upper()}: {detail}]"`). Called with `reason="step_budget_exhausted"` from three sites: **:3938** (pre-loop guard), **:4691** (the in-loop gate), **:4818** (post-loop path).
* **Detail built by:** `WorkStepLedger.marker_detail`, **work_step_ledger.py:112-124**:
  `reached {work_steps}/{planned_steps} work steps in {turns} model turns (…; {tool_trace}) without [WORK_DONE]`.
* **Condition that triggers it:** the loop has charged `planned_steps` work steps and `_task_is_closed()` is false. A "work step" is a turn with ≥1 executed action (`charge()`, work_step_ledger.py:67-81). The trace in the marker is built by `_work_tool_trace` (autopilot.py:3132-3147).
* **What the loop does next:** it closes the session `failed` at `progress_pct=99`, calls `fail_job`, and saves a checkpoint of the last 5000 chars (autopilot.py:3304-3334).
* **The evidence that this is not a model-quality problem:** median **10 tool calls** per failed session; the tools are dominated by reconnaissance, not idling — `repo_search` (157 sessions), `list_tasks` (132), `memory_search` (108), `repo_list_dir` (104), `save_memory` (88), `system_health` (72), `create_task` (59), `gmail_search` (58). The canonical example is session **77803**: `reached 5/5 work steps … 10 tool call(s) over 1 distinct tool(s): repo_search` — ten searches, no `[WORK_DONE]`.
* **The design fault:** the budget is a fixed **5** (`_WORK_MAX_STEPS`, autopilot.py:2779) and the only way to earn more is `_maybe_extend_work_session_budget` (:3030-3088), which extends **only if `_work_session_is_progressing` (:3184-3214) is true** — i.e. a *non-read-only* action in the last 3 persisted step markers and no repeated signature in the last 2. A session that spends its five steps investigating (`repo_search`, `repo_list_dir`, `list_tasks`) is, by definition, *not progressing*, so it can never earn the extension that would let it finish. The prompt tells the agent to "work step by step" and "EVERY step must contain at least one tool call" (:4868), then starves it at five. **Control-flow + context fault.**

### 2.2 `EMPTY-TURN` / `NO-ACTION` — 38 sessions terminate on it

* **Emitted by:** the step markers `[NO-ACTION: …]` at **autopilot.py:4345-4349** and `[EMPTY-TURN: …]` at **:4368-4373** (in-loop) and **:4471-4475** (persisted copy).
* **Condition:** `ledger.charge(actions=actions_executed)` returns `EMPTY_TURN` when a turn executes **zero** actions (work_step_ledger.py:79-81); after **two silent turns in a row** the loop sets `empty_turn_reason="stalled_repeating_output"` and breaks (`ledger.empty_turns_in_a_row >= 2`, autopilot.py:4477-4488). The terminal marker is then written by `_close_unfinished_work_session` via the post-loop block at **:4758-4777**.
* **What the loop does next:** ends the session `failed` with detail `"2 consecutive model turns produced no tool call after X/5 work steps; the step budget is untouched"`.
* **Counts:** 43 sessions carry the terminal `STALLED_REPEATING_OUTPUT` marker; **38 of those are this empty-turn shape**, 5 are the prose shape below. 62 failed sessions contain a `[NO-ACTION:` marker, 62 contain `[EMPTY-TURN`, and 39 failed sessions contain both. 22 `STEP_BUDGET_EXHAUSTED` sessions also contain the pair (empty turns happened *inside* a budget run).
* **The design fault:** the loop treats "the model produced no parseable tool call" as terminal after two turns, instead of re-prompting or falling back to the JSON envelope the work prompt itself describes (:4865-4867). A single provider/format hiccup ends the session. **Tool-surface fault.**

### 2.3 `STALLED_REPEATING_OUTPUT` (prose) — 5 sessions

* **Emitted by:** the repetition guard at **autopilot.py:4384-4428**. Condition: `len(cleaned) > 50` **and** `_text_similarity(cleaned, self._last_work_output) > 0.85` **and** `not actions` (:4385-4391); at `_repeat_count >= 2` (three near-identical replies) it closes the session with `reason="stalled_repeating_output"`, detail `"{n} consecutive near-identical steps"` (:4415-4427).
* **Counts:** 5 sessions (the remainder of the 43 `STALLED_REPEATING_OUTPUT`).
* **The design fault:** the guard explicitly excludes steps that **did** execute actions (`and not actions`, added 2026-09-14). It therefore cannot see the much larger failure it sits next to — the same **tool** called over and over. That shape is caught (late, and destructively) by the tool-loop quarantine instead. **Prompt/context fault.**

---

## 3. The step budget

* **Is it 5?** Yes. `_WORK_MAX_STEPS = 5`, **autopilot.py:2779**. `create_work_session(... total_steps=self._WORK_MAX_STEPS)` at **:3789**; the in-memory `active_session["total_steps"]` is also 5 (:3809). It is **not per-task**: every session starts at 5 regardless of task.
* **Can it grow?** `_WORK_STEP_EXTENSION = 3`, `_WORK_MAX_EXTENSIONS = 2`, `_WORK_ABSOLUTE_MAX_STEPS = 15` (:2784-2792); `_maybe_extend_work_session_budget` (:3030-3088) extends 5→8→11 (cap 15) only when `_work_session_is_progressing` (see §2.1). The turn allowance is separate: `_WORK_TURN_MULTIPLIER = 3`, `_WORK_ABSOLUTE_MAX_TURNS = 15` (:2799-2800), `_work_turns_cap` (:3149-3157) → `min(15, total_steps*3)` = 15 for a 5-step plan.
* **Why `6/5` appears.** Two independent facts:
  1. `ledger = WorkStepLedger(planned_steps=total_steps, …)` snapshots `planned_steps=5` at **autopilot.py:3956-3962**, and the ledger is **never updated** when `_maybe_extend` raises the local `total_steps`. `marker_detail` prints `ledger.work_steps / ledger.planned_steps` (work_step_ledger.py:119-124), so any session that ran past 5 reports `N/5`.
  2. The in-loop gate is `if current_step >= total_steps:` at **:4636**, where `current_step = ledger.work_steps` is read **before** the turn is charged (:4127). So when the 5th step is done the gate examines `4 >= 5` (false) and lets a 6th turn run; on the 6th iteration it examines `5 >= 5` and fails with `ledger.work_steps = 6`. The 356 sessions that report `5/5` were instead closed by the **pre-loop** guard at **:3891-3942** (`steps_floor >= total_steps`, where `steps_floor` is the persisted `steps_completed` column), which fires before the extra turn.
  Observed distribution of `STEP_BUDGET_EXHAUSTED`: **356 at 5/5, 19 at 6/5, 3 at 9/5, 1 at 12/5** — the `N>5` cases are the extension paths, and `N/5` is the frozen denominator, not a 6th-step allowance.
* **Is `[WORK_DONE]` the only success signal?** **No — and in this window it was never used.** The code checks the model's reply for `"[WORK_DONE]"` at **:4560** (and accumulated output at :4009), but the token is **written by the LLM**, not by code; the prompt asks for it at **:4871** and :4879. Two code paths complete a session without it: `_task_is_closed` at **:4523** and `_complete_if_task_closed` at **:3388** (also :4660, :4790). In the window, **0** sessions completed via `[WORK_DONE]`, **204** via "task itself is closed", **32** via "budget spent + task closed".

Quoted code:
```python
# autopilot.py:2779
_WORK_MAX_STEPS = 5
# autopilot.py:4636 (the gate that "fires at 5/5")
if current_step >= total_steps:
# work_step_ledger.py:119-124 (the marker)
return (
    f"reached {self.work_steps}/{self.planned_steps} work steps in "
    f"{self.turns_spent} model turns "
    f"({self.work_steps} action step(s), {self.empty_turns} empty turn(s) "
    f"that did not spend a work step; {tool_trace}) without [WORK_DONE]"
)
```

---

## 4. Repeat and retry behaviour, quantified

Window is the same 7 days; every session in it has a non-null `task_id`, and the 824 sessions map to **403 distinct tasks**.

**Attempts per task (work_sessions in the window):**

| attempts | tasks |
|---:|---:|
| 1 | 170 |
| 2 | 48 |
| 3 | 184 |
| 6 | 1 |
| **≥2** | **233** |

**Worst offenders by attempt count:**
| task | attempts | failures | title |
|---|---:|---:|---|
| 28052 | 6 | 6 | Fix `fleet_location_poll` subsystem — 414 consecutive failures |
| 27758 | 3 | 3 | Reply to 300DDR re Ticket #74115 (Eliyahu Zabrowsky ST200…) |
| 27760 | 3 | 3 | `cfo_backup`: the backup verifier compares a snapshot against… |
| 27761 | 3 | 3 | Review voicemail from (732) 364-2373 before responding |
| 28518 | 3 | 3 | Fix browser automation on host: use system Chrome channel |
| … | 3 each | 3 each | 180 more tasks at exactly 3 attempts |

(`28518` is the brief's "retried four times": the window shows 3 work_sessions — 78605, 78606, 78607 — all `STEP_BUDGET_EXHAUSTED`; a 4th attempt may predate the window.)

**Does a retry ever succeed?**
* Of the **233** tasks with N≥2 attempts, **71** had at least one `completed` session and **162** had none.
* **All 71 of those completions are the `[COMPLETED: the task itself is closed]` path. Zero had a completion at budget or by LLM signal.**
* By the task row's *current* status, **107 / 233** are `done`/`completed`/`closed` — but those were closed by task hygiene or the owner, not by the retried sessions (no session in the window ever ran the `[WORK_DONE]` branch, which is the only branch that closes a task, :4573-4594).

**Answer: 0 of 233.** Retries for tasks with ≥2 attempts never completed the work; the apparent 71 "recoveries" are sessions that woke up to find the task already closed.

---

## 5. The stalled task population (`tasks`)

`tasks` at the snapshot: **237 blocked**, 29 open, 29 in_progress, plus a few stray statuses. The blocked population:

**Age** (against 2026-10-14T01:00Z; `created_at` is used as the event time — it is the row's own creation stamp, not an ingest time):
| age | count |
|---|---:|
| < 1 day | 28 |
| 1–3 days | 19 |
| 3–7 days | 69 |
| 7–14 days | 66 |
| > 14 days | 55 |
| **median** | **7.22 days** (min 0.02, max 29.04) |

**Classification by reason text** — priority order, first match wins: `duplicate/consolidated` (contains "consolidated into task" / "duplicate" / "superseded") → `owner_gated` (explicit phrases: "blocked on owner", "owner input/decision/approval/confirmation/physical action", "only the owner", "requires owner", "awaiting owner", "asked owner", `ask_owner`, …) → `engineering_fault` (`tsx: not found`, `rc=127/255`, "not connected", "unreachable", "consecutive fail", "deadman", "db_contention", "failed to launch", "probe failed", "root cause", "subsystem", "timeout", "error", "broken", "fix", "repair", "degraded", "stalled", "down", "failing", "failure") → `external_dependency` (bank/vendor/carrier/gov names) → `auto_generated_hygiene` (`[Initiative tick]`, `[ACTION]`, "Auto-created for work order", "Standing work order", …). Full 237-row table: `blocked_tasks_classified.tsv`.

| priority category | count |
|---|---:|
| engineering_fault | 81 |
| external_dependency | 39 |
| owner_gated | 32 |
| duplicate/consolidated | 34 |
| auto_generated_hygiene | 13 |
| unclassified | 38 |
| **total** | **237** |

Because these markers overlap, the independent (non-exclusive) marker counts are the harder evidence: **"duplicate" 34, owner-gating 35, engineering/tool fault 95, external party 85, auto-generated 28.**

**The owner's share.** `tasks.assigned_to` is `owner` for only **4** of 237; 233 are assigned to department agents. The real owner backlog lives in **`owner_decision_queue`: 155 rows `pending`** (2 critical, 38 high, 104 medium, 11 low), asked between 2026-09-16 and 2026-10-13 (plus 229 resolved, 71 dismissed, 38 answered). So the owner answers for a **minority**: ~32 blocked tasks name an owner gate, and 155 questions are queued for him. The plurality — **81 by priority / 95 by marker** — name an engineering or tool fault inside the company, and 34 are explicit duplicate/consolidation artifacts. The blocked population is mostly the company's own broken machinery plus auto-generated noise, not owner decisions. The brief's framing is correct.

---

## 6. Dead and flapping subsystems

### 6.1 The autopilot's own subsystem ledger

Read from `/opt/company/data/autopilot_state.json` (written by the running autopilot, `updated_at 2026-10-14T00:59:49Z`; 39 subsystem rows). Exactly **three** subsystems have `consecutive_failures >= 1`; the other 36 are at 0:

| subsystem | consecutive failures | last attempt | last error | what it does / status |
|---|---:|---|---|---|
| `fleet_location_poll` | **414** | 2026-09-29T03:44:44Z | `0 polled, 1 errors` | Polls fleet/vehicle location. **Dead ~14.9 days**; the counter is frozen because it no longer runs. Its last 10 recorded runs (2026-09-28T19:04 → 2026-09-29T03:44) all fail. |
| `ebay_sync` | 3 | 2026-10-13T04:20:07Z | `eBay download failed (rc=127). stderr: sh: 1: tsx: not found` | Daily download + ingest of eBay transactions into `accounting.db`. Streak began **2026-10-11T05:41Z** ("quickbooks-agent repo not found"), continued 10-12, then `tsx` missing on 10-13. |
| `amazon_sync` | 3 | 2026-10-13T04:00:23Z | `Amazon download failed (rc=127). stderr: sh: 1: tsx: not found` | Same, for Amazon. Streak began **2026-10-11T05:41Z**. |

Three further subsystems carry frozen historical counters but are `disabled_superseded` with `consecutive_failures` reset to 0: `boa_sync` (114 historical failures, disabled 2026-07-21), `spending_report` (38, disabled 2026-09-03), `balance_capture` (2, disabled 2026-08-04). They are the subject of the `subsystem_presence.py` retirement fix (docstring, 2026-09-15) and are no longer being escalated.

### 6.2 `tick_telemetry`

Window `started_at >= '2026-10-12…'`/7d, 1,019–1,021 rows (live drift):

| outcome | tick_quality | count | zero-`steps_completed` |
|---|---|---:|---:|
| complete | productive | 903 | 0 |
| error | empty | 39 | 39 |
| escalate | empty | 25 | 25 |
| error | failed | 17 | 17 |
| suspended | reactive | 12 | 12 |
| suspended | empty | 10 | 10 |
| suspended | productive | 8 | 8 |
| complete | reactive | 5 | 0 |

* **Zero-work ticks:** **111 / 1,019 (10.9 %)** have `steps_completed = 0`; **92 / 1,019 (9.0 %)** have empty `tool_calls_json`. **0** have `llm_rounds = 0` — every tick paid for at least one model round. Every zero-step tick is `error`/`escalate`/`suspended`; all 908 `complete` ticks did at least one step. This matches the 2026-10-13 baseline ("10–15 % of ticks do no work").
* **Error ticks by agent:** `dept_home_life` **31** (Home Assistant `ha_status` down), `dept_engineering` 6, `dept_ai_platform` 4, `dept_finance` 3, `dept_research` 3, `dept_world_index` 3, `dept_business_ops` 2, `orchestrator` 2, `dept_devices` 1, `evolution_architect` 1.
* **Representative `error` strings:** `[TOOL_LOOP_DEADLOCK: 'ha_status' failed identically 3/3 …]` (11 ticks), `No tool call executed successfully. Invalid or blocked attempts: ha_status, save_memory, …` (several), `LLM error (round 2): [identical failure 1/3 …]`.

**Contradiction worth carrying into the redesign:** the tick telemetry reports **908/1,019 = 89 % `complete`** while the work sessions under it failed **580/824 = 70 %**. `tick_quality` grades a tick `productive` on *one* meaningful tool call (`tick_quality.py:5-14`, `_PRODUCTIVE_TOOLS`), so a tick that successfully runs a work session which then dies at 5/5 is still `complete|productive`.

---

## 7. The cost of failure

### 7.1 `tick_telemetry` per day (tokens/cost the tick loop records)

| day | ticks | total_tokens | total_cost |
|---|---:|---:|---:|
| 2026-10-07 | 140 | 1,679,470 | $0.1382 |
| 2026-10-08 | 172 | 2,168,254 | $0.1780 |
| 2026-10-09 | 167 | 2,101,145 | $0.1771 |
| 2026-10-10 | 101 | 1,142,613 | $0.0939 |
| 2026-10-11 | 152 | 1,784,042 | $0.1471 |
| 2026-10-12 | 122 | 1,392,156 | $0.1147 |
| 2026-10-13 | 163 | 1,973,010 | $0.1673 |
| 2026-10-14 | 2 | 22,039 | $0.0018 |
| **7-day** | **1,019–1,021** | **≈12.3 M** | **≈$1.02** |

### 7.2 `model_usage` per day (all LLM calls the company logs)

| day | calls | total_tokens | estimated_cost_usd |
|---|---:|---:|---:|
| 2026-10-07 | 1,908 | 39,435,453 | $17.5348 |
| 2026-10-08 | 2,110 | 40,297,072 | $19.7343 |
| 2026-10-09 | 1,762 | 36,603,056 | $16.7934 |
| 2026-10-10 | 1,337 | 26,324,969 | $12.2591 |
| 2026-10-11 | 1,386 | 32,701,726 | $15.1986 |
| 2026-10-12 | 1,193 | 28,782,763 | $13.4434 |
| 2026-10-13 | 2,758 | 49,964,574 | $23.3229 |
| 2026-10-14 | 99 | 1,800,044 | $0.8111 |
| **7-day** | **≈12,553** | **≈255.9 M** | **≈$119.10** |

`tick_telemetry` records only ~5 % of the tokens in `model_usage`; its `$1.02` is **not** the company's LLM spend. The per-agent split for the window is led by `orchestrator` (2,574 calls, $34.70) and `dept_finance` (1,295, $17.77), `dept_engineering` (1,021, $14.78).

### 7.3 Spend on work sessions that ended in failure — **the join is not sound**

`model_usage.session_id` is **not** `work_sessions.id`. It is a 32-hex opaque string (e.g. `00061be3bd3703bf4db0c694f6dbc302`), and the work-mode logging path (`assistant_chat._log_usage`, authority `app/assistant_chat.py:4373`) **does not pass `session_id` at all**. A `CAST(session_id AS INTEGER) = work_sessions.id` join matches **4 of 12,554** rows in the window — those are coincidences where the hex token happened to be all digits. **I will not report a per-session failure cost from that join.**

**Order-of-magnitude estimate (labelled as an estimate, not a join).** The session `output_log` records one marker per turn; summing `[ACTIONS:` + `[EMPTY-TURN` over the window's sessions gives **3,156 work-mode turns**, of which **2,310 (73 %) are in failed sessions** (3.98 turns/session) and 831 in completed sessions. Work mode's default tier is `fast` (`_work_mode_tier` defaults to `fast`, autopilot.py:1001), whose 7-day average in `model_usage` is **$0.012529/call**; the all-tier average is **$0.009604/call**. That gives:

* failed-session LLM spend ≈ **$22–29** of the **$119.10** 7-day `model_usage` total (**19–24 %**).

Treat this as ±50 %: work-mode prompts are longer than the average call, and the turn count excludes any hidden retries inside `run_assistant_chat`. The only *sound* statement is: **~70 % of work sessions failed, and they account for roughly a fifth to a quarter of the 7-day model spend; the exact per-session number is NOT DETERMINED because the join key does not exist.**

---

## 8. Root causes, ranked

Ranked by number of sessions explained in the 7-day window.

| # | root cause | sessions | file + line evidence | fault class |
|---|---|---:|---|---|
| 1 | **Fixed 5-step budget; the only extension requires "progress", and reconnaissance never qualifies.** A session that spends its five steps investigating is closed `failed` with `5/5` and no path to finish. | **379** (46 %) | `_WORK_MAX_STEPS = 5` autopilot.py:2779; extension gate `_work_session_is_progressing` :3184-3214; `_maybe_extend_work_session_budget` :3030-3088; close :4691/:4818; detail work_step_ledger.py:112-124 | control-flow + context |
| 2 | **Tool-loop quarantine aborts a session after 3 identical tool failures** — including fixable *parameter* errors (`gmail_read` bad `message_id`) and environment errors (`repo_search` no checkout). The verdict is also misreported as `0/3`. | **156** (19 %) | `_note_tool_failure` agent_worker.py:882-912; limits agent_worker.py:734-775 (3 / 300 s); call + close autopilot.py:4173-4234; bad read `strikes` vs `count`: autopilot.py:4202-4214 vs `tool_loop_snapshot` agent_worker.py:950-961 and `_tool_loop_deadlock_summary` :984 | tool-surface + environment |
| 3 | **Two consecutive empty turns end the session** instead of re-prompting / using the JSON envelope the prompt itself documents. | **38** | `charge` returns `EMPTY_TURN` work_step_ledger.py:79-81; terminal break autopilot.py:4477-4488; marker :4345-4349/:4368-4373; close :4758-4777 | tool-surface + context |
| 4 | **Completion is keyed on `[WORK_DONE]`, which the model almost never emits; the fallback (task row already closed) produced every "success".** | **236 "completed"** (0 real completions) | `[WORK_DONE]` check :4560; prompt :4871; `_task_is_closed` :3252-3270; `_complete_if_task_closed` :3388 | prompt + control-flow |
| 5 | **Dead/flapping subsystems keep generating work**: `fleet_location_poll` 414 consecutive failures (dead 15 days), `ebay_sync`/`amazon_sync` 3 each (`tsx` missing); 34 blocked tasks are duplicate/consolidated artifacts. | **~34 blocked tasks + task 28052 ×6 sessions** | `autopilot_state.json` `subsystem_health`; subsystem_presence.py | environment |
| 6 | **Prose-repetition guard is blind to tool repetition** (`and not actions`), so identical tool calls are never caught by the cheap guard and instead fester into §2.2/§2.3. | **5 prose + contributes to 379** | autopilot.py:4384-4428 | prompt/context |
| 7 | **Retry is a fresh session with no learning.** A failed task is retried as a brand-new `work_sessions` row with empty `output_log`; 233 tasks retried, **0 succeeded**. | **233 tasks / ~650 sessions** | `create_work_session` :3784; `_WORK_MAX_FAILED_ATTEMPTS` :2791; checkpoints are prose-only (§9) | control-flow |

---

## 9. What would have to be true for a retry to succeed

**Where a failed session's work goes.** `progress_checkpoints` holds **3,156 rows across 745 of the 824 sessions** (step_1 … step_12), one per turn, written by `save_checkpoint` after each step (autopilot.py:4433-4440) and once more on failure with the last 5,000 chars (`_close_unfinished_work_session` :3325-3334). What is stored is **model prose** (`cleaned[:2000]` per step, `output_text`), not tool state.

**What is lost when a session dies.**
* A retry is a **new session** (`create_work_session`, :3784) with `output_log=''`, `steps_completed=0`, and a fresh 5-step budget. It does not read the previous session's `progress_checkpoints` (the table is write-only in this loop) and it does not resume the previous `context_json` — across ticks **within** a session, `ctx["accumulated_output_tail"]`/`work_steps` are persisted (:4728-4737), but there is no equivalent seeding of a new session from a checkpoint.
* The task row may have been updated at `progress_pct = min(pct, 99)` (:4506-4514) and the description may have been rewritten, but there is no structured handoff of *what was tried*, *what tool results were seen*, or *what remains*. The 4,372 `[ACTIONS: …]` traces and rendered tool results live only in the dead session's `output_log`.
* Side effects (files written, tasks created, messages sent) survive; nothing else does.

**For a retry to be worth attempting, all of these must become true:**
1. **The work must be resumable.** The next session must be seeded from the failed session's checkpoint/output tail (or the budget must be per-**task**, not per-session), so reconnaissance is paid for once.
2. **The budget must fit the work.** Either a plan is decomposed into ≤5-step tasks at creation, or the extension rule must credit *productive reconnaissance* (distinct tools/evidence gathered), not only mutating actions — otherwise §2.1 recurs at 5/5.
3. **The tool-loop quarantine must distinguish a dead tool from a bad argument.** `gmail_read` with a malformed `message_id` and `repo_search` with no checkout are not the same as a tool that cannot work; the session should receive the error text and one retry with guidance, not be closed.
4. **Completion must be judged by the artifact/task state.** The task row is already the authority (`_task_is_closed`); the retry should start from a status the session can actually close, and `[WORK_DONE]` should be a signal, never the only one.
5. **The dead subsystems must be retired first.** Retrying `fleet_location_poll` / `ebay_sync` / `amazon_sync` tasks cannot succeed until `tsx` exists (or the syncs are formally retired), and task 28052 will keep spawning attempts otherwise.

---

## WHAT I COULD NOT DETERMINE

* **`docs/dsh-evolution/30-systems-and-autonomy-audit.md` at the path named in the brief** — I found it at `/home/zabz/instruction-audit-v2/round1/docs/dsh-evolution/30-systems-and-autonomy-audit.md` (2026-10-13, 177 lines) and read it; it exists in **no** checkout under `code/harness-config` and in no ref `git ls-files`/`git log --all` reaches. The brief's path is wrong; the content exists.
* **`docs/dsh-evolution-v2/PROGRAM.md`** — **NOT DETERMINED** as named. No `dsh-evolution-v2` directory exists anywhere I searched (`find /home/zabz -maxdepth 8 -type d -name 'dsh-evolution*'`); the `PROGRAM.md` I read is `/home/zabz/instruction-audit-v2/round1/docs/dsh-evolution/PROGRAM.md` (2026-10-13). I also read `docs/dsh-at-scale/PROGRAM.md` and `docs/mesh/188-SYSTEM-AUDIT-AND-FIXES.md` as the nearest current baselines.
* **Per-work-session LLM cost** — **NOT DETERMINED.** Tried a `CAST(model_usage.session_id AS INTEGER) = work_sessions.id` join (4 coincidental matches of 12,554), inspected the writers (`assistant_chat.py:4373` does not pass `session_id`; `database.py:4052 log_model_usage` accepts it), and confirmed `session_id` is a 32-hex opaque token. There is no sound key. The §7.3 figure is an explicit estimate.
* **The start date of the `fleet_location_poll` 414-failure streak** — **NOT DETERMINED** from `autopilot_state.json`; only the last 10 runs (all 2026-09-28/29) are retained, and `consecutive_failures` is a scalar. The last attempt is 2026-09-29T03:44:44Z, so it has been frozen since then.
* **`6/5` vs `5/5` caller split** — the code has two call sites with different caps (`_process_work_queue(proactive)` with no cap at :5579; `_maybe_poll_work_queue_fast` with `max_steps` at :7542), and the logs record the marker, not which caller produced it. I established *how* `N/5` is produced (§3), not which tick path produced each of the 23 `N>5` sessions.
* **Whether the 236 `completed` sessions closed their tasks** — **NOT DETERMINED by me.** The completion branch requires `_task_is_closed` to *already* be true and never writes `status='done'`; who closed those task rows (owner vs lifecycle sweep) is outside the work-session tables I was allowed to scan cheaply.

---

## EVIDENCE LOG

Snapshot 2026-10-14T01:01–01:02Z unless stated. `DB=/root/authority.db`. All commands read-only (`sqlite3 -readonly`). Line numbers are for the live authority files, hashed below.

```
# environment / access
hostname                                                     -> zabz-tech-linux
ssh -o BatchMode=yes secratary-cloud 'hostname'              -> secratary-cloud
ssh ... 'sqlite3 -readonly /root/authority.db ".tables"'      -> 662 tables incl. work_sessions, tasks, tick_telemetry, model_usage, progress_checkpoints, owner_decision_queue

# source (live authority, md5 anchored)
md5sum /opt/company/app/autopilot.py                          -> 34b23314de4973f306c260d89f5184b6  (11,206 lines)
md5sum /opt/company/app/services/work_step_ledger.py          -> 8fc9fba017cc5d440f5f11c0d9475294  (133 lines)
md5sum /opt/company/app/services/agent_worker.py              -> 1a2892d33e95860e62e7812eda8cf196  (5,220 lines)
md5sum /opt/company/app/services/tick_quality.py              -> f2917cc961104a1b4e6b5f7392a2318b  (303 lines)
grep -n 'STEP_BUDGET_EXHAUSTED|WORK_DONE|EMPTY-TURN|NO-ACTION|STALLED' /opt/company/app/...  -> autopilot.py only (real emitters); agent_worker.py:728 docstring; tick_quality.py none

# 7-day population
SELECT status,COUNT(*) FROM work_sessions WHERE started_at>=datetime('now','-7 days') GROUP BY status
  -> failed 580 | completed 235 (later 236) | paused 8 | active 1; total 824
SELECT SUM(task_id IS NULL),COUNT(*),COUNT(DISTINCT task_id) FROM work_sessions WHERE started_at>=datetime('now','-7 days')
  -> 0 null | 824 | 403 distinct tasks
SELECT DISTINCT agent_id FROM work_sessions WHERE started_at>=datetime('now','-7 days')
  -> orchestrator (all 824)
EXPLAIN QUERY PLAN SELECT ... WHERE started_at>=datetime('now','-7 days')
  -> SEARCH work_sessions USING COVERING INDEX idx_ws_started_at

# row-level classification (export + script; one line per session = work_sessions_7d_classified.tsv)
sqlite3 -readonly -json DB "SELECT id,task_id,agent_id,title,status,steps_completed,total_steps,progress_pct,started_at,updated_at,completed_at,output_log FROM work_sessions WHERE started_at>=datetime('now','-7 days') ORDER BY id;"
  -> ws7d.json, 824 rows, 1,234,300 bytes, SUM(LENGTH(output_log))=865,907
python3 classify_work_sessions.py ws7d.json ws7d.tsv
  -> step_budget_exhausted 379 | completed 236 | tool_loop_deadlock 156 | stalled_repeating_output 43 | blocked-on-owner 8 | completion_blocked 1 | budget_exhausted 1
  -> stalled split: empty_turn 38, near_identical_prose 5
completed subtypes: task_already_closed 204 | task_closed_at_budget 32 | llm_signal 0

# failure detail
STEP_BUDGET work-steps reached: 5->356, 6->19, 9->3, 12->1 (sum 379)
STEP_BUDGET tool names (sessions): repo_search 157, list_tasks 132, memory_search 108, repo_list_dir 104, save_memory 88, system_health 72, create_task 59, gmail_search 58, ... ; median 10 tool calls
failed sessions containing '[NO-ACTION:' 62 | containing '[EMPTY-TURN' 62 | both 39
plain-English tail of session 77803: 'reached 5/5 work steps ... 10 tool call(s) over 1 distinct tool(s): repo_search'
session 77820: 6 [ACTIONS:], 0 [BUDGET-EXTENDED], marker '6/5'
session 78143: 12 [ACTIONS:], 2 [BUDGET-EXTENDED], marker '12/5'
TOOL_LOOP_DEADLOCK detail always 'failed identically 0/3 times' (all 156)

# retries
attempts/task (7d): 1->170, 2->48, 3->184, 6->1; tasks with n>=2 = 233
of 233: any completed session 71; ALL 71 were 'task already closed'; completions at budget/LLM 0; none 162
task 28052: 6 attempts (78107,78108,78109,78302,78303,78304) all step_budget_exhausted
task 28518: 3 attempts (78605,78606,78607) all step_budget_exhausted
task rows done/closed for the 233: 107

# blocked tasks
SELECT status,COUNT(*) FROM tasks GROUP BY status
  -> done 28098 | blocked 237 | closed 56 | cancelled 32 | in_progress 29 | open 29 | completed 27 | in-progress 2 | ...
blocked age (created_at vs 2026-10-14T01:00Z): <1d 28, 1-3d 19, 3-7d 69, 7-14d 66, >14d 55; median 7.22 d, max 29.04 d
blocked priority classification: engineering_fault 81 | external_dependency 39 | owner_gated 32 | duplicate/consolidated 34 | auto_generated_hygiene 13 | unclassified 38
independent markers: dup 34 | owner 35 | eng 95 | ext 85 | auto 28
assigned_to=owner: 4 of 237; department agents: 233
owner_decision_queue: pending 155 (critical 2, high 38, medium 104, low 11); answered 38, dismissed 71, resolved 229

# subsystem ledger
/opt/company/data/autopilot_state.json (updated 2026-10-14T00:59:49Z), subsystem_health: 39 rows
consecutive_failures>=1: fleet_location_poll 414 (last 2026-09-29T03:44:44Z, '0 polled, 1 errors'); ebay_sync 3 (2026-10-13T04:20:07Z, 'tsx: not found'); amazon_sync 3 (2026-10-13T04:00:23Z, 'tsx: not found')
retired/disabled with 0 live: boa_sync 114, spending_report 38, balance_capture 2

# tick_telemetry
7d rows 1019-1021; zero steps_completed 111; empty tool_calls_json 92; zero llm_rounds 0
outcome: complete 908 | error 56 | escalate 25 | suspended 30 ; tick_quality: productive 911 | empty 74 | failed 17 | reactive 17
zero-step ticks all in error/escalate/suspended; 908 'complete' ticks had 0 zero-step
error ticks by agent: dept_home_life 31, dept_engineering 6, dept_ai_platform 4, ...

# cost
tick_telemetry/day (ticks,tokens,cost): 10-07 140/1,679,470/0.1382 | 10-08 172/2,168,254/0.1780 | 10-09 167/2,101,145/0.1771 | 10-10 101/1,142,613/0.0939 | 10-11 152/1,784,042/0.1471 | 10-12 122/1,392,156/0.1147 | 10-13 163/1,973,010/0.1673 | 10-14 2/22,039/0.0018 ; 7d ~$1.02
model_usage/day (calls,tokens,cost): 10-07 1908/39,435,453/17.5348 | 10-08 2110/40,297,072/19.7343 | 10-09 1762/36,603,056/16.7934 | 10-10 1337/26,324,969/12.2591 | 10-11 1386/32,701,726/15.1986 | 10-12 1193/28,782,763/13.4434 | 10-13 2758/49,964,574/23.3229 | 10-14 99/1,800,044/0.8111 ; 7d ~$119.10
model_usage session_id: 12553 rows, 6060 with a session_id, 2079 distinct; values are 32-hex (e.g. 00061be3bd3703bf4db0c694f6dbc302); CAST-join to work_sessions.id matches 4 rows
turn counts from output_log: failed 2,310 (3.98/session), completed 831 (3.52/session), all 3,156
progress_checkpoints for 7d sessions: 3,156 rows, 745 distinct sessions, labels step_1..step_12
```

**TSVs / scripts produced (local seat only; the one-file rule forbids copying them to the authority):** `/home/zabz/audit-cf/ws7d.json`, `/home/zabz/audit-cf/ws7d.tsv` (824 rows, one line per session), `/home/zabz/audit-cf/blocked_tasks_classified.tsv` (237 rows), `/home/zabz/audit-cf/classify_work_sessions.py`.

**Honesty notes.** The `tasks` table has no event-time `blocked_at`; I used `created_at` as the age origin, which is the row's creation, not the moment it became blocked — ages are therefore lower bounds on block age. `tick_telemetry` and `model_usage` counts moved by 1–3 rows between the first and last read (the company was live); per-day tables are one read each. The effective 7-day window includes all of 2026-10-07 because of the `'T'`-vs-space comparison; a strict `>= '2026-10-07T01:01:52Z'` window gives 819 rows (577 failed / 234 completed / 8 paused), so the boundary contributes 5 sessions.
