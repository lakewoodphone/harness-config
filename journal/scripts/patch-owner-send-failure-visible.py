#!/usr/bin/env python3
"""A failed owner SMS was completely silent, so 42 undelivered alerts looked like health.

MEASURED on secratary 2026-09-15, pain P6 ("held messages and unanswered questions rot
silently"). The owner-message flush runs at most once a minute, takes the two NEWEST held rows,
and ends:

    res = send_message(settings=self._settings, to=owner_phone, body=body)
    if res.get("ok"):
        mark_owner_message_sent(self._db_url, mid)
    # <- no else

So a failed send logs nothing, counts nothing and changes nothing. The visible consequence:

  * 162 rows sat `held`;
  * `owner_sms_allowed` admits only urgent/critical (threshold "urgent"), so the 95 `ask_owner`
    rows -- all `normal`, the oldest from 2026-05-29 -- can never be sent, and they are 95 of
    the 162;
  * 42 held rows WERE sendable, including an urgent evening briefing sitting at position 2 of
    the flush order, re-attempted thousands of times over 5.7 hours and still held;
  * 2 messages were sent in 7 days, and nothing anywhere recorded a reason.

Twilio credentials are configured and `sms_log` shows successful sends, so the transport works;
the failure is real, specific, and unrecorded -- which is the defect this fixes.

WHAT THIS DOES NOT DO, on purpose: it does not change the selection. The flush only ever
attempts the two newest held rows, so everything older is starved, and widening that would cause
owner SMS to be sent that is not being sent today. Outbound is the owner's call and needs his
per-message word, so the starvation is reported to him rather than fixed underneath him.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_COLS = '''        if "last_seen_at" not in cols:
            conn.execute("ALTER TABLE owner_message_queue ADD COLUMN last_seen_at TEXT")
        conn.commit()'''

NEW_COLS = '''        if "last_seen_at" not in cols:
            conn.execute("ALTER TABLE owner_message_queue ADD COLUMN last_seen_at TEXT")
        # Delivery attempts and their last error. Added 2026-09-15: a failed owner SMS left
        # no trace anywhere -- no log, no counter, no status change -- so 42 undelivered
        # urgent/critical alerts read exactly like health. A message that cannot be sent
        # must say so on its own row.
        if "send_attempts" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN send_attempts INTEGER DEFAULT 0"
            )
        if "last_send_error" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN last_send_error TEXT"
            )
        conn.commit()'''

FUNC = '''def record_owner_message_send_failure(
    db_url: str,
    message_id: int,
    reason: str,
) -> bool:
    """Record that an owner message could not be sent, and why.

    Added 2026-09-15. The flush had no failure branch, so a send that failed was
    indistinguishable from one that was never attempted: it stayed `held`, was retried at the
    same position in the queue forever, and nothing surfaced the reason. Measured at the time:
    42 urgent/critical messages held and unsent, an urgent briefing re-attempted thousands of
    times over 5.7 hours with no recorded cause, and 2 messages sent in 7 days.
    """
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET send_attempts = COALESCE(send_attempts, 0) + 1, "
            "last_send_error = ?, last_seen_at = ? "
            "WHERE id = ?",
            (str(reason or "")[:300], now, int(message_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_owner_message_status('''

OLD_FLUSH = '''        from app.database import (
            list_owner_message_queue,
            mark_owner_message_sent,
            mark_owner_message_status,
        )'''
NEW_FLUSH = '''        from app.database import (
            list_owner_message_queue,
            mark_owner_message_sent,
            mark_owner_message_status,
            record_owner_message_send_failure,
        )'''

OLD_SEND = '''            res = send_message(settings=self._settings, to=owner_phone, body=body)
            if res.get("ok"):
                mark_owner_message_sent(self._db_url, mid)'''
NEW_SEND = '''            res = send_message(settings=self._settings, to=owner_phone, body=body)
            if res.get("ok"):
                mark_owner_message_sent(self._db_url, mid)
            else:
                # This branch did not exist. A failed send was silent -- no log, no counter,
                # no status change -- so 42 undelivered urgent/critical alerts were
                # indistinguishable from health, and the message sat at the front of the
                # flush order being retried indefinitely with nobody able to say why.
                reason = str(
                    res.get("error")
                    or res.get("detail")
                    or res.get("status")
                    or "unknown"
                )[:300]
                logger.warning(
                    "owner SMS send failed for message %s (urgency=%s): %s",
                    mid,
                    urgency,
                    reason,
                )
                try:
                    record_owner_message_send_failure(self._db_url, mid, reason)
                except Exception as exc:  # noqa: BLE001 - never break the flush
                    logger.debug("could not record owner message send failure: %s", exc)'''

TEST = '''"""A failed owner SMS must leave a trace on its own row.

