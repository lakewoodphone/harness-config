# 09 — The refreshed system spec: what is needed, and what is not

**2026-10-14, round 3.** The owner's second pillar, verbatim: *"go back and look at your memories and
make sure that you remember everything, and document everything properly. And have an entirely refreshed
system about what's needed and what's not in this setup."*

This is that document. It is **prescriptive, not descriptive** — every "keep", "cut" and "add" below
carries the measurement that decides it, and a reader disagreeing with a line can go and re-measure it.
It supersedes `07-target-system.md` (round 1, 2026-10-13) where they conflict.

---

## 1. The diagnosis in one paragraph

This estate has **two** always-alive agents, **four** lineages of its own instructions, **four**
journals, **thirteen** subsystems that report healthy while producing nothing, and **no single source of
truth for anything shared**. It is not short of capability; it is short of *agreement about what is
true*. Measured consequences in one month: 624 failed company work sessions in 7 days against 266
"completed" of which only 24 proved anything; 59%+ of owner sessions containing a tool failure; every
rolling-window figure in the estate one day too long; and four separate copies of the agent's own
persona, three of them on one machine. **The evolution this round is not more systems. It is fewer
truths, each of them checkable.**

---

## 2. What is NEEDED — keep, and strengthen

| system | keep because | strengthen by |
|---|---|---|
| **The wake ledger** (`/root/work/work.db`, `/root/bin/work.py`) | it closes a **proven** item for **0.0900 USD**, enforces hard 150/day and 25 USD/day ceilings, and demonstrably stops at `daily_cap: 150/150, claimable_now: 0` | giving it the company's outcome classification, and making it the claim/close discipline for company work too (§5) |
| **The journal** | it is the only continuity mechanism, and it works: `status` is 97 ms, `check` is 0 errors on 263 warnings | §4.1 — one authoritative tree, host-banded ids, `idguard` on working trees |
| **The transcript archive** | hourly systemd timer, gap/silence distinguished, credentials refused by name, redaction verified on arrival | nothing. It is the best-built thing in the estate. Do not touch it |
| **The mesh + worktree fleet discipline** | 57 owner-sessions were read whole by 57 mesh children at once; the manager-integrates pattern holds | §4.4 — a brief must carry the node contract, and children must checkpoint |
| **The instruction surface's *safety* rules** | outbound-with-a-per-message-yes, never-destroy-data, no-hardcoded-model-ids, provenance — all irreversible-mistake rules | keep them; they are the cheap 1,500 bytes (§6) |
| **`preset-drift.py`, `journal-union.py`, `resolve-journal-merge.py`, `agent-fleet`, `sessions.mjs`** | each answers a question nothing else answers | **install them on every machine** — three of the four exist on one machine only (§4.3) |

---

## 3. What is NOT needed — retire, with the reason

| thing | evidence | action |
|---|---|---|
| **`fleet_location_poll`** | 414 consecutive failures, nothing since **2026-09-29** | RETIRE |
| **13 subsystems reporting `ok` with >= 500 consecutive empty ticks** (round 2 said five) | `consecutive_empty_ticks` increments on a *success* whose detail is blank, and its only reader is a cadence throttle — it cannot mark anything failing | RETIRE the ones whose output nothing reads; fix the counter for the rest |
| **`amazon_sync` / `ebay_sync`** | `rc=127`, `sh: 1: tsx: not found`; `tsx ^4.21.0` is declared in `package.json` and simply not installed | **REPAIR, not retire** — `npm install`. Calling this "dead" would be wrong |
| **The company's bespoke always-alive loop as *the* always-alive agent** | ~17.5 USD/day, 67.8 % of work sessions failing over 7 days, `tick_telemetry.total_cost` ~1.02 USD/week against ~123 actually spent | demote to a low-frequency heartbeat that **files ledger items**; keep `/opt/company` as the application (§5) |
| **`tick_telemetry` as a grade** | 192 `complete`/`productive` ticks against 8 `error`, while the work sessions under them fail two thirds | stop grading; keep the table as telemetry only |
| **`work_item` in `/root/authority.db`** | 0 rows, same name and shape as the live ledger's table, whose correct reading is `nothing-todo` | drop it, or rename it — a decoy store is worse than no store |
| **The persona's do-not-ask material** | `asked-unnecessarily` 2.7 % + `asked-badly` 2.6 % — the two LEAST frequent frictions in 961 classified sessions — while approval-shaped turns fell 25 % → 2.38 % | cut to one sentence (§6) |
| **The Copilot-era `_audit` tooling** | absent from the authority; the predecessor audit survives only at commit `51e2d32d` | keep the commit, stop pointing at the path |

---

## 4. What is MISSING — add, in this order

