# 07 — The pain register, ranked and evidenced

**Prepared:** 2026-10-13 · **Two independent measurements, deliberately kept separate:**

- **A. What the sessions show** — **945 of the owner's 1,059 sessions (89.2%)** classified by 18 mesh
  children reading shard digests. **All 18 shards landed; nothing missing, nothing suspiciously short.**
  Each child returned one record per session; the counts are folded by
  `~/code/_evolve/aggregate_readers.py` from what the children published to
  `secratary-cloud:/home/zabz/evolution-corpus/reports/`. Sources: `reader-aggregate.json`,
  `reader-findings.md`.
- **B. What the record already knew** — 393 open journal `pain` entries, clustered into 21 by the
  open-work triage. Source: the child's report, its ids quoted inline.

**They rank different things, and that is the finding.** A is *what went wrong in a session*; B is
*what has been written down as broken*. **The instruction surface is written for B's old list and the
agent is failing at A's new one.**

---

## 1. A — the session census

| domain | n | | intent | n | | outcome | n | | tone | n |
|---|---:|---|---|---:|---|---|---:|---|---|---:|
| **shop** | **208** | | **investigate** | **309** | | completed | 748 | | directing | 516 |
| build | 162 | | **fix** | **218** | | partial | 162 | | calm | 258 |
| harness | 122 | | build | 173 | | unknown | 28 | | **correcting** | **120** |
| personal | 112 | | verify | 99 | | failed | 7 | | **frustrated** | **49** |
| research | 103 | | document | 43 | | | | | approving | 2 |
| company | 86 | | communicate | 31 | | | | | | |
| infra | 81 | | decide | 18 | | | | | | |
| comms 29 · finance 26 · meta 11 · other 5 | | | plan 13 · nudge 2 · other 17 | | | | | | | |

**Reading.** Investigation and repair are **56% of his intent** (309 + 218) — building is 18%. That
confirms, harder than the Copilot audit did, that this is a comprehension-and-repair harness, not a
code generator. Shop work is the single largest domain (22%) but the technical estate as a whole
(build 162 + harness 122 + infra 81 = **365, 38.6%**) is larger than shop, and **his own life at 112
sessions (11.9%) is a bigger category than comms and finance combined**. 79% of sessions complete;
**17.9% carry a correcting or frustrated tone.**

**A correction to my own earlier read.** From the first 9 shards I reported `company` and `research`
at the top and shop at 69. The shards are ordered by day and the fleet ran in waves, so the early
sample was a biased slice. With all 18 in, `shop` is the largest domain. The child reports are the
evidence; the aggregate is recomputed from all of them, not from my memory of the first wave. The
lesson is journal `L3773`.

---

## 2. The ranked friction — `wrong-data` is first, and the instruction surface does not mention it

| # | friction | sessions | % of 945 |
|---:|---|---:|---:|
| 0 | *(none recorded)* | 424 | 44.9% |
| **1** | **`wrong-data`** — acted on, or reported, something that was not true | **108** | **11.4%** |
| **2** | **`tool-failure`** | **96** | **10.2%** |
| **3** | **`repeated-work`** — redid something already done | **89** | **9.4%** |
| 4 | `env-hostile` — broken path, failing shell, unreachable host | 68 | 7.2% |
| 5 | **`false-completion`** — claimed done, was not | **49** | 5.2% |
| 6 | `stopped-early` | 44 | 4.7% |
| 7 | `slow` | 44 | 4.7% |
| 8 | `ignored-instruction` | 41 | 4.3% |
| 9 | `context-loss` — forgot a decision, re-derived it | 32 | 3.4% |
| 10 | `asked-unnecessarily` | 17 | 1.8% |
| 11 | `asked-badly` | 14 | 1.5% |

**This is the single most actionable table in the audit.**

The current persona's first and longest rule is *do not stop to ask permission you already have*, and
its data are the Copilot-era 9.9% "keep going". Measured now: **`stopped-early` is #6 at 4.7%** and
**`asked-unnecessarily` + `asked-badly` together are #10-11 at 3.3%**. The two behaviours the
instruction surface is organised around are the two *least* frequent failures.

