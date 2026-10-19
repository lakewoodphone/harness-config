#!/usr/bin/env python3
"""add-k3-gate-error-is-an-outage.py - the gate failing closed 2,780 times raised no alarm.

MEASURED 2026-10-19, from `owner_text_decision` itself:

    ok                 allowed=1  3827
    gate_error         allowed=0  2780   <-- all of them in the first five days of October
    awaiting_reply     allowed=0  1315
    too_long           allowed=0  1273

Every `gate_error` row carries the same sentence:

    "the owner-text ledger is unreadable (TypeError: getattr expected at most 3 arguments,
     got 7); refusing to send rather than sending blind"

So ONE internal bug - a `getattr` called with seven arguments - made `app/owner_text.gate()` raise on
every owner send for five days. The broad `except Exception` around the gate body is deliberate and
the direction is right per message: refuse rather than send blind. **In aggregate it is a channel
outage**, and nothing escalated: 2,780 refusals, no alarm, and the texts that went missing were
`urgent_email` (2,564) and `reminder:N` (216).

No seven-argument `getattr` exists in the code now, so the bug is history. What was missing is the
DETECTION, and that is what K3 adds: any `gate_error` decision inside the window means the gate is
refusing for a reason that is not a policy - it is an outage of the channel, however few texts it
cost so far.

Window-scoped like J1 and K1: the historical 2,780 are reported, and only a fresh one fails.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/text-health.py")

CHECK = '''
# ---------------------------------------------------------------------------------------
# K3: a gate_error is an outage, not a policy refusal.
#
# Measured 2026-10-19 from owner_text_decision: 2,780 rows with code `gate_error`, EVERY ONE in the
# first five days of October, all saying the same thing - the owner-text ledger was unreadable
# because of a getattr called with seven arguments. One internal bug made the gate raise on every
# owner send for five days; the broad `except` refused rather than sending blind, which is right per
# message and, in aggregate, is a channel outage. Nothing escalated.
#
# `ok` (3827) and the policy codes - awaiting_reply, too_long, rate_floor, similar_hold - are the
# gate working. `gate_error` is the gate BROKEN. It gets its own invariant so the next occurrence is
# a red check within a day rather than a number found five months later.
# ---------------------------------------------------------------------------------------
try:
    _q = ro(_resolve_app_db())
    try:
        _win = int(os.environ.get("GATE_ERROR_WINDOW_DAYS", "1") or 1)
        _cut = (datetime.now(timezone.utc) - timedelta(days=_win)).isoformat()
        _recent = _q.execute(
            "select count(*) from owner_text_decision "
            "where code='gate_error' and created_at >= ?", (_cut,)).fetchone()[0]
        _total = _q.execute(
            "select count(*) from owner_text_decision where code='gate_error'").fetchone()[0]
        _why = _q.execute(
            "select why from owner_text_decision where code='gate_error' "
            "order by created_at desc limit 1").fetchone()
        check("K3 the owner-text gate is not refusing because it is broken",
              _recent == 0,
              "%d gate_error decision(s) in the last %d day(s); %d all-time. %s"
              % (_recent, _win, _total,
                 ("Most recent: %s" % str(_why[0])[:150]) if _why else "none on record"))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K3 the owner-text gate is not refusing because it is broken", False,
          "%s: %s" % (type(exc).__name__, exc))

'''

ANCHOR = 'print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "K3 the owner-text gate is not refusing" in text:
        print("OK    already applied")
        return 0
    if text.count(ANCHOR) != 1:
        print("FAIL  print anchor found %d times" % text.count(ANCHOR))
        return 1
    out = text.replace(ANCHOR, CHECK + ANCHOR, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add K3 (a gate_error is an outage)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-k3-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
