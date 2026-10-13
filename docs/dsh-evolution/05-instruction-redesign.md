# 05 — The instruction and identity redesign

**Prepared:** 2026-10-13 · **Inputs:** `01-corpus.md` (what he actually does, measured over 4,372 of
his own turns), `10-instruction-surface-audit.md` (what the surface says and costs),
`20-memory-continuity-audit.md`, `30-systems-and-autonomy-audit.md`, and the open-work triage.

**This document is the design. §7 is what has already been changed and verified.**

---

## 0. What the redesign is for

The owner's words: *"the instructions and identities changed to better match what we really need"*
and *"optimize your system as to what we actually do and really need and fix all my pain points."*

Three measurements decide what "really need" means, and they are not the three the current persona
was written from.

**1. The questionnaire is over; the wrongness is not.** Approval-shaped turns fell from 25% to
**2.4%**. The persona's first and longest rule — *do not stop to ask permission you already have* —
has done its job, and `stop_reporting` is now 0.16%. But `frustration` (6.52%) plus `correction`
(5.81%) is **12.3% of his turns**, and `keep_going` is still 7.34% (321 turns). The failure moved
from *"it stopped"* to *"it did the wrong thing confidently"*.

**2. The churn went the wrong way.** **38.18 tool calls per owner turn against 22.0 on Copilot.** He
says less per thing and the machine does almost twice as much per thing. `pwsh` alone is **40.65%
of all calls**, and the agent polls its own job machinery **10,916 times** in a month.

**3. He now asks whether the machine is alive.** `i think you froze` ×5, `did you freeze` ×4 —
9 turns in a month asking whether the agent is still running. The Copilot era had no such signal.
The harness can hang, and nothing in the persona treats a hang as distinct from a halt.

**So the redesign's priority is not "ask less" — that is done. It is: do the right thing, prove it,
do not flail, and be visibly alive.**

---

## 1. The structural change: two tiers, and a hard byte budget

The measured problem is not that any rule is wrong. It is that **45,474 bytes are re-sent every
step**, of which **~40% restates a rule that already lives in a skill or a doc**, and the cost rule
on this estate is `steps × mean context` (the three most expensive sessions were 52.5% of a day's
$54.92).

**The rule for the new surface, in one sentence:**

> **The always-on persona carries only what must be true before the agent has read anything. Every
> rule that has a *procedure* lives in the skill that owns the procedure, and the persona keeps one
> sentence and a pointer.**

Applied concretely:

| move | bytes saved from the always-on budget | where it goes |
|---|---:|---|
| journal mechanics (persona lines 120-139) | 4,682 | `journal/README.md` — already written there |
| fast-search + governor + in-process measurements (lines 67-71) | 3,588 | the `fast-search` skill and a shell-policy doc |
| outbound hard-stop detail (lines 96-102) | 1,568 | `docs/outbound-comms-hard-stop.md` — already a doc |
| `AGENTS.md` §5 incident narrative | ~3,500 | `docs/mesh/142-ANCHOR-WRITE-NOTICE.md` — already written there |
| mesh mechanics (line 40) | 1,311 | the `parallel-agent-orchestration` skill |
| fleet + systems list (lines 106-118) | ~1,111 | `settings/machines/host-posture.tsv` + the systems register |
| the duplicate paragraph (line 165) | 215 | — |
| the broken `{cwd}` line (line 24) | 38 | — |
| **total** | **~16,000** | |

**Target: always-on instruction from ~45.5 KB to ~20 KB, with no rule lost.** At 900 steps that is
about 18 MB of re-billing saved per long session.

**Tier 2 — a new required file: `state/now-next.md`, 2 KB, hard cap, rewritten every session.**
The audit's gap (d) — "exact state of play in one read" — does not exist today: `status` prints
4,957 B but cuts `state/in-flight.md` from 24,416 B to a few hundred, and `NOW.md` was 28 days
stale. Two kilobytes that are *always current* beat twenty-four kilobytes that are not.

---

## 2. The rules to add — each proven by the journal, none currently in the surface

These are the nine the instruction audit found missing. They go into skills, not the persona.

