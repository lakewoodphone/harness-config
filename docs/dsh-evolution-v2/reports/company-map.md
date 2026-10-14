# company-map — the AI company on `secratary-cloud`, described

HOST: ZABZ-TECH
READ: `docs/mesh/000-SYSTEMS-REGISTER.md` (all 129 lines) · `docs/dsh-evolution/30-systems-and-autonomy-audit.md` (all 177 lines, recovered from git object `75ffbeef` — see the note below) · `docs/dsh-evolution-v2/PROGRAM.md` (**not found in any ref or on any host**; see WHAT I COULD NOT DETERMINE).

**Node contract compliance.** `ssh -o BatchMode=yes -o ConnectTimeout=8 secratary-cloud 'hostname'` printed `secratary-cloud` (exit 0). All authority work was read-only. The single permitted write was `/home/zabz/evolution-corpus-v2/reports/company-map.md`. Nothing was written to any git repository. No builds, no test suites, no browsers, no `PRAGMA integrity_check`, no `VACUUM`, no `dbstat`, no scan of `dsh_session_events` beyond `COUNT(*)`.

**The baseline document the brief names does not exist where the brief says it does.** `C:\Users\ezabz\code\harness-config\docs\dsh-evolution\` and `docs\dsh-evolution-v2\` are absent from the working tree (branch `mesh/broker-host-cloud-default-20261013`) *and* from `/root/code/harness-config/docs/` on the authority. `30-systems-and-autonomy-audit.md` was recovered with `git show 75ffbeef:docs/dsh-evolution/30-systems-and-autonomy-audit.md`. `PROGRAM.md` exists only at `docs/dsh-evolution/PROGRAM.md` in that same commit; the v2 path exists in **no** ref (`git log --all --diff-filter=A -- "docs/dsh-evolution-v2/*"` → empty).

**Posture.** Authority = `secratary-cloud` (tailnet `100.73.176.126`), root@. `/opt/company` git HEAD = `db07e8e023d2f2720ccfa6b76b76bc99f08af414` ("docs(cfo): map the 51 modified files in the live checkout…", 2026-10-14 00:28:56 +0000). `/root/authority.db` = **26,783,068,160 bytes** (24.94 GiB). Disk `/` = 75 G total, 68 G used, **4.1 G free, 95%** (`df -h /`). 2 vCPU. `sqlite3` 3.46.1. `app/` holds **323** `.py` modules; `app/services/` holds **257**.

**Measurement window.** All live numbers were read 2026-10-14 between 01:00Z and 01:15Z unless stated. `[M]` = measured by me on the live system today. `[DOC]` = a documentation claim I did not reproduce.

---

## 1. The organization

### 1.1 Declared — what the code says the company is

`app/company_blueprint.py` (1,978 lines) is the declaration.

| what | where | measured |
|---|---|---|
| `DEPARTMENTS: list[Department]` | `app/company_blueprint.py:164` | **28** literal entries (AST parse of the list literal) |
| board seats appended at import | `_board_agents()` `:1144`, called by `_extend_department_hierarchy()` `:1215`, invoked at `:1223` | **+3** → runtime `DEPARTMENTS` = **31** |
| ladder agents | `_department_ladder_agents()` `:1203` | returns `[]` — the docstring says 56 `floor_manager/reviewer/clerk/indexer` agents were **removed** |
| core department ids | `CORE_DEPARTMENT_IDS` `:1116` | **14** |
| board ids | `FRONTIER_BOARD_AGENT_IDS` `:1133` | 3: `frontier_strategy_board`, `frontier_risk_board`, `frontier_capital_board` |
| always-on bottom layer | `ALWAYS_ON_BOTTOM_LAYER_AGENT_IDS` `:1225` | **`[]`** — it filters `hierarchy_layer in {clerk,indexer,scout}` and no declared department carries those layers any more |
| agent record fields | `class Department(TypedDict)` `:36-54` | `agent_id, name, role, reports_to, hierarchy_layer, cost_tier, model_tier, decision_scope, review_gate, mission, focus_areas, repos, kpis, standing_orders` |
| reporting tree | `build_org_hierarchy()` `:1738` | parent→children from `reports_to`, **defaulting to `"orchestrator"`** |

The 14 core departments (`:1116`) with what each is for (name and first focus areas, `:166-1115`):

| agent_id | name | reports_to | layer | cost/model tier | focus (abridged) |
|---|---|---|---|---|---|
| `dept_business_ops` | Business Operations | *(unset → orchestrator)* | vp | smart/smart | work_orders, inventory_management, customer_service, shop_operations, pricing |
| `dept_finance` | Finance & Accounting | *(unset → orchestrator)* | vp | frontier_reviewed/smart | cash_and_debt_state, source_registry_freshness, quickbooks_automation, processor_reconciliation, tax_preparation |
| `dept_engineering` | Engineering | *(unset → orchestrator)* | vp | smart/smart | software_development, code_review, deployments, ci_cd, architecture |
| `dept_research` | Research & Intelligence | *(unset → orchestrator)* | vp | smart/smart | market_research, computer_sourcing, technology_evaluation, competitive_intelligence |
| `dept_home_life` | Home & Personal Life | *(unset → orchestrator)* | — | — | home_automation, personal_routines, reminders, health_wellness |
| `dept_world_index` | World Index & Continuity | *(unset → orchestrator)* | — | — | world_indexing, context_freshness, vscode_chat_ingestion, memory_continuity |
| `dept_systems_custody` | Systems Custody & Remote Operations | *(unset → orchestrator)* | — | — | repo_inventory, worktree_hygiene, remote_desktop_access, machine_state |
| `dept_scheduling` | Scheduling & Commitments | *(unset → orchestrator)* | — | — | calendar_management, commitment_extraction, prep_packets, follow_up_tracking |
| `dept_comms_relationships` | Communications & Relationships | *(unset → orchestrator)* | — | — | twilio_cutover, dialpad_business_sms, email_hubs, relationship_memory |
| `dept_ai_platform` | AI Platform | *(unset → orchestrator)* | vp | smart/smart | vscode_ai_gateway, provider_routing, cost_telemetry, golden_evals |
| `dept_evolution_reliability` | Evolution & Reliability | *(unset → orchestrator)* | — | — | anti_stagnation, self_improvement, reliability_scorecards, autonomy_evidence |
| `dept_devices` | Device Operations | *(unset → orchestrator)* | — | — | phone_flipping, device_setup, kyocera_management, firmware_operations |
| `dept_creativity` | Creativity & Opportunity | *(unset → orchestrator)* | — | — | opportunity_identification, business_innovation, cross_domain_insight_generation |
| `dept_mashgiach` | Mashgiach Quality & Audit | *(unset → orchestrator)* | — | — | department_compliance_auditing, agent_drift_detection, task_closure_evidence_review, weekly_scorecard |

Sub-department agents declared with an explicit `reports_to` (14 more): `finance_controller`, `finance_source_steward`, `finance_reconciliation_lead`, `finance_accountant`, `finance_bookkeeper` → `dept_finance`; `evolution_architect`, `reliability_verifier` → `dept_evolution_reliability`; `platform_routing_engineer`, `platform_extension_engineer`, `gateway_cost_analyst`, `model_ops_evaluator` → `dept_ai_platform`; `creativity_scout`, `proposal_evaluator`, `cross_domain_synthesizer` → `dept_creativity`. The 3 board seats report to `orchestrator`, `hierarchy_layer="board"`, `cost_tier="frontier"`, and their `review_gate` is *"Reviews synthesized packets only; raw low-level output must be filtered first."*

### 1.2 Running — where agents actually live, and which of them do anything

**Agents are not in a database table.** There is no `agents` table (`sqlite3 -readonly /root/authority.db ".schema agents"` → no such table; `SELECT name FROM sqlite_master WHERE name LIKE '%agent%'` returns only `agent_budgets, agent_metrics, agent_questions, agent_reflections, agent_routing_rules, agent_rules, agent_working_memory` plus `blocked_agents`, `chat_agent_review_*`).

The workforce store is a **JSON file**:
- `app/workforce.py:45` `_store_path()` → `settings.identity_store_path`
- `app/config.py:946` `identity_store_path: str = "data/agent_identities.json"`
- live file `/opt/company/data/agent_identities.json`, **13,988,406 bytes**, mtime **2026-10-14T00:59Z** [M]

**126 agent records** [M], in two tables:

| status | n |
|---|---|
| `active` | **31** |
| `deactivated` | **89** |
| `null` (key absent) | **6** |

Every agent record's `hierarchy.layer` is `None` (measured: `collections.Counter` over `hierarchy.layer` and `hierarchy_layer` → `{None: 126}`), so `ALWAYS_ON_BOTTOM_LAYER_AGENT_IDS` is empty at runtime too, not just in the literal.

The live tree under `orchestrator` (depth ≤ 3) [M]: 17 `active` children and 2 `deactivated` (`dept_communications`, `dept_operations`). The 14 core departments are all `active`; every `*_floor_manager` / `*_reviewer` / `*_clerk` / `*_indexer` reported under them is `deactivated`. Four ids in the store are **not in the blueprint at all**: `dept_communications`, `dept_operations`, `dept_security`, `dept_self_improve`.

There are **37 records with no `hierarchy.parent_agent_id`** [M], including `ceo`, `vp`, `owner`, `primary`, `status`, `test-agent`, `postoutage_probe`, `dept_security`, `dept_self_improve`, `dept_self_improve`, both `lakewoodphoneandtech,repo:*` records, and a whole orphaned family of `orchestrator-child-01…10` trees. `ceo` and `vp` have `status: null`.

### 1.3 Declared vs running — the distinction, measured

| claimed | evidence | verdict |
|---|---|---|
| "an `orchestrator` agent is the only agent that actually runs work sessions" | `work_sessions`: **78,566** rows, **11** distinct `agent_id`; **78,513 = `orchestrator` (99.93%)**; last 7 days = **824 sessions, all `orchestrator`** [M] | **confirmed** |
| departments run work | `work_sessions` by agent, all time: `dept_engineering` 3, `dept_business_ops` 2, `dept_devices` 2, `orchestrator-child-0x` 5, plus 4 junk ids (`2026-06-27` 39 rows, `owner`, `lakewoodphone,repo:quickbooks-agent`) [M] | departments have run **7** sessions ever |
| agents are ticked | `tick_telemetry`: **34,213** rows, **85** distinct `agent_id`, span 2026-03-06T20:00Z → 2026-10-14T00:43Z [M] | 85 ids have *ever* ticked |
| agents are ticked **now** | last 24 h: **165** rows over **17** distinct agents — `dept_finance` 28, `dept_business_ops` 25, `dept_scheduling` 19, `dept_engineering` 15, `dept_world_index` 14, `model_ops_evaluator` 14, `dept_home_life` 13, `dept_ai_platform` 8, `dept_comms_relationships` 6, `dept_evolution_reliability` 6, `evolution_architect` 5, `dept_systems_custody` 3, `dept_devices` 2, `dept_research` 2, `finance_source_steward` 2, `orchestrator` 2, `dept_mashgiach` 1 [M] — outcomes: complete 142, error 11, suspended 8, escalate 4 [M] | **17 of 126 agents did anything in 24 h**; **none of the 89 `deactivated` and neither of the 3 board seats appear** |
| the task board is used | `tasks`: **28,513** rows, **71** distinct `agent_id`, **114** distinct `assigned_to` [M] | — |
| — by status | done **28,099**, blocked 237, closed 56, cancelled 32, open **29**, in_progress 28, completed 27, in-progress 2, paused 1, pending 1, todo 1 [M] | the status vocabulary is **inconsistent**: `done` vs `completed`, `in_progress` vs `in-progress` |
| — open work by owner | open tasks: `orchestrator` 12, `dept_finance` 6, `reconciliation` 3, `dept_devices` 2, `dept_business_ops` 2, then 1 each for `dept_world_index`, `dept_scheduling`, `dept_mashgiach`, `dept_engineering` [M] | |
| standing work orders | `standing_work_orders`: **34** rows, **24** `is_enabled=1`; `last_run_status`: success 16, failed **9**, skipped 9 [M]. Departments: `dept_business_ops` 5, `dept_engineering` 5 (**0 enabled**), `orchestrator` 4, `dept_ai_platform` 3, `dept_finance` 3, … [M] | 10 of 34 are disabled; 9 are sitting in `failed` |
| work-order execution | `work_order_executions`: **11,483** rows, 2026-03-06 → 2026-10-14T00:43Z; **failed 7,159 / success 2,758 / skipped 1,566** [M] | 62% of executions are recorded `failed` |
| goals | `goal_plans` **35,652** (failed **17,617**, completed 14,562, cancelled 3,463, active **10**); `goal_steps` **47,812** (skipped 29,714, completed 18,014, failed 75, pending 7, running **2**) [M] | |
| missions | `missions` **3** rows, all `active` [M] | |
| jobs | `job_queue` **87,135** rows: completed 86,128, failed 1,007 [M] | |
| owner queue | `owner_decision_queue` **493** rows: resolved 229, **pending 155**, dismissed 71, answered 38 [M] | |
| questions agents asked | `agent_questions` **532** rows; `blocked_agents` **0** rows [M] | |

**Who reports to whom** (declared, and the store agrees for the active set): `orchestrator` is the root; the 14 core departments and the 3 board seats are its direct children; the 14 specialist agents report to their department head. `build_org_hierarchy()` (`app/company_blueprint.py:1738`) is the single builder, and `_append_org_hierarchy_lines()` (`:1753`) renders it into the prompt, so the model is told the tree as well as being bound by it. At runtime the store's tree is the truth and it is **narrower** than the declaration: the whole ladder tier exists in the declaration's DNA (`_department_ladder_agents`) only as a function that returns `[]`.

---

## 2. The control loop, end to end

### 2.1 What triggers a tick

| trigger | file:line | detail |
|---|---|---|
| first boot, no state file | `app/main.py:1224` | `autopilot.enable(interval_sec=settings.autopilot_interval_sec, run_now=False)` — **only** when `autopilot_default_enabled` is true **and** `data/autopilot_state.json` does not exist **and** the controller is not already enabled |
| `POST /autopilot/enable` | `app/main.py:15944` | body `AutopilotEnableInput{enabled, interval_sec, run_now}` |
| `POST /autopilot/restart` | `app/main.py:15957` | `stop()` → sleep 1 s → `start_thread()` → `enable()` |
| `POST /autopilot/run-once` | `app/main.py:15968` | `run_once(reason="manual_run_once")` |
| thread start | `app/autopilot.py:2417 enable()` → `:2372 start_thread()` → `:6922 _loop()` | daemon thread named `autopilot`; `start_thread` force-restarts a thread whose `last_run_at` is > 1 h stale |
| service | `/etc/systemd/system/company-api.service` | `ExecStart=…/uvicorn app.main:app --host 127.0.0.1 --port 8002 --proxy-headers --forwarded-allow-ips=127.0.0.1`; drop-in `10-timeouts.conf` sets `TimeoutStartSec=600`, `TimeoutStopSec=180`; `MemoryMax=infinity` |

**Interval.** `AUTOPILOT_INTERVAL_SEC=900` (`/opt/company/.env:133`); live state carries `interval_sec = 900` [M]. First tick is delayed 5 s (`app/autopilot.py:6952`). `AUTOPILOT_COMPANY_TICK_EVERY=2`, `AUTOPILOT_EVOLUTION_EVERY=6`, `AUTOPILOT_OPTIMIZE_EVERY=12`, `AUTOPILOT_CEO_TICK_EVERY=1`, `AUTOPILOT_LLM_CHECKIN_EVERY=1`, `AUTOPILOT_WORLD_CONTEXT_EVERY=1`, `AUTOPILOT_SKIP_BOOTSTRAP=true`, `AUTOPILOT_MAX_AGENTS_PER_TICK=20` (`.env:183-236, 416-419`).

**Live controller state** (`/opt/company/data/autopilot_state.json`) [M]: `enabled=true`, `interval_sec=900`, `run_count=87`, `consecutive_failures=0`, `last_error=null`, `crash_count=0`, `last_run_at=2026-10-14T00:59:27.666130+00:00`, `last_checkin_state_hash=3594db6a…`, `event_push_sources` = `{dialpad_sms, dialpad_call, twilio_sms, lpt_website, …}`.

**Re-entrancy.** `run_once` refuses to start if `self._run_once_active` (`app/autopilot.py:5362`), and the flag is released in a `finally` (comment at `:1537` records that before 2026-09-20 it was released only on the success path, which latched 5 timeouts / 0 completions in 6 hours).

### 2.2 What the tick does, in order

`run_once` is `app/autopilot.py:5356`–`:6921` (1,566 lines). Order of work, with the banner line and the `_record_subsystem` call that names each subsystem:

| # | step | banner / call line | subsystem recorded |
|---|---|---|---|
| 0 | `refresh_config_from_settings()` | 5384 | — |
| 0 | `_do_proactive_tasks()` | 5390 | — |
| 0 | `_apply_budget_guardrails(proactive_actions)` | 5392 | — |
| 1 | World context (calendar / email / home / finance) | banner 5394 | `world_context` (5488 ok / 5494 fail) |
| 2 | World index pass | banner 5500, `_run_world_index_pass` 5324 | `world_index` (5512/5519) |
| 3 | Calendar reminders (opt-in) | banner 5525 | — (own scheduler `_maybe_send_calendar_reminders` `:11072`) |
| 4 | Email catalog sync | banner 5534, `_maybe_sync_email_catalog` `:10564` | `email_catalog` (call site 10635) |
| 5 | Owner-attention sweep | banner 5545, `_maybe_run_owner_attention_sweep` `:10638` | `owner_attention_sweep` (10759) |
| 6 | Gmail decision queue (opt-in) | banner 5558, `_maybe_poll_gmail_decision_queue` `:10762` | `gmail_decisions` |
| 7 | Google Voice secretary (opt-in) | banner 5567, `_maybe_run_google_voice_secretary` `:10950` | `google_voice_secretary` (11017) |
| 8 | Work mode — process queued jobs | banner 5575, `_process_work_queue` `:3440` | `work_mode` (5582/5591) |
| 9 | **Company-wide tick** | banner 5597, `run_once` 5660 | `company` (5688/5694) |
| 10 | Evolution cycle | banner 5710 | `evolution` (5730/5737) |
| 11 | Self-healing sweep | banner 5791 | `healing` (5815) |
| 12 | Mashgiach daily scan | banner 5822 | `mashgiach` (5836) |
| 13 | Initiative cycle | banner 5840 | `initiative` (5869) |
| 14 | Creativity scanner | banner 5873 | `creativity_scan` (5887) |
| 15 | Ambient bottom layer | banner 5891 | `ambient_bottom_layer` (5908/5914) |
| 16 | Manager review packets | banner 5916 | `hierarchy_manager_reviews` (5933/5939) |
| 17 | Frontier board packets | banner 5941 | `frontier_board_packets` (5958/5964) |
| 18 | Company evolution portfolio | banner 5966 | `company_evolution` (5985/5991) |
| 19 | CEO weekly strategy synthesis | banner 5993 | `weekly_strategy` (6025/6028) |
| 20 | Self-programming cycle | banner 6034 | `self_prog` (6083/6092) |
| 21 | Fleet location poll | banner 6098 | `fleet_location_poll` (6131/6141) |
| 22 | Self-audit | banner 6147 | `self_audit` (6172/6179) |
| 23 | Self-improvement cycle | banner 6185 | `self_improvement` (6236/6243) |
| 24 | Trigger engine / proactive event detection | banner 6249 | — |
| 25 | Advance active goals | banner 6316 | — |
| 26 | Proactive synthesis | banner 6330 | `proactive_synthesis` (6352/6365) |
| 27 | Rule consolidation | banner 6371 | `rule_consolidation` (6394/6404) |
| 28 | Shadow learning | banner 6410 | `shadow_learning` (6433/6440) |
| 29 | CEO autonomous tick | banner 6446 | `ceo_tick` (6461/6470) |
| 30 | LLM check-in, incl. the multi-turn action execution loop | banner 6476 | `llm_checkin` (6530/6574/6588) |
| 31 | Success — reset failure tracking, `_save_state()` | 6847 / 6879 | — |

Two subsystems run on their own clocks, both invoked from `_maybe_*` helpers inside the tick: `work_mode_poll` (`_maybe_poll_work_queue_fast` `:7520`) and `financial_alert_sweep` (`_maybe_run_financial_alert_sweep` `:9717`, default interval 3600 s at `:9732`). `_retire_absent_subsystems()` (`:1388`, delegating to `app/services/subsystem_presence.py`) deletes health entries for subsystems not installed on this host, and `_record_subsystem` refuses to record a failure for an absent subsystem (`:1441`).

### 2.3 The 39 subsystems, by name, with live state

`data/autopilot_state.json` → `subsystem_health` contains exactly **39** keys [M]. `[M]` = read at 2026-10-14T01:0xZ.

| subsystem | ok | fail | consec | last_status | last_ran_at |
|---|---:|---:|---:|---|---|
| `activity_sync` | 2752 | 0 | 0 | ok | 2026-10-14T00:58:11Z |
| `amazon_sync` | 23 | 50 | **3** | **failed** | 2026-10-13T04:00:23Z |
| `ambient_bottom_layer` | 5373 | 0 | 0 | ok | 2026-10-14T00:44:15Z |
| `balance_capture` | 0 | 2 | 0 | **disabled_superseded** | 2026-08-04T17:43:35Z |
| `boa_sync` | 0 | 114 | 0 | **disabled_superseded** | 2026-07-21T03:00:37Z |
| `ceo_tick` | 8162 | 1 | 0 | ok | 2026-10-14T00:44:24Z |
| `company` | 6792 | 151 | 0 | ok | 2026-10-14T00:44:08Z |
| `company_evolution` | 1936 | 36 | 0 | ok | 2026-10-14T00:44:15Z |
| `creativity_scan` | 1127 | 0 | 0 | ok | 2026-10-13T22:12:42Z |
| `ebay_sync` | 25 | 50 | **3** | **failed** | 2026-10-13T04:20:07Z |
| `email_catalog` | 335 | 0 | 0 | ok | 2026-10-14T00:33:44Z |
| `evolution` | 1019 | 98 | 0 | ok | 2026-10-14T00:44:09Z |
| `financial_alert_sweep` | 2911 | 0 | 0 | ok | 2026-10-14T00:55:35Z |
| `fleet_location_poll` | 9347 | 592 | **414** | **failed** | **2026-09-29T03:44:44Z** |
| `frontier_board_packets` | 1122 | 19 | 0 | ok | 2026-10-13T22:12:42Z |
| `gmail_decisions` | 1827 | 3 | 0 | ok | 2026-10-14T00:43:33Z |
| `google_voice_secretary` | 14414 | 0 | 0 | ok | **2026-10-05T03:33:45Z** |
| `healing` | 6100 | 129 | 0 | ok | 2026-10-14T00:44:15Z |
| `hierarchy_manager_reviews` | 2764 | 56 | 0 | ok | 2026-10-13T23:19:17Z |
| `initiative` | 1394 | 0 | 0 | ok | 2026-10-13T18:55:58Z |
| `llm_checkin` | 22496 | 0 | 0 | ok | 2026-10-14T00:59:38Z |
| `mashgiach` | 2005 | 51 | 0 | ok | 2026-10-14T00:44:15Z |
| `memory_consolidation` | 443 | 0 | 0 | ok | 2026-10-13T21:53:18Z |
| `owner_attention_sweep` | 345 | 0 | 0 | ok | 2026-10-14T00:33:56Z |
| `paypal_sync` | 38 | 42 | 0 | ok | 2026-10-13T03:45:15Z |
| `plaid_sync` | 70 | 7 | 0 | ok | 2026-10-13T04:30:25Z |
| `proactive_synthesis` | 7597 | 1 | 0 | ok | 2026-10-14T00:44:16Z |
| `receipt_sync` | 77 | 0 | 0 | ok | 2026-10-13T04:45:38Z |
| `rule_consolidation` | 838 | 0 | 0 | ok | 2026-10-13T22:12:43Z |
| `self_audit` | 5474 | 116 | 0 | ok | 2026-10-14T00:44:15Z |
| `self_improvement` | 1749 | 45 | 0 | ok | 2026-10-14T00:44:15Z |
| `self_prog` | 3134 | 0 | 0 | ok | 2026-10-13T23:19:18Z |
| `shadow_learning` | 5589 | 0 | 0 | ok | 2026-10-14T00:44:24Z |
| `spending_report` | 0 | 38 | 0 | **disabled_superseded** | 2026-09-03T05:30:51Z |
| `weekly_strategy` | 72 | 0 | 0 | ok | 2026-10-11T15:23:14Z |
| `work_mode` | 8364 | 168 | 0 | ok | 2026-10-14T00:43:33Z |
| `work_mode_poll` | **235852** | 0 | 0 | ok | 2026-10-14T00:59:11Z |
| `world_context` | 8016 | 23 | 0 | ok | 2026-10-14T00:42:53Z |
| `world_index` | 2077 | 150 | 0 | ok | 2026-10-14T00:33:16Z |

Ticks actually completed, per day (from `tick_telemetry`) [M]:

| day | ticks | complete | error | steps | tokens | cost $ |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-14 (partial) | 2 | 2 | 0 | 2 | 22,039 | 0.0018 |
| 2026-10-13 | 163 | 140 | 11 | 140 | 1,973,010 | 0.1673 |
| 2026-10-12 | 122 | 109 | 9 | 109 | 1,392,156 | 0.1147 |
| 2026-10-11 | 152 | 119 | 23 | 119 | 1,784,042 | 0.1471 |
| 2026-10-10 | 101 | 91 | 5 | 91 | 1,142,613 | 0.0939 |
| 2026-10-09 | 167 | 158 | 1 | 158 | 2,101,145 | 0.1771 |
| 2026-10-08 | 172 | 161 | 5 | 161 | 2,168,254 | 0.1780 |

`anomaly_log` holds **537** rows total (2026-04-21 → 2026-10-13T10:29:38Z) [M]: `comms_capture_stale` 504 (294 escalated as `owner_message_queued`, 210 `logged_only`), `hollow_workflow` 25 (newest 2026-07-02), `velocity_spike` 7, `runaway_loop` 1. Note `detected_at` is the timestamp column — there is no `created_at` on this table.

### 2.4 Where the agent loop sits

```
company-api (uvicorn, pid 1195880, active since 2026-10-13T18:52:23Z, NRestarts=0, MemoryCurrent=6,818,807,808 B, MemoryMax=infinity)
└─ AutopilotController._loop()                     app/autopilot.py:6922   (daemon thread, interval 900 s)
   └─ run_once()                                   app/autopilot.py:5356
      ├─ "Company-wide tick"                       app/autopilot.py:5660
      │  └─ workforce.company_tick()               app/workforce.py:1320   (non-blocking _tick_lock)
      │     ├─ walk_agent_tree(root_id, max_depth=6)          app/workforce.py:1341
      │     ├─ _worker_agents = skipped_depts + root_id        app/workforce.py:1565-1567
      │     └─ ThreadPoolExecutor(max_workers=max(4, len))     app/workforce.py:1574
      │        └─ agent_worker.productive_tick(db, dept_id)    app/workforce.py:1582 → app/services/agent_worker.py:3804
      │           ├─ cost_circuit_breaker.is_circuit_broken()          agent_worker.py:3821
      │           ├─ release_stale_claims(db_url)                      agent_worker.py:1377
      │           ├─ _resume_approved_steps(db, agent)                 agent_worker.py:4337
      │           ├─ claim_next_step(db_url, agent_id)                 agent_worker.py:1299   ← CLAIM
      │           ├─ llm_budget.check_budget(db, agent, source=…)      agent_worker.py:3866
      │           ├─ build_focused_prompt(...)                         agent_worker.py:1445   ← CONTEXT
      │           └─ _execute_llm_step(messages, tools, ...)           agent_worker.py:2517   ← LLM + TOOLS
      │              └─ for round_num in range(max_rounds)             agent_worker.py:2768
      │                 max_rounds = route_contract.max_retries or MAX_TOOL_ROUNDS   agent_worker.py:2704
      │                 MAX_TOOL_ROUNDS = 5                            agent_worker.py:66
      │                 └─ _execute_tool_with_autonomy(tool, args, …)  agent_worker.py:2396   ← GATE + EXECUTE
      │                    ├─ department_tools.is_action_allowed(agent, tool)   agent_worker.py:2407 → app/services/department_tools.py:1728
      │                    │     over DEPARTMENT_TOOLS  (18 keys, 76 distinct tool names)
      │                    ├─ _read_only_autonomy_override(...) or _check_autonomy(tool, agent)  agent_worker.py:2422
      │                    │     _check_autonomy → autonomy.should_execute(action)   agent_worker.py:2279 → app/services/autonomy.py:380
      │                    │     if not execute → _queue_for_approval(...)           agent_worker.py:2470
      │                    └─ _execute_tool_dispatch(tool, args, agent)             agent_worker.py:2296 → app/chat_actions.execute_actions
      │                                                                              → app/chat_action_runtime._dispatch_action_inner
      └─ record + telemeter
         ├─ agent_worker.record_step_outcome(...)      agent_worker.py:4543
         └─ agent_worker._log_tick(...)                agent_worker.py:4609  → tick_telemetry
