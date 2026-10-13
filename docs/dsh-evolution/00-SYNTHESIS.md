# 00 — Synthesis

**2026-10-13.** The successor to `personal-secretary-mvp/docs/secretary-replacement-audit/`
(2026-09-11), built the same way and by the same rule: **no claim without provenance, no trend without
freshness.** That audit judged a workflow from 1,642 Copilot sessions. This one judges the harness
that replaced it, from **6,927 DSH sessions and 4,372 of the owner's own turns in one month.**

Everything below traces to a document in this directory, a journal id, or a script that reproduces it.

---

## 1. The four numbers that decide everything

| | Copilot (14 months) | DSH (1 month) | |
|---|---:|---:|---|
| **approval-shaped turns** — a bare yes / a / 1 | 25% | **2.4%** | **the migration worked** |
| **tool calls per owner turn** | 22.0 | **38.18** | the machine does 74% more per thing he says |
| **median turn length** | 62 chars | **114** | he stopped typing single letters |
| failure-signal tool results | — | **17.09% of all calls** | and `pwsh` alone is 40.65% of calls |

**The questionnaire is over.** Nine months of "keep going" and "one at a time" produced a harness that
no longer makes him the router. That is real and it should be said plainly.

**What replaced it is wrongness.** Measured across 935 of his sessions: the most common failure is
**`wrong-data` — acting on or reporting something untrue — at 11.2% of sessions**, followed by
`tool-failure` 9.9% and `repeated-work` 9.3%. `stopped-early` is sixth at 4.7%, and
`asked-unnecessarily` / `asked-badly` together are last at 3.3%.

**And the prompt is aimed at the wrong two.** Roughly a third of the always-on instruction budget goes
on asking less; the first-ranked failure has no rule in it at all. That is now fixed (§4).

---

## 2. What the corpus actually is — and it is not what we thought

**Only 15.3% of the archived sessions are his.** 1,059 of 6,927. The rest: 4,570 headless mesh/cron/
probe sessions, and **1,298 dispatches that were launched with his own interactive `zabz` profile**
(98.69% of them). The archive kept "forever for training data" is 85% machine output, and any
measurement of him taken before separating the three is wrong — including the first version of this
one. The definition is frozen in `_evolve/finalize_corpus.py` with its evidence.

**What he does with the agent, over 935 sessions:** investigating 33%, fixing 23%, building 18%,
verifying 10%. **Investigation plus repair is 56%** — this is a comprehension-and-repair harness.
Shop work is the largest single domain at 22%; the technical estate (build + harness + infra) is
38.5%; and **his own life, at 12%, is a bigger category than comms and finance combined.** 79% of
sessions complete. 17.6% carry a correcting or frustrated tone.

---

## 3. What is broken, and it is three things more than anyone knew

**a. The transcript archive has been dead since the cutover.** Last ingest **2026-10-11T20:23Z**; the
store lives on the box that was frozen at 05:43Z that morning; the authority has no archive at all;
**this laptop's sessions have been unarchived since 09-Oct.** The owner's own standing rule — *"a copy
always needs to exist"* — is false right now, and the only thing that would have reported it is the
check, which runs on the box that stopped. `P3162`. Repair dispatched.

**b. The authority is one hourly job from a full disk.** 6.1 GB free, an hourly archive temporary of
~6.27 GB, swap at 93.5%, 11 OOM kills in 24 h — and `estate-monitor` computes `CRITICAL crit=4` every
two minutes with its escalation list hard-coded to a single condition, so `escalated=0`. **The estate
has a detector and no transport.** `P3161`.

**c. The mesh broker — the only dispatch control plane — runs on the frozen box.** When it blinked, a
fan-out hard-failed. `a813fab2` claims a dead control plane no longer stops a dispatch; measured
today, it does. An unmerged fix (`89ffd242`) already exists. `P3160`.

**And one that is not new but is now measured: there is no one journal.** ~120 divergent git refs;
open pain reads **162 / 366 / 373 / 393** depending on the machine; **121 base-id collisions**; and
`check` calls all of it healthy. The predecessor audit this persona was written from **exists on no
trunk** — only in git history.

---

## 4. What has been changed

**In the instruction and identity surface, applied and verified:**

- **Added the rule for the #1 failure** — a new section, *"The one you must not get wrong"*: every
  claim carries the command and its output line; a reading is not evidence until you know its source
  and age; an empty result is a refusal, not health; never complete what you have not run. Plus
  *"look before you redo"* for the third-ranked failure.
- **Killed the `{cwd}` templating bug** that was in every prompt of every step.
- **Corrected three statements that named the frozen office box as the authority** — the exact alias
  confusion that caused the October incident.
- **Corrected the fleet list**, which called `zabz-tech-linux` "a macOS mini for his employee Yisroel".
- **Fixed `AGENTS.md` §1** — the archive table, its host and its scheduler, with a dated warning.
- **Cut the always-on persona from 28,697 to about 23,000 bytes** with no rule lost: the journal
  mechanics now point at `journal/README.md`, the orchestration mechanics point at the skill, and the
  measurement recitals are gone. The target is ~22 KB and the remaining moves are named.

**Recorded rather than left in a session:** `P3160`, `P3161`, `P3162`, the program decision `D3127`,
and three handoffs. Committed as `75ffbeef` on `main` and pushed to the branch
`evolution/dsh-audit-20261013` — the push to `main` was rejected non-fast-forward and **was not
forced**.

---

## 5. What it means, in one paragraph

The migration did the thing it was built to do and nobody has looked since. The harness no longer
wastes the owner's attention on questions, and it now spends the saved attention on a machine that
does 74% more actions per instruction, fails to tell the truth about its own work 11% of the time, and
redoes work it has already done 9% of the time — while the archive that is supposed to preserve all of
it stopped six hours after the server migration and nothing noticed for two days. **The next evolution
is not more autonomy. It is truthfulness, evidence and memory** — the three things that make autonomy
worth having. That is what §4 starts.

---

## 6. The documents

| | |
|---|---|
| `01-corpus.md` | the measured corpus, the three actors, the delta against Copilot |
| `05-instruction-redesign.md` | **the design** — two tiers, the rules to add, the identity, the test in 30 days |
| `07-pain-register.md` | the ranked friction from 935 sessions + 393 open pains clustered, side by side |
| `10-instruction-surface-audit.md` | what the prompt says, what it duplicates, what it is missing |
| `20-memory-continuity-audit.md` | whether the journal can be trusted — it cannot, yet |
| `30-systems-and-autonomy-audit.md` | what is running, what is silently dead, what fails to alert |
| `PROGRAM.md` | the program, its method, and the rules it holds itself to |
| `README-BRIEF.template.md` | the contract used for the 18 reading children |

**Reproduce any number:** `~/code/_evolve/{extract_corpus,extract_tools,finalize_corpus,aggregate_readers}.py`
on the authority; artifacts in `secratary-cloud:/home/zabz/evolution-corpus/`. Rerunnable by a session
with no memory of this one, which is the point.

---

## 7. The one thing that is his

**#475 — the 2025 tax return extension expires 15 October, two days.** Behind it: Q3 estimated tax 28
days past, NJ-927/WR-30 payroll 75 days past, his NJ employer number not entered into Gusto 59 days
past, and ST-50 sales tax 85 days past with the next due in 7 days. **That is one question, asked
separately, with a recommendation.** Everything else in 162 pending rows — about 137 of them — is
engineering this seat is responsible for, and the triage says so row by row.