### 4.1 One authoritative journal, with host-banded ids
**Missing because:** 63 ids mean two different entries, all minted today; four trees hold 4051 / 4037 /
3907 / 3440 entries; a citation of `D3147` is ambiguous; and `journal-union.py` refuses to consolidate,
correctly.
**Add:** ids allocated from ONE authority or reserved in a **per-host band** so two hosts cannot collide
by construction; `idguard` pointed at WORKING TREES (it reports 0 collisions today because it reads refs);
then repair the 63 by reading both sides — **not** by a timestamp rule, because mtime is a rewrite time on
the authority and the body's first date is frequently a date the entry *mentions* (27 of 63 decisions flip
between the two rules and 13 tie). See `L3806`.

### 4.2 One authoritative instruction surface
**Missing because:** `scripts/preset-drift.py` exists on **no machine but ZABZ-YOGA**; three different
`zabz` personas exist on the authority alone; the machine designated primary runs the oldest text; and the
repo is internally DIVERGENT on two skills (`lpt-production-case-work` 10,545/11,282/11,878;
`parallel-agent-orchestration` 10,802/7,852/13,700), so the shared catalog cannot hold one copy.
**Add:** one reference lineage; a clean checkout on it per machine; `preset-drift.py` installed and run on
all of them; the 12 edits of `instruction-v2.md` §8 applied; and the drift detector wired into the
scheduled sync so a refusal reaches the journal instead of a log nobody reads.

### 4.3 A rule for where a *procedure* lives
**Missing because:** the same rule exists in three surfaces at three ages, and the measured shape of the
defect is always **a hostname or path correct in one surface and wrong in another** (`secratary` named as
the authority in the persona, the archive's own store path wrong in `AGENTS.md`, `secratary` a prefix of
`secratary-cloud` defeating a grep).
**Add:** when correcting a fact, grep every surface that states it and correct them together, or record in
the commit which ones were left and why. Put the rule where the work happens — a skill loaded with the
task beats a paragraph nobody opens.

### 4.4 A contract for a dispatched child
**Missing because:** 1,382 of 6,103 machine sessions (**22.6 %**) made **zero tool calls** and 1,342 of
those still paid a title-generation call; 165 of 690 mesh children produced `deliverables = 0`; and 816
real `edit`-family errors are children who never read the file they were editing.
**Add:** every brief carries the node contract (which node, and that it must work through ssh if it lands
elsewhere), an exact output path, the base revision, and a **checkpoint file** written after every step —
two children in this round were killed mid-run and lost everything they had learned.

### 4.5 The bridge: company work closes with a proof or a measurement
**Missing because:** 242 of 266 "completed" company sessions fired because the *task row was already
closed*, and `[ARTEFACT:]`/`[OUTBOUND:]` appear **0 times in 78,649 work sessions**.
**Add:** every company work session ends by recording `did` / `proof` / `result` / `left`, or closes
`blocked` with the measurement — the ledger's discipline, which already produces honest partials
(`STARTED, NOT FINISHED … no writes made`, `state_after=todo`).

### 4.6 A transport for silent failure
**Missing because:** `company-api` was `active` with `NRestarts=0` and answered **nothing for 50+
minutes** on 2026-10-14; the only reason it was found is that the API was needed for something else; and
`estate-monitor` computes `crit=5` every two minutes with `escalated=0`.
**Add:** one request **with a deadline against the service's own endpoint**, not a status line; every
condition the monitor already computes gets a severity that is *allowed* to escalate; the authority's
journald made persistent.

### 4.7 A time-window that is one window
**Missing because:** timestamps are stored ISO with a literal `T` (262,424 rows; **0** with a space),
`datetime('now','-N days')` returns a **space**-separated string, and `'T'` sorts after `' '` — so
`> datetime(...)` covers **N+1** days. Measured on one column in one minute: literal comparison 3,218
calls / 33.03 USD; `datetime()` comparison 5,023 / 45.45 USD.
**Add:** one shared helper (or `date()` grouping, which is immune); a test that inserts one row at a known
time and asserts the boundary. **This is reporting-only and carries no risk — do it first.**

---

## 5. The autonomy architecture, decided

**Decision (engineering, mine to make):** the ledger's claim → work → **close-with-proof** discipline
becomes the work-submission protocol for the always-alive agent. `/opt/company` remains the *application*
— it holds the business integrations nothing else has (Dialpad, Gmail, comms, 203 tables) — and its
bespoke loop is demoted to a heartbeat that **files ledger items** rather than launching its own
unprovable sessions.

