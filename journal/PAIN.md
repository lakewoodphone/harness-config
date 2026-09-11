# PAIN — what hurts, ranked, with what would fix it

**Rule:** every entry names the symptom, the evidence, the cost, and the fix. Ranked by what
actually costs the owner most. This file is how a problem stops being rediscovered.

Updated: 2026-09-11

---

## P1 — The owner's attention is spent on questions that are not his

**Symptom.** ~25% of all 26,950 measured turns were a single letter — `a`, `b`, `yes`, `ok`. Median
turn length 62 characters. 966 turns said "one at a time"; 2,283 said "keep going"; 227 said "stop
reporting back".

**Evidence.** `01-copilot-corpus-audit.md` §3–4, derived from every session on both machines.

**Cost.** The owner is the scarcest resource in the system and he was acting as a decision router
for questions the agent should have decided. It is also why the workflow was abandoned: usage
collapsed 75% in May and 78% again in June.

**Fix.** Encoded in the `zabz` persona: finish the work, never ask permission already held, one
question at a time with options and a recommendation, and never route development decisions up.
Remaining work: make it *measurable* — count questions per session and flag sessions that exceed a
threshold.

---

## P2 — Nothing watches outcomes, so failures are silent

**Symptom.** 8–13 August 2026: six consecutive days, 3,246 ticks, **zero completions**, one dead
model id. Nobody was told. 24 August: 597 ticks, 84% failure. Also silent.

**Evidence.** `04-autonomous-system-postmortem.md` §2.1–2.2, live database.

**Cost.** ~6 days of a company that exists to work while the owner sleeps, plus an unknown number of
missed finance syncs, sensor checks, inbox triage, and follow-ups.

**Fix.** The `ceo-kernel` sentinel — done and verified. It retrospectively detects both windows and
refuses to report when it cannot see. Remaining: run it on a schedule from `secratary` so it is not
dependent on anyone remembering to run it.

---

## P3 — Reading the wrong data and believing it

**Symptom.** The CEO reported a **45-day outage that never happened**, by reading a stale local copy
of the database. Three copies of `secretary.db` exist — 203 / 194 / 173 tables, tick histories ending
on three different dates — and none declares which is authoritative.

**Evidence.** `04-...` §0; `06-decision-log.md` D5.

**Cost.** A false crisis report to the owner. If it had been acted on, real systems would have been
"fixed" that were not broken.

**Fix.** Provenance layer — done. Every reading carries source, authority, and age; a consumer that
cannot establish them refuses. Remaining: **collapse the three copies** into one authority plus
explicitly-marked replicas, and stop anything writing to a stale replica.

---

## P4 — The improvement loop does not close

**Symptom.** 56 proposals unapplied; **30 identical proposals to fix the same file**; 13 targeting
files inside `node_modules`; 51 generated in September, 0 applied. Last successful application:
4 July 2026.

**Evidence.** `04-...` §2.3; live `evolution_log`.

**Cost.** Real tokens spent every day generating improvements that structurally cannot land — which
looks like progress and is worse than doing nothing.

**Fix.** Design exists (path filter, dedup, real apply path, verify-then-keep-or-revert). Not built.
This is the highest-value unbuilt subsystem, because it is the mechanism of self-improvement.

---

## P5 — Work assigned to agents that do not exist

**Symptom.** `engineering_indexer` has run **172 ticks and never completed one**. 34 `ghost_agent`
errors: `goal_steps` assigned to names like `engineering_floor_manager`, `finance_clerk`,
`world_index_indexer` — twenty-plus phantom names, each appearing twice.

**Evidence.** Sentinel finding `agent_dead_weight`; `error_log`.

**Cost.** Work silently vanishing. The blueprint and reality disagree and nothing reconciles them.

**Fix.** A reconciliation check comparing `company_blueprint.py` against live agent ids, plus routing
orphaned steps. Not built.

---

## P6 — Held messages and unanswered questions rot silently

**Symptom.** **7 `critical` and 46 `urgent` messages held undelivered.** 313 questions pending, none
created since 19 July, oldest **131 days** old. Three competing dismissal schemes suggest repeated
ad-hoc noise suppression rather than fixing the cause.

**Evidence.** Sentinel finding `attention_debt`, live data.

**Cost.** The system detected real problems and buried them. Some were customer-facing.

**Fix.** Inbox with ageing, escalation ladder (24h→48h→72h), and an interrupt quota — designed, not
built. Note the 144 sync-breaker alerts in one month are almost certainly why the dismissal schemes
appeared: fix the noise source first or the inbox becomes noise too.

---

## P7 — Context poisoning

**Symptom.** 41,522 tool-leak events across the corpus. Sessions of 4 MB of output per owner turn;
one session reached 399 MB for two messages. `ps_health` alone returns **90,891 bytes** in a single
result.

**Evidence.** `01-...` §5.3; MCP validation report.

**Cost.** Compaction discards the decisions the owner cares about, which is the real cause of "you
forgot what we decided".

**Fix.** Pruning and spill policy exist in the harness. The specific trap is the MCP bridge returning
huge payloads — needs a wrapper that truncates and summarises before it reaches the model.

---

## P8 — Harness configuration drifts between machines

**Symptom.** Desktop had authored a background-first shell preset and **never switched it on**;
Yoga did not have it at all; neither was version-controlled; settings differed in both directions.

**Evidence.** `06-decision-log.md` D7.

**Fix.** `harness-config` source of truth — done, with sync, remote on `secratary`, and LF
normalisation. Remaining: no scheduled sync, so drift resumes the moment someone forgets.

---

## P9 — The CEO stops when it owns the decision

**Symptom.** Four consecutive turns ended with "say go and I'll proceed" for work already delegated.

**Evidence.** `06-decision-log.md` D8.

**Fix.** Rules recorded in the persona. Monitoring it is the honest test: if it recurs, the rule is
insufficient and the harness needs to enforce it rather than the prompt.