Measured on secratary 2026-09-15: the flush had no failure branch, so 42 undelivered
urgent/critical owner messages looked exactly like health, and an urgent briefing was retried
thousands of times over 5.7 hours with no recorded reason.
"""

import sqlite3

from app.database import record_owner_message_send_failure

SCHEMA = """
create table owner_message_queue (
    id integer primary key, body text, reason text, urgency text, status text,
    created_at text, repeat_count integer, last_seen_at text,
    send_attempts integer, last_send_error text
);
"""


def _scratch(tmp_path):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "insert into owner_message_queue (id, body, reason, urgency, status, created_at, "
        "send_attempts) values (1, 'x', 'sync_breaker:ebay_sync', 'urgent', 'held', "
        "'2026-09-15T00:00:00+00:00', 0)"
    )
    con.commit()
    con.close()
    return str(path)


def test_a_failure_is_counted_and_explained(tmp_path):
    url = _scratch(tmp_path)
    assert record_owner_message_send_failure(url, 1, "Twilio credentials not configured")
    con = sqlite3.connect(url)
    attempts, err = con.execute(
        "select send_attempts, last_send_error from owner_message_queue where id=1"
    ).fetchone()
    assert attempts == 1
    assert "credentials" in err


def test_attempts_accumulate(tmp_path):
    url = _scratch(tmp_path)
    for i in range(3):
        record_owner_message_send_failure(url, 1, f"failure {i}")
    con = sqlite3.connect(url)
    attempts, err = con.execute(
        "select send_attempts, last_send_error from owner_message_queue where id=1"
    ).fetchone()
    assert attempts == 3
    assert err == "failure 2"          # the most recent reason wins


def test_a_missing_row_is_reported_not_raised(tmp_path):
    url = _scratch(tmp_path)
    assert record_owner_message_send_failure(url, 999, "nope") is False


def test_the_flush_records_failures_and_still_does_not_widen_its_selection():
    """Two properties, asserted on the source because both are about control flow.

    (1) a failed send is recorded -- the missing branch was the defect;
    (2) the selection is still `held, limit=2` -- widening it would send owner SMS that is
        not sent today, and outbound is the owner's decision, not mine.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "autopilot.py").read_text(
        encoding="utf-8"
    )
    assert "record_owner_message_send_failure(self._db_url, mid, reason)" in src
    assert 'status="held",\n            limit=2,' in src or 'status="held", limit=2' in src, (
        "the flush's selection changed; that would send messages nobody authorised"
    )
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")
    ap = pathlib.Path("app/autopilot.py")
    asrc = ap.read_text(encoding="utf-8")

    assert src.count(OLD_COLS) == 1, f"cols: {src.count(OLD_COLS)}"
    assert src.count("def mark_owner_message_status(") == 1
    assert "record_owner_message_send_failure" not in src
    assert asrc.count(OLD_FLUSH) == 1, f"import: {asrc.count(OLD_FLUSH)}"
    assert asrc.count(OLD_SEND) == 1, f"send: {asrc.count(OLD_SEND)}"

    for rel in ("app/database.py", "app/autopilot.py"):
        backup = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak17"
        if not backup.exists():
            shutil.copy(rel, backup)

    src = src.replace(OLD_COLS, NEW_COLS).replace(
        "def mark_owner_message_status(", FUNC, 1
    )
    db.write_text(src, encoding="utf-8")
    asrc = asrc.replace(OLD_FLUSH, NEW_FLUSH).replace(OLD_SEND, NEW_SEND)
    ap.write_text(asrc, encoding="utf-8")
    print("patched: failure columns, recorder, and the flush's missing else-branch")

    pathlib.Path("tests/test_owner_send_failure_is_recorded.py").write_text(
        TEST, encoding="utf-8"
    )
    print("wrote tests/test_owner_send_failure_is_recorded.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