| # | rule | evidence | where it belongs |
|---|---|---|---|
| A1 | **Never `git add -A` in a shared working tree — stage explicit paths.** | `L33`, pain `P13`: eight concurrent sessions committed each other's files | `parallel-agent-orchestration` |
| A2 | **A `git worktree` is not a copy** — untracked files stay behind, so it is the wrong control for environment-sensitive behaviour | `L217` | `parallel-agent-orchestration` |
| A3 | **`origin` here is a diverged two-URL remote** — fetch from the frozen box, push to two places; push your own commit from a detached worktree, never by pulling | `L1462`, `P3135` "every push half-fails" | `harness-config/AGENTS.md` |
| A4 | **Never print a credential value** — exact-key allow-list plus a shape assert; a name-pattern mask has already leaked a live key and a password-bearing DSN into the permanent transcript | `P2938`, `L44`, `P13b` | a `secrets` skill |
| A5 | **Check where a mesh child will land before delegating build work** — a child on a node without the repository can research but cannot build | `P3141`, `P3139`: three of four children landed on such machines | `parallel-agent-orchestration` |
| A6 | **No heavy work on the authority** — 15.6 GB box, ~7.4 GB peak, 11 OOM kills in 24 h | `P3136`, `P3140`, `P2947` | `estate-systems` |
| A7 | **The owner channel can be gated** — "read the queue" is not "he will see it"; 160 pending questions and 78 unanswered texts | `P2942` | `secretary-wake` |
| A8 | **A rule in one surface is not a rule** — check the surface the caller actually reads | `L1490` | `harness-config/AGENTS.md` |
| A9 | **The generator hazard** currently lives only in YAML comments (`agent.cordis.yml` 461-468) and is never injected | audit §4.9 | `editing-cordis-compositions` |

**And two rules the measurement itself demands, which no audit file contains yet:**

| # | rule | evidence |
|---|---|---|
| A10 | **A hang is not a halt.** If a step has not advanced, say so and surface it — do not sit silent. When you start a background job, write down what "done" looks like *before* you start polling it, and prefer one blocking read over a poll loop. | 9 owner turns asking "did you freeze"; **10,916 `job_output`/`job_list`/`job_kill`/`list_agents` calls in one month** — the Copilot `sleep` anti-pattern re-implemented |
| A11 | **Do the cheap tool call last, not first.** `pwsh` costs ~700 ms of process start-up and is **40.65% of all tool calls**: read, grep and edit in-process; batch shell work into fewer calls; background anything over a minute. | `01-corpus.md` §4 — ≈13 hours of pure shell start-up in a month |

---

## 3. The rules to cut or merge

Not because they are wrong, but because they are paid for on every step and needed on almost none:

- **The journal mechanics block** → `journal/README.md` says it better and at length.
- **The measurement recitals** (search timings, `pwsh` latency, governor budget) → keep the *rule*,
  drop the *numbers*; the numbers are in the skills that act on them.
- **The outbound hard-stop detail** → keep "show the body, wait for the yes" in the persona (it is a
  safety rule and belongs before anything is read); move the five hardenings and the incident to the
  doc that already exists.
- **The duplicate paragraph at line 165** → delete.
- **`{cwd}` at line 24** → delete; the composition's own `suffix` already emits it correctly with
  `{{cwd}}`.
- **The `AGENTS.md` §5 narrative** → the rule is two sentences; the incident is 4,357 bytes in
  `docs/mesh/142`.

**Keep and strengthen** — these are load-bearing *and* cheap:
`Never destroy data` · `Never send outbound without a per-message yes` · `Never hardcode a model id` ·
`Provenance` · `Verify, do not assume` · `One source of truth per thing` · the four reasons a turn may
end.

---

## 4. Identity: what "Zabz" should say it is

The current opening is *"You are not an assistant he consults; you are the one who runs the systems
and does the work."* Measured, that is right and it is being met — the approval loop is gone. What it
does not say, and the corpus shows is the actual failure, is **what to do when the work goes wrong**.

**Proposed additions to the identity block (short, and each traceable):**

> **You are measured.** Every claim you make about what you did is checkable, and someone will check
> it. Prefer the command and its output line over the adjective. When you are wrong, say so before
> you are caught — the record of having been wrong is worth more here than the appearance of being
> right.
>
> **You are the only one watching the machine.** Nobody is looking over your shoulder between turns.
> A hang, a silent cron, a job that never ran and a job that ran correctly print the same thing:
> nothing. So when a thing is supposed to be running, **go and read that it ran** — the exit code in
> the ledger, the file's mtime, the row's timestamp — and say what you read.
>
> **Do not make him the router, and do not make him the debugger.** He answers questions that are
> his; he does not hold your plan, and he does not chase your failures. If you are about to write a
> sentence that ends in a question mark, first ask whether the answer is already in the record, in a
> log, or in a file — and if it is, go and read it instead.

---

## 5. What the identity should stop claiming

- **"~300 ticks/day."** Measured: **134 ticks in 24 h**. The persona overstates the company's
  activity by 2.2×.
- **"618 routes, 199 services."** A count with no date attached, on a system whose own headers say
  203 tables.
- **"55 improvements piled up unapplied"** — undated, from a September session, and stale.
- **The authority host**, fixed in §7.
- **A machine's role**, fixed in §7.

**Rule for numbers in the persona: a number that is not re-measured each time it is written is a
claim that will be false within a month. State the number with its date, or state the shape and not
the number.**

---

## 6. The memory half — what must be true for any of this to hold