```

**The brief's "up to 3 LLM rounds" is a documentation claim, and the code disagrees with itself.** The module docstring says *"Make multi-turn LLM calls with structured tool calling (max 3 rounds)"* (`agent_worker.py:6`) and `_execute_llm_step`'s own docstring repeats *"max 3 rounds"* (`:2525`), but the constant is `MAX_TOOL_ROUNDS = 5` (`:66`) and the loop bound is `route_contract.max_retries or MAX_TOOL_ROUNDS` (`:2704`), clamped to 5 at `:357`. Measured: **5**, not 3. `[M]` on the source.

`work_mode` and `company` are the only two subsystems that reach `productive_tick`; `work_mode_poll` (`_maybe_poll_work_queue_fast`, `:7520`) is the fast poll that feeds it. `AUTOPILOT_MAX_AGENTS_PER_TICK=20` (`.env:416`) caps how many agents `company_tick` will process per invocation.

---

## 3. The autonomy framework

`app/services/autonomy.py` (629 lines).

### 3.1 The levels

`class AutonomyLevel(IntEnum)` at `autonomy.py:38-47`:

| level | name | meaning (verbatim docstring `:6-10`) | `should_execute` verdict (`:380-436`) |
|---|---|---|---|
| 0 | `L0_SHADOW` | "Log only, never execute. For legal/irreversible actions." | `execute: False`, `action: "shadow_log"` |
| 1 | `L1_SUGGEST` | "Propose to owner, require explicit approval." | `execute: False`, `action: "suggest"` |
| 2 | `L2_APPROVE` | "Execute after owner quick-approve (SMS/dashboard)." | `execute: False`, `action: "request_approval"` |
| 3 | `L3_ACT_UNDO` | "Execute with cancel window (undo via delayed_executor)." | `execute: True`, `action: "execute_with_undo"` |
| 4 | `L4_AUTONOMOUS` | "Execute immediately, no human in loop." | `execute: True`, `action: "execute"` |

Only L3 and L4 set `execute: True`. L0–L2 all return `execute: False` and are routed by the caller to `_queue_for_approval` (`app/services/agent_worker.py:2470`), which writes to `action_approval_queue`.

### 3.2 The action → level table

`DEFAULT_MATRIX: dict[str, dict[str, Any]]` at `autonomy.py:66-196` — **56 entries** [M], keyed by action name, each with `max` (the ceiling auto-promotion can never exceed), `default` (the starting level), `cat`, optionally `no_demote` and `notes`.

Measured shape of the matrix [M]:

| property | count | which |
|---|---:|---|
| entries | **56** | — |
| `no_demote: True` (immune to auto-demotion) | **17** | `list_tasks, memory_search, memory_save, save_memory, memory_sync, system_health, gmail_search, ha_states, fetch_url, qb_search, managed_workflow_status, ledger_source_registry, create_task, update_task, close_task, complete_goal_step, delegate_task` |
| ceiling below L4 (`max < 4`) | **18** | `send_sms, dialpad_send_sms, gmail_send, ha_call_service, ha_doors, ha_climate, propose_spend_request, qb_reconciliation, alibaba_onetalk_automation, github_write_file, github_create_pr, repo_run_command, browser_goto, browser_click, browser_fill, browser_act, code_edit, propose_human_job` |
| ceiling ≤ L1 (permanently near-shadow) | **1** | `propose_human_job` — `{"max": 1, "default": 1, "cat": "legal", "notes": "Legal commitments need human"}` (`autonomy.py:184-190`) |
| ceiling exactly L0 | **0** | nothing in the matrix is pinned at L0 |

**What is permanently restricted.** The comment at `autonomy.py:183` reads `# Permanently restricted — L0 or L1`, and the only row under it is `propose_human_job` (max 1). `code_edit` — self-modification — is at `max: 3` (`:167-172`) with the note *"Self-improvement is encouraged. Avoid editing protected infrastructure files."* `build_tool` is `{"max": 4, "default": 3}` (i.e. it can climb to full autonomy). `gmail_send` is `max: 3` with note *"30s undo window"*. `send_sms` is `max: 3` with note *"SMS to owner always autonomous"*. `dialpad_send_sms` is `max: 3` with the note *"Routine operational customer SMS can be sent autonomously. Escalate to owner for sensitive or high-stakes messages."*

**The fall-through is the important structural fact.** `get_level()` (`autonomy.py:316`) resolves in this order: in-memory `_level_overrides` → the `autonomy_levels` DB row → `DEFAULT_MATRIX` default → and finally, at `:376-377`:

```python
    # Unknown actions default to L4 (autonomous) — bias towards action
    return AutonomyLevel.L4_AUTONOMOUS
```

So **any action name that is not a key of `DEFAULT_MATRIX` executes at L4 with no gate at all.** `_check_autonomy` (`agent_worker.py:2279-2294`) also wraps the call in `try/except` and returns `{"execute": True, "level": 4, "action": "execute"}` if the autonomy module raises.

### 3.3 How a level is raised or lowered

| mechanism | constant | file:line |
|---|---|---|
| promote | `PROMOTE_AFTER_SUCCESSES = 8` — "Promote after N consecutive successes" | `autonomy.py:201`, `_try_promote` `:478` |
| demote | `DEMOTE_AFTER_FAILURES = 5` in `FAILURE_WINDOW_SECONDS = 3600` | `autonomy.py:202-203`, `_try_demote` `:499` |
| auto-recovery | `COOLDOWN_RESTORE_SECONDS = 2 * 3600` — a level stuck below its default for 2 h with no new failures is restored to `default` | `autonomy.py:208`, applied in `get_level` `:326-352` |
| manual override | `set_level_override(action, level)`, refused if `level > max_level` (or outside 0..4 when the action is not in the matrix) | `autonomy.py:612-629` |
| persistence | `_persist_level(...)` writes `autonomy_levels`; `_ensure_table` creates it | `autonomy.py:534`, `:285` |
| demotion immunity | `entry.get("no_demote")` short-circuits `_try_demote` | `:499-514` |
| stale-override sweep | `_cleanup_stale_overrides()` runs on every `get_level` | `:224`, called `:319` |

Promotion is capped by `entry.get("max", 2)` (`:483`) — note the **default of 2** when an action is missing from the matrix in `_try_promote`/`_try_demote`, which is inconsistent with `get_level`'s default of 4.

### 3.4 What the table says right now

`SELECT * FROM autonomy_levels` at 2026-10-14T01:0xZ [M]:

- **74 rows.** Schema: `action_name PRIMARY KEY, current_level, max_level, successes, failures, last_promoted_at, last_demoted_at, updated_at`.
- **43 of 74 have ever been promoted** (`last_promoted_at IS NOT NULL`); **42 of 74 have ever been demoted** (`last_demoted_at IS NOT NULL`).
- Distribution `(current, max)` → n: `(4,4)` **31**, `(2,4)` 14, `(3,3)` 10, `(0,2)` 4, `(1,4)` 4, `(3,2)` 4, `(0,4)` 2, `(2,3)` 2, `(3,4)` 2, `(1,2)` 1. **31 rows sit at L4/L4; 43 sit below L4.**
- The `current_level`/`max_level` pair is **internally inconsistent on 5 rows** where `current > max`: `calendar_get` 3/2, `cua_run` 3/2, `run_command` 3/2, `web_extract` 3/2, `upgrade_tool` 1/2. Reported, not judged.
- Recent activity: `repo_search` promoted to 4 at 2026-10-13T20:36:57Z; `repo_list_dir` last `updated_at` 2026-10-13T20:08:59Z with successes 0 / failures **9**; `browser_act` demoted to 2 at 2026-10-13T20:21:29Z; `gmail_read` failures 3, last demoted 2026-10-12T17:21:46Z; `ha_status` demoted 2026-10-13T14:17:35Z. **18 rows still read `updated_at` 2026-06-05** — untouched for four months.

**The matrix and the table do not describe the same set of actions** [M]:

| comparison | count |
|---|---:|
| rows in `autonomy_levels` | 74 |
| entries in `DEFAULT_MATRIX` | 56 |
| **in the DB but NOT in the matrix** (so `get_level` returns their DB row while `get_max`/`_try_promote` would use the fallback 2) | **28** |
| in the matrix but NOT in the DB | 10 |

The 28 DB-only actions are: `ask_owner, assign_task, browser_run, browser_save_session, browser_screenshot, browser_sessions, browser_use_run, calendar_get, contact_lookup, contact_search, cua_run, dialpad_pull_calls, dialpad_pull_sms, get_current_datetime, gmail_accounts, ha_entity, ledger_process_inbox, ledger_status, lpt_hub_classify_cases, lpt_hub_sync_cases, managed_workflow_report, repo_map, run_command, task_hygiene, upgrade_tool, web_extract, website_pricing_summary, website_work_order_digest`.

