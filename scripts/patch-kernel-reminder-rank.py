"""A reminder the owner asked for must not rank below a briefing on the badge.

The badge renders only `summary`, and `check_attention_debt` builds it from the top two
distinct headlines of four sampled held rows. `reminder:%` rows now exist (the in-app channel
routes them into the owner queue), and an unranked reason lands in the `ELSE 1` bucket beside
briefings -- so a reminder the owner himself created could be sampled out by an evening
digest. Rank it beside `urgent_email`: same priority, newest wins.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

ANCHOR = '''        "ORDER BY CASE WHEN reason = 'urgent_email' THEN 0 "
        "WHEN reason LIKE 'sync_breaker%' THEN 2 ELSE 1 END, "'''

REPLACE = '''        "ORDER BY CASE WHEN reason = 'urgent_email' THEN 0 "
        # A reminder is the owner's own item, so it ranks with the mail he asked to be
        # told about rather than with the briefings; same rank means newest wins.
        "WHEN reason LIKE 'reminder:%' THEN 0 "
        "WHEN reason LIKE 'sync_breaker%' THEN 2 ELSE 1 END, "'''


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
    count = text.count(ANCHOR)
    if count != 1:
        print(f"REFUSE: anchor count {count} (expected 1)")
        return 2
    if REPLACE in text:
        print("REFUSE: already applied")
        return 2
    SENT.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
