# HANDOFF — Security department & anti-stagnation engine

**For:** the next agent picking this up
**From:** Zabz (chief executive / chief of staff) — session of 2026-10-26, ZABZ-YOGA
**Written:** 2026-10-26 ~02:40 UTC, at the end of 16 goal rounds
**Status of the work:** HALF DONE. Read §2 before you touch anything.

---

## 1. Who I am, and why this document exists

I am Zabz, the owner's chief executive and chief of staff for this estate — I run the systems,
the AI company, and the machines, and I have no continuous memory. Everything I know that survives
a session is written down. This document is that writing-down.

This session was given one objective by the owner:

> *"Two departments that I think are very important to have in the AI company. First, the security
> department, now that more and more hacks and different things are happening with AI, we need a
> constant security overview of all our systems and architecture. Second, an anti-stagnating
> evolution engine. I think we had one, but I'm not sure how well it's working. Basically it's a
> department whose job is to make sure that all other departments, the company in general and
> DeepSeek and everything else is constantly evolving, getting better, more efficient. I want you to
> work for 20 rounds on the list, making sure all this is fully implemented. And obviously you'll
> have questions from your things that need me as you go along. So write them in a document. Then
> when you finish all 20 rounds we'll go through that document together."*

I completed 16 rounds and am stopping because my context is exhausted. I was then marked blocked.
**I did not finish.** What follows is exactly what is true, so you do not re-derive it and so you do
not repeat my mistakes.

---

## 2. What I want from you — the short version

1. **Read §3 first.** Both departments existed before me and were inert. Do not rebuild them.
2. **Do the one fix in §6.1 first.** It is small, it is the keystone, and everything else is blocked
   behind it.
3. **Verify by reading the system back, never by trusting that a change is live.** This session found
   four defects that all looked like "working" from the outside. The measurement rule is not optional
   here: print the raw value next to the predicate.
4. **Keep the owner-questions document going.** It is
   `~/code/harness-config/docs/security-and-evolution/OWNER-QUESTIONS.md`. He wants to go through it
   with you at the end. Append to it; never leave a stale question in it (see §7 — I had to retract
   one).
5. **Do not mark anything "done" that you have not watched work.** In this session the two cron jobs
   I installed have never been observed firing. That is stated plainly everywhere it matters and it
   must stay that way until someone reads the log.

---

## 3. What was actually true when I started (read this before designing anything)

### 3.1 The security department existed — dead, and nothing could tell

| Fact | Evidence |
|---|---|
| `dept_security` was in the authority's blueprint | `grep -n 'dept_security' app/company_blueprint.py` → lines 604, 1161, 1408 |
| Two enabled standing work orders existed | `standing_work_orders`: `seed_security_posture_sweep` (1440 min), `seed_security_credential_hygiene` (10080 min), `is_enabled=1` |
| Both had FAILED | `work_order_executions.error_message = "Lifecycle sweep released stale running execution."`, `2026-10-25T02:26:29Z` |
| All 9 goal steps were skipped, never attempted | `goal_steps`: `status=skipped, attempts=0, claimed_by=null, started_at=null` |
| It had NEVER ticked | `tick_telemetry` over 2026-10-24→26 had no row for `dept_security` (19 other agents present) |
| Its identity was an orphan clone of the orchestrator | `hierarchy.parent_agent_id: null`, `children: []`, `name: Agent-4193`, `department.department_name: "General Operations"`, no `status`, `reflection_count: 0` |

### 3.2 The anti-stagnation engine existed in four disconnected pieces and closed nothing

| Piece | What I measured |
|---|---|
| `app/evolution.py` | `evolution_log`: 186 rows — 103 `applied`, 74 `dismissed`, **9 still `open`**; newest `2026-10-14T22:30:54Z` |
| `app/services/company_evolution.py` | Builds a "next version portfolio" of task seeds (called from `autopilot.py:7824`) |
| `app/services/mashgiach.py` | Weekly scorecard — its findings were fabricated (§3.4) |
| `dept_evolution_reliability` | Ticks (16 in 2 days) but spent **$0.0213** — essentially no work |
| `app/services/evolution_verifier.py` | Has `create_verification()` and `record_measurement()`, wired at 6 call sites — **but `evolution_verification` had no new row since `2026-07-04T09:54:09Z`** |

**This is the answer to the owner's "I think we had one, but I'm not sure how well it's working":**
it applied 103 changes and graded none of them for ~16 weeks.

### 3.3 The reason new departments never worked — one log line

