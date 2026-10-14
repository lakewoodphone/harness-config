# BRIEF — WS-TRANSPORT: silent failure must reach a human, and the task ceiling must stop blocking work

You are one builder in a fleet of three. You own a small, precisely-bounded set of files. Read this
brief completely before you write anything.

## 0. Where you are, and the revision you are on

* **Work on host `secratary-cloud`.** If `hostname` is not `secratary-cloud`, prefix every command
  with `ssh secratary-cloud '...'`. Say in your report which host you actually ran on.
* **Repo root and branch:** `/root/work/r4-transport`, branch `r4/silent-failure-transport`, cut from
  `14ebb2322`. Report the `git log -1 --format=%H` you actually read.
* **The tenant:** an autonomous "AI company" running a phone-repair business — a FastAPI service
  (`company-api`) with a 900-second autopilot tick, 74 autonomy-gated action families, and ~140 work
  sessions a day. It has no way to tell its owner that it is broken.

## 1. The two defects, each already measured

### Defect A — the service can be up and answering nothing, for an hour, with nobody told

Measured 2026-10-14 this morning (`journal` handoff `H3660`, and re-confirmed by the round-4 recon):

* `company-api` was `active`, `NRestarts=0`, and answered **nothing for over 50 minutes**.
* It was found only because somebody happened to want the API for a different reason.
* `estate-monitor` computes `crit=5` **every two minutes** and logs `escalated=0`, because its
  escalation path admits only one kind of condition.
* `cron-liveness.py` exists and is **not scheduled**.
* The authority's journald does **not persist**, so the logs that would have explained a
  4 h 33 min disk-full window were gone.

The distinction that matters and must be preserved: **`is-active` is not health, and `/health` is not
health either** — this API returns `{"ok": true, "database": {"ok": true}}` in the body while a real
`ok:false` was seen in `finance`. A probe must answer *"did the service do the thing it exists to
do"*, not *"is the socket open"*.

### Defect B — the company cannot create a task, because of its own ceiling

Measured 2026-10-14 19:35Z, read-only:

```
sqlite3 -readonly /root/authority.db \
  "SELECT status, count(*) FROM tasks GROUP BY 1 ORDER BY 2 DESC"
done 28180 · blocked 247 · closed 56 · open 41 · cancelled 34 · completed 28 · in_progress 19 · pending 1 · todo 1
```

The ceiling counts everything not in the closed set, which is **309 rows against a ceiling of 300**.
The live trace of a failed session (`work_sessions.id = 78750`, verbatim from `output_log`) shows
what that does to real work:

```
[TOOL_LOOP_DEADLOCK: 'create_task' failed identically 3/3 times for dept_engineering in the last
300s (failure_class=task creation blocked: 300 active tasks (ceiling 300). close or complete
existing tasks before creating new ones.)]
```

So the company is over its own task ceiling, and its agents spend their session trying to register
work and failing. Locate the ceiling yourself and report exactly where it is:

```sh
grep -rn "300 active tasks\|MAX_ACTIVE_TASKS\|active task ceiling\|ceiling" /root/work/r4-transport/app/ --include=*.py | head -20
```

Confirm the current count with the query above (do not trust this brief's number — re-run it and
report what you got).

## 2. What to build

### 2a. A real probe with a deadline, that can escalate

Add a module `app/services/liveness_probe.py` exposing one function:

```
def probe_company_api(timeout_s: float = 5.0) -> dict
```

It must, in this order, and it must **not** simply open a socket:

1. `GET /health` with a hard deadline; parse the JSON; extract a boolean verdict from the body
   (not the HTTP status alone).
2. Perform one **trivial read-only database round-trip through the API's own client path** (a
   `SELECT 1`-class call), because a wedged API is exactly one that answers `/health` from a cached
   object while its DB lock is held. If the API exposes no such endpoint, call the same DB file
   directly with a deadline and say so in the docstring.
3. Return a dict with, at minimum: `ok` (bool), `http_status`, `detail` (str), `elapsed_ms` (int),
   `checked_at` (ISO-8601 UTC, `T`-separated — the stored timestamp shape in this estate is
   `2026-10-14T11:05:01+00:00`, and comparing it against `datetime('now')` is a known one-day
   off-by-one bug, `L3801`).

No network calls to anywhere except `127.0.0.1`. No writes. It must return rather than raise on
timeout, and `ok=False` with a `detail` naming the failure is the correct result when the API is
wedged.

### 2b. Make it reach somebody

Read how the estate already notifies before you invent anything — this estate has repeatedly paid
for building a parallel system. Find the existing transport:

