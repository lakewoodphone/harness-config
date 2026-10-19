#!/usr/bin/env python3
"""add-k4-retry-storm-is-an-outage.py - 842 refusals of ONE body is a loop, not a policy.

MEASURED 2026-10-19 from `owner_text_decision`: 1,273 `too_long` refusals, and the count is dominated
by a handful of bodies retried hundreds of times each -

    "Check 300DDR for Fishman tickets 74114 ..."  321 chars, 842 refusals
    "CALL TOPGOLF EDISON GUEST CARE ..."          811 chars, 291 refusals
    "NJ DOL separation request ..."               390 chars,  59 refusals

Every one of those eventually reached him EXCEPT the 321-character one, and that one is not a loss of
work either: the task it referenced ("Reply to Tim Bryson - 300DDR about Ticket #74114") is `done`,
no reminder row mentions it, and 300DDR subjects reached him 14 other times.

So the class is quiet now - 0 refusals in the last day, 3 in the last 7 - and the bug that caused the
retry storm was the composing side, now fitted against the gate's own ceiling.

WHAT WAS MISSING IS THE DETECTION. A producer retrying the same body 842 times is a LOOP, and a loop
looks exactly like policy from the outside: refusals with a reason. K4 says so - one body refused more
than a handful of times inside the window is an outage of that producer, however few texts it costs
so far. Window-scoped like J1, K1 and K3.
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
# K4: a retry storm is an outage of one producer.
#
# Measured 2026-10-19: 1,273 `too_long` refusals, dominated by a few bodies retried hundreds of
# times - one 321-character reminder 842 times, an 811-character one 291 times. Each refusal is a
# sane decision about one message; 842 of them about the same message is a LOOP, and from outside the
# table a loop and a policy look identical: refusals, each with a reason.
#
# So: no single body may be refused more than RETRY_STORM_LIMIT times inside the window.
# ---------------------------------------------------------------------------------------
try:
    _q = ro(_resolve_app_db())
    try:
        _win = int(os.environ.get("RETRY_STORM_WINDOW_HOURS", "24") or 24)
        _limit = int(os.environ.get("RETRY_STORM_LIMIT", "5") or 5)
        _cut = (datetime.now(timezone.utc) - timedelta(hours=_win)).isoformat()
        _rows = _q.execute(
            "select substr(coalesce(body_head,''),1,40) h, count(*) n from owner_text_decision "
            "where allowed=0 and created_at >= ? group by 1 having count(*) > ? "
            "order by n desc limit 5", (_cut, _limit)).fetchall()
        _worst = _q.execute(
            "select substr(coalesce(body_head,''),1,40) h, count(*) n from owner_text_decision "
            "where allowed=0 and created_at >= ? group by 1 order by n desc limit 1",
            (_cut,)).fetchone()
        check("K4 no producer is retrying one body into a refusal loop",
              not _rows,
              "%d body/bodies refused more than %d times in %d h%s"
              % (len(_rows), _limit, _win,
                 ("" if not _rows else ": " + "; ".join(
                     "%.40s x%d" % (r[0], r[1]) for r in _rows))
                 + (" | worst overall: %.40s x%d" % (_worst[0], _worst[1]) if _worst else "")))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K4 no producer is retrying one body into a refusal loop", False,
          "%s: %s" % (type(exc).__name__, exc))

'''

ANCHOR = 'print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "K4 no producer is retrying" in text:
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
        print("DRY   would add K4 (a retry storm is an outage)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-k4-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
