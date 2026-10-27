# C — agent runtime: what can already react in seconds, what must be built, what breaks first

Research lane C, 2026-10-26. Host: **zabz-tech**. Read-only on every live system: no service was
started, stopped or changed; no message was sent; no credential value is printed.

All `file:line` citations are against the **deployed tree** `/opt/company` on `secratary-cloud`,
`git rev-parse --short HEAD` = **8f19ab373**, `company-api.service` active since
`Mon 2026-10-26 03:22:44 UTC`. The files were copied read-only to
`C:\Users\ezabz\ha-work\lane-c-src\` so line numbers could be read precisely; the copies are
byte-identical to the deployed files.

Two corrections to the brief, both measured:

* The design document is **not** at
  `harness-config/docs/security-and-evolution/ha-security/…`. It is at
  `C:\Users\ezabz\Code\ha-config\docs\security-system-design-2026-10-26.md` (991 lines). Round 5
  is lines 97-147, Round 7 lines 154-188.
* Round 7's autonomy claim (`app/services/autonomy.py` line 376, *"Unknown actions default to L4"*)
  is **stale**. The live file was replaced at 03:22 today and the unknown-action default is now
  **L1**. See finding 4.

---

## Findings

### 1. The existing event path: complete, unused, and broken at dispatch

#### 1.1 What writes it, what reads it, at what cadence

| Piece | Writes | Reads | Cadence |
|---|---|---|---|
| `events` table (`event_queue.py:117-135`) | only `POST /events` → `EventQueue.enqueue` (`main.py:10679-10703`) | only `autopilot._process_event_queue` (`autopilot.py:9210`) | drained every **30 s** by the reminder poll (`autopilot.py:9051`); also on a P0 wake (`autopilot.py:9206`) |
| `event_router.py` | nothing; writes `routing_log` (`:344-374`) | `_process_event_queue` (`autopilot.py:9228`) | per event |
| `job_queue` | router → `enqueue_job` (`autopilot.py:9320`) | `_process_work_queue` (`autopilot.py:4909`) | **1 job per 30 s poll**, 1 LLM step (`config.py:1149-1151`) |
| `ceo_wake.py` | `POST /events` when `priority <= 1` (`main.py:10708-10715`); two in-process callers (`self_diagnosis.py:204`, `main.py:22768`) | the autopilot loop's `wait_or_timeout(1.0)` (`autopilot.py:9200`) | event-driven, 1 s poll floor (`ceo_wake.py:183-209`) |
| `trigger_engine.py` | nothing; returns in-memory `TriggerEvent`s | `run_once` → `run_triggers` (`autopilot.py:8113`) | every autopilot tick |
| `trigger_goal_pipeline.py` | `goal_plans`, `trigger_dedup_log` | only the API endpoint `main.py:11019` (`process_trigger_event`) | on request only; **no autopilot caller** |
| `work_orders.py` | `work_order_executions`, goals | `process_standing_work_orders` (`work_orders.py:2382`) from `autopilot.py:7463`, `workforce.py:1982`, `main.py:10912` | lifecycle sweep interval **120 s** (`autopilot.py:11894`) |
| `agent_worker.py` | `tick_telemetry`, steps, goals | `workforce._run_worker_ticks` → `productive_tick` (`agent_worker.py:3982`) | company tick, `company_tick_every=2` |

The chain a Home-Assistant event would take:

```
POST /events (main.py:10679)
  -> events row (event_queue.py:117)
  -> ceo_wake.signal if priority<=1 (main.py:10710)   [<=1 s]
  -> autopilot._process_event_queue (autopilot.py:9210)
  -> EventRouter.route -> builtin rule ha_state_change/ha_alarm (event_router.py:108-124)
     action="ha_security_check", actor="dept_home_life", HA alarm priority_override=0
  -> _dispatch_routed_event -> enqueue_job (autopilot.py:9320)
  -> job_queue, ORDER BY priority DESC (database.py:9837)
  -> _process_work_queue -> run_assistant_chat(..., call_type="work_mode") (autopilot.py:5732)