Of those, seven are **also** absent from the 147-name dispatcher chain (`assign_task`, `managed_workflow_report`, `contact_lookup`, `contact_search`, `cua_run` are present in the chain; `assign_task` and `calendar_get` are present) — the two sets overlap but neither contains the other. The consequence is mechanical: an action present in the dispatcher but absent from `DEFAULT_MATRIX` (e.g. `read_call_transcript`, `gv_send_sms`, `shop_update_repair_status`, `stripe_search_charges`, `deep_research`, `ask_advisor`, `code_edit` is present, `propose_mission` is absent, `hire_department`/`fire_agent`/`reactivate_agent` are absent) resolves to **L4 and executes immediately**, regardless of what `autonomy_levels` says about a different name.

---

## 4. The action surface

### 4.1 The count

| surface | count | how measured |
|---|---:|---|
| actions in the hand-written dispatch chain, `app/chat_action_runtime.py` | **147** distinct names | `grep -o 'action_name == "[a-z0-9_]*"' app/chat_action_runtime.py \| sed 's/.*"\(.*\)"/\1/' \| sort -u \| wc -l` |
| `chat_action_*` modules forming that surface | **23** (`chat_action_agents, _browser, _calendar, _code_edit, _dynamic_tools, _gmail, _home_assistant, _linux_pc, _managed_workflows, _memory, _notifications, _owner, _parsing, _phone_tech, _policy, _quickbooks, _repos, _resilience, _runtime, _scheduling, _skills, _system, _tasks`) plus the facade `app/chat_actions.py` | `ls app/ \| grep chat_action` |
| self-built dynamic tools, `data/tool_registry.json` | **633** tools (+ 4 department records) | `json.load(...)["tools"]` → `len == 633` |
| per-department allow-lists, `DEPARTMENT_TOOLS` | **18** keys, **76** distinct tool names | AST/regex over `app/services/department_tools.py` |
| HTTP routes | **665** route decorators (377 get, 270 post, 11 delete, 5 patch, 2 put) | `grep -rEho '@(app\|router)\.(get\|post\|put\|patch\|delete)\(' app/ --include=*.py \| wc -l` |

### 4.2 How they are registered

There is no decorator registry and no table of actions. Three mechanisms, all ad hoc:

1. **A hand-written `if` chain.** `app/chat_action_runtime.py` (2,678 lines) `_dispatch_action_inner` is a flat sequence of `if action_name == "…": return _exec_…(params, settings=settings)` — first at `:452` (`system_health`), continuing to `:875` (`cua_run`) and beyond, with the bulk of the `_exec_*` bodies living in the same file from `:2477` onward. `app/chat_actions.py` is a **compatibility facade** (209 lines) that imports handler callables out of the `chat_action_*.py` modules by name (`from app.chat_action_gmail import _exec_gmail_list, …` at `:34-41`) and forwards `execute_actions()` into `_runtime`. So the names live in the chain; the bodies live in 23 modules; the facade exists to keep old import paths working.
2. **A JSON registry for self-built tools.** `app/tool_factory.py` (2,342 lines) defines `_REGISTRY_PATH = _PROJECT_ROOT / "data" / "tool_registry.json"` (`:35`) and `_save_registry(registry)` (`:88`), called from nine sites (`:124, 655, 835, 965, 1111, 1614, 1671, 1691`). The live file is **404,947 bytes**, `updated_at 2026-10-14T00:58:44.642793+00:00` [M], holding **633** tools and 4 department records. `app/chat_action_dynamic_tools.py` (230 lines) exposes `_exec_build_tool` (`:14`), `_exec_upgrade_tool` (`:65`), `_exec_delete_tool` (`:104`), `_exec_list_dynamic_tools` (`:141`) and `_exec_dynamic_tool` (`:181`) — the last is the generic invoker.
3. **Prompt-declared tools.** The gateway injects its own internal tools — `_SEARCH_WORKSPACE_TOOL` (`app/services/ai_gateway.py:169`), `_DELEGATE_TASK_TOOL` (`:213`), `_GATEWAY_INTERNAL_TOOL_NAMES = {"search_workspace", "delegate_task"}` (`:243`) — via `_inject_gateway_tools` (`:301`).

### 4.3 How dispatch works, and where the gates are

```
_execute_llm_step (agent_worker.py:2517)
  └─ per round: model returns tool_calls → _normalize_gateway_tool_calls (:3624)
     └─ for each call: _execute_tool_with_autonomy (agent_worker.py:2396)
        ├─ SCOPE GATE   department_tools.is_action_allowed(agent_id, tool_name)          agent_worker.py:2407
        │               → app/services/department_tools.py:1728
        │               → `return action_name in DEPARTMENT_TOOLS.get(agent_id, [])`
        │               → refusal text: f"Tool '{tool}' is not available to {agent}."    (2409-2414)
        ├─ ARG NORMALISE _normalize_tool_args_for_context(tool, args, step_id, goal_id)  agent_worker.py:2417
        ├─ AUTONOMY GATE _read_only_autonomy_override(...) or _check_autonomy(...)        agent_worker.py:2422
        │               → autonomy.should_execute(action_name)                            autonomy.py:380
        │               └─ if not execute: _queue_for_approval(...) → action_approval_queue  agent_worker.py:2470
        │                  returns "... requires approval (level L, disposition). Queued as approval #id."
        └─ EXECUTE      _execute_tool_dispatch(tool, args, agent_id, goal_id)             agent_worker.py:2296
                        → app.chat_actions.execute_actions → _dispatch_action_inner
        └─ record: executed → _clear_tool_failures_for; not executed → _note_tool_failure  agent_worker.py:2455-2461
```

A fourth gate sits underneath: `TOOL_RUNTIME_REQUIREMENTS` (`app/services/department_tools.py:1751-1754`) declares `browser_use_run` and `browser_capture_session` as needing the `browser_use` package, and `tool_runtime_unavailable_reason()` (`:1759`) answers whether the host can actually import it — cached per process in `_TOOL_AVAILABILITY_CACHE` (`:1756`). The comment at `:1734-1750` records why: those tools were allow-listed for five departments while the package was not installed, so every call failed.

### 4.4 Which are gated

| gate | coverage | evidence |
|---|---|---|
| department scope (`is_action_allowed`) | all tool calls in `_execute_tool_with_autonomy` | `agent_worker.py:2407`, `department_tools.py:1728` |
| autonomy level | all tool calls, unless `bypass_autonomy=True` | `agent_worker.py:2421`; `bypass_autonomy` is a parameter of `_execute_tool_with_autonomy` (`:2403`) |
| explicit matrix row | **56** action names | `autonomy.py:66-196` |
| ceiling below L4 | **18** of those 56 | measured |
| permanently ≤ L1 | **1** (`propose_human_job`) | `autonomy.py:184-190` |
| **not** gated by any matrix row (falls to L4) | every one of the 147 dispatcher names that is not in the 56 — including `hire_department`, `fire_agent`, `reactivate_agent`, `send_directive`, `propose_mission`, `update_mission`, `schedule_action`, `deep_research`, `ask_advisor`, `delete_tool`, `gv_send_sms`, and the whole `shop_*` / `website_*` family | derived from the 147-name list vs the 56-entry matrix [M] |
| no-dispatch fallback | `_dispatch_action_inner` has no generic `else` that raises on an unknown name; the final handlers at `:2608-2672` are concrete `_exec_bulk_*` bodies | `app/chat_action_runtime.py` tail |

---

## 5. Memory

**Measured 2026-10-14T01:00:00Z–01:07:00Z on the authority** by a delegated measurement on this same thread. All row counts below are live in that window unless explicitly marked as coming from a shadow/index table. Nothing was written on the authority.

### 5.0 The load-bearing fact: imported vs dead

Every one of the six named modules is imported by non-test code. **None of them is dead.** What *is* dead is three SQLite write functions, one dangling import, and two whole vector collections.

| module | imported by (non-test, file:line) | reachable from the tick? |
|---|---|---|
| `app/services/unified_memory.py` | `app/autopilot.py:495`; `app/chat_action_memory.py:71,126`; `app/memory_contract.py:203,391` | **YES — writes and reads.** `app/autopilot.py:6793`/`:6806` (inside `run_once`, `:5356`, called from the loop at `:7250`) → `app/database.py:5016 add_memory` → `app/memory_contract.py:182 record_memory` → `unified_memory.save_memory` (`:1010`) |
| `app/services/semantic_memory.py` | `app/assistant_chat.py:5087`; `app/services/memory_consolidation.py:142`; `app/services/email_style.py:209,351`; `app/main.py:16589,16596,16615`; `app/chat_action_memory.py:42,181,209`; `app/memory_contract.py:412` | **YES, indirectly** — via `memory_consolidation.py:142` (see 5.7) |
| `app/services/memory_consolidation.py` | `app/autopilot.py:8655` | **YES — direct** (`app/autopilot.py:7179` → `:8630`) |
| `app/services/procedural_memory.py` | `app/services/agent_worker.py:4303`; `app/services/context_manager.py:353`; `app/main.py:17496`; `app/memory_contract.py:456` | **YES, indirectly** — written from `agent_worker.py:4303` inside `observe_tick` (`:3962`), in the department-worker path driven by the autopilot work queue (`app/autopilot.py:3440`) |
| `app/services/mem0_service.py` | `app/assistant_chat.py:5112,5695`; `app/agent_bus.py:523`; `app/memory_contract.py:438` | **NO** — chat-turn or APScheduler only |
| `app/services/project_memory.py` | `app/main.py:21877` **only** | **NO** — the sole call site is the HTTP route `POST /api/v1/projects/{project_id}/distill` (`app/main.py:21875`); `grep -n "distill\|project_memory" app/autopilot.py` → nothing |

**Dead code found:**

- `app/database.py:3967 store_memory_entry` — writes `memory_entries`. **Zero callers outside `app/database.py`.** Corroborated by the table: `SELECT COUNT(*) FROM memory_entries` → **0**.
- `app/database.py:4015 vector_search_memories` — reads `memory_vectors JOIN memory_entries`. **Zero callers.** Structurally dead: it can only return rows if `store_memory_entry` runs.
- `app/database.py:6531 upsert_knowledge` — writes/reads `knowledge`. **Zero callers.** Corroborated: `SELECT COUNT(*) FROM knowledge` → **0**.
- `app/agent_bus.py:493` — `from app.services.memory_consolidation import run_consolidation`. **`run_consolidation` does not exist in that module** (`grep -rn "def run_consolidation" app/` → nothing; the module defines only `run_memory_consolidation` at `app/services/memory_consolidation.py:25`). It sits inside `_wrap_memory_consolidation` (`app/agent_bus.py:490`) wrapped in `try/except Exception` with `log.error(...)` at `:495-497`, so it fails silently on every scheduled fire. NOT DETERMINED — whether that APScheduler job is currently registered.

### 5.1 ChromaDB — the company vector store

**(a) What it holds.** Seven collections created by `semantic_memory._get_collection` (`app/services/semantic_memory.py:129-138`) and `workspace_search._get_or_create_collection` (`app/services/workspace_search.py:337,519,631,752`). Path: `settings.semantic_memory_dir` (`app/services/semantic_memory.py:84-86`), default `"data/chromadb"` (`app/config.py:882`); no `SEMANTIC_MEMORY_DIR` in `.env`, so with `WorkingDirectory=/opt/company` the live path is **`/opt/company/data/chromadb/chroma.sqlite3`**.

**(b) Who writes it.** `memories` + `knowledge`: `semantic_memory.store` → `col.upsert(...)` at **`app/services/semantic_memory.py:762`** (read-back verify `:770`), from `app/services/memory_consolidation.py:144` (**tick-reachable**) and `app/chat_action_memory.py:44` (chat action). Bulk backfill `_upsert_batch` → `col.upsert` at `:223`, from `sync_from_db` (`:1028`), callers `app/chat_action_memory.py:181`, `app/main.py:16596` — neither is the tick. `workspace_all`/`company_data`/`workspace_code`/`vscode_chats` from `app/services/workspace_search.py:752,631,337,519`. `email_sent_history` from `app/services/email_style.py:227`.

**(c) Who reads it.** `search` → `col.query` at `app/services/semantic_memory.py:437`; `search_hybrid` `:868`; `get_relevant_context` `:1122`, whose only non-test caller is `app/assistant_chat.py:5087` (**not the tick**). `stats` `:1101`.

**(d) Current size — measured.**
```
du -sh /opt/company/data/chromadb                             → 2.9G
ls -la /opt/company/data/chromadb/chroma.sqlite3              → 2,404,261,888 bytes, mtime Oct 14 01:01
sqlite3 -readonly …/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings"                        → 393112
sqlite3 -readonly …/chroma.sqlite3 "SELECT id,name FROM collections"                        → 7 collections
sqlite3 -readonly …/chroma.sqlite3 "SELECT COUNT(*) FROM embedding_metadata WHERE key='chroma:document'" → 393112
```

| collection | embeddings |
|---|---:|
| workspace_all | 193,487 |
| company_data | 176,036 |
| workspace_code | 17,451 |
| `memories` | **6,138** |
| `knowledge` | **0** |
| `vscode_chats` | **0** |
| `email_sent_history` | **0** |

Two counts stated plainly: the `memories` collection holds **6,138** documents against **25,049** rows in the SQLite `memories` table measured in the same window; and the `knowledge` collection has a row in `collections` but **zero** embeddings — consistent with the `knowledge` table itself holding 0 rows.

### 5.2 ChromaDB — the mem0 vector store

**(a) What it holds.** Three collections `mem0_memories`, `mem0migrations`, `mem0_memories_entities`, declared in the vector-store config at `app/services/mem0_service.py:217-223`. Path `settings.mem0_storage_path` (`:191`) = `data/mem0` (`.env:255`) → **`/opt/company/data/mem0/chroma.sqlite3`**.

**(b) Who writes it.** The `mem0ai` library via `mem.add(...)` at `app/services/mem0_service.py:335`, reached from `app/assistant_chat.py:5703`. **Not tick-reachable.** `nightly_consolidation` (`:486`) is called from `app/agent_bus.py:525`, also not the tick.

**(c) Who reads it.** `mem.search(...)` at `app/services/mem0_service.py:122` (via `app/assistant_chat.py:5114`); `mem.get_all(...)` at `:142` (via `get_all_memories` `:461`, `nightly_consolidation` `:501`, `mem0_stats` `:578`).

**(d) Current size — measured.**
```
du -sh /opt/company/data/mem0                                → 1.1G
ls -la /opt/company/data/mem0/chroma.sqlite3                 → 311,074,816 bytes, mtime Oct 14 01:01
sqlite3 -readonly …/data/mem0/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings"              → 130983
```
Per collection: `mem0_memories` **123,865** · `mem0_memories_entities` **7,118** · `mem0migrations` 0. Metadata-key histogram: `user_id` 130,983, `data` 130,983, `agent_id` 130,983, `created_at` 123,865, `channel` 123,865, `attributed_to` 62,159, `entity_type` 7,118.

### 5.3 ChromaDB — other trees on the box

| path | file bytes | mtime | embeddings | collections |
|---|---:|---|---:|---|
| `/opt/company/data/chromadb/chromadb/` | 11,280,384 | May 4 22:05 | 2,092 | `memories` 2,092 · `knowledge` 0 |
| `/root/work/esc-baseline/data/chromadb/` | 188,416 | Oct 14 00:12 | NOT DETERMINED | NOT DETERMINED |
| `/root/work/esc-parser/data/chromadb/` | 188,416 | Oct 14 00:09 | NOT DETERMINED | NOT DETERMINED |
| `/root/work/fd-relay/data/chromadb/` | 188,416 | Oct 13 14:41 | NOT DETERMINED | NOT DETERMINED |
| `/root/.cache/chroma/` | dir `onnx_models` only | — | — | not a store |

The `data/chromadb/chromadb/` tree is **not** the live store: its mtime is May 4 while the parent `chroma.sqlite3` was written Oct 14 01:01. It is dead weight on a 95%-full disk.

### 5.4 mem0 — installed and configured, but not on the tick

- `mem0ai` **2.2.1** at `/opt/company/.venv/lib/python3.14/site-packages/mem0ai-2.2.1.dist-info`.
- `.env:252-255`: `MEM0_ENABLED=true`, `MEM0_LLM_MODEL=gpt-4o-mini`, `MEM0_EMBEDDING_MODEL=text-embedding-3-small`, `MEM0_STORAGE_PATH=data/mem0`; also `.env:525 MEM0_PROVIDER=` and `.env:526 MEM0_GATEWAY_MODEL=secretary-fast`. `app/config.py:1188 mem0_enabled=True` and `:1193 mem0_storage_path="data/mem0"`, so it is enabled by two independent paths.
- Outside `/opt/company`: `/root/.mem0/history.db` **3,072,000 bytes** (mtime Oct 14 01:01), `SELECT COUNT(*) FROM history` → **2,656**; `/root/.mem0/config.json` 7,751 bytes holds only `user_id` + `notice_state` telemetry. Which exact `mem0ai` call writes `history.db` is NOT DETERMINED.
- **Unresolved configuration conflict, stated as a fact:** `app/services/mem0_service.py:174-179` overrides the configured model whenever `deepinfra_api_key` is set — forcing `deepseek-ai/DeepSeek-V4-Flash-0731` at `https://api.deepinfra.com/v1/openai` — so `.env:253 MEM0_LLM_MODEL=gpt-4o-mini` may not be the model actually in use. NOT DETERMINED whether `deepinfra_api_key` is non-empty (secret values were not read).
- Its footprint is the 130,983 embeddings in 5.2.

### 5.5 `app/services/semantic_memory.py` (1,215 lines)

Client for the two collections in 5.1; docstring `:1-19` names them. Maintains process-local counters (`:73-81`) and patches out Chroma telemetry (`:89-109`). Writes: `store()` `:707` → `col.upsert(...)` at **`:762`**; `sync_from_db()` `:1028` → `_upsert_batch` `col.upsert` `:223`. Reads: `_query_collection` → `col.query(...)` at **`:437`**; `get_relevant_context` `:1122`, sole non-test external read `app/assistant_chat.py:5087` (**not the tick**). It owns no store of its own; `store_outcome_report()` `:804` and `search_outcome_report()` `:1012` are process-local counters that read zero on a fresh process, so no live number can be read from them via the CLI — not read.

### 5.6 `app/services/unified_memory.py` (1,706 lines) — the canonical store

**(a) What it holds.** The `memories` table plus the `memory_vectors` sqlite-vec index plus `memory_write_outcomes`. Constants `:51-55` (`EMBED_MODEL="text-embedding-3-small"`, `EMBED_DIMS=1536`); vec DDL `:239-244`; `app/memory_contract.py:636` names the canonical chain verbatim: *"database.add_memory -> memory_contract.record_memory -> unified_memory.save_memory"*.

**(b) Who writes it.** `save_memory_outcome` `:725`: `INSERT INTO memories` at **`:894`**, `INSERT INTO memory_vectors` at **`:955`**, outcome telemetry via `_insert_outcome_row` `:409` / `_record_outcome` `:435`, backfill `INSERT INTO memory_vectors` at **`:1147`**; `save_memory` wrapper `:1010`; `UPDATE memories` (decay/access) `:846`, `:1380`; `UPDATE memories SET status='archived'` at `:1591` (`archive_dormant` `:1572`). **Tick-reachable: YES** — chain in 5.0. Corroborating: the `source` histogram is topped by `autopilot_checkin` (11,214), and `memory_write_outcomes` has a row dated `2026-10-14T01:01:56`.

