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

ONE CANONICAL TIMESTAMP, BECAUSE ONE COLUMN HOLDS TWO FORMATS
------------------------------------------------------------
`date_sent` carries at least two different formats in one column, because two
writers fill it: Twilio's REST API returns RFC-2822 ("Wed, 30 Sep 2026 16:44:20
+0000"), and the app's sms_log -- mirrored in by mirror-owner-sms.py, which maps
`created_at` onto `date_sent` -- holds ISO-8601 with microseconds
("2026-09-28T22:43:10.210640+00:00"). Measured on the live store 2026-10-13:
2189 RFC-2822 + 134 ISO-8601, 2323 rows.

SQLite compares those strings byte by byte, so `ORDER BY date_sent` is not
chronological in two independent ways: every row starting with an uppercase day
name sorts after none of them but before... nothing -- it sorts ABOVE every row
starting with a digit, and among the RFC rows the DAY OF MONTH is compared before
the month, because the month is a NAME at a later offset. Measured: ORDER BY
date_sent returns 2026-09-18 first and 'Wed, 30 Sep 2026' last, a "range" of 12
days for a store that truly spans 405 days.

`date_sent` is NEVER rewritten -- it is the provider's own testimony and the only
place the original format survives. `date_sent_utc` is added beside it, and every
ordering in this file uses it.

USAGE
    python3 ~/bin/sms-inbox.py sync              # reconcile (default; safe to cron)
    python3 ~/bin/sms-inbox.py sync --all        # FULL history, every page Twilio has
    python3 ~/bin/sms-inbox.py normalise --apply # fill the canonical UTC timestamp
    python3 ~/bin/sms-inbox.py thread            # the conversation, oldest first, true UTC
    python3 ~/bin/sms-inbox.py thread --who 8455 # one correspondent
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
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import storelock

HOME = Path.home()
ENV_FILE = Path(os.environ.get("SMS_INBOX_ENV", HOME / "personal-secretary-mvp" / ".env"))
def _app_db_path() -> Path:
    """The app's live database.

    The default used to be HOME/personal-secretary-mvp/data/secretary.db. On the
    authority that path is a stale copy with ZERO sms_log rows while the live app
    writes /root/authority.db (DATABASE_URL=sqlite:////root/authority.db). The
    sync therefore reported "app sids known: 0" and left every inbound text
    app_has_it=0 -- including texts the app had recorded. Measured 2026-10-18:
    45 inbound rows (2026-10-11 23:05 .. 2026-10-16 15:35) were all present in
    /root/authority.db sms_log and all labelled app_has_it=0.

    Prefer the authority store; keep the env override first and the old path as
    the fallback for a host that is not the authority.
    """
    override = os.environ.get("SMS_INBOX_APP_DB") or os.environ.get("OWNER_QUEUE_DB")
    if override:
        return Path(override)
    authority = Path("/root/authority.db")
    if authority.is_file():
        return authority
    return HOME / "personal-secretary-mvp" / "data" / "secretary.db"


APP_DB = _app_db_path()
# Overridable so tests never touch the live store. A test that writes the real
# inbox is a test that can lose a real text.
STORE = Path(os.environ.get("SMS_INBOX_DB", HOME / ".sms-inbox" / "inbox.db"))
AI_LINE_DEFAULT = "+17324447361"

# Fixed-width, same offset, same shape, so a plain lexicographic ORDER BY on this
# string IS chronological. Do not change the shape without re-running `normalise`.
UTC_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"


