#!/usr/bin/env python3
"""`--status done --since <today>` must mean "closed since today", not "created since today".

MEASURED 2026-10-18. With the status overlay in place, `list --kind pain --status done` correctly
returns 141 resolved entries, but adding `--since 2026-10-18` returns NOTHING -- because
`_matches` compares `e["date"]`, which is when the entry was WRITTEN. The 15 entries the pain
closer closed today were all written weeks ago, so every one of them is filtered out.

That misled me for two rounds: I read "no entries match" as "the closes did not take effect" when
they had. A filter that answers a different question than it appears to is the same class as a
monitor that measures the wrong thing.

THE FIX: carry the resolve DATE alongside the overlaid status, and when a status filter is in play,
`--since`/`--until` compare against that date instead. Without a status filter the behaviour is
unchanged, so "entries created since X" still works exactly as before.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/code/harness-config/journal/tools/journal.py"

EDITS = [
    # carry the resolve date on the entry in both overlays
    (P,
     '''    _ev = load_status_events()
    for _e in entries:
        _e["status"] = effective_status(_e["kind"], _e["id_full"],
                                        _e.get("status") or "", _ev)''',
     '''    _ev = load_status_events()
    for _e in entries:
        _e["status"] = effective_status(_e["kind"], _e["id_full"],
                                        _e.get("status") or "", _ev)
        # The date the STATUS was set, when it came from the resolve log. `--since` needs it: the
        # 15 entries closed today were all written weeks ago, so a creation-date filter excluded
        # every one and the caller read "nothing was closed".
        _row = _ev.get((_e["kind"], _e["id_full"]))
        _e["status_date"] = _row[1] if _row else None'''),
    (P,
     '''            e["status"] = effective_status(e["kind"], e["id_full"],
                                           e.get("status") or "", _ev)''',
     '''            e["status"] = effective_status(e["kind"], e["id_full"],
                                           e.get("status") or "", _ev)
            _row = _ev.get((e["kind"], e["id_full"]))
            e["status_date"] = _row[1] if _row else None'''),
    # the filter itself
    (P,
     '''    since = getattr(args, "since", None)
    if since and (e.get("date") or "")[:10] < since:
        return False''',
     '''    since = getattr(args, "since", None)
    # MEASURED 2026-10-18: with a status filter, the date that matters is when the STATUS changed,
    # not when the entry was written -- otherwise "--status done --since today" can never match a
    # closure, because closed entries are older than their closure.
    _date = (e.get("status_date") or e.get("date")) if st else e.get("date")
    if since and (_date or "")[:10] < since:
        return False'''),
    (P,
     '''    until = getattr(args, "until", None)
    if until and ((e.get("date") or "9999")[:10] or "9999") > until:
        return False''',
     '''    until = getattr(args, "until", None)
    if until and ((((_date or "9999")[:10]) or "9999") > until):
        return False'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED")
        continue
    if src.count(old) != 1:
        print("REFUSED: anchor %r found %d times" % (old.splitlines()[0], src.count(old)))
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