```

**Where an agent turn actually starts.** There are two, and they are different code:

* Event/job path: `run_assistant_chat(...)` at **`autopilot.py:5732`**, inside
  `_process_work_queue` → work session. This is the turn an `ha_security_check` job would get.
* Department path: `agent_worker.productive_tick` at **`agent_worker.py:3982`**, which claims a
  step at `:4029` (`claim_next_step`, defined `:1355`) and calls `_execute_llm_step` (`:2612`).
  This is what `company_tick` runs.

#### 1.2 Measured latency

The event queue has **never processed an event**, so there is no event→agent latency to measure.
The only honest measurement is the path it feeds:

```
sqlite> SELECT COUNT(*) FROM events;                          -> 0
sqlite> SELECT COUNT(*) FROM routing_log;                     -> 0
sqlite> SELECT COUNT(*) FROM job_queue;                       -> 90870 (10 pending)
sqlite> SELECT COUNT(*) FROM tick_telemetry;                  -> 35970
```

Job-queue pickup wait, last 24 h (`picked_up_at - created_at`), n=347:

```
avg 6656.0 s   p50 6272.4 s (1 h 45 m)   p90 12860.9 s (3 h 34 m)   max 21940.6 s (6 h 06 m)
```

Agent-turn duration, last 24 h, n=373:

```
avg 23.8 s   median 10.7 s   min 1.5 s   max 2191.3 s (36 m 31 s)
```

373 turns in 24 h is **15.5 turns/hour — one turn every 3.9 minutes for the whole company**.

#### 1.3 The path is dead on arrival: a wrong keyword

`_dispatch_routed_event` calls `enqueue_job` with `task_type=`, but the function takes `job_type`:

```
app/autopilot.py:9320   enqueue_job(
app/autopilot.py:9322       task_type=action,
app/database.py:9638    def enqueue_job(db_url: str, job_type: str, ...)
```

Verified against the live interpreter:

```
$ /opt/company/.venv/bin/python -c "import inspect; from app.database import enqueue_job; print(inspect.signature(enqueue_job))"
(db_url: 'str', job_type: 'str', title: 'str' = '', payload: 'dict[str, Any] | None' = None,
 priority: 'int' = 5, agent_id: 'str' = 'orchestrator', max_retries: 'int' = 3) -> 'int'
```

`task_type` is not accepted. Crucially, the `TypeError` is swallowed **inside**
`_dispatch_routed_event` by its own broad `except` (`autopilot.py:9336-9343`, the line
`"Routed event dispatch failed for %s/%s"`), so the function returns normally and the caller then
executes `eq.complete(event["id"])` (`autopilot.py:9254`). **The event is recorded as `processed`,
no job is created, and the only trace is a `warning` line.** No retry, no dead-letter, no metric.
`git log -S "task_type=action"` dates the line to
`a7006f175 2026-03-23 audit remediation: local context, router wiring` — the path has been broken
since the day it was wired, seven months, and its failure mode is silent success.

#### 1.4 The second HA path is also dead

`trigger_engine._check_ha_security` exists (`trigger_engine.py:685-730`) and raises a priority-95
"Door unlocked at night" event. It reads `ctx.get("home_assistant", {})` (`:691`) and bails when
`doors` is empty (`:697-698`). The only caller builds the context as:

```
app/autopilot.py:8122   _trig_ctx: dict[str, Any] = {}
app/autopilot.py:8123   if world_ctx_text:
app/autopilot.py:8124       _trig_ctx["world_context"] = world_ctx_text[:4000]
app/autopilot.py:8125   _trig_ctx["tick"] = self._run_count
```

There is no `home_assistant` key, and `home_assistant` appears nowhere in `app/autopilot.py`
(`grep -c` = 0), so the rule returns `[]` on every tick. Independently, the downstream pipeline
would refuse it anyway: `trigger_goal_templates` has **0 rows**, and `process_trigger_event`
returns `{"action": "ignored", "reason": "no_template"}` (`trigger_goal_pipeline.py:162-163`).

So: the event queue is unused, its dispatch is broken, the trigger rule has no input, and the
pipeline has no templates. The "event path" in this company is scaffolding, not a runtime.

---

### 2. The wake loop: real, cron-driven, minutes-to-hours

**There is no wake systemd unit.** Verified on the authority:

```
$ systemctl list-units --all | grep -i wake
(no output)
$ crontab -l | grep -i wake
41 * * * *  wake-balance
7,37 * * * *  run-wake-sources
*/15 * * * *  wake-cost
* * * * *  wake-fanout          <- every minute
* * * * *  wake-lock-watch
```

The dispatcher is `/root/bin/wake-dispatch.sh` (82 KB), invoked by `wake-fanout.sh` every minute.
Its own header states the hop (`wake-dispatch.sh:8-12`):

```
scp prompt -> ZABZ-TECH:C:\Users\ezabz\bin\wake-prompt-<id>.txt
ssh ZABZ-TECH 'powershell -File ...\wake-run.ps1 ...'
     (the desktop runs `dsh --profile headless "<task>"`, answers, exits)
scp the out-file back
close the wake row
```

`TURN_CAP=1800` s, outer timeout `TURN_CAP+360` (`wake-dispatch.sh:114,118`).

**Measured end-to-end, `done` rows created in the last 3 days, n=112:**

```
p50 = 37.3 min      p90 = 308.4 min (5 h 08 m)
file -> claim p50 = 1.3 min
```

The claim is fast; the session and the caps are the slow part. All-time state counts:
`done 1187, failed 273, cancelled 93, dropped 16, new 7`.

**Failure mode, observed today** (`/root/.sms-inbox/wake-dispatch.log`):

```
2026-10-26T21:22:46Z released 2026-10-26 wake #1559 failed exit=1 runner_code=1 cost=none dur=521s
  outcome: ssh hop failed (rc=1) after 521s, but the session's out-file was recovered via scp
  ... Error: ENOENT: no such file or directory, open 'C:\...\dsh-subprocess-...-stdout.log'
```

The wake loop's real failure mode is **the desktop and the harness, not the authority**: the flag
is stored and claimed correctly, then the `ssh → powershell → dsh` hop fails, the row is closed
`failed`, and nothing retries it (`attempts` cap 2). At 21:22 today the fanout line was
`budget tier=conserve - cadence throttled to target=1 max=2`, and the budget file capped the day at
`max_per_day: 337`, `max_usd_per_day: 21.5733`, `cost_per_release_usd: 0.0639`.

The one already-always-on HA watcher is `ha-watch.py`, cron `7,37 * * * *` (every **30 min**), a
read-only probe that files a wake flag (`ha-watch.py` docstring; crontab line 251). Its measured
flag latency in the last 2 days is 2 rows, `avg 14.6 min`; add the ≤30 min detection delay.

`owner-ask.timer` runs every 30 min (`/etc/systemd/system/owner-ask.timer`, `OnUnitActiveSec=30min`).

---

### 3. Blocking constraints at 03:00

The brief's premises are two revisions stale in ways that matter.

#### 3.1 The tick is 15 minutes, not hourly — and measures ~10

```
$ tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value company-api)/environ | grep AUTOPILOT_INTERVAL
AUTOPILOT_INTERVAL_SEC=900
$ cat /opt/company/data/autopilot_state.json
"interval_sec": 900, "run_count": 106, "last_run_at": "2026-10-26T21:28:49Z"
$ systemctl show company-api -p ExecMainStartTimestamp
Mon 2026-10-26 03:22:44 UTC          (18.1 h up -> 106/18.1 h = 5.9 ticks/h = 10.2 min/tick)
```

So the company wakes on its own every ~10 minutes, not every hour. That is the *fastest* built-in
cadence, and it still misses every window a burglar uses.

#### 3.2 `SCHEDULE_MODE` is `cheap-first`, and the department you name decides the deferral

```
$ ... environ | grep SCHEDULE_MODE
SCHEDULE_MODE=cheap-first          # not "cheap"; MODES = legacy|cheap-first|cheap-only (schedule_policy.py:161)
```

The ladder (`app/services/schedule_priority.py`):

```
:92   PRIORITY_NEVER_DEFER = 0
:94   PRIORITY_FULL_BLOCK  = 2      # "defer for the whole peak block"
:215  "dept_home_life": PRIORITY_NEVER_DEFER,   # owner's home, alarms, family
:229  "dept_security":  PRIORITY_FULL_BLOCK,    # posture and credential sweeps
```

DeepSeek's peak is `01:00-04:00` and `06:00-10:00 UTC Mon-Fri` (`schedule_policy.py:22-23`).
**03:00 EDT = 07:00 UTC — inside the second peak block.** A security action run as `dept_security`
is FULL_BLOCK: deferred to the end of the block, up to **3 hours**. Run as `dept_home_life` it is
never deferred. This is the trap: the obvious name for the new department, `dept_security`, is the
one the scheduler parks at exactly the hour the owner cares about.

Scope limit: the ladder is consulted in exactly one place, `workforce.py:1670` (company_tick). The
job/work-queue path does **not** consult it, so a job is not deferred — it is simply not prioritized
(see 3.5).

#### 3.3 The per-day LLM budget

```
$ ... environ | grep -E "LLM_(DAILY|MONTHLY)"
LLM_DAILY_BUDGET_USD=40.0
LLM_MONTHLY_BUDGET_USD=1100.0

