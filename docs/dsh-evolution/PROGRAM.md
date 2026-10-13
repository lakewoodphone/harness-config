# PROGRAM — DSH Evolution Audit (2026-10-13)

**Owner's ask, verbatim, 2026-10-13:** *"it's time for the next evolution… go through every single DSH
session… categorize all my conversations… find all the pain points, find what I want, I want the
systems evolved and fixed. I want the instructions and identities changed to better match what we
really need."* Two pillars, his words: **(1)** optimize the system to what we actually do and really
need, fix the pain points — his and mine — robustly, with real engineering and planning; **(2)** go
back through the memories, make sure everything is remembered and documented properly, and produce
an entirely refreshed system spec of what is needed and what is not — *"way smarter, way more
capable, way more autonomous."*

This is the successor to `personal-secretary-mvp/docs/secretary-replacement-audit/` (2026-09-11),
which was built from **1,642 Copilot sessions / 26,950 owner turns** and is the evidence base the
current `zabz` persona was written from. That audit is now a month old, the harness it judged has
been replaced, and the corpus it judged no longer exists in that form.

---

## What is already true, established 2026-10-13 (provenance in brackets)

| Fact | Value | Source |
|---|---|---|
| DSH sessions, authority | **6,909** | `dsh_sessions` on `secratary-cloud:/root/authority.db`, newest `2026-10-13T11:05Z` |
| DSH events, authority | **2,030,000** (approx; exact in `stats.json`) | same |
| DSH session dirs on disk, fleet | 1,795 + 3,910 + 528 + 447 + 253 = **6,933** | `scripts/sessions.mjs nodes` |
| Fleet nodes answering | 5 (local, secratary, zabz-tech, zabz-tech-linux, mac-mini) | same |
| Projects represented | 22 (`--C-Users-ezabz-code--`, `--home-zabz--`, `--Users-lpt--`, …) | `dsh_sessions` |
| Open journal pains | 373 | `journal.py status` |
| Open owner questions | 143 | `owner_decision_queue` mirror |
| Journal entries | 3,624 (handoff 1018, lessons 1422, pain 483, decisions 402, wins 299) | same |
| Instruction surface | `presets/zabz/agent.cordis.yml` 58,677 B + 9 skills ≈ 116 KB | `presets/` |
| Predecessor audit corpus | 1,642 Copilot sessions, 31.58 GB, 593,203 tool calls, 26,950 owner turns | `docs/secretary-replacement-audit/01-copilot-corpus-audit.md` |
| Predecessor raw corpus + tooling | `~/code/_audit/` — `chatscan.py`, `run_corpus.py`, `harvest_prompts.py`, `clean_prompts.py`, `mine_intent.py`, `yoga.json` 89 MB, `desktop.json` 1.9 MB | disk |

**The corpus is ~2 months old, not 14.** DSH began 2026-09-11. So this audit measures a *young*,
high-intensity corpus: ~17,000 owner turns in a month, against Copilot's 26,950 over fourteen. The
comparison to the Copilot audit is therefore the interesting part: **which of the ten measured
behaviours survived the migration, and which did the new harness actually fix?**

---

## Method

**Deterministic first, judgment second.** The Copilot audit's own lesson was that its numbers were
reproducible from scripts, and that its opinions were not. So:

1. **Extract once, on the authority**, from `dsh_session_events` — one streaming pass, every artifact
   at once, every count auditable. Never guess a number; `stats.json` records what the run saw.
2. **Count deterministically** where a rule is unambiguous (intent phrases, tool histograms, failure
   markers, turn-length distribution, approval-loop share).
3. **Judge with agents** where it is not: reading sessions, ranking what hurts, designing the fix.
4. **Fan out across the mesh**, one document per workstream, one writer per path.
5. **Reproduce every claim.** An agent's report is a claim. Numbers come from `stats.json` or they do
   not go in a document.

**Fan-out runs on the MESH** (`subagent` → a real agent turn on another node). This laptop has ~8.5 GB
free of 32 GB; it dispatches, it does not host the fleet.

---

## Workstreams

