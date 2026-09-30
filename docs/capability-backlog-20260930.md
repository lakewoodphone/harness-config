# Capability backlog — 38 things to change, one topic each

**Date:** 2026-09-30 · **Author:** Zabz seat (DSH) · **Companion documents:**
`autonomy-audit-20260930.md` (what is broken and why) and `tooling-audit-20260930.md` (the 2026
landscape and our stack).

Each item is a self-contained topic: what to do, why it is worth doing with the measurement behind it, how
much effort, what it buys, and the first concrete step. They are ordered by leverage within each group, not
by theme.

## Status — what is already done (updated 2026-09-30 15:25Z)

- **Item 7, DONE and verified live.** A read-only reader, `scripts/wake/wake-nextclaim.py`, answers
  "can anything be claimed right now, and if not, when" from the `not_before` gate. `autonomy-status.sh`
  now prints three distinct states instead of one. Live output at 15:13Z:
  `IDLE: healthy - 8 row(s) waiting, NONE claimable now; earliest 2026-10-01T19:44:24+00:00 (dormant-archive:20260928)`
  — where an hour earlier the same queue read "no cap in force - the next cron tick should claim".
- **Items 9 and 10, DONE and verified live.** A failed claim no longer runs `rm -rf` on its own evidence:
  it is moved to `~/.sms-inbox/wake-failed/` and the tick now records the gate reason. Confirmed on the
  15:15Z tick: `claimed=no; stopping; evidence=kept in .../wake-failed; gate={"claimable_now": 0, "gated": 8,
  "earliest": "2026-10-01T19:44:24+00:00"}`.
- **Item 6, DECIDED.** An integrator shift may merge reviewed, test-green, conflict-free branches to main —
  logged, revertible, no force-pushes. Recorded as decision **D2841**.
- **Item 5, blocked on one measured thing.** `work-integrator.py` never merges (it files integration items),
  but it has no per-run limit and a cold dry run finds 12 unmerged branches for kosher-ai-filter, 9 for
  lpt-website and 5 for lpt-sync. Scheduling it as-is would file dozens at once. It gets a `--limit` first.
- Backups of both changed live scripts exist beside them on the authority, and the repo copies in
  `scripts/wake/` were updated in the same commit so the next deploy cannot silently revert the fix.

Items 1-5, 6's implementation, 8 and 11-38 remain as written below.

Numbers in USD, written plainly. Where a figure comes from a vendor's own page the source document names
it; where it is my arithmetic it says so.

---

## A. Autonomy core — make it run itself

**1. Local-first shift runner.** Run shifts on the authority itself by default and treat the desktop as a
peer, not as the only executor. *Why:* I ran one — `node .../dsh/lib/bin.js --profile headless` on the
authority exited 0 with `LOCAL_SHIFT_OK` — while every one of today's releases crossed an ssh hop that has
already destroyed answers 16 times. *Effort* M. *Gain:* deletes the answer-loss class, the sleeping-desktop
dependency, and most store contention in one move. *First step:* add a `runner` column (`authority` |
`desktop`) to `work_item` and `wake`, and run one real ledger item locally end to end.

**2. Per-item runner and repo-relative definitions of done.** Every item declares which node can execute it
and states its proving command relative to the repo root, not to a Windows absolute path. *Why:* item 82's
definition of done is `cd C:\Users\ezabz\Code\chumash-timeline && ...`, which no Linux executor can run,
while the authority holds the same repository at `/home/zabz/repos/chumash-timeline`. *Effort* S. *Gain:*
makes item 1 possible and makes a second executor a routing decision instead of a rewrite. *First step:*
rewrite the definitions of done for the eleven blocked items and add the column.

**3. Result before acknowledgement.** A runner commits its result to the store *before* it releases the
lease, so "finished but unrecorded" cannot exist. *Why:* row 79 in the store reads `session finished but
the output file could not be copied back (scp rc=1) - the result is unverified`. *Effort* S. *Gain:* the
answer stops being the thing that gets lost; retries become safe. *First step:* one transaction on the
release path — insert the outcome, then clear the lease.

**4. Give `blocked` a way out.** Type the blocker (`owner` | `role` | `dependency`), store a `revisit_at`,
and make one source re-examine anything blocked past its revisit time. *Why:* 11 of the 15 non-done items
are `blocked`, every one names a pending owner row or a role that does not exist, and no code ever moves an
item out of that state. *Effort* S. *Gain:* turns a dead-end state into a queue with a clock. *First step:*
add the two columns and a source that lists blockers whose revisit time has passed.