config.py:1270   llm_daily_budget_usd: float = 25.0      # overridden to 40 by env
config.py:1271   llm_monthly_budget_usd: float = 750.0  # overridden to 1100
llm_budget.py:35 DEFAULT_DAILY_LIMIT = 10.0
llm_budget.py:36 CEO_RESERVE_PCT = 0.20
llm_budget.py:37 AGENT_SOFT_CAP_MULTIPLIER = 2.0
budget_tiers.py:34-36  COMPANY_AUTO_CAP=50  STEP=10  HARD_CEILING=100
```

`check_budget` (`llm_budget.py:222`) is called before every work-mode turn
(`autopilot.py:5643-5648`) and before every productive tick (`agent_worker.py:4039-4045`). The
only unconditional bypass is **owner chat** (`llm_budget.py:251-252`). Global daily, rolling-24 h
(1.5×), per-agent soft cap and dept pool all raise `BudgetExceededError`
(`llm_budget.py:356,366,385,407`). Pressure bands: yellow 0.60, orange 0.80, red at ceiling
(`pressure.py:127-134`), and **at RED only P0 runs** (`pressure.py:13-14`).

A security job classifies **P1**: `classify_priority` defaults unknown autonomous work to P1
("safe default: protect it", `priority.py:125-127`), and `dept_home_life` is explicitly in
`_OPERATIONAL_AGENTS` (`priority.py:82-88`). P1 is blocked at RED and blocked by the global daily
limit. **No security event can bypass the budget.** It cannot even buy one turn at 03:00 if the
company spent $40 that day.

Per-agent circuit breaker (`cost_circuit_breaker.py`):

```
:35 DEFAULT_COOLDOWN_SEC = 1800
:36 MAX_COOLDOWN_SEC = 7200
:37 PROBES_TO_RESTORE = 3
:38 TICK_COST_CAP = 0.18          # max acceptable cost for ONE agent tick
:39 VELOCITY_LIMIT = 0.80         # max spend in a 5-minute window
:42 DUPLICATE_TOOL_LIMIT = 6
```

Measured turn cost is far below the cap — `tick_telemetry` rows today show `total_cost`
0.00137-0.00478 — so cost is not the binding constraint. **Availability of the queue is.**

#### 3.4 The approval gate is closed, and it is closed globally

```
$ ... environ | grep -E "^(UNSAFE_ACTIONS_ENABLED|HA_CALL_SERVICE_REQUIRES_APPROVAL)="
UNSAFE_ACTIONS_ENABLED=false
HA_CALL_SERVICE_REQUIRES_APPROVAL=true
```

```python
chat_action_home_assistant.py:15  def _ha_service_approval_required(settings):
:16      return (not bool(getattr(settings, "unsafe_actions_enabled", True))) and bool(
:17          getattr(settings, "ha_call_service_requires_approval", True))
:221     if _ha_service_approval_required(settings):
:222         return _ha_approval_result(...)   # creates an approval TASK, does not actuate
```

With the live values that expression is `True`. **Every `ha_call_service` and every buzz-in becomes
an approval task** (`_create_approval_task`, `:19-38`) instead of a siren, a lock, or a light. The
agent can read HA at L4 (`ha_security`, `ha_states`), and can decide, and then it cannot *do*
anything without a human. At 03:00 the human is asleep. This is the single most decisive blocker in
the whole report.

The refusal itself is well-behaved: `policy_refused: True` (`chat_action_policy.py:519-523`) is
recognised by `_is_policy_refusal` (`chat_action_runtime.py:345`) and deliberately kept out of the
retry loop and strike counter (`agent_worker.py:2360`). That is correct design — it just means the
refusal is quiet and final.

#### 3.5 Task ceiling

```
config.py:1121                     policy_active_task_ceiling: int = 300
task_protection.py:417-421         default = 60 measured consuming rows x 5 = 300
```

Live evidence, `tick_telemetry` id 35970 (2026-10-26T21:14:34Z), tool result:

```
Task creation blocked: 316 active tasks (ceiling 300). Close or complete existing tasks before creating new ones.
```

At any moment the company may be unable to create the task that records a security event. A
security lane must not depend on `create_task`.

#### 3.6 Does a security event bypass any of this? No.

A P0 HA alarm does get `priority_override=0` in the router (`event_router.py:116-124`). It signals
the wake (`main.py:10708-10715`, which wakes the 1-second sleep) **only if the POST body itself
carries `priority<=1`** — the signal is decided before routing, from `body.get("priority", 2)`.
A `state_change` posted at the default 2 gets no wake and waits for the 30 s poll. But then:

1. dispatch raises `TypeError` (1.3), so no job is created at all; and
2. even fixed, `enqueue_job` is passed `priority=route_result.priority` = **0**, and both claim
   paths order `priority DESC` (`database.py:9837,9790`), while ordinary task jobs are enqueued at
   5-8 (observed rows: `priority 6` and `8`). **P0 is the lowest rank in this queue.** The alarm
   job goes to the back of a queue whose measured p50 wait is 1 h 45 m.
3. even reached, `ha_call_service` is approval-gated (3.4).

So the router's "P0 critical" comment is inverted in practice. That inversion, not the tick
cadence, is what would make the first real intrusion arrive after the burglar has left.

---

### 4. Autonomy: the ladder, the matrix, and the stale Round-7 claim

Ladder (`autonomy.py:56-63`):

```
L0_SHADOW=0  log only, never execute
L1_SUGGEST=1 propose, require explicit approval
L2_APPROVE=2 execute after quick-approve
L3_ACT_UNDO=3 execute with cancel window (undo via delayed_executor)
L4_AUTONOMOUS=4 execute immediately
```

`max` on a row is a hard ceiling and `get_level` clamps every source to it
(`autonomy.py:25-29`, `ceiling_for` `:445`, `_clamp_to_ceiling` `:462`).

**UNKNOWN action, quoted (this is the line the design doc is wrong about):**

```python
autonomy.py:302   UNCLASSIFIED_ACTION_LEVEL: AutonomyLevel = AutonomyLevel.L1_SUGGEST

