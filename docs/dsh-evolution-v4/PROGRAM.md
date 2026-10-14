# PROGRAM v4 — DSH Evolution, round 4 (2026-10-14, opened 19:20Z on ZABZ-YOGA)

**The owner's command, 2026-10-14 (third time he has issued it), abridged and verbatim:**

> *"when we set up dsh and migrated from vs code copilot to dsh a few months ago I had you read every
> single copilot session ever and classify them… it's time for the next evolution. Now that we
> migrated to the Secretary Cloud… it's time to really evolve our systems… go through every single dsh
> session… we need to fan out orchestrate through sub agents, categorize all my conversations, find
> all the pain points, find what I want. I want the systems evolved and fixed. **I want the
> instructions and identities changed to better match what we really need**… going back to the copilot
> sessions also… I want this to be very robust. I want this to be running for real with real
> engineering"*

and the second ask:

> *"look at your memories and make sure that you remember everything, and document everything
> properly. And have an entire refreshed AI system about what's needed and what's not in this setup"*

and the headline:

> *"audit and evolve the AI company that lives on the Secretary Cloud server tremendously… the AI
> company there is supposed to be you. It's like a version of you that just always stays alive. So it
> needs to be brought to the next level and needs to be an order of magnitude better, faster and most
> importantly more capable and autonomous and smart."*

He also said, plainly: *"This is the command another session got and worked on very hard today. So a
lot of it was done, but I want you to start again… update and evolve it fully and fix everything and
make it even better."*

---

## 1. What round 4 did differently, and why that was necessary

Rounds 1–3 produced good analysis and almost no landed change. Round 4's **first act was therefore an
inventory of what was actually true**, and it changed the plan twice:

| round 3 believed | round 4 measured | consequence |
|---|---|---|
| "P6 is not live and the safety hole is open" | **P6 IS live** and genuinely fails closed — `UNCLASSIFIED_ACTION_LEVEL = L1_SUGGEST`, `delete_tool` L0, `fire_agent`/`gmail_send`/`run_command` L1, and three stale L3 rows in `autonomy_levels` are **clamped to their ceiling** | do not rebuild the gate; verify it this way instead |
| "the fixes need building and deploying" | **P1–P6 were already live — in no commit.** 25 modified `app/` files, ~4,100 lines, the running company | preserve them before anything else |
| "sessions fail because the budget is small" | the budget is already 20; sessions now fail **at 20/20 and at 5/5**, spending every step on `repo_search`/`repo_list_dir`/`repo_read_file`/`list_tasks` | the defect is **convergence**, not the size of the budget |

**The single most valuable thing round 4 did was make the running system a commit.** `14ebb2322`
(branch `preserve/live-tree-20261014`) captures the live tree; `git checkout -- app/` would have
erased the work-loop budget change, the information-gain progress rule, the stall redirect, the
completion markers, the resumable opening context, the fail-closed gate and the chat-path fix.

---

## 2. The measured state at round 4's start (corrected windows)

Captured `2026-10-14T19:26:58Z` by `scripts/evolution/capture-company-baseline.py`, every window built
with `strftime('%Y-%m-%dT%H:%M:%S','now',...)` because `datetime('now','-N days')` against a T-format
column silently covers N+1 days (`L3801`).

| measure | value |
|---|---|
| work sessions, 7 days | 578 failed · 259 completed · 33 paused (**~30 % completed**) |
| `STEP_BUDGET_EXHAUSTED` | **389** (67 % of failures) |
| `TOOL_LOOP_DEADLOCK` | 157 |
| `STALLED_REPEATING_OUTPUT` | 49 |
| completion **by the session itself** (`TASK-CLOSED-BY-SESSION`) | 44 on 10-14, **0 on each of the 10 preceding days** |
| model spend | 135.24 USD / 7 days; 31.18 USD on the final day |
| tasks retried with 2+ attempts | 238 — of which 78 ever completed |
| tick self-grading | 901 `complete` / 904 `productive` against 578 failed work sessions |

