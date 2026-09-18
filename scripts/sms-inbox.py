#!/usr/bin/env python3
"""The texting inbox: every SMS to and from the secretary's own line, in one
place, reconciled against Twilio so nothing is ever lost.

WHY THIS EXISTS
---------------
On 2026-09-18 the inbound path was found to be dropping real texts. Twilio's own
record for +17324447361 showed inbound messages on 2026-09-07/08/09 - including
"Is this an automatic ai generated text or legitimate questions?" and "My car is
not starting" - and journalctl showed the matching requests dying with
`Unhandled error on /webhook/twilio/sms: database is locked` and
`HTTP/1.1 500 Internal Server Error`. Twilio does NOT retry an inbound SMS
webhook after a 5xx, so those messages were gone: not in sms_log, not in
memory, no reply, nobody told. Silence to a person, twice over.

Twilio keeps the message. So the fix is not a cleverer webhook - it is to treat
Twilio as the log of record and reconcile against it. That is what this script
does, and it is deliberately a standalone ~/bin ops script rather than a change
to the app: the deployed tree was 119 commits ahead / 176 behind origin with
uncommitted edits to app/main.py, so an additive sensor runs today and the
in-app writer can be fixed deliberately, later, with the app's own git story.

WHAT IT DOES
------------
1. Pulls inbound and outbound messages for the AI line from Twilio's REST API.
2. Upserts them into its own SQLite store, keyed on MessageSid, so a message is
   recorded exactly once however many times it is seen.
3. Cross-checks the app's own sms_log and records whether the app has the
   message - so a text that reached Twilio but never reached the app is visible
   as a GAP rather than as silence.
4. Reports unanswered inbound, and who is waiting.
5. Holds the permission ledger: who Zabz may answer, and how freely.

It never sends anything. Read-only against Twilio.

USAGE
    python3 ~/bin/sms-inbox.py sync              # reconcile (default; safe to cron)
    python3 ~/bin/sms-inbox.py report            # who is waiting on a reply
    python3 ~/bin/sms-inbox.py threads           # one line per correspondent
    python3 ~/bin/sms-inbox.py show <phone|name> # the conversation
    python3 ~/bin/sms-inbox.py permissions       # the ledger
    python3 ~/bin/sms-inbox.py allow <phone> --name X --relationship family \
        --allow auto --note "brother; may answer directly"
    python3 ~/bin/sms-inbox.py deny  <phone> --note "why"
    python3 ~/bin/sms-inbox.py gaps              # texts the app never recorded
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
ENV_FILE = HOME / "personal-secretary-mvp" / ".env"
APP_DB = HOME / "personal-secretary-mvp" / "data" / "secretary.db"
STORE = HOME / ".sms-inbox" / "inbox.db"
AI_LINE_DEFAULT = "+17324447361"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    sid          TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,              -- inbound | outbound
    from_number  TEXT NOT NULL,
    to_number    TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    date_sent    TEXT,                       -- Twilio's date_sent, ISO-ish
    status       TEXT,
    num_media    INTEGER DEFAULT 0,
    price        TEXT,
    first_seen   TEXT NOT NULL,
    app_has_it   INTEGER,                    -- 1/0/NULL(unknown): in sms_log?
    state        TEXT NOT NULL DEFAULT 'new',-- new|seen|answered|queued|ignored
    decided_by   TEXT,
    decided_at   TEXT,
    reason       TEXT,
    reply_sid    TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date_sent);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_number);
CREATE INDEX IF NOT EXISTS idx_messages_state ON messages(state);

CREATE TABLE IF NOT EXISTS permissions (
    phone         TEXT PRIMARY KEY,          -- E.164
    name          TEXT,
    relationship  TEXT,                      -- owner|family|friend|customer|vendor|unknown
    allow         TEXT NOT NULL,             -- auto | queue | never
    note          TEXT DEFAULT '',
    learned_from  TEXT DEFAULT '',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# --------------------------------------------------------------------------- #
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def env() -> dict:
    out: dict[str, str] = {}
    if not ENV_FILE.is_file():
        sys.exit(f"no {ENV_FILE}")
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def connect() -> sqlite3.Connection:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(STORE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def twilio_get(sid: str, tok: str, path: str, **params) -> dict:
    url = "https://api.twilio.com/2010-04-01/Accounts/%s/%s" % (sid, path)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header(
        "Authorization",
        "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode(),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def norm(p: str) -> str:
    """Last 10 digits, so +1 845 555 0100 and 8455550100 compare equal."""
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


def fetch_messages(cfg: dict, *, direction: str, pages: int) -> list[dict]:
    sid = cfg["TWILIO_ACCOUNT_SID"]
    tok = cfg["TWILIO_AUTH_TOKEN"]
    line = cfg.get("TWILIO_PHONE_NUMBER") or AI_LINE_DEFAULT
    key = "To" if direction == "inbound" else "From"
    out: list[dict] = []
    params = {key: line, "PageSize": 200}
    path = "Messages.json"
    for _ in range(pages):
        data = twilio_get(sid, tok, path, **params)
        out.extend(data.get("messages", []))
        nxt = data.get("next_page_uri")
        if not nxt:
            break
        path = nxt.lstrip("/").replace("2010-04-01/Accounts/%s/" % sid, "")
        params = {}
    return out


def app_sids() -> set[str]:
    """MessageSids the app itself recorded. Read-only; never writes the app DB."""
    if not APP_DB.is_file():
        return set()
    try:
        conn = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True, timeout=10)
        rows = conn.execute(
            "SELECT twilio_sid FROM sms_log WHERE twilio_sid IS NOT NULL"
        ).fetchall()
        conn.close()
        return {str(r[0]) for r in rows if r[0]}
    except Exception as exc:
        print(f"  (could not read the app's sms_log: {exc})", file=sys.stderr)
        return set()


def upsert(conn: sqlite3.Connection, msgs: list[dict], known: set[str]) -> int:
    added = 0
    for m in msgs:
        sid = str(m.get("sid") or "")
        if not sid:
            continue
        direction = _direction(m)
        cur = conn.execute(
            """INSERT OR IGNORE INTO messages
               (sid, direction, from_number, to_number, body, date_sent, status,
                num_media, price, first_seen, app_has_it)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid,
                direction,
                str(m.get("from") or ""),
                str(m.get("to") or ""),
                str(m.get("body") or ""),
                str(m.get("date_sent") or m.get("date_created") or ""),
                str(m.get("status") or ""),
                int(m.get("num_media") or 0),
                str(m.get("price") or ""),
                now(),
                1 if sid in known else 0,
            ),
        )
        added += cur.rowcount
        # Keep app_has_it honest as the app's own log catches up.
        if sid in known:
            conn.execute("UPDATE messages SET app_has_it=1 WHERE sid=?", (sid,))
    conn.commit()
    return added


