#!/usr/bin/env python3
"""provisional-is-ambiguity-not-reversal.py - "not a purchase" is not "I am unsure".

`_from_descriptor` sets `provisional = weak or not purchase`. Those are two different facts:

  weak         TRUE ambiguity - the descriptor carries two readings, or its token claims little
               ("adjust" at 0.55, which could be a gym membership or a correction). Keep asking.
  not purchase a DEFINITE fact - this is a reversal or a refund. "crdt rvsd" says card credit
               reversed. There is nothing to ask; it should be filed as Fees & Adjustments.

Conflating them made an explicit reversal unsolved: measured 2026-10-19,
`cdd crdt rvsd case` resolved to Fees & Adjustments, purchase=False, and came back solved=False,
so the question it had already answered would be asked again.

`purchase` stays on the result - the caller must still never present a reversal as something
bought, and `resolved_enough` still refuses `purchase is False` for a DESCRIPTOR reading, so a
reversal is never treated as a completed purchase resolution. What changes is `provisional`, which
now means only what it says: ambiguity.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/merchant_resolve.py")

OLD = '        "provisional": bool(weak or not best["purchase"]),'
NEW = ('        # AMBIGUITY, not "not a purchase". A definite reversal ("crdt rvsd") is not\n'
       '        # uncertain - there is nothing to ask, and it should be filed. `purchase` carries\n'
       '        # the other fact separately, and `resolved_enough` still refuses a descriptor\n'
       '        # reading with purchase=False, so a reversal is never counted as a purchase.\n'
       '        "provisional": bool(weak),')


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if '"provisional": bool(weak),' in text:
        print("OK    already applied")
        return 0
    if text.count(OLD) != 1:
        print("FAIL  found %d times" % text.count(OLD))
        return 1
    out = text.replace(OLD, NEW, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would make provisional mean ambiguity only")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-prov-" + stamp))
    PATH.write_text(out, encoding="utf-8")
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
