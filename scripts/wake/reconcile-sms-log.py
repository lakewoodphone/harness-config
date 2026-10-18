#!/usr/bin/env python3
"""Ask Twilio directly about sms_log rows whose status never closed.

WHY (docs/mesh/178 s54, s57). `reconcile-sent-status.py` reconciles a MIRROR table
(`~/.sms-inbox/inbox.db` -> `messages`). The rows the owner-facing tools read live in
`/root/authority.db` -> `sms_log`, and 27 of its outbound rows sit `queued` **with no mirror
row at all**, so no amount of mirror reconciliation can settle them. Measured 2026-10-18:
`select count(*) ... left join messages` -> 27 of 27 have no mirror row.

This asks Twilio for each unsettled SID and closes the row with the provider's own verdict.

WHAT IT WILL NOT DO
  * No time window. Age is the entire point -- the oldest unsettled row is from 2026-09-29,
    and a window is exactly what the existing reconciler used to exclude it.
  * No SQL date comparison. `reconcile-sent-status.py` documents in its own comments how
    `date_sent > datetime('now','-48 hours')` compared an RFC-2822 string to an ISO literal
    and selected 1838 of 1914 rows: bytes not dates. Nothing here filters on a date.
  * No row without a real `SM...` sid, and never a `suppressed` row: those never reached
    Twilio, so Twilio cannot have an opinion about them.
  * Dry run by default; `--apply` is the only way it writes.

Exit 3 (not 0) when credentials are missing: a reconciler that cannot ask is not a healthy
reconciler, and the estate has already been burned by a script that reported success while
measuring nothing.
"""
import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_DB = os.environ.get("SMART_DB") or "/root/authority.db"

# Statuses that mean "we do not yet know how this ended".
UNSETTLED = ("queued", "sent", "sending", "accepted", "pending", "", None)
# Twilio's vocabulary is already this table's vocabulary; anything unrecognised is left alone.
KNOWN = {"queued", "sent", "delivered", "undelivered", "failed", "receiving", "received"}


def load_env() -> dict:
    vals = dict(os.environ)
    for p in (Path.home() / "personal-secretary-mvp" / ".env",
              Path.home() / ".sms-inbox" / ".env",
              Path("/opt/company/.env")):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            continue
    return vals


def _write_status(conn: sqlite3.Connection, row_id: int, want: str,
                  attempts: int = 6) -> None:
    """Update one row, committing per row, retrying on `database is locked`.

    MEASURED 2026-10-18: the first --apply of this script died with
    `sqlite3.OperationalError: database is locked` and wrote nothing, because the authority
    database is written constantly by company-api and one lock lost the whole batch. Per-row
    commits mean a lock costs one row, not the run; the retry means it usually costs nothing.
    """
    for n in range(attempts):
        try:
            conn.execute("UPDATE sms_log SET status=?, updated_at=? WHERE id=?",
                         (want, datetime.now(timezone.utc).isoformat(), row_id))
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or n == attempts - 1:
                raise
            time.sleep(1.5 * (n + 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--db", default=APP_DB)
    a = ap.parse_args()

    env = load_env()
    # TWO ACCOUNTS, AND ASKING ONE IS NOT ASKING TWILIO. MEASURED 2026-10-18: the 23
    # unsettled rows are RECENT (2026-10-14 .. 10-18) yet every one answers HTTP 404 on the
    # MAIN account. The same sid on the FAMILY account returns HTTP 200
    # status=delivered from +17328009174 to +18482245096. So those rows were sent through a
    # different Twilio account, and no reconciler that asks only the main one can settle
    # them. Each is tried in order and the answering account is reported.
    creds = []
    for label, ak, tk in (
        ("main", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"),
        ("family", "FAMILY_CHAT_TWILIO_ACCOUNT_SID", "FAMILY_CHAT_TWILIO_AUTH_TOKEN"),
    ):
        acct, token = env.get(ak, ""), env.get(tk, "")
        if acct and token:
            creds.append((label, acct, base64.b64encode(
                ("%s:%s" % (acct, token)).encode()).decode()))
    if not creds:
        print("REFUSED: no Twilio credentials (looked in the env, ~/personal-secretary-mvp/.env,"
              " ~/.sms-inbox/.env, /opt/company/.env)")
        return 3
    print("accounts available: %s" % ", ".join(c[0] for c in creds))

    conn = sqlite3.connect(a.db, timeout=30)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, twilio_sid, status, created_at FROM sms_log "
        "WHERE direction='outbound' AND twilio_sid LIKE 'SM%%' AND (status IS NULL OR status IN (%s)) "
        "ORDER BY id LIMIT ?" % ",".join("?" * len(UNSETTLED)),
        list(UNSETTLED) + [a.limit]).fetchall()

    print("unsettled outbound rows to ask Twilio about: %d" % len(rows))
    if not rows:
        print("nothing to reconcile")
        return 0

    changed, same, refused, errors = [], 0, 0, []
    for r in rows:
        sid = r["twilio_sid"]
        d = None
        answered_by = ""
        for label, acct, auth in creds:
            url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/%s.json" % (acct, sid)
            req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read().decode("utf-8", "replace"))
                    answered_by = label
                    break
            except urllib.error.HTTPError as exc:
                # 404 here means "not this account's message", which is exactly why the
                # next account must be asked. Any other code is reported, never guessed.
                if exc.code == 404:
                    continue
                errors.append((sid, "HTTP %s on %s" % (exc.code, label)))
                break
            except Exception as exc:                               # noqa: BLE001
                errors.append((sid, "%s: %s" % (type(exc).__name__, exc)))
                break

        if d is None:
            if not any(e[0] == sid for e in errors):
                errors.append((sid, "404 on every account (%s)" % ",".join(c[0] for c in creds)))
            refused += 1
            continue

        want = str(d.get("status") or "").strip().lower()
        have = (r["status"] or "").strip().lower()
        if want not in KNOWN or want == have:
            same += 1
            continue
        changed.append((r["id"], sid, have or "(empty)", want, answered_by))

    for i, sid, have, want, who in changed[:20]:
        print("  %-6d %-34s %s -> %-9s (answered by %s)" % (i, sid, have, want, who))
    if len(changed) > 20:
        print("  ... and %d more" % (len(changed) - 20))
    for sid, why in errors[:10]:
        print("  UNANSWERED %-34s %s (left alone)" % (sid, why))

    print("to_change=%d  already_settled=%d  unanswered=%d" % (len(changed), same, refused))
    if not a.apply:
        print("\n(dry run: nothing written. use --apply)")
        return 0

    for i, sid, have, want, who in changed:
        _write_status(conn, i, want)
    left = conn.execute(
        "SELECT status, COUNT(*) c FROM sms_log WHERE direction='outbound' GROUP BY status"
        " ORDER BY c DESC").fetchall()
    print("sms_log outbound AFTER: " + ", ".join("%s=%d" % (r["status"] or "NULL", r["c"])
                                                 for r in left))
    print("RESULT: wrote %d status update(s); %d unanswered" % (len(changed), refused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