| # | Workstream | Output | Owner | State |
|---|---|---|---|---|
| 0 | **Corpus materialization** — one pass over `dsh_session_events` | `/home/zabz/evolution-corpus/*` on the authority | me | **running** |
| 1 | **Instruction & identity surface** — the preset, skills, every `AGENTS.md` | `10-instruction-surface-audit.md` | mesh child A | dispatched |
| 2 | **Memory & continuity mechanism** — journal, queue, memories, wake, handoff | `20-memory-continuity-audit.md` | mesh child B | dispatched |
| 3 | **Systems & autonomy** — search, sessions, mesh, dispatch, cron, the company loop | `30-systems-and-autonomy-audit.md` | mesh child C | dispatched |
| 4 | **Open-work triage** — 373 open pains + 143 owner questions, clustered | `40-open-work-triage.md` | mesh child D | dispatched |
| 5 | **Owner-intent taxonomy** — measured from `owner-turns.jsonl` | `05-owner-intent.md` | me + children | waits on WS-0 |
| 6 | **Friction & pain register** — ranked, evidenced, mapped to the journal | `50-pain-register.md` | children | waits on WS-0 |
| 7 | **The redesign** — new instructions/identities, built and tested | `presets/`, `AGENTS.md`, skills | me + children | waits on 1–6 |
| 8 | **The fixes** — top engineering pains, built, verified, merged | branches → `main` | children | waits on 6 |
| 9 | **Record** — journal entries, owner-queue refresh, handoff | journal | me | continuous |

---

## Rules this program holds itself to

* **Nothing is written to the authority database.** The extractor opens it `mode=ro`, `query_only`.
* **One writer per file.** A worker returns its document; the manager writes it. No agent commits
  into a shared repo path while another agent is running.
* **No number without provenance.** Every figure cites `stats.json`, a SQL result, or a file path.
* **A negative is not evidence of absence.** "No match" from a search prints what it searched.
* **The office box `secratary` is FROZEN** (`settings/machines/host-posture.tsv`). The authority is
  `secratary-cloud`. Never a second writer.
* **Report, don't queue.** Anything solvable here is solved here. Owner questions come back as one
  question with one recommendation.

---

## State log

* `2026-10-13 13:05Z` — recon done; program written; corpus extraction running on the authority
  (PID 943706, log `/home/zabz/evolution/extract.log`); four corpus-independent workstreams dispatched.
* `2026-10-13 13:45Z` — corpus measured and finalised: 6,927 sessions, **1,059 (15.3%) the owner's**,
  4,372 owner turns; artifacts on the authority. Four audits returned (instruction surface, memory,
  systems, open-work triage). Three fixes applied and verified.
* `2026-10-13 14:00Z` — **the census closed: 18 of 18 reading shards, 945 of 1,059 owner sessions
  (89.2%)** classified, nothing missing. `00-SYNTHESIS`, `07-pain-register`, `07-target-system`
  written. The persona went 28,697 → 25,531 bytes **with two new rules added**; `AGENTS.md` §6-7 added;
  four skills extended. **Two false claims of my own found and retracted** (the archive) — the #1
  ranked failure, committed by the session writing the rule against it. `L3774`.
* `2026-10-13 13:55Z` — the archive free-space guard **deployed to the host that runs it and proven**
  (exit 0, ingested, 465 MB peak, disk steady) — after discovering the deploy is manual and
  `harness-config` and `/opt/company/archive/tools/` can drift with nothing to notice. `W2758`.

**Open at the end of this program's first pass:** one journal lineage (`N2`); a transport for the
estate's own alarms (`N3`); the four memory fixes (`N6`); the owner-queue filing guard; the two
deliberately-declined persona moves; and the capacity decision, which is row **#473** and is his.
Nothing in this program's scope is blocked on information — only on work.
* `2026-10-13 14:15Z` — **the instruction surface was two days stale on EVERY machine**, not just this
  one. Root cause found: `sync.py` was refusing the profile layer *correctly* (the committed generated
  preset rows embedded a pre-correction sha) and printing one line into a log nobody reads. Rows
  regenerated; `sync.py`'s refusal now files a journal entry. Corrected and verified on all four
  machines that load an estate preset. `W2794`-`W2797`.
* `2026-10-13 14:26Z` — `08-changes-made.md` written: every change, how it was checked, and the two
  false claims of my own kept in the record on purpose.
