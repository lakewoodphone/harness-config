# PROGRAM v2 — DSH Evolution, round 2 (2026-10-14)

**Owner's ask, 2026-10-14, verbatim (abridged):** *"when we set up dsh and migrated from vs code copilot
to dsh a few months ago I had you read every single copilot session ever and classify them… it's time
for the next evolution… go through every single dsh session, and maybe even going back to the copilot
sessions… we need to fan out orchestrate through sub agents, categorize all my conversations… find all
the pain points, find what I want, I want the systems evolved and fixed. I want the instructions and
identities changed to better match what we really need."*

And the emphasis that this round is really about:

> *"especially focus is after doing this and based on your conclusions to audit and evolve the AI
> company that lives on the Secretary Cloud server tremendously, meaning the AI company there is
> supposed to be you. It's like a version of you that just always stays alive. So it needs to be
> brought to the next level and needs to be an order of magnitude better, faster and most importantly
> more capable and autonomous and smart."*

Three pillars, in the order he said them:

1. **Optimise the system to what we actually do and need; fix the pain points — his and mine.** Real
   planning, real engineering, robust.
2. **Go back through the memories; make sure everything is remembered and documented properly.** A
   refreshed account of what is needed in this setup and what is not.
3. **Audit and evolve the AI company on `secratary-cloud`.** Order of magnitude. This is the headline.

---

## Why round 2 is not a repeat of round 1

Round 1 was **2026-10-13**, closed by handoff `H3626` and ~12 documents in `docs/dsh-evolution/`.
It was real work and it stands as the baseline. It also has three measured limits, and this round exists
to close them rather than to re-derive its findings:

| round 1 limit | measured | round 2 rule |
|---|---|---|
| **Sampled heads, not transcripts** | each reader saw the **first 256 KB** of a session | every owner session is read **whole**, via a digest that carries the beginning, the corrections, the failures and the ending |
| **Owner sessions only** | 945 of 1,059 (89.2%) classified; the 4,570 machine/cron/dispatch sessions were never read for *systemic* failure | machine and dispatch sessions are a **first-class subject** — the company's own agents run there |
| **Documents, lightly landed** | fixes were partial; journal lineage still divergent; disk still fatal; several "fixed" claims were later retracted | every finding carries **a verification command and an owner**; nothing closes on prose |

And one subject round 1 never had: **the company itself.** It audited the estate around the company.
It never audited `/opt/company` as a system — its agents, its 900-second tick, its autonomy levels, its
3-round agent loop, its 203 tables, its cost per outcome, or whether any of it works.

---

## What is already established (provenance in brackets)

| fact | value | source |
|---|---|---|
| DSH sessions in the authority DB | 6,935 (newest ingest 2026-10-13T13:08Z) | round-1 audit, `30-` §1 |
| DSH sessions on disk, fleet | 6,933 across 5 nodes | `sessions.mjs nodes` |
| Round-1 corpus artifacts | `/home/zabz/evolution-corpus/` — 204 MB, 24 files, ran 13:08-13:16Z 2026-10-13 | live `ls` 2026-10-14T00:51Z |
| Authority disk | **0 bytes free at 2026-10-14T00:23Z**, 4.1 GB (95%) at 00:56Z | `ALARM` file; `df` |
| Transcript archive | **refused to start for want of free space at 00:23Z**; pass re-run and **green at 00:53:18Z** (`pull_rc=0 check_rc=0 ok=true gaps=[] silent=[]`) | `systemctl status`, `status.json` |
| The company's runtime | `/opt/company` (FastAPI, 323 python modules, 618 routes), `company-api.service`, DB `/root/authority.db` **26.78 GB** | live |
| The company's agent loop | its **own** bespoke loop: `app/services/agent_worker.py` — claim → LLM (max 3 rounds) → autonomy gate L0-L4 → execute → record | file header, live |
| The company's tick | 900 s autoregressive autopilot, 39 subsystems, ~134 ticks/day | round-1 audit |
| Company model spend, 2026-10-14 | **deepseek-v4-flash 46.5M tokens = 20.73 USD, 1,272 calls**, plus ~2.96 USD on Gemini tiers | `ps_company_status` |
| Journal | 3,966 entries, 427 open pain, 155 open owner questions | `journal.py status` 2026-10-14T00:43Z |
| Round-1 instruction surface | persona 25,531 B + 9 skills ≈ 116 KB | `PROGRAM.md` (round 1) |

