#!/usr/bin/env python3
"""Recording evidence must not change state, and must never erase a blocker.

MEASURED 2026-10-18, on live item 559 while recording a diagnostic lead:

    $ work.py attempt 559 --by ... --did "..." --proof "..." --result "..."
    attempt-recorded {"attempt": 1053, "exit_code": null, "id": 559, "state": "todo"}

Item 559 had been `blocked`. Recording an observation silently UNBLOCKED it, because `attempt`
shares cmd_attempt with `close` and its `--state` default is `todo`.

TWO CONSEQUENCES, the second worse than the first:

1. A shift that records "I looked at this and found X" changes the world it was describing. The
   ledger then shows work as startable because someone wrote a note about it.

2. `blocked_on` is computed as `a.blocked_on if state == "blocked" else None`. So the same call
   writes `blocked_on = NULL` over a recorded blocker. That is precisely the hazard the code
   already guards against for the `--state blocked` case ("an untyped block is how work goes
   invisible"), reached from the other side.

THE FIX: `attempt --state` defaults to None meaning "record only, change nothing". The item's
current state is preserved, and a blocked item keeps both its blocker and its revisit date unless
the caller supplies new ones. `close` keeps its `todo` default, because closing a shift must always
state an outcome.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/bin/work.py"

EDITS = [
    # 1. attempt --state no longer defaults to todo
    (P,
     '''    at.add_argument("--state", choices=["todo", "running", "blocked", "done", "dropped"], default="todo")''',
     '''    # None = "record only, change nothing". MEASURED 2026-10-18: defaulting to `todo` meant
    # recording a diagnostic note on a blocked item silently unblocked it.
    at.add_argument("--state", choices=["todo", "running", "blocked", "done", "dropped"],
                    default=None)'''),
    # 2. resolve the state, and preserve a blocker + revisit date that were not supplied
    (P,
     '''    state = a.state
    blocked_on = a.blocked_on if state == "blocked" else None''',
     '''    # An absent --state means "record only". The item keeps the state it had, and if that state
    # is blocked it keeps its blocker and revisit date too: writing blocked_on=NULL would erase
    # the one thing that explains why the item is waiting.
    state = a.state if a.state else r["state"]
    blocked_on = a.blocked_on if state == "blocked" else None
    if state == "blocked" and not (a.blocked_on or "").strip():
        blocked_on = r["blocked_on"]'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED: %s" % path)
        continue
    if src.count(old) != 1:
        print("REFUSED: anchor found %d times" % src.count(old))
        ok = False
        continue
    out = src.replace(old, new, 1)
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("REFUSED: would not parse: %s" % exc)
        ok = False
        continue
    io.open(path, "w", encoding="utf-8").write(out)
    print("WROTE %s  %d -> %d chars" % (path, len(src), len(out)))
sys.exit(0 if ok else 1)
