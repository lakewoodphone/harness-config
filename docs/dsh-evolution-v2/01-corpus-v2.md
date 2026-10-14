# 01 — Corpus v2: the measured census, over a corrected denominator

**Prepared** 2026-10-14 · round 2 of the DSH evolution audit. Supersedes `docs/dsh-evolution/01-corpus.md`
(2026-10-13) as the current reading; round 1 remains the baseline it is compared against.

**Every number here traces to a file on the authority** — `/home/zabz/evolution-corpus-v2/` — or to a
script in `/home/zabz/evolution/`, and each block names the command that produced it.

---

## 1. What was read, and how it differs from round 1

| | round 1 (2026-10-13) | round 2 (2026-10-14) |
|---|---|---|
| sessions in the corpus | 6,927 | **7,196** |
| owner sessions | 1,059 | **1,093** |
| owner turns | 4,372 | **4,544** |
| what a reader saw | the **first 256 KB** of a session; his turns truncated to **220 characters** | **the whole session**; every one of his turns **complete** |
| reading layer | 18 shards over a stratified sample | **57 shards**, 11,774,632 bytes, no truncation of his words |
| machine sessions separable? | yes, by a regex heuristic that leaked (see §3) | **measured and excluded** |

The single reason this round exists: **round 1 threw away the most valuable thing in the corpus — what he
actually typed.** Its digests cut every owner turn to 220 characters. This round's carry them whole.

**Built the cheap way, deliberately.** Round 1 already held full owner-turn text, per-call tool sequences
(`tool-calls-full.tsv`, 420 k rows) and failure rows with context, so round 2 did **not** re-scan 2.1 M
event rows on the box that holds the only copy of the company database. It took a **delta** of the 286
sessions changed since `2026-10-13T13:13:28Z` — 120,546 events, **25 seconds** — and merged it onto the
baseline. Scripts: `evolve2.py` (delta + merge), `finalize_corpus.py` (round 1's frozen actor rule,
re-run unchanged), `digest2.py` (new whole-session digests).

---

## 2. The census

**755 of his sessions**, classified by 48 mesh readers over whole-session digests. 884 reader records
were produced and **129 were dropped as machine sessions** (§3). Source:
`python3 /home/zabz/evolution/aggregate_readers_v2.py` → `census-v2.json`, `CENSUS-v2.md`.

| friction | sessions | share |
|---|---:|---:|
| `tool-failure` | 508 | **67.3%** *(upper bound — see §4)* |
| **`wrong-data`** | **92** | **12.2%** |
| `env-hostile` | 87 | 11.5% |
| `slow` | 57 | 7.5% |
| `stopped-early` | 52 | 6.9% |
| `ignored-instruction` | 42 | 5.6% |
| `repeated-work` | 31 | 4.1% |
| `false-completion` | 25 | 3.3% |
| `context-loss` | — | 3.2% |
| **`asked-unnecessarily`** | — | **3.0%** |
| **`asked-badly`** | — | **2.5%** |

*(Counts left blank where the aggregate printed the share and I did not record the count — not omitted
silently: the exact figures are in `census-v2.json`.)*

### 2.1 The finding this round confirms, and the one it re-ranks

**The instruction surface is still aimed at the bottom of this table.** `asked-unnecessarily` plus
`asked-badly` together are **5.5%** — the *least* frequent of everything measured — while roughly a
third of the always-on instruction budget is spent on "do not ask". Round 1 measured the same shape at
3.3% and it could have been a small-sample artefact. It has now been reproduced on a larger, better-read
sample by a different set of readers. **It is not an artefact.**

**`wrong-data` remains at the top of the failures that are not mechanical** — 12.2% against round 1's
11.4%. This is the behaviour the persona only received a rule for in the previous round, and it is the
through-line of the system's worst recorded incident: a crisis reported that did not exist, because a
stale copy was read and believed.

---

## 3. Correction one: the "owner" set was 14% machine

**Measured by `check_actor_v2.py` over `owner-turns-final.jsonl`:** of **1,005** sessions carrying owner
turns, **141 (14.0%)** contain the mesh parent-agent handshake *"Your parent agent id is"*, and **132**
carry it in their **first** turn — so the "ask" that would have been classified is a machine-written
brief, and the tone is a parent's.

Round 1's frozen actor rule excludes a dispatch only when `turns <= 3` **and** the first turn matches a
narrow regex. A dispatch with four turns, or a differently phrased brief, lands in "the owner".

**The exclusion is not optional and is not hidden:** `aggregate_readers_v2.py` drops those sessions and
reports **both** denominators, so the size of the correction is visible. Journal `L3782`.

---

## 4. Correction two: round-2 friction tags are not comparable to round 1's

`tool-failure` reads **67.3%** here against round 1's **10.2%**. One of those is wrong, and the likely
cause was mine: each session block in `shards2/*.md` carries a header line I put there —
`- failure classes: exit_nonzero ×17, …` — because the corpus can compute it.

`validate_friction.py` tested the tag against the corpus's **deterministic** per-session failure count
(`sessions-index.tsv`, column 7), which is computed from `isError` flags and failure regexes, not from
any agent's judgement:

| | sessions | mean failures | median | share with **zero** |
|---|---:|---:|---:|---:|
| tagged `tool-failure` | 273 | 32.2 | 17 | **0.0%** |
| not tagged | 144 | 14.9 | 5 | **32.6%** |

**The tag is grounded** — not one session was tagged without a recorded failure. **But it is loose**: it
means *"this session contains tool failures"*, not *"tool failure is why the session went wrong"*, and
the header primes readers toward the loose reading.

> **67.3% is an upper bound; round 1's 10.2% is a lower bound; the two are NOT comparable**, because
> round 1 could not see the failures its successor can. A document that puts them side by side without
> this sentence is lying by juxtaposition.

Journal `L3783`.

---

## 5. What is still open, stated rather than implied

* **10 of 57 shards never landed.** The reader workflow stalled with its output count frozen at 47
  across repeated checks; the stuck batch is shards 049–054. The census above therefore covers 48
  shards, **not all 1,093 sessions**. Re-dispatch as **ten single-shard children** — never re-run all 57.
  `H3644`.
* **The tone and intent distributions are not reported here.** The aggregate computes them; this
  document reports the friction ranking, which is what the redesign turns on. Read `census-v2.json` for
  the rest.
* **Two off-vocabulary tokens** (`tone:` ×2, `tone:unknown` ×2) were counted rather than silently
  dropped — 4 records in 884, which does not move any ranking.