---

## Method

Deterministic first, judgment second, and a fleet for the judgment. Round 1's method, kept and
tightened:

1. **One streaming extraction pass** over `dsh_session_events` on the authority, read-only, every
   artifact written at once. A delta pass for what has arrived since 2026-10-13T13:16Z; the existing
   artifacts stay the baseline and are re-used, not re-derived.
2. **Digest per session** — deterministic, complete, not a head: the owner's turns verbatim, the tool
   failures with their class, correction and frustration signals, the agent's own last message, turn
   and tool counts, cost if present.
3. **Readers on the fleet** read digests, one record per session, and publish to
   `…/evolution-corpus-v2/reports/`. Aggregation is a script, never a memory.
4. **The company is audited as a system**, from the running host, read-only, and by measurement.
5. **Every claim reproduced by the manager** before it reaches a document. An agent's report is a claim.
6. **Fixes are built, deployed and verified** where they run — not described.

**The mesh rule.** Fan-out runs through `subagent` (a real agent turn on another node). This laptop
dispatches; it does not host the fleet. A child reports the host it ran on and refuses to guess.
If the mesh is unreachable, that is stated, and anything that ran locally is marked **LOCAL**.

**The authority rule.** `secratary-cloud` is the sole writer of the company database and a 15 GB box.
Read-only there; nothing heavy runs on it; `df` and `free` before anything that writes.

---

## Workstreams

| id | workstream | output | node |
|---|---|---|---|
| **E1** | corpus v2 — delta extraction, digests, deterministic re-measure | `evolution-corpus-v2/*` on the authority; `01-corpus-v2.md` | authority |
| **E2** | reader fleet over every owner session (whole-session digests) | `reader-*` in the corpus dir | mesh |
| **E3** | machine/dispatch sessions read for *systemic* failure | `03-machine-sessions.md` | mesh |
| **X1** | the Copilot layer — 1,608 sessions, what DSH lost and gained | `05-copilot-delta.md` | authority |
| **H1** | instruction & identity surface v2 | `10-instruction-surface-v2.md` | mesh |
| **M1** | memory & continuity v2 — journal, queue, memories, wake, handoff | `20-memory-v2.md` | mesh |
| **S1** | estate systems v2 — disk, archive, monitors, search, sessions, dispatch | `30-systems-v2.md` | authority + mesh |
| **P1** | the ranked pain register v2, both lists, with owners | `07-pain-register-v2.md` | manager |
| **C1** | **the company map** — what it is, agent by agent, table by table | `40-company-map.md` | authority |
| **C2** | **the company audit** — what it accomplishes, what it fails at, cost per outcome | `50-company-audit.md` | authority |
| **C3** | **the company design** — the next-level architecture, argued and costed | `55-company-design.md` | manager |
| **C4** | **the company build** — landed, deployed, verified | `60-company-changes.md` | manager + fleet |
| **F1** | the harness fixes that land — top ranked, built and verified | `70-fixes-landed.md` | fleet |
| **R1** | record — journal, owner queue, handoffs, this program | journal + `docs/` | manager |

---

## Rules this program holds itself to

* **Nothing is written to the authority database.** Read-only, `mode=ro`, `query_only`.
* **One writer per file.** A worker returns a report; the manager writes the document.
* **No number without provenance.** Every figure cites a file, a command's output line, or a row.
* **A negative is not evidence of absence.** "No match" prints what it searched.
* **`secratary` is FROZEN** (`settings/machines/host-posture.tsv`). Never a second writer.
* **Report, don't queue.** Anything solvable here is solved here. What is left for the owner becomes
  one question with one recommendation.
* **Look before redoing.** Before commissioning any audit, `journal.py search` for it and read what
  round 1 already established.
* **A fix is a verification command**, not a paragraph.

## State log

* `2026-10-14 00:56Z` — recon complete. Program written. **Live P0 closed and verified:** the
  transcript archive had refused to pull since ~18:25Z on free space (0 bytes free at 00:23Z); safe
  regenerable space reclaimed, the pass re-run, and it exits 0 with no gaps and no silent machines.
  Authority at 4.1 GB / 95%. Round-1 corpus artifacts confirmed present and re-usable. The company's
  runtime confirmed to be a bespoke loop, not DSH.