def _direction(m: dict) -> str:
    """Twilio's own call: a message from us is outbound."""
    frm = norm(str(m.get("from") or ""))
    ai = norm(env().get("TWILIO_PHONE_NUMBER") or AI_LINE_DEFAULT)
    return "outbound" if frm == ai else "inbound"


# --------------------------------------------------------------------------- #
def cmd_sync(args) -> int:
    cfg = env()
    line = cfg.get("TWILIO_PHONE_NUMBER") or AI_LINE_DEFAULT
    conn = connect()
    known = app_sids()
    print(f"AI line: {line}   store: {STORE}   app sids known: {len(known)}")
    total_new = 0
    for direction in ("inbound", "outbound"):
        try:
            msgs = fetch_messages(cfg, direction=direction, pages=args.pages)
        except Exception as exc:
            print(f"  {direction}: Twilio read FAILED: {exc}")
            continue
        added = upsert(conn, msgs, known)
        total_new += added
        print(f"  {direction}: {len(msgs)} from Twilio, {added} new")
        for m in msgs:
            sid = str(m.get("sid") or "")
            if sid and sid not in known and _direction(m) == "inbound":
                print(
                    "    GAP: %s  %s -> %s  %r"
                    % (
                        m.get("date_sent") or m.get("date_created"),
                        m.get("from"),
                        m.get("to"),
                        (m.get("body") or "")[:60],
                    )
                )
    conn.execute(
        "INSERT OR REPLACE INTO sync_state(key,value) VALUES('last_sync',?)", (now(),)
    )
    conn.commit()
    stats = conn.execute(
        "SELECT direction, COUNT(*) n FROM messages GROUP BY direction"
    ).fetchall()
    print("  store now: " + ", ".join(f"{r['direction']}={r['n']}" for r in stats))
    print(f"  new this run: {total_new}")
    return 0


def unanswered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Inbound messages with no outbound message to that correspondent since."""
    return conn.execute(
        """
        SELECT m.* FROM messages m
        WHERE m.direction='inbound'
          AND NOT EXISTS (
            SELECT 1 FROM messages o
            WHERE o.direction='outbound'
              AND o.to_number LIKE '%' || substr(m.from_number, -10) || '%'
              AND o.date_sent > m.date_sent
          )
        ORDER BY m.date_sent DESC
        """
    ).fetchall()


def cmd_report(args) -> int:
    conn = connect()
    rows = unanswered(conn)
    print(f"{len(rows)} inbound message(s) with no reply after them")
    if rows:
        print()
        for r in rows[: args.limit]:
            app = {1: "app YES", 0: "app MISSED", None: "app ?"}[
                None if r["app_has_it"] is None else int(r["app_has_it"])
            ]
            print(
                "%-22s %-14s [%s] %s"
                % (r["date_sent"] or "?", r["from_number"], app, (r["body"] or "")[:70])
            )
    print()
    gaps = conn.execute(
        "SELECT COUNT(*) n FROM messages WHERE direction='inbound' AND app_has_it=0"
    ).fetchone()["n"]
    print(f"inbound texts Twilio has that the app never recorded: {gaps}")
    return 0


def cmd_gaps(args) -> int:
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM messages WHERE direction='inbound' AND app_has_it=0
           ORDER BY date_sent DESC"""
    ).fetchall()
    print(f"{len(rows)} inbound text(s) reached Twilio but never reached the app")
    for r in rows:
        print("  %s  %s  %r" % (r["date_sent"], r["from_number"], (r["body"] or "")[:70]))
    return 0


