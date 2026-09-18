"""Surface the Amazon and eBay login need to the owner now, not at 04:00.

Both syncs were probed directly this session and returned, verbatim:
  amazon_sync -> needs_mfa   "Amazon login requires MFA. Open the Amazon download
                              script manually ... and complete the verification in
                              the browser window."
  ebay_sync   -> error       "eBay download failed (rc=1). stderr: Authentication failed."

Until this deploy, that result only reached a log line. The queue row is enqueued
HELD, so it is counted by the attention-debt check and rendered by the harness badge
(the channel the owner chose) and can never become an outbound SMS without a
deliberate change. Writes two rows, deduplicated, one per sync.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.database import _get_conn, enqueue_owner_message  # noqa: E402

DB_URL = "sqlite:///data/secretary.db"

ITEMS = [
    (
        "amazon_sync",
        "Amazon login requires MFA. Open the Amazon download script manually "
        "(`cd /home/zabz/repos/quickbooks-agent && npm run amazon:download`) and "
        "complete the verification in the browser window. The session cookie is "
        "saved for future runs.",
    ),
    (
        "ebay_sync",
        "eBay download failed: Authentication failed. The saved eBay session has "
        "expired and needs an interactive login.",
    ),
]


def main() -> int:
    conn = _get_conn(DB_URL)
    conn.row_factory = __import__("sqlite3").Row

    before = conn.execute(
        "SELECT COUNT(*) FROM owner_message_queue WHERE status='held'"
    ).fetchone()[0]
    print(f"held rows before: {before}")

    for name, detail in ITEMS:
        row_id = enqueue_owner_message(
            DB_URL,
            body=f"{name} sync needs you: {detail}",
            reason=f"sync_needs_login:{name}",
            urgency="high",
            status="held",
        )
        print(f"  enqueued {name} -> row {row_id}")

    after = conn.execute(
        "SELECT COUNT(*) FROM owner_message_queue WHERE status='held'"
    ).fetchone()[0]
    print(f"held rows after:  {after}  (delta {after - before})")

    print("\nwhat the owner's surfaces now carry:")
    for r in conn.execute(
        """SELECT id, reason, urgency, repeat_count, substr(body,1,90) AS head
           FROM owner_message_queue
           WHERE reason LIKE 'sync_needs_login:%'
           ORDER BY id"""
    ):
        print(f"  #{r['id']} [{r['urgency']}] {r['reason']}  repeat={r['repeat_count']}")
        print(f"      {r['head']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