* `2026-10-14 01:14Z` — **the disk emergency was root-caused and fixed, and it was not the box.**
  `/root/.disk-guard/guard.log` shows **0 bytes free continuously from 2026-10-13T20:15Z to
  2026-10-14T00:48Z — 4 h 33 min**. Cause: the Hetzner server was CCX23 compute on an 80 GB
  CCX13-class disk, because a type change applied the compute half and skipped the disk half
  (Hetzner's `change_type` requires a stopped server for a disk upgrade). The owner power-cycled the
  VM; **verified after, not assumed**: `/dev/sda` 163,842,097,152 B (was 81,923,145,728), `df -h /` =
  `150G 68G 76G 48%`, swap 0 of 4095 MB, `company-api`/`cron`/`mesh-broker`/`cloudflared` active,
  `systemctl --failed` 0 units, `/health` ok. **P3169, W2805.**
* `2026-10-14 01:16Z` — **corpus v2 built the cheap way.** Round 1 already held full owner-turn text,
  per-call tool sequences and failure rows, so round 2 did **not** re-scan 2.1 M event rows on the box
  that holds the company database: a **delta** of the 286 sessions changed since
  `2026-10-13T13:13:28Z` (120,546 events, **25 s**) was merged onto the baseline.
  `evolve2.py` → `finalize_corpus.py` (round 1's frozen actor rule) → `digest2.py` (new:
  whole-session digests). Measured: **7,196 sessions; 1,093 owner sessions and 4,544 owner turns**
  (round 1: 1,059 / 4,372); `shards2/` = **57 shards, 11,774,632 B**, every owner turn complete where
  round 1 truncated each to 220 characters and read 256 KB heads.
* `2026-10-14 01:20Z` — five mesh audits dispatched; four returned and are in `reports/`:
  `company-map.md` (138 KB), `company-failures.md` (37 KB), `estate-v2.md` (66 KB),
  `instruction-v2.md` (42 KB). Memory audit in flight. **The reader fleet is running** as a workflow:
  57 mesh children, one per digest shard, in batches of six.
* `2026-10-14 01:25Z` — **the company fails ~70% of the work it attempts.** 7 days: 580 failed, 236
  "completed" — and **none of the 236 used the `[WORK_DONE]` path**; every one fired because the task
  row was already closed. Root causes are control-flow, not model quality: a hard 5-step budget whose
  only extension requires a *mutating* action (so investigation-heavy work can never finish); a 3-strike
  tool abort; two empty turns ending a session; completion keyed on a token the model never emits; and
  a retry that is a brand-new session with no memory of the last one (233 tasks retried, **0
  succeeded**). 7-day model spend **119.10 USD**, of which roughly a fifth to a quarter went on failed
  work. Tick telemetry calls 89% of ticks "complete" while those sessions fail 70%.
* `2026-10-14 01:30Z` — **round 1's instruction fixes did not reach the machine the fleet runs on.**
  `instruction-v2.md` measured the `{cwd}` bug still live in ZABZ-TECH's loaded persona, the
  wrong-data rule absent there, and three statements still naming the frozen office box as the
  authority. Round 1 verified 15/15 preset drift-free — on the canonical clone. `AGENTS.md` §6.3's
  defect, recurring.
* `2026-10-14 01:32Z` — handoff **H3632** written with the full state, the traps, and the next steps.
* `2026-10-14 01:19Z` — **all five audits in.** `memory-v2.md` (41 KB) joins the set. Reports live in
  `reports/` here **and** at `secratary-cloud:/home/zabz/evolution-corpus-v2/reports/`.
* `2026-10-14 01:20Z` — **`55-company-design.md` written.** The company's failure is diagnosed as
  control flow, not intelligence, and the design names eight defects with file-and-line evidence:
  a 5-step budget whose extension requires *mutation* so investigation can never finish (379 of 580
  failures); a 3-strike tool abort that misreports its own count as `0/3` (156); two empty turns
  ending a session (38); completion keyed on `[WORK_DONE]`, which **zero sessions emitted**; retries
  that are brand-new sessions (**233 retried, 0 succeeded**) while `progress_checkpoints` holds 3,156
  rows nothing reads; **an autonomy gate that defaults unknown actions to L4, leaving ≥91 dispatcher
  names — including `hire_department`, `fire_agent`, `delete_tool` and the whole `shop_*`/`website_*`
  family — able to execute with no human**; memory written and never read (`store_memory_entry`,
  `vector_search_memories` and `upsert_knowledge` have **zero callers**); and **181 hardcoded model
  ids across 13 files**, the exact shape of the failure that silently broke `personality-system` for a
  week. Ten numbered changes and the numbers each must move are in the document.
* `2026-10-14 01:22Z` — **build started.** Two worktrees cut on the authority from the live revision
  `db07e8e0`, with the live venv linked and `import app.main` verified in each:
  `/root/work/evolve2-loop` (`evolve2/loop`) and `/root/work/evolve2-gate` (`evolve2/gate`). Two mesh
  builders dispatched with disjoint file scopes — the loop owns `autopilot.py`,
  `work_step_ledger.py`, `agent_worker.py`, `tick_quality.py`; the gate owns `autonomy.py` and the
  generated matrix. **Neither may touch `/opt/company`**, which is live with 94 uncommitted files from
  other sessions. Deployment is the manager's, not theirs.
* `2026-10-14 01:25Z` — 10 of 57 reader shards returned.
* `2026-10-14 01:35Z` — **the instruction surface on ZABZ-TECH was stale, and the machine had been
  reporting `clean` while skipping the step that installs it.** Measured on the *loaded* file, not the
  checkout, which is the distinction that hid it: `~/.dsh/.agent-presets/zabz/agent.cordis.yml` was
  58,677 B dated 2026-10-13T13:17 with **zero** occurrences of round 1's wrong-data rule, **three**
  literal `{cwd}` tokens, and the pre-correction facts. `~/.dsh-sync-status/status.json` at
  01:17:16Z reads `result: "clean"` **and, in the same line, `SKIPPED (not applied): profiles … the
  committed generated preset rows are STALE … DRIFT`** — while `autosync.ps1`'s own header states that
  a skipped step is not a converged step. This is `AGENTS.md` §1 trap 2 (a job reporting success for
  21 days while the archive stood still) a third time, and this time the victim was the prompt. Fixed
  by running the repo's own installer and verifying the **loaded** file: 56,297 B, rule present,
  `{cwd}` 3→2, `secratary-cloud` named 6×, stale fleet claim gone; a second `--dry-run` reports no
  `WOULD`, no `SKIPPED`, no `DRIFT`. **P3171.** An instruction audit that reads the checkout is not
  measuring what a session runs.
## Round 3 — 2026-10-14, opened 11:49Z on ZABZ-YOGA (session `be1398ed`)

The owner re-issued the whole command: *"This is the command another session got and worked on very
hard today. So a lot of it was done, but I want you to start again… update and evolve it fully and fix
everything and make it even better."* Round 3 therefore **continues round 2 rather than replacing it**,
and its first duty is to verify what round 2 claimed.

**What round 2 delivered, confirmed present at 2026-10-14 11:50Z:** corpus v2 at
`secratary-cloud:/home/zabz/evolution-corpus-v2/` (7,196 sessions, 1,093 owner sessions, 4,544 owner
turns, 57 shards, 11.77 MB); the reader census **completed after round 2's own document was written** —
`CENSUS-v2.md` and `census-v2.json` record **1,093 reader records over 57 shards**, 132 dropped as
machine sessions, a census over **961** owner sessions; seven reports in `reports/`; two test-verified
builds in `/root/work/evolve2-loop` and `/root/work/evolve2-gate`, **neither merged nor deployed**.

**Corrections to round 2's own record, made this round:**
* `01-corpus-v2.md` §5 says "10 of 57 shards never landed… the census covers 48 shards". The census was
  re-run to completion at 01:58Z and covers **57 shards / 961 sessions**. The document is stale against
  its own artifact — the shard gap closed after it was written. (`H3644` was right when written.)
* Round 2's headline *"`[WORK_DONE]` … zero sessions emitted it"* **does not hold as stated**: measured
  this round, **675 work sessions in the last 7 days contain the string in `output_log`**. Whether that
  is the model emitting it or the loop writing its own prompt into `output_log` is the whole question
  and is **not assumed here** — it is assigned to workstream A1 to settle. This round does not repeat
  the vice round 2 caught itself in.

**What round 2 left undone** — these are round 3's worklist, not new work: `03-machine-sessions.md`,
`05-copilot-delta.md`, `07-pain-register-v2.md`, `40-open-work-triage`, `50-company-audit.md`,
`60-company-changes.md`, `70-fixes-landed.md`, and the instruction/identity v2 **build** (round 2 audited
the surface; it did not rewrite it).

**The company, re-measured on the live database 2026-10-14 11:50Z** (`sqlite3 -readonly
/root/authority.db`, ZABZ-YOGA) — **corrected at 12:30Z, see the note below the table:**

| measure | 7 days (Oct 8–14, by calendar day) | today (Oct 14, partial) |
|---|---|---|
| work sessions, all | **786** | 91 |
| work sessions `completed` | 237 | 33 |
| work sessions `failed` | **533** (67.8 %) | 48 |
| model spend | **122.87 USD** | 22.13 USD |
| evidence-backed completions | 24 (all of them today) | 24 |
| `STEP_BUDGET_EXHAUSTED` | 415 *(8-day window — see note)* | — |
| `TOOL_LOOP_DEADLOCK` | 176 *(8-day window)* | — |
| `STALLED_REPEATING` | 56 *(8-day window)* | — |

> **A defect in my own first reading, found and fixed within the hour — and it is a defect of the whole
> estate, not of one query.** I first published "model spend 140.42 USD / 7 days, 45.45 USD / last
> 24 h". Both are **inflated by one full day.** `model_usage.created_at` is stored as
> `2026-10-14T11:05:01.867681+00:00` (ISO-8601, `T`-separated — measured: 262,424 rows contain `T`,
> **0 contain a space**), while `datetime('now','-1 days')` returns `2026-10-13 11:50:00`
> (**space**-separated). SQLite compares TEXT byte-wise, and at position 10 `'T'` (0x54) sorts **after**
> `' '` (0x20) — so `created_at > datetime('now','-1 days')` matches **every** row on 2026-10-13
> whatever its time, i.e. it is a two-day window. Measured proof, same column, same minute:
> `created_at >= '2026-10-13T11:50:00'` → 3,218 calls / **33.03 USD**;
> `created_at > datetime('now','-1 days')` → 5,023 calls / **45.45 USD**. Mis-matching formats is the
> whole difference. The same bug is why my 24-hour work-session counts read 277 (174 failed + 93
> completed) when today's own total is **91** — 277 is exactly Oct 13 (186) + Oct 14 (91).
>
> **Consequence for the reader: any figure in this estate produced with `WHERE <ts> > datetime('now',
> '-N days')` against a `T`-format column covers N+1 days.** That includes round 2's "119.10 USD in a
> week". The day-grouped table above is the corrected reading; the three failure-marker counts in the
> row above are still the 8-day window and are marked as such rather than quietly restated. The fix is
> one helper — compare against `strftime('%Y-%m-%dT%H:%M:%S','now',...)` or use `date()` grouping —
> and it is workstream A12.

`tick_telemetry` 24 h: **192 `complete`/`productive`** against 8 `error` — the self-grading is still
measuring activity, not outcome. Round 2's diagnosis (control flow, not intelligence) survives
re-measurement.

**Corrected within the hour, by the round-3 session that wrote it.** I first recorded that "spend is
accelerating: 7-day average 20.06 USD/day, last 24 h 45.45". That was a rolling-window artefact, not
a trend. The per-day figures (`SELECT date(created_at), round(sum(estimated_cost_usd),2) FROM
model_usage GROUP BY 1` over 9 days) are flat:

| day | 10-06 | 10-07 | 10-08 | 10-09 | 10-10 | 10-11 | 10-12 | 10-13 | 10-14 (partial) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| USD | 12.11 | 17.53 | 19.73 | 16.79 | 12.26 | 15.20 | 13.44 | 23.32 | 22.13 |

So ~17 USD/day and ~123 USD per 7 days, **flat**. And the completion rate is not flat — it is slowly
rising, and today it changed in kind:

| day | 10-06 | 10-07 | 10-08 | 10-09 | 10-10 | 10-11 | 10-12 | 10-13 | 10-14 (partial) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| work sessions | 91 | 121 | 144 | 108 | 74 | 95 | 88 | 186 | 91 |
| `completed` % | 17.6 | 24.0 | 27.1 | 29.6 | 33.8 | 25.3 | 27.3 | 32.3 | **36.3** |
| evidence-backed (`[TASK-CLOSED-BY-SESSION]`) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **24** |

**A live loop change landed during this session, applied by another session, not by this program.**
`/opt/company/app/autopilot.py` was modified at **2026-10-14T07:23:44Z** (md5 `30a4a185a8e2839509
2032fc4d367f36`, 522,614 B; backup `autopilot.py.bak-item80-20261014T072225Z`), and the live file now
carries `_WORK_MAX_STEPS = 20` (was 5) with a hard ceiling of 30 — which is edit **P1** of
`55-company-design.md` — plus the evidence-based completion markers `[ARTEFACT:`, `[OUTBOUND:`,
`[TASK-CLOSED-BY-SESSION:` and the comment "`[WORK_DONE]` is an intent to finish, never the verdict"
— which is **P4**. `app/services/autonomy.py`, the gate build's target, is **untouched** (Jul 1).

**Measured effect of that change, today, before vs after 07:23Z** (`work_sessions`):

| | sessions | completed | failed | completed % | STEP_BUDGET_EXHAUSTED | TOOL_LOOP_DEADLOCK | STALLED |
|---|---:|---:|---:|---:|---:|---:|---:|
| before 07:23 | 65 | 25 | 34 | **38.5 %** | 32 | 13 | 6 |
| after 07:23 | 26 | 8 | 14 | **30.8 %** | 5 | 7 | 10 |

**The budget fix did not move the outcome; it moved the failure.** Budget exhaustion as a share fell
from 49 % to 19 %, and stalling rose from 9 % to 38 % of sessions — the fix removed the wall in front
of the next wall. At n=26 the completion difference is noise, and it is recorded as noise rather than
as a regression. **The conclusion is that P3 (a stall changes strategy instead of ending the session)
is now the dominant residual failure, and it is the one to build next.**

**The finding that reframes the headline.** There are **two** always-alive systems on the authority, and
round 2 audited only one of them:

| | wake loop (cron, ledger-driven) | the company (`/opt/company`, bespoke loop) |
|---|---|---|
| cost, 2026-10-14 | **9.08 USD** over **132 releases** (419.8 M tokens, 0 unsourced, `wake-cost-cron.log`) | **45.45 USD / 24 h** |
| discipline | claim from a ledger → work → **close with a named proof or the shift is recorded as producing nothing**; `nothing-todo` must be reported and stops the shift | completion keyed on a token the model may never emit |
| self-limiting | daily release cap 150, spend ceiling 25 USD/day, pause file, single-flight lock, hourly balance guard | none found |
| attribution | per-release cost, measured, 0 unmapped | `tick_telemetry.total_cost` ≈ 1.02 USD/week against 140.42 USD actually spent |

The cheap loop is the better-engineered one. Workstream **A9** tests whether its *results* justify that,
and no architecture decision is taken from the cost table alone.

**Disk, checked because yesterday's 4 h 33 min outage was a full disk:** 29 GB free at 80 %
(`df -h /`). The 47 GB consumed since 01:14Z is a **27.5 GB stale `authority.db.pre-remediation-*` copy**
in `/root/lpt-sweep-20261014/` (the handoff calls it 16 GB; it is 27,515,334,656 B) plus `/root/work`.
Not a runaway, and **not deleted** — `H3659` records it as the owner's call.

**Round-3 wave A, dispatched on the mesh 2026-10-14 12:0xZ**, every writer on its own path, all
read-only on the authority: A1 company control-flow truth (`company-truth.md`), A2 dead weight
(`company-deadweight.md`), A3 machine/dispatch sessions (`03-machine-sessions.md`), A4 open-pain triage
(`40-pains-triage.md`), A5 owner-question triage (`41-owner-questions-triage.md`), A6 Copilot delta
(`05-copilot-delta.md`), A7 friction evidence (`06-friction-evidence.md`), A9 wake-loop audit
(`09-wake-loop.md`), A10 deploy runbook (`DEPLOY-PLAN-20261014.md`). Outputs land in
`secratary-cloud:/home/zabz/evolution-corpus-v3/`.

* `2026-10-14 01:40Z` — **instruction-surface health across the fleet, measured at the installed file

* `2026-10-14 01:40Z` — **instruction-surface health across the fleet, measured at the installed file
  and the sync record rather than the checkout.** ZABZ-YOGA: sync `clean` and truthful
  (`profile web … applied`, no skip), persona correct. **ZABZ-TECH: sync said `clean` while skipping —
  fixed and verified.** `secratary-cloud`: sync says `attention`, `not converged: diverged … the shared
  checkout is on 'hk/28-refresh-deployed-sources-20261013', NOT on 'main'` — honest, but its
  harness-config is not converging. **`linux-pc-ts` and `mac-mini-ts` have no sync status file at
  all** — the installer is not running there, so they drift with nothing to report it. Four machines,
  four different answers to "is the instruction surface current", and only one of them was telling the
  truth.