```sh
grep -rn "send_sms\|owner_alert\|escalat" /root/work/r4-transport/app/services/*.py | head -30
sqlite3 -readonly /root/authority.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%alert%' OR name LIKE '%escalat%'"
grep -rn "estate-monitor\|estate_monitor" /root/work/r4-transport/app/ /root/bin/ 2>/dev/null | head
```

Then **wire the probe into one existing escalation path** — the one that already reaches the owner —
rather than adding a new one. Record in your report which path you used and what it writes. If the
existing path cannot carry a new condition, say so explicitly in the report and implement the
minimal change that lets it; do not build a second notification system.

### 2c. Schedule it, and make the schedule provable

Add a systemd timer **unit file in the repo** (not installed by you) at
`deploy/r4-liveness-probe.timer` and `.service`, on a 2-minute interval, running the probe and
escalating on two consecutive failures. **Do not install or start it** — installation is the
manager's job and the authority runs a live business. Your deliverable is the unit file plus the
exact commands the manager will run.

### 2d. Resolve the task ceiling, with the reasoning written down

Choose **one** of these and implement it, with a test:

* count only `open`/`in_progress`/`pending`/`todo` against the ceiling and let `blocked` be a
  non-consuming state (a blocked task is not consuming an agent), **or**
* raise the ceiling to a value derived from measurement rather than a round number, and add a
  `blocked`-aging sweep that returns stale blocked rows to `todo`.

Whichever you choose, the ceiling must become a **named, env-overridable constant**, not a literal.
State the arithmetic that justifies your choice in the code comment and in your report.

## 3. Exclusive file scope

**You may edit/create:** `app/services/liveness_probe.py` (new),
`app/services/task_protection.py` (only the ceiling constant and the counting predicate),
`deploy/r4-liveness-probe.timer`, `deploy/r4-liveness-probe.service`,
`tests/test_r4_liveness_and_ceiling.py`.
**You may NOT touch:** `app/autopilot.py` (another builder owns it), `app/main.py`,
`app/services/autonomy.py`, `app/services/agent_worker.py`, any other test file, any config.
Do not edit `estate-monitor` if it lives outside this repo — report it instead.

## 4. Tests

```sh
cd /root/work/r4-transport
python3 -m pytest tests/test_r4_liveness_and_ceiling.py -q --basetemp=/root/work/r4-transport/_pt_t 2>&1 | tail -20
```

Requirements:
* `probe_company_api` must be tested against a **stub** HTTP server or a monkeypatched transport, so
  the test passes with the real API up or down. Never bind a port on a shared host; if you must use
  a socket, bind `127.0.0.1` on port 0 and close it, and say so.
* The ceiling change must have a regression test that **fails on base `14ebb2322` and passes after**.
  Show both lines.
* Do not use the real `/root/authority.db` in a test. Use an in-memory or temp SQLite file.

## 5. Git rules — absolute

Commit to `r4/silent-failure-transport` only. Never push. Never touch `master`/`main`. Never
`git add -A`/`git add .`; stage explicit paths. Never `reset --hard`, `clean`, or delete anything.
Commit with a message naming what changed, why, and the test result lines.

## 6. Definition of done

1. `python3 -c "import ast;ast.parse(open('app/services/liveness_probe.py').read());print('AST OK')"` → `AST OK`
2. `python3 -m pytest tests/test_r4_liveness_and_ceiling.py -q --basetemp=/root/work/r4-transport/_pt_t` → the pass line
3. The same test file's ceiling test on base `14ebb2322` → the fail line
4. `grep -rn "300" app/services/task_protection.py` → no bare literal ceiling remains
5. `ls -l deploy/r4-liveness-probe.*` → both unit files present
6. `/root/work/r4-transport/CHECKPOINT.md` exists and was updated after each milestone
7. `/root/work/r4-transport/REPORT.md` written

## 7. Report format, and the honesty clause

```
HOST: <hostname>   BASE: <hash>   COMMIT: <hash>
FILES: <exact paths>
CHANGE: <what and why, including the arithmetic for the ceiling>
EXISTING TRANSPORT USED: <the path you wired into, or "none found — here is what I found instead">
TEST: <command> -> <exact result line>
BASE TEST: <command on 14ebb2322> -> <exact fail line>
UNITS: <paths> + the exact commands the manager should run to install them (not run by you)
NOT DONE: <what you left>
UNVERIFIED: <what you could not check, and what you checked instead>
```

**A confident claim you did not earn is worse than an honest gap.** A probe you could not run
against a live API is "not verified against the live API" — that is an acceptable and correct
report; claiming you saw it escalate when you did not is not.
