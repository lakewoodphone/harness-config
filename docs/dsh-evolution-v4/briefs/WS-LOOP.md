# BRIEF — WS-LOOP: a session that is reading forever must converge, and a session that ends must leave a handoff

You are one builder in a fleet of three. You own **one file** and a test file. Read this brief
completely before you write anything.

## 0. Where you are and what the tenant is

* **You must work on host `secratary-cloud`.** If your shell's `hostname` is not `secratary-cloud`,
  prefix every command with `ssh secratary-cloud '...'` (or `ssh secratary-cloud` then work in that
  shell). Report in your final message which host you actually ran on.
* **Repo root and branch:** `/root/work/r4-loop`, branch `r4/loop-convergence`, cut from
  `14ebb2322` (the live tree preservation commit). Verify with `git -C /root/work/r4-loop log -1 --format=%H`
  and put the hash you actually read in your report.
* **The tenant** is the autonomous "AI company" that runs this family's phone-repair business: a
  FastAPI service (`company-api`) with a 900-second autopilot tick that spawns "work sessions" —
  one LLM agent loop per task, ~140 attempts a day. `app/autopilot.py` is that loop.

## 1. Read-first list — do this before you design anything

1. `app/autopilot.py`, these functions only (use `grep -n` to locate, then `read`):
   `_maybe_extend_work_session_budget` (~line 3150), `_work_session_is_progressing` (~3406),
   `_work_session_information_gain`, `_action_name_is_read_only`, `_close_unfinished_work_session`,
   `_repeated_tool_call_tool`, and the step loop's tail where `_maybe_extend_work_session_budget`
   is called (`sed -n '5340,5420p'`).
2. `app/services/work_step_ledger.py` — what a "work step" is, and what `charge()` returns.
3. This brief's §2 measurements. Do not re-derive them; they cost a day to establish.

## 2. The measurement — why this task exists (do not re-derive, do cite)

Read-only on `/root/authority.db` (`sqlite3 -readonly`), 2026-10-14 19:26Z, corrected windows:

```
work_sessions 7d:  failed 578 · completed 259 · paused 33
failure markers 7d:  STEP_BUDGET_EXHAUSTED 389 · TOOL_LOOP_DEADLOCK 157 · STALLED_REPEATING_OUTPUT 49
completion mechanism, 2026-10-14:  TASK-CLOSED-BY-SESSION 44 · ARTEFACT 0 · OUTBOUND 1
completion mechanism, 10-04..10-13:  TASK-CLOSED-BY-SESSION 0 every day
```

Sampled over the last 24 h (78 failed sessions, JSON so multi-line `output_log` survives):

```
STEP_BUDGET_EXHAUSTED 53 · TOOL_LOOP_DEADLOCK 24 · STALLED_REPEATING_OUTPUT 15
steps_completed distribution: 5 -> 20 sessions, 20 -> 19 sessions, remainder scattered
the tool mix in the exhausted sessions is 4 distinct tools: repo_search, repo_list_dir,
repo_read_file, list_tasks — reconnaissance
```

The literal tail of a failing session (session 78750, which failed at 20/20):

```
[BUDGET-EXTENDED: 20 -> 23 steps. ...]
[STEP_BUDGET_EXHAUSTED: reached 20/20 work steps in 20 model turns ... 40 tool call(s)
 over 4 distinct tool(s): create_task, list_tasks, repo_list_dir, repo_search) without [WORK_DONE]]
```

And the model's own last two turns in that same session, verbatim from `output_log`:

```
Step 19: I'll stop reading and take the mutating action now: write the fix artifact into the repo,
         then close the task with it recorded.
[ACTIONS: 2 (repo_search, create_task)]
Step 20: I'll stop the read-loop and take the decisive mutating action: locate the seed
         definition, then write the fix artifact directly into the repo.
[ACTIONS: 2 (repo_search, repo_search)]
```

**That is the defect: the session announces it will stop reading and act, and then reads again.**
Nothing in the loop turns the model's stated intent into a requirement. It burns 20–30 steps of
reconnaissance, never writes, and is recorded as a failure — while the task it was given is real
work that simply never got done.

## 3. What to build

### 3a. A convergence requirement that fires on a read-storm (the core change)

The loop already knows whether a step was read-only (`_action_name_is_read_only`). Add a
**reconnaissance budget that forces a decision**:

* Count consecutive steps in which **every** action was read-only.
* **At `RECON_SOFT_LIMIT` (default 6) consecutive read-only steps**, inject a directive into the
  next prompt — the loop already has a precedent for this shape, the `[STALL-DIRECTIVE: ...]` the
  repetition guard appends (`grep -n "STALL-DIRECTIVE" app/autopilot.py`), and it persists it in
  `output_log`. Follow that precedent rather than inventing a new channel. The directive must be
  concrete and demand one of exactly three things: *(i)* name the file you will change and change
  it in the next step; *(ii)* close the session with the evidence you already have; *(iii)* state
  in one line the specific thing you cannot find and why.
* **At `RECON_HARD_LIMIT` (default 10) consecutive read-only steps**, stop extending the session
  budget and record the session as `blocked` with a marker that names the real reason, rather than
  as a generic failure. A `blocked` session is honest; a `STEP_BUDGET_EXHAUSTED` session looks like
  a loop bug and buries the truth.