autonomy.py:616   # Nobody has classified this action: ask, do not act.
autonomy.py:618   # This branch used to return L4_AUTONOMOUS ("bias towards action"), which
autonomy.py:619   # meant any action the dispatcher gained ... executed immediately with no human
autonomy.py:621   # in the loop.  L1 (suggest) queues it for explicit owner approval instead.
autonomy.py:622   log.info("Autonomy: %r is unclassified; resolving to %s (fail-closed default)", ...)
autonomy.py:627   return UNCLASSIFIED_ACTION_LEVEL
```

Round 7 of the design doc says line 376 defaults to L4. That was true before the
`autonomy.py.bak-ceiling-20261026T032229Z` replacement; it is **not true now**. A security action
invented at runtime will be refused into an approval queue, not executed. That is the safe
direction, but it means the department cannot bootstrap itself by inventing tool names — every
action it needs must be pre-registered.

**What already exists in the matrix** (`CURATED_MATRIX`, `autonomy.py:90`):

```
:102  ha_status      max 4  default 4
:103  ha_states      max 4  default 4
:171  ha_call_service max 3 default 3
:172  ha_doors        max 3 default 3
:176      notes: "Door unlock is fine — act+undo window for safety"
:178  ha_climate      max 3 default 3
```

and generated: `ha_security` default 4 / max 4, policy `autonomous`, reason "read-only/investigative"
(`autonomy_matrix_generated.py:1154-1166`).

The current policy is **backwards for security**. It gives a 3-level, cancellable path to *unlock*
("act+undo window for safety", `:176`) and the same 3-level path to fire a siren; and it gives L4
only to reading. In a security system the additive, force-adding actions (siren, strobe, lock,
page) must be the autonomous ones, and the force-removing actions (silence, unlock, disable) must
be the restricted ones.

**Minimum set that must be explicitly registered, with level:**

| Action | Level | Why |
|---|---|---|
| `ha_security` (read doors/locks/presence) | **L4** — exists | no side effect outside the process |
| `ha_alarm_trigger` (siren/strobe) | **L4**, `max=4`, idempotent | additive force; must never wait for a human |
| `ha_alarm_silence` | **L0** (`max=0`) | removing force; credential/owner/timeout only |
| `ha_door_lock` (secure) | **L4** | additive force |
| `ha_door_unlock` | **L0/L1** | removing force; today it is L3 and described as "fine" |
| `security_page_owner` | **L4**, rate-limited, distinct from `send_sms` (L3, cancellable) | a page is not an SMS |
| `security_event_record` (decision row) | **L4** | internal bookkeeping, no task-ceiling dependency |
| `security_rule_propose` (L2 diff) | **L1** | may propose, never edit the envelope |

Registration mechanism: a hand-written row in `CURATED_MATRIX` (`autonomy.py:90`) **and**
regeneration of `GENERATED_MATRIX` via `app/services/autonomy_matrix_generator.py`; the generator
refuses a table whose restricted set disagrees with a curated row (`autonomy.py:258-262`). Do not
rely on `autonomy_levels` DB rows alone: a row for a name with no matrix entry is explicitly not a
classification (`autonomy.py:30-32,544-547`).

---

### 5. Concurrency and safety: one turn at a time, and a burst is fatal

**How many agent turns can run at once: one.**

```python
workforce.py:52  _WF_TICK_MAX_CONCURRENCY = max(1, int(os.environ.get("COMPANY_MAX_CONCURRENT_TICKS", "1")))
```

No such env var is set on the live process (`tr '\0' '\n' < /proc/.../environ | grep COMPANY_MAX` →
empty), so the default **1** applies. The comment above it is a measured OOM
(`workforce.py:55-63`): after the cap of 3 went live, "three departments ticked … anon-rss went from
~3.8 GB to 12.5 GB in 35 s and the kernel killed the process again". A memory-percentage gate
refuses new ticks near the cgroup limit (`:184`).

The work queue is a second serial lane inside the autopilot loop: `_process_work_queue` runs at
the 30 s poll with `max_runs=1, max_steps=1` (`autopilot.py:9402-9424`; `config.py:1149-1151`).

Measured throughput: 373 turns/24 h ≈ 15.5/h (`tick_telemetry`).

**A burst of 50 events in one minute.** Walk it with the constants:

* `POST /events` ×50 → 50 rows; each with `priority<=1` signals the same `threading.Event`
  (`ceo_wake.py:135-144`), whose pending deque holds 100 (`:97`).
* The loop wakes once, `_process_event_queue` claims **10** (`autopilot.py:9222-9223`). The other
  40 do not re-signal (the signal is only sent at POST time), so they wait for the 30-second
  reminder poll: 10 per 30 s → **~2.5 min** just to turn 50 events into 50 jobs.
* Each job then enters `job_queue`, `ORDER BY priority DESC`. If the events are P0-P3 they land
  **below** the existing task backlog (priority 5-8), whose p50 wait is 1 h 45 m.
* Execution is serial at 1 turn / 30 s poll. 50 turns × (10.7 s median + up to 30 s poll) is
  ≥ 34 min of pure turn time even with nothing else competing — and 50 turns is **13 % of the
  company's entire daily turn capacity**.
* No dedup by default: `dedup_key` is optional (`event_queue.py:77`), and the router does not
  synthesize one, so the same sensor tripping 50 times makes 50 jobs.

**The deadlock detector vs a retrying security agent.** `ToolLoopDeadlock` (`agent_worker.py:720`)
with limits read at `:734-778`: default **3 identical failures in 300 s**
(`router_deadlock_repeat_limit` / `..._window_sec`). On the third it stops attempting:

```
tick_telemetry id 35968 (2026-10-26T20:06:31Z):
[TOOL_LOOP_DEADLOCK: 'repo_search' failed identically 3/3 times for dept_engineering in the last
 300s (failure_class=not executed ... this is a policy refusal, not a failure ... )]
 0 calls attempted - another attempt is guaranteed to fail the same way and is not made
 (exit: a successful call to this tool, a tool this agent has not been failing on, or the loop
 window elapsing).
