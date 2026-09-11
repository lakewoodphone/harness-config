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
refuses to report when it cannot see.

**DONE 2026-09-11 (later session).** The sentinel now runs *unattended*: `ceo-kernel` is a git repo
(deployed as a checkout on `secratary`), and cron runs `scripts/run-sentinel.sh` every 5 minutes,
recording `latest.json` + `history.jsonl` in `/home/zabz/ceo-kernel-var/`. The gap named here — "not
dependent on anyone remembering to run it" — is closed for Phase 1. What is *not* yet closed: nothing
routes a finding to a human (that is the inbox, Phase 2), and nothing reads the history as a trend.
Recording without alerting is deliberate; see `ceo-kernel/docs/OPERATIONS.md`.

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

---

## P10 — ~~Repeated mount-validation spawns duplicate MCP servers~~ **RETRACTED 2026-09-11 — see the correction at the end of this entry. There is no duplication.**

**Symptom.** After several `standingKeyFor` calls, **four** `ps_mcp_server.py` processes were running
as children of the DSH process, plus **three** `mcp_launcher.py` processes — one per validation call.
A standing mount persists for the life of the process, so each check adds a live server rather than
reusing the existing one.

**Evidence.** Process tree on `ZABY-YOGA`, 2026-09-11: DSH pid 11744 had children 57252 / 37548 /
60428 / 24148 all running `ps_mcp_server.py`, and 30716 / 4184 / 49292 running `mcp_launcher.py`.

**Cost.** Wasted memory and duplicate subprocess trees, each holding its own connection to the
secretary API. On a machine with six MCP bridges this compounds. It also makes process evidence
harder to read — "is the bridge up?" returns four answers.

**Fix.** Do not mount-validate repeatedly. Validate once, then rely on it. Longer term: the
mount-validate path should detect an existing standing generation and reuse it rather than
re-composing. Needs investigation in the roster service, not a workaround here.

**CORRECTED 2026-09-11 (later session) — the symptom above is not real. This entry was wrong.**
The "four `ps_mcp_server.py`" count came from matching process command lines against
`personal-secretary-mvp` — a **directory** — which matches every script inside it. Counted by exact
script name on a live session: **exactly one** `ps_mcp_server.py`, plus 3× `mcp_launcher.py`
(firecrawl, jina, context7), one per bridge. There is no duplication, and the "each check adds a live
server" mechanism is unsupported.
What *is* real, and what produced the illusion: **every venv-python launch appears as two processes** —
a ~4 MB parent (the venv shim) and the real payload child (14 MB launcher, 63 MB `ps_mcp_server.py`).
Reproduced independently with a `time.sleep(20)` payload containing no process-spawning code, so it is
a property of the interpreter launch, not of the MCP scripts. A naive process count therefore
**double-counts every python-based bridge**.
*Kept as written, not deleted*, because the error is instructive: this is L2 — reading the wrong thing
confidently — committed inside the very journal created to prevent it. See LESSONS L28.
**Confirmed a second time with eight sessions open (2026-09-11 12:58).** Measured precisely — by
exact process name and script basename, and excluding the survey's own command line — there is
**one** DSH server process (`dsh web`, hosting ~8 sessions) with exactly **one** `ps_mcp_server.py`
shim per external bridge. The bridges are composed **once per process, not once per session**: opening
seven more sessions added no bridges. So the original worry was doubly wrong, and the design is
better than the entry assumed.
Measured as a side note: the whole DSH process tree with six bridges holds **721 MB** across 12
processes, and that number is real, unlike the one above. The dominant cost is not the bridges — it is
**one `dsh-subprocess-local/runner.js` shell per concurrent command at ~58 MB each**, so the memory
story on this machine is driven by how many sessions run shells at once, not by MCP.

---

## P13 — Concurrent sessions share one repo, and `git add -A` sweeps each other's work

**Symptom.** Eight DSH sessions were live in one project directory at once (`session_projcache`,
2026-09-11 12:53–12:58), all on preset `zabz`, several of them editing the same working tree —
`harness-config`, and other repos under `C:\Users\ezabz\code`. While this session was writing the
journal, another session ("Add per-turn chat cost estimates") wrote
`journal/reference/deepseek-token-pricing-2026-09-11.md` into the same repo, and this session's
`git add -A` **committed it**, under a message that does not mention it.