```
Oct 25 18:34:49 secratary-cloud app.autopilot: Company bootstrap skipped (autopilot_skip_bootstrap=True)
```

`AUTOPILOT_SKIP_BOOTSTRAP` is set in `/opt/company/.env`. `bootstrap_company()` (`app/autopilot.py:8829`)
is the **only** thing that parents a newly-added blueprint department into the agent tree. It is
skipped for a defensible reason (the box is 4-core / 15 GB) but nothing replaced the part the tick
depends on.

`company_tick` dispatches productive work from `walk_agent_tree(root_id)`, which breadth-first walks
`hierarchy.children`. **An orphan is never visited.** So on that host, adding a department to
`DEPARTMENTS` changed nothing at runtime, silently.

### 3.4 The scorecard was a constant, not a measurement

`mashgiach_dept_scores`: **6,244 rows, 88 departments, and `SUM(findings_count)=0`,
`SUM(auto_fixes)=0`, `SUM(escalations)=0`** — every row. Cause: `app/services/mashgiach.py` inserted
a **literal `0`** for `findings_count` and never wrote the other two columns at all.
`daily_scan()` had been writing real rows into `mashgiach_audit_log` the whole time; the two were
never joined.

### 3.5 Two deliberate policies that contradicted each other and deleted work

| Constant | Value | Where |
|---|---|---|
| `STUCK_WORK_ORDER_PROGRESS_WINDOW_MINUTES` | **90** | `app/services/lifecycle_sweep.py:62` |
| Longest cheap-window deferral | **180** | `SCHEDULE_MODE=cheap`, peak 01:00–04:00 / 06:00–10:00 UTC Mon–Fri |

A work order created inside a peak block is released for "no progress" **before its department is
permitted to run**. Measured: the two `dept_security` goals, created `2026-10-25T00:54:54Z`, released
`02:26:29Z` — 91.6 minutes, 9/9 steps `attempts=0`.

### 3.6 A policy refusal was being booked as a tool failure (STILL OPEN — see §6.1)

```
NOT EXECUTED - 'repo_read_file' requires owner approval (L2_APPROVE: Action requires quick-approve).
Queued for approval as task 30090.
Autonomy DEMOTED: repo_read_file L4 → L3 → L2 (after 5 failures in 3600s)
Autonomy: resetting DB level for repo_read_file from L2 to L4          (02:23:57Z)
Autonomy DEMOTED: repo_read_file L4 → L3                               (02:27:17Z)
ERROR agent_worker: dept_business_ops step 49482 tool-loop deadlock: 'repo_read_file'
      failed identically 3/3 times (failure_class=not executed)
```

`NOT EXECUTED` means it never ran — it was refused by policy, correctly. But the refusal is counted
as an execution failure, so the agent is retried 3×, its permission is walked **L4→L2 for obeying the
rule**, a deadlock fires, and a duplicate approval task is queued on every attempt. This is **not**
security-specific — `dept_business_ops` hit the identical deadlock on the same tool.

---

## 4. What I changed on the authority, and the proof for each

Everything below is in `/opt/company` on `secratary-cloud` (THE AUTHORITY). Backups were taken
before every edit and files were installed with a new inode. `company-api` was restarted **three
times, deliberately**, between 02:13Z and 02:24Z on 2026-10-26; `secratary` (the FROZEN rollback
anchor) was never touched.

| # | File | Backup |
|---|---|---|
| 1 | `app/services/org_reconcile.py` (**new**) | — |
| 2 | `app/workforce.py` — call reconcile before the tree walk | `app/workforce.py.bak-reconcile-20261026T021239Z` |
| 3 | `app/workforce.py` — `_has_claimable_work()` no-starve guard | `app/workforce.py.bak-nostarve` |
| 4 | `app/company_blueprint.py` — complete the `dept_security` entry | `app/company_blueprint.py.bak-secfields-` (note the trailing space; it exists) |
| 5 | `app/services/mashgiach.py` — real finding counts | `/tmp/mashgiach.bak.py` |
| 6 | `app/services/evolution_loop.py` (**new**) | — |
| 7 | `app/services/stagnation_detector.py` (**new**) | — |
| 8 | `/root/bin/evolution-loop.py`, `/root/bin/stagnation-sweep.py` (**new**) | — |
| 9 | `/etc/cron.d/evolution-loop` (**new file**; the existing crontab was not read or rewritten) | — |

