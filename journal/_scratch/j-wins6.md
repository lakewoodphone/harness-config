**The repetition guard failed sessions for working, and my own audit metric was wrong about why**

Two corrections first, because both were mine.

**Correction 1 — "386/386 failed sessions executed no action" was a measurement artifact.**
`execute_actions` results are appended to `proactive_actions`, which is the *tick's* notes, and
never to the session's own `output_log`. My classifier searched `output_log` for `"Work action "`
and therefore could not have found one whatever the truth was. The finding was an artifact of where
I looked, not a property of the system. It is now fixed at the source: a step that executes actions
writes `[ACTIONS: n (names)]` into the session's own log, so the question is answerable from the
record. That is the second half of the change below, and it exists because of this error.

**Correction 2 — the classification ruled out two of my three P73 hypotheses.** Over the newest 400
sessions (since 2026-09-07), **96.5% failed** (386 of 400), and the failures are spread evenly:

| by task shape | sessions | failed |
|---|---|---|
| monitor_check | 191 | 95.8% |
| fix_or_build | 65 | 98.5% |
| investigate | 22 | 100% |
| close_or_triage | 12 | 100% |
| initiative | 5 | 100% |
| unshaped | 115 | 95.7% |

| by target | sessions | failed |
|---|---|---|
| local_repo | 400 | 96.5% |
| home_assistant | 74 | 98.6% |
| ci_pr_github | 35 | 100% |
| browser_or_web | 21 | 100% |

So hypothesis **(1) "the goals do not fit the budget"** and hypothesis **(2) "the work is not
reachable from this host"** are both **out**. If it were the goal shape, initiative-sized tasks would
fail worse than concrete ones; they do not (5/5 vs 65/65 — everything fails). If it were
reachability, HA tasks would fail worse than local ones; they do not (98.6% vs 96.5%). The cause is
in the loop for essentially every task, which is what hypothesis (3) predicted and what the
measurement now supports — but the *specific* defect had to be found, not assumed.

**The defect: the repetition guard could not tell "doing nothing twice" from "working twice".**
Session **75335** (started 16:03:17, *after* my earlier fix) was closed as
`stalled_repeating_output` after three steps reading:

    I'll work on Task #24966: reconciling the 1 in_progress task that's stale >48h.
    Let me identify which task is stale by listing tasks.

That is the phrasing of an agent **calling `list_tasks`**. The guard compared only the model's prose
and knew nothing about whether the step had executed anything, so it counted a working step toward
the stall threshold and failed the session. `_text_similarity` on those two real texts is **> 0.85**,
which is exactly why it fired. The fix is one condition — `and not actions` — so a step that executed
an action cannot accumulate toward the stall.

**Verified.** 24 tests pass on the authority's own tree (8 new, using the verbatim production step
texts to pin both the hazard and the fix), compile gate green, `/health` 200, and both `and not
actions` and the `[ACTIONS: ` marker confirmed present in the running file. Deploy recorded at
16:09:51Z; backup at `.runtime/deploy-backups/handport-repetition-guard.py.pre`.

**What is NOT yet established, stated plainly.** This is a plausible and evidence-backed defect, not
a proven cure. The next reading is whether `[STALLED_REPEATING_OUTPUT]` stops appearing **and**
sessions start completing — and the new `[ACTIONS: n]` marker will finally answer whether work is
happening at all, which I could not have known before this change. If stalls vanish and sessions
still fail, the guard was a symptom too, and the next suspect is that the model narrates because the
task is not actionable with the tools it has. Nothing before the next few dozen sessions settles it.

**Also newly visible and worth someone's attention:** 400 sessions in seven days with a 3.5%
completion rate is not a tuning problem. Whatever the remaining loop defect is, the company has been
spending real tokens daily on work that almost never lands, and that is the thing the owner's money
is going into.
