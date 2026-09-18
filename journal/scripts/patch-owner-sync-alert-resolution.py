"""Resolve a subsystem's owner alerts when that subsystem succeeds.

Measured 2026-09-15: amazon_sync and ebay_sync raised `sync_needs_login:*` rows
at 16:49 on 2026-09-14. The sessions were re-authenticated at 04:01/04:15 the next
morning and a real sync ingested transactions at 04:30 (transactions.captured_at
newest = 2026-09-15T04:30:06). The two `urgent` rows still sat `held` that
afternoon, counted by the kernel's attention_debt check and rendered on the
owner's badge as work waiting for him.

The emitters already funnel through one place -- `_record_subsystem(name,
success=...)` on every sync outcome -- so binding the clear to the same signal
that raises the alert keeps the pair from drifting apart.

(Patch-script lesson from the previous attempt in this session: accumulate edits
per file on a running copy of the text; writing every replacement from one
validated snapshot silently keeps only the last edit per file.)
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path.home() / "personal-secretary-mvp"
DB = REPO / "app" / "database.py"
AUTO = REPO / "app" / "autopilot.py"

DB_ANCHOR = "def mark_owner_message_sent("
DB_BLOCK = '''def clear_owner_sync_alerts(
    db_url: str,
    subsystem: str,
    *,
    evidence: str = "",
) -> int:
    """Resolve the sync alerts a subsystem raised, now that it has succeeded.

    Added 2026-09-15. amazon_sync and ebay_sync each raised a
    `sync_needs_login:*` row when their saved browser sessions expired, and
    nothing ever cleared one: both sessions were re-authenticated on the morning
    of 2026-09-15, a real sync ingested transactions at 04:30, and the two
    `urgent` rows were still `held` that afternoon -- counted by the kernel's
    attention-debt check and shown on the owner's badge as work waiting for him.
    An alert whose condition is gone is not an alert; it is a false reading that
    spends the owner's attention.

    Called from the one place every sync outcome passes through, so the alert and
    its clear cannot drift apart. Returns the number of rows resolved.
    """
    name = str(subsystem or "").strip()
    if not name:
        return 0
    conn = _get_conn(db_url)
    note = f"resolved: {name} succeeded"
    if str(evidence or "").strip():
        note = f"{note} ({str(evidence).strip()[:160]})"
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        try:
            cur = conn.execute(
                "UPDATE owner_message_queue SET status = 'resolved', status_note = ? "
                "WHERE status IN ('held', 'queued') AND (reason = ? OR reason = ?)",
                (note, f"sync_needs_login:{name}", f"sync_breaker:{name}"),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - never break the caller's health record
            _log.warning("clear_owner_sync_alerts(%s) failed: %s", name, exc)
            return 0
    return int(cur.rowcount or 0)


'''
DB_REPLACE = DB_BLOCK + DB_ANCHOR

AUTO_CALL_ANCHOR = '''            else:
                entry["consecutive_empty_ticks"] = 0
        else:
            entry["failures"] += 1'''
AUTO_CALL_REPLACE = '''            else:
                entry["consecutive_empty_ticks"] = 0
            # A subsystem that succeeds must clear the alerts it raised, or they
            # outlive their cause forever (see clear_owner_sync_alerts). Only the
            # five browser syncs enqueue `sync_*:<name>` rows, and each of them
            # reports through here.
            if str(name).endswith("_sync"):
                self._resolve_owner_sync_alerts(str(name), detail)
        else:
            entry["failures"] += 1'''

AUTO_METHOD_ANCHOR = '''        except Exception as exc:  # noqa: BLE001
            logger.debug("sync login nudge failed (%s): %s", name, exc)'''
AUTO_METHOD_REPLACE = AUTO_METHOD_ANCHOR + '''

    def _resolve_owner_sync_alerts(self, name: str, detail: str = "") -> None:
        """Clear this sync's owner alerts, because it just worked.

        The counterpart to _notify_owner_sync_needs_login. Measured 2026-09-15:
        amazon_sync and ebay_sync had been re-authenticated and had ingested real
        transactions hours earlier, while their `urgent` rows were still counted as
        owner-attention debt -- the badge was telling the owner to fix something
        that was already fixed.
        """
        try:
            from app.database import clear_owner_sync_alerts

            cleared = clear_owner_sync_alerts(
                self._settings.database_url, name, evidence=detail
            )
            if cleared:
                logger.info(
                    "autopilot: cleared %d owner alert(s) after %s succeeded", cleared, name
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("sync alert clear failed (%s): %s", name, exc)'''

EDITS = {
    DB: [(DB_ANCHOR, DB_REPLACE, "database.py: clear_owner_sync_alerts")],
    AUTO: [
        (AUTO_CALL_ANCHOR, AUTO_CALL_REPLACE, "autopilot.py: call it on sync success"),
        (AUTO_METHOD_ANCHOR, AUTO_METHOD_REPLACE, "autopilot.py: the resolver method"),
    ],
}


def main() -> int:
    plans = []
    for path, edits in EDITS.items():
        text = path.read_text(encoding="utf-8")
        for old, new, label in edits:
            count = text.count(old)
            if count != 1:
                print(f"REFUSE {label}: anchor count {count} (expected 1)")
                return 2
            if new in text:
                print(f"REFUSE {label}: replacement already present")
                return 2
            text = text.replace(old, new, 1)
            print(f"planned  {label}")
        plans.append((path, text))

    for path, text in plans:
        path.write_text(text, encoding="utf-8")
        print(f"WROTE {path}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