**5. Schedule the integrator.** `/home/zabz/bin/work-integrator.py` exists, is 12.8 KB, and appears in no
crontab. Schedule it, with an integration item type, so reviewed branches land. *Why:* four items are
blocked on merges a shift is forbidden to do; item 82 is review-complete with a clean merge tree and has
sat since 2026-09-29. *Effort* S. *Gain:* work stops accumulating as unmerged branches — the standing
failure of this whole loop. *First step, updated:* it needs a `--limit N` argument first. A cold dry run
found 12 unmerged branches for kosher-ai-filter, 9 for lpt-website and 5 for lpt-sync, and the script has
only `--days` and `--project`, so one scheduled run would file dozens of items at once, many of them stale
`origin/agent/*` and `origin/integrate/*` refs. Add the cap, verify with a dry run that files nothing,
then schedule it hourly.

**6. Authorize the integrator to merge to main, scoped and audited.** *This is the one item that is
genuinely yours.* Two blocked items say, in their own words, "a person with main-branch access" and "only
a person may commit to main" — that is a missing role, not a judgement call, and it is currently routed to
you by default. *My recommendation:* authorize an integrator agent to merge **reviewed, test-green,
conflict-free** branches to main, with a mandatory revert path, a per-merge audit line, and a standing
prohibition on force-pushes and history rewrites. *Effort* S once decided. *Gain:* you stop being the
merge queue. *First step:* your yes or no on exactly that scope.

**7. One reading that decides.** Replace the waiting count with next-claimable time, and distinguish three
states explicitly: claimable now, gated until a named time, and stalled (claimable now, nothing claimed).
*Why:* at 14:44Z the status tool said `7 row(s) waiting and no cap in force - the next cron tick should
claim` while all seven rows were gated days out; two sources file rows with `not_before` three to seven
days ahead by design, so the count means nothing. *Effort* S. *Gain:* ends the failure class this system
has already been burned by — a reading that cannot distinguish two states. *First step:* call
`_candidates_gated()` from `autonomy-status.sh` and print the earliest claimable timestamp.

**8. An external dead-man switch.** A check that pings out from the authority on every tick and alerts your
phone when it stops, hosted off the authority. *Why:* both heartbeats exist and nothing off-box reads
them; if the authority dies, its own health checks die with it. *Effort* S. *Gain:* a silent stop becomes a
loud alert; 0 USD on the free tier, about 20 USD/month at the business tier with SMS. *First step:* one
check, period set to twice the tick interval.

## B. Reliability — stop losing work

**9. Stop destroying the failure evidence.** `wake-fanout.sh` runs `rm -rf "$INST"` when a shift does not
claim, deleting `wake-ssh.log`, `claim.json` and `prompt.txt` — the only record of why. *Why:* eleven
consecutive failed ticks today, zero evidence retained; 223 instance directories leak in the other
direction. *Effort* S. *Gain:* every future stall is diagnosable in one read instead of an hour of
archaeology. *First step:* replace the delete with a rotate-to-`wake-failed/` and a cleanup by age.

**10. Continue past a non-claim instead of breaking the run.** One unclaimable row at the head of the
ordering currently blocks every other row. *Why:* the fan-out's own log shows `started 1 this run` on
every tick while eight rows waited. *Effort* S. *Gain:* the queue drains in order instead of stalling
behind its worst row. *First step:* log the gate reason from `wake.py`, skip that row, try the next.

**11. Fix store contention at the source.** Eight or more writers hammer `inbox.db`; a heartbeat that
cannot write causes a session to be killed so it cannot be double-run. *Why:* row 125 was killed at 655
seconds for exactly that reason, and today's log carries a lock storm from 00:07Z to 00:40Z. *Effort* S.
*Gain:* stops converting contention into killed work. *First step:* one writer process, or WAL plus a
generous busy timeout on every path, then re-measure the lock-error count for a day.

**12. Pull-dispatch instead of ssh-push.** The worker claims from a `runs` table on the authority rather
than being invoked through a shell hop. *Why:* it removes the single place where a killed tunnel loses an
answer, and it makes retries and concurrency control possible. *Effort* M. *Gain:* the top failure mode
disappears; ssh becomes a fallback. *First step:* add `runs` and a claim query, then have one worker poll
it every ten seconds.

