#!/usr/bin/env python3
"""fix-k1-tuples.py - `ro()` has no row_factory, so a row is a tuple.

Exactly the bug J1 had and I fixed there: `dict(r)` on a plain tuple raises
"dictionary update sequence element #0 has length N; 2 is required", so the check reports a crash
instead of its finding - and a crash and a finding print the same FAIL.

Name the columns explicitly.
"""
import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/root/bin/text-health.py"

OLD = '''        _claimed = [dict(r) for r in _q.execute(
            "select id, body, sent_at from owner_message_queue "
            "where status='sent' and sent_at is not null and sent_at >= ?", (_cut,))]'''
NEW = '''        # ro() does not set a row_factory: name the columns rather than assuming a mapping.
        _claimed = [{"id": r[0], "body": r[1], "sent_at": r[2]} for r in _q.execute(
            "select id, body, sent_at from owner_message_queue "
            "where status='sent' and sent_at is not null and sent_at >= ?", (_cut,))]'''

text = io.open(PATH, encoding="utf-8").read()
if NEW in text:
    print("already fixed")
    raise SystemExit(0)
if text.count(OLD) != 1:
    print("anchor found %d times" % text.count(OLD))
    raise SystemExit(1)
import ast
out = text.replace(OLD, NEW, 1)
ast.parse(out)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
print("fixed")
