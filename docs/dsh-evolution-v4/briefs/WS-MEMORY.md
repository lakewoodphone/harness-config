# BRIEF — WS-MEMORY: memory that is read, not written and ignored

You are one builder in a fleet. You own the memory read path. Read this brief completely before you
write anything.

## 0. Where you are

* **Work on host `secratary-cloud`.** If `hostname` is not `secratary-cloud`, prefix every command
  with `ssh secratary-cloud '...'`. Report the host you actually ran on.
* **Repo root and branch:** `/root/work/r4-memory`, branch `r4/memory-read`, cut from `14ebb2322`.
  Report the `git log -1 --format=%H` you actually read.

## 1. Why this exists — measured, and it is the capability multiplier

The company writes a diary it does not read. Measured read-only on `/root/authority.db`,
2026-10-14 (re-measure before you believe; the numbers move):

| store | size | read by the work loop? |
|---|---|---|
| `memories` | ~25,000 rows (`observation` ~12.4k, `summary` ~12.0k) | **no** |
| `procedural_experiences` | ~18,500 rows | **no** |
| `progress_checkpoints` | **52,494 rows across 12,482 sessions** | **no** (verify this yourself: `grep -rn "progress_checkpoints" app/ \| head`) |
| Chroma | ~393k embeddings, three collections holding **0** | partially |
| mem0 | ~131k embeddings | chat turns only, not the tick |

Two defects named in round 3 and still open unless you find otherwise:

* `store_memory_entry` (`app/database.py`), `vector_search_memories` and `upsert_knowledge` have
  **zero callers** — helpers written and never called.
* `from app.services.memory_consolidation import run_consolidation` in `app/services/agent_bus.py`
  names **a function that does not exist**, and the import error is swallowed by a bare `except`.
  A silent no-op wearing the name of a maintenance job.

**The consequence that makes this worth a builder:** the loop *fails* at a step budget
(`STEP_BUDGET_EXHAUSTED` = 389 of 578 failures in 7 days) and a **retry starts from nothing** —
`create_work_session` gives a fresh session an empty `output_log`, zero steps, and no memory of
the attempt that just failed. Measured: **238 tasks had 2+ attempts; 78 ever completed.** Every
retry re-pays for the same reconnaissance. A memory read at session start is not a nicety here; it
is the mechanism by which a retry becomes worth making.

## 2. Read-first list — do this before you design

1. `grep -n "def create_work_session" -A 60 app/autopilot.py` — what a new attempt is given.
2. `grep -n "progress_checkpoints" -r app/ | head -20` — every reader and writer, if any.
3. `grep -n "def store_memory_entry\|def vector_search_memories\|def upsert_knowledge" app/database.py`
   then `grep -rn "store_memory_entry\|vector_search_memories\|upsert_knowledge" app/ | head` — confirm
   the zero-caller claim yourself and report what you found.
4. `grep -n "memory_consolidation\|run_consolidation" -r app/ | head` — the defective import.
5. `grep -n "Inject relevant context memories\|_memory_block\|memories" app/autopilot.py | head -30` —
   whether the loop already injects anything (round 3 recorded one comment at ~line 492; check).
6. `sqlite3 -readonly /root/authority.db ".schema memories"` and `".schema progress_checkpoints"`.

## 3. What to build

### 3a. A memory context block at work-session start, from real data

Add one function, `build_attempt_context(...) -> str` in a new
`app/services/attempt_context.py`, returning a **bounded** block (hard cap ~1500 characters;
state the cap as a constant) assembled from, in priority order:

1. **The previous attempt on the same task**, if any — from `work_sessions` (its status, how it
   ended, the last N characters of its `output_log` **including any `[HANDOFF: ...]` block**) and
   from `progress_checkpoints` for that session.
2. **Task-local facts** already recorded: the task row and any `memories` rows whose content
   mentions the task id or its title (a bounded LIKE/LIMIT query, not a scan).
3. **Nothing at all** when there is no prior attempt — and in that case return a short marker
   saying so explicitly, so a reader can tell "no memory" from "memory lookup failed".

Every part of the block must be **derived from a row or a file**, never narrated. If a lookup
fails, the block must say `attempt-context: <part> unavailable (<reason>)` and still return the
rest — a memory failure must never fail the session.

Wire it in at exactly one place: where `create_work_session` builds a new attempt's opening
context in `app/autopilot.py`.

