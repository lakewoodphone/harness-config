# ROUND 4 RECON — what actually landed vs what is only a claim

**Written 2026-10-14 ~19:50Z by a recon agent running on `ZABZ-TECH` (Windows), read-only.**
**Reconciled against the live tree as of `2026-10-14T19:35Z`.**

## 0. Where this ran, and the premise correction you must read first

`hostname` → `zabz-tech`; `$env:COMPUTERNAME` → `ZABZ-TECH`. **I ran on ZABZ-TECH.**

**The round-2/3 doc directory named in the brief does not exist on ZABZ-TECH.** Facts, each with its command:

| claim | command | output |
|---|---|---|
| the local checkout is not on mainline | `git -C C:\Users\ezabz\code\harness-config rev-parse --abbrev-ref HEAD` | `mesh/broker-host-cloud-default-20261013` |
| no v2 dir here | `Get-ChildItem ...\harness-config\docs` | `dsh-evolution` and `dsh-evolution-v2` **absent** |
| `docs/dsh-evolution-v2` never existed in this repo's history | `git -C ... log --all --oneline -- docs/dsh-evolution-v2` | **empty** |
| `docs/dsh-evolution` (round 1) does exist on a ref | `git -C ... ls-tree -r --name-only origin/main -- docs/dsh-evolution` | 11 files, `00-SYNTHESIS.md` … `PROGRAM.md` |
| nothing on the authority either | `ssh secratary-cloud "find /root /home /opt /srv -xdev -name '55-company-design.md' -o -name '07-pain-register-v2.md' -o -name '09-refreshed-system-spec.md'"` | no output, `FIND_DONE` |
| **the docs are on ZABZ-YOGA** | `ssh laptop-ts 'Test-Path C:\Users\ezabz\code\harness-config\docs\dsh-evolution-v2'` | `True` (branch `feat/card-due-watch-20261014`) |

**Consequence: `docs/dsh-evolution-v2` is an uncommitted, ZABZ-YOGA-only working tree.** `07-pain-register-v2.md` is modified-but-uncommitted on ZABZ-YOGA (`git status --porcelain` → ` M docs/dsh-evolution-v2/07-pain-register-v2.md`); `HEAD` of that repo does not contain the directory. Every fact in those documents is one `git clean` or one fresh clone from being lost — the same failure the documents themselves flag for three skill files (`11-instruction-convergence-plan.md` §5.4). This report is written to **both** ZABZ-TECH (the literal path in the brief) and ZABZ-YOGA (where the series lives).

**Access used:** `ssh secratary-cloud` (root), `ssh laptop-ts` (ZABZ-YOGA, PowerShell shell), `ssh linux-pc`, `ssh mac-mini`. `secratary` (frozen) was never contacted. The authority was read-only throughout: `sqlite3 -readonly`, `md5sum`, `stat`, `grep`, `git log/branch/status/diff/show`. **Nothing was written to `/opt/company`; no service was restarted; no file was written anywhere except this report.**

**The mainline.** `/opt/company` is the *main worktree* of `personal-secretary-mvp` (`git -C /root/work/evolve3-gate worktree list` → `/opt/company 561535b78 [keepalive/156-dialpad-status-landing]`). The mainline is **`master` (`982c4332d`) / `origin/master` (`eb0cef81b`)** — `git rev-parse main` → `fatal: Needed a single revision`; there is **no `main`**. `origin` = `https://github.com/lakewoodphone/personal-secretary-mvp.git`.

**The single most important measurement in this report.** `git -C /opt/company status --porcelain` → **153 dirty files**, and the three files that carry the changes below are all dirty:

```
 M app/autopilot.py
 M app/chat_action_runtime.py
 M app/services/autonomy.py
git diff --stat -- those files:
 app/autopilot.py           | 1816 +++++++++++++++++++++++++++---------
 app/chat_action_runtime.py |   41 +-
 app/services/autonomy.py   |  238 +++++-
 3 files changed, 1723 insertions(+), 372 deletions(-)
```

**Nothing in this round is merged. The live tree is the only place it exists.**

---

## 1. Landed vs claimed

Labels: **(a)** merged into the company mainline (`master`/`origin/master`) · **(b)** present as a branch/worktree only · **(c)** live in `/opt/company` · **(d)** unbuilt. A change can be (b)+(c) or (c) only; **(c) with no (a) is the estate's dominant state and its biggest risk.**

### 1.1 `55-company-design.md` §3 — the ten changes (P1–P10)

