# ROUND 6 HANDOFF — the delta, and the one thing to do next

**Written 2026-10-15 15:0xZ on ZABZ-YOGA.** Read `docs/dsh-evolution-v4/HANDOFF-ROUND4.md` first — it is
still the spine — then `HANDOFF-ROUND5.md`, then this. This file is only what round 6 changed and
what it now hands over.

> **The documents are now reachable from every node.** `docs/dsh-evolution-v4/` and
> `docs/dsh-evolution-v6/` are committed into the **authority's** checkout (`secratary-cloud:
> /root/code/harness-config`, commit `9408281d`). Rounds 4/5 lived only on a yoga branch and three
> children this round reported them as non-existent — that is the "a rule in one surface is not a
> rule" defect (`AGENTS.md` §6.3) applied to the documents themselves, and it is fixed.

---

## 1. WHAT ROUND 6 DELIVERED, each with its command

| # | what | the command that settles it | verdict |
|---|---|---|---|
| 1 | **The instruction surface reaches all three machines** — the owner's #1 ask, which had been one machine of three | `dsh --profile web --dump-config` on each, asserting four v6 markers present and two compressed-away markers absent | **CURRENT on ZABZ-YOGA, ZABZ-TECH and `secratary-cloud`** |
| 2 | **The surface is ten numbered, checkable rules** | `scripts/make_zabz_preset.py --check` | exit 0 on all three; commits `9344060e` (yoga), `6b9a00d0` (tech), `9408281d` (cloud) |
| 3 | **The authority's `brokerSsh` no longer defaults to the FROZEN office box** | `--dump-config \| grep brokerSsh` on the authority | `?? 'secratary-cloud'` (was `'secratary-ts'`) |
| 4 | **The authority can run the row generator at all** | `node scripts/make-preset-rows.mjs --check` on the authority | ran and reported real DRIFT; before, it threw `cannot resolve a usable "yaml" package` |
| 5 | **A tool to do this again** | `python scripts/evolution/deliver-persona.py --repo <path>` | 6 steps, prints evidence, exit 0/1/3 |
| 6 | **The round's documents are on the machine that runs the company** | `ls /root/code/harness-config/docs/dsh-evolution-v6/` | 6 files + `PROGRAM.md` |
| 7 | **TWO company fixes are DEPLOYED and verified, and the first is PROVEN by observed sessions.** (a) a retry now inherits an attempt that ended `paused`; (b) `left=` can no longer quote a stale `[OUT-OF-TURNS]` tick for a session that closed | `systemctl show company-api -p ExecMainStartTimestamp` | **(a) 00:25:19 → 14:41:46 UTC**, **(b) 14:52:41 → 14:53:59 UTC**; `/health` `{"ok":true}`; running interpreter reports `PRIOR_ATTEMPT_STATUSES = ('failed','expired','paused')`; `/opt/company` commit **`2dc5c89d4`** + the marker fix |
| 7a | **the observed proof for (a)** | one row per session created after the deploy | **78869, 78870, 78871 — all `prev_status=paused`, all carried `attempt-context`, none said "no prior attempt"**; and over 2 h: `paused` predecessors 5 sessions / 5 carried context / 1 said no-prior (session **78861, 13:31:12, pre-deploy**), `failed` 3/3, no predecessor 6/6 (correct) |
| 7b | **the observed proof for (b)** | the live module, called directly | `[COMPLETED: …]` and `[TASK-CLOSED-BY-SESSION: …]` now return their own marker; an empty marker still quotes the trace's (correct); regex alternatives **16 → 18** |
| 7c | **REVERTED, with the measurement that refuted it:** `paused` is no longer a strike toward the give-up ceiling | `systemctl show company-api -p ExecMainStartTimestamp` and the running source | **14:53:59 → 15:13:48 UTC**; the running predicate is `status = 'failed'` only, occurrences of `status IN ('failed', 'paused')` in `database.py`: **0**; `/opt/company` commit **`ca9248eef`**. The retry-context half is KEPT and verified in the running interpreter: `PRIOR_ATTEMPT_STATUSES = ('failed', 'expired', 'paused')` |
| 7d | **A repo that is not present on this host is now non-fatal** — it is neither retried into `TOOL_LOOP_DEADLOCK` nor counted toward the action's circuit breaker | the running interpreter's own predicate, on the real messages | **15:13:48 → 15:22:18 UTC**; `/health` `{"ok":true}`; `_should_retry_action_failure("repo_map", …)` returns **False** for all three resolver messages and **True** for a `Connection reset` control; `/opt/company` commit **`d43a75a37`** |
| 8 | **The whole live `app/` tree is now inside a commit.** 28 modified files of production code were in NO commit today — the round-4 disease, four days after round 4 cured its own instance | `git -C /opt/company status --porcelain -- app \| grep -c '^ M'` | **0**; commit **`2f478ba0c`** on the unchanged branch `keepalive/156-dialpad-status-landing`; committed blobs byte-identical to live for `autopilot.py`, `database.py`, `attempt_context.py`; 38 `.bak-*` files left untracked on purpose |

**Journal entries written this round:** decisions `D3723` (delivered from the generator; the proof is
the composed config), lessons `L4577` (the repair step that reported a false clean), `L4578` (see the
correction below), pain `P4185` (sync.py's exit code; the authority's missing yaml), win `W3070`.
Since then: `L4579`, `L4768`, `L4832`, `L4834`, `L4836`, `P4251`, `W3134`, `W3135`, `W3136`, `W3137`.

### 1a. THE CENSUS IS NOT YET A CENSUS — 130 owner sessions were read by nobody

`owner-sessions.tsv` holds **1,149** owner sessions. The twenty-two shards name **1,034** distinct ids,
of which ~1,019 are owner sessions. So **130 of the owner's own sessions are named in NO reader shard** —
measured 2026-10-15. They are small (139 turns and 11.6 MB across all 130, about 1.07 turns each), which
is very likely *why* they were dropped: the reader brief instructs an empty friction list for one-turn
sessions, and a sample that filters on volume would drop exactly these. **But a one-turn session where
he asked for something and got nothing is a `want`, and wants are the point of this census.** Per
machine: `secratary` 44, `zabz-tech` 34, `zabz-yoga` 52. The id list is
`/root/work/r6/90-unread-owner-sessions.txt`; `R8-UNREAD` was dispatched to read all 130 into `R23+`.
**Item 1 of round 6's objective is therefore NOT complete until those shards land and the coverage
arithmetic is stated.**

### The closing verification, taken fresh on all three machines after every subsequent change

Run 2026-10-15 ~15:4xZ, AFTER the sync.py exit-code fix and every other change of this round. This is
the reading to trust over any earlier line in this file:

| machine | `make_zabz_preset.py --check` | `make-preset-rows.mjs --check` | `preset-drift.py` | the four v6 markers in `--dump-config` | the two old markers |
|---|---|---|---|---|---|
| ZABZ-YOGA | exit 0 — "zabz: in sync with the generator" | exit 0 — managed block UP TO DATE | `compared 17 match=17 drift=0` | **1, 1, 1, 1** | **0, 0** |
| ZABZ-TECH | exit 0 | exit 0 — UP TO DATE | `compared 15 match=15 drift=0` | **1, 1, 1, 1** | **0, 0** |
| `secratary-cloud` | exit 0 | exit 0 — UP TO DATE | `compared 14 match=14 drift=0` (1 divergent-in-repo, a tidiness note, not a failure) | **1, 1, 1, 1** | **0, 0** |

**So `L4578`'s worry is resolved in the other direction from how it was written**: the drift
comparison is green on all three machines once the generated rows are correct, which is further
evidence for the `L4579` correction. It was never red "by construction"; it was red because the rows
were genuinely one generation behind.

---

## 2. THE ONE THING TO DO NEXT, AND IT IS NOT AN ENGINEERING DETAIL

**The journal has forked into five trees, and 363 entry ids carry DIFFERENT BODIES in different
trees.** Measured 2026-10-15 by the R6-JOURNAL child, across yoga, the authority, ZABZ-TECH,
`zabz-tech-linux` and the mac mini: union 4,513 ids, only 1,643 in all five, **436 confined to one
tree, 363 ids carrying two (341) or three (22) different bodies.** `journal.py check` reports
**0 errors in all five**, because it has no cross-tree rule.

The worked example, read on both sides: `D3034` is *"the shop's money & customer tracking survives
long-term"* on yoga and the authority, and *"Weitman SD copy route"* on ZABZ-TECH. **A `resolve
D3034` on the authority would close the shop-money decision using evidence about an SD card, with no
error raised.**

This is the agent's ONLY memory, it is the thing the owner's second ask is about, and it is currently
unreliable in a way that is invisible from inside any one machine. **It is round 7's headline.** The
child correctly refused to write anything: converging five trees is a deliberate, backed-up, verified
merge, not a sweep. Read `docs/dsh-evolution-v6/50-journal-hygiene.md` before touching it.

Round 7's first three actions, in order:
1. **Decide the merge base** and write the decision down. The authority owns `owner_decision_queue`
   and `AGENTS.md` §5 makes it the sole writer, which makes its checkout the natural base — but the
   child flagged, correctly, that it has NOT verified `/root/code/harness-config` is the tree the
   authority's own sessions write to. **Confirm that first.**
2. **Reconcile the 363 collisions by reading both bodies**, never by taking the newer mtime. Take a
   full backup of all five trees before the first write.
3. **Then make every machine consume that tree**, and add the cross-tree check to `journal.py check`
   so this cannot happen silently again. A check that reports 0 errors on a forked store is the same
   defect class as everything else in this round.

### 2a. THE FORK ALREADY HAS A HALF-LANDED REPAIR — read this before any merge

**Found last, and it changes the shape of the job.** `git status` on ZABZ-TECH shows **239 untracked
entry files** under `journal/entries/` — `D3132.md`..`D3137.md`, `H3602.md`..`H3629.md`,
`L3774.md`..`L3815.md`, `P3169.md`, `P3798.md`..`P3803.md` — sitting in exactly the id neighbourhoods
where ZABZ-TECH holds a different body from yoga and the authority.

They are the output of **item 163, a cross-machine duplicate-id repair performed on 2026-10-11** and
recorded in `docs/mesh/163-journal-repair-crossmachine-ids.md` (20,820 B, untracked, on ZABZ-TECH)
with its id mapping in `163-repair-manifest.json` (42,741 B) and its own verifier
(`163-verify.py`). **It was never committed and never propagated**, so today it reads as a fork.

So ZABZ-TECH is **not a stale copy — it holds a partially-landed repair**, and the 210 collisions
where it is the odd tree out are most likely the *unlanded residue* of that repair. Consequences:

* **Do not "correct" ZABZ-TECH toward yoga for those ids.** The safe resolution is the lossless one:
  keep every distinct body in the union and let `journal.py dedupe` / `repair-ids` renumber the
  losers, which reproduces 163's intent mechanically instead of re-deciding it by hand.
* **The repair is a landable artefact, not a mess to clean.** Whatever the union concludes, 163's
  own record and manifest must be read first, and the merged tree must be shown to have preserved
  its renumbering — with a command, not a claim.
* This is the fourth time this round that a document describing work already done sat unread while a
  session was about to redo it. **`git status` on the machine that owns the work is a cheaper first
  step than any analysis.**

### 2b. THE CANDIDATE UNION EXISTS, AND IT HAS ONE REAL DEFECT — measured, after four false alarms of my own

`R7-JOURNAL-MERGE` delivered a candidate at **`secratary-cloud:/root/work/r7/merged-journal`**:
**4,887 files, 4,887 ids, `check` 0 errors, 0 malformed, 0 CRLF, 0 in-file id/name mismatches**, built
from 17,387 files across the five trees. Report: `/root/work/r6/80-journal-merge.md` (697 lines).
**Nothing was switched over.**

**The acceptance test in this file's earlier §2 was wrong and the builder was right to refuse it.**
"Residual collisions must be 0" is structurally impossible — an id holds one body, so the losers are
renamed and the number of ids that *used to* carry more than one body does not change. The test that
answers the real question compares BODIES: `scripts/evolution/r7-verify-body-loss.py`.

**It took me four attempts to write that test, and every earlier version produced a false alarm** —
which is the round's own subject, so it is recorded rather than smoothed:

| version | what it compared | it reported | what was actually wrong |
|---|---|---|---|
| whole-file sha256 | file bytes | **403 lost / 377 invented** | the header line carries the id, so a renumber changes the bytes |
| + strip header and metadata | body, file's own id normalised | 270 / 250 | entry bodies carry their id in the *heading* too |
| + normalise every id token | body | 11 / 4 | the merge renames into `<ID>b.md`, so the stem is not the id; and renumbered entries cite *other* ids |
| + collapse whitespace, live entries only | body | **7 / 0** | the last 7 are real, and they are in `archive/duplicates/` |

**`0 invented` is the load-bearing number**: every body in the candidate has a source. No content was
fabricated and none was deleted.

**THE ONE REAL DEFECT.** Seven bodies that are LIVE in at least one source tree end up in the candidate
under **`archive/duplicates/`** rather than renumbered to fresh live ids — so they would leave the live
view (`list`, `search`, `status`) at switchover. Verified by direct comparison, not by inference:

| id | live body in the source | what the candidate keeps LIVE under that id | where the source body went |
|---|---|---|---|
| `H2729` | `mac` — "Daily note from LakewooechsMini", 344 chars | yoga's "Queue walk: Golembick's recovery…", 7,087 chars | `archive/duplicates/handoff/H2729.md` — body identical to the source |
| `L3767` | `cloud`+`yoga` — "A whole-file comparison and a change-comparison…", 168 chars | yoga's "A mis-pointed Core Data object-id allocator…", 2,653 chars | `archive/duplicates/lessons/L3767.md` — body identical to the source |

Same pattern for `H2781`, `H458`, `H514`, `P2561bc`, `H3401`. **This is exactly what the builder
warned about in its §4.2**: `dedupe`'s `archive/duplicates/<id>.md` write has no collision-avoidance
loop, unlike `repair-ids`. Nothing is lost from the disk — but "the union keeps every body" and "the
union keeps every body LIVE" are different sentences and only the first is true.

**THE SEVEN ARE FIXED, AND THE UNION NOW PASSES ITS ACCEPTANCE TEST** (2026-10-15 ~15:1xZ):

| the seven | restored as live | how it was done |
|---|---|---|
| `H2729`, `H3401`, `H2781`, `H458`, `H514` | **`H4933`–`H4937`** | `scripts/evolution/r7-restore-archived.py` |
| `P2561bc` | **`P5139`** | same, plus the two entries whose bodies carry their own id had their metadata `sha=` refreshed |
| `L3767` | **`L5066`** | same |

```
BODIES MISSING from merged : 0
BODIES INVENTED in merged  : 0
VERDICT: NO BODY LOST
```
**4,894 distinct source bodies = 4,894 merged files = 4,894 merged bodies**, `check` **0 errors** on
4,894 entries, and the restore tool is **idempotent** — re-running it reports "already live, skipped"
for all seven and writes nothing (file count before 4894, after 4894). Every source tree is untouched;
**nothing has been switched over.**

`r7-restore-archived.py` copies the archived body to a fresh live id rather than moving it, so the
`archive/duplicates/` copies stay exactly where `dedupe` put them. Two things it had to learn the hard
way and now does: it guards on **whether the body is already live** (not on whether the new id exists,
which is no guard at all and would have created a second copy on every run), and an entry whose body
carries its own id needs its `sha=` metadata refreshed or `check` turns the edit into an ERROR — the
trap `journal.py`'s own comment at line 2697 already names.

**So the journal's remaining work is the SWITCHOVER, and it is a decision, not a script:** pin ONE
`journal.py` (the five trees ship **four different versions** — yoga `47fbf32b`, cloud `f6a7a014`,
tech=linux `87737e66`, mac `9b0e020b`), decide where the single tree lives and who may write to it,
retire the other four **without deleting them**, add the cross-tree rule to `check`, and re-run
`r7-verify-body-loss.py` after the switch to prove the union survived it. `verify.py` cannot run from
the candidate's own directory (it derives the v1 parser from its path); run it through a symlink or
from a checkout.


---

## 3. WHAT IS OPEN, IN THE ORDER I WOULD DO IT

1. **The journal fork** (§2).
2. **The owner queue holds 101 engineering faults.** Of 127 pending rows the child classified
   **26 as genuinely his and 101 as ours**. Bring him the 26; solve or close the 101. This is the
   measured failure the owners' own words describe (*"you are being annoying"*), at scale.
3. **The company improved on the round-4 headline, by the matched comparison that round 4 could not
   run.** `R6-COMPANY` matched the **18 h before vs 18 h after** the 2026-10-14T20:16Z deploy:
   **117 sessions / 45 completed / 47 failed (38.5 %) → 113 / 62 / 31 (54.9 %)**, at
   **$0.6253 → $0.4172 per completed session (−33 %) on 8 % less spend**, with
   `TASK-CLOSED-BY-SESSION` 45 → 62 and `STALLED_REPEATING_OUTPUT` 12 → 0. **n = 113 ≥ 50, so
   `PROGRAM.md` §8's abandon condition is now decidable and the answer is: the convergence change
   moved the number.** The 7-day rows agree in direction: 29.9 % → 35.3 % completed.
   **But `STEP_BUDGET_EXHAUSTED` is 322 in 7 days and `TOOL_LOOP_DEADLOCK` is a REGRESSION
   (38 → 55 matched, 133 of 486 seven-day failures) — the second-largest failure class.** So: the
   deploy worked, and two named classes are still open. Measure before building (§8 still applies).
4. **The mechanism behind the biggest friction is now known, and it is two settings.**
   `dsh-tool-pwsh/lib/index.js:133-136`: a non-zero exit **is not an error** — the result appends a
   string, `isError` stays false, and the loop moves on. And the preset's tool-result pruner
   (5000/2500/700 chars, engine default 8192/4096/1024) **replaces the middle of a long result**,
   which is usually where the error text sits. That is `tool-failure`, 302 sessions, 30 %, the
   most-tagged friction in the corpus. Full evidence: `30-friction-evidence.md`.
5. **`sync.py` still exits 0 while skipping a step** (`return max(plugin_status, sampler_status)`;
   the presets/profiles skips and the `verify_loaded_surface` verdict never reach the exit code).
   `P4185`.
6. **25 owner-want clusters are classified and verified** — `20-owner-wants.md`, 212 wants assigned,
   2 in an honest tail, every cluster carrying a verdict and the command behind it. Read it, then
   pick the ones that are still open and build them.
7. **`presets/yocheved/agent.cordis.yml` differs across machines** (37,606 B on yoga vs 33,498 B on
   the authority) and all copies name the frozen box three times. Filed, not fixed — it is a
   different agent's lineage and I did not review its content differences.
8. **A restart is needed for a RUNNING engine to load the v6 surface.** The composed config is
   verified on all three; round 5 measured that the engine holds the persona it booted with, and I
   have not disproved that. New engines are correct. **Nothing should be restarted from inside a
   live session without the owner knowing**, and the authority's `dsh web` on `:3089` is the one that
   matters most.
9. **`R6-COMPANY` and `R6-RECENT` are DONE** (their artefacts are in `docs/dsh-evolution-v6/`, and
   `40-company-baseline.md` is the one that carries the matched pre/post numbers). **`R7-JOURNAL-MERGE`
   was still running at handover** — it is building the five-tree union as a *candidate* at
   `/root/work/r7/merged-journal/`, with its report expected at `/root/work/r6/80-journal-merge.md`
   and the merged manifest at `/root/work/r6/80-journal-manifest-merged.tsv`. **Read those before
   starting the merge yourself**; if they are absent, the child did not land and the job is still to do.
   It was dispatched before §2a was found, so **check its output against item 163** (see §2a) rather
   than trusting it: it may have taken yoga's body for the ids where ZABZ-TECH holds 163's renumbering.
10. **The behavioural proof for the first company fix is CLOSED** — see §1 rows 7a and 7b. It was
   outstanding when this file was first written and is now an observed row: three sessions created
   after the deploy, all with a `paused` predecessor, all carrying the prior attempt, none saying
   "no prior attempt". **And the give-up half of that same change was measured, found wrong, and
   REVERTED** (§1 row 7c): of 13 tasks that paused 3+ times in 30 days, **5 went on to complete**,
   against 9 of 482 for `failed`; task **28625** paused six consecutive times, failed once, then
   completed, and the amended ceiling would have refused it at the third pause.

10a. **`TOOL_LOOP_DEADLOCK` IS ROOT-CAUSED, measured 2026-10-15 — it is a repo that is not on the
   machine, and the error message sends the agent the wrong way.** Of **176** sessions in 7 days
   carrying the marker, **36** name an action that is `temporarily disabled` and **28** name
   `file not found`. Read in full, session **78859** shows the mechanism: the agent calls
   `repo_map`/`repo_read_file` with a `repo_path` that does not exist **on the authority**, the
   action is circuit-broken after 10 consecutive failures, and the session then spends its entire
   step budget re-announcing intent —

   > Step 5: I'll stop probing repo_map entirely and take the mutating action… Step 12: I'll stop
   > re-probing and take the mutating action now… **thirteen consecutive steps, none of them an
   > action.**

   **The instruction the agent is given is wrong for this case.** `chat_action_resilience.py:305`
   tells it `FIX: Use repo_path alias (e.g. personal-secretary, phone-and-tech)`, and on the
   authority an alias resolves through `resolve_managed_repo_path` (`chat_action_repos.py:92`) to
   the blueprint's **canonical Windows path**, then to `~/repos/<repo>` — and neither exists. **The
   real instruction is the resolver's own `hint`**, which the agent never sees: *use github_\* tools,
   or bootstrap a clone with `scripts/repo-bootstrap.sh <repo>`*. So the estate tells the agent to
   change the argument when the argument is not the problem, and the agent complies, forever.

   **The bounded fix, for the next session:** when `resolve_managed_repo_path` returns
   `exists=False`, that failure is TERMINAL FOR THE SESSION — no alias, no retry and no argument
   change can make it succeed — so surface its `hint` on the FIRST failure, mark the action
   non-retryable, and stop the identical-failure counter from spending three strikes on it. That
   turns 36 seven-day failures into 36 sessions that get told what to do instead.
   **Also worth fixing while there:** `ps_circuit_breakers`, the CEO's own way to see breaker state,
   errors on call — `no such column: action_name`; the real schema is
   `circuit_breaker_events(agent_id, event_type, reason, spend_at_event, created_at)`.

   **FIXED 2026-10-15 15:22:18Z — commit `d43a75a37`, `/opt/company` HEAD.** It turned out to be a
   DATA change rather than a logic change, because `_NON_FATAL_CB_FAILURE_PATTERNS` already drives
   BOTH predicates: adding the three messages `resolve_managed_repo_path` actually emits to the five
   `repo_*` pattern tuples is the whole fix. Proven against the running interpreter, not argued —
   `_should_retry_action_failure("repo_map", …)` now returns **False** for *"Path does not exist on
   this host: …"*, *"Repo 'x' has no local checkout on this host"* and *"Repo not available locally
   for 'repo_map'"*, and still **True** for a `Connection reset by peer` control. `r7-nonfatal`
   script: `scripts/evolution/r7-deadlock-nonfatal.py`.
   **WHAT IS NOT YET PROVEN, and must be read before this is called a win:** the *field* effect. The
   predicate is proven; a fall in `TOOL_LOOP_DEADLOCK` sessions is not, and cannot be until sessions
   run against the new code. **Read the honest reading as of 2026-10-15T15:25Z: deadlock sessions
   since the fix = 0, sessions of any kind since the fix = 0.** Zero of zero is "nothing has run",
   not "the fix worked". **Post-check, one query, against the 176-in-7-days baseline:**
   `select count(*) from work_sessions where started_at >= '2026-10-15T15:22:18Z' and output_log like '%TOOL_LOOP_DEADLOCK%';`
   alongside `select count(*) from work_sessions where started_at >= '2026-10-15T15:22:18Z';`

   **AND THE SECOND HALF IS DONE TOO (commit `f8873de29`, restart 15:24:45Z).** The agent is no longer
   told to change an argument that cannot help: `_REPO_ABSENT_TAIL` now appends the permanent-condition
   advice to all five `repo_*` hints, proven by printing what the running interpreter returns —
   *"… Optional: depth=N, pattern=*.py **If the repo has no checkout on THIS host, do not change the
   argument again — call github_\* tools, or bootstrap a clone with scripts/repo-bootstrap.sh \<alias\>**"*.
   **Still not done, and smaller: `ps_circuit_breakers` itself**, the CEO's own way to read breaker
   state, errors on call (`no such column: action_name`).


---

## 4. THE TRAPS THIS ROUND PAID FOR — do not re-learn them

* **A machine's checkout can be self-consistently wrong.** Both stale machines answered
  `make_zabz_preset.py --check` → *"in sync with the generator"*, because their generator matched
  their preset and their preset matched their rows. **A green check proves the surface THAT CHECK
  KNOWS ABOUT is right, nothing more.** The only instrument that answered the real question was
  `dsh --profile web --dump-config`.
* **Ship the GENERATOR, not the artefact** (`D3723`). Regenerating from a shipped generator is what
  makes the result reproducible; copying the generated preset hides the next divergence.
* **`make_zabz_preset.py` refuses to regenerate when the committed preset holds text the generator
  does not.** That refusal is correct and it fired on the authority. **Read the paragraphs it lists
  before forcing** — they were the older generation's rules, which is why `--force-preset` was right
  there; the same flag would destroy a genuine hand edit.
* **A repair step's negative result is a claim** (`L4577`). My first `brokerSsh` regex matched
  nothing and the step printed *"nothing to repair"* while the frozen box was still the composed
  default. Print the evidence for the negative or do not report clean.
* **Windows nodes are PowerShell over ssh**; `df`, `head`, `grep`, `/c/...` and single-quoted
  heredocs do not exist there. Use `$remote = @'...'@` here-strings for remote commands, and
  `scp -O` to ZABZ-YOGA (plain `scp` gets `Connection closed`).
* **A directory listing of `/root` on the authority costs a fortune in context.** Ask for the file,
  not the directory (`ls /root` produced ~150 lines of `_lpt*_wt` scratch dirs and no value).
* **`scp` to a path whose parent directory does not exist fails with `dest open … No such file or
  directory`** — `mkdir -p` first.
* **Never `git add -A`** on this estate: other sessions commit to these repos concurrently. Every
  commit this round staged explicit paths.

---

## 5. WHAT I GOT WRONG THIS ROUND, so you can discount me correctly

1. **The `brokerSsh` regex false negative** (`L4577`) — reported clean while the defect was live.
2. **`L4578` is partly wrong, and this is the correction.** It says the drift instrument is "red by
   construction" because the live layer is a different kind of artefact. Measured again AFTER
   `sync.py` applied: `verify: loaded surface matches the repo (compared 17 match=17 drift=0)`. So
   the 146 KB composed form was **a transient state written by something I could not identify**, not
   a permanent property of the file. What IS reproducible: **`--dump-config` does not write the live
   layer** (tested twice — mtime and sha unchanged) and **`sync.py` does** (it creates
   `.bak-<stamp>` and writes `_norm(src)`). **What wrote the 146 KB form is unproven and is left
   open**, not guessed.
3. **I shipped the generator to ZABZ-TECH and the authority before checking that
   `make-preset-rows.mjs` could run there at all.** It could not, on the authority, for a missing
   `yaml` package — a standing defect that had been silently keeping the authority's generated rows
   stale. It should have been measured first.
4. **Two children reported the round-6 documents as non-existent** because I wrote them on the
   branch I happened to be standing on. A plan the workers cannot read is not a plan.
5. **The v6 surface grew the generator by 1,710 characters**, against the child's measured
   recommendation to pay ~4,000 for labelled tests. I folded the tests into the rule bodies as
   checkable clauses instead, which is why it is smaller — but that is a deviation from the brief's
   recommendation and it is recorded here rather than smoothed.
6. **I asserted "the persona had no rule for `env-hostile`"** — true — and in the same message wrote
   the rule while dispatching a child whose brief had to spell the shell contract out by hand. The
   evidence for the finding was my own brief.

**The through-line, again: every miss was a confident number I had not checked, and each was caught
by running something rather than thinking harder.**

7. **My brief to `R6-RECENT` was wrong and the child caught it.** I said every owner session since
   2026-10-13 was unread. **60 of the 86 in that window had already been read by R01–R19** — round 4's
   extraction ran to 2026-10-14T19:27Z, past its own stated cut — so **only 26 sessions were genuinely
   new**, and the true corpus total is **1,008 + 26 = 1,034**, not 1,094. The child measured it, said
   so, and refused to inherit the arithmetic. That is the behaviour the briefs ask for and it is the
   second time this round a child refuted its own premise.

8. **I called a deployed fix incomplete without opening the file.** `D3850` says the `_handoff_left`
   precedence site "is needed" and (B) shipped without it. The pre-image backup taken at deploy time
   already contains it (`grep -c "findall(terminal_marker"` → 1), so my deploy neither added it nor
   needed to. **I wrote that from a child's prose paragraph after checking its numbers** — a claim I
   did not earn, in the one round whose subject is exactly that. Corrected in `L4768`. The residual was
   real but for a different reason, and measuring it properly is what found the two missing completion
   markers and produced the second deploy (§1 row 7b).

---

## 6. THE COMPANY, MEASURED — `40-company-baseline.md`

Every number carries its SQL, its window and the UTC instant it was read. The three findings that
change what to do next:

1. **The `HANDOFF` marker is a mid-session tick, not the session's ending — the instrument is lying.**
   All **113 of 113** post-deploy handoffs say `proof=none` and `result=partial`, **including the 62
   that did write `[TASK-CLOSED-BY-SESSION:]`**; 95 of 113 quote `[OUT-OF-TURNS: … the session is
   still open]` as `left=`, and **61 of those ended `completed`**. The block is emitted from the
   `OUT-OF-TURNS` path (`autopilot.py:6092-6106`) and `_session_handoff_block` refuses a second one,
   so the real ending never gets one. **Round 4's flagship marker counts correctly and records
   nothing.** Also `[ARTEFACT:]` has **never been written** (0 rows all-time) and `[OUTBOUND:]` once.
2. **`paused` is invisible to the retry it most needs.** `PRIOR_ATTEMPT_STATUSES = ("failed",
   "expired")` at `attempt_context.py:79`; **`expired` has not occurred in 30 days (0 rows)**, so in
   practice the tuple is `("failed",)`. **13 field instances** of a session whose previous attempt
   ended `paused` opening with `attempt-context: no prior attempt on this task`. `paused` rows have
   `completed_at` NULL in **153/153** cases, and the give-up counter counts `status='failed'` only.
   Round 5 found half of this; the `completed_at` half is new. Worth **153 sessions / 30 d** — small,
   and one line to fix.
3. **`TOOL_LOOP_DEADLOCK` is the live regression** (38 → 55 matched). The guard reports
   `'repo_read_file' failed identically 3/3 times (file not found)` and the sessions escape by
   changing tool rather than behaviour.
4. **Do not trust the 7-day totals as a before/after.** 130 `error_log` rows all-time vs 3,322
   `database is locked` events in the journal for the same week is the shape of that trap; the
   matched 18 h window is the reading that counts.
5. **`model_usage.served_by` is empty** — 0 of 14,675 rows in 7 d, against round 4 listing "publishes
   which model served a request" as delivered. And `model_usage.session_id` is a 32-hex hash that is
   **never** a `work_sessions.id`, so **per-session cost attribution is impossible with this schema**;
   the cost figures above are company-wide.

## 7. THE NEWEST SESSIONS — `60-recent-census.md`, `readers/R20..R22.md`

86 owner sessions read out of 86 in the window (no sample; 816 no-preset mesh/wake sessions excluded
by rule and stated). Mergeability proved by running round 4's own `reader-census.py` over the new
shards: `files=3 records=86 unique=86 dupes=0 parse_problems=0`.

* **`wrong-data` has displaced `tool-failure` as the #1 friction** — 22.1 % of the window against
  11.5 % in the census — and `ignored-instruction` multiplied ×2.6 (5.3 % → 14.0 %), `safety` ×2.5,
  `bad-prioritisation` ×5.2. Every one of those is driven by the owner's own words. **This is the
  evidence that round 6's choice of which rules to write was the right one.**
* **`tool-failure`'s apparent collapse (30.0 % → 8.1 %) is a METHOD ARTEFACT and must not be read as
  improvement** — round 4's readers got a per-session failure-signal count and this run's transcript
  rendering gives none, so the id can only fire when a failure reaches conversation. **Re-measure it
  with the `failures.jsonl` pipeline before believing any fall.**
* **None of the 26 genuinely new sessions is severity 5**; the newer sessions are the owner re-issuing
  this command, hellos and stubs. **The mega-command is now five-for-five in one window.**