**(c) Who reads it.** `search_memory` `:1184` reads `memories_fts` at `:1225`, `memory_vectors` at `:1248`/`:1258`, `memories` at `:1316`; `_keyword_fallback` `:1391` reads `memories` at `:1421`. `get_context_memories` `:1457` → called from `app/autopilot.py:498` inside `_checkin_prompt` (`:261`), which `run_once` invokes at `app/autopilot.py:6536` — **tick-reachable read**. `stats` `:1599` reads `SELECT COUNT(*) FROM memory_vectors` at `:1630`.

**(d) Current size — measured.**
```
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memories"                → 25049  (01:06Z; 25047 at 01:00Z — live growth)
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memory_vectors_rowids"  → 10725  (01:06Z; 10723 at 01:00Z)
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memory_write_outcomes"  → 4085
```
`memory_type`: observation 12,462 · summary 12,022 · question 412 · preference 45 · lesson 43 · event 39 · profile 9 · fact 6 · decision 5 · goal 2 · milestone 1 · schema 1. `status`: active 25,034 · superseded 13 (no `archived` — `archive_dormant` `:1572` has produced no row). `source`: autopilot_checkin 11,214 · activity_sync 2,916 · self_diagnosis 1,794 · finance 914 · action 649 · shadow_mode 576 · audit 531 · system 481 · ask_owner 455 · operations 430 · security 414 · engineering 201. `category`: autopilot_checkin 11,214 · owner_context 2,943 · self_diagnosis 1,795 · finance 1,021 · memory_consolidation **708** · shadow_mode 667 · audit 606 · system 564 · owner_questions 455 · security 453 · operations 441 · business 210. `created_at` range `2026-02-17T06:44:29.878682+00:00` → `2026-10-14T01:01:56`; **1,787 rows in the trailing 7 days**; **69 distinct `agent_id`**.

`memory_write_outcomes`: outcome written 3,216 · skipped_policy 775 · deduplicated 82 · partial 11 · failed 1 (= 4,085). stage NULL 3,298 · extraction 775 · embedding 11 · persistence 1 (= 4,085). Range `2026-09-28T05:55:57` → `2026-10-14T01:01:56`; trailing-7-day histogram 10-07 255 · 10-08 491 · 10-09 251 · 10-10 259 · 10-11 326 · 10-12 260 · 10-13 543 · 10-14 23.

**Index caveat, stated explicitly.** `memory_vectors` is `CREATE VIRTUAL TABLE memory_vectors USING vec0(memory_id INTEGER PRIMARY KEY, agent_id TEXT partition key, embedding float[1536] distance_metric=cosine)` and the `sqlite3` CLI **cannot open it**: `SELECT COUNT(*) FROM memory_vectors` → `Error: in prepare, no such module: vec0`. The **10,725** figure comes from the shadow table `memory_vectors_rowids` — **the index's own bookkeeping, not a query of the vector table**. `sqlite_vec` 0.1.9 *is* importable in the app venv (`import sqlite_vec` → OK), so the application can read it. Against `memories` = 25,049 this leaves **14,324 rows with no vector row**, computed from two index counts.

### 5.7 `app/services/memory_consolidation.py` (163 lines)

**(a)** One daily summary memory; docstring `:32`. **(b)** Writes `add_memory(...)` at **`:131`** (→ `database.add_memory` `app/database.py:5016` → `unified_memory.save_memory`) then `semantic_memory.store(...)` at **`:144`**. Idempotence key `source_key = f"memory_consolidation:{today}"` `:49`; exclusion set `:62-67`; minimum 8 items `:73`; minimum 80-char summary `:124`.

**Tick-reachable: YES, directly.** `_loop` (`app/autopilot.py:6922`) → `self._maybe_run_memory_consolidation()` at **`app/autopilot.py:7179`** → def at `:8630` → import at `:8655` → called at `:8660`. Gate `memory_consolidation_enabled` at `:8632`; no `MEMORY_CONSOLIDATION_*` key exists in `.env`, so config defaults apply: `app/config.py:1135 enabled=True`, `:1136 every_hours=4`, `:1137 max_items=250`. (`app/autopilot.py:8657` reads `memory_consolidation_max_items` with a local fallback of 500, but the attribute exists on settings, so the effective value is 250.)

Live proof it runs, not just that it is wired:
```
SELECT id, created_at, substr(content,1,90) FROM memories WHERE category='memory_consolidation' ORDER BY id DESC LIMIT 5
 → 25029|2026-10-13T21:53:17, 25000|17:53:12, 24815|13:53:08, 24763|09:52:50, 24701|05:52:48
autopilot_state.json last_memory_consolidation_at → "2026-10-13T21:53:17.799291+00:00"
```
A 4-hour cadence across a full day, matching `every_hours = 4`.

**(c)** Only reader is its own `get_recent_memories(...)` at `:36` (defined `app/database.py:5087`). **(d)** **708** rows in `memories` with `category='memory_consolidation'`; most recent 2026-10-13T21:53:17, next due ~01:53 on 2026-10-14.

### 5.8 `app/services/procedural_memory.py` (397 lines)

**(a)** State-action-outcome tuples; docstring `:1-11`. Rolling cap `_MAX_EXPERIENCES_PER_AGENT = 500` at `:28`, retrieval limit 5 at `:31`. **(b)** `INSERT INTO procedural_experiences` at **`:151`** inside `store_experience` (`:116`); prune `DELETE` `:178`. Caller `app/services/agent_worker.py:4316` inside `observe_tick` (`:3962`), preceded by `capture_env_state` `:4309` — tick-reachable indirectly. **(c)** `SELECT … FROM procedural_experiences` at `:243-256` inside `retrieve_similar_experiences` (`:211`); caller `app/services/context_manager.py:362` in `assemble_context` (`:321`), formatted `:364`. Aggregate `get_experience_stats` `:366` → `:372`.

**(d) Measured.**
```
SELECT COUNT(*), SUM(state_embedding_json IS NOT NULL), MIN(created_at), MAX(created_at) FROM procedural_experiences
 → 18526|18494|2026-04-13T05:35:58.329015+00:00|2026-10-14T00:43:58.817224+00:00
SELECT agent_id, COUNT(*) FROM procedural_experiences GROUP BY agent_id ORDER BY 2 DESC LIMIT 10
 → cross_domain_synthesizer 500, dept_ai_platform 500, dept_business_ops 500, dept_comms_relationships 500,
   dept_creativity 500, dept_devices 500, dept_engineering 500, dept_evolution_reliability 500,
   dept_finance 500, dept_home_life 500
```
18,526 rows, 18,494 carrying a `state_embedding_json` (32 without). `MAX(created_at)` is ~20 minutes before measurement — live. The per-agent totals sitting at exactly 500 is the `:176-184` prune binding.

### 5.9 `app/services/project_memory.py` (191 lines)

**(a)** Distilled project knowledge; docstring `:1-6`. `DISTILL_PROMPT` `:24-34`; batch 20 / min importance 3 `:74-75`; max 5 items per batch (`:31`). **(b)** `add_project_knowledge(...)` at **`:151`** (imported `:140` from `app/services/project_hub.py`, defined `app/services/project_hub.py:840`). **Tick-reachable: NO** — the only caller of `distill_events` in the codebase is `app/main.py:21879`, inside the route `api_distill_project` (`app/main.py:21875`, `@app.post("/api/v1/projects/{project_id}/distill")`). `grep -n "distill\|project_memory" app/autopilot.py` → no output; `grep -rn "distill" scripts/` → no output. Secondary writers of the same table elsewhere: `app/services/managed_workflows.py:1155,1832,1845,1855,1865,1875`. **(c)** Read through `app/services/project_hub.py` / `app/memory_contract.py:487` (registered as the `project_memory` system report at `app/memory_contract.py:706-708`). NOT DETERMINED — the exact `SELECT` line inside `project_hub.py`; that file was not opened.

**(d) Measured.** `project_events` **2,600** rows; `project_knowledge` **303** rows, `MAX(created_at)` = **2026-07-02T00:41:53.543665+00:00** — **nothing has been written to this store for 103 days**. `app/memory_contract.py:641` names it: `"project_memory_store": "project_events + project_knowledge"`.

### 5.10 Every DB table that holds memory (`/root/authority.db`)

| table | rows (measured) | holds | written by (file:line) | read by (file:line) | tick? |
|---|---:|---|---|---|---|
| `memories` | **25,049** | canonical memory rows | `unified_memory.py:894` | `unified_memory.py:1316`, `:1421`, `:1617`; `semantic_memory.py:501` | YES |
| `memories_fts` (+`_data`,`_idx`,`_docsize`,`_config`) | FTS5 shadow | full-text index of `memories` | triggers `memories_fts_insert` / `_delete` / `_update` | `unified_memory.py:1225` | YES |
| `memory_vectors` (vec0) | **10,725** (via `memory_vectors_rowids`) | 1536-d vectors, DDL `unified_memory.py:239-244` | `unified_memory.py:955`, `:1147` | `unified_memory.py:1248`, `:1258`, `:1630` | YES |
| `memory_write_outcomes` | **4,085** | per-write staged outcome telemetry | `unified_memory.py:409`, `:435` | `unified_memory.py:454` | YES |
| `procedural_experiences` | **18,526** | state-action-outcome tuples | `procedural_memory.py:151` | `procedural_memory.py:243`, `:372` | indirect |
| `project_knowledge` | **303** | distilled project knowledge | `project_hub.py:840` via `project_memory.py:151`; `managed_workflows.py:1155…1875` | `project_hub.py` / `memory_contract.py:487` | NO |
| `agent_working_memory` | **84** | per-agent tick focus/next-actions/decisions | `agent_worker.py:4151`, `:4595`; `chat_action_agents.py:284`; `workflow_engine.py:725` | `agent_worker.py:3969`; `workflow_engine.py:760`; `memory_contract.py:556,559,563` | indirect |
| `knowledge` | **0** | topic/content knowledge | `database.py:6566` — **dead, no callers** | `semantic_memory.py:515,651`; `database.py:6531` (dead) | NO |
| `knowledge_triples` | **38** | subject-predicate-object graph | `owner_model.py:276`, `:642` | `owner_model.py:257`, `:627` | NO |
| `kg_nodes` / `kg_edges` | **2,544** / **2,172** | knowledge graph | not measured | `memory_contract.py:644` names it `knowledge_graph_store` | NOT DETERMINED |
| `agent_rules` | **170** | skill/constraint/preference rules | `behavioral_rules.py:213` | `behavioral_rules.py:267`, `:331`, `:593` | NOT DETERMINED |
| `rule_applications` | **0** | rule→outcome ledger | `behavioral_rules.py:408` | `database.py:3526` (schema only) | NOT DETERMINED |
| `agent_routing_rules` | **0** | project→agent routing | NOT DETERMINED | NOT DETERMINED | NOT DETERMINED |
| `memory_entries` | **0** | legacy vec-backed entries | `database.py:3989` — **dead, no callers** | `database.py:4037` — **dead, no callers** | NO |
| `proactive_insights` | **2,438** | insight feed rows | `proactive_engine.py:965` | `proactive_engine.py:295,323,353,374,384,422,426,429,434` | NOT DETERMINED |

Two of these deserve emphasis because the number is zero and the writer exists: **`memory_entries` = 0** and **`knowledge` = 0**, both with a fully-written insert function that nothing in `/opt/company/app` calls. `memory_entries` in particular is the target of a *second*, independent join into the **same** `memory_vectors` table (`database.py:4037` joins it to `memory_entries`, while `unified_memory.py:1111` joins it to `memories`) — so one vec0 table is addressed by two different joins, only one of which can ever match rows.

### 5.11 Summary of what is dead or unreachable

| thing | evidence |
|---|---|
| `store_memory_entry` (`app/database.py:3967`) | no callers outside `app/database.py`; target table 0 rows |
| `vector_search_memories` (`app/database.py:4015`) | no callers outside `app/database.py` |
| `upsert_knowledge` (`app/database.py:6531`) | no callers outside `app/database.py`; target table 0 rows |
| `from app.services.memory_consolidation import run_consolidation` (`app/agent_bus.py:493`) | name does not exist in the module; caught by `except` at `:495` |
| `project_memory.distill_events` | only caller is an HTTP route (`app/main.py:21875`); no tick or cron reference |
| Chroma collections `knowledge`, `vscode_chats`, `email_sent_history` | 0 embeddings each |
| whole tree `/opt/company/data/chromadb/chromadb/` | mtime May 4 vs live store Oct 14 01:01; not referenced by `settings.semantic_memory_dir` |
| `mem0` (`mem0ai` 2.2.1) | installed and configured (`.env:252`), 130,983 embeddings — but every caller is chat-turn or APScheduler, never the tick |

**Disk relevance to the 95%-full box:** the live Chroma stores total **4.0 GB** of the box; the dead legacy tree plus the three 188 KB sandboxes are pure dead weight.

---

## 6. The model layer

### 6.1 How a model is chosen

Two modules, 9,661 lines between them:

- **`app/services/smart_router.py`** (3,998 lines) is the chooser. Its static tables [M]:
  - `_CAPABILITY_DB` (`:81`) — **34** model capability entries.
  - `_COPILOT_EQUIVALENTS` (`:571`) — **12** copilot-lane equivalents.
  - `_TASK_CAPABILITY_REQUIREMENTS` (`:624`) — **56** task types (owner_chat, owner_sms, phone_call, sms_reply, strategic, code_edit, github_pr_review, github_plan, healing, self_prog, work_mode, agent_chat, company_tick, company, …).
  - `_ROUTE_POLICIES` (`:832`) — **4** public aliases: `secretary-fast`, `secretary-auto`, `secretary-smart`, `secretary-genius`.
  - `_ROLE_POLICIES` (`:871`) — **7** roles: classifier, summarizer, json_repair, tool_planner, code_reviewer, vision_reader, image_analyst.
  - `_TASK_ROLE_MAP` (`:927`) — **29** task→role mappings.
  - `_APPROVED_PROVIDERS = frozenset({"deepseek", "deepinfra", "fireworks", "google", "minimax"})` (`:820-822`).
  - `_UNSELECTABLE_ROUTE_ALIAS = "secretary-genius"` (`:829`) — present in the catalogue so clients can *ask*, but never selected; the standing rule names it explicitly ("never secretary-genius").
  - `_GEMINI_LONGCTX_IDS` (`:747`) — **0** entries. `_DIRECT_DEEPSEEK_EQUIVALENTS` (`:751`) — 2.
  - Scoring constants: `_DEFAULT_QUALITY_FLOOR = 0.85` (`:694`), `_ADAPT_MIN_CALLS = 8` (`:702`), `_ADAPT_RELIABILITY_MIN = 0.4` (`:703`), `_ADAPT_PRIOR_MEAN = 0.75` (`:705`), `_COST_REFERENCE_PER_MTOK = 10.0` (`:724`), `_MODEL_CB_FAIL_THRESHOLD = 3` / `_MODEL_CB_COOLDOWN_SEC = 90.0` (`:1105-1106`), `_CATALOGUE_TTL_SEC = 300.0` / `_CATALOGUE_TIMEOUT_SEC = 5.0` (`:1179-1180`).
- **`app/services/ai_gateway.py`** (5,663 lines) is the transport and the accounting layer. `_GOOGLE_MODEL_RENAME` (`:74`), `billing_model_id()` (`:82`), `_MAX_AGENT_LOOPS = 10` (`:245`), `_AGENT_LOOP_TIME_BUDGET_SEC = 100.0` (`:249`), `_MAX_DELEGATE_LOOPS = 6` / `_DELEGATE_COST_CAP_USD = 0.05` (`:253-254`), the server-side tool loop `_delegate_agent_loop_nonstream` (`:529`), and the internal tools at `:169`/`:213`.

### 6.2 The catalogue and aliases

| store | where | measured |
|---|---|---|
| `model_registry` table | `/root/authority.db` | **60** rows; **54** with `is_deprecated=1`, **6** live [M]. Columns include `canonical_id, provider, provider_model_id, display_name, tier, pricing_input_per_mtok, pricing_output_per_mtok, copilot_multiplier, context_window, supports_tools, is_vision, is_deprecated, is_preview, successor_model_id, lifecycle_state, pricing_source, pricing_confidence` |
| `model_aliases` table | same | **31** rows, **every one `source='hardcoded'`** [M]: `claude-opus-4.6→anthropic/claude-opus-4-6`, `gpt-5.5→openai/gpt-5.5`, `gemini-3-flash→google/gemini-3-flash`, `deepseek-v4-flash→openrouter/deepseek/deepseek-v4-flash`, `deepseek-v4-pro`, `kimi-k2.6`, `grok-4.20`, `mimo-v2.5`, `step-3.7-flash`, `MiniMax-M3`, … |
| seed catalogue (code) | `app/services/model_registry.py` | the same ids appear as literals here — e.g. `:118 "canonical_id": "openai/gpt-5.4"`, `:828-832` the `{"alias": …, "canonical_id": …, "source": "hardcoded"}` list. This is the catalogue's own seed, so the literal is the point of the file. |
| discovery | `app/services/model_discovery.py`, `app/monitoring`-adjacent `_maybe_run_model_discovery` (`app/autopilot.py:9097`) | runs as an autopilot subsystem |
| gateway trace | `gateway_trace_span` table | present |

Note: **54 of 60 catalogue rows are marked deprecated**, most with the note *"Deprecated 2026-07-19: DeepSeek Flash only policy"* [M]. The router still carries 34 capability entries and 12 copilot equivalents, so the routing tables and the catalogue are not in step.

### 6.3 Are model names hardcoded anywhere? Yes — 181 literal ids in 13 files

`grep -rEo '"(deepseek|openai|anthropic|google|openrouter|moonshotai|x-ai|xiaomi|minimax|copilot)/[A-Za-z0-9._-]+"' app/ --include=*.py | wc -l` → **181** [M].

Files that contain such literals [M]: `app/assistant_chat.py`, `app/services/model_registry.py`, `app/services/conversation_compactor.py`, `app/services/smart_router.py`, `app/services/browser_use_agent.py`, `app/services/model_discovery.py`, `app/services/research_dispatcher.py`, `app/services/agent_worker.py`, `app/services/cognitive_router.py`, `app/services/ai_gateway.py`, `app/main.py`, `app/config.py`, `app/pricing.py`.

The ones that are **operational defaults rather than catalogue rows** — i.e. the ones the standing rule ("model ids must be resolved at runtime") is about:

| file:line | literal | context |
|---|---|---|
| `app/services/ai_gateway.py:447` | `_DELEGATE_DEFAULT = "deepseek/deepseek-v4-flash"` | the model `delegate_task` runs on when no tier resolves |
| `app/assistant_chat.py:1909` | `getattr(settings, "fast_model_openrouter", "deepseek/deepseek-v4-flash")` | inline fallback default |
| `app/config.py` | `fast_model_openrouter` and siblings | the settings defaults themselves |
| `app/services/agent_worker.py` | department model chains (`_dept_model_env_chain` `:3451`, `_resolve_department_models` `:3485`, `_available_department_models` `:3578`) | per-department candidate lists |
| `app/main.py`, `app/pricing.py`, `app/services/cognitive_router.py`, `app/services/conversation_compactor.py`, `app/services/browser_use_agent.py`, `app/services/research_dispatcher.py`, `app/services/model_discovery.py` | assorted | — |
| `app/services/ai_gateway.py:74` | `_GOOGLE_MODEL_RENAME` | a hardcoded id→id rename map |