**Every patch is scripted and committed** so you can re-apply or review it:
`~/code/harness-config/docs/security-and-evolution/patches/` —
`org_reconcile.py`, `patch_workforce.py`, `patch_blueprint.py`, `patch_mashgiach.py`,
`patch_nostarve.py`, `evolution_loop.py`, `stagnation_detector.py`, `run_scorecard.py`,
`run_evoloop.py`, `run_stagnation.py`, `verify_tree.py`, `check_orgchart.sh`, `install_cron.sh`,
`sched_stag.sh`.

### 4.1 Fix 1 — departments born dead → reconciled into the tree (VERIFIED)

`org_reconcile.py` repairs presence, parent, status and department block for every blueprint
department. It hires nothing, deletes nothing, never overwrites an identity that has reflections,
and fails visibly. Read its module docstring — it carries the whole argument.

Live log, inside the running process:
```
02:14:45 WARNING org_reconcile: repaired dept_security (parent null -> orchestrator;
         status null -> active; department block -> own; identity_core.mission -> blueprint;
         hierarchy.role -> 'VP of Security')
02:14:48 WARNING workforce: company_tick: reconciled 1 blueprint department(s) into the agent
         tree: ['dept_security']
```
Store, read directly from `data/agent_identities.json`:
```
orchestrator.children count: 21        dept_security in orchestrator.children: True
dept_security.parent_agent_id: orchestrator   role: VP of Security   status: active
department.department_name: Security
walk_agent_tree reaches 91 agents      dept_security reached by the tick walk: True
```
It then ticked for the first time in its existence: `tick_telemetry ab0b7dbfb5dd47c9`,
`02:16:56Z`, `outcome=complete`, `tick_quality=productive`, `cost=$0.0047`.

### 4.2 Fix 2 — the scheduler deleting work it had deferred (VERIFIED)

`_has_claimable_work(agent_id)` in `workforce.py`, checked in `_filter_by_schedule` **before** the
cost policy decides. Deferral is for idle reflection; an agent holding a pending unclaimed step runs
now. It **fails open** (returns `True` on error) because starving work to save one query is the wrong
trade.

Verified live during the peak block:
```
deferred count         : 17
dept_security deferred : False     <- ran while 17 others waited
agents_ticked          : 16        (was 13)
```
It then claimed and **completed** both older blocked goals `d17091582e83` and `b7b175d53238`.

### 4.3 Fix 3 — the fabricated scorecard (VERIFIED)

`weekly_report()` now joins `mashgiach_audit_log` and writes real `findings_count`, `auto_fixes`,
`escalations`. Result: `departments_scored: 32`, **19 of 32 with ≥1 finding** — `dept_engineering`
325, `dept_mashgiach` 1951, `dept_evolution_reliability` 188, `dept_security` 0 (correct: it has
never produced one). `auto_fixes` is **0 everywhere** — that column is honest now, and it says the
mashgiach finds and cannot fix.

### 4.4 Fix 4 — the verification loop (BUILT, RUN, SCHEDULED, **CRON UNOBSERVED**)

`app/services/evolution_loop.py` → `close_the_loop(db_url)` reuses the existing table (it does not
rebuild the verifier): backfills a verification row for every applied change that never got one, and
advances open rows to a verdict after `TICKS_BEFORE_VERDICT = 3`.

```
first run : ok=True backfilled=103 measured=103 passed=0 failed=0
later run : ok=True backfilled=0   measured=103 passed=103 failed=0
table     : passed=114 (was 11), failed=14 (unchanged), measuring=0
```

**Read the caveat before you use this number.** `103 of 103 passed` is exactly as uninformative as
`0 of 0`. Every change passed because the single shared metric (unresolved `error_log` count,
baseline 16) never rose above 16. The **plumbing** is verified; the **judgement** is not. Treat
`passed` as *"no harm detected"*, never as *"this helped"*. See §6.2.

### 4.5 New capability — the stagnation detector (BUILT, RUN, SCHEDULED, **CRON UNOBSERVED**)

`app/services/stagnation_detector.py` → `detect(db_url)`. Two kinds, deliberately separate:
**SILENT** = no tick in the window (not working); **IDLE** = ticking and finding nothing (working,
achieving nothing). A never-ticked department cannot be judged on findings, so SILENT is tested
first. Writes one deduplicated `mashgiach_audit_log` row per (department, kind, day).

```
departments_checked: 19   silent: 4   idle: 1   findings_logged: 5
SILENT dept_admin, dept_home, dept_management, dept_orchestrator   (last_tick=None)
IDLE   dept_security   ticks=3   findings=0
```

**The system now names its own security department as stagnant.** That is the forcing function the
owner asked for.