```

For a security agent this is a **fail-open hazard in the wrong direction**: if the first three
attempts to call `alarm_trigger` fail because HA is briefly unreachable, the detector classifies
the tool as dead and stops trying — exactly when persistence matters most. The same 3/300 s rule
governs LLM failures (`agent_worker.py:430-481`). A security lane needs its own retry policy
(bounded exponential backoff with a *longer* window, and a second channel), not the worker's
loop detector.

---

### 6. The smallest always-on security runtime

Facts that constrain the shape:

* One uvicorn process, no workers: `ExecStart=... uvicorn app.main:app --host 127.0.0.1 --port 8002`
  (`systemctl cat company-api`). The autopilot is a thread inside it (`main.py:546-560`).
* `/opt/company` is the **sole writer** of `/root/authority.db` (SQLite, WAL); a second process
  writing it would contend on the one writer lock. The estate already sees lock contention
  (the `ps_db_query` docstring records 3,322 "database is locked" journal events in 7 days,
  UNVERIFIED here beyond that note).
* Measured headroom right now: 8 cores, 31.3 GB RAM, 25.6 GB available, API RSS 1.64 GB, cgroup
  max 20 GB, disk 83 % with 38.5 GB free. The older "4-core / 15 GB / 91 % disk" warning in the
  estate skill is stale for this box, but the single-writer rule is not.
* HA client timeouts: connect 3 s, request 15 s, hard cap 25 s (`services/home_assistant.py:29-32`).
  A 5 s poll on a single thread cannot keep cadence if HA stalls; the consumer must be a loop with
  a deadline, not a `sleep`.
* Idle cost of an LLM-free poller is ~0. Measured LLM turn cost is **$0.00137-$0.00478**
  (`tick_telemetry`), i.e. a thousand security turns ≈ $1.4-$4.8. Cost is not the constraint.

**Shape: an in-process security consumer inside `company-api`, not a new daemon.**

```
company-api.service (existing)
├── FastAPI  POST /security/event        shared-secret HA webhook target, returns 202 in <5 ms
├── thread "security-consumer"           deque + deadline loop, NOT the autopilot loop
│     ├── deterministic pre-filter       (no model: door + away + no credential -> candidate)
│     ├── one model turn, hard 60 s      run_assistant_chat(call_type="security")
│     ├── action gate                    ha_alarm_trigger / ha_door_lock at L4; silence at L0
│     └── write security_events row      (never create_task; ceiling-independent)
├── heartbeat row every 15 s             security_runtime_heartbeat(ts, last_event, queue_depth)
└── supervisor: existing systemd Restart= + company-api-liveness.timer (every 2 min)

