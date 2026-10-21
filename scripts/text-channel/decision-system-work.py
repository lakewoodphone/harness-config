#!/usr/bin/env python3
"""decision-system-work.py — a row the system was going to "handle" must become a ledger item.

WHY THIS EXISTS (2026-10-21)
----------------------------
The triage grew a SYSTEM disposition for rows whose ask is passive: "Want me to note the device
details?", "Want me to save the referral list for shop use?", "Want me to note Nov 1 billing?".
None has a downside, a cost, or a real alternative, so asking spends the owner's attention to
obtain consent nobody needed -- his own instruction was "only text me for truly important things
and don't overdo it or spam me".

But classifying them SYSTEM while NOTHING acts on that disposition would be worse than asking: a
question he can answer is at least visible, and a SYSTEM row that no shift ever touches is a
decision silently dropped. Measured: no consumer of the SYSTEM disposition existed.

So this files ONE ledger item per SYSTEM row, idempotently, and a normal shift claims and does it.
The note gets noted; he hears about it in the digest rather than being asked about it.

IDEMPOTENT through `source = system-row:<id>`; a re-run cannot file twice.
READ-ONLY except the ledger items it files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
WORK = HOME / "bin" / "work.py"
TRIAGE = Path("/root/bin/decision-triage.py")
PREFIX = "system-row:"


def system_rows() -> list[dict]:
    """The rows the triage says the system should handle itself."""
    try:
        out = subprocess.run([sys.executable, str(TRIAGE), "--json"],
                             capture_output=True, text=True, timeout=600).stdout
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print("decision-system-work: cannot read the triage (%s)" % exc)
        return []
    return [r for r in data.get("rows", []) if r.get("disposition") == "SYSTEM"]


def already_filed(row_id: int) -> bool:
    try:
        out = subprocess.run([sys.executable, str(WORK), "show", PREFIX + str(row_id)],
                             capture_output=True, text=True, timeout=60)
        return out.returncode == 0 and (PREFIX + str(row_id)) in (out.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv: list[str] | None = None) -> int:
    apply = "--apply" in (argv or sys.argv[1:])
    rows = system_rows()
    if not rows:
        print("decision-system-work: nothing the system owes itself")
        return 0
    filed = 0
    for r in rows:
        rid = int(r["id"])
        if already_filed(rid):
            continue
        q = " ".join(str(r.get("question") or "").split())[:150]
        why = ("The triage classified queue row #%d as SYSTEM: a passive record-keeping act with "
               "no downside, no cost and no real alternative, so asking the owner for permission "
               "would spend his attention to obtain consent nobody needed (his instruction: "
               "'only text me for truly important things and don't overdo it or spam me'). This "
               "item exists so the disposition is ACTED ON rather than merely hidden -- a row "
               "classified SYSTEM that no shift touches is a decision silently dropped. Do the "
               "thing the row describes and record where it was written." % rid)
        print("would file: #%s %s" % (rid, q[:80]))
        if not apply:
            continue
        try:
            out = subprocess.run(
                [sys.executable, str(WORK), "add", "--project", "housekeeping",
                 "--priority", "4", "--source", PREFIX + str(rid),
                 "--title", "Note what he was sent: %s" % q,
                 "--why", why,
                 "--dod", "The thing the row describes is recorded where it belongs (memory, "
                          "notes, or the relevant store) and the ledger item names the location."],
                capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            print("  failed for #%s: %s" % (rid, exc))
            continue
        if out.returncode == 0:
            filed += 1
    print("filed %d system item(s)" % filed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