**Evidence.** `git log --oneline -- journal/reference/` → the file arrives in commit `4becfa4`, a
commit whose message describes only journal corrections. File mtime 12:55:41, between two of this
session's own edits.

**Cost.** Small this time — the file was legitimate and correctly placed, and nothing was lost. The
failure class is not small: two agents staging a shared tree means one can commit, attribute, or
revert another's half-finished work, and neither can tell from the diff. It also produces exactly the
phantom-difference confusion of P8/L21, with a new cause.

**Fix.** Adopted rule: **in a shared working tree, stage explicit paths — never `git add -A` or
`git add .`** (LESSONS L33). Longer term, concurrent sessions should not share a mutating repo at all:
either serialise on it, or give each session its own clone and let the remote be the meeting point.
Not built; the rule is the cheap half.

---

## P14 — The real memory cost of a session is the shell, not the tools

**Symptom.** Six MCP bridges looked like the memory story. They are not. Measured on ZABZ-YOGA with
eight sessions live: a DSH server at **678 MB**, six bridges as direct children at **4–63 MB**
(the venv shim is ~4 MB; the real payload is its child), and then **each concurrent shell command at
~58 MB** for its `dsh-subprocess-local/runner.js`.

**Evidence.** Process survey at 12:58, counting by exact name and script basename: 16 direct children
of the one DSH server, of which 10 were `runner.js` at ~58 MB and 6 were bridges.

**Cost.** Roughly ten concurrent shell commands is ~580 MB before the sessions themselves. With eight
parallel sessions on an i9/64 GB desktop that is affordable; on the Yoga it is the number that decides
how much parallel work is safe, and nothing tracks it.

**Fix.** Not urgent and not yet a problem — recorded so a future self sizes parallel work from the
right variable instead of blaming MCP bridges, and so the "eight sessions" habit is a known cost.
If it becomes a constraint, the lever is limiting concurrent shells per machine, not reducing bridges.

---

## P11 — The preset default is chosen at session start, so changes need a restart

**Symptom.** `self_audit` reported this session running preset `cordis` while `settings.yaml` said
`zabz`. The DSH process started at **12:32:28** and the settings file was written at **12:32:29**.

**Evidence.** `self_audit` output; `HANDOFF.md` entry for 2026-09-11.

**Cost.** A change can be "made" and reported as done while having no effect at all. The model
namespace re-reads per request, which makes the difference easy to miss: one setting applied live and
the other silently did not.

**Fix.** After changing `agent-presets.default`, **restart the profile and verify with `self_audit`
before claiming anything.** The rule is now: no claim about a preset without a live agent reporting
that preset.

---

## P12 — Freshness is asserted but not measured, so every reading says `age=?`

**Symptom.** Every provenance line the sentinel prints ends `age=?` — e.g.
`daily_completion: ok  AUTHORITATIVE  age=?  src=sqlite:…secretary.db@secratary`. The source and the
authority are established; **the age of the data is not**.

**Evidence.** `ck status` on `secratary`, 2026-09-11T16:50Z, all seven checks. Same in
`/home/zabz/ceo-kernel-var/latest.json`.

**Cost.** Rule 1 of the kernel is "no trend without freshness" — and the kernel currently reports
trends (a 30-day collapse window) whose underlying data age it cannot state. It is *honest* about this,
which is why it is a medium and not a crisis: `?` is better than a fabricated number. But a reading
that cannot say how old it is cannot distinguish "healthy" from "the pipeline died three days ago",
which is the exact failure the whole kernel exists to catch (L12, P2).

**Fix.** Give each check a declared freshness basis: the timestamp column that proves it is current
(`tick_telemetry.created_at`, `activity_log.created_at`, …), pass it as `newest_row`, and let
`provenance.build()` compute the age. Where no timestamp exists, assert **"age not applicable"**
explicitly rather than leaving `?`, so an unresolved `?` becomes a bug rather than the normal state.
Belongs in `ck/sentinel.py` + `ck/sources.py`; not started.