---

## 3. Workstreams and their outcome

| id | workstream | output | state |
|---|---|---|---|
| **R4-A** | recon: what landed vs what was claimed | `dsh-evolution-v2/ROUND4-RECON.md` | **done** |
| **R4-B** | preserve the live tree | branch `preserve/live-tree-20261014` (`14ebb2322`) | **done, verified byte-identical** |
| **R4-C** | corpus v4 — delta extraction, finalize, 19 whole-session shards | `/home/zabz/evolution-corpus-v4/` — **7,755 sessions**, 1,149 owner sessions, 4,758 owner turns, 19 shards, 1,008 sampled sessions (87.7 %) | **done** |
| **R4-D** | reader fleet over the owner's own turns | `readers/R01..R19.md` | **7 of 19 returned** — census unbuilt |
| **E4** | WS-LOOP — a session that reads forever must converge, and one that ends must leave a handoff | `RECON_SOFT_LIMIT` 6 / `RECON_HARD_LIMIT` 10, `[RECON-DIRECTIVE:]`, `[RECON_BUDGET_EXHAUSTED:]`, `[HANDOFF: did/proof/result/left]` | **built, tested, deployed** |
| **E5** | WS-TRANSPORT — a probe that asks whether the service did its job, and the task ceiling | `liveness_probe.py`, the consuming-task predicate, systemd units | **built, tested, deployed** |
| **E6** | WS-MODEL — model ids resolve at runtime | `model_resolution.py`, 6 operational sites, a guard with an allow-list | **built, tested, deployed** |
| **E7** | WS-MEMORY — an attempt context that is bounded and honest | `attempt_context.py`, the repaired `run_memory_consolidation` import | **built, tested, deployed** |
| **M4** | journal id allocation — one global ceiling | `journal-ceiling-refresh.py` + the cron, installed and probed | **done: `next-id pain` P3212 → P3865** |
| **H4** | instruction & identity surface v2 | `10-instruction-surface-v2.md` | **NOT STARTED** |
| **S4** | census v4, owner-want extraction, pain register v4 | `07-pain-register-v4.md` | **NOT STARTED** (needs the readers) |
| **C4** | the company's *architecture* — should the bespoke loop remain | — | **NOT STARTED** |

---

## 4. What is deployed and how it was verified

Deployed `2026-10-14T20:16:07Z` by `scripts/evolution/deploy-round4.sh`, 10 files, backup at
`/var/lib/authority-snapshots/r4-deploy-20261014T201607Z`.

Evidence, each a command:
1. **Content**: md5 of every deployed file against the integration tree → **0 mismatches**.
2. **The process picked the code up** (`ExecMainStartTimestamp` 17:10:50 → **20:16:07** — an mtime is
   not a deployment, `L3803`).
3. `/health` → `{"ok":true,…,"database":{"ok":true}}`.
4. **In the running interpreter**: `attempt_context cap=1500`; `liveness_probe ok=False … finance` (a
   true reading, not a false alarm); `model_resolution id=secretary-fast source=route_alias
   validated=True`; `autonomy unclassified=L1_SUGGEST execute=False`; `autopilot RECON_SOFT_LIMIT=True
   RECON_HARD_LIMIT=True HANDOFF=True`.
5. **The loop is alive**: a new work session created 25 s after the restart; **it wrote a
   `[HANDOFF: did=…]` within 100 seconds** — the first proof the new path fires in production.

**The regression gate**: four suites, **63 passed**; the whole test tree compared against the base,
**51 failing node ids on each side, 0 new**. `scripts/evolution/round4-loop-baseline.sh` is the
before/after measurement, and its own first mistake is recorded in §6.

---

## 5. Rules round 4 holds itself to

* **A claimed fix is a command and its output line.** `cmp`/`md5sum` for content, `ExecMainStartTimestamp`
  for deployment, a row for behaviour.
