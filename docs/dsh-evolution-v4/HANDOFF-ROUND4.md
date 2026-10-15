# ROUND 4 HANDOFF — start here

**Written 2026-10-14 23:2xZ by the retiring round-4 agent (session on ZABZ-YOGA).**
**For whoever takes over. Read this whole file first, then open only what it points you at.**

The owner's instruction for this round, and it is the same command three rounds have now received
verbatim: *"go through every single dsh session… categorize all my conversations, find all the pain
points, find what I want. I want the systems evolved and fixed. I want the instructions and
identities changed to better match what we really need… audit and evolve the AI company that lives
on the Secretary Cloud server tremendously… it needs to be an order of magnitude better, faster and
most importantly more capable and autonomous and smart."*

**Everything below marked ✅ was performed and verified with a command this round. Everything marked
⬜ is open. Do not re-do the ✅ items — three rounds were spent re-deriving things that already
existed, and the single most expensive habit in this estate's history.**

---

## 1. THE ONE THING TO KNOW BEFORE YOU TOUCH ANYTHING

**`/opt/company` on `secratary-cloud` is the running company, and until this round its code existed
in no commit.** 25 modified `app/` files, ~4,100 inserted lines — the live work loop, the autonomy
gate, the completion markers. A single `git checkout -- app/` would have erased months of work.

That tree is now preserved as **commit `14ebb2322`**, branch `preserve/live-tree-20261014`, verified
byte-identical to live with `cmp`. **If you change nothing else, never delete that branch.**

---

## 2. THE FIVE THINGS THAT ARE DONE, AND HOW THEY WERE VERIFIED

| # | what | evidence (run it yourself) |
|---|---|---|
| ✅ 1 | **The live company tree is preserved in git.** | `ssh secratary-cloud 'git -C /root/work/r4-preserve log --oneline -1'` → `14ebb2322`; `cmp /root/work/r4-preserve/app/autopilot.py /opt/company/app/autopilot.py` → identical |
| ✅ 2 | **The fail-closed autonomy gate is live and genuinely closed** — every round-1/2/3 document says it is open. It is not. | `ssh secratary-cloud` then import the live module: `UNCLASSIFIED_ACTION_LEVEL = L1_SUGGEST`; `should_execute("fire_agent")` → `execute=False`; `delete_tool` → L0. **Do NOT rebuild it.** |
| ✅ 3 | **Four workstreams built, tested, merged and DEPLOYED** to `/opt/company` at 20:16:07Z | §3 below; `ExecMainStartTimestamp` = `2026-10-14 20:16:07 UTC` |
| ✅ 4 | **Corpus v4 + the reader fleet + the census** — 7,755 sessions, 1,149 owner sessions, 19 shards, **1,008 sessions read, 0 parse problems, 0 duplicate ids** | `ssh secratary-cloud 'ls /home/zabz/evolution-corpus-v4/readers/*.md \| wc -l'` → 19; `head -40 /home/zabz/evolution-corpus-v4/CENSUS-v4.md` |
| ✅ 5 | **The journal id allocator no longer mints duplicates** — it answered P3212, a number another machine already held. | `ssh secratary-cloud 'cd /root/code/harness-config && python3 journal/tools/journal.py next-id pain'` → **P3865** (was P3212). Cron installed and probed rc=0. |

---

## 3. WHAT IS DEPLOYED AND RUNNING RIGHT NOW

Deployed by `scripts/evolution/deploy-round4.sh` (10 files, backup
`/var/lib/authority-snapshots/r4-deploy-20261014T201607Z`). Verified at five points: md5 of every
file against the integration tree (**0 mismatches**), `ExecMainStartTimestamp` moved
(17:10:50 → **20:16:07** — an mtime is not a deployment), `/health` ok, the new symbols importable
**in the running interpreter**, and a new work session created 25 s later.