* **Both limits must be module-level constants** next to `_WORK_MAX_STEPS`, and settable by env var
  (`ZABZ_RECON_SOFT_LIMIT`, `ZABZ_RECON_HARD_LIMIT`) so an operator can tune them without a code
  change. Default to the values above.

### 3b. A session that ends leaves a handoff, whatever else happens

`progress_checkpoints` holds **52,494 rows across 12,482 sessions** and nothing in the loop reads
it (measured; verify that claim yourself with
`grep -n "progress_checkpoints" -r app/ | head -20` and report what you find — if it IS read, say
so and adjust).

Add `_write_session_handoff(...)`, called on **every** terminal path (completed, failed, blocked,
budget-exhausted, stall-closed). It appends one block to `output_log`, in this exact shape, so a
later reader — human or agent — can resume without re-reading the trace:

```
[HANDOFF: did=<one line, what this session actually did> |
 proof=<the command, file+hash, or row that evidences it, or "none"> |
 result=<done|partial|blocked> |
 left=<what remains, concretely>]
```

The fields must be **derived from the session's own recorded trace** (the actions it took, the
files it touched, the markers it wrote) and **never invented**. When the trace supports nothing,
write `proof=none` and `result=partial` — an honest empty is required and is not a failure.

### 3c. Do not change the completion rule

`[WORK_DONE]` stays an intent; the evidence gate stays. Do not loosen it. This workstream is about
**convergence and honest reporting**, not about making failures count as successes. If you believe
the evidence gate itself is wrong, write that as a finding in your report — do not implement it.

## 4. Exclusive file scope

**You may edit:** `app/autopilot.py`, and you may add `tests/test_r4_loop_convergence.py`.
**You may not touch anything else.** Not `app/main.py`, not `app/services/*`, not `tick_quality.py`,
not any other test file, not any config, not `.gitignore`.
Other builders are editing `app/services/…` concurrently; a file outside your scope is a lost merge.

## 5. Test command — and the one that matters

```sh
cd /root/work/r4-loop
# NEVER bind a port, NEVER touch /root/authority.db. Use your own temp base dir.
python3 -m pytest tests/test_r4_loop_convergence.py -q --basetemp=/root/work/r4-loop/_pt_loop 2>&1 | tail -20
```

Your test must be a **regression test in the real sense**: it must **FAIL on the base commit
`14ebb2322` and PASS after your change**. Demonstrate both result lines in your report. A test that
passes with and without your change is not a regression test and will be rejected — this exact
failure was caught in round 3 and is the reason this line is here.

Build the test around the pure/static pieces you can drive without a live database or a live model
(the read-only classification, the consecutive-read counter, the handoff field derivation). If you
cannot test a piece without a model call, say so explicitly rather than writing a test that
asserts nothing.

Then the existing suite that touches this file:

```sh
python3 -m pytest tests/ -q -x --basetemp=/root/work/r4-loop/_pt_loop2 -k "budget or ledger or work_session" 2>&1 | tail -20
```

Report the exact tail. A pre-existing failure is not yours — say which failures existed on the base
commit (`git stash -u` is FORBIDDEN; instead run the same command in `/root/work/r4-preserve` and
compare).

## 6. Git rules — absolute

* Commit to `r4/loop-convergence` only. **Never push. Never touch `master`/`main`.**
* **Never** `git add -A`, `git add .`, `git reset --hard`, `git checkout .`, `git clean`, or any
  delete. Stage **explicit paths**: `git add -- app/autopilot.py tests/test_r4_loop_convergence.py`.
* Do not create worktrees, do not merge, do not rebase.
* Commit with a message that says what changed and why, and the test result lines.

## 7. Definition of done — commands, not adjectives

1. `grep -c "RECON_SOFT_LIMIT\|RECON_HARD_LIMIT" app/autopilot.py` → non-zero.
2. `grep -c "HANDOFF: did=" app/autopilot.py` → non-zero.
3. `python3 -c "import ast;ast.parse(open('app/autopilot.py').read());print('AST OK')"` → `AST OK`.
4. `python3 -m pytest tests/test_r4_loop_convergence.py -q --basetemp=/root/work/r4-loop/_pt_loop`
   → the pass line, **and** the same command on base `14ebb2322` → the fail line.
5. `git -C /root/work/r4-loop log --oneline -1` → your commit.
6. A checkpoint file exists and is updated as you go: `/root/work/r4-loop/CHECKPOINT.md`
   (a few lines: what is done, what is next). **Write it early and update it after each milestone.**
   Children in this estate have been killed mid-run and lost everything; the checkpoint is how that
   stops mattering.

## 8. Report format — and the honesty clause

Write `/root/work/r4-loop/REPORT.md` and make your final message a summary of it:

```
HOST: <hostname you ran on>
BASE: <git rev-parse HEAD at start>   COMMIT: <your commit hash>
FILES: <exact paths changed>
CHANGE: <one paragraph, what and why>
TEST: <the exact pytest command> -> <the exact pass line, character for character>
BASE TEST: <same command on 14ebb2322> -> <the exact fail line>
AUDITS: <the other pytest command> -> <its tail>
NOT DONE: <what you deliberately left, and why>
UNVERIFIED: <anything you could not check, and exactly what you checked instead>
```

**A confident claim you did not earn is worse than an honest gap.** If a test does not discriminate,
say so. If you could not run something, say "not run" — never imply a green you did not see. If you
ran out of room, say where you stopped; the checkpoint and the report are what the next session
builds on.