### 6.4 What was actually spent in the last 24 hours

`SELECT provider||'/'||model, COUNT(*), SUM(total_tokens), ROUND(SUM(estimated_cost_usd),6) FROM model_usage WHERE created_at >= datetime('now','-24 hours') GROUP BY provider, model` at 2026-10-14T01:04Z [M]. **Note the column names: `model_usage` has `provider`, `model`, `total_tokens`, `estimated_cost_usd`, `created_at` — not `model_id`/`cost_usd`/`source`.**

| model | calls | tokens | USD |
|---|---:|---:|---:|
| `deepseek/deepseek-v4-flash` | 1,291 | 47,342,785 | **21.092936** |
| `google/gemini-3.5-flash` | 275 | 984,579 | 1.547459 |
| `google/gemini-3.5-flash-lite` | 929 | 2,381,081 | 0.775101 |
| `openai/whisper-1` | 55 | 0 | 0.566536 |
| `deepseek/deepseek-v4-pro` | 302 | 1,051,699 | 0.139574 |
| `google/gemini-3.1-pro-preview` | 6 | 5,962 | 0.012964 |
| **total** | **2,858** | **51,766,106** | **24.134569** |

`SUM(success)` = 2,816 of 2,858.

By agent [M]: `orchestrator` 386 calls / $5.155658 · `dept_finance` 298 / $4.402805 · `dept_scheduling` 245 / $2.944868 · `dept_business_ops` 151 / $1.786838 · `model_ops_evaluator` 101 / $1.659537 · `dept_engineering` 97 / $1.407108 · `evolution_architect` 77 / $1.283507 · `dept_world_index` 117 / $1.138272 · `vscode_gateway` 949 / $0.840538 · `dept_home_life` 76 / $0.679535 · `dept_devices` 122 / $0.642260 · `dept_evolution_reliability` 58 / $0.575648 · `dept_systems_custody` 43 / $0.552598 · … · `mem0_consolidation` 1 / $0.002761 · `email_draft` 1 / $0.000759.

By tier [M]: `fast` 2,270 calls / **$22.374507** · `mid` 577 / $1.687032 · `ceo` 11 / $0.073030.

`served_by` is **NULL on all 2,858 rows** [M] — the column exists but nothing populates it, so the exact upstream provider behind an OpenRouter-shaped id cannot be read from this table.

All-time top spenders (for scale) [M]: `deepseek/deepseek-v4-flash` 92,295 calls / $318.11 · `openrouter/deepseek/deepseek-v4-pro` 6,909 / $271.48 · `deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731` 56,050 / $158.13 · `openai/gpt-5.2` 769 / $119.73 · `google/google/gemini-3.5-flash` 1,053 / $78.93. `model_usage` holds **260,256** rows spanning 2026-05-24T07:23Z → 2026-10-14T01:04:37Z.

**For comparison with the one-day-old baseline:** `docs/dsh-evolution/30-systems-and-autonomy-audit.md:78` recorded *"1,639,891 tokens | $0.1395"* for the preceding 24 h at 13:07Z on 2026-10-12. The 24 h to 2026-10-14T01:04Z is **51,766,106 tokens and $24.1346** — a 31× token and 173× dollar increase. Both are true readings of the same table at different times; I report them side by side and do not reconcile them. (`tick_telemetry`'s own `total_cost` for 2026-10-13 is $0.1673, i.e. the same table disagrees with `model_usage` by two orders of magnitude for the same day — `tick_telemetry.total_cost` appears to cover only the agent tick path, not gateway traffic such as `vscode_gateway`'s 949 calls.)

---

## 7. The data model

### 7.1 Object counts

```
sqlite3 -readonly /root/authority.db "SELECT type, COUNT(*) FROM sqlite_master WHERE type IN ('table','view') GROUP BY type;"
 → table|235   view|9
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM sqlite_master;"        → 662
```
**235 tables, 9 views.** The remaining 418 `sqlite_master` rows are indexes and triggers — measure them with `SELECT type, COUNT(*) FROM sqlite_master GROUP BY type`. The 9 views are `v_contact_duplicate, v_dialpad_call_media, v_dialpad_calls, v_dialpad_comms_coverage, v_dialpad_dup_row, v_dialpad_sms, v_identity_conflict, v_identity_surface_status, v_person_canonical` — i.e. the whole view layer exists to reconcile the communications identity problem.

### 7.2 How the sizes below were obtained — and their exact meaning

**`MAX(rowid)` is an upper bound on the row count, not the row count.** A table with 10,000 inserted and 5,000 deleted rows reports 10,000. Every figure in 7.3–7.4 is `SELECT COALESCE(MAX(rowid),0)`, chosen because it is O(1)-ish on the btree and therefore safe on a 95%-full 2-vCPU box where a `COUNT(*)` over `dsh_session_events` would scan 2.1 M rows. Where I also have a true `COUNT(*)` from another measurement in this report, I give both so the divergence is visible:

| table | `MAX(rowid)` | true `COUNT(*)` | gap |
|---|---:|---:|---:|
| `tasks` | 28,531 | **28,513** | 18 |
| `memories` | 25,059 | **25,049** | 10 |
| `procedural_experiences` | 33,503 | **18,526** | **14,977** (the `_MAX_EXPERIENCES_PER_AGENT=500` prune) |
| `work_sessions` | 78,619 | **78,566** | 53 |
| `goal_steps` | 47,845 | **47,812** | 33 |
| `goal_plans` | 35,654 | **35,652** | 2 |
| `tick_telemetry` | 34,215 | **34,213** | 2 |
| `work_order_executions` | 11,525 | **11,483** | 42 |
| `job_queue` | 87,184 | **87,135** | 49 |

So the rowid figures are a *ranking* instrument; the true counts are the ones to quote. `comms_identity_link`'s `MAX(rowid)` = **4,475,551** is the highest number in the database and is a churn artefact of a table that is being rewritten, not a 4.4 M-row table — no true count was taken for it, so its real size is **NOT DETERMINED**.

**What was measured and what was skipped.** 212 of the 235 tables were measured. 22 were skipped **by construction, not by failure**: `memory_vectors` (vec0) and `dsh_session_events_fts`, `memories_fts`, `vscode_chat_sessions_fts` are `CREATE VIRTUAL TABLE`s, and the FTS shadow tables (`*_fts_data`, `*_fts_idx`, `*_fts_docsize`, `*_fts_config`, `*_fts_content`, `project_knowledge_fts*`) have no `rowid`. `memory_vectors` genuinely cannot be counted from the `sqlite3` CLI at all — `SELECT COUNT(*) FROM memory_vectors` → `Error: in prepare, no such module: vec0`; its **10,725** figure (section 5.6) comes from the shadow table `memory_vectors_rowids`. Per-table **byte sizes are NOT DETERMINED**: `dbstat` is forbidden on this host.

### 7.3 The tables that matter, grouped by purpose

All 235, each assigned to exactly one group.

**A. Work, tasks, goals, missions, jobs (24)** — `tasks`, `task_outcome_signals`, `work_item`**(0)**, `work_sessions`, `work_order_executions`, `standing_work_orders`, `job_queue`, `deferred_llm_work`, `attempt`**(0)**, `goal_plans`, `goal_steps`, `missions`, `project_mission_map`, `project_task_map`, `progress_checkpoints`, `step_trigger_state`**(0)**, `trigger_dedup_log`**(0)**, `trigger_goal_templates`**(0)**, `obligation_registry`, `obligation_raises`, `reminders`, `reconciliation_runs`, `reconciliation_proposals`, `research_jobs`.

**B. Agents, workforce, org, rules, budget (21)** — `agent_budgets`**(0)**, `agent_metrics`, `agent_questions`, `agent_reflections`**(0)**, `agent_routing_rules`**(0)**, `agent_rules`, `agent_working_memory`, `blocked_agents`**(0)**, `cognitive_decisions`, `delegations`, `delegation_execution_log`**(0)**, `rule_applications`**(0)**, `behavioral`-adjacent `autonomy_levels`, `identity_surface_meta`, `person_canonical`, `person_phone`, `human_jobs`, `vp_inbox`, `lost_and_found`, `operation_journal`, `purchases`.

**C. Communications — Dialpad (the live business line), 21 tables** — `dialpad_call_full`, `dialpad_call_link`, `dialpad_call_reconciliation_run`, `dialpad_call_retranscript`, `dialpad_digital_session`, `dialpad_entity`, `dialpad_media_download_attempt`, `dialpad_media_file`, `dialpad_sms_cache`, `dialpad_stats_export`, `dialpad_stats_record`, `dialpad_transcript_cache`, `dialpad_ui_call_row`, `dialpad_ui_contact_row`, `dialpad_ui_history_row`, `dialpad_ui_message_body_row`, `dialpad_ui_message_row`, `dialpad_ui_message_thread_harvest`, `dialpad_ui_snapshot`, `dialpad_ui_voicemail_row`, `dialpad_ui_xhr`.

**D. Communications — Twilio (**the collapsed lineage**), 6 tables** — `call_log`, `sms_log`, `sms_media`, `sms_opt_outs`**(0)**, `contacts`, `contact_interactions`. *(`comms_identity_link` sits across C and D and is the only join between them.)*

**E. Communications — other channels, 6** — `google_voice_secretary_health`, `google_voice_secretary_log`, `voice_handoff_requests`**(0)**, `voice_notes`**(0)**, `voice_recordings`, `voice_transcripts`.

**F. Owner channel, 13** — `owner_assumptions`, `owner_attention_findings`, `owner_attention_runs`, `owner_decision_queue`, `owner_feedback_events`, `owner_message_queue`, `owner_profile`, `owner_profile_v2`, `owner_state`, `owner_text_decision`, `owner_text_suppression`, `owner_text_turn`, `owner_weekly_feedback`**(0)**.

**G. Email, 9** — `email_catalog`, `email_drafts`, `email_sender_signals`, `email_sync_runs`, `email_thread_state`, `email_triage_log`, `briefing_log`**(0)**, `event_triage_log`, `next_stage_email_hubs`.

**H. Memory and knowledge, 15** — `memories`, `memory_entries`**(0)**, `memory_vectors`(+ `_chunks`, `_info`, `_rowids`, `_vector_chunks00`), `memory_write_outcomes`, `memories_fts`(+ shadows), `procedural_experiences`, `knowledge`**(0)**, `knowledge_triples`, `kg_nodes`, `kg_edges`, `proactive_insights`, `proactive_events`, `discovered_sources`**(0)**, `skill`-adjacent `creativity_proposals`, `proposal_history`. *(Full per-store treatment in section 5.10.)*

**I. Model / AI gateway / routing / cost, 15** — `model_registry`, `model_aliases`, `model_usage`, `model_routing_log`**(0)**, `model_pricing_history`, `model_quality_scores`, `model_ops_findings`, `smart_router_decisions`, `ai_cost_snapshots`, `ai_cache_events`, `ai_gateway_fallback_chains`, `ai_response_cache`**(0)**, `gateway_trace_span`, `provider_health_events`, `settings_overrides`.

**J. Telemetry, audit and health, 17** — `tick_telemetry`, `tick_activity`, `activity_log`, `anomaly_log`, `error_log`, `policy_audit_log`, `mashgiach_audit_log`, `mashgiach_dept_scores`, `circuit_breaker_events`, `circuit_breaker_state`**(0)**, `operation_journal` *(counted once, in B)*, `company-outcome`-adjacent `evolution_log`, `evolution_changelog`, `evolution_verification`, `budget_tier_approvals`, `action_approval_queue`, `coding_approvals`, `doc_registry`.

**K. DSH and VS Code session archive, 11** — `dsh_sessions`, `dsh_session_events`, `dsh_session_events_fts`(+ 5 shadows), `dsh_session_exports`, `vscode_chat_sessions`, `vscode_chat_sessions_fts`(+ 5 shadows), `vscode_chat_messages`, `vscode_chat_exports`. *(Newest `dsh_sessions.ingested_at` 2026-10-14T01:02:56Z; `dsh_session_events` 2,147,367 rows — section 8.5.)*

**L. Projects and code, 12** — `projects`, `project`**(0)**, `project_contexts`, `project_events`, `project_knowledge`, `project_knowledge_fts`(+ shadows), `project_conversation_map`**(0)**, `projects`*, `repo_registry`, `website_sync_cursor`, `website_write_log`, `coding_sessions`, `coding_session_turns`. *(Deploy/CI tables absent: `data/code_snapshots/` and `data/code_proposals.json` are files, not tables — section 9.)*

**M. Finance and commerce, 14** — `plaid_accounts`, `plaid_items`, `plaid_transactions`, `plaid_ingest_cursor`, `plaid_sync_cursors`, `bills`, `purchases` *(counted in B)*, `spend_requests`**(0)**, `pricing_history`**(0)**, `pricing_trends`**(0)**, `parts_inventory`, `prod_customer_mirror`, `customer_stall_alerts`, `reconciliation_proposals` *(counted in A)*.

**N. Devices, MDM, fleet, home, life, 12** — `mdm_device_locations`**(0)**, `mdm_fleet_devices`, `waze_mdm_devices`, `life_domains`, `calendar_events`, `credentials`**(0)**, `equipment`-adjacent `parts_inventory` *(counted in M)*, `captures_inbox`, `web_sessions`**(0)**, `source_watchers`**(0)**, `next_stage_system_inventory`, `next_stage_node_reports`, `next_stage_machine_access_checks`, `next_stage_world_events`, `next_stage_comms_learning_events`**(0)**, `next_stage_remote_command_audit`**(0)**.

**O. Watch party (a whole dormant feature), 7** — `watch_bookmarks`**(0)**, `watch_chat_messages`**(0)**, `watch_comments`**(0)**, `watch_history`**(0)**, `watch_rooms`**(0)**, `watch_videos`**(0)**. The routes for it exist (`app/watch_party/routes.py`, 17 decorators) and every table is empty.

**P. Junk / test / framework leftovers, 15** — `_health_write_probe`**(1)**, `_locktest`**(0)**, `sqlite_sequence`, `events`**(0)**, `note`**(0)**, `routing_log`**(0)**, `conversations`, `vscode`*, `web_sessions`*(counted in N)*, `phone_chat_messages`**(1)**, `family`-adjacent `phone_chat_messages`, `briefing_log`, plus the three empty generically-named tables above. `_health_write_probe` and `_locktest` are **write probes left in the production schema** — a 1-row and a 0-row table whose only purpose is to prove the database is writable.

### 7.4 The biggest tables by row count

Top 45 of the 212 measured, **ranked by `MAX(rowid)`** (so: an upper bound; see 7.2 for the true counts where I have them) [M]:

| # | table | MAX(rowid) | # | table | MAX(rowid) |
|---:|---|---:|---:|---|---:|
| 1 | `comms_identity_link` | 4,475,551 | 24 | `procedural_experiences` | 33,503 |
| 2 | `dsh_session_events` | 2,160,894 | 25 | `tasks` | 28,531 |
| 3 | `dialpad_sms_cache` | 1,125,482 | 26 | `agent_working_memory` | 27,119 |
| 4 | `gateway_trace_span` | 615,178 | 27 | `ai_cost_snapshots` | 27,026 |
| 5 | `model_usage` | 336,945 | 28 | `memories` | 25,059 |
| 6 | `activity_log` | 329,935 | 29 | `memory_vectors_rowids` | 25,059 |
| 7 | `tick_activity` | 317,725 | 30 | `owner_attention_findings` | 24,120 |
| 8 | `policy_audit_log` | 255,197 | 31 | `next_stage_machine_access_checks` | 21,138 |
| 9 | `dialpad_stats_record` | 178,893 | 32 | `dialpad_ui_xhr` | 15,783 |
| 10 | `provider_health_events` | 109,152 | 33 | `dialpad_ui_call_row` | 15,596 |
| 11 | `progress_checkpoints` | 103,267 | 34 | `dialpad_ui_message_row` | 14,516 |
| 12 | `job_queue` | 87,184 | 35 | `dialpad_call_full` | 14,429 |
| 13 | `smart_router_decisions` | 87,030 | 36 | `plaid_transactions` | 13,848 |
| 14 | `work_sessions` | 78,619 | 37 | `work_order_executions` | 11,525 |
| 15 | `mashgiach_dept_scores` | 75,857 | 38 | `dialpad_media_download_attempt` | 10,866 |
| 16 | `customer_stall_alerts` | 64,736 | 39 | `dialpad_ui_history_row` | 10,703 |
| 17 | `goal_steps` | 47,845 | 40 | `next_stage_world_events` | 10,501 |
| 18 | `mashgiach_audit_log` | 38,779 | 41 | `model_registry` | 9,590 |
| 19 | `proactive_events` | 37,720 | 42 | `dialpad_ui_message_body_row` | 9,303 |
| 20 | `website_write_log` | 37,560 | 43 | `owner_text_decision` | 9,209 |
| 21 | `goal_plans` | 35,654 | 44 | `project_task_map` | 8,562 |
| 22 | `cognitive_decisions` | 34,780 | 45 | — | — |
| 23 | `tick_telemetry` | 34,215 | | | |

