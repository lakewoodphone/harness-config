"""The critical line must state the newest *critical* age, not the newest row's.

Caught immediately after applying the freshness patch, by reading the output rather than
trusting it: the summary said "2 critical message(s) held, newest 0.1d old" while
`held_critical_fresh` was 0 and the newest held row (3.4 h) was the evening briefing.
The age came from the newest held row of *any* urgency, so a six-day-old critical alert
was reported as a tenth of a day old -- a wrong number on the one line the owner reads,
which is precisely the failure mode this system has been burned by twice.

Fix: track the newest age per urgency and use the critical one on the critical line.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

ANCHOR = '''    now = pv.now()
    fresh_critical = 0
    fresh_urgent = 0
    newest_age_h: float | None = None
    for row in (dict(r) for r in (held_ages.value or [])):
        seen = pv.parse_stamp(row.get("seen_at")) if row.get("seen_at") else None
        if seen is None:
            continue
        age_h = (now - seen).total_seconds() / 3600
        newest_age_h = age_h if newest_age_h is None else min(newest_age_h, age_h)
        if age_h <= FRESH_CRITICAL_HOURS:
            if str(row.get("urgency")) == "critical":
                fresh_critical += 1
            elif str(row.get("urgency")) == "urgent":
                fresh_urgent += 1'''

REPLACE = '''    now = pv.now()
    fresh_critical = 0
    fresh_urgent = 0
    newest_age_h: float | None = None
    newest_critical_age_h: float | None = None
    for row in (dict(r) for r in (held_ages.value or [])):
        seen = pv.parse_stamp(row.get("seen_at")) if row.get("seen_at") else None
        if seen is None:
            continue
        age_h = (now - seen).total_seconds() / 3600
        newest_age_h = age_h if newest_age_h is None else min(newest_age_h, age_h)
        urgency = str(row.get("urgency"))
        if urgency == "critical":
            # Per-urgency, because the newest held row is usually *not* the critical one:
            # reporting the overall newest age beside a critical count said "2 critical
            # held, newest 0.1d old" when those two were six days old.
            newest_critical_age_h = (
                age_h
                if newest_critical_age_h is None
                else min(newest_critical_age_h, age_h)
            )
            if age_h <= FRESH_CRITICAL_HOURS:
                fresh_critical += 1
        elif urgency == "urgent" and age_h <= FRESH_CRITICAL_HOURS:
            fresh_urgent += 1'''

ANCHOR2 = '''        "newest_held_age_hours": (
            round(newest_age_h, 1) if newest_age_h is not None else None
        ),'''

REPLACE2 = '''        "newest_held_age_hours": (
            round(newest_age_h, 1) if newest_age_h is not None else None
        ),
        "newest_critical_age_hours": (
            round(newest_critical_age_h, 1)
            if newest_critical_age_h is not None
            else None
        ),'''

ANCHOR3 = '''        age_note = (
            f", newest {newest_age_h/24:.1f}d old" if newest_age_h is not None else ""
        )'''

REPLACE3 = '''        age_note = (
            f", newest {newest_critical_age_h/24:.1f}d old"
            if newest_critical_age_h is not None
            else ""
        )'''

EDITS = [
    (ANCHOR, REPLACE, "per-urgency newest age"),
    (ANCHOR2, REPLACE2, "expose it in metrics"),
    (ANCHOR3, REPLACE3, "the critical line uses the critical age"),
]


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if new in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)
        print(f"planned  {label}")
    SENT.write_text(text, encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