**13. One lease mechanism across both stores.** The wake store and the ledger each have their own lease
handling, and the ledger's reaper has never reported freeing anything (`reaped {"count": 0}` on every
line). *Why:* a reaper that has run but never freed a lease is untested, not working. *Effort* S. *Gain:*
a shift that dies mid-item stops leaving the item neither done nor available. *First step:* plant an
expired lease and watch the reaper free it and record it.

**14. Idempotency keys on every side effect.** Key them `run_id:step_index` and honour them before any
send, payment or record write. *Why:* retries exist precisely because runs die, and a re-run must not
double-send or double-charge. *Effort* M. *Gain:* at-least-once delivery behaves like once. *First step:*
an `effects` table with a unique key, written before the call.

**15. A per-session event log and defined exit codes.** Each shift emits a small JSONL record plus an exit
code, and that record is the durable artefact. *Why:* today a shift's output is 184 to 201 KB on a desktop
and a single truncated `outcome:` line in the log; the dispatcher explicitly logs that the harness reports
no cost. *Effort* M. *Gain:* inspectable, resumable, gradeable runs and real cost attribution. *First
step:* define six events (start, tool call, tool result, message, end, exit) and emit them for one item.

**16. Harvest the transcript.** Two hundred kilobytes per shift is written and discarded. *Why:* the store
keeps a truncated line, so nothing can be reviewed after the fact — including by you. *Effort* S. *Gain:*
the reasoning behind every shift becomes reviewable and searchable; also the raw material for evaluating
quality. *First step:* copy the output file into the session archive and index its path in the ledger.

**17. A capability and health table for nodes, with a drain flag.** Work lands only on a node that has the
code and the credentials. *Why:* the wake path has no placement layer at all and hardcodes one desktop;
the mesh broker that does this properly already exists and the wake path ignores it. *Effort* M. *Gain:*
fewer "not found" and "not logged in" failures, and a laptop that can be drained before it sleeps. *First
step:* a `nodes` table with capabilities, `last_seen`, and a drain column, filtered into the claim query.

## C. Supply — give it work, and finish it

**18. Wire the journal's open pain into the ledger.** 304 open pain entries are the machine's own written
backlog and no source reads them. *Why:* the machine idles with an empty todo queue while its own record
holds hundreds of measured problems; `grep -rln journal /home/zabz/bin/sources/` shows only
`dormant-handoff.py`, which reads handoffs. *Effort* M. *Gain:* the largest single increase in available
work, from a list that is already deduplicated and evidence-bearing. *First step:* a source that files the
top ten open pain entries as ledger items with a `revisit_at`, run in dry-run first.

