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

**Journal entries written this round:** decisions `D3723` (delivered from the generator; the proof is
the composed config), lessons `L4577` (the repair step that reported a false clean), `L4578` (see the
correction below), pain `P4185` (sync.py's exit code; the authority's missing yaml), win `W3070`.

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
9. **`R6-COMPANY` and `R6-RECENT` were still running when this file was written.** Their artefacts
   land in `secratary-cloud:/root/work/r6/` and `docs/dsh-evolution-v6/`. Read them before re-doing
   either.

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