outside the process (must survive company-api death):
└── HA L0 envelope (deterministic, local)  <- the alarm does not depend on any of the above
```

Supervisor: `company-api.service` already restarts on failure, and `company-api-liveness.timer`
probes every 2 minutes and restarts a hung API (`systemctl list-timers`; unit description "Restart
company-api when it is ALIVE BUT NOT ANSWERING"). Heartbeat: a row plus a `/health` field, and a
`security-heartbeat.timer` (1 min) that files a wake flag only if the heartbeat is stale — the same
pattern as `ha-watch`, which is already proven.

What it costs when idle: one HA `GET /api/states` per 5 s (~17 k/day) on the existing HTTP client,
zero model calls, one small row per 15 s. Measured HA request ceiling 25 s; with a 5 s poll the
consumer is idle >99 % of the time.

**Why not a new systemd unit:** it would need to write `authority.db` (second writer, lock
contention) or keep its own store (a second source of truth about what happened). The company's
whole event/decision/audit model assumes one writer. If isolation is later required, the unit
should be read-only against the DB and POST to `company-api`, not write.

**Why not just an endpoint on company-api:** an endpoint alone is not always-on work — it only
runs when called. The always-on part is the consumer thread and its heartbeat. The endpoint is the
front door; the thread is the runtime.

---

## What already works

1. **A real interrupt, in-process.** `ceo_wake` genuinely wakes the autopilot loop within ~1 s of a
   P0 signal (`ceo_wake.py:135-144`, `autopilot.py:9200-9207`). The primitive exists; nothing
   external uses it.
2. **A durable, deduping queue with P0-P3 and backoff.** `event_queue.py` is competent code
   (`UPDATE … RETURNING` claim, dedup, dead-letter). It is unused, not inadequate.
3. **A two-tier router that already names HA.** `event_router.py:108-124` maps
   `home_assistant/state_change` and `home_assistant/alarm_triggered` to `ha_security_check` for
   `dept_home_life`, with P0 for the alarm. The policy is written; the wire is cut.
4. **The wake/flag/dispatch loop to the desktop.** It works end to end, with leases, caps, a
   heartbeat, a kill switch and a cost ceiling. Median 37 min — slow, but real and supervised.
5. **`ha-watch`.** Every 30 min, read-only, files a flag, dedupes by stable subject, writes
   history. The correct pattern for "detect and escalate" already exists.
6. **HA read tools and an HA client.** `ha_status/ha_states/ha_entity/ha_security` at L4, with
   timeouts and a security summary (`chat_action_home_assistant.py:45-403`,
   `services/home_assistant.py:882-910`).
7. **Per-agent cost breaker and loop detectors.** `cost_circuit_breaker.py` and the
   `TOOL_LOOP_DEADLOCK` verdict are exactly the guardrails a new runtime should reuse.
8. **A fail-closed autonomy default.** Since today, an unregistered action resolves to L1
   (`autonomy.py:302`), not L4.

## What must be built

1. **An always-on consumer at seconds cadence.** Nothing today runs an agent turn on an external
   event; the fastest built-in cadence is the ~10 min tick.
2. **A security priority lane that is above task work**, or the `priority DESC` inversion
   (`database.py:9837`) will keep putting P0 alarms last. Either invert the rubric (P0 highest
   number) or give security its own table/lane and drain it first.
3. **A per-action approval policy.** `UNSAFE_ACTIONS_ENABLED=false` is correct as a default, but a
   global boolean cannot express "siren yes, unlock no". The gate must move from the global flag to
   the autonomy row (`ha_call_service` L3 + `ha_call_service_requires_approval` is too coarse).
4. **A security department id placed correctly in both ladders**: `PRIORITY_NEVER_DEFER` in
   `schedule_priority.py` (not `PRIORITY_FULL_BLOCK`) and **P0** in `priority.py` (not the P1
   default), otherwise 03:00 and RED both stop it.
5. **Registered security actions at the levels in finding 4**, and the inverse rule for
   force-removing actions.
6. **A security budget reservation** that is not the dept pool: one turn per event, hard-capped,
   exempt from the $40 global stop — or the whole lane dies on a busy spending day.
7. **A heartbeat and an out-of-process dead-man** that survives `company-api` dying. HA L0 is that
   dead-man; the company must never be the only path.
8. **Either fix and feed the trigger rule or delete it.** `_check_ha_security` needs a real
   `home_assistant` context (`autopilot.py:8122-8125`) and a `trigger_goal_templates` row; today it
   is unreachable code that makes the system look like it has HA detection when it does not.
9. **A security-specific retry policy**, not the worker's 3-failures/300 s
   `TOOL_LOOP_DEADLOCK`.

## Recommendation

**Do not put the alarm in the company. Put the *judgement* there, behind a lane that can actually
run at 03:00.** The measured facts force a three-phase order:

**Phase 0 — keep L0 in Home Assistant (no company code).** The six deterministic rules in design
doc R5 (lines 128-134) are the only thing that works with the network down. The company's job is to
corroborate and escalate, never to be the sole force. Nothing in this report changes that; this
report is why it is not optional.

**Phase 1 — the smallest runtime that can act in <60 s (build this first).**
An in-process `security-consumer` thread in `company-api` with: a `POST /security/event` endpoint
(shared secret, 202 in <5 ms), a deterministic pre-filter, one model turn with a hard 60 s deadline
and a capped security budget, an L4 path for `ha_alarm_trigger`/`ha_door_lock`, a heartbeat row
every 15 s, and a 1-minute heartbeat-stale checker that files a wake flag. It bypasses
`job_queue` entirely. It must not call `create_task` (ceiling 300, already hit at 316).

Why in-process: one SQLite writer, one supervisor, no new unit to keep alive, and the existing
`company-api-liveness.timer` already restarts a hung API every 2 minutes.

**Phase 2 — make the company's answer trustworthy.**
Fix the `task_type`/`job_type` dispatch bug (`autopilot.py:9322`) and the `priority DESC`
inversion, register the eight actions, set the security agent to never-defer/P0, split the
approval gate per action, and give the security lane its own capped spend. Feed the trigger engine
a real `home_assistant` context or delete the rule.

**Phase 3 — L2 learning, nightly.** As designed in R5/R7: replay against labelled history, propose
thresholds, promote only with a passing replay and an owner-visible diff. This is where the
"gets better over time" claim is actually earned, and it is the least latency-sensitive part — it
can run on the existing ~10 min tick or a nightly goal.

**The number to design against is not 10 minutes.** It is the measured **p50 1 h 45 m** wait in
`job_queue` and **p50 37 min** on the wake path. A security lane that inherits either is a
post-incident reporter. Phase 1 exists to give the department a path that inherits neither.

---

## UNVERIFIED / what would settle it

| Claim | Why unverified | What would settle it |
|---|---|---|
| HA is not configured to POST `/events` | The HA side was out of scope for this lane; 0 rows is consistent with "never called" but also with "called and dead-lettered" (no, dead rows would exist) | `grep -r "company\|/events"` in the HA config; one synthetic POST to a scratch DB |
| Exact 03:00 behaviour of `decide_priority` for a new agent id | I read the ladder and the peak book but did not execute `decide_priority("dept_security", at="2026-10-27T07:00:00Z")` (it would count a deferral/`record=True`) | run it with `record=False` in a scratch process |
| Whether `company-api` currently exceeds the 300-task ceiling at any given minute | The 316 observation is one tick at 21:14Z | `SELECT COUNT(*) FROM tasks WHERE status IN ('open','in_progress','pending','todo')` on a schedule |
| The real source of the ~10.2 min tick vs configured 900 s | `run_count/uptime` and log gaps; I did not instrument the loop | log `run_once` entry/exit timestamps for an hour |
| Whether a second process writing `authority.db` would in fact fail | Not tested (would be a live write); the single-writer claim is from the schema/MCP note | a read-only test DB copy with two writers |
| The wake p50/p90 is for `done` rows; `failed` rows may be faster or slower | Failures are excluded from the percentile | include `failed` with `finished_at` and report both |
