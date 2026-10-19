#!/usr/bin/env python3
"""add-alias-invariant.py - an instrument that would have caught the unfilable aliases.

MEASURED 2026-10-19: of 11 learned aliases, **10 cannot be filed** - five carry the category
"personal" or "unknown", which are NOT in the ledger's categories table, and five carry no
category at all. Only one is filable.

That is why the questions keep coming back. The self-evolution hook writes what he said into
`~/.cfo-asks/aliases.db`, and the asker reads it back as an answer - but a category the ledger
does not hold gets no `category_id`, so the charge is never filed, and the next pass sees the
same unexplained charge.

`text-health.py` has 15 invariants and runs on a schedule. None of them looked at whether the
vocabulary the channel writes is a vocabulary the ledger can resolve. This adds that one:

    no learned alias may name a category the ledger does not hold

An alias with NO category is deliberately not a failure - that is the documented `known_only`
case, where the vendor is known and nobody has said what the charge was for, and the rung is
supposed to report it as still-a-question rather than as a resolution.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/text-health.py")

CHECK = '''
# ---------------------------------------------------------------------------------------
# J1: the vocabulary the channel LEARNS must be a vocabulary the ledger can FILE.
#
# Measured 2026-10-19: 10 of 11 learned aliases were unfilable - "personal" and "unknown" are
# not categories in the ledger, and a category that does not resolve to an id files nothing.
# The charge stays uncategorised, the resolver still calls it answered, and the same question
# comes back weeks later. That is the loop this invariant exists to break.
#
# An alias with NO category is not a failure: that is the documented `known_only` case - the
# vendor is known, nobody has said what the charge was for, and the rung must report it as a
# question rather than as a resolution.
# ---------------------------------------------------------------------------------------
try:
    aliases_db = BIN / ".." / ".cfo-asks" / "aliases.db"
    aliases_db = Path(os.path.expanduser(os.environ.get("CFO_ALIAS_DB", "~/.cfo-asks/aliases.db")))
    acct_db = Path(os.environ.get("CFO_ACCOUNTING_DB", "/root/accounting-data/live/accounting.db"))
    if not aliases_db.exists():
        check("J1 every learned alias names a category the ledger can file", True,
              "no alias store at %s yet - nothing has been learned" % aliases_db)
    elif not acct_db.exists():
        check("J1 every learned alias names a category the ledger can file", True,
              "NOT MEASURED: accounting db absent at %s" % acct_db)
    else:
        _a = ro(acct_db)
        try:
            known = {(r[0] or "").lower() for r in _a.execute("select name from categories")}
        finally:
            _a.close()
        _s = ro(aliases_db)
        try:
            rows = [dict(r) for r in _s.execute(
                "select merchant_key, category, learned_at from alias")]
        finally:
            _s.close()
        bad = [r for r in rows
               if str(r.get("category") or "").strip()
               and str(r["category"]).strip().lower() not in known]
        blank = [r for r in rows if not str(r.get("category") or "").strip()]
        detail = ("%d learned alias(es); %d name a category the ledger does NOT hold, so they "
                  "can never be filed; %d carry no category (the known-only case, correct)"
                  % (len(rows), len(bad), len(blank)))
        if bad:
            detail += " :: " + "; ".join(
                "%s -> %r (learned %s)" % (str(r["merchant_key"])[:30],
                                           str(r["category"])[:24],
                                           str(r.get("learned_at"))[:10])
                for r in bad[:6])
        check("J1 every learned alias names a category the ledger can file", not bad, detail)
except Exception as exc:
    check("J1 every learned alias names a category the ledger can file", False,
          "%s: %s" % (type(exc).__name__, exc))

'''

ANCHOR = 'print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "J1 every learned alias" in text:
        print("OK    already applied")
        return 0
    if text.count(ANCHOR) != 1:
        print("FAIL  anchor found %d times" % text.count(ANCHOR))
        return 1
    if "\nimport os" not in text and "import os" not in text.split("\n\n")[0]:
        text = text.replace("import sys", "import os\nimport sys", 1)
    out = text.replace(ANCHOR, CHECK + ANCHOR, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add invariant J1")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-j1-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    rc = subprocess.run([sys.executable, "-c",
                         "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
                         str(tmp)], capture_output=True)
    if rc.returncode != 0:
        print("FAIL  tmp does not parse: %s" % rc.stderr.decode()[:300])
        tmp.unlink(missing_ok=True)
        return 1
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