**By bytes: NOT DETERMINED.** `dbstat` is forbidden on this host (register §4 trap 2, and the brief's heavy-work rule). What is available cheaply is the whole-file size — `/root/authority.db` = **26,783,068,160 bytes** — and the file growth rate the baseline measured as 2.3 MB/h (`docs/dsh-evolution/30-systems-and-autonomy-audit.md:20`). `page_count`/`freelist_count` via `PRAGMA` would give free space, not per-table bytes; I did not run it.

### 7.5 Tables that look abandoned

Measured `MAX(rowid) = 0`, i.e. **never had a row** (or every row deleted), 63 tables — including several that a reader would assume are load-bearing [M]:

`_locktest`, `agent_budgets`, `agent_reflections`, `agent_routing_rules`, `ai_response_cache`, `attempt`, `blocked_agents`, `briefing_log`, `circuit_breaker_state`, `credentials`, `delegation_execution_log`, `discovered_sources`, `events`, `knowledge`, `mdm_device_locations`, `memory_entries`, `next_stage_comms_learning_events`, `next_stage_remote_command_audit`, `note`, `outbound_buffer`, `owner_weekly_feedback`, `pricing_history`, `pricing_trends`, `project`, `project_conversation_map`, `project_mission_map`, `routing_log`, `rule_applications`, `sms_opt_outs`, `source_watchers`, `spend_requests`, `step_trigger_state`, `trigger_dedup_log`, `trigger_goal_templates`, `voice_handoff_requests`, `voice_notes`, `watch_bookmarks`, `watch_chat_messages`, `watch_comments`, `watch_history`, `watch_rooms`, `watch_videos`, `web_sessions`, `work_item`.

Three of these deserve naming because the writer exists and is reachable: `knowledge` and `memory_entries` (section 5.0 — dead `upsert_knowledge` / `store_memory_entry`), and `credentials` (**0 rows** — whatever was meant to hold credential metadata holds nothing).

Near-empty (`1`–`5` rows) [M]: `_health_write_probe`(1), `calendar_events`(1), **`evolution_changelog`(1)**, `owner_text_suppression`(1), `phone_chat_messages`(1), `coding_approvals`(2), `google_voice_secretary_health`(2), `next_stage_email_hubs`(2), `owner_state`(2), `waze_mdm_devices`(2), `website_sync_cursor`(3), `budget_tier_approvals`(4), `human_jobs`(4), `mdm_fleet_devices`(4), `memory_vectors_info`(4), `missions`(4→**3 true**), `deferred_llm_work`(5), `dialpad_call_reconciliation_run`(5), `doc_registry`(5), `plaid_items`(5), `plaid_sync_cursors`(5).

**Abandoned by freshness rather than by emptiness** (from measurements elsewhere in this report): `project_knowledge` — 303 rows, newest **2026-07-02** (103 days); `evolution_changelog` — 1 row, 2026-04-22 (175 days); `project_knowledge`'s writer is only reachable by HTTP (5.9). The `coding_*` trio (14/14/2 rows) is entirely 2026-03-22.

### 7.6 Tables that look duplicated

| duplicate pair/group | evidence |
|---|---|
| **`contacts`/`call_log`/`sms_log` (Twilio, frozen) vs `dialpad_entity`/`dialpad_call_full`/`dialpad_sms_cache` (Dialpad, live)** | two complete communications lineages in one database. `comms_identity_link` (MAX(rowid) 4.4 M) is the join. The 9 views in 7.1 exist to reconcile them (`v_dialpad_dup_row`, `v_identity_conflict`, `v_contact_duplicate`). The Dialpad tables hold the live data — `dialpad_sms_cache` 1,125,482 vs `sms_log` 70 rows [M]. |
| `project` (0) vs `projects` (43) | singular/plural pair; the singular is empty |
| `knowledge` (0) vs `knowledge_triples` (38) vs `kg_nodes` (2,544)/`kg_edges` (2,172) vs `project_knowledge` (303) | four different "knowledge" stores |
| `memories` (25,049) vs `memory_entries` (0) vs `project_knowledge` (303) vs `agent_working_memory` (27,119 via rowid) vs `procedural_experiences` (18,526) | five memory stores; two are addressed by the **same** `memory_vectors` vec0 table through different joins (5.10) |
| `agent_rules` (170) vs `agent_routing_rules` (0) vs `rule_applications` (0) | three rule tables, two empty |
| `tasks` (28,513) vs `work_item` (0) vs `job_queue` (87,135) vs `deferred_llm_work` (5) vs `work_sessions` (78,566) vs `work_order_executions` (11,483) vs `goal_steps` (47,812) | seven work-item stores with overlapping semantics |
| `attempt` (0), `events` (0), `note` (0), `web_sessions` (0), `routing_log` (0) | five generically-named empty tables |
| `mdm_device_locations` (0) vs `mdm_fleet_devices` (4) vs `waze_mdm_devices` (2) | three device tables, two with a handful of rows |
| `_health_write_probe` (1) and `_locktest` (0) | production-schema write/probe leftovers |
| the `next_stage_*` family | 7 tables on one prefix, 2 empty, 2 large (21,138 / 10,501) — a staging namespace that never got renamed |
| the `watch_*` family | 7 tables, all 0 rows, with 17 live HTTP routes (`app/watch_party/routes.py`) |

**Row-count caveat for this whole section:** everything in 7.3–7.6 is `MAX(rowid)`, an upper bound. Only the tables listed in 7.2 have a true `COUNT(*)` in this report.

---

## 8. Interfaces

### 8.1 HTTP

**665 route decorators** across 5 files [M]: `app/main.py` **623**, `app/watch_party/routes.py` 17, `app/api/vehicle.py` 11, `app/family_chat/routes.py` 8, `app/api/calls.py` 6. Methods: 377 `get`, 270 `post`, 11 `delete`, 5 `patch`, 2 `put`. (The brief's "618 routes" is in the right neighbourhood; the decorator count is 665 and some decorated handlers may be shadowed by later duplicates.)

By first path segment [M], top 20:

| prefix | n | prefix | n |
|---|---:|---|---:|
| `/api` | 193 | `/autopilot` | 11 |
| `/ceo` | 51 | `/owner` | 11 |
| `/agents` | 34 | `/goals` | 10 |
| `/webhook` | 22 | `/events` | 10 |
| `/finance` | 15 | `/google-voice` | 9 |
| `/models` | 15 | `/calendar` | 9 |
| `/company` | 13 | `/ha` | 8 |
| `/tools` | 13 | `/missions` | 7 |
| `/gmail` | 13 | `/cognitive` | 7 |
| `/voice` | 12 | `/metrics` | 6 |
| `/sms` | 12 | `/action-approvals` | 6 |

Process binding: `--host 127.0.0.1 --port 8002` with `--proxy-headers --forwarded-allow-ips=127.0.0.1` (`/etc/systemd/system/company-api.service`). The service unit carries a long comment explaining why those three flags are load-bearing (a public IPv4 must not see `0.0.0.0`; without the allow-list any peer could forge `X-Forwarded-For`). Public names [DOC, `docs/mesh/000-SYSTEMS-REGISTER.md:90-95`]: company API `https://api.abletelsolutions.com`, dashboard `https://ai.abletelsolutions.com`. Auth: `_dashboard_path_requires_api_key` (`app/main.py:358`), `_current_dashboard_api_key` (`:341`), header `x-ps-api-key`; loopback is trusted (`:376-384`).

### 8.2 MCP

`app/services/mcp_manager.py` (301 lines): `class MCPServerConfig` (`:35`), `class MCPManager` (`:63`) with `connect`, `disconnect_all` (`:163`), `get_all_tools` (`:199`), `connected_servers` (`:249`), `get_mcp_manager()` (`:271`), `async setup_mcp_servers(settings)` (`:282`) which is what startup would call. **`MCP_ENABLED=false` (`/opt/company/.env:262`, comment: *"Enable MCP server lifecycle management. Requires `mcp` pip package."*)** [M]. Referenced from `app/config.py`, `app/database.py`, `app/config_contract.py`, `app/integrations_contract.py` and `app/services/quickbooks_service.py`. **MCP is configured and present in code, and switched off in the live environment.**

### 8.3 The dashboard

`secretary-dashboard.service` — **loaded active running** on the authority [M]: *"Personal Secretary Dashboard (Next.js)"*. `DASHBOARD_PORT=3000` (`.env:11`). The Next.js source is `/opt/company/apps/rentals/` (`app/`, `components/`, `Dockerfile`, `.env.example`). CORS allows the dashboard origin to call the API (`.env:43`, `:318-319`). `cloudflared.service` is running and its unit description is *"Cloudflare Tunnel (secratary-cloud: the company API and dashboard)"* [M].

### 8.4 SMS, email and voice

| channel | entry point | file:line |
|---|---|---|
| Twilio SMS in | `POST /webhook/twilio/sms` | `app/main.py:4091` |
| Twilio status callback | `POST /webhook/twilio/status` | `:6366` |
| Twilio voice in | `POST /webhook/twilio/voice` | `:5178` |
| Twilio voice gather | `POST /webhook/twilio/voice/gather` | `:5344` |
| Twilio voice bridge wait / dial result / status / recorded | `:5369`, `:5391`, `:5411`, `:5746` | |
| voice media + TTS | `GET /voice/streams` `:5699`, `/voice/streams/{filename}` `:5725`, `/voice/recordings` `:5936`, `/voice/tts/{filename}` `:5965`, `/voice/health` `:1649` | |
| voice bridge approval | `GET|POST /voice/bridge/{request_id}/approve|reject` `:1750, :1773, :1796, :1811`; `GET /voice/bridge/requests` `:1710`; `GET /voice/disaster-fallback/twiml` `:1691` | |
| SMS outbound + management | `POST /sms/send` `:6064`, `GET /sms/status/{sid}` `:6105`, `/sms/threads` `:6122`, `/sms/thread/{phone:path}` `:6140`, `/sms/log` `:6300`, `/sms/stats` `:6316`, `/sms/templates` `:6322/6328`, `/sms/opt-out` `:6339`, `/sms/opt-outs` `:6359`, `GET /sms/media/{filename}` `:5986` | |
| voice notes | `POST /voice-notes/send` `:6016`, `GET /voice-notes` `:6040`, `/voice-notes/stats` `:6055` | |
| Dialpad | `POST /webhook/dialpad/sms` `:6503`, `POST /webhook/dialpad/call` `:6546` | |
| Gmail | `GET/POST /gmail/*` 13 routes | `app/main.py`, `app/chat_action_gmail.py` |
| Google Voice | `/google-voice/*` 9 routes; `_maybe_run_google_voice_secretary` `app/autopilot.py:10950` | |
| GitHub | `POST /webhook/github` `:8605` | |
| Home Assistant | `POST /webhook/ha/push-to-talk` `:8659`, `/webhook/ha/security-alert` `:8684`, `GET /webhook/ha/security-media/{filename}` `:8905` | |

Live comms tables and their freshest rows are covered in section 7. `comms_identity_link` plus views `v_dialpad_calls`, `v_dialpad_sms`, `v_dialpad_comms_coverage`, `v_contact_duplicate`, `v_identity_conflict`, `v_identity_surface_status`, `v_person_canonical` are the identity layer.

### 8.5 The mesh and DSH

| interface | evidence |
|---|---|
| `GET /mesh/health` | `app/main.py:1612` (the only `/mesh/*` route in `main.py`; `POST /mesh/run` is the HMAC surface per `docs/mesh/000-SYSTEMS-REGISTER.md:61` and lives in `packages/plugin-mesh-http` in the harness-config repo, not in this app) |
| `mesh-broker.service` | **loaded active running** on the authority, described as *"mesh broker - placement decisions for the DSH mesh (never refuses; queues instead)"* [M] — this contradicts `docs/mesh/000-SYSTEMS-REGISTER.md:59`, which was measured 2026-10-11 as *"`mesh-broker.service` on the OFFICE box `secratary`, loopback `:3091`… the cloud's `mesh-broker.service` is `inactive`/`disabled`"*. The state changed between 10-11 and 10-14. |
| DSH session ingest | `POST` handler `api_owner_dsh_sessions_ingest` (`app/main.py:22908`), token gate `_require_dsh_session_access` (`:22887`) / `_current_dsh_session_ingest_token` (`:22871`), stats `api_owner_dsh_sessions_stats` (`:22925`), implementation `app/services/dsh_session_ingest.py` |
| session archive | `dsh_sessions` **7,148** rows, newest `ingested_at` **2026-10-14T01:02:56Z**; `dsh_session_events` **2,147,367** rows; `vscode_chat_sessions` **1,608**; `vscode_chat_messages` **4,373** [M]. An FTS5 mirror exists (`dsh_session_events_fts` + its 5 shadow tables, and `vscode_chat_sessions_fts*`) |
| phone | `phone-engine.service`, `phone-gate.service`, `phone-redirector.service` all **loaded active running** [M] |

Other live services on the authority [M]: `company-api`, `cloudflared`, `cron`, `fail2ban`, `atd`, `chrony`, `rsyslog`, `systemd-*`, `qemu-guest-agent`. Timers [M]: `authority-deadman.timer` (5 min), `estate-monitor.timer` (2 min), `estate-alerts-to-journal.timer` (2 min), `transcript-archive-pull.timer`, `authority-report-offsite-age.timer`, `company-outcome-monitor.timer`, `deployed-drift-check.timer`, `authority-offsite-backup.timer`, `authority-data-offsite.timer`, `lpt-email-sweep.timer`, `lpt-marketplace-orders.timer`, `lpt-owner-attention.timer`. `crontab -l` on the authority holds **~44** entries, each wrapped in `cron-wrap.sh <name> <base64>` (e.g. `*/5 * * * * cron-wrap.sh sms-inbox …`, `*/15 * * * * cron-wrap.sh disk-guard …`, `* * * * * cron-wrap.sh wake-fanout …`, `*/5 * * * * cron-wrap.sh run-sentinel …`) [M].

---

## 9. What runs the company when it writes code to itself

`app/code_self_edit.py` — **2,020 lines**.

### 9.1 What it can change

- `propose_code_changes(instruction, …)` (`:1193`) asks an LLM for a unified diff against named files and stores it as a proposal.
- `apply_proposal(...)` (`:1560`) writes the change.
- `apply_proposal_isolated(...)` (`:1824`) writes into a throwaway copy.
- Snapshot/rollback: `_save_snapshot` (`:100`) into `_SNAPSHOT_DIR = "data/code_snapshots"`, `_MAX_SNAPSHOTS = 50` (`:27-28`), `_restore_snapshot` (`:161`), `list_snapshots` (`:200`), `restore_last_known_good` (`:224`).
- Validators for other stacks: `_validate_typescript` (`:1901`), `_validate_next_build` (`:1950`), `_resolve_node_command` (`:1989`).
- LLM backends it can call directly: `_call_copilot` (`:493`), `_call_deepinfra` (`:542`), `_call_deepseek` (`:597`), `_call_openai` (`:636`), `_call_anthropic` (`:676`) — i.e. it does not go only through `ai_gateway`; it has its own provider clients.
- Spend is attributed to its own agent: `_USAGE_AGENT_ID = "self_improvement"`, `_USAGE_TASK_TYPE = "code_proposal"` (`:49-50`).

### 9.2 How it is gated

Five distinct gates:

1. **The live checkout is refused unconditionally.** `guard_write_root()` (`:320-351`): *"the running checkout is refused unconditionally -- even if somebody marked it, nothing may write into the tree the API is serving out of"*, raising `LiveCheckoutWriteRefused`; `_LIVE_CHECKOUT_ROOT = Path(__file__).resolve().parents[1]` (`:40`).
2. **Any other root must carry a sentinel.** `_ISOLATION_SENTINEL = ".code_edit_isolated"` (`:39`), written only by `make_isolated_apply_root()` (`:351`); `guard_write_root` refuses a root without it.
3. **Path deny-list.** `_DENY_PREFIXES` (`:71-89`): `.git/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `node_modules/`, `data/secretary.db`, `data/secretary.sqlite`, `data/secretary.sqlite3`, `requirements`, `pyproject.toml`, `setup.py`, `setup.cfg`, `dockerfile`, `docker-compose`, `makefile`, `alembic/`, `.github/`. `_is_denied_rel_path` (`:266`) additionally refuses any `..` traversal, an absolute path, `.env`, and any `.env.*` except `.env.example`, and calls `_is_vendored_rel_path` (`:252`) at any depth. **But `_is_allowed_rel_path` (`:292`) then returns `True` for everything not denied** — its own comment says *"Full access mode — no restrictions beyond path-escape and .git"*.
4. **The auto-apply flag is off.** `CODE_EDIT_AUTO_APPLY=false` (`/opt/company/.env:123`), with `CODE_EDIT_AUTO_APPLY_MAX_DIFF_LINES=140` (`:124`), `CODE_EDIT_MODE=trusted` (`:119`), `CODE_EDIT_MAX_TARGET_FILES=8` (`:120`), `CODE_EDIT_MAX_FILE_CHARS=200000` (`:121`), `CODE_EDIT_ALLOW_CREATE_FILES=true` (`:122`). The module's own comment (`:33-36`) records that this has been false *since 2026-06-12* and why.
5. **Deduplication / cost gates.** `proposal_key` (`:1032`), a bounded offer ledger `_MAX_TRACKED_KEYS = 500` (`:46`) with `offer_keys` / `dedup_keys` / `noop_keys` (`:1064-1136`), and three refusal statuses returned with `refused: True` and `model_calls: 0`: `noop_refused` (`:1271`, `:1450`), `duplicate_refused` (`:1310`), and a pre-flight refusal at `:1594-1602` with `error_stage: "apply_root_refused"`.

Its autonomy row is `code_edit {"max": 3, "default": 3}` (`app/services/autonomy.py:167-172`).

### 9.3 Has it ever run?

| evidence | reading |
|---|---|
| `evolution_changelog` | **exactly 1 row** [M], `2026-04-22T15:40:07.699984+00:00`, `agent_id='orchestrator'`, `file_path='app/database.py'`, `change_summary='Add vp_inbox + evolution_changelog tables and helpers (Round 2 A1.C, B1)'`, **`commit_sha` NULL**, `rolled_back=0`. No row since 2026-04-22 — 175 days. The module's own comment (`:35-38`) states the same: *"CODE_EDIT_AUTO_APPLY has been false since 2026-06-12 (evolution_changelog holds 1 row with commit_sha NULL since 2026-04-22)"*. |
| `data/code_proposals.json` | **1,351,902 bytes**, keys `proposals` (**25**), `offer_keys` (**82**), `dedup_keys` (**96**), `noop_keys` (**22**) [M]. The `noop_keys` count is the measured number of times the model was asked and returned the file byte-identical. |
| `data/code_snapshots/` | exists, populated; newest snapshots are dated **April 2026** (e.g. `3ea51ce4761a.json`, 2026-04-16 19:56, `391cdc67a83a.json` 2026-04-01) [M] — consistent with proposals being generated and snapshotted, not applied. |
| `model_usage` for `agent_id='self_improvement'` | **486** calls, 8,641,604 tokens, **$1.4845**, span 2026-09-15T21:12Z → **2026-10-11T19:26:26Z** [M]. So `code_self_edit` *has* been exercised as a proposer, most recently 2026-10-11. |
| related evolution spend | `dept_evolution_reliability` 9,251 calls / $31.8023 (newest 2026-10-13T19:38Z), `evolution_architect` 3,511 / $9.1517 (newest 2026-10-13T20:12Z) [M] |
| `coding_approvals` / `coding_sessions` / `coding_session_turns` | 2 / 14 / 14 rows [M]. All sessions are from **2026-03-22**, all in `C:\Users\ezabz\AppData\Local\Temp\psmvp-d018-*` temp paths, all `status='active'` with `turn_count=1`, `total_cost=0.0`, and summaries recording `Turn 1 failed: Copilot chat/completions request failed with status 400 … 'tools[0].function.name': empty string`. The 2 approvals are `npm install left-pad` smoke tests (one `pending` since 2026-03-22, one `rejected`). These are a **different, older subsystem** (`coding_*`), not `code_self_edit`. |

**Answer: it has proposed many times and applied essentially never.** Zero `evolution_changelog` rows in 175 days, `CODE_EDIT_AUTO_APPLY=false`, and the live checkout is refused by construction. The one recorded change is dated 2026-04-22 with no commit. The 22 `noop_keys` and 96 `dedup_keys` are the measured record of proposals that were generated, deduplicated, or came back unchanged.

---

## WHAT I COULD NOT DETERMINE

1. **`docs/dsh-evolution-v2/PROGRAM.md`** — NOT DETERMINED. Tried: `Test-Path` on the brief's path (absent); `Get-ChildItem docs -Recurse -Filter *.md` in `C:\Users\ezabz\code\harness-config` (no `dsh-evolution*` directory); `git log --all --diff-filter=A --name-only -- "docs/dsh-evolution-v2/*"` (empty — the path exists in **no** ref); `git ls-tree -r --name-only` for `main`, `master`, `fleet/dsh-docs`, `remotes/mirror/master` filtered on `dsh-evolution` (empty); `ls /root/code/harness-config/docs/` on the authority (no `dsh-evolution*`); `find / -maxdepth 6 -name "30-systems-and-autonomy-audit.md"` on the authority (nothing). The nearest surviving artefact is `docs/self-evolution/README.md` on the authority (2,305 bytes) — **not read in full, and not the same document.**
2. **`docs/dsh-evolution/30-systems-and-autonomy-audit.md` in the working tree** — NOT DETERMINED as a live file. It was recovered from git object `75ffbeef` and read in full; that is a committed object, not a checked-out file the brief's reader would find.
3. **Which subsystems are scheduled by *cadence* rather than by state** — PARTIALLY. I measured every subsystem's live `last_ran_at` / `successes` / `failures` / `last_status` and the five tick-cadence knobs (`company_tick_every`, `evolution_every`, `optimize_every`, `self_prog_every`, `ceo_tick_every`, `llm_checkin_every`, `world_context_every`). I did **not** enumerate the per-`_maybe_*` interval constant for every one of the 39 (e.g. `_maybe_capture_balances`, `_maybe_generate_spending_report`, `_maybe_deliver_notification_digest`), so the tick *interval* of each is not individually cited. `NOT DETERMINED — would require reading ~30 `_maybe_*` bodies; not attempted.`
4. **`model_usage.served_by`** — NOT DETERMINED. The column exists; `SELECT COALESCE(served_by,'(null)') … GROUP BY served_by` returned `(null)` for all 2,858 rows in the last 24 h. The actual upstream provider behind each OpenRouter-shaped id cannot be read from this table.
5. **Per-table byte sizes** — NOT DETERMINED for the large tables. `dbstat` is forbidden on this host (register §4 trap 2 and the brief's heavy-work prohibition), and per-table bytes need `dbstat`. What I could get is the whole-file size (26,783,068,160 bytes) and a row ranking by `MAX(rowid)` — section 7.2 states exactly what that number is and is not.
6. **Reconciliation of the two cost readings.** `model_usage` says $24.13 for the 24 h; `tick_telemetry.total_cost` says $0.1673 for the whole of 2026-10-13. Both are live reads of the same database. I did not determine whether `tick_telemetry` deliberately excludes the `vscode_gateway` path (949 calls, $0.8405) or whether one of the two is wrong. `NOT DETERMINED — the reconciliation would need the writer of each column, not read.`
7. **Whether the 28 DB-only autonomy actions are reachable.** I established that they are absent from `DEFAULT_MATRIX` and that `get_level` reads their DB row. I did not test whether each is also in the dispatcher chain — the name sets overlap but I did not compute the intersection exhaustively. `NOT DETERMINED — the intersection was not computed.`
8. **`work_metrics`** — confirmed absent again (`sqlite_master` has no such table); the baseline's finding reproduces.
9. **Whether `POST /mesh/run` exists on this app** — NOT DETERMINED. Only `GET /mesh/health` is decorated in `app/main.py:1612`; the register attributes `/mesh/run` to `packages/plugin-mesh-http` in the harness-config repo, which I did not open.
10. **What the dashboard actually shows** — NOT DETERMINED beyond "the service is running and the Next.js source is at `/opt/company/apps/rentals`". I did not read its pages or query it (the brief forbids browsers, and hitting an authenticated UI would be a write-path test).

---

## EVIDENCE LOG

Every command below was run by me on this thread against `secratary-cloud` over `ssh -o BatchMode=yes`, read-only, or against `/opt/company` on that host. `$DB` = `/root/authority.db`.

```
ssh -o BatchMode=yes -o ConnectTimeout=8 secratary-cloud 'hostname'                 # -> secratary-cloud
cd /opt/company; git rev-parse HEAD                                                  # -> db07e8e023d2f2720ccfa6b76b76bc99f08af414
cd /opt/company; git log -1 --format="%ci %s"                                        # -> 2026-10-14 00:28:56 +0000
find app -name "*.py" | wc -l                                                        # -> 323
ls app/services/ | wc -l                                                             # -> 257
ls -la /root/authority.db                                                            # -> 26783068160
df -h /                                                                              # -> /dev/sda1 75G 68G 4.1G 95%
sqlite3 --version                                                                    # -> 3.46.1 2024-08-13
sqlite3 -readonly $DB "SELECT type, COUNT(*) FROM sqlite_master WHERE type IN ('table','view') GROUP BY type;"   # -> table|235  view|9
sqlite3 -readonly $DB "SELECT COUNT(*) FROM sqlite_master;"                          # -> 662
sqlite3 -readonly $DB "SELECT COUNT(*) FROM autonomy_levels;"                        # -> 74
sqlite3 -readonly -header -column $DB "SELECT action_name,current_level,max_level,successes,failures,last_promoted_at,last_demoted_at,updated_at FROM autonomy_levels ORDER BY current_level DESC, action_name;"
sqlite3 -readonly $DB "SELECT current_level,max_level,COUNT(*) FROM autonomy_levels GROUP BY 1,2 ORDER BY 1;"
sqlite3 -readonly $DB "SELECT COUNT(*),SUM(last_promoted_at IS NOT NULL),SUM(last_demoted_at IS NOT NULL) FROM autonomy_levels;"   # -> 74|43|42
sqlite3 -readonly $DB "SELECT COUNT(*) FROM model_usage;"                            # -> 260256
sqlite3 -readonly -header -column $DB "SELECT provider||'/'||model AS model,COUNT(*) calls,SUM(total_tokens) tokens,ROUND(SUM(estimated_cost_usd),6) usd FROM model_usage WHERE created_at >= datetime('now','-24 hours') GROUP BY provider,model ORDER BY usd DESC;"
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) calls,SUM(total_tokens) tokens,ROUND(SUM(estimated_cost_usd),6) usd,SUM(success) ok FROM model_usage WHERE created_at >= datetime('now','-24 hours');"   # -> 2858|51766106|24.134569|2816
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*) calls,ROUND(SUM(estimated_cost_usd),6) usd FROM model_usage WHERE created_at >= datetime('now','-24 hours') GROUP BY agent_id ORDER BY usd DESC;"
sqlite3 -readonly -header -column $DB "SELECT COALESCE(served_by,'(null)'),COUNT(*),ROUND(SUM(estimated_cost_usd),6) FROM model_usage WHERE created_at >= datetime('now','-24 hours') GROUP BY 1;"   # -> (null)|2858|24.134569
sqlite3 -readonly -header -column $DB "SELECT tier,COUNT(*),ROUND(SUM(estimated_cost_usd),6) FROM model_usage WHERE created_at >= datetime('now','-24 hours') GROUP BY tier;"
sqlite3 -readonly -header -column $DB "SELECT provider||'/'||model,COUNT(*),ROUND(SUM(estimated_cost_usd),4) FROM model_usage GROUP BY 1 ORDER BY 3 DESC LIMIT 15;"
sqlite3 -readonly $DB "SELECT COUNT(*) FROM model_registry;"                         # -> 60
sqlite3 -readonly $DB "SELECT COUNT(*),SUM(is_deprecated=1),SUM(is_deprecated=0) FROM model_registry;"   # -> 60|54|6
sqlite3 -readonly $DB "SELECT COUNT(*) FROM model_aliases;"                          # -> 31
sqlite3 -readonly -header -column $DB "SELECT alias,canonical_id,source FROM model_aliases LIMIT 40;"
sqlite3 -readonly $DB "SELECT COUNT(*),MIN(started_at),MAX(started_at) FROM tick_telemetry;"   # -> 34213|<oldest>|2026-10-14T00:43:34Z
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),COUNT(DISTINCT agent_id),MIN(started_at),MAX(started_at) FROM tick_telemetry;"   # -> 34213|85|…
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*) n,SUM(steps_completed),SUM(total_tokens),ROUND(SUM(total_cost),4) FROM tick_telemetry WHERE started_at >= datetime('now','-24 hours') GROUP BY agent_id ORDER BY n DESC;"
sqlite3 -readonly -header -column $DB "SELECT outcome,COUNT(*) FROM tick_telemetry WHERE started_at >= datetime('now','-24 hours') GROUP BY outcome;"   # -> complete 142, error 11, suspended 8, escalate 4
sqlite3 -readonly -header -column $DB "SELECT substr(started_at,1,10) day,COUNT(*) ticks,SUM(outcome='complete'),SUM(outcome='error'),SUM(steps_completed),SUM(total_tokens),ROUND(SUM(total_cost),4) FROM tick_telemetry WHERE started_at >= datetime('now','-6 days') GROUP BY day ORDER BY day DESC;"
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),COUNT(DISTINCT agent_id),MIN(started_at),MAX(started_at) FROM work_sessions;"    # -> 78566|11|0|2026-10-14T00:59:51Z
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*) n,SUM(status='completed') done FROM work_sessions GROUP BY agent_id ORDER BY n DESC LIMIT 30;"   # -> orchestrator 78513
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*) FROM work_sessions WHERE started_at >= datetime('now','-7 days') GROUP BY agent_id ORDER BY 2 DESC;"   # -> orchestrator 824
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),COUNT(DISTINCT agent_id),COUNT(DISTINCT assigned_to) FROM tasks;"   # -> 28513|71|114
sqlite3 -readonly -header -column $DB "SELECT status,COUNT(*) FROM tasks GROUP BY status ORDER BY 2 DESC;"
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*) n FROM tasks WHERE status='open' GROUP BY agent_id ORDER BY n DESC LIMIT 15;"
sqlite3 -readonly -header -column $DB "SELECT COALESCE(assigned_to,'(null)') who,COUNT(*) FROM tasks GROUP BY who ORDER BY 2 DESC LIMIT 30;"
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),SUM(is_enabled=1) FROM standing_work_orders;"   # -> 34|24
sqlite3 -readonly -header -column $DB "SELECT last_run_status,COUNT(*) FROM standing_work_orders GROUP BY 1;"   # -> success 16, failed 9, skipped 9
sqlite3 -readonly -header -column $DB "SELECT id,department,schedule_type,interval_minutes,is_enabled,last_run_at,last_run_status FROM standing_work_orders ORDER BY department LIMIT 40;"
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),MIN(started_at),MAX(started_at) FROM work_order_executions;"   # -> 11483
sqlite3 -readonly -header -column $DB "SELECT status,COUNT(*) FROM work_order_executions GROUP BY status;"   # -> failed 7159, success 2758, skipped 1566
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM goal_plans;"             # -> 35652
sqlite3 -readonly -header -column $DB "SELECT status,COUNT(*) FROM goal_plans GROUP BY status;"   # -> failed 17617, completed 14562, cancelled 3463, active 10
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM goal_steps;"             # -> 47812
sqlite3 -readonly -header -column $DB "SELECT status,COUNT(*) FROM goal_steps GROUP BY status;"   # -> skipped 29714, completed 18014, failed 75, pending 7, running 2
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM missions; SELECT status,COUNT(*) FROM missions GROUP BY status;"   # -> 3, all active
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM job_queue; SELECT status,COUNT(*) FROM job_queue GROUP BY status;"   # -> 87135; completed 86128, failed 1007
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM agent_questions;"        # -> 532
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM blocked_agents;"         # -> 0
sqlite3 -readonly -header -column $DB "SELECT status,COUNT(*) FROM owner_decision_queue GROUP BY status;"   # -> resolved 229, pending 155, dismissed 71, answered 38
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),MIN(detected_at),MAX(detected_at) FROM anomaly_log;"   # -> 537|2026-04-21T22:52:13|2026-10-13T10:29:38
sqlite3 -readonly -header -column $DB "SELECT anomaly_type,escalation,COUNT(*),MAX(detected_at) FROM anomaly_log GROUP BY 1,2 ORDER BY 3 DESC;"
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),MAX(ingested_at) FROM dsh_sessions;"   # -> 7148|2026-10-14T01:02:56Z
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM dsh_session_events;"     # -> 2147367
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM vscode_chat_sessions;"   # -> 1608
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM vscode_chat_messages;"   # -> 4373
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM evolution_changelog; SELECT * FROM evolution_changelog;"   # -> 1 row, 2026-04-22, commit_sha NULL
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM coding_approvals; SELECT * FROM coding_approvals LIMIT 5;"   # -> 2
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM coding_sessions; SELECT * FROM coding_sessions LIMIT 3;"     # -> 14, all 2026-03-22
sqlite3 -readonly -header -column $DB "SELECT COUNT(*) FROM coding_session_turns;"   # -> 14
sqlite3 -readonly -header -column $DB "SELECT COUNT(*),SUM(total_tokens),ROUND(SUM(estimated_cost_usd),4),MIN(created_at),MAX(created_at) FROM model_usage WHERE agent_id='self_improvement';"   # -> 486|8641604|1.4845|2026-09-15T21:12Z|2026-10-11T19:26Z
sqlite3 -readonly -header -column $DB "SELECT agent_id,COUNT(*),ROUND(SUM(estimated_cost_usd),4),MAX(created_at) FROM model_usage WHERE agent_id LIKE '%self%' OR agent_id LIKE '%evolution%' GROUP BY agent_id;"
sqlite3 -readonly $DB ".schema autonomy_levels" ; ".schema tasks" ; ".schema work_sessions" ; ".schema tick_telemetry" ; ".schema model_usage" ; ".schema model_aliases" ; ".schema model_registry" ; ".schema anomaly_log" ; ".schema standing_work_orders" ; ".schema owner_decision_queue" ; ".schema evolution_changelog"

