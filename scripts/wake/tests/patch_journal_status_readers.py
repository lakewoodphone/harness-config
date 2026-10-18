#!/usr/bin/env python3
"""Make `show` and `list` agree with `status` about whether an entry is closed.

MEASURED 2026-10-18 on the authority, minutes after the pain closer closed 15 entries:

    journal.py status                          -> OPEN PAIN 573            (correct)
    journal.py show P261                       -> pain · 2026-09-17 · open (WRONG)
    journal.py list --kind pain --status done  -> no entries match         (WRONG; 40 exist)

WHY. `cmd_resolve` appends to `state/status.tsv` and *never edits the entry file* -- that is
deliberate and documented ("Appends; never edits the entry file"). `effective_status()` exists
precisely to overlay that log onto the marker, and `status` uses it. But `cmd_show` prints
`e["status"]` straight from the entry marker, and `cmd_list` both FILTERS and PRINTS on it.

CONSEQUENCE. The journal's own README tells a session to read one entry with `show <id>`. A session
that follows the instructions sees `open` on work closed on evidence minutes earlier, and re-opens
it. The memory system would then manufacture the repeated-work failure it exists to prevent -- for
every closure the now-scheduled pain closer makes.

THE FIX, deliberately narrow: overlay in the two read paths the README names, and leave `catalog()`
untouched so integrity/drift checks keep their raw view of the markers.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/code/harness-config/journal/tools/journal.py"

EDITS = [
    # cmd_list: overlay before filtering and printing
    (P,
     '''def cmd_list(args) -> int:
    entries, source, _fresh = catalog()''',
     '''def cmd_list(args) -> int:
    entries, source, _fresh = catalog()
    # OVERLAY THE RESOLVE LOG (2026-10-18). Filtering and printing used the entry marker alone, so
    # `--status done` matched nothing and every closed entry still read `open`. Narrow on purpose:
    # `catalog()` keeps its raw view for the drift checks.
    _ev = load_status_events()
    for _e in entries:
        _e["status"] = effective_status(_e["kind"], _e["id_full"],
                                        _e.get("status") or "", _ev)'''),
    # cmd_show: load the events once, overlay once the entry is found
    (P,
     '''    misses = []
    notes = []
    for raw in ids:''',
     '''    misses = []
    notes = []
    # Same overlay as cmd_list: `show` printed the marker, so a resolved entry still read `open`.
    _ev = load_status_events()
    for raw in ids:'''),
    (P,
     '''        e = load_one(want) or load_one(want.upper())              # exact path: one open
        if e is not None:''',
     '''        e = load_one(want) or load_one(want.upper())              # exact path: one open
        if e is not None:
            e["status"] = effective_status(e["kind"], e["id_full"],
                                           e.get("status") or "", _ev)'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED")
        continue
    if src.count(old) != 1:
        print("REFUSED: anchor found %d times: %r" % (src.count(old), old.splitlines()[0]))
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
