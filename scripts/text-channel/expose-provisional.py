#!/usr/bin/env python3
"""expose-provisional.py - a flag the caller checks must be a flag the caller can see.

`resolved_enough()` tests `res.get("provisional")`, but `_finish()` never put `provisional` in the
returned dict - it lives on the `best` candidate. So the check read `None` and silently did nothing.

Measured 2026-10-19 on `cdd crdt rvsd case`: the resolver now returns solved=True with
category Fees & Adjustments and purchase=False. `resolved_enough` refused it because of the
`purchase is False` clause - a clause written when `provisional` still meant "not a purchase".
Now that provisional means AMBIGUITY, the refusal belongs on that flag and not on `purchase`:
a definite reversal is a complete answer, and asking him again would be exactly the kind of
question he complains about.

So: expose `provisional` on the result, and take the `purchase is False` clause out of
`resolved_enough`. `purchase` stays on the result for any caller that must not describe a reversal
as a purchase.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MR = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/merchant_resolve.py")
CFO = Path(sys.argv[2] if len(sys.argv) > 2 else "/root/bin/cfo-ask.py")

EDITS_MR = [
    # expose provisional alongside purchase
    ('    return {\n        "solved": is_solved,',
     '    out = {\n        "solved": is_solved,\n'
     '        # EXPOSED, because `resolved_enough` checks it. A flag the caller tests must be a\n'
     '        # flag the caller can see; it lived only on `best` and the check read None.\n'
     '        "provisional": bool((best or {}).get("provisional")),'),
]

EDITS_CFO = [
    ('''    if res.get("purchase") is False or res.get("provisional"):
        return False''',
     '''    # PROVISIONAL IS AMBIGUITY, AND IT IS THE ONLY THING THAT BLOCKS HERE. A definite
    # reversal (purchase is False) is a complete answer - file it as Fees & Adjustments and do
    # not ask; asking about a refund he already told us about is the complaint. `purchase`
    # stays on the result so nobody describes a reversal as something bought.
    if res.get("provisional"):
        return False'''),
]


def patch(path: Path, edits, dry: bool) -> int:
    text = path.read_text(encoding="utf-8")
    changed = 0
    for old, new in edits:
        if new.split("\n")[0] in text and old not in text:
            print("OK    %s already applied" % path.name)
            continue
        if text.count(old) != 1:
            print("SKIP  %s: anchor found %d times" % (path.name, text.count(old)))
            continue
        text = text.replace(old, new, 1)
        changed += 1
    if not changed:
        return 0
    import ast
    ast.parse(text)
    if dry:
        print("DRY   %s: %d edit(s)" % (path.name, changed))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak-prov2-" + stamp))
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    print("PATCHED %s (%d edit(s))" % (path, changed))
    return 0


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    rc = patch(MR, EDITS_MR, dry)
    rc |= patch(CFO, EDITS_CFO, dry)
    raise SystemExit(rc)