Caveats that must travel with it:
- **`dept_orchestrator` is a false positive.** Tick telemetry records the CEO as `orchestrator`, so
  that is a naming artifact. Same doubt applies to `dept_admin` / `dept_home` / `dept_management` —
  they may be retired labels, not broken desks. Verify before acting on any SILENT verdict.
- Second run gave `logged=0` — that is the 1-day dedup working, **not** a regression.

---

## 5. Where everything lives

**Journal** (`python ~/code/harness-config/journal/tools/journal.py show <id>`):
`H13356` (rounds 0–1) · `H13357` (rounds 2–3) · `H13358` (correction: `repo_read_file` failing) ·
`H13359` (**the refusal fix — read this one**) · `H13360` (verdict caveat + cron unobserved) ·
`H13361` (stagnation detector + false positives).

**Docs** (`~/code/harness-config/docs/security-and-evolution/`):
`00-FINDINGS-2026-10-26.md` (full findings, §3b/3c/3d are the later rounds) ·
`OWNER-QUESTIONS.md` (10 questions — append, never overwrite) · `patches/` (every script) ·
`HANDOFF-TO-NEXT-AGENT.md` (this file).

**Code**: the 6 new/changed app modules exist **only** in `/opt/company` on the authority. They are
**not** in the `personal-secretary-mvp` repo — see §6.6.

**Git**: branch `agent/security-evolution-20261026`, pushed to `offsite` (GitHub).
Commits: `713a75d74`, `7df500fc2`, `6227115ae`, `03ac98108`, `cb9e9d09c`, `72fc54140`,
`5bb67332e`, `2664ab266`, `f998be347`, `f27794cfe`, `36ffe2523`, `75ffb26ce`.

**Cron on the authority**: `/etc/cron.d/evolution-loop` — `:17` runs `evolution-loop.py` →
`/var/log/evolution-loop.log`; `:47` runs `stagnation-sweep.py` → `/var/log/stagnation-sweep.log`.

---

## 6. WHAT STILL NEEDS DOING — in priority order

### 6.1 THE KEYSTONE — a policy refusal must not be booked as a tool failure

**This is the single most important thing. Do it first.** It blocks the security department's actual
mission and it blocks every department from acting on a finding.

**Where:** `app/chat_action_runtime.py` (retry loop + failure classification) and
`app/services/autonomy.py` (demote / reset).

**What "done" looks like — write this down before you start:**
- A refusal (`L1_SUGGEST` / `L2_APPROVE` / `L3`) is classified **`policy_refused`**, not `failed`.
- Exempt from the autonomy demotion counter.
- Exempt from the identical-failure `TOOL_LOOP_DEADLOCK` detector.
- The approval task is deduplicated per (action, agent, resource), not queued on every attempt.
- Surfaced to the owner as "waiting on owner", not "broken".

**Verification (do not accept anything less):**
- `journalctl -u company-api | grep 'Autonomy DEMOTED'` shows **no** new `repo_read_file`
  demotions while the refusal still occurs.
- No duplicate approval-task rows accumulate across repeated attempts.
- No `TOOL_LOOP_DEADLOCK` naming a refused action.

**Trap:** do not "fix" this by granting the permission. That hides the defect and leaves every other
gated action eroding its own autonomy for obeying the rules.

### 6.2 Verification verdicts cannot discriminate

`error_count` is too coarse (§4.4). **Fix:** each proposal must name the metric it expects to move,
and its baseline, **at proposal time**; the verification row must carry that metric. Until then
`passed` means "no harm detected".

### 6.3 A security findings store

`dept_security` has produced **no finding**, and there is nowhere for one to land —
`mashgiach_audit_log` is generic. Its posture sweep `swo_seed_security_posture_sweep_037c2e9c`
(5 steps, `active`, priority 25) has step 1 marked `completed` but with `claimed_by=null,
attempts=0` — **that is not a genuine completion**, it was closed by a path other than a real
claim-and-work cycle. Investigate, then build the store.

### 6.4 Nothing closes a finding

`auto_fixes` is 0 everywhere. The mashgiach and the stagnation detector both **find** and neither can
**fix**. This is the difference between a scorecard and an engine.

### 6.5 DSH itself — the owner explicitly asked for it

*"the company in general and DeepSeek and everything else"*. Today the engine can only reach the
company repo. It cannot reach `~/code/harness-config` or the engine checkout. **This is the largest
unstarted piece** and it was in the original ask.

### 6.6 Land the six app files into the repo

