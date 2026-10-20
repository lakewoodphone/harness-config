#!/usr/bin/env python3
"""FLAG SOURCE: are the owner's texts DOING anything?

THE SIGNAL
----------
For every text that actually reached him, what did he do next?

    ANSWERED    he replied inside the reply window, and not to complain
    COMPLAINED  he replied, and the reply is a complaint
    IGNORED     he said nothing at all for the whole window

`bin/sources/owner-question-audit.py` already classifies each text by its WORDING
(QUESTION / RESULT / ALERT / NOISE) and fires on noise. This source asks the other half of
the question, and only this one can answer it: **did the text earn its place?** A perfectly
well-formed question that nobody ever answers is still a text that did no work, and no
wording-based rule can see that.

WHY THE THRESHOLD IS 50%
------------------------
Measured on the authority 2026-10-19, first run of the instrument:

    last 30 days   47 answered, 7 complained about, 44 ignored   -> 52% dead of 98 judged
    last  7 days   21 answered, 1 complained about, 13 ignored   -> 40% dead of 35 judged

So the channel is currently talking to itself about half the time, and the worst families are
the briefings the owner banned in March (evening briefing 4/4 dead, morning briefing 2/2) and
one payment reminder (2/2). Half is not a target to approach; it is the level at which the
channel is more noise than signal, which is the owner's own words: "so many of them I don't
need text it to me."

WEEKLY, AND ONE THING
---------------------
The subject carries the ISO week, so the same condition cannot file a session every morning.
The prompt names the WORST FAMILY and tells the session to land ONE bounded change with a
before/after count -- never to re-audit the channel, because
`owner-text-audit.py` and `owner-text-scorecard.py` are already the instruments.

READ-ONLY on every store. It writes nothing anywhere; its only side effect is the flag.

SUBJECT   owner-text:scorecard:<ISO year>-W<ISO week>

MUST NEVER
    - send anything to anyone;
    - fire when the rate is below threshold (a quiet source is a working instrument);
    - count a text as delivered when it carries no provider sid.
"""
from __future__ import annotations

import importlib.util
import os
import sys

SCORECARD = os.environ.get(
    "OWNER_TEXT_SCORECARD",
    "/root/code/harness-config/scripts/text-channel/owner-text-scorecard.py",
)


def main() -> int:
    if not os.path.exists(SCORECARD):
        print("SIGNAL UNREADABLE -- scorecard not found at %s" % SCORECARD, file=sys.stderr)
        return 1
    spec = importlib.util.spec_from_file_location("owner_text_scorecard", SCORECARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # --flag prints either "no flag: ..." (quiet) or "flag <subject> -> filed/deduped".
    rc = module.main(["--days", os.environ.get("OWNER_TEXT_SCORECARD_DAYS", "14"), "--flag"])
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