def cmd_threads(args) -> int:
    conn = connect()
    rows = conn.execute(
        """
        SELECT i.from_number AS who,
               COUNT(*) AS incoming,
               (SELECT COUNT(*) FROM messages o
                 WHERE o.direction='outbound'
                   AND substr(o.to_number,-10) = substr(i.from_number,-10)) AS outgoing,
               MAX(i.date_sent) AS last_at
        FROM messages i
        WHERE i.direction='inbound'
        GROUP BY i.from_number
        ORDER BY last_at DESC
        """
    ).fetchall()
    print(f"{len(rows)} correspondent(s)")
    for r in rows:
        print(
            "  %-16s in=%-4s out=%-4s last=%s"
            % (r["who"], r["incoming"], r["outgoing"], r["last_at"])
        )
    return 0


def cmd_show(args) -> int:
    conn = connect()
    q = norm(args.query)
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE from_number LIKE ? OR to_number LIKE ?
           ORDER BY date_sent ASC""",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    print(f"{len(rows)} message(s) matching {args.query!r}")
    for r in rows:
        arrow = "->" if r["direction"] == "outbound" else "<-"
        print(
            "%s %s %s\n    %s"
            % (r["date_sent"], arrow, r["from_number"], (r["body"] or "")[:400])
        )
    return 0


def cmd_permissions(args) -> int:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM permissions ORDER BY relationship, name"
    ).fetchall()
    if not rows:
        print("permission ledger is EMPTY - nobody may be answered automatically")
        return 0
    print(f"{len(rows)} row(s)")
    for r in rows:
        print(
            "  %-16s %-22s %-9s %-6s %s"
            % (r["phone"], r["name"] or "-", r["relationship"] or "-",
               r["allow"], (r["note"] or "")[:50])
        )
    return 0


def cmd_allow(args) -> int:
    conn = connect()
    conn.execute(
        """INSERT INTO permissions(phone,name,relationship,allow,note,learned_from,updated_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(phone) DO UPDATE SET
             name=excluded.name, relationship=excluded.relationship,
             allow=excluded.allow, note=excluded.note,
             learned_from=excluded.learned_from, updated_at=excluded.updated_at""",
        (args.phone, args.name, args.relationship, args.allow, args.note,
         args.learned_from, now()),
    )
    conn.commit()
    print(f"{args.phone}: allow={args.allow} ({args.relationship})")
    return 0


def cmd_deny(args) -> int:
    conn = connect()
    conn.execute(
        """INSERT INTO permissions(phone,name,relationship,allow,note,learned_from,updated_at)
           VALUES(?,?,?,'never',?,?,?)
           ON CONFLICT(phone) DO UPDATE SET allow='never', note=excluded.note,
             updated_at=excluded.updated_at""",
        (args.phone, args.name, args.relationship, args.note, "deny", now()),
    )
    conn.commit()
    print(f"{args.phone}: allow=never")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("sync"); s.add_argument("--pages", type=int, default=5)
    s.set_defaults(func=cmd_sync)
    s = sub.add_parser("report"); s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_report)
    sub.add_parser("gaps").set_defaults(func=cmd_gaps)
    sub.add_parser("threads").set_defaults(func=cmd_threads)
    s = sub.add_parser("show"); s.add_argument("query"); s.set_defaults(func=cmd_show)
    sub.add_parser("permissions").set_defaults(func=cmd_permissions)
    s = sub.add_parser("allow")
    s.add_argument("phone"); s.add_argument("--name", default=None)
    s.add_argument("--relationship", default="unknown")
    s.add_argument("--allow", default="queue", choices=["auto", "queue", "never"])
    s.add_argument("--note", default=""); s.add_argument("--learned-from", default="owner")
    s.set_defaults(func=cmd_allow)
    s = sub.add_parser("deny")
    s.add_argument("phone"); s.add_argument("--name", default=None)
    s.add_argument("--relationship", default="unknown"); s.add_argument("--note", default="")
    s.set_defaults(func=cmd_deny)
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["sync"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