They exist only in `/opt/company`'s working tree, which is **329 files dirty** on branch
`keepalive/323-pickup-live-restore-20261021` — a **different lineage** from the local checkout
(`agent/ebay-account-deletion-endpoint-20261025`). **Do not copy files across lineages**
(`harness-config/AGENTS.md` §6.1). Re-apply the changes as patches on the right branch, then commit.
The scripts in `patches/` are the source of truth for what changed.

### 6.7 Owner questions still open

Read `OWNER-QUESTIONS.md`. Two need care:
- **Q8b — do NOT let the owner grant repo access yet.** I asked for it in round 1 and it was the
  wrong layer; §6.1 is the real problem. The question is withdrawn and reframed in the doc.
- **Q3a — the anonymous-cookie issue.** `Set-Cookie` is minted in
  `node_modules/@deepseek-ai/dsh-client-connection/lib/index.js:347-348, 466-477, 524-536` — a
  **vendored package**. Patching `node_modules` is the anti-pattern this estate has paid for
  (`evolution_log` even has a dismissed proposal: *"target is vendored/generated; the writer refuses
  this class now"*). Legitimate homes: `scripts/phone-gate.py` (ours) or an engine upgrade. **The
  live behaviour has never been re-measured — whether it is still open is UNKNOWN. Do not guess.**

---

## 7. Traps in this estate that cost me time — do not repeat them

1. **Never inline `$(...)` or `$VAR` in a PowerShell-quoted `ssh` command.** PowerShell expands it
   locally and silently corrupts the remote command. It wasted four of my rounds. Write the script
   to a file, then `Get-Content -Raw x.sh | ssh host "bash -s"`.
2. **Strip CRLF before piping a script**, or bash reports `$'\r': command not found` and exits 1.
   `(Get-Content -Raw x.sh) -replace "\`r\`n","\`n"`.
3. **On ZABZ-YOGA `bash` resolves to WSL, which has no distro.** So
   `scripts/mesh/guard-service-state.sh` exits 1 — that is the *environment* code, **not a refusal
   and not permission**. Read `harness-config/settings/machines/host-posture.tsv` directly instead.
   `secratary-cloud` is `writable` ("THE AUTHORITY… may be changed here — deliberately, and
   recorded"). `secratary` is **FROZEN** — never start, stop, unmask or restart anything there.
4. **Never rewrite a running file in place.** Backup → write `.new` → `py_compile`/`bash -n` → `mv`
   (new inode). A running bash script reads by byte offset and will execute a mixture of old and new.
5. **Always diff the authority's actual text before patching.** My `mashgiach.py` patch failed the
   first time because the authority's upsert has no `conn.commit()` — the local copy does.
6. **`journal.py search` returns exit 1 and "no match" for a real negative.** That is an answer.
7. **`ps_action("search")` and `repo_search` / `repo_read_file` / `repo_map` are approval-gated** and
   return `NOT EXECUTED … L1_SUGGEST/L2_APPROVE`. Use `ps_search` (the MCP tool) instead — it works.
8. **The authority is at ~82% disk, ~26 GB available, 31 GB RAM.** Do not run builds, tests or corpus
   scans there. It is 4-core and it is the sole writer of the company database.
9. **`SCHEDULE_MODE=cheap` + `SCHEDULE_PRIORITY_MODE=ladder` defer ALL departments out of the peak
   bands.** Never conclude "this department is idle" without checking the clock — but my no-starve
   guard (§4.2) now means real work is exempt.

---

## 8. Two things I got wrong, so you can calibrate me

- **I asked the owner the wrong question.** I told him the security department was blocked on
  standing read-only repo access. It is not — the refusal is correct and the defect is what happens
  *after* it. I withdrew the request in Q8b. If you find yourself asking him for a permission to fix
  a problem you have not traced, stop and trace it first.
- **I reported an unverified success as verified.** In round 5 I said step 1 of the posture sweep
  looked like real progress; in round 6 the log showed the tool was actually failing and being
  autonomy-demoted. `H13358` corrects `H13357`. Prefer "not yet observed" over "should work".
- **I also reported `103 passed` before noticing it was meaningless.** The caveat is now welded to
  the number everywhere. Keep it that way.

---

## 9. If you only do one thing

Do §6.1. Everything else in this handoff is either done, cosmetic, or blocked behind it. The security
department is alive and correctly targeting `/root/code/harness-config/settings/machines/host-posture.tsv
` (the file exists, 5,687 bytes, Oct 11) and it cannot read a repo because a refusal is being
punished as a failure. Fix that and both departments start working.