| workstream | what it does | tests |
|---|---|---|
| **WS-LOOP** | A reconnaissance budget: at **6** consecutive read-only steps inject `[RECON-DIRECTIVE:]` demanding one of three concrete actions; at **10**, refuse to extend and close **BLOCKED** (`[RECON_BUDGET_EXHAUSTED:]`). Plus `[HANDOFF: did=… \| proof=… \| result=… \| left=…]` on **every** terminal path, including one that previously recorded nothing. Env-tunable: `ZABZ_RECON_SOFT_LIMIT`, `ZABZ_RECON_HARD_LIMIT`. | 30 passed; **29 of 30 fail on base** |
| **WS-TRANSPORT** | `liveness_probe.py`: `/health` under a hard deadline, the verdict taken from the **JSON body not the HTTP status**, plus an independent read-only `SELECT 1`, because a wedged API answers 200 from a cached object. And the **task ceiling fixed**: it counted `blocked` as consuming, so it sat at 308 against a limit of 300 and **`create_task` was refusing to create work**. | 10 passed; ceiling re-measured myself: **308 → 60** |
| **WS-MODEL** | `model_resolution.py`: operator env chain → gateway-catalogue-validated → route alias, fail-soft, publishes which model served. A guard with an explicit allow-list of 629 permitted literal lines. | 11 passed; guard fails on base with the offender list |
| **WS-MEMORY** | `attempt_context.py`: a bounded (1500-char) attempt context with an explicit "no prior attempt" marker, and the repair of `app/agent_bus.py`'s import of a function that **does not exist** (`run_consolidation`) — so the 03:00 consolidation job was a silent no-op. | 12 passed |

**Regression gate (the number that matters): the whole test tree, base `14ebb2322` vs the integrated
tree — 51 failing node ids on each side, 0 new.** Plus **63 tests** across the four new suites.

**Also live: the liveness probe.** `r4-liveness-probe.timer` enabled, 2-minute cadence, ran on its
own, `systemctl --failed` empty. Escalation goes through the estate's **existing** owner-notification
path, after 2 consecutive failures. **The owner chose `R4_LIVENESS_FAIL_ON_FINANCE=0`** — alert on a
dead service, not on a quiet bank feed.

---

## 4. THE STATE OF THE THING WE ARE ACTUALLY TRYING TO FIX

**Pre-deploy, 24 h:** `STEP_BUDGET_EXHAUSTED 49 · TOOL_LOOP_DEADLOCK 38 · STALLED_REPEATING_OUTPUT 15 ·
stalled_no_tool_call 6 · HANDOFF 1 · TASK-CLOSED-BY-SESSION 46`. 7 days: **578 failed / 259 completed**.

**Post-deploy, 16 sessions, read this honestly — the sample is tiny:**

| outcome | count | why |
|---|---|---|
| `paused` | **10** | `[BUDGET-PAUSED: agent_soft_cap …]` — **not a loop failure** |
| `completed` | **6** | closed with `TASK-CLOSED-BY-SESSION` proof |
| `failed` | **0** | — |

Markers since the deploy: **`HANDOFF` 16 of 16**, `TASK-CLOSED-BY-SESSION` 6,
`RECON-DIRECTIVE` **1**, `RECON_BUDGET_EXHAUSTED` **0**, `STEP_BUDGET_EXHAUSTED` **0**.

**What that does and does not mean.**
* It does **not** prove the failure rate moved. n=16, and ten of the sixteen were stopped by budget.
* It **does** prove: every session now leaves a handoff (was 1 in 24 h), and **not one of sixteen
  died at the step budget** (was 49 in 24 h).
* The new forcing function fired **once**. Sessions are converging before it — session `78761` said,
  in its own words: *"Six steps have cycled on the same read-only evidence; the honest resolution is
  to document the verified state and close."* **That is the desired behaviour, and it means the
  directive's own mechanism is UNPROVEN in the field. Do not claim it works.**

**A cleaner comparison than the 24 h window, because both hours are 8 sessions each:**

| hour 2026-10-14 | sessions | completed | failed | `STEP_BUDGET_EXHAUSTED` | `RECON-DIRECTIVE` | `HANDOFF` |
|---|---:|---:|---:|---:|---:|---:|
| **20:00** (8 min pre-deploy) | 8 | 2 | 0 | **0** | 0 | 8 |
| **22:00** (post-deploy) | 8 | 4 | 0 | **0** | **1** | 8 |

