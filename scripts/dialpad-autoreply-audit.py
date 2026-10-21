#!/usr/bin/env python3
"""AUDIT: the shop line's Dialpad native SMS auto-reply -- policy, not a defect.

WHY THIS FILE EXISTS
--------------------
Owner-queue row #901 (`owner_decision_queue`, source `dialpad-autoreply-audit`)
asked whether to turn off the auto-reply that answers texts on the shop line.
The owner ruled, verbatim:

    "dialpad autoreply i set up"        (2026-10-21)

So the auto-reply is intentional owner-configured policy. It must never again be
filed as a defect, and no audit may recommend turning it off.

The trap this file closes: the two outbound rows that triggered #901 are ONE
message stored twice in `dialpad_sms_cache` under two session_id forms
(the raw Dialpad session id and `ptf-thread-<phone>`), with the SAME message_id.
Measured on that pair: message_id 6466481996734464 on both rows, ids 1126276 and
1126282, created_at 01:17:13.382Z and 01:17:16.174Z. `app/communications_contract.py`
documents the same double-store across the table (2,744 groups / 5,488 rows).
Counting raw rows manufactures a "sent twice" defect that does not exist.

WHAT THIS FILE DOES
-------------------
Nothing but read. It carries the ruling as an explicit, named allowlist so any
audit that wakes up here finds the policy before it finds a defect, and it
reports the raw-row double-store as what it is. `--flag` deliberately files
nothing: there is no defect to file.

The "no automated customer text" rule binds OUR outbound code paths only. The
gate for those stays exactly as it is: `dialpad_customer_sms_live_sends_enabled`
is false in `settings_overrides` and this ruling does not change it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path("/root/authority.db")

QUEUE_ROW = 901
OWNER_POLICY_DATE = "2026-10-21"
OWNER_POLICY_VERBATIM = "dialpad autoreply i set up"

# The shop line's auto-reply is owner-set policy (owner, 2026-10-21, queue #901:
# "dialpad autoreply i set up"); our "no automated customer text" rule binds our
# own outbound code paths only, never Dialpad's native reply.
DIALPAD_AUTOREPLY_IS_OWNER_POLICY = True

AUTOREPLY_POLICY_ALLOWLIST = (
    {
        "queue": QUEUE_ROW,
        "ruled_on": OWNER_POLICY_DATE,
        "verbatim": OWNER_POLICY_VERBATIM,
        "scope": "Dialpad native SMS auto-reply on the shop line",
        "verdict": "policy",
    },
)


def classify(body_text: str, sender: str = "dialpad-native") -> str:
    """Classify one outbound row. The shop line's native reply is policy."""
    del body_text  # shape moves; the ruling does not
    if DIALPAD_AUTOREPLY_IS_OWNER_POLICY and sender == "dialpad-native":
        return "policy"
    return "defect"


def count_duplicate_message_ids(conn: sqlite3.Connection, days: int = 30) -> int:
    """Groups where ONE Dialpad message_id sits under two session_id forms."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT message_id
            FROM dialpad_sms_cache
           WHERE COALESCE(message_id, '') <> ''
             AND created_at >= datetime('now', ?)
           GROUP BY message_id
          HAVING COUNT(DISTINCT session_id) > 1
        )
        """,
        (f"-{int(days)} days",),
    ).fetchone()
    return int(row[0] or 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--flag",
        action="store_true",
        help="accepted for audit-shaped callers; files nothing by design",
    )
    args = ap.parse_args(argv)

    duplicates = None
    note = None
    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=10)
        try:
            duplicates = count_duplicate_message_ids(conn, args.days)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        note = f"database not read: {exc}"
        print(f"WARN {note}", file=sys.stderr)

    payload = {
        "audit": "dialpad-autoreply-audit",
        "queue": QUEUE_ROW,
        "verdict": "policy",
        "owner_verbatim": OWNER_POLICY_VERBATIM,
        "owner_ruled_on": OWNER_POLICY_DATE,
        "allowlist": [dict(entry) for entry in AUTOREPLY_POLICY_ALLOWLIST],
        "message_ids_stored_twice": duplicates,
        "filed": 0,
        "note": note,
        "writes": "none",
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"policy, not a defect: Dialpad's shop-line auto-reply is owner-set "
            f"(queue #{QUEUE_ROW}, {OWNER_POLICY_DATE}: \"{OWNER_POLICY_VERBATIM}\")."
        )
        if duplicates is not None:
            print(
                f"one message under two session_id forms: {duplicates} message_id(s) "
                f"in {args.days}d -- rows, not sends."
            )
        print("filed nothing (by design).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())