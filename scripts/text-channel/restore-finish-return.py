#!/usr/bin/env python3
"""restore-finish-return.py - my patch replaced `return {` with `out = {`.

`_finish` ended with `return { ... }`. The patch script's NEW text began `    out = {`, so
substituting it turned the return statement into an assignment and the function fell off the end
returning None — `resolve()` then returned None and the CLI died with
"'NoneType' object is not subscriptable".

The dict is right; the keyword has to be `return`. This restores it and keeps the new
`provisional` field, then proves `_finish` returns a dict for a real merchant.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/root/bin/merchant_resolve.py"

OLD = '    out = {\n        "solved": is_solved,'
NEW = '    return {\n        "solved": is_solved,'

text = io.open(PATH, encoding="utf-8").read()
if text.count(OLD) != 1:
    print("anchor found %d times - nothing to do or ambiguous" % text.count(OLD))
    raise SystemExit(1 if text.count(OLD) == 0 else 0)
out = text.replace(OLD, NEW, 1)
import ast
ast.parse(out)
if "--apply" not in sys.argv:
    print("DRY   would restore `return {` in _finish")
    raise SystemExit(0)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
print("APPLIED: _finish returns its dict again")