The 20:00 hour already had **zero** step-budget failures — so the deploy-day collapse from 49 was
**already under way before this deploy**, and attributing it to the loop change is **not supported**.
What the 22:00 hour adds is the `RECON-DIRECTIVE` firing once and 4 completions against 2. **n=8; this
is a direction of travel, not a result.** The honest summary is: the mechanism is live and firing, the
15-month step-budget failure class is not appearing in the post-deploy hours, and the attribution is
still open.

**By 2026-10-14 23:2xZ the owner had made his budget decision: the daily cap STAYS at 37.50**
(journal `D3402`). October to date 228.15 of a 750 monthly cap; the company spent **33.91 today**.
So the lever from here is **efficiency, not spend** — and the cheapest efficiency available is
**failed work that still gets paid for**.

---

## 5. THE BIGGEST OPEN ITEM: THE INSTRUCTION SURFACE (the owner's explicit first ask)

**Not started.** And the census now supplies the evidence that decides what it should say. Frictions
by number of the 1,008 owner sessions read:

```
tool-failure 302 · correction 132 · wrong-data 116 · repeated-work 102 · frustration 96
no-verification 76 · env-hostile 74 · restart-agent 73 · context-loss 56 · ignored-instruction 53
format-unreadable 40 · stopped-early 37 · safety 32 · non-answer 26 · overcomplicated 25
asked-badly 22 · asked-unnecessarily 20 · invented-detail 19 · bad-prioritisation 9
```

**Read the last three lines against the current persona.** The two frictions it spends its longest
paragraphs on — *do not ask*, *ask one question* — are the **two rarest of twenty** (20 and 22).
Meanwhile `wrong-data` (116), `correction` (132), `repeated-work` (102) and `restart-agent` (73) have
**no rule in the surface at all**. Severity: 78 sessions at 4, 44 at **5**.

**And the convergence trap is real and unsolved:** `autosync.ps1` ships `git archive HEAD`, so a
correction that is not *committed* comes back on the next pass. Pain #3 in
`docs/dsh-evolution-v2/07-pain-register-v2.md`. **Rewrite the persona and commit it on every
machine's sync lineage, then verify the INSTALLED file, not the checkout.**

* Where the persona lives: `presets/zabz/agent.cordis.yml` (54,551 B) is **generated** by
  `scripts/make_zabz_preset.py` — edit the generator, regenerate, never hand-edit the output.
* The instrument to prove convergence: `scripts/preset-drift.py --json`. On ZABZ-YOGA it reports
  15/15 MATCH today.
* Owner decision already recorded and still binding: **a rule in one surface is not a rule**
  (`AGENTS.md` §6.3). Put rules where the work happens.

---

## 6. OPEN ITEMS, EACH WITH ITS FIRST COMMAND

1. **Measure the loop properly** (the thing §4 cannot yet answer):
   `ssh secratary-cloud 'bash /root/work/round4-loop-baseline.sh after'` — already installed and
   verified to run at `/root/work/round4-loop-baseline.sh`, and in this repo at
   `scripts/evolution/round4-loop-baseline.sh`. Compare against the pre-deploy row in §4 at +24 h and
   +7 days. **If `STEP_BUDGET_EXHAUSTED` does not fall, apply `docs/dsh-evolution-v4/PROGRAM.md` §8
   and stop building — measure instead.**
