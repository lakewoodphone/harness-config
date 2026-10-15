# 90 — What this setup NEEDS, and what it does NOT

**Round 6, 2026-10-15.** This is the owner's second ask made concrete: *"an entire refreshed system about
what's needed and what's not in this setup."* It is deliberately two lists, because a list of needs with
no list of things to stop doing is how an estate grows instruments nobody reads.

Every row carries what it rests on. Where round 6 did not fix something, the row says so and says why —
a register whose entries all read "fixed" would be a register that measured nothing.

---

## 1. The 20 measured frictions: what round 6 did, one row each

Counts are from the round-4 census (`CENSUS-v4.json`, 1,008 owner sessions read, 19 reader shards).
"Rule N" refers to the ten numbered rules now in `presets/zabz/agent.cordis.yml`, delivered to all three
machines on 2026-10-15 and verified per machine with `dsh --profile web --dump-config`.

| # | friction | sessions | what round 6 did | the reading that would show it moved |
|---|---|---:|---|---|
| 1 | `tool-failure` | 302 | **Rule 3.** Mechanism found and named: a non-zero exit sets no error flag (`dsh-tool-pwsh/lib/index.js:133-136`) and the preset's result pruner (5000/2500/700) replaces the middle of a long result, where the error text sits. **Not fixed at the engine level** — the rule changes what the agent does with the failure, not what the harness reports. | `989 of 1,093` was the surface's old figure and it disagrees 3× with the census; re-measure with the `failures.jsonl` pipeline, not by inheriting either number |
| 2 | `frustration` | 96 | folded into **rule 6**. Not independently fixable — it is a consequence. | mean severity by month over new shards; it should track `restart-agent` and `wrong-data`, not move alone |
| 3 | `wrong-data` | 116 | **Rule 1.** Also: a wrong figure *inside the surface itself* was found and deleted — see §4. | the register's own `07-pain-register-v4-check.py wrong-data 116` (exits 1 today, correct: it is open) |
| 4 | `restart-agent` | 73 | **Rule 6**, promoted to its own numbered rule. It previously lived inside the 1,661-character do-not-ask paragraph. | 46.6 % of these sessions ended without the work done; that share is the number to watch |
| 5 | `correction` | 132 | **Rule 1** (the old rule 7b, folded in with the checkable clause). | `correction` share of owner turns, computed the way the instruction audit computed 5.74 % |
| 6 | `repeated-work` | 102 | **Rule 7**, with the search named as a visible artefact ("say what you looked for"). | count of sessions containing a journal/handoff search before the first write |
| 7 | `slow` | 54 | **not addressed.** No mechanism isolated; the measured shell start-up and index costs are already corrected elsewhere and `slow` may now be a different thing. Filed. | wall-clock per session from the corpus's `step-timing.tsv` |
| 8 | `ignored-instruction` | 53 | **Rule 2 — new.** It had no rule despite having the second-highest mean severity (4.06) of any high-volume class. | the register's check for `ignored-instruction 53` |
| 9 | `no-verification` | 76 | **Rules 1 and 5** — rule 5 is new and is about writing the decision down at the moment it is made, which is what makes a claim checkable later. | share of sessions containing a command output line where a claim is made |
| 10 | `context-loss` | 56 | **Rule 8 — new.** It had no rule *in the right place*: the surface covered memory between sessions and said nothing about the pruner and the compaction summariser inside one. | sessions where a fact stated early is absent from the closing message |
| 11 | `stopped-early` | 37 | partly **rule 6**; the four permitted stops are now enumerated. | the register's check for `stopped-early 37` |
| 12 | `env-hostile` | 74 | **Rule 9 — new. This one had no rule anywhere**; the shell contract lived only inside the engine's tool description, which an agent reads only if it already suspects the problem. Round 6's own dispatch brief had to spell the rule out by hand for every child, which is the measurement that it was missing. | count of commands whose syntax belongs to the other shell — greppable in transcripts |
| 13 | `format-unreadable` | 40 | **Rule 10**, widened from the dollar-sign case to the artefact (rendering, walls of text, menus where a decision was wanted). | the money-rendering rule catches the `$` case; the rest needs a reading of owner replies |
| 14 | `safety` | 32 | **not addressed by a new rule** — `never destroy data` and the outbound-comms block already exist and are the longest-standing rules in the surface. Filed as covered. | the outbound block's own incident count |
| 15 | `non-answer` | 26 | **Rule 4** — one question, options laid out, recommendation marked, question last. | register check |
| 16 | `asked-badly` | 22 | **Rule 4.** | register check |
| 17 | `asked-unnecessarily` | 20 | **Rule 4**, and the 1,661-character ask paragraph it lived in is gone — the surface's longest text served the two rarest frictions. | register check |
| 18 | `invented-detail` | 19 | **Rule 1** ("if you cannot say where you read it, the answer is not verified"). | register check |
| 19 | `overcomplicated` | 25 | **Rules 4 and 10** ("no menu where a decision was wanted"). | register check |
| 20 | `bad-prioritisation` | 9 | **Rule 4.** | register check |