The behaviour it does not mention at all is **#1: `wrong-data`, 11.2%** — reporting or acting on
something untrue. It is corroborated from two other directions: the corpus's `correction` signal
(5.81% of his turns, "you missed", "that's not what", "you forgot") and the system's own history,
where the worst incident on record was *reporting a crisis that did not exist because a stale
database copy was read and believed*. **That failure is the through-line of this system and it is not
a rule in its prompt.**

**#2 `tool-failure` (9.9%) and #4 `env-hostile` (7.2%) = 160 sessions where the machinery, not the
judgement, was the problem.** This is the same shape the Copilot audit measured and attributed to a
broken `PATH`: 60% of that corpus's tool calls were terminal and file reads, and the loop was
*run → environment wrong → diagnose → retry*. Today `pwsh` is **40.65% of all calls** and 17.09% of
tool results come back as a failure signal. The environment fight survived the migration.

**#3 `repeated-work` (9.3%)** is the one the journal has been shouting about for a month: 66 both-live
near-identical lesson entries, 9 both-live near-duplicate pains, and an audit set that was
commissioned more than once because its findings lived in a session that died.

---

## 3. B — what the record already knew: 393 open pains, 21 clusters

From the triage. Ranked by the same principle — how many independent recordings.

| cluster | n | the problem | live? |
|---|---:|---|---|
| **K2** | 72 | journal and repo divergence; work that never lands | **live** — three lineages, `P3156` recurred |
| **K3** | 39 | lpt-hub / production reconciliation | partly fixed, new members live |
| **K7** | 35 | mesh dispatch and the subagent fleet | live — `P3160` filed today |
| **K8** | 34 | Dialpad/SMS store duplication (389 messages are really 16) | live, no landed guard |
| **K6** | 13 | money: card, webhook, unrecorded payments | `P2250` settled; four live |
| **K11** | 33 | owner channel, queue hygiene, alerting | live |
| **K9** | 23 | authority access, load, placement | four members refuted today, six live |
| **K12** | 18 | leaked credentials, rotation owed | **live** — five entries say a secret is in a transcript |
| **K13** | 18 | tests, lint, CI debt (ESLint cannot fail CI) | live |
| K10 | 14 | disk, backup, capacity | **live — `P3161`** |
| K18 | 25 | harness/desktop papercuts | live |
| **K1** | 12 | journal base-id collisions | symptom fixed once, **cause live** (`bands.tsv` double-grants a window) |
| K15 11 · K14 6 · K19 11 · K16 13 · K17 9 · K4 3 · K5 6 · K20 4 · K21 1 | | | |

**Fixed-but-still-open debris, proved by prose not by status:** `P2250` (257 rows settled, 27,384.00),
`P3003`/`P2944`/`P2946`/`P3005` (authority ssh works today), `P3015`/`P3010` (the guard reaches all
four machines), `P2867`/`P2878` (the 14 counter checks ran signed in on production), `P3131` and
`P3130`/`P2549`/`P2539`/`P334` (whose own body says FIXED 2026-10-09), and `P10` (retracted in place
on 2026-09-11 and still listed open). **Nothing in `state/status.tsv` marks any of them closed** — the
status store and the open list agree perfectly at zero discrepancies, which means the *record* is the
thing that is stale, not the index.

**Structural defect this exposes:** a pain can only be closed by `resolve`, and nobody resolves. So
the open list accretes and stops being readable, and the reader's own workaround (writing "FIXED" in
the body) is invisible to every tool. **`resolve` needs to be a habit, not an option.**

---

## 4. The two lists, side by side — where the instruction surface is aimed

| failure | sessions (A) | in the persona today? |
|---|---:|---|
| `wrong-data` | **105** | **no rule at all** — only the provenance rule's origin story |
| `tool-failure` | 93 | partially: "prefer in-process tools", "background-first shell" |
| `repeated-work` | 87 | **no rule** — the journal exists for this and nothing says "search it before redoing" |
| `env-hostile` | 67 | partially: the same two rules |
| `false-completion` | 48 | "verify, do not assume" — one sentence, no test |
| `stopped-early` | 44 | **rule 1, the longest block in the file** |
| `slow` | 43 | one line on background jobs |
| `ignored-instruction` | 40 | **no rule** |
| `context-loss` | 32 | the journal section |
| `asked-unnecessarily` / `asked-badly` | 31 | **rules 2, 2b, 2c, 3, 9 — about 3,000 bytes** |