2. **Build `07-pain-register-v4.md`** from `docs/dsh-evolution-v4/CENSUS-v4.md` +
   `/home/zabz/evolution-corpus-v4/CENSUS-v4.json` (which also holds 212 "wanted but never built"
   lines and the 122 severity-4/5 records with the owner's own words). One owner and one verification
   command per row, ranked by *blocks work → recurs → owner-visible*.
3. **Two live correctness jobs the builders surfaced and nobody did:**
   * `app/autopilot.py:3768` — `_prior_attempt_context` is now **dead code** (WS-MEMORY replaced it at
     the same injection point). Either delete it or wire it; leaving it is a trap for the next reader.
   * `app/agent_worker.py:3054` — a literal `"secretary-fast"` should be
     `resolve_model("fast")` now that the resolver exists.
4. **The company is the headline and it is only partly evolved.** `docs/dsh-evolution-v4/PROGRAM.md`
   §7 has the order. The two biggest remaining: **a retry must inherit the previous attempt**
   (measured: 238 tasks retried, 78 ever completed — every retry re-pays for the same
   reconnaissance), and **cost per proven outcome published weekly** (the cron wake loop achieves
   0.0900 USD per closed-with-proof item against the company's ~0.53 USD per "completed" session).
5. **`WRONG`/stale claims still in round-3 documents.** `55-company-design.md` §R4 recommends building
   the gate (it is built) and `07-pain-register-v2.md` ranks it #2 (it is closed). Add correcting
   notes rather than rewriting history — the journal is append-only and so is trust.

---

## 7. THE TRAPS THAT COST THIS ROUND REAL TIME — do not re-learn them

* **`secratary` (office box) is FROZEN.** `settings/machines/host-posture.tsv` decides, never memory.
  **`secratary-cloud` is the authority** and is a 15 GB box — read-only for analysis, writable only
  for a backed-up, verified deploy. No builds, no test suites, no corpus scans there.
* **The authority's disk is a live hazard.** Measured **88 % used / 18 GB free** at handover, and it
  moves. On 2026-10-13 a full disk caused a **4 h 33 min** company outage. **Check `df -h /` before
  anything that writes.** `estate-monitor.service` failed with `ENOSPC` during this round for exactly
  this reason.
* **`/root/work/venv-pytest` is a symlink farm to `/usr/bin/python3`** with pytest only. It lacks
  `pydantic_settings` and `twilio`. **Run company tests with `/opt/company/.venv/bin/python3`**, and
  compare a suite's verdict against the base tree rather than trusting any pass count.
* **A `git` ref is not the newest state of anything.** `bands.tsv` was reserved at allocation time and
  committed hours later; the working trees were up to 8 hours ahead of every ref. Ask where a thing is
  *written*, not where it is *archived* (`L4066`).
* **Never `git add -A`** — other sessions commit to these repos concurrently. Explicit paths only.
  Never push. Never `reset --hard`, `clean`, or force.
* **A PowerShell here-string wraps a long base64 token**, and the wrapped token arrives as a different
  payload — three cron installs failed with "command too long" for this (`L4065`).
* **A systemd `Environment=` line beats `EnvironmentFile=`**, so a unit can be pointed at the wrong
  endpoint by a file it does not control. The liveness probe was calling the **public** URL and
  getting **403** until this was pinned to loopback.
* **`Type=oneshot` + `return 0 if ok else 1` turns a detection into an infrastructure failure** — a
  real outage would have marked the probe's own unit failed and masked a probe crash.
* **The background job limit is 10 per owner.** A 19-reader fleet exceeds it; rotate.
* **The pytest venv cannot even collect `tests/test_r4_loop_convergence.py`** — it has no
  `pydantic_settings`.

---

## 8. WHERE EVERYTHING LIVES

**This repo (`harness-config`, branch `feat/card-due-watch-20261014`)** — my commits are
`8c9c4d41`, `b83b1f7c`, `70c82413`, `638de097`, `edf7299b`:

| path | what |
|---|---|
| `docs/dsh-evolution-v4/HANDOFF-ROUND4.md` | **this file** |
| `docs/dsh-evolution-v4/PROGRAM.md` | the round-4 spine: what recon changed about the plan, the baseline, the workstreams, §8's abandon-condition |
| `docs/dsh-evolution-v4/CENSUS-v4.md` | the census: 1,008 sessions, frictions, outcomes, severity, 212 wants |
| `docs/dsh-evolution-v2/ROUND4-RECON.md` | what prior rounds landed vs claimed, worktree by worktree |
| `docs/dsh-evolution-v4/briefs/WS-*.md` | the four workstream briefs — reusable as contract templates |
| `docs/dsh-evolution-v4/READER-BRIEF.md` | the reader contract (closed friction vocabulary) |
| `scripts/evolution/` | `capture-company-baseline.py`, `deploy-round4.sh`, `round4-loop-baseline.sh`, `reader-census.py`, `preserve-live-tree.sh`, `cut-round4-worktrees.sh`, `install-ceiling-cron.py`, `check-autonomy-policy.py`, `fix-probe-exit-code.py` |
| `journal/tools/journal-ceiling-refresh.py` | the id-ceiling fix (deployed to the authority's cron) |
| journal `H3911` | the round-4 handoff entry, incl. the deployed state and traps |
| journal `L4065`, `L4066`, `L4068`, `D3402` | the four records I wrote: the payload-wrap defect; refs vs working trees; **a pain I filed about a defect I had not read the artefact for and then removed**; the budget decision |

**On the authority (`secratary-cloud`):**

| path | what |
|---|---|
| `/opt/company` | the live company (read-only unless deploying) |
| `/var/lib/authority-snapshots/r4-deploy-20261014T201607Z` | the pre-deploy backup; rollback is in `deploy-round4.sh`'s last line |
| `/root/work/r4-preserve` | branch `preserve/live-tree-20261014` (`14ebb2322`) — **the preserved live tree** |
| `/root/work/r4-integration` | branch `r4/integration` (`4b750e5aa`) — everything merged; contains `round4-reports/REPORT-WS-*.md`, each builder's own report |
| `/root/work/r4-{loop,transport,model,memory}` | the four workstream worktrees, each with its own `REPORT.md` and `CHECKPOINT.md` |
| `/root/work/HANDOFF-ROUND4.md` | a copy of this file, on the authority, so the machine that owns the work carries its own instructions |
| `/root/work/round4-loop-baseline.sh` | the measurement script, installed and verified to run |
| `/home/zabz/evolution-corpus-v4/` | 7,755 sessions, 19 shards, `readers/R01..R19.md`, `CENSUS-v4.{md,json}`, `baselines/` |

---

## 9. HOW TO WORK WITH THE OWNER (measured, not folklore)

* **One question, at a time, with a recommendation and the arithmetic shown.** He answered two of
  mine this round (the liveness alarm, the budget cap) in a single exchange each, both because the
  question arrived with one number and a reason.
* **He does not read documents.** A document is for the record. A decision becomes one plain-language
  question in the conversation.
* **Anything solvable without him is not his.** Rounds 1–3 pushed 595 things at him of which 383 were
  engineering faults. That is the failure mode to avoid, and it is why §6 has no questions for him
  in it.
* **Verify before claiming.** The single most common failure in this estate is acting on or reporting
  something that was not true (11.2 % of sessions), and the worst incident in its history was a
  crisis reported that did not exist because a stale copy was read and believed. **Every claim needs
  its command and its output line, or it does not leave your hands.**

## 10. WHAT I GOT WRONG THIS ROUND, so you can discount me correctly

1. I **filed a pain** (`P3866`) about a sweep re-creating rows without opening the artefact. The
   artefact stated its own date and the backlog was **shrinking 80 → 32**. I removed it (`L4068`).
2. I **asserted a path did not exist** on the authority. It does.
3. I **called a regression that was not one** — four failures that were a missing `twilio` module and
   identical on base. The isolation run across base → transport → model → integration settled it.
4. My **first regression comparison was meaningless** — a `sed` stripped the node ids so every
   failure looked new. Redone: **51 = 51, 0 new**.
5. I **guessed a journal id** (`H3910`) instead of asking the allocator, and wrote a decision under a
   wrong id (`D3376`) whose heading I then failed to update. Both fixed; `journal.py check` is **0
   errors** at handover.
6. My **census cluster matching was substring-based**, so `find` matched `finding` and ties were won
   by iteration order. Fixed to whole-word; 296 of 1,008 now report honestly as `unclassified`.

**The through-line: every one of those was a confident number I had not checked, and each was caught
by running something rather than thinking harder. Do that.**