**The honest summary: round 6 wrote or rewrote a rule for fourteen of the twenty, named a mechanism for one
more, and filed the remaining five with the reason it did not.** The register's own check script still
exits 1 for all twenty, which is the correct reading — a rule is not a fix.

### The structural caveat that makes the right-hand column nearly unusable

**The register's verification commands recompute from the reader shards, and the shards only grow when
someone reads new sessions.** So `07-pain-register-v4-check.py <friction> <count>` cannot report movement
until the corpus grows. Round 6 added three shards (`readers/R20..R22`, 86 sessions, mergeable — proved by
running round 4's own `reader-census.py` over them: `files=3 records=86 unique=86 dupes=0
parse_problems=0`). **Until a round re-reads a comparable number of sessions, every "did it move" question
about these twenty is unanswerable.** That is the measurement gap to close next, and it is worth more than
another rule.

---

## 2. What this setup does NOT need — stop doing these

Each of these is live today, costs something, and has been measured as either unused or misleading.

| stop | the measurement that condemns it |
|---|---|
| **The tick self-grade** | 823 `complete` / 821 `productive` recorded against **485 failed work sessions** in the same 7 days — the same shape round 4 measured (901/904 vs 578) and round 3 before it. Three rounds have re-measured it. Rename the field to say "tick" and delete the instrument. |
| **The `[ARTEFACT:]` completion marker** | **0 rows, all time.** One of the three markers `_completion_evidence` looks for has never once been written. |
| **The `[OUTBOUND:]` marker** | Written once, ever. |
| **`expired` in `PRIOR_ATTEMPT_STATUSES`** | **0 rows in 30 days**, so the tuple is in practice `("failed",)` — a member that cannot fire and hides the one that should (`paused`). |
| **Re-reading the Copilot corpus** | Verified 2026-10-15: **1,608 sessions / 4,373 messages, window 2026-02-06 → 2026-09-18**, frozen because Copilot was retired. It was already read by an audit of **3,133 lines** (`/opt/company` commit `51e2d32da`, 8 files: `01-copilot-corpus-audit.md` 552 lines, `02-harness-and-gap-analysis.md` 805, `04-autonomous-system-postmortem.md` 343, `05-question-register.md` 465). Reading it a fourth time is the most expensive shape of repeated work this estate has. |
| **Comparing `$DSH_HOME/profiles/<n>/cordis.patch.yml` to the repo file byte-for-byte** | Round 5 added this to `preset-drift.py`; measured 2026-10-15 it is stable only while nothing else writes the live file, and one reading of it produced a generalisation that had to be corrected the same day (`L4578` → `L4579`). It reported DRIFT on a machine whose composed config was, by `--dump-config`, entirely correct. |
| **Five journal trees** | 4,527 ids, 364 of them carrying different bodies — see §3.1. |
| **A rule that lives in a YAML comment** | `AGENTS.md` §7 already says so and it keeps happening: the generator's own warning about hand edits is a comment that reaches no session. |

---

## 3. What this setup still needs, in the order I would do it

### 3.1 One journal, and a check that can see a fork — the headline
The journal has forked into five trees; **364 ids carry different bodies in different trees**, 449 ids are
confined to one tree, and `journal.py check` reports **0 errors in all five**. `D3034` means *"the shop's
money & customer tracking survives long-term"* on yoga and the authority and *"Weitman SD copy route"* on
ZABZ-TECH. This is the only memory an agent has and it is unreliable in a way that is invisible from
inside any one machine.

**`journal.py` already ships the intra-tree repair** — `dedupe` (exact-content duplicates), `repair-ids`
(an id colliding with different content), `pairs` (list them). What it has never had is the **cross-tree
union**, because it has never seen more than one tree. So the fix is a union plus a cross-tree rule, not a
new merger. Measured 2026-10-15: union 4,527 ids, **4,913 distinct bodies**, yoga the widest tree at 4,213
of 4,527, and **210 of the 364 collisions are ZABZ-TECH holding a different body for a contiguous run** —
`W2735..W2740`, `P2996..P3022`, `D3034..D3138`, `D3124..D3137`, `P3151..P3167`, `H3443..H3450`,
`L3504..L3506`, `H3565..H3625`, `L3668..L3692`, `L3730..L3775` — which makes the repair bounded, not
scattered. The remaining 122 need both bodies read. Full method: `50-journal-hygiene.md`.

### 3.2 Two company instruments that are currently lying
1. **The `[HANDOFF:]` block is written by the `OUT-OF-TURNS` path and records a mid-session tick**: 113/113
   say `proof=none`/`result=partial`, *including the 62 that did write `[TASK-CLOSED-BY-SESSION:]`*, and 61
   of the "still open" ones ended `completed`. Round 4's flagship marker counts correctly and records
   nothing.
2. **`paused` is invisible to its own retry**: `PRIOR_ATTEMPT_STATUSES` omits it, `completed_at` stays
   NULL for 153/153, and the give-up ceiling never advances. 13 field instances of a retry opening with
   `no prior attempt on this task`.

### 3.3 The company's two open failure classes
`STEP_BUDGET_EXHAUSTED` 322 in 7 days; `TOOL_LOOP_DEADLOCK` a **regression** (38 → 55 matched pre/post,
133 of 486 seven-day failures). Both now have their command; neither has a fix.

### 3.4 The owner queue, drained
127 pending rows: **26 genuinely his, 101 engineering faults.** The 101 are ours and the measured failure
this estate keeps repeating is sending them to him.

### 3.5 The 25 owner-want clusters
`20-owner-wants.md` — 212 wants assigned, every cluster carrying a verdict (`delivered` / `still open` /
`no longer wanted`) and the command behind it. Nothing has been built from it yet.

### 3.6 One gap round 6 found and did not close
The predecessor audit's **`05-question-register.md`** (465 lines, in `/opt/company` git history at
`51e2d32da`) has never been dispositioned against today's `owner_decision_queue`. That is the cheapest
test of the owner's *"make sure that you remember everything"*, and it is one command:
`git -C /opt/company show 51e2d32da:docs/secretary-replacement-audit/05-question-register.md`.

---

## 4. One correction that belongs in the record

The instruction surface itself carried a **3× wrong figure**: it stated `tool-failure` "appears in 989 of
1,093 owner sessions, 90.5 %", while the census records 302 of 1,008 sessions = **30.0 %** for the same
friction. Two different denominators were being compared as if they were the same. The paragraph carrying
90.5 % was removed on 2026-10-15 and rule 3 now states the census's number **with its denominator**.
This is `wrong-data` — the corpus's #1 measured failure — found inside the very text written to prevent it,
which is the point worth keeping.