**Conclusion, stated plainly: roughly a third of the always-on instruction budget is spent on the 10th
and 11th most common failure, and the most common one has no rule.** That is the redesign's whole
justification, and it is a measurement, not an opinion.

---

## 5. The register — what to fix, in order

Ordered by *blocks other work → recurs → owner-visible*. Owner-vs-ours per `AGENTS.md` §2-3.

| # | pain | evidence | whose | smallest next action |
|---:|---|---|---|---|
| 1 | **`wrong-data` has no rule** | A #1, 105 sessions; `correction` 5.81% of turns; the system's worst incident | **ours** | add the rule in `05-instruction-redesign.md` §4: *every claim about what you did carries the command and its output line* — and make `false-completion` unrepresentable by requiring the check |
| 2 | **The archive's failure alarm cannot name the machine it could not reach** | **`P3162` was MINE AND WRONG** — retracted; the store is at `/opt/company/archive/lpt-transcripts` and the 13:39Z pass succeeded. What is real: the 13:23Z pass failed exit 3 with `cannot reach , …` — an **empty machine name** — and the 12:28Z pass failed the same way at a 6 GB peak. Lesson `L3774`. | **ours** | fix the message template so it names the machine; bound the pass's memory |
| 3 | **Journal divergence and id collisions** | `K2` 72 + `K1` 12; 121 base-id collisions across ~120 refs; open pain reads 162/366/373/393 | **ours** | one canonical lineage; `bands.tsv` one window per host; promote collisions to ERROR in `check` |
| 4 | **`repeated-work`, no "look before you redo" rule** | A #3, 87 sessions; 66 both-live duplicate lessons | **ours** | one line in the persona + a `journal.py search` in the pre-work checklist |
| 5 | **The authority is one hourly job from a full disk** | `P3161`; 6.1 GB free, 6.27 GB archive temp, swap 93.5%, 11 OOM/24h | **ours** | bounded archive temp; `MemoryMax`; schedule `cron-liveness.py`; let `estate-monitor` escalate what it computes |
| 6 | **The mesh broker runs on the frozen box** | `P3160`; a fan-out hard-failed at 13:2xZ | **ours** | merge `89ffd242`; make a dead broker fall through to direct probing |
| 7 | **~137 of 162 owner questions are not his** | triage §4 | **ours** | settle the ~43 "was X collected" rows as one reconciliation rule; close the ~31 engineering rows |
| 8 | **`false-completion`** | A #5, 48 sessions; `P2948` rc=0 for 2,991 runs | **ours** | make `proof_command` required on a closed item |
| 9 | **Silent failure has no transport** | B: 45 recordings; `estate-monitor` `escalated=0` | **ours** | the one-line routing change, plus an off-box check of cron |
| 10 | **The owner's attention is the scarcest resource** | `P2942`; 160 pending, 78 unanswered texts | **ours** | fix the mirror's freshness (mtime → `generated`) so a stale mirror stops reading as current |
| 11 | **Leaked credentials, rotation owed** | `K12` 18 | ours + 1 his | rotate what we hold a console for; `#450` is already answered |
| 12 | **The 2025 return and four state filings** | `#475` 2 days out; `#476` 28d; `#477` 75d; `#478` 59d; `#480` 85d | **HIS** | **one question, asked** — see `00-SYNTHESIS.md` |

---

## 6. Honesty

- **Coverage:** 935 of 1,059 owner sessions (88.3%) read and classified by an agent; `shard-018` was
  still running at the time of writing. Every session is in the deterministic layer regardless.
- **Vocabulary drift:** 22 records used `research` where only `investigate` was allowed — a reader
  error, counted rather than hidden by `aggregate_readers.py` under `off_vocabulary_tokens`. It does
  not change the ranking; those 22 sessions are *under*-counted in `investigate`.
- **The friction tags are judgments**, not measurements. Two readers may tag the same behaviour
  differently. The ranking is worth more than any single row; treat gaps under ~10 sessions as noise.
- **The 21 clusters are the triage child's judgement** over 393 entries, with grouped overlaps. The
  counts are exact; the membership is not.
- **Not measured:** whether any fix lands. §8 of `05-instruction-redesign.md` names the numbers to
  re-run in 30 days and the scripts that produce them.