# source measurements (/opt/company)
grep -n "^[A-Za-z_].*=\|^class \|^def \|^# ---" app/company_blueprint.py | head -80
python3 -c "<AST parse of the DEPARTMENTS list literal>"                              # -> 28 entries
grep -n "CORE_DEPARTMENT_IDS" -A 16 app/company_blueprint.py                          # -> 14 ids, :1116
grep -n "FRONTIER_BOARD_AGENT_IDS" -A 6 app/company_blueprint.py                      # -> 3 ids, :1133
sed -n '1203,1235p' app/company_blueprint.py                                          # _department_ladder_agents -> []
sed -n '1738,1775p' app/company_blueprint.py                                          # build_org_hierarchy
python3 - <<'PY'  # identity-store census
import json,collections
d=json.load(open('/opt/company/data/agent_identities.json')); ag=d['agents']
print(len(ag)); print(collections.Counter(str(v.get('status')) for v in ag.values()))
PY
ls -la /opt/company/data/agent_identities.json                                         # -> 13988406 bytes, 2026-10-14 00:59
grep -n "identity_store_path" app/config.py                                           # -> :946 default data/agent_identities.json
wc -l app/autopilot.py app/services/agent_worker.py app/services/autonomy.py app/code_self_edit.py app/services/ai_gateway.py app/services/smart_router.py app/chat_action_runtime.py app/tool_factory.py app/workforce.py app/company_blueprint.py   # -> 11206 5220 629 2020 5663 3998 2678 2342 2211 1978
grep -n "^class \|^def \|^async def \|^    def \|^    async def " app/services/autonomy.py
sed -n '66,215p' app/services/autonomy.py                                             # DEFAULT_MATRIX, full
sed -n '285,440p' app/services/autonomy.py                                            # _ensure_table, get_level, should_execute
sed -n '478,535p' app/services/autonomy.py                                            # _try_promote / _try_demote
sed -n '572,629p' app/services/autonomy.py                                            # get_autonomy_matrix / get_autonomy_stats / set_level_override
python3 - <<'PY'  # matrix vs DB comparison
import re,sqlite3
...
PY
# -> DEFAULT_MATRIX 56; max<4 = 18; max<3 = 1; no_demote = 17; DB 74; DB-only 28; matrix-only 10; DB at L4 31; DB below L4 43
grep -n "    def \|    async def " app/autopilot.py | head -200
python3 - <<'PY'  # ordered self-calls inside run_once
import re
lines=open('/opt/company/app/autopilot.py').read().splitlines()
for i in range(5355,6922):
    m=re.match(r'\s+(?:await\s+)?(?:ok\s*=\s*)?self\.(_[a-z0-9_]+|[a-z0-9_]*)\(', lines[i])
    if m: print(i+1, m.group(1))