> **File-scope exception, granted deliberately:** `app/autopilot.py` is owned by the WS-LOOP
> builder. You may make **one narrowly-scoped edit** to it: the single call that injects the block
> at session start, plus the import. Nothing else in that file. If you find you need more, stop and
> put it in your report as `NEEDS-EDIT` with the exact diff.

### 3b. Repair the silent no-op

Fix the `memory_consolidation` import so it either imports something that exists or fails loudly.
Whichever you choose, the `except` that currently swallows an `ImportError` must be narrowed so it
cannot hide this class again, and say in your report exactly what the handler now catches.

### 3c. Measure whether a memory is ever read

Add a counter, not a document. A small table or a JSON file is fine (state which), recording for
each `build_attempt_context` call: the task id, whether a prior attempt was found, the byte size
of the block, and the wall time. Then answer, with one command a reviewer can run:

* How many memories exist?
* How many were **read by the loop** since this change?
* How many memories were written and never retrieved in 7 days?

Report the command and its output line. "A memory that is written and never retrieved in 7 days
should be reported, not stored" is the rule this closes.

## 4. Exclusive file scope

**You may create:** `app/services/attempt_context.py`, `tests/test_r4_memory_context.py`.
**You may edit:** `app/autopilot.py` — **only** the session-start injection and its import (see 3a);
`app/database.py` — only if you must repair a broken helper; `app/services/agent_bus.py` for 3b.
**You may not touch:** `tests/` other than your own file, `app/services/autonomy.py`,
`app/services/agent_worker.py`, `app/services/task_protection.py`, `app/main.py`, any config.

## 5. Tests

```sh
cd /root/work/r4-memory
export PATH=/root/work/venv-pytest/bin:$PATH
python3 -m pytest tests/test_r4_memory_context.py -q --basetemp=/root/work/r4-memory/_pt_mem 2>&1 | tail -20
```

* Build the block from a **temp SQLite database you create in the test**, never the real
  `/root/authority.db`. Create the tables you need with the real schema (copy it from
  `.schema`), insert a fake failed attempt and a fake memory, and assert the block contains the
  handoff text and stays inside the character cap.
* Assert the failure path: with the database unreachable, the function returns a marker and raises
  nothing.
* Assert the "no prior attempt" path returns the explicit marker rather than an empty string.
* A regression test that **fails on base `14ebb2322` and passes after** — for the injection at
  least (on base, `build_attempt_context` does not exist, so a test that imports it fails; that is
  fine and is the discriminating line). Show both result lines.
* Never bind a port. Use `--basetemp` as shown.

## 6. Git rules — absolute

Branch `r4/memory-read` only. Never push, never touch `master`/`main`, never `git add -A`/`.`,
never `reset --hard`/`clean`/delete. Stage explicit paths. Commit message names what changed and
the test result lines.

## 7. Definition of done

1. `python3 -c "import ast;ast.parse(open('app/services/attempt_context.py').read());print('AST OK')"` → `AST OK`
2. `python3 -m pytest tests/test_r4_memory_context.py -q --basetemp=/root/work/r4-memory/_pt_mem` → pass line
3. The same test on base `14ebb2322` → fail line
4. `grep -c "build_attempt_context" app/autopilot.py` → 1 (the injection) — not 0, not 5
5. `grep -n "run_consolidation" app/services/agent_bus.py` → the repaired form, and say what the handler now catches
6. `/root/work/r4-memory/CHECKPOINT.md` updated; `/root/work/r4-memory/REPORT.md` written

## 8. Report format, and the honesty clause

```
HOST: <hostname>   BASE: <hash>   COMMIT: <hash>
FILES: <exact paths>
THE ZERO-CALLER CLAIM: <confirmed | refuted — with the grep and its output>
THE BAD IMPORT: <what it actually was, and what you changed it to>
CONTEXT BLOCK: <what it contains, its cap, and the order of priority>
INJECTION SITE: <file:line — and the count of changed lines in autopilot.py>
MEASUREMENT: <the command> -> <the output line>
TEST: <command> -> <exact result line>
BASE TEST: <command on 14ebb2322> -> <exact fail line>
NOT DONE: <what you left>
UNVERIFIED: <what you could not check, and what you checked instead>
```

**A confident claim you did not earn is worse than an honest gap.** If the loop already read
memories somewhere you did not expect, say so — that reframes the whole task and is more valuable
than carrying out a brief written on a stale measurement.
