#!/usr/bin/env python3
"""measure-pager-answerability.py — can the owner ANSWER what the pager sends?

WHY THIS EXISTS
---------------
`owner-text-scorecard.py` names the worst family and `owner-text-audit.py` the
channel defects, but neither answers the narrow question the 2026-10-20 wake was
sent for: of the items in the live digest, how many compose to a text the owner
could actually answer?

The 36-item wall (`10-13 02:24 UTC 36 items, 26 urgent`) was 3 dead of 3 because
it asked nothing.  The wall was retired; the one-item pager that replaced it
still chooses by rank only, so a statement like

    OVERDUE 2026-08-15 - Elantra - New York toll bill collection (bill)

went out with `Reply with your answer, or say 'your call'.`  There is no answer
to that.  The text is dead by construction.

WHAT IT COUNTS
--------------
For every item line in the digest, with the module's OWN `_compose_one()`:

    answerable               the composed body contains '?'
    bodies_without_question  the composed body is non-empty but has no '?'
                             (a dead text: it demands a reply to a statement)
    skipped                  the composed body is empty (the answerability gate)

It then runs the pager over the whole list from a COLD START (nothing sent yet),
using `pick_one_item()` itself, and counts the texts one digest cycle would
produce and how many of them are statements.  This is the before/after number:
the gate changes the cycle from "34 texts, 23 statements" to "11 texts, 0
statements".

READ-ONLY.  It never calls send() and never writes sent-items.json.

RUN
    /root/personal-secretary-mvp/.venv/bin/python3 measure-pager-answerability.py \
        [/root/personal-secretary-mvp/scripts/owner_attention.py] \
        [/root/personal-secretary-mvp/data/owner-attention/latest.txt]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MOD = Path(sys.argv[1] if len(sys.argv) > 1 else
           "/root/personal-secretary-mvp/scripts/owner_attention.py")
DIGEST = Path(sys.argv[2] if len(sys.argv) > 2 else
              "/root/personal-secretary-mvp/data/owner-attention/latest.txt")


def load(path: Path):
    spec = importlib.util.spec_from_file_location("oa_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if not MOD.is_file():
        print(f"FAIL module not found: {MOD}")
        return 2
    if not DIGEST.is_file():
        print(f"FAIL digest not found: {DIGEST}")
        return 2
    m = load(MOD)
    text = DIGEST.read_text(encoding="utf-8")
    items = [l for l in text.split("\n")
             if l[:4].strip().rstrip(".").isdigit() and "] " in l]

    answerable = statements = skipped = 0
    for raw in items:
        body = m._compose_one(raw)
        if not body:
            skipped += 1
        elif "?" in body:
            answerable += 1
        else:
            statements += 1

    # Cold start: what one pass over this digest would text him.
    sent: dict[str, str] = {}
    cycle = 0
    cycle_statements = 0
    now = m._now().isoformat()
    for _ in range(len(items) + 1):
        picked = m.pick_one_item(items, sent)
        if picked is None:
            break
        raw = next((l for l in items if m._render_item(l) == picked), "")
        body = m._compose_one(raw)
        if not body:
            break
        cycle += 1
        if "?" not in body:
            cycle_statements += 1
        sent[m.item_fingerprint(picked)] = now

    print(f"MODULE {MOD}")
    print(f"DIGEST {DIGEST}")
    print(f"items {len(items)}")
    print(f"answerable {answerable}")
    print(f"bodies_without_question {statements}")
    print(f"skipped {skipped}")
    print(f"COLD-START TEXTS {cycle}  statements {cycle_statements}  answerable {cycle - cycle_statements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