The instruction surface cannot fix continuity; the journal must. The four gaps in
`20-memory-continuity-audit.md` §5, with the smallest fix for each:

| gap | smallest fix |
|---|---|
| **a.** a decision can be lost when the agent forgets to write it | make `owner-queue.py answer` append the owner's words to `entries/decisions/` **at answer time**, not later |
| **b.** an answered question can be re-asked | a content-hash dedup key on `owner_decision_queue`, and freshness from the `generated` line, never mtime |
| **c.** an audit can be re-commissioned | a queryable audit registry — a `decisions`/`wins` index of covered areas, or one `docs/**/AUDITS.md` |
| **d.** no one-read state of play | the 2 KB `state/now-next.md` of §1 |

**And the one that matters most for the archive:** a rule that says "a copy must always exist off the
machine that wrote it" is currently false — the archive has not ingested since 2026-10-11T20:23Z and
this laptop's sessions have been unarchived since 09-Oct. Recorded as `P3162`, with a repair
workstream open.

---

## 7. What was changed and verified, 2026-10-13

**In `presets/zabz/agent.cordis.yml`:**

| # | change | verification |
|---|---|---|
| 1 | **Deleted the `{cwd}` line** (was line 24). The composition's `suffix` at line 20 already emits `Your working directory is {{cwd}}.` | the literal `{cwd}` no longer appears in the prefix; it was reproduced live in the running prompt before the fix |
| 2 | **Authority corrected to `secratary-cloud`** in the opening paragraph (was "a Linux server called `secratary`") | grep: `secratary-cloud` present, `runs on a Linux server called \`secratary\`` gone |
| 3 | **"One source of truth per thing" rewritten** — names `/root/authority.db` on `secratary-cloud`, states that `secratary` is the FROZEN rollback anchor, and points at `settings/machines/host-posture.tsv` as the thing that decides | the old sentence "remote on `secratary`" and "authoritative database is on `secratary`" are gone |
| 4 | **The fleet list rewritten** — `secratary-cloud` is THE AUTHORITY; `secratary` is frozen; `zabz-tech-linux` is the office Linux PC, not "a macOS mini for his employee Yisroel"; `lakewooechsmini` is Yisroel's mini; the posture file and the guard are named | grep: "macOS mini for his employee" gone; `lakewooechsmini` present |

**In `presets/zabz/skills/estate-systems/SKILL.md`:**
5. Line 39 said "`secratary-cloud` and `secratary` hold the authority". It now says only
   `secratary-cloud` does, names the office box as frozen, and points at `host-posture.tsv`.

**In `AGENTS.md` §1 (the standing archive rule):**
6. The archive table is corrected and carries a dated warning that it describes the *intended* state;
   the DSH row points at `/root/authority.db` on the authority; the Copilot row records that it is
   **25 days stale** (1,608 sessions / 4,373 messages, newest 2026-09-18); the scheduler is corrected
   from `cron` on `secratary` to `cron` on `secratary-cloud`; both `ssh secratary-ts` commands in
   "how to tell whether it is current" now target `secratary-cloud`.
7. **A correction of an audit's own error, recorded rather than propagated:** the audit reported that
   `scripts/push_vscode_chats.py` and `scripts/vscode_chat_extractor.py` "do not exist". They do —
   in `personal-secretary-mvp/scripts/`, 24,934 B and 35,494 B. The section's *host and path* claims
   were the wrong part. This is written into the file so the next reader does not repeat it.

**Not yet done, and named so it is not mistaken for done:**
the ~16 KB of movement into skills (§1), the new `state/now-next.md` (§1), the eleven added rules
(§2), the removals (§3), the identity additions (§4), the numeric corrections (§5), and the four
memory fixes (§6). Each is small; none is ambiguous; they are the next session's work.

---

## 8. How to know it worked

A redesign with no test is a wish. These are the measurements to re-run in 30 days, from the same
scripts:

| measure | today | target |
|---|---:|---|
| tool calls per owner turn | 38.18 | **< 25** |
| `pwsh` share of tool calls | 40.65% | **< 25%** |
| job-polling calls (`job_output`+`job_list`+`job_kill`+`list_agents`) | 10,916/month | **< 3,000** |
| `frustration` + `correction` share of owner turns | 12.33% | **< 6%** |
| `keep_going` share | 7.34% | **< 3%** |
| always-on instruction bytes for `zabz` | 45,474 | **< 22,000** |
| owner questions pending, of which mis-filed | 162 pending / ~137 not his | **< 20 pending, 0 mis-filed** |
| journal open pain | 393 (three trees: 162/366/393) | **one tree, one number** |
| failure-signal tool results | 17.09% of calls | reported per tool, with the top three fixed |

`~/code/_evolve/finalize_corpus.py` reproduces every corpus figure; `journal.py status` reproduces
the journal ones. Both are rerunnable by a future session with no memory of this one — which is the
point.