**Staged deliberately, because a big-bang replacement of a live revenue-adjacent loop is the failure this
estate keeps recording:**
1. **Now — the gate.** `app/services/autonomy.py:376` returns L4 for anything unclassified, so
   `hire_department`, `fire_agent`, `delete_tool` and the whole `shop_*`/`website_*` family execute
   **with no human**. The built fix does not close it: 134 of its 150 rows say "autonomous" and every
   dispatcher name now has an explicit row, so the fail-closed branch is unreachable. Rebuild as a
   **considered** matrix — the owner wants *more* autonomy, not less: irreversible / money / outbound /
   people / production writes → L0-L1 explicitly; reversible investigation stays autonomous; **an
   unclassified name resolves to L1**; a test asserts `dispatcher_names ⊆ matrix_names` **and** that L4 is
   reachable only from a named allow-list.
2. **The bridge** (§4.5). This is what makes step 3 safe.
3. **Then** the heartbeat demotion, with the ledger owning claim/close.
4. **Abandon the direction if** a session closing with `did`/`proof`/`result` proves no more reliable than
   one closing on a marker, measured over at least 50 sessions.

**And stop the bleeding first:** the residual failure is now the **output-repetition guard**
(`autopilot.py` ~4997-5048), which closes the session where the rest of the loop redirects — 10 of 26
sessions, **38 %**, in the most recent window. Its log line claims "force-completing" while closing
unfinished, and its reported count is off by one.

---

## 6. The instruction surface, decided

**The measured allocation error:** `frustration` (6.58 % of the owner's turns), `correction` (5.74 %) and
`restart_agent` (2.05 %) appear **nowhere** in the persona or `AGENTS.md`; `tool-failure` (#2 friction) and
`env-hostile` (#4) have **no rule**; while the longest paragraphs serve "do not ask", a failure that fell
from 25 % to 2.38 %.

**Cut:** the do-not-ask material to one sentence. The five outbound hardenings stay (irreversible
mistakes); the journal mechanics move wholly to `journal/README.md`; the measurement recitals drop the
numbers and keep the rule; `AGENTS.md` §5's incident narrative moves to `docs/mesh/142`.

**Add — what is missing, each traceable to a measurement:**
1. **A rule for being corrected.** `correction` 5.74 % + `frustration` 6.58 % = 12.3 % of his turns.
   The rule: *when he corrects you, the correction is the requirement — restate it in one line, check
   whether the same error exists elsewhere, fix it there too, and continue. Do not defend, do not
   apologise twice, do not ask whether he is sure.*
2. **A tool-failure rule** (#2 friction, 4,204 web-family real errors): *read the exit code; quote the
   tool's own diagnostic; distinguish "the tool failed" from "the answer is empty"; a missing dependency
   (`rc=127`, `not found`, `not configured`) is not retryable — escalate with the exact stderr; retry once
   with a different tool or host before falling back.*
3. **An env-hostile rule** (#4): *detect the OS, the alias and the path before blaming the system; prefer
   an in-process or indexed route; never report a command's failure as a fact about the host.*
4. **A hang rule** (`restart_agent` 2.05 %, ~93 turns, and 10,916 job-poll calls in a month): *a hang is
   not a halt — if a step has not advanced, say so; write down what "done" looks like before polling for
   it, and prefer one blocking read over a poll loop.*
5. **The measurement rule, extended** — this round's four corrections (`L3796`, `L3801`, `L3803`, `L3806`)
   are all the same failure and none was a wrong opinion: **a query's predicate was never read, only its
   number.** The rule: print the raw value next to the predicate, and ask what writes that field.

---

## 7. What changes this week, in order

| # | change | verification |
|---|---|---|
| 1 | the timestamp-window helper + test | a test that inserts one row at a known time and asserts the boundary |
| 2 | the gate matrix, rebuilt as considered, with the invariant test | `dispatcher_names ⊆ matrix_names`; an unclassified name resolves L1; the dangerous families resolve L0/L1 |
| 3 | the repetition guard redirects instead of ending | a session that repeats then acts survives; one that repeats 4+ still closes, with the true count |
| 4 | `preset-drift.py` on every machine; the 12 edits applied; the reference lineage named | `preset-drift.py` exits 0 on all four machines |
| 5 | journal host-banded ids + `idguard` on working trees | `journal-union.py` runs without refusing |
| 6 | the bridge: company sessions close with proof or measurement | share of work sessions with a non-empty `proof`; `[ARTEFACT:]`/`[OUTBOUND:]` stop being 0 of 78,649 |
| 7 | retire `fleet_location_poll`; `npm install` for `tsx`; fix `consecutive_empty_ticks` | the subsystem register shows it stopped retrying; amazon/ebay leave `rc=127` |
| 8 | a deadline-checked endpoint probe for `company-api`, escalating | kill -STOP the process and watch the alert arrive |

**The measurement is the deliverable.** A change that does not move a row in §7 or in
`55-company-design.md` §R5 is not a fix, and the row it was supposed to move is named before it is built.