* **Verify the surface the system actually reads.** The loaded persona, not the checkout; the running
  interpreter, not the source; `next-id`, not the file that was edited.
* **A builder's report is a claim.** All four workstreams were reproduced by the manager before merge;
  three of the four **refuted a premise in their own brief**, which is the outcome the briefs asked for.
* **Zero new test failures, proven by set comparison**, never by a pass count.
* **The authority is read-only for analysis and writable only for a deliberate, backed-up, verified
  deploy.** Never a build, never a test suite, never a corpus scan.
* **`secratary` is FROZEN** (`settings/machines/host-posture.tsv` decides).

---

## 6. Failure of my own this round, recorded rather than smoothed

1. **I asserted a path did not exist on the authority** (`/home/zabz/code/harness-config`) in a
   journal handoff. **It does exist.** The real defect in that cron was different — it ran
   `journal.git_max()` in a separate interpreter and discarded the result — and the correction stands
   on its own, but the claim I made was false and is corrected here.
2. **My first preservation commit swept in 35 `.bak-*` files**, and a nested ssh mangled its message
   with backtick command substitution. Both fixed (amended commit, `.gitignore`).
3. **I called a regression that did not exist.** Four `chat_action_tasks` failures looked like my
   merges' fault; they are `ModuleNotFoundError: No module named 'twilio'` in the pytest venv and are
   **identical on base**. The isolation run across base → transport → model → integration settled it.
4. **My regression comparison was meaningless the first time**: a `sed` stripped the node ids, leaving
   bare `FAILED`, so `comm` reported 91 "new" failures that were 91 identical ones. Redone correctly:
   51 = 51, 0 new.
5. **Three failed attempts to install one cron line**, each blamed on crontab, because a PowerShell
   here-string wrapped the base64 payload. `L4065`.

---

## 7. What is next, in order

1. **Measure the loop properly.** `round4-loop-baseline.sh` at +2 h and +24 h. The claim to test is
   narrow: `STEP_BUDGET_EXHAUSTED` falls, `RECON-DIRECTIVE`/`RECON_BUDGET_EXHAUSTED`/`HANDOFF` appear,
   and completion by the session rises. If it does not move, the loop change is the wrong lever and
   §8's condition applies.
2. **R4-D is incomplete and it is the owner's first ask**: 12 more shards, then the reader census, then
   `07-pain-register-v4.md` with one owner and one verification command per row.
3. **H4 — the instruction surface.** The measured frictions the surface does not currently serve:
   `correction` 5.74 %, `frustration` 6.58 %, `restart-agent` 2.05 % have **no rule**; `wrong-data` is
   the #1 measured failure at 12.0 %; `repeated-work` 9.3 %. Meanwhile the longest paragraphs serve
   *do-not-ask*, the two rarest frictions. The build must also **converge**: `autosync.ps1` ships
   `git archive HEAD`, so a correction that is not committed comes back.
4. **Two live correctness jobs** the builders surfaced and nobody has done: the dead
   `_prior_attempt_context` at `app/autopilot.py:3768`, and `agent_worker.py:3054`'s literal
   `"secretary-fast"`.
5. **P9 — the transport for silent failure is deployed but NOT scheduled.** The systemd units exist in
   `/opt/company/deploy/`; nothing runs them. A probe nobody runs is a document.
6. **C4 — the architecture question.** The company fails ~30 % of what it attempts and cannot prove
   most of its completions, while the cron wake loop closes with `did/proof/result/left` at **0.09 USD
   per proven item**. The staged path is: fix the loop (done) → give every work session the same
   close-with-proof discipline (partly done via `[HANDOFF:]`) → only then consider replacing the
   bespoke loop with the ledger discipline.

## 8. The condition under which this direction is abandoned

If, measured over **at least 50 work sessions after the deploy**, a session that is forced to converge
proves **no** more likely to close with evidence than one that was not — then convergence is not the
binding constraint, the remaining failure is something else, and the next round measures rather than
builds. **A change that does not move one of §2's rows is not a fix.**