def _from_rfc(s: str):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def _from_iso(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def sent_utc(value) -> str | None:
    """Normalise ANY timestamp this column actually holds to a sortable UTC string.

    The formats present are enumerated from the data, not guessed: RFC-2822 (2189
    rows) and ISO-8601 with or without fractional seconds and with `Z` or `+HH:MM`
    (134 rows). Measured 2026-10-13: these two families cover 2323 of 2323 rows.

    Returns None for a value that is absent or that nothing parses. None is a
    REFUSAL, not a guess -- the caller must be able to see the row it could not
    read rather than have it silently placed somewhere plausible.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    d = _from_iso(s) if s[0].isdigit() else _from_rfc(s)
    if d is None:
        d = parse_dt(s)                      # the existing parser, as a fallback
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime(UTC_FORMAT)

# Our own test traffic. It sits in the same tables as real correspondence, and
# counting it as correspondence is how a freshness reading lies (audit B10). These
# are never deleted - they are excluded from the health math and named as test.
TEST_NUMBERS = {"+15555550199"}
TEST_BODY_RE = re.compile(
    r"(DSH realtime delivery check|"
    r"Lakewood Phone & Tech: Thank you for opting in|"
    r"Thanks for texting Lakewood Phone & Tech\. We'?re closed)", re.I)
TEST_OPTIN_NUMBER = "+17326552355"   # the shop's own Dialpad line confirming an opt-in


def is_test_traffic(from_number: str, body: str) -> bool:
    """Is this row our own plumbing rather than a person?"""
    num = (from_number or "").strip()
    if num in TEST_NUMBERS:
        return True
    if TEST_BODY_RE.search(body or ""):
        return True
    return False


def parse_dt(value: str):
    """Twilio sends RFC-2822 dates; some rows are ISO. Parse, never string-compare.

    Sorting `date_sent` as text put 2026 rows before 2025 rows, which made every
    freshness reading nonsense.
    """
    if not value:
        return None
    from email.utils import parsedate_to_datetime
    try:
        got = parsedate_to_datetime(value)
    except Exception:
        try:
            got = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if got is not None and got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    return got

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    sid          TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,              -- inbound | outbound
    from_number  TEXT NOT NULL,
    to_number    TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    date_sent    TEXT,                       -- AS RECEIVED; never rewritten
    date_sent_utc TEXT,                      -- normalised UTC; the ONLY sort key
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
CREATE INDEX IF NOT EXISTS idx_messages_date_utc ON messages(date_sent_utc);
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


def one_line(text: str) -> str:
    """Collapse a body to one line so a thread reads as a thread."""
    return " ".join((text or "").split())


def backfill_utc(conn: sqlite3.Connection, *, apply: bool,
                 limit: int | None = None) -> dict:
    """Fill date_sent_utc from date_sent. Idempotent; NEVER touches date_sent."""
    rows = conn.execute(
        "SELECT sid, date_sent, date_sent_utc FROM messages").fetchall()
    stats = {"total": len(rows), "already": 0, "updating": 0, "unparseable": 0}
    todo: list[tuple[str, str]] = []
    bad: list[tuple[str, str]] = []
    for r in rows:
        want = sent_utc(r["date_sent"])
        if want is None:
            stats["unparseable"] += 1
            bad.append((r["sid"], r["date_sent"]))
            continue
        if r["date_sent_utc"] == want:
            stats["already"] += 1
            continue
        todo.append((want, r["sid"]))
    stats["updating"] = len(todo)
    if limit is not None:
        stats["limited_to"] = limit
        todo = todo[:limit]
    wrote = 0
    if apply and todo:
        conn.executemany(
            "UPDATE messages SET date_sent_utc=? WHERE sid=?", todo)
        conn.commit()
        wrote = len(todo)
    return {"stats": stats, "unparseable_rows": bad, "wrote": wrote}


def ensure_utc_column(conn: sqlite3.Connection, *, backfill: bool = True) -> None:
    """Make date_sent_utc exist AND be filled, on any command.

    Deliberately self-healing: a store built before this column existed is repaired
    by the next ordinary run instead of by an operator remembering a migration, and
    a store that is already correct writes nothing. A locked store must never make a
    read command fail, so the fill is best-effort and silent about failure.

    MUST be called BEFORE executescript(SCHEMA): the schema carries an index on
    date_sent_utc, and SQLite cannot resolve that index against a pre-existing
    `messages` table that does not have the column yet. On a brand-new store the
    table does not exist at all, so there is nothing to alter and SCHEMA creates it
    with the column already in place.
    """
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "messages" not in tables:
            return
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        if "date_sent_utc" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN date_sent_utc TEXT")
            conn.commit()
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_date_utc "
                     "ON messages(date_sent_utc)")
        conn.commit()
        if not backfill:
            return                 # so `normalise` without --apply is TRULY dry
        res = backfill_utc(conn, apply=True)
        if res["wrote"]:
            print(f"  date_sent_utc: filled {res['wrote']} row(s)", file=sys.stderr)
    except sqlite3.Error as exc:
        print(f"  date_sent_utc: could not ensure ({exc})", file=sys.stderr)


def connect(*, backfill: bool = True) -> sqlite3.Connection:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(STORE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_utc_column(conn, backfill=backfill)
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


MAX_PAGES_RUNAWAY_GUARD = 200


def fetch_messages(cfg: dict, *, direction: str, pages: int | None,
                   max_pages: int = MAX_PAGES_RUNAWAY_GUARD) -> list[dict]:
    """Pull one direction from Twilio.

    `pages=None` walks EVERY page Twilio has, up to `max_pages` as a runaway guard.
    That is what makes the store complete instead of a fixed slice: the cron ran
    `sync --pages 3` against a PageSize of 200, a 600-message window, while Twilio
    held 11,903 outbound messages for this line -- so 9,989 of them (measured
    2026-10-13) had never been seen, and a fresh message could be pushed out of the
    window and lost for ever.

    PageSize is 1000, Twilio's own maximum, so a full walk of this line is 13
    requests instead of 60. Every request keeps its own 60s socket timeout.
    """
    sid = cfg["TWILIO_ACCOUNT_SID"]
    tok = cfg["TWILIO_AUTH_TOKEN"]
    line = cfg.get("TWILIO_PHONE_NUMBER") or AI_LINE_DEFAULT
    key = "To" if direction == "inbound" else "From"
    out: list[dict] = []
    params = {key: line, "PageSize": 1000}
    path = "Messages.json"
    hard = max_pages if pages is None else min(pages, max_pages)
    for _ in range(hard):
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


@storelock.locked_write
def upsert(conn: sqlite3.Connection, msgs: list[dict], known: set[str]) -> int:
    added = 0
    for m in msgs:
        sid = str(m.get("sid") or "")
        if not sid:
            continue
        direction = _direction(m)
        raw = str(m.get("date_sent") or m.get("date_created") or "")
        cur = conn.execute(
            """INSERT OR IGNORE INTO messages
               (sid, direction, from_number, to_number, body, date_sent,
                date_sent_utc, status, num_media, price, first_seen, app_has_it)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid,
                direction,
                str(m.get("from") or ""),
                str(m.get("to") or ""),
                str(m.get("body") or ""),
                raw,
                sent_utc(raw),
                str(m.get("status") or ""),
                int(m.get("num_media") or 0),
                str(m.get("price") or ""),
                now(),
                1 if sid in known else 0,
            ),
        )
        added += cur.rowcount
        # CONVERGE ON THE TRUTH for the fields the PROVIDER owns.
        #
        # This used to be INSERT OR IGNORE and nothing else, so an existing row
        # froze at the status it carried the instant it was first seen: `queued`
        # stayed `queued` for ever and became indistinguishable from never sent
        # (that is the fault reconcile-sent-status.py exists to paper over, and it
        # only chases queued/sending/accepted/undefined -- never a `failed`).
        # The window is deliberately narrow: `date_sent`, `body`, `from_number`,
        # `to_number`, `num_media` and `first_seen` are NEVER rewritten, because
        # the raw timestamp is the only place the original format survives.
        if cur.rowcount == 0:
            conn.execute(
                """UPDATE messages
                      SET status = CASE WHEN ? <> '' THEN ? ELSE status END,
                          price  = CASE WHEN ? <> '' THEN ? ELSE price  END,
                          app_has_it = CASE WHEN ? = 1 THEN 1 ELSE app_has_it END
                    WHERE sid = ?""",
                (
                    str(m.get("status") or ""), str(m.get("status") or ""),
                    str(m.get("price") or ""), str(m.get("price") or ""),
                    1 if sid in known else 0,
                    sid,
                ),
            )
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
    # Make sure the v2 tables exist before anything reads them. The responder and
    # the context resolver both depend on `jobs` and `person`; creating them here
    # means a fresh machine is coherent after one sync rather than after one
    # surprised failure inside the responder.
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "textstore", str(Path(__file__).resolve().parent / "textstore.py"))
        if _spec:
            _ts = _ilu.module_from_spec(_spec)
            sys.modules.setdefault("textstore", _ts)
            _spec.loader.exec_module(_ts)
            made = _ts.ensure_schema(conn)
            if made.get("created"):
                print(f"  schema: created {made['created']}")
    except Exception as exc:
        print(f"  schema: textstore unavailable ({exc}) - continuing without it")
    known = app_sids()
    print(f"AI line: {line}   store: {STORE}   app sids known: {len(known)}")
    total_new = 0
    for direction in ("inbound", "outbound"):
        try:
            msgs = fetch_messages(cfg, direction=direction,
                                  pages=None if args.all else args.pages)
        except Exception as exc:
            print(f"  {direction}: Twilio read FAILED: {exc}")
            continue
        have = {r[0] for r in conn.execute("SELECT sid FROM messages")}
        # TWO DIFFERENT GAPS, AND THEY ARE NOT THE SAME THING.
        #
        # STORE GAP is the one that loses a text: Twilio holds a message the store
        # does not. It can only see as far back as the pull actually reaches, which
        # is exactly why `sync --all` is required for the number to mean anything
        # (measured 2026-10-13: the `--pages 3` window reaches back about a day
        # while Twilio held 9,989 outbound messages the store had never seen, back
        # to 2025-09-08).
        #
        # APP GAP is what this loop used to print under the bare name `GAP`, and it
        # means only that the APP's own sms_log does not hold the sid -- NOT that
        # anything is missing from this store. Measured 2026-10-13: of the 406
        # `GAP:` lines one run printed, 405 were already in the store. Reprinted
        # every five minutes it buried the real gap under 207,025 false lines and
        # made sync.log 24 MB, so it now speaks only when the exact set CHANGES.
        store_gap = [m for m in msgs if str(m.get("sid") or "") not in have]
        added = upsert(conn, msgs, known)
        total_new += added
        print(f"  {direction}: {len(msgs)} from Twilio, {added} new")
        if store_gap:
            print(f"    STORE GAP: {len(store_gap)} of those are NOT in the store "
                  f"- run `sync --all` to backfill")
            for m in store_gap[:20]:
                print("      %s  %s -> %s  %r"
                      % (m.get("date_sent") or m.get("date_created"), m.get("from"),
                         m.get("to"), (m.get("body") or "")[:60]))
            if len(store_gap) > 20:
                print(f"      ... and {len(store_gap) - 20} more")
        app_gap = [m for m in msgs
                   if str(m.get("sid") or "") and str(m.get("sid") or "") not in known
                   and _direction(m) == "inbound"]
        digest = hashlib.sha256(
            "\n".join(sorted(str(m.get("sid")) for m in app_gap)).encode()
        ).hexdigest()[:16]
        seen_key = "gap_digest:" + direction
        prior = conn.execute("SELECT value FROM sync_state WHERE key=?",
                             (seen_key,)).fetchone()
        if app_gap and (prior is None or prior["value"] != digest):
            print(f"    APP GAP: {len(app_gap)} inbound text(s) the APP's own sms_log "
                  f"never recorded (this store HAS them) - first sighting of this set")
            for m in app_gap[:20]:
                print("      %s  %s -> %s  %r"
                      % (m.get("date_sent") or m.get("date_created"), m.get("from"),
                         m.get("to"), (m.get("body") or "")[:60]))
            if len(app_gap) > 20:
                print(f"      ... and {len(app_gap) - 20} more")
        conn.execute("INSERT OR REPLACE INTO sync_state(key,value) VALUES(?,?)",
                     (seen_key, digest))
    with storelock.store_lock(storelock.store_of(conn)):
        conn.execute(
            "INSERT OR REPLACE INTO sync_state(key,value) VALUES('last_sync',?)", (now(),)
        )
        conn.commit()
    stats = conn.execute(
        "SELECT direction, COUNT(*) n FROM messages GROUP BY direction"
    ).fetchall()
    print("  store now: " + ", ".join(f"{r['direction']}={r['n']}" for r in stats))
    print(f"  new this run: {total_new}")
    span = conn.execute(
        "SELECT min(date_sent_utc) lo, max(date_sent_utc) hi FROM messages").fetchone()
    raw = conn.execute(
        "SELECT min(date_sent) lo, max(date_sent) hi FROM messages").fetchone()
    if span and span["lo"]:
        print(f"  true range {span['lo']} .. {span['hi']}")
        print(f"  (ORDER BY date_sent would claim {raw['lo']} .. {raw['hi']})")
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
              AND COALESCE(o.date_sent_utc, o.date_sent)
                  > COALESCE(m.date_sent_utc, m.date_sent)
          )
        ORDER BY COALESCE(m.date_sent_utc, m.date_sent) DESC
        """
    ).fetchall()


def cmd_probe(args) -> int:
    """Is this line actually alive, and is anyone still waiting?

    Exits non-zero when the line looks dead or when anything is undecided. An empty
    result here is a refusal to look, not health: the whole reason this exists is
    that `0 to decide` printed forever while three people waited (audit B1, lesson
    L2099).
    """
    conn = connect()
    rows = conn.execute("SELECT * FROM messages WHERE direction='inbound'").fetchall()
    real = [r for r in rows if not is_test_traffic(r["from_number"], r["body"])]

    stamped = [(parse_dt(r["date_sent"]), r) for r in real]
    stamped = [(d, r) for d, r in stamped if d is not None]
    stamped.sort(key=lambda p: p[0])

    print(f"store      {STORE}")
    try:
        last_sync = conn.execute(
            "SELECT value FROM sync_state WHERE key='last_sync'").fetchone()
        print(f"last sync  {last_sync['value'] if last_sync else '(never)'}")
    except sqlite3.Error:
        print("last sync  (unreadable)")
    print(f"inbound    {len(real)} real of {len(rows)} rows "
          f"({len(rows)-len(real)} test row(s) excluded)")
    if not stamped:
        print("VERDICT    no parseable inbound at all - the sensor may be blind")
        return 2

    newest_d, newest = stamped[-1]
    hours = (datetime.now(timezone.utc) - newest_d).total_seconds() / 3600
    print(f"newest     {newest['date_sent']}  ({hours:.1f}h ago)  {newest['from_number']}")
    if hours < 0:
        print("           ^ a timestamp in the FUTURE - clock skew or a bad parse")
    for r in [r for _, r in stamped[-3:]][::-1]:
        print(f"           {r['from_number']:<15} [{r['state']}] {(r['body'] or '')[:50]!r}")

    undecided = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE direction='inbound' AND state='new'"
    ).fetchone()[0]
    print(f"undecided  {undecided}")

    # Anyone with a real inbound and no reply after it.
    lastout = {}
    for r in conn.execute("SELECT to_number, date_sent FROM messages WHERE direction='outbound'"):
        t = "".join(ch for ch in (r["to_number"] or "") if ch.isdigit())[-10:]
        d = parse_dt(r["date_sent"])
        if t and d and (t not in lastout or d > lastout[t]):
            lastout[t] = d
    waiting = []
    for d, r in stamped:
        t = "".join(ch for ch in (r["from_number"] or "") if ch.isdigit())[-10:]
        if t and (t not in lastout or lastout[t] < d):
            waiting.append((d, r))
    print(f"waiting    {len(waiting)} real text(s) with no reply after them")
    for d, r in waiting[-10:]:
        print(f"           {d.isoformat()[:16]}  {r['from_number']:<15} "
              f"{(r['body'] or '')[:60]!r}")

    verdict_ok = hours <= 72 and undecided == 0
    print(f"VERDICT    {'alive' if verdict_ok else 'NEEDS ATTENTION'}"
          + ("" if hours <= 72 else f" - newest real inbound is {hours:.0f}h old"))
    return 0 if verdict_ok else 1


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
           ORDER BY COALESCE(date_sent_utc, date_sent) DESC"""
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
               MAX(COALESCE(i.date_sent_utc, i.date_sent)) AS last_at
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
           ORDER BY COALESCE(date_sent_utc, date_sent) ASC""",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    print(f"{len(rows)} message(s) matching {args.query!r}")
    for r in rows:
        arrow = "->" if r["direction"] == "outbound" else "<-"
        print(
            "%s  %s %s\n    %s"
            % (r["date_sent_utc"] or r["date_sent"], arrow, r["from_number"],
               (r["body"] or "")[:400])
        )
    return 0


def cmd_thread(args) -> int:
    """The conversation as it actually happened: oldest first, true UTC, both sides.

    Sorted in PYTHON on a PARSED value rather than by SQL on the raw column, so the
    reader is correct even against a store that has not been normalised yet. A
    reader whose order depends on someone having remembered to run a migration is a
    reader that lies quietly until they do.
    """
    conn = connect()
    if args.who:
        q = norm(args.who)
        rows = conn.execute(
            "SELECT * FROM messages WHERE from_number LIKE ? OR to_number LIKE ?",
            (f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM messages").fetchall()

    stamped, unparsed = [], []
    for r in rows:
        d = parse_dt(r["date_sent"])
        if d is None:
            unparsed.append(r)
            continue
        stamped.append((d.astimezone(timezone.utc), r))
    stamped.sort(key=lambda p: p[0])
    # Stable tie-break so two messages in the same second never swap between runs.
    stamped.sort(key=lambda p: (p[0], p[1]["sid"]))

    what = f"matching {args.who!r}" if args.who else "in the store"
    print(f"{len(stamped)} message(s) {what}")
    if stamped:
        lo = stamped[0][0].strftime("%Y-%m-%dT%H:%M:%SZ")
        hi = stamped[-1][0].strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"true range {lo} .. {hi}")
    if unparsed:
        print(f"{len(unparsed)} row(s) had no parseable date_sent and are NOT in the "
              f"order below - named, not hidden:")
        for r in unparsed[:20]:
            print(f"   {r['sid']}  {r['date_sent']!r}  {(r['body'] or '')[:40]!r}")

    n = max(1, args.limit)
    head = stamped[:n]
    tail = stamped[-n:] if len(stamped) > n else []
    for label, block in (("FIRST", head), ("LAST", tail)):
        if not block:
            continue
        print(f"\n--- {label} {len(block)} of the real range ---")
        for d, r in block:
            arrow = "->" if r["direction"] == "outbound" else "<-"
            peer = r["from_number"] if r["direction"] == "inbound" else r["to_number"]
            print("%s  %s  %-15s [%s] %s"
                  % (d.strftime("%Y-%m-%dT%H:%M:%SZ"), arrow, peer, r["state"],
                     one_line(r["body"])[:args.width]))
    return 0


def cmd_normalise(args) -> int:
    """Fill the canonical sortable timestamp. Safe to re-run; never touches date_sent.

    Dry by default. Prints the rows it CANNOT parse instead of placing them
    somewhere plausible, because an unparseable row silently ordered is a message
    silently in the wrong place in a conversation.
    """
    conn = connect(backfill=False)
    res = backfill_utc(conn, apply=args.apply, limit=args.limit)
    s = res["stats"]
    print(f"messages rows     : {s['total']}")
    print(f"already canonical : {s['already']}")
    print(f"to update         : {s['updating']}")
    print(f"UNPARSEABLE       : {s['unparseable']}")
    if res["unparseable_rows"]:
        print("  no known format parses these; date_sent_utc stays NULL and they are")
        print("  excluded from every ordered read rather than guessed into place:")
        for sid, raw in res["unparseable_rows"][:50]:
            print(f"     {sid}  {raw!r}")
    print(f"wrote             : {res['wrote']}")
    if not args.apply:
        print("\n(dry run: nothing written. use --apply)")
        return 0
    span = conn.execute(
        "SELECT min(date_sent_utc) lo, max(date_sent_utc) hi FROM messages").fetchone()
    raw = conn.execute(
        "SELECT min(date_sent) lo, max(date_sent) hi FROM messages").fetchone()
    print(f"\ntrue range        : {span['lo']} .. {span['hi']}")
    print(f"ORDER BY date_sent claims {raw['lo']} .. {raw['hi']}")
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


@storelock.locked_store(STORE)
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


@storelock.locked_store(STORE)
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
    s.add_argument("--all", action="store_true",
                   help="walk EVERY page Twilio has, not just --pages (full history)")
    s.set_defaults(func=cmd_sync)
    s = sub.add_parser("normalise")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_normalise)
    s = sub.add_parser("thread")
    s.add_argument("--who", default=None,
                   help="phone or name fragment; omit for every message in the store")
    s.add_argument("--limit", type=int, default=20, help="how many of each end to show")
    s.add_argument("--width", type=int, default=72)
    s.set_defaults(func=cmd_thread)
    s = sub.add_parser("report"); s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_report)
    sub.add_parser("gaps").set_defaults(func=cmd_gaps)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
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