| # | change | status | proof (command → output) |
|---|---|---|---|
| **P1** | budget belongs to the TASK; 20 steps, ceiling 40 | **(c) LIVE, uncommitted** | `grep -nE '_WORK_MAX_STEPS =\|_WORK_ABSOLUTE_MAX_STEPS =\|_WORK_ABSOLUTE_MAX_TURNS =' app/autopilot.py` → `2884: _WORK_MAX_STEPS = 20`, `2895: _WORK_ABSOLUTE_MAX_STEPS = 30`, `2905: _WORK_ABSOLUTE_MAX_TURNS = 60` |
| **P2** | reconnaissance is progress (information gain) | **(c) LIVE, uncommitted** | `sed -n '3406,3416p' app/autopilot.py` → `_work_session_is_progressing` docstring: *"PREFERS information gain… `[TOOL-SIGS:]`"* and `return cls._work_session_information_gain(accumulated_output)` |
| **P3** | a stall changes strategy, does not end the session | **(c) LIVE, uncommitted (13:11Z)** | `sed -n '5012,5022p' app/autopilot.py` → *"2026-10-14 (P3c): a repetition is a redirect, not a death sentence… At `_repeat_count == 2` it injects a directive and CONTINUES… and it closes only at `_repeat_count >= 4`"*; the injected text is `[STALL-DIRECTIVE: … the approach is not working -- call a tool now…]` + `update_work_session(output_append=…)` |
| **P4** | done = artefact changed / task closed, never a token | **(c) LIVE, uncommitted** | `for m in TASK-CLOSED-BY-SESSION ARTEFACT: OUTBOUND: WORK_DONE; do grep -c -- "$m" app/autopilot.py; done` → `3`, `2`, `2`, `22` |
| **P5** | resumable sessions (distilled previous attempt) | **(c) LIVE, uncommitted** | `grep -n 'Distil the previous attempt' app/autopilot.py` → `3768: """Distil the previous attempt on \`task_id\` into an opening-context block`; `3848: "[RETRY-CONTEXT: a previous attempt…"`; `4351: with the previous attempt's last checkpoint and a distilled record` |
| **P6** | the autonomy gate fails closed | **(c) LIVE as of 2026-10-14T12:44:11Z, uncommitted** — *see §1.2, this is the headline correction* | `stat -c '%n\|%s\|%y' app/services/autonomy.py` → `app/services/autonomy.py\|31922\|2026-10-14 12:44:11.422368688 +0000`; backup `.bak-gatefix-20261014T124411Z` is the prior **23,524 B, Jul 1 04:10** file |
| **P7** | memory that is read | **(d) PARTIAL / NOT VERIFIED** | `grep -n 'memor' app/autopilot.py \| grep -iE 'read\|retriev\|search\|recall'` → only `492: # ── Inject relevant context memories ─────`. I did **not** verify a session-start memory read added to the work loop, nor that the zero-caller helpers were deleted or wired |
| **P8** | model ids resolve at runtime | **(d) NOT DONE** | `grep -rnoE '"(claude\|gpt\|grok\|gemini\|deepseek)-[a-z0-9.-]+"' app/ \| wc -l` → **429 hits across 47 files**. (The doc's baseline was 181 across 13 — my regex is broader, so this is not like-for-like; it is unambiguously **not 0**) |
| **P9** | silent failure gets a transport | **(d) NOT VERIFIED** | monitor services exist (`company_outcome_monitor.py`, `self_healing_monitor.py`, `provider_health.py`, `telephony_health.py`) but no evidence a deadline-checked endpoint probe or an escalation that fires landed. Not claimed either way |
| **P10** | self-improvement loop + human-visible proposal queue | **(d) NOT VERIFIED** | `app/services/self_improvement.py` and `company_evolution.py` exist; no evidence the propose→apply→verify→promote loop or the queue landed |

### 1.2 P6 — the headline: the safety hole described as OPEN was CLOSED ~30 minutes after the report that called it open

`DEPLOY-PLAN.md` L588 says the gate needs *"a separate, reviewed change"* and that change is NOT DONE. `07-pain-register-v2.md` #2 and `09-refreshed-system-spec.md` §5.1 both call the hole open **right now**. **That is stale.** The live tree proves it:

**The fail-closed fallthrough — `sed -n '538,560p' app/services/autonomy.py`:**
```python
    # Nobody has classified this action: ask, do not act.
    #
    # This branch used to return L4_AUTONOMOUS ("bias towards action"), which
    # meant any action the dispatcher gained -- or any action invoked by name
    # that no matrix row mentioned -- executed immediately with no human in the
    # loop.  L1 (suggest) queues it for explicit owner approval instead.
    log.info("Autonomy: %r is unclassified; resolving to %s (fail-closed default)", ...)
    return UNCLASSIFIED_ACTION_LEVEL
```
`grep -n 'UNCLASSIFIED_ACTION_LEVEL' app/services/autonomy.py` → **`302:UNCLASSIFIED_ACTION_LEVEL: AutonomyLevel = AutonomyLevel.L1_SUGGEST`**

**The dangerous names are exactly the ones the fallthrough now catches.** `grep -cE '^    "(fire_agent|hire_department|delete_tool|run_command|create_customer|create_work_order|shop_[a-z_]*|website_[a-z_]*)": \{' app/services/autonomy.py` → **`0`**. The matrix is still **56 entries with 37 at `"default": 4`** (`grep -c '"default": 4'` → `37`), i.e. R1's description of the matrix is still accurate — but the names that were never in it no longer fall through to L4.

**The two outbound actions were hand-fixed to L1**, `sed -n '147,168p' app/services/autonomy.py`:
```
    "dialpad_send_sms": { "max": 1, "default": 1, ... "RESTRICTED (changed from L3 by the evolve3 gate workstream)…" },
    "gmail_send":       { "max": 1, "default": 1, ... "RESTRICTED (changed from L3 by the evolve3 gate workstream)…" },
```
This resolves `evolve3-gate/REPORT.md:297` *("The two remaining changes are `dialpad_send_sms` and `gmail_send` (L3 → L1)")* — **those two landed.**

**The chat-action path — `sed -n '381,398p' app/chat_action_runtime.py`:**
```python
        decision = should_execute(action_name, settings)
        _autonomy_action = decision.get("action", "execute")
        _autonomy_execute = bool(decision.get("execute", False))
    except Exception:
        # FAIL CLOSED: a gate that cannot be consulted must not grant execution.
        _autonomy_action = "suggest";  _autonomy_execute = False
    # --- Autonomy verdict: it must reach a branch, not only a variable ---
    # should_execute() returns execute=False for L0/L1/L2. Until this, the verdict was
    # stored in _autonomy_action and the action dispatched regardless.
    if not _autonomy_execute:
```
This is exactly the second half of P6 that `55-company-design.md`'s addendum demanded, and exactly the `except Exception` that `DEPLOY-PLAN.md` and `08-changes-made` said was still fail-open. **It is fixed in the live tree.**

**Attribution — the live file matches NO ref:**
| source | md5 of `app/services/autonomy.py` |
|---|---|
| live `/opt/company` | `e318b1ac894b29c31e27a01e1ecfdf98` |
| commit `41d08d628` (only on branch `evolve2/gate`) | `216702adde9885acf0681f57138b041e` |
| `master` and `HEAD:app/services/autonomy.py` | `64c8b900b3825b2d1059c7305865f14f` |

`git branch -a --contains 41d08d628` → **`+ evolve2/gate`** only; `git log -1 --format='%H|%ad|%s' 41d08d628` → `41d08d628fd303293d33712d266bddca3592a809|2026-10-14 01:36:57 +0000|fix(autonomy): make the unclassified-action default fail closed (L1, not L4)`. **The live gate is that fix, further edited by hand, committed nowhere.**

**What did NOT land out of P6:** the *considered matrix* the spec §5.1 asks for ("irreversible / money / outbound / people / production writes → L0-L1 **explicitly**"; a test asserting `dispatcher_names ⊇ matrix_names`). There is no such test and no such matrix — the safety now rests on a fail-closed **default**, which is weaker but not open. (`evolve3/gate`'s 150-row generated matrix is branch-only and, per DEPLOY-PLAN §3, has 134 of 150 rows at `default: 4` — it would have re-opened the hole and correctly was not shipped.)

### 1.3 `55-company-design.md` ROUND 3 REVISION — the revised order (R4) and targets (R5)

| R4 step | status | proof |
|---|---|---|
| 1. P6 the gate fails closed | **(c) LIVE 12:44Z, uncommitted** | §1.2 |
| 2. P3 a stall changes strategy | **(c) LIVE 13:11Z, uncommitted** | backup `app/autopilot.py.bak-guardfix-20261014T131129Z` (13:11) and the P3c block |
| 3a. timestamp-window fix (L3801) | **(b) BRANCH ONLY** | `evolve3/window` `8571245aa` + test `258075de3`; live `grep -c 'julianday(' app/autopilot.py app/main.py` → **`0` and `3`** — the 13-site fix is not in the two files that matter most |
| 3b. retire `fleet_location_poll`; `npm install tsx`; fix `consecutive_empty_ticks` | **NOT VERIFIED** | not probed |
| 4. the bridge (sessions close `did`/`proof`/`result`/`left`) | **(d) UNBUILT** | `[ARTEFACT:]`/`[OUTBOUND:]` exist only as source strings (2 each); the production count was 0 of 78,649 in round 3 and was not re-measured |
| 5. heartbeat demotion to ledger items | **(d) UNBUILT** | no evidence in the live tree |
| 6. P5 → P7 → P8 → P9 | P5 **(c)**; P7/P8/P9 as §1.1 | — |

**R5's baseline table is now internally contradicted by its own source:** `R5` says 7-day completion 237/786 = 30.2 %; the DB says **257/836 = 30.74 %** (§3 below). Both are "7 days" on different days; the DB reading is the current one.

### 1.4 `07-pain-register-v2.md` — the 15 ranked pains

| # | pain | status 2026-10-14T19:35Z | proof |
|---|---|---|---|
| 1 | company cannot prove its work | **OPEN** | bridge unbuilt; `[ARTEFACT:]`/`[OUTBOUND:]` not re-measured against `work_sessions` |
| 2 | **the autonomy gate is fail-open** | **CLOSED in the live tree (uncommitted)** | §1.2 — fallthrough is `L1_SUGGEST`; dangerous names unclassified → L1; both outbound senders explicitly L1; chat path now branches on the verdict |
| 3 | instruction surface has no source of truth | **PARTIAL** | the round-1 rule is now present on **all four** loaded personas, but they sit in **two divergent groups**: md5 `01A2C5C8…` 54,551 B (ZABZ-TECH = ZABZ-YOGA) vs `53C63E2F…` 56,297 B (secratary-cloud = mac). 2 revisions, not 1. And the **mac's default preset is `yocheved`**, which has no such rule (§4) |
| 4 | journal divergence | **OPEN; (b) branch only** | `git -C /root/code/harness-config branch -a --contains evolve3/alloc` → **`+ evolve3/alloc`** (itself only). Never merged, never pushed |
| 5 | tool-failure / env-hostile have no rule | **CLOSED on the loaded surface** | ZABZ-TECH persona line 124: *"A missing dependency (`rc=127`, `not found`, `not configured`) is not retryable: escalate…"*; line 130: *"A hang is not a halt…"* |
| 6 | words spent on already-improved failures | **CLOSED on the loaded surface** | ZABZ-TECH persona line 60: *"**7b. When he corrects you, the correction is the requirement.** Restate it in one line, check…"*; line 63-64 carries the measurement *"`correction` 5.74% + `frustration` 6.58% = 12.3% of his turns, and no rule addressed either"* |
| 7 | zero-tool machine sessions / cost | **NOT VERIFIED** | — |
| 8 | silent failure has no transport | **NOT VERIFIED** | see P9 |
| 9 | every rolling window is one day too long | **(b) BRANCH ONLY** | `evolve3/window`; live `julianday(` = 0 in `autopilot.py`. The defect itself is **confirmed present**: §3.4 |
| 10 | `wrong-data` is #1 and the agent committed it 4× | **CLOSED on the loaded surface** | rule at ZABZ-TECH/YOGA line 82, cloud/mac line 75 |
| 11 | open-work queues are not queues | **NOT VERIFIED** | — |
| 12 | dead weight retried rather than retired | **NOT VERIFIED** | — |
| 13 | worktree/fleet hygiene | **NOT VERIFIED** | — |
| 14 | capability on one machine only | **PARTIAL; (b) branch only** | `evolve3/alloc` `19b48df9` adds the every-ref reader; unmerged |
| 15 | the record's own health is unmonitored | **NOT VERIFIED** | — |

### 1.5 `09-refreshed-system-spec.md` §4–§7

| item | status | proof |
|---|---|---|
| §4.1 one authoritative journal, host-banded ids | **(b) branch only** | `evolve3/alloc` `19b48df9`; `git branch --contains` → itself only |
| §4.2 one authoritative instruction surface | **PARTIAL** | the edits are largely **in the loaded files** (persona mtimes 2026-10-14 11:02 on both Windows boxes) but two revisions survive and `preset-drift.py` presence on every machine is **NOT VERIFIED** |
| §4.3 a rule for where a procedure lives | **CLOSED on the loaded surface** | the `secratary` → `secratary-cloud` correction is present: cloud/mac persona L127-128 name `secratary-cloud` as THE AUTHORITY and `secratary` as FROZEN |
| §4.4 a contract for a dispatched child | **NOT VERIFIED** | — |
| §4.5 the bridge | **(d) UNBUILT** | as R4 step 4 |
| §4.6 a transport for silent failure | **NOT VERIFIED** | as P9 |
| §4.7 a time-window that is one window | **(b) branch only** | `evolve3/window`; defect confirmed live (§3.4) |
| §5 staged architecture (gate → bridge → heartbeat demotion) | gate **(c)**; bridge **(d)**; demotion **(d)** | — |
| §6 the instruction surface, decided (5 rules) | **landed in the loaded personas** | grep of the ZABZ-TECH loaded file: L58/L60 (correction), L124 (`rc=127`), L130 (hang), L82 (`wrong-data`) |
| §7 item 1 timestamp helper + test | **(b) branch only** | `evolve3/window` |
| §7 item 2 gate matrix rebuilt, invariant test | **NOT as specified** | fail-closed default + 2 L1 entries landed instead (live); no `dispatcher_names ⊇ matrix_names` test found |
| §7 item 3 repetition guard redirects | **(c) LIVE 13:11Z** | §1.1 P3 |
| §7 item 4 `preset-drift.py` everywhere + 12 edits | **edits landed**; detector install **NOT VERIFIED** | §4 |
| §7 item 5 journal host-banded ids | **(b) branch only** | `evolve3/alloc` |
| §7 item 6 the bridge | **(d) UNBUILT** | — |
| §7 item 7 retire `fleet_location_poll`; `npm install tsx`; fix `consecutive_empty_ticks` | **NOT VERIFIED** | — |
| §7 item 8 deadline-checked endpoint probe | **NOT VERIFIED** | — |

### 1.6 v3 `DEPLOY-PLAN.md` (`/home/zabz/evolution-corpus-v3/DEPLOY-PLAN.md`)

Byte-identical to `/root/work/DEPLOY-PLAN-20261014.md`: `sha256sum` → `4e8586f1fabc1eef94a4c0698247ac5e47bd94c1c92d9880e52678d259853e31` for **both** paths.

| § | claim | status 2026-10-14T19:35Z |
|---|---|---|
| L12 §1 | *"the `evolve2/loop` change is ALREADY DEPLOYED AND RUNNING in production"* | **CONFIRMED** — it is deployed as uncommitted live edits (`M app/autopilot.py`), not as a commit. `evolve2/loop` `b70173f27` is **not** an ancestor of `master` |
| L19 §2 | applying `loop-full.patch` would destroy another session's uncommitted work | **CONFIRMED STILL TRUE** — 153 dirty files; `app/autopilot.py` has moved twice since (13:11Z, 15:33Z) |
| L22 §3 | *"the `evolve2/gate` change applies cleanly — but it does NOT do what its title says… 134 of its 150 rows carry `default: 4`… the fail-closed branch is unreachable"* | **CORRECT AT THE TIME, OVERTAKEN.** That was `evolve3/gate` `f8e2902b4` (150 rows, branch-only). At **12:44Z** a *different* fix not described by this plan landed in the live tree and **is** fail-closed (§1.2) |
| L25 §4 | `GET /health` is already `"ok": false` before any deploy; not a pass criterion | not re-measured (would need a live HTTP call; not in scope) |
| L115 §1.3 | *"Not verified"* — the reports' full-suite numbers not reproduced | **still not reproduced by anyone** |
| L480 §4.f | `tick_telemetry.autonomy_decisions_json` non-empty in 0 of 34,274 rows; the tick had already gone quiet | not re-measured |
| L588 §5.1 | the *"separate, reviewed change"* making the unclassified default L1: **NOT DONE** | **FALSE NOW — DONE at 12:44Z**, live, uncommitted (§1.2) |
| L619 §5.4 | rotate the DB password embedded in a filename; fix `dialpad-harvest-cron.sh`; delete the two files | **NOT VERIFIED**; explicitly deferred by the plan |
| L631 §5.8 | `_cleanup_stale_overrides()` writes the live DB inside every `get_level()` | **CONFIRMED PRESENT** — `get_level()` still begins `_cleanup_stale_overrides()` (live file line ~481) |
| L647–654 §6 | 8 things that do not hold up (gate headline, `build-loop.md` "did not edit any existing test", P2 zero footprint, `46 failed/3538 passed` unverified, live revision `561535b78` not `db07e8e0`) | live revision **still `561535b78`** (`git log -1`); the other items stand |
| L658 §7 | the plan was written to two unauthorised paths | unchanged |

**Net for DEPLOY-PLAN: its two central "don't ship this / it doesn't work" findings were right; its one "this is still open" finding (§5.1) was closed 30 minutes later and nobody updated the plan.**

---

## 2. The round-3 worktrees

Source: `git -C /root/work/evolve3-gate worktree list`, then per-directory `git rev-parse --abbrev-ref HEAD`, `git log -1`, `ls REPORT.md`, and `git branch -a --contains <sha>` / `merge-base --is-ancestor`.

| dir | branch | tip | last commit subject | merged? | REPORT.md |
|---|---|---|---|---|---|
| `/root/work/evolve2-base` | *detached* | `db07e8e02` | `docs(cfo): map the 51 modified files in the live checkout to the branches that already describe them (item 81)` | **n/a — base only** | no |
| `/root/work/evolve2-gate` | `evolve2/gate` | `78c151bef` | `evolve2/gate: update the autonomy default guard deliberately - an unclassified action must ASK` | **UNMERGED** (`merge-base --is-ancestor` vs `master` → not ancestor) | no |
| `/root/work/evolve2-loop` | `evolve2/loop` | `b70173f27` | `merge: WS-STORM (585b4dda) into evolve2/loop - clean, no conflicts` | **UNMERGED in git; LIVE in production as uncommitted edits** | no |
| `/root/work/evolve3-alloc` | `evolve3/alloc` | `19b48df9` | `journal(alloc): read every host's bands.tsv from every origin ref` | **UNMERGED** — worktree of `/root/code/harness-config`; `branch -a --contains` → itself only | **YES** |
| `/root/work/evolve3-alloc-applycheck` | `master` (no commits) | — | — | **ABORTED / EMPTY** | no |
| `/root/work/evolve3-alloc-fixture` | `master` (no commits) | — | — | **ABORTED / EMPTY** | no |
| `/root/work/evolve3-alloc-fixture2` | `master` (no commits) | — | — | **ABORTED / EMPTY** | no |
| `/root/work/evolve3-alloc-fx1` | `master` (no commits) | — | — | **ABORTED / EMPTY** | no |
| `/root/work/evolve3-alloc-fx2` | `master` (no commits) | — | — | **ABORTED / EMPTY** | no |
| `/root/work/evolve3-coverage` | *not a git repo* | — | — | **ABORTED / scratch** | no |
| `/root/work/evolve3-gate` | `evolve3/gate` | `f8e2902b4` | `evolve3/gate: classify every dispatched action by consequence; fail closed at L1` | **UNMERGED** (not ancestor of `master`/`origin/master`) | **YES** |
| `/root/work/evolve3-instr` | `evolve3/instr` | `aff4528c` | `evolve3/instr: final report (verified; adds the missed line-28 authority fix)` | **UNMERGED** — worktree of `/root/code/harness-config`; contained by itself only | **YES** |
| `/root/work/evolve3-merchant` | `evolve3/merchant` | `632d25a` | `evolve3/merchant: generic merchant receipt discovery keyed on the vendor order number` | **ISOLATED** (own repo, `No such remote 'origin'`) | **YES** |
| `/root/work/evolve3-repeat` | `evolve3/repeat` | `ce79c4b` | `report: P3c stopped on live-base drift (no code change committed)` | **ABORTED (deliberately), not merged** (own repo, no origin) | **YES** |
| `/root/work/evolve3-repeat2` | `evolve3/repeat2` | `ff1c89d` | `P3d: REPORT.md (test, three result lines, deploy patch, ranked deploy risks)` | **UNMERGED** (own repo, `origin` = `/root/work/evolve3-repeat`) | **YES** |
| `/root/work/evolve3-wedge` | `evolve3/wedge` | `b80602d84` | `wedge: cooperative cancellation deadlines, a wedge-visible loop surface, and a bounded auto-re-arm` | **UNMERGED** (`origin` = `/opt/company`; `merge-base --is-ancestor … master` → `NOT-ancestor-of-master`) | **YES** |
| `/root/work/evolve3-window` | `evolve3/window` | `71a5e23e9` | `docs: WIN report for the time-window repair (19 worklist sites: 13 defects, 6 already correct)` | **UNMERGED** | **YES** |

**REPORT.md exists in 8 of 17:** `evolve3-{alloc,gate,instr,merchant,repeat,repeat2,wedge,window}`. Claimed result, one line each (verbatim first-headline from each file):

1. **evolve3-alloc** — *"make the reservation-window reader see every host's `bands.tsv`"*: adds `ledger_ref_rows()` reading every `refs/remotes/origin` ref (≤25, 8 s per ref, 20 s sweep) and folds it into `allocation_ceiling()`. **Branch only; no live `append` was run anywhere.**
2. **evolve3-gate** — *"the fail-closed autonomy gate, done properly"*: 150 generated rows, 31 actions moved to L0/L1, regression test fails 2 on base / passes patched. **Branch only — and DEPLOY-PLAN §3 reports its rows are mostly `default: 4`, so it would not have worked.**
3. **evolve3-instr** — *"always-on instruction rebuild"*: preserve + edit + fix commits on `evolve3/instr`; **never pushed**; the live `~/.dsh` was deliberately left alone.
4. **evolve3-merchant** — *"merchant-receipt coverage: 39.5 % → 95.0 %"*: measured on a DB **copy** (`/dev/shm/mv3/db-merchant.sqlite`); `receipt_parser.py` md5 unchanged. **Isolated repo; not merged.**
5. **evolve3-repeat** — *"P3c — repetition-guard redirect"*: **"STOPPED on live-base drift"** (the live md5 changed mid-run); exact change recorded, patch **not** produced or committed. **Honest abort.**
6. **evolve3-repeat2** — *"P3d — regression test and deploy-ready patch"*: patch at `/tmp/evolution-v3/P3c-prepared.patch` (4,913 B), `git apply --check` exit 0, base `30a4a185…` → `6c312a8b…`; **"Any live or deployed behaviour… therefore unverified"**. *(That hedge is now obsolete: a P3c block **is** live — §1.1.)*
7. **evolve3-wedge** — *"the always-on loop that wedges itself and goes quiet"*: py-spy attribution of the 600 s wedge; cooperative cancellation deadlines + bounded auto-re-arm. **Branch only; nothing deployed.**
8. **evolve3-window** — *"WIN report — T-format time-window defect, 13 sites repaired"*: 13 sites → `julianday()`, 6 boundary tests, branch `evolve3/window` at `258075de3`. **Branch only; the live `autopilot.py` has 0 `julianday(` calls.**

---

## 3. The company's live state right now (read-only, `/root/authority.db`, `sqlite3 -readonly`)

`ls -la /root/authority.db` → **29,151,342,592 B (29.15 GB)** — *the brief's "15 GB" is wrong*. Disk 84 % used, 24 G free.
DB clock: `SELECT datetime('now'), strftime('%Y-%m-%dT%H:%M:%S','now');` → `2026-10-14 19:31:31 | 2026-10-14T19:31:31`.
Window = last **7 calendar days** = 2026-10-08 … 2026-10-14 (`date(col) >= date('now','-6 days')`).

### 3.1 Work-session completion rate
```sql
SELECT date(started_at) AS day, COUNT(*) total, SUM(status='completed') completed,
       ROUND(100.0*SUM(status='completed')/COUNT(*),1) rate_pct
FROM work_sessions WHERE date(started_at) >= date('now','-6 days') GROUP BY day ORDER BY day;
```
```
day         total  completed  failed  paused  rate_pct
2026-10-08  144    39         102     3       27.1
2026-10-09  108    32         75      1       29.6
2026-10-10  74     25         49      0       33.8
2026-10-11  95     24         71      0       25.3
2026-10-12  88     24         62      2       27.3
2026-10-13  186    60         126     0       32.3
2026-10-14  141    53         60      27      37.6
TOTAL 7d    836    257                 —       30.74
```
**7-day completion rate = 257/836 = 30.74 %.** (`paused` is the dominant lifetime non-completed status: 47,227 rows.) R5 in `55-company-design.md` states 237/786 = 30.2 % — same order, different window; **use 30.74 %**.

### 3.2 Model spend per day
`agent_budgets` **exists but holds 0 rows** — it cannot source spend. `model_usage.estimated_cost_usd` (USD) is the ledger.
```sql
SELECT date(created_at) day, COUNT(*) calls, ROUND(SUM(estimated_cost_usd),6) spend_usd
FROM model_usage WHERE date(created_at) >= date('now','-6 days') GROUP BY day ORDER BY day;
```
```
2026-10-08  2110  $19.734298
2026-10-09  1762  $16.793386
2026-10-10  1337  $12.259059
2026-10-11  1386  $15.198601
2026-10-12  1193  $13.443360
2026-10-13  2758  $23.322927
2026-10-14  2978  $31.236154
TOTAL 7d   13524  $131.987784  (282,406,926 tokens)
```
Separate small ledger for contrast: `tick_telemetry.total_cost` = **$0.977172 over 7 days** — which is why `tick_telemetry` cannot witness spend.

### 3.3 The three failure markers (row-hits; the strings are *values*, not schema: `.schema | grep -i` → no output)
| string | total row-hits | where |
|---|---|---|
| `STEP_BUDGET_EXHAUSTED` | **2,671** | `work_sessions.output_log` 1,849; `dsh_session_events.raw` 819; `job_queue.result_json` 2; `tasks.description` 1 |
| `TOOL_LOOP_DEADLOCK` | **704** | `work_sessions.output_log` 244; `dsh_session_events.raw` 239; `job_queue` 100; `goal_steps` 34; `proactive_events` 35; `tick_telemetry` 34; + 8 more tables |
| `STALLED_REPEATING` | **954** | `work_sessions.output_log` **546, all as the full marker `STALLED_REPEATING_OUTPUT`** (bare = 0); `dsh_session_events.raw` 408 |
Method: exact case-sensitive `instr()` over a curated table set **plus an exhaustive generated sweep of all 1,451 remaining TEXT columns**; `dsh_session_events` via its provably complete FTS index (`COUNT(fts)=COUNT(src)=2,331,841`) then exact-verified. **These are row-hits, not distinct incidents** — one incident echoes across several tables, so do not sum them. Nothing in any `dialpad_*`, `email_*`, `sms_log`, `call_log`, `voice_*` or chat table.

### 3.4 The timestamp trap — reproduced, and it is exactly 24 hours
Columns are ISO **T**-format (`work_sessions.started_at` = `2026-10-14T19:29:30.637032+00:00`; `model_usage.created_at` same shape), while `datetime('now','-7 days')` returns a **space**-separated string and `'T'`(0x54) > `' '`(0x20), so every T-value on 2026-10-07 compares greater than the cutoff.
```
                        SPACE cutoff 7d | calendar 8d | calendar 7d | ISO-T rolling 7d
work_sessions           958             | 958         | 837         | 698
model_usage             15437           | 15437       | 13529       | 11613
```
**`datetime('now','-7 days')` gives *exactly* the 8-calendar-day count (958 = 958; 15,437 = 15,437).** Correct 7-calendar-day counts are **837** and **13,529**. Any surviving report quoting ~958 sessions or ~15,437 model calls for "7 days" is inflated by one full day. Note also `proactive_events.created_at` is **space**-format (its DEFAULT is `datetime('now')`) — a mixed-format table population, so use `date()` grouping, never a string comparison.

---

## 4. The instruction surface — installed (loaded) files, not checkouts

`agent-presets` default: ZABZ-TECH / ZABZ-YOGA / secratary-cloud read `zabz` (`settings.yaml.imported` L11 `default: zabz`); **the mac's live `settings.yaml` says `default: yocheved`**; linux-pc has no preset install at all.

| node | how reached | **loaded** persona | size | mtime | md5 | `wrong data` rule | names `secratary-cloud`? |
|---|---|---|---|---|---|---|---|
| **ZABZ-TECH** | local | `C:\Users\ezabz\.dsh\.agent-presets\zabz\agent.cordis.yml` | 54,551 | 2026-10-14 11:02:05 | `01A2C5C80C4BF45F3E7CB72BB1CBAEC3` | **YES** — L82 | **YES** — `secratary-cloud`=7, bare `secratary`=3 |
| **ZABZ-YOGA** | `ssh laptop-ts` (`ssh zabz-yoga` times out) | `C:\Users\ezabz\.dsh\.agent-presets\zabz\agent.cordis.yml` | 54,551 | 2026-10-14 11:02:30 | `01A2C5C80C4BF45F3E7CB72BB1CBAEC3` | **YES** — L82 | **YES** — 7 / 3 |
| **secratary-cloud** | `ssh secratary-cloud` (root) | `/root/.dsh/.agent-presets/zabz/agent.cordis.yml` | 56,297 | 2026-10-13 14:13:51 +0000 | `53c63e2fe0cd0eb4c5065b9a1384eef4` | **YES** — L75 | **YES** — 6 / 3 |
| **linux-pc** | `ssh linux-pc` (zabz) | **NO INSTALLED FILE** — `~/.dsh/.agent-presets` and `/root/.dsh` do not exist | — | — | — | **n/a** | **n/a** |
| **lakewooechsmini** | `ssh mac-mini` (lpt); `ssh lakewooechsmini` fails (wrong user) | `/Users/lpt/.dsh/.agent-presets/zabz/agent.cordis.yml` | 56,297 | 2026-10-13 10:23:52 | `53c63e2fe0cd0eb4c5065b9a1384eef4` | **YES** — L75 | **YES** — 6 / 3 |
| **(mac ACTUAL default)** | same | `/Users/lpt/.dsh/.agent-presets/yocheved/agent.cordis.yml` | 34,258 | 2026-10-13 10:23:52 | `40e7f99f6f85d63869f8fed27bb1cee5` | **NO — no match at all** | YES — 5 / 4 |

**Findings:**
1. **The round-1 "wrong data" rule is now present on all four loaded `zabz` personas** — including ZABZ-TECH, which `11-instruction-convergence-plan.md` §0 certified as *"FALSE on the loaded file. It is still 58,677 B, the rule heading is absent (0 hits)"*. It is 54,551 B and the rule **is** there (L82). **That claimed-not-landed has since landed.**
2. **The surface has converged from 5 revisions to 2, not 1**: `01A2C5C8…` (both Windows boxes) vs `53C63E2F…` (cloud + mac). md5-divergent inside a single fleet.
3. **linux-pc loads no `zabz` persona at all** — no `.agent-presets` under any home, no `~/.dsh/settings.yaml`. Only the shipped preset set (`standard`/`cordis`/`minimal`/`ptc`) can mount. Every one of the 190+ `agent.cordis.yml` files on that box is a checkout/worktree/fixture. **This is the largest instruction-surface gap and it is new information: pain #3 and spec §4.2 assumed four machines each with a loaded persona.**
4. **The mac's defaulted preset is `yocheved`, which contains no `wrong-data` rule** — so the one machine with a customer-facing default runs a persona missing the round-1 fix.
5. §6's five new rules are verifiably present in the loaded Windows persona: L58/L60 (the correction rule, with its measurement attached), L124 (`rc=127` not retryable), L130 ("a hang is not a halt"), L82 (`wrong-data`).

---

## 5. The open loops

Collected from `/home/zabz/evolution-corpus-v3/{DEPLOY-PLAN,05-copilot-delta,09-wake-loop,11-instruction-convergence-plan}.md`, the 8 `evolve3-*/REPORT.md`, and journal handoffs **H3617–H3627** (`python .../journal/tools/journal.py list --kind handoff --since 2026-10-13 --limit 40` → H3586…H3627). `/home/zabz/evolution-corpus-v3/corpus/` is **empty** (`ls -laR` → only `.`/`..`); `find … -name '*.md'` returns exactly the 4 files above.

**A. Products of the round that were never built (highest value to a round-4 planner)**
1. **The bridge** — every work session closes with `did`/`proof`/`result`/`left`, or `blocked` with a measurement. Spec §4.5, spec §7 item 6, R4 step 4. **Unbuilt; it is the change that makes every other claim checkable.**
2. **A considered autonomy matrix + the invariant test** (`dispatcher_names ⊇ matrix_names`; L4 only from a named allow-list). The live fix closes the *default*; it does not name the dangerous families. R4 step 1, spec §5.1/§7 item 2.
3. **A shared timestamp-window helper + boundary test** — the 7-site fix is branch-only and `app/autopilot.py` still has 0 `julianday(`. Spec §4.7/§7 item 1. Explicitly "reporting-only, no risk, do it first".
4. **`preset-drift.py` installed and run on every machine**, and the drift detector wired into the sync so a refusal reaches the journal. Spec §4.2/§7 item 4.
5. **Journal host-banded ids + `idguard` pointed at working trees along with repair of the 63 colliding ids.** Spec §4.1/§7 item 5; `evolve3/alloc` is branch-only.
6. **A deadline-checked probe against `company-api`'s own endpoint, escalating.** Spec §4.6/§7 item 8; proof of need is `H3660` (`active`, `NRestarts=0`, answered nothing for 50+ minutes).
7. **Retire `fleet_location_poll` (dead since 2026-09-29, 414 consecutive failures); `npm install tsx` for amazon/ebay (a missing devDependency, i.e. REPAIR not retire); fix `consecutive_empty_ticks` (increments on a blank-detail *success*).** Spec §7 item 7, R4 step 3.

**B. Explicit "deliberately not done" (builders' own words)**
- `evolve3-instr/REPORT.md:192` "**Deliberately not done**": did not change a single composition row; did not apply §8 #1/#2/#8, nor #6/#10/#12; did not edit `~/.dsh` or deploy anything (`sync.py` run `--dry-run` only); `fast-search/SKILL.md` still names `secratary` for the comms index — left alone.
- `evolve3-repeat/REPORT.md` — **STOPPED on live-base drift**, no code change committed; patch deliberately not produced.
- `evolve3-alloc/REPORT.md:163/165` — "**No live `append` was run anywhere**"; "**`journal.py claim` / `publish` were never run** (they push)"; `verify.py` under Python 3.10 unverified.
- `evolve3-wedge/REPORT.md` — nothing deployed, restarted, enabled or disabled.
- `evolve3-window/REPORT.md` — "Nothing was pushed; `main` was never touched."
- `evolve3-gate/REPORT.md` — "**Nothing under `/opt/company` was written.**"

**C. Claimed-done but hedged (round-4's "verify before believing" list)**
1. DEPLOY-PLAN L647: the gate build's title and commit claim the L4 default was closed — *"It was not. … The report's prose survives scrutiny; its headline does not."* (Still true of `evolve3/gate`; **no longer true of the live tree** — cf. §1.2.)
2. DEPLOY-PLAN L115/L652: *"Full-suite claims from both reports are **NOT verified**"* (`46 failed, 3538 passed`).
3. DEPLOY-PLAN L650: loop **P2** *"has never once fired in production … Do not claim P2 works"* (markers `[ARTEFACT:` 0, `[OUTBOUND:` 0, `[ALREADY-CLOSED:` 0, `[WORK-DONE-INSUFFICIENT:` 0 across 78,649 rows).
4. DEPLOY-PLAN L651: the loop benefit `46.3 % → 39.4 %` is *"not statistically separable. I am not calling it green."*
5. `09-wake-loop.md:78` — *"Countable, yes. Verifiable as proof quality, no"*: 412/424 attempts "have a proof" **overstates** it.
6. `05-copilot-delta.md` L193 — *"Do not quote 25 % → 2.38 % as a like-for-like measurement"* (two Copilot sources disagree 25×).
7. `evolve3-repeat2/REPORT.md:676` — *"**Any live or deployed behaviour** … is therefore unverified"*; `_build_work_prompt` "was read, not executed". *(Overtaken by events — the P3c block is live.)*
8. `H3627` — *"lpt-web IS COMPLETE AND COMMITTED"* but **"not pushed"**; README/CHECKSUMS "still staged at `/tmp/handoff/ready/`".
9. `H3626` — parity `973 REACHABLE` is hedged by *"The inventory cannot see handler-level gates, which is a known understatement."*

**D. Cross-cutting closed loops the docs say cannot be closed by measurement**
- `09-wake-loop.md:105` — *"`nothing-todo` / no-close balance: **NOT DERIVABLE from the store**"* — `work.py` keeps no per-shift outcome column and `attempt` has no `nothing-todo` result value, so a shift that correctly claimed nothing leaves **no row at all**. *"This is the one number the deliverable asked for that the data cannot produce."*
- `09-wake-loop.md:110/113` — a 7-day figure is **missing by construction** (history starts 2026-10-13) and per-CFO-shift dollars are missing (`~/.cfo/shifts.jsonl` has no dollar field).
- `05-copilot-delta.md:222` — *"**DSH lost this.** There is no equivalent table for DSH sessions in the authority … `sessions-archive` does not even exist"* on that node; the Copilot→DSH comparison is a research artefact that dies with `/home/zabz/evolution-corpus-v2`.
- `05-copilot-delta.md:292` — **a live preset points at a deleted directory** (`~/code/personal-secretary-mvp/docs/secretary-replacement-audit/` → *"No such file or directory"*). Every session that obeys it wastes a step. **This is a one-line fix and it is not in any of the four documents' change lists.**
- `11-instruction-convergence-plan.md:586` §5.4 — **three files exist ONLY as uncommitted working-tree blobs, unreachable from any ref**: ZABZ-YOGA `parallel-agent-orchestration` 13,700 and `secretary-wake` 18,975, ZABZ-TECH `lpt-label-printing` 10,275 (`git log --all --find-object=…` → `(nothing)`). *"A `git clean`, a `git checkout -- .`, or a fresh clone elsewhere destroys both … **Commit them first.**"* — **NOT DONE.**

**E. Journal handoffs H3617–H3627 — the immediately-open, revenue-adjacent work**
- **H3627 (18:39)** — `NEXT, IN ORDER: deploy the API (migration included) -> lpt-web payment cancel --payment-id 3380 --apply … -> pay-notice draft --order WO26100812739 --apply -> show the body -> send on the owner's per-message approval.` Plus: two branches **"not pushed"**; `README/CHECKSUMS still staged at /tmp/handoff/ready/`; two duplicate tax branches — "keep one".
- **H3626 (17:19)** — `NEXT, AND IN THIS ORDER: read both reports; **verify the parity test and the guards myself** (reproduce, do not accept); decide the deploy (a production API restart is the manager's call, not a builder's); then mint a correct link, show the body, and send on the owner's per-message approval.` `STILL OPEN AND TRACKED:` **P3801** (plaintext default ADMIN password in `seed_admin_user/migration.sql`), **P3169** (`update_order()` hardcodes the status-history reason), media analysis returned nothing.
- **H3624** — *"The data copy is RUNNING, and it is **not yet verified** — do not tell anyone it is finished."* `Verification is not done.`
- **H3622/H3621** — `owner_decision_queue row #512` **NOT yet amended**; two amend attempts hit `database locked (attempt N/4)`; a retry loop (`nohup bash /tmp/amend-512.sh`) was left running; H3621 concedes the amend **"may have needed a retry"** and corrects H3619's citation (`L3802`, not `L3788`).
- **H3625/H3623** — the Steinfeld SD card (64 GB, serial 45CB-13FF) **still has NO case file of its own** and 2,776 files of a family's photographs; logging it as found property and imaging it is **"offered, not done"**.
- **H3619** — ownership **not** confirmed; nothing recovered; no customer message; no refund; the owner's park untouched. **H3618** — two explanations stay open; next is the flex/current test, then QC, then the screen evaluation. **H3620** — re-read B&H live (Cloudflare-gated), verify the Krum v. WD case number, and *"No ≥100 GB post-cache test exists for ANY USB4/V3-generation drive"*. **H3617** — *"12 of 16 jobs recorded NO copy duration, so the shop does not know what its own media costs it."*

---

## 6. What I could NOT verify, and why

Each of these is a place where a confident sentence would have been a guess.

1. **Whether `docs/dsh-evolution-v2` was ever committed anywhere.** Verified absent from ZABZ-TECH's `origin/main`, its whole object history, the authority, linux-pc, mac-mini, and the authority's two checkouts. **Not verified:** whether the `mirror` remote (`linux-pc:/home/zabz/harness-config-mirror.git`) or `origin` (`secretary-ts:…`) hold it in an unfetched ref — I did not fetch (a fetch writes `.git`, and the rules are read-only).
2. **`preset-drift.py` installation on any machine.** The spec makes its exit-0-on-every-machine the close condition for pain #3; I did not look for the script.
3. **P7 (memory that is read).** One comment line (492) is all I found; I did not read the work-loop session start or check whether the zero-caller helpers were deleted. **Not verified.**
4. **P9/P10 and pains #7, #8, #11, #12, #13, #15, and the dead-weight/metadata fixes** (retire `fleet_location_poll`, `npm install tsx`, `consecutive_empty_ticks`). Not probed at all. **Not verified.**
5. **Whether the live `[ARTEFACT:]`/`[OUTBOUND:]` markers ever fire.** I counted marker *source strings* in `autopilot.py` (2 and 2), not their occurrence in `work_sessions` across 78,649 rows. The round-3 "0 times" claim was **not re-measured**.
6. **Which process is running which code.** R2 of `55-company-design.md` establishes that an mtime is not the deployment boundary — `ExecMainStartTimestamp` is. I read file mtimes (12:44Z autonomy, 13:11Z/15:33Z autopilot) but **did not read `systemctl show company-api -p ExecMainStartTimestamp` or `journalctl`**, so I cannot say whether the running process picked any of it up. If the service last started before 12:44Z, **none of the live fixes are in force yet.**
7. **The exact preset each machine defaults to.** `C:\Users\ezabz\.dsh\settings.yaml` does not exist on ZABZ-TECH (only `settings.yaml.imported`, `default: zabz`); `/root/.dsh/settings.yaml` does not exist on the authority. The mac's is read directly (`default: yocheved`). linux-pc's is unlocatable.
8. **linux-pc's exact loaded file.** The `default` is not resolvable inside its `node_modules` mount; "no `zabz` persona" is solid, the specific fallback is not.
9. **DEPLOY-PLAN L25 (`GET /health` already `ok: false`)** — not re-probed (would need a live HTTP call).
10. **The password-in-a-filename and `dialpad-harvest-cron.sh` items (L619 §5.4)** — deliberately not touched.
11. **Agent-budget spend** — `agent_budgets` holds 0 rows, so "spend per day" is `model_usage` only; per-agent attribution is impossible from that table.
12. **The v3 reports' own measurements were not re-run.** I read the reports and the live tree; I did not reproduce their suite numbers, their parity test, or their DB counts. Where a report contradicts the live tree (P3, P6) I have said so and shown the live command.
13. **`/root/work/evolve3-*/findings-*.md`** (4 files across 4 dirs) — not opened.
14. **The handoffs' production-record claims** (case files, task statuses, `owner_decision_queue` rows) — not verified in the company DB.

---

## 7. The single biggest gap

**Nothing in this round is merged. The company's live behaviour is 1,723 inserted and 372 deleted lines of uncommitted working-tree edit inside `/opt/company`, on a feature branch, and the round-3 documents describing that work are themselves uncommitted and exist on one laptop.**

Three consequences a round-4 plan must absorb:

1. **The largest documented defect — the fail-open autonomy gate (pain #2, spec §5.1, DEPLOY-PLAN §5.1) — is already fixed in the live tree at 12:44Z, uncommitted, and every round-3 document still says it is open.** A round 4 that "builds the gate fix" would be re-doing finished work; a round 4 that *commits and tests what is live* is doing the work that does not exist yet.
2. **The fixes that ARE merged into `master` number zero.** `evolve2/gate`, `evolve2/loop`, `evolve3/gate`, `evolve3/window` are all non-ancestors of `master`/`origin/master`; the eight `REPORT.md`s are in eight directories on one host. One `git clean`, one container rebuild, or one deploy from `master` reverts the entire round — exactly the failure `evolve3-repeat` stopped itself to avoid.
3. **The measurement layer is sound but one day wide by default, and the marker counts are row-hits, not incidents.** Use `date(col) >= date('now','-6 days')` (837 sessions / 13,529 calls) and never `datetime('now','-N days')` (958 / 15,437 — a verified 24-hour inflation). Live baseline for round 4: **30.74 % completion (257/836), $131.99 model spend over 7 days, `STALLED_REPEATING_OUTPUT` the largest residual failure marker at 546 `work_sessions` rows.**