PY
# -> 54 self-calls; the ordered subsystem list in section 2.2
awk 'NR>=5356 && NR<=6922' app/autopilot.py | grep -n "── \|^            # "               # section banners
sed -n '749,800p' app/autopilot.py                                                    # AutopilotController.__init__ signature, interval_sec default 3600
sed -n '895,1020p' app/autopilot.py                                                   # cadence controls + per-subsystem toggles
sed -n '6922,7000p' app/autopilot.py                                                  # _loop, 5 s first-tick delay
sed -n '5356,5400p' app/autopilot.py                                                  # run_once head + re-entrancy guard
sed -n '5660,5700p' app/autopilot.py                                                  # company-tick block
grep -n "company_tick\|_process_work_queue\|work_mode" app/autopilot.py
sed -n '1320,1360p' app/workforce.py                                                  # company_tick head
grep -n "_worker_agents" app/workforce.py                                             # :1565-1567
sed -n '1575,1600p' app/workforce.py                                                  # productive_tick submission, :1582
sed -n '3804,3900p' app/services/agent_worker.py                                      # productive_tick head
grep -n "MAX_TOOL_ROUNDS" app/services/agent_worker.py                                # :66 = 5, :2704 bound
sed -n '2517,2600p' app/services/agent_worker.py                                      # _execute_llm_step
sed -n '2279,2300p' app/services/agent_worker.py                                      # _check_autonomy
sed -n '2396,2475p' app/services/agent_worker.py                                      # _execute_tool_with_autonomy
grep -n "def is_action_allowed" -A 4 app/services/department_tools.py                 # :1728
grep -n "TOOL_RUNTIME_REQUIREMENTS" -A 6 app/services/department_tools.py             # :1751
python3 - <<'PY'  # DEPARTMENT_TOOLS census
... # -> 18 department keys, 76 distinct tool names
PY
grep -n "action_name ==\|action_name in {" app/chat_action_runtime.py | head -80
grep -o 'action_name == "[a-z0-9_]*"' app/chat_action_runtime.py | sed 's/.*"\(.*\)"/\1/' | sort -u | wc -l   # -> 147
wc -l app/chat_action_runtime.py app/chat_actions.py                                  # -> 2678, 209
sed -n '1,130p' app/chat_actions.py                                                   # the compatibility facade
grep -n "_REGISTRY_PATH\|_save_registry" app/tool_factory.py                          # :35, :88 + 9 call sites
python3 -c "import json;d=json.load(open('/opt/company/data/tool_registry.json'));print(len(d['tools']),len(d['departments']),d['updated_at'])"   # -> 633 4 2026-10-14T00:58:44Z
ls -la /opt/company/data/tool_registry.json                                            # -> 404947 bytes
grep -n "def " app/chat_action_dynamic_tools.py                                       # :14,:65,:104,:141,:181
grep -n "^class \|^def \|^[A-Z_][A-Z0-9_]* *[:=]" app/services/smart_router.py | head -50
grep -n "_APPROVED_PROVIDERS = frozenset" -A 4 app/services/smart_router.py            # :820-822
grep -n "^class \|^def \|^[A-Z_][A-Z0-9_]* *[:=]" app/services/ai_gateway.py | head -50
grep -n "_DELEGATE_DEFAULT" app/services/ai_gateway.py                                 # :447 literal model id
grep -rEo '"(deepseek|openai|anthropic|google|openrouter|moonshotai|x-ai|xiaomi|minimax|copilot)/[A-Za-z0-9._-]+"' app/ --include=*.py | wc -l   # -> 181
grep -rlE '"(deepseek|openai|anthropic|google|openrouter|moonshotai|x-ai|xiaomi|minimax|copilot)/[A-Za-z0-9._-]+"' app/ --include=*.py          # -> 13 files
python3 - <<'PY'  # smart_router table sizes
... # -> _CAPABILITY_DB 34, _COPILOT_EQUIVALENTS 12, _TASK_CAPABILITY_REQUIREMENTS 56, _ROUTE_POLICIES 4, _ROLE_POLICIES 7, _TASK_ROLE_MAP 29, _GEMINI_LONGCTX_IDS 0, _DIRECT_DEEPSEEK_EQUIVALENTS 2
PY
grep -rEho '@(app|router)\.(get|post|put|patch|delete)\(' app/ --include=*.py | wc -l   # -> 665
grep -rEho '@(app|router)\.(get|post|put|patch|delete)\(' app/ --include=*.py | sed 's/.*\.//' | sort | uniq -c   # -> 377 get, 270 post, 11 delete, 5 patch, 2 put
python3 - <<'PY'  # route paths by first segment
... # -> /api 193, /ceo 51, /agents 34, /webhook 22, …; app/main.py 623
PY
grep -n "mesh/health\|/mesh/" app/main.py                                              # -> :1612
wc -l app/services/mcp_manager.py                                                      # -> 301
grep -n "MCP" .env                                                                     # -> :260-262 MCP_ENABLED=false
grep -n "dsh_session" app/main.py                                                      # -> :22871, :22887, :22908, :22925
grep -n "^class \|^def \|^async def \|^[A-Z_][A-Z0-9_]* *[:=]" app/code_self_edit.py | head -70
sed -n '1,60p' app/code_self_edit.py                                                    # isolation rationale
sed -n '71,96p' app/code_self_edit.py                                                   # _DENY_PREFIXES
sed -n '266,300p' app/code_self_edit.py                                                 # _is_denied_rel_path / _is_allowed_rel_path
sed -n '320,352p' app/code_self_edit.py                                                 # guard_write_root
grep -nE "CODE_EDIT|AUTO_APPLY" .env                                                    # :119-124
python3 -c "import json,os;p='/opt/company/data/code_proposals.json';d=json.load(open(p));print(os.path.getsize(p),len(d['proposals']),len(d['offer_keys']),len(d['dedup_keys']),len(d['noop_keys']))"   # -> 1351902 25 82 96 22
ls -la /opt/company/data/code_snapshots | head -20
systemctl cat company-api.service ; systemctl show company-api -p NRestarts,MemoryCurrent,MemoryMax,ActiveEnterTimestamp,MainPID
systemctl is-active company-api                                                        # -> active
systemctl list-timers --all --no-legend
systemctl list-units --type=service --state=running --no-legend
crontab -l
python3 - <<'PY'  # 39 subsystem_health entries
import json; d=json.load(open('/opt/company/data/autopilot_state.json'))
for k in sorted(d['subsystem_health']): print(k, d['subsystem_health'][k]['successes'], d['subsystem_health'][k]['last_ran_at'])
PY
ls -la /opt/company/data/ ; ls -la /opt/company/apps/rentals

# baseline document recovery (local, Windows)
cd C:\Users\ezabz\code\harness-config
git show 75ffbeef:docs/dsh-evolution/30-systems-and-autonomy-audit.md   # 177 lines, recovered into $TEMP
git show 75ffbeef:docs/dsh-evolution/PROGRAM.md                         # 6301 bytes
git log --all --diff-filter=A --name-only -- "docs/dsh-evolution-v2/*"  # empty
git ls-tree -r --name-only main -- docs | Select-String "dsh-evolution" # empty
```

### Section 7 (data model) evidence log

```text
sqlite3 -readonly /root/authority.db "SELECT type, COUNT(*) FROM sqlite_master WHERE type IN ('table','view') GROUP BY type;"   → table|235  view|9
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM sqlite_master;"   → 662
sqlite3 -readonly /root/authority.db "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name;"   → the 9 v_* views
sqlite3 -readonly /root/authority.db "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
# one generated UNION ALL of MAX(rowid) per table, run once, with virtual/FTS tables excluded:
python3 - <<'PY' > /tmp/dm.sql
import sqlite3,sys
con=sqlite3.connect('file:/root/authority.db?mode=ro',uri=True)
rows=con.execute("SELECT name, COALESCE(sql,'') FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
names=[n for n,s in rows if 'virtual table' not in s.lower() and '_fts' not in n.lower()]
parts=[f"SELECT '{n.replace(chr(34),chr(34)*2)}' AS t, (SELECT COALESCE(MAX(rowid),0) FROM \"{n}\") AS n" for n in names]
print(" UNION ALL ".join(parts) + " ORDER BY n DESC;")
PY
timeout 150 sqlite3 -readonly /root/authority.db < /tmp/dm.sql    → exit 0, 212 rows; measured 212, skipped 22
# -> top: comms_identity_link 4475551, dsh_session_events 2160894, dialpad_sms_cache 1125482,
#    gateway_trace_span 615178, model_usage 336945, activity_log 329935, tick_activity 317725, policy_audit_log 255197, …
# -> 63 tables returned 0; 21 tables returned 1..5
# FAILED ATTEMPTS, recorded because they define the limitation:
sqlite3 -readonly /root/authority.db < /tmp/dm.sql   (first version, all 233 tables)
   → Parse error near line 1: no such module: vec0            (memory_vectors is a vec0 virtual table)
sqlite3 -readonly /root/authority.db < /tmp/dm.sql   (second version, excluding 'virtual table')
   → Parse error near line 1: no such column: rowid          (vscode_chat_sessions_fts_idx is an FTS shadow table)
sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memory_vectors;"
   → Error: in prepare, no such module: vec0                 (so memory_vectors has no CLI-readable count)
# true COUNT(*) figures for the comparison table in 7.2 come from the commands logged in sections 1 and 5.
```

### Section 5 (memory) evidence log — delegated measurement, same thread, same host

```text
du -sh /opt/company/data/chromadb   → 2.9G
du -sh /opt/company/data/mem0   → 1.1G
du -sh /root/.mem0   → 3.0M
ls -la /opt/company/data/chromadb/chroma.sqlite3   → 2404261888 bytes, Oct 14 01:01
ls -la /opt/company/data/chromadb/chromadb/chroma.sqlite3   → 11280384 bytes, May 4 22:05
ls -la /opt/company/data/mem0/chroma.sqlite3   → 311074816 bytes, Oct 14 01:01
ls -la /root/.mem0/history.db   → 3072000 bytes, Oct 14 01:01
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings;"   → 393112
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chroma.sqlite3 "SELECT id,name FROM collections;"   → memories, knowledge, workspace_code, vscode_chats, company_data, workspace_all, email_sent_history
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chroma.sqlite3 "SELECT COUNT(*) FROM collection_metadata;"   → 7
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chroma.sqlite3 "SELECT c.name, COUNT(e.id) AS n FROM collections c JOIN segments s ON s.collection=c.id JOIN embeddings e ON e.segment_id=s.id GROUP BY c.name ORDER BY n DESC;"   → workspace_all|193487, company_data|176036, workspace_code|17451, memories|6138
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chroma.sqlite3 "SELECT COUNT(*) FROM embedding_metadata WHERE key='chroma:document';"   → 393112
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chromadb/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings;"   → 2092
timeout 25 sqlite3 -readonly /opt/company/data/chromadb/chromadb/chroma.sqlite3 "SELECT c.name, COUNT(e.id) FROM collections c JOIN segments s ON s.collection=c.id JOIN embeddings e ON e.segment_id=s.id GROUP BY c.name;"   → memories|2092
timeout 25 sqlite3 -readonly /opt/company/data/mem0/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings;"   → 130983
timeout 25 sqlite3 -readonly /opt/company/data/mem0/chroma.sqlite3 "SELECT c.name, COUNT(e.id) AS n FROM collections c JOIN segments s ON s.collection=c.id JOIN embeddings e ON e.segment_id=s.id GROUP BY c.name ORDER BY n DESC;"   → mem0_memories|123865, mem0_memories_entities|7118
timeout 25 sqlite3 -readonly /opt/company/data/mem0/chroma.sqlite3 "SELECT key, COUNT(*) FROM embedding_metadata GROUP BY key ORDER BY 2 DESC LIMIT 20;"   → user_id 130983, data 130983, agent_id 130983, updated_at 123865, timestamp 123865, text_lemmatized 123865, hash 123865, created_at 123865, channel 123865, attributed_to 62159, entity_type 7118
ls -la /root/work/esc-baseline/data/chromadb/chroma.sqlite3   → 188416 bytes, Oct 14 00:12
ls -la /root/work/esc-parser/data/chromadb/chroma.sqlite3   → 188416 bytes, Oct 14 00:09
ls -la /root/work/fd-relay/data/chromadb/chroma.sqlite3   → 188416 bytes, Oct 13 14:41
timeout 25 sqlite3 -readonly /root/.mem0/history.db "SELECT COUNT(*) FROM history;"   → 2656
grep -in -E 'mem0|chroma|memory|embed' /opt/company/.env   → 252:MEM0_ENABLED=true 253:MEM0_LLM_MODEL=gpt-4o-mini 254:MEM0_EMBEDDING_MODEL=text-embedding-3-small 255:MEM0_STORAGE_PATH=data/mem0 525:MEM0_PROVIDER= 526:MEM0_GATEWAY_MODEL=secretary-fast
grep -in -E '^(DATABASE_URL|SEMANTIC_MEMORY_DIR|MEM0_|MEMORY_CONSOLIDATION|RETRIEVAL_)' /opt/company/.env   → 196-201 RETRIEVAL_*, 252-255 MEM0_*, 533:DATABASE_URL=sqlite:////root/authority.db   (no SEMANTIC_MEMORY_DIR, no MEMORY_CONSOLIDATION_*)
grep -n -E "memory_consolidation_enabled|memory_consolidation_every_hours|memory_consolidation_max_items|mem0_enabled|mem0_storage_path|semantic_memory_dir" /opt/company/app/config.py   → 882 semantic_memory_dir="data/chromadb", 885 retrieval_hybrid_enabled=True, 1135 memory_consolidation_enabled=True, 1136 every_hours=4, 1137 max_items=250, 1188 mem0_enabled=True, 1193 mem0_storage_path="data/mem0"
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';"   → 235
timeout 25 sqlite3 -readonly /root/authority.db "SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND (lower(name) LIKE '%memory%' OR … OR lower(name) LIKE '%fact%') ORDER BY name;"   → 19 rows
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM \"<t>\";" per table   → agent_working_memory 84, knowledge 0, knowledge_triples 38, memory_entries 0, memory_write_outcomes 4085, procedural_experiences 18526, project_knowledge 303, rule_applications 0, agent_rules 170, agent_routing_rules 0, memories 25047 (→25049 at 01:06Z), proactive_insights 2438
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memory_vectors_rowids;"   → 10723 (→10725 at 01:06Z)
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memory_vectors;"   → Error: in prepare, no such module: vec0
timeout 25 sqlite3 -readonly /root/authority.db "SELECT outcome, COUNT(*) FROM memory_write_outcomes GROUP BY outcome ORDER BY 2 DESC;"   → written 3216, skipped_policy 775, deduplicated 82, partial 11, failed 1
timeout 25 sqlite3 -readonly /root/authority.db "SELECT stage, COUNT(*) FROM memory_write_outcomes GROUP BY stage ORDER BY 2 DESC;"   → (NULL) 3298, extraction 775, embedding 11, persistence 1
timeout 25 sqlite3 -readonly /root/authority.db "SELECT MIN(attempted_at), MAX(attempted_at) FROM memory_write_outcomes;"   → 2026-09-28T05:55:57|2026-10-14T01:01:56
timeout 25 sqlite3 -readonly /root/authority.db "SELECT date(attempted_at) d, COUNT(*) FROM memory_write_outcomes WHERE attempted_at >= date('now','-7 day') GROUP BY d ORDER BY d;"   → 10-07|255 10-08|491 10-09|251 10-10|259 10-11|326 10-12|260 10-13|543 10-14|23
timeout 25 sqlite3 -readonly /root/authority.db "SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type ORDER BY 2 DESC;"   → observation 12462, summary 12022, question 412, preference 45, lesson 43, event 39, profile 9, fact 6, decision 5, goal 2, milestone 1, schema 1
timeout 25 sqlite3 -readonly /root/authority.db "SELECT status, COUNT(*) FROM memories GROUP BY status;"   → active 25034, superseded 13
timeout 25 sqlite3 -readonly /root/authority.db "SELECT MIN(created_at), MAX(created_at) FROM memories;"   → 2026-02-17T06:44:29.878682+00:00|2026-10-14T01:01:56
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM memories WHERE created_at >= date('now','-7 day');"   → 1787
timeout 25 sqlite3 -readonly /root/authority.db "SELECT source, COUNT(*) FROM memories GROUP BY source ORDER BY 2 DESC LIMIT 12;"   → autopilot_checkin 11214, activity_sync 2916, self_diagnosis 1794, finance 914, action 649, shadow_mode 576, audit 531, system 481, ask_owner 455, operations 430, security 414, engineering 201
timeout 25 sqlite3 -readonly /root/authority.db "SELECT category, COUNT(*) FROM memories GROUP BY category ORDER BY 2 DESC LIMIT 12;"   → autopilot_checkin 11214, owner_context 2943, self_diagnosis 1795, finance 1021, memory_consolidation 708, shadow_mode 667, audit 606, system 564, owner_questions 455, security 453, operations 441, business 210
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(DISTINCT agent_id) FROM memories;"   → 69
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) AS total, SUM(state_embedding_json IS NOT NULL) AS with_emb, MIN(created_at), MAX(created_at) FROM procedural_experiences;"   → 18526|18494|2026-04-13T05:35:58.329015+00:00|2026-10-14T00:43:58.817224+00:00
timeout 25 sqlite3 -readonly /root/authority.db "SELECT agent_id, COUNT(*) FROM procedural_experiences GROUP BY agent_id ORDER BY 2 DESC LIMIT 10;"   → ten agents, all exactly 500
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*) FROM project_events;"   → 2600
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*), MAX(created_at) FROM project_knowledge;"   → 303|2026-07-02T00:41:53.543665+00:00
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*), MIN(updated_at), MAX(updated_at) FROM agent_working_memory;"   → 84|2026-05-06T23:56:47.371762+00:00|2026-10-14T00:59:49.456440+00:00
timeout 25 sqlite3 -readonly /root/authority.db "SELECT (SELECT COUNT(*) FROM kg_nodes), (SELECT COUNT(*) FROM kg_edges);"   → 2544|2172
timeout 25 sqlite3 -readonly /root/authority.db "SELECT COUNT(*), MAX(created_at) FROM activity_log;"   → 233597|2026-10-14T01:04:22.999778+00:00
timeout 25 sqlite3 -readonly /root/authority.db "SELECT name FROM sqlite_master WHERE type='trigger' AND lower(name) LIKE '%memor%';"   → memories_fts_insert, memories_fts_delete, memories_fts_update
timeout 25 sqlite3 -readonly /root/authority.db "SELECT sql FROM sqlite_master WHERE name='memory_vectors';"   → CREATE VIRTUAL TABLE memory_vectors USING vec0(memory_id INTEGER PRIMARY KEY, agent_id TEXT partition key, embedding float[1536] distance_metric=cosine)
timeout 25 sqlite3 -readonly /root/authority.db "SELECT id, created_at, substr(content,1,90) FROM memories WHERE category='memory_consolidation' ORDER BY id DESC LIMIT 5;"   → 25029|2026-10-13T21:53:17, 25000|17:53:12, 24815|13:53:08, 24763|09:52:50, 24701|05:52:48
python3 -c "import json; d=json.load(open('/opt/company/data/autopilot_state.json')); print(d.get('last_memory_consolidation_at'))"   → 2026-10-13T21:53:17.799291+00:00
ls -d /opt/company/.venv/lib/python3.14/site-packages/mem0*   → mem0, mem0ai-2.2.1.dist-info
/opt/company/.venv/bin/python -c "import mem0; print(mem0.__version__)"   → 2.2.1
ls -d /opt/company/.venv/lib/python3.14/site-packages/sqlite_vec*   → sqlite_vec, sqlite_vec-0.1.9.dist-info
systemctl list-units --type=service --all | grep -iE 'autopilot|secretary|company'   → company-api.service active running; secretary-dashboard.service active running
ps -eo pid,etime,cmd | grep -iE 'autopilot|uvicorn|main:app'   → 1195880 uvicorn app.main:app --host 127.0.0.1 --port 8002
grep -rn --include=*.py -E "(from +(app\.services\.)?semantic_memory +import|import +semantic_memory)" app/ scripts/   → assistant_chat.py:5087, memory_consolidation.py:142, email_style.py:209,351, main.py:16589,16596,16615, chat_action_memory.py:42,181,209, persistence_contract.py:502, memory_contract.py:412
grep -rn --include=*.py -E "project_memory" app/   → main.py:21877 only (non-test, non-report)
grep -rn --include=*.py -E "procedural_memory" app/   → agent_worker.py:4303, context_manager.py:353, main.py:17496, memory_contract.py:456
grep -rn --include=*.py -E "memory_consolidation|run_consolidation" app/   → agent_bus.py:493 (run_consolidation — DOES NOT EXIST), autopilot.py:8655 (run_memory_consolidation)
grep -rn --include=*.py "def run_consolidation" app/   → (no output)
grep -rn --include=*.py -E "unified_memory" app/   → chat_action_memory.py:71,126, autopilot.py:495, memory_contract.py:203,391
grep -rn --include=*.py -E "mem0_service|post_conversation_extract|nightly_consolidation" app/   → assistant_chat.py:5112,5695, agent_bus.py:523, memory_contract.py:438
grep -rn --include=*.py -E "store_memory_entry|vector_search_memories" app/   → only app/database.py:3967, 4015 (definitions) — ZERO callers
grep -rn --include=*.py "upsert_knowledge" app/   → only app/database.py:6531 (definition) — ZERO callers
grep -rn --include=*.py -E "distill_events|distill_all_projects" app/   → main.py:21877 only
grep -n "_maybe_run_memory_consolidation" app/autopilot.py   → 7179 (call), 8630 (def)
awk 'NR<=7179 && /^    def /{l=NR": "$0} NR==7179{print l}' app/autopilot.py   → 6922: def _loop(self) -> None:
grep -n -E "while not self\._stop" app/autopilot.py   → 6994
grep -n "self.run_once" app/autopilot.py   → 7224 (external_event), 7250 (autopilot_interval)
grep -n -E "threading.Thread" app/autopilot.py   → 2411 target=self._loop
grep -n "autopilot.start_thread()" app/main.py   → 1200, 15967
date -u   → Wed Oct 14 01:06:14 AM UTC 2026
```