**19. Wire the CEO kernel and the company's sensing into the ledger.** `grep -rln "wake.py\|work.py"
/home/zabz/ceo-kernel/` returns nothing, so the sentinel running every five minutes and the
company-outcome monitor cannot create a single item. *Why:* the biggest producer of "the machine noticed
something" is disconnected from the only consumer of work. *Effort* M. *Gain:* every monitored condition
gets a path to actually being fixed. *First step:* give the sentinel one write path — file, dedupe, done.

**20. Make integration a first-class source, not a hope.** Merging and verifying should be filed as items
with the same rigour as building. *Why:* a shift ends with a pushed branch and a line saying the next
worker must merge it, and nothing merges it — item 82 has waited a day. *Effort* S once item 5 exists.
*Gain:* daily progress stops accumulating as unmerged branches. *First step:* a source that scans pushed
branches not on main and files a merge item with the branch's own test command.

**21. Close the discovery deadlock for empty projects.** One registered project has no items at all and
still gets woken. *Why:* a woken session whose project has no ledger item gets `nothing-todo` and stops, so
the project is scheduled, woken, and advances nothing. *Effort* S. *Gain:* no project burns releases doing
nothing. *First step:* a discovery item for every enabled project with an empty queue.

## D. Cost and context — same work for a fraction of the tokens

**22. Freeze a byte-stable cached prefix.** Constitution and tool list first, in a fixed order, nothing
dynamic above the cache breakpoint. *Why:* cache reads cost roughly a tenth of writes (0.003 against 0.15
per million input tokens on the Flash tier), so one changed byte at the top re-bills the whole prefix; the
measured shape gives 30-60% off input cost. *Effort* M. *Gain:* the cheapest large saving available.
*First step:* hash the first 4 KB of the shift prompt and log write-versus-read tokens for twenty shifts.

**23. Generate a 2,000-token packet per shift instead of a prompt that re-derives the world.** Constitution,
work item with its verbatim proving command, interface contract, state snapshot, decisions and dead ends,
next action, recall index, output contract. *Why:* a shift currently re-derives context it could be handed,
and measured cost per shift is 3 to 5 million tokens; the packet attacks the prefix-cost line, about 90% of
it. *Effort* M. *Gain:* roughly ten times more steps per dollar, fewer duplicate shifts. *First step:*
render the packet for one project and diff it against what its shifts actually read.

**24. Load 3 to 5 tool definitions, not 95.** Defer the rest behind a tool search. *Why:* the six MCP
families cost 87,777 characters of schema — about 21,944 tokens — on every request that sees them, and
behaviour degrades past 30 to 50 tools in context. *Effort* S-M. *Gain:* 10-25% of the prefix, and a
smaller decision space for the model. *First step:* measure tool-definition tokens per shift today.

**25. Structured tool returns.** Every tool returns status, ids, paths, counts and a digest, with the full
output written to a file. *Why:* tool results dominate how context grows, and a shift's raw output is
routinely a megabyte. *Effort* M. *Gain:* 30-60% of context growth removed. *First step:* rank the top ten
tools by bytes returned across a hundred shifts.

**26. Effort routing plus a clock.** Cheap effort by default, re-run only failures at high effort, and
inject elapsed time with a hard stop that leaves a partial record. *Why:* measured equal pass rate at about
half the cost, and 33-69% less wall time. *Effort* S. *Gain:* 20-50% of cost on mechanical work. *First
step:* run twenty items at low effort and compare verified pass rate and spend against the default.

**27. Cache and cost telemetry per shift.** Log cache-read share, write tokens, output tokens and cost per
shift, and alert when the cache-read share drops below 80%. *Why:* cache share is the diagnostic that
tells you the prefix broke; today the dispatcher logs that the harness reports no cost at all. *Effort* S.
*Gain:* protects items 22 and 23 and makes spend attributable per item. *First step:* emit the usage fields
into the ledger on every shift.

**28. Resolve the model at runtime, and delete the literal id.** `~/.dsh/settings.yaml` names
`deepseek-flash` as the agent default, which is what every headless shift boots with. *Why:* this is the
documented time bomb that already broke the personality system for over a week behind a plausible-looking
fallback; the gateway at port 8002 answered 200 today with route aliases available. *Effort* S. *Gain:*
a model swap stops being a code change and an outage stops being silent. *First step:* point the headless
profile at a route alias and log which model actually served each shift.

**29. One reconciled budget.** The harness guard (warn 35, fanout 80, ceiling 150) and the wake ceiling
(70/day) are two different numbers for the same money, and neither is visible in one place. *Why:* a cap
that reads a different measurement than the thing it caps is how this system has failed before. *Effort* S.
*Gain:* one number you can trust, and a ceiling that fails closed. *First step:* publish both in one line
of the daily digest and reconcile them.

**30. Meter value, not activity.** Report verified items per day and cost per verified item next to
releases per day. *Why:* `wake.py stats` already warns that releases are sessions started, not work done —
133 releases over 41 distinct ids on 2026-09-29 — and today 32 releases produced 0.61 USD of spend whose
value is only visible in the ledger. *Effort* S. *Gain:* the reading you actually care about, and the only
way to tell whether any of the above worked. *First step:* one line in the digest: items closed with a
proof, and dollars per closed item.

## E. Capability — make the fleet and the session stronger

**31. Give headless workers a browse path, and drop the two dead MCP families.** Headless children get no
MCP tools at all — no firecrawl, no jina, no playwright, no `ps_*` — while `fetch` and `context7` cost
2,196 tokens per request for 5 and 1 uses in 1,611 sessions. *Why:* a fleet that cannot scrape, cannot
drive a logged-in browser and cannot query the company database is doing half the job blind. *Effort* M.
*Gain:* children become real researchers; every request gets cheaper. *First step:* disable the two dead
families and prove the token drop, then define a headless profile that carries search and `ps_*`.

## F. Self-improvement — the half that compounds

The research pass on this found the important thing, and it is not flattering: **the reason improvements
piled up is an enforcement failure, not a learning failure.** Writing a lesson is cheap and closing one is
not, and the literature on self-admitted technical debt shows the same collapse — prose does not enforce
itself. Everything below is mechanical for that reason.

**32. Every incident must produce one executable check.** A pain entry cannot close without a proving
command, and a job scaffolds the failing check. *Why:* the measured baseline is that 3.4% of removals in the
technical-debt study added a targeted test, and this tree has 304 open pain entries. *Effort* M. *Gain:*
recurrence stops being re-discovered; the metric is incidents with a passing reproducer within 48 hours,
and the recurrence rate. *First step:* make `proof_command` a required field and reject entries without one.

**33. A proposal backlog with a work-in-progress cap, an expiry, and a failing metric.** A `proposals`
table with owner, state and `expires_at`, one nightly job that applies at most one, and a **non-zero exit
when more than five are open or the oldest passes 21 days.** *Why:* 55 improvements accumulated because
nothing failed when the list grew. *Effort* S. *Gain:* the class becomes bounded and visible. *First step:*
create the table and add the count gate to the nightly job.

**34. An outcome table per unit of work, reported as pass^k.** One row per item with exit code, proof
command and proof result; the weekly report repeats identical tasks and reports pass^4 to pass^8, not a
single success rate. *Why:* single-run success rates lie — the reference benchmark shows pass^8 under 25%
for agents that look much better on one attempt — and a rising success rate with a flat pass^k is the
signature of automation gaming its own task. *Effort* S-M. *Gain:* a fitness signal that is not an
opinion. *First step:* add the two columns and backfill one project.

**35. A frozen fitness set, and keep-only-on-a-win.** 20 to 40 already-solved tasks with deterministic
proof commands; every prompt or config change is scored before and after and reverted unless it wins with
no regression. *Why:* this is the affordable core of the self-modification research — the parts that need a
GPU or an expensive benchmark are not transferable, but "never keep a change that did not beat a fixed
task set" is. *Effort* M. *Gain:* stops silent regressions shipped as improvements. *First step:* pick 20
historical tasks and record their current pass or fail.

**36. A guard registry checked by a different process.** A short list of the guards that matter with their
check commands, a separate checker that exits non-zero when one is missing or failing, and an owner
approval record required for any change that touches a guard. *Why:* the failure mode to design against is
a self-modification that silently disables a safety check — the published evidence is that agents attempt
exactly that — and a guard checked by the same process that could disable it is not a guard. *Effort* S.
*Gain:* makes the one unthinkable failure detectable. *First step:* write the three most important guards
in, with their commands.

**37. Retry only against a verifier.** One reflect-and-retry cycle is allowed only where a compiler, test
or database check can tell you it failed, and the verifier's output is fed back. *Why:* the evidence is
direct — self-correction without external feedback can make things worse, and the gains attributed to
reflection came from tasks with reliable external feedback. *Effort* S. *Gain:* fewer wasted retries and a
higher fix rate on checked work. *First step:* one rule in the shift contract: retry only if a verifier
failed.

**38. A change budget, a canary, and a rehearsed rollback.** Three changes a week, one config path made a
file with a canary flag, a pinned previous version, and a rollback that has been run in dry-run. *Why:*
mean time to recover, not change volume, is what makes an autonomous system trustworthy over a long
horizon. *Effort* S. *Gain:* a bad change costs minutes. *First step:* convert one hardcoded path to a file
plus one rollback script.

**What NOT to adopt, and I would hold this line.** Evolutionary self-modification of our own code
(Darwin-Gödel-Machine and AlphaEvolve style), weight-level self-adaptation, intrinsic self-critique loops
with no verifier, LLM-as-judge as the primary gate, and — most importantly — **a nightly session that
reads the entire journal and "improves itself".** That last one is the most expensive way to learn the
least: 2,800 entries as one context is exactly the configuration the curation research shows collapsing.
And no mechanism that lets the agent weaken, disable or self-approve a change to its own guards.

---

## The order I would do them in

**Today, in one sitting (small, reversible, high return):** 4, 5, 7, 9, 10, 28, 31. Together these give the
queue a clock, make stalls visible, stop the evidence deletion, and delete the hardcoded model — all with
no architectural change.

**This week (the ones that change what the system *is*):** 1, 2, 3, 8, 11, 30. Local execution, results that
cannot be lost, a dead-man switch, and a value reading.

**Then the compounding half:** 18, 19, 20, 15, 16 — supply from the machine's own backlog, integration as a
scheduled role, and a per-shift record worth reading.

**Then the efficiency half:** 22, 23, 24, 25, 26, 27 — the measured 30-60% input-cost reductions and the
tenfold context cut.

**Then the half that makes it get better on its own:** 32, 33, 34, 35, 36, 37, 38 — all mechanical, none of
them needing a model to rewrite itself.

**And exactly one item needs you:** item 6, the merge authorization. Everything else is mine.
