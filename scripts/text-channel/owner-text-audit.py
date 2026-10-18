#!/usr/bin/env python3
"""AUDIT: the owner text channel as eight hard numbers and a ranked defect list.

WHY THIS EXISTS
---------------
The owner asked, verbatim, that the texting back-and-forth system be
"constantly learning and optimizing itself", and that the autonomous wake system
"every week or two" audit and evolve it. This file is the instrument that audit
runs on. It reads the channel's OWN history and turns it into numbers, so a woken
session can fix the worst defect instead of re-reading 500 texts.

WHAT IT READS (read-only, always, `mode=ro`)
--------------------------------------------
    /root/authority.db            sms_log, owner_text_turn, owner_decision_queue,
                                  owner_message_queue (only to recover a truncated
                                  original whose ref points at it)
    /root/.owner-text/relay.db    attempt, ask
    /root/.cfo-asks/asks.db       clarification
The owner's number is +18483897895, compared on DIGITS only, so a stored
`18483897895` and `+18483897895` are the same person.

THE ONE THING THAT MUST NOT BE GOT WRONG
----------------------------------------
`sms_log` logs the same outbound send TWICE with the SAME `twilio_sid`. Measured
2026-10-18 on the authority: 1809 outbound rows in the 14-day window carried only
91 distinct sids. Every number below therefore says whether it counts ROWS or
DISTINCT SIDS, and `repeat_index` counts distinct sids -- otherwise the duplicate
LOGGING would manufacture a fake repeat for every message he ever received, which
is the opposite of what an audit is for.

EXIT CODES
----------
    0   ran; every metric computed (finding a defect is not a failure of the
        instrument, so defects alone do not change the code)
    2   ran, but at least one data source was unreachable/unreadable. The metric
        that needed it is `null` with a `reason`; every other metric still
        reports, and the unmeasured metrics are named on stderr.
    3   usage error (bad --days/--since, --json together with --flag, ...)

Every metric is independently failable: one broken query nulls that metric and
nothing else. A number is NEVER printed that was not read.

THE FLAG
--------
`--flag` is the only side effect, and it fires ONLY when a measured defect
breaches a threshold in THRESHOLDS below. Nothing on a timer may file work merely
because time passed. When nothing breaches it prints
`no flag: all metrics within threshold` and files nothing.

RUN
    python3 owner-text-audit.py                     # human report, 14 days
    python3 owner-text-audit.py --json --days 14    # one JSON object
    python3 owner-text-audit.py --flag              # file a flag IF a threshold
                                                    # is breached, else nothing
    python3 owner-text-audit.py --flag --dry-run    # print the brief, file nothing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# THE THRESHOLDS. Reviewable on purpose: this dict is the whole judgement of
# what counts as a defect, and every entry means `metric > value`.
#
# Why each number is what it is (WEEKLY-AUDIT.md carries the same table):
#   double_sends        > 0   he may never receive the same words twice. Zero
#                             tolerance: the same body twice inside two minutes
#                             is visible to him and is pure noise. Live 2026-10-18.
#   silent_outcomes     > 0   a row stuck pending/queued past 6h is a message we
#                             believe we sent and did not. There is no acceptable
#                             number of messages that vanished, so zero.
#   unanswered_backlog  > 0   a question he has not answered in 48h is either a
#                             question that should never have been asked or a gate
#                             now blocking the channel. Either way, a defect: zero.
#   max_repeat          > 1   a body delivered more than once in the window. One
#                             delivery is the healthy maximum, so >1 is a repeat.
#   internal_asks       > 2   the system asked him something it then answered
#                             itself. One or two can be a legitimate fallback; a
#                             pattern means the ask should have been resolved
#                             before it reached him. 2 is the tolerated count.
#   refusal_rate        > 0.5 more than half of everything we tried to send was
#                             suppressed. Below half, suppression is doing its
#                             job; above it the channel mostly generates text it
#                             then refuses to send, which is the "36 items,
#                             18 urgent" failure wearing a different coat.
# --------------------------------------------------------------------------- #
THRESHOLDS = {
    "double_sends": 0,
    "silent_outcomes": 0,
    "unanswered_backlog": 0,
    "max_repeat": 1,
    "internal_asks": 2,
    "refusal_rate": 0.5,
}

OWNER = "+18483897895"
OWNER_DIGITS = "18483897895"

SILENT_HOURS = 6           # relay pending/queued older than this = silent outcome
BACKLOG_HOURS = 48         # owner_text_turn unanswered longer than this = backlog
EXPIRY_DAYS = 7            # an answer later than sent+7d answered an expired gate
DOUBLE_SEND_SECONDS = 120  # two sends of one body inside this = a double send
TOP_N = 10                 # repeated bodies listed

# Values of `ask.answered_by` / `clarification.answered_via` that mean "the owner
# answered it". `owner` is the symbolic alias the ledger actually writes --
# measured 2026-10-18: every answered `ask` row carries the string 'owner', never
# the number, so a literal comparison with the number alone would call all of
# them foreign.
OWNER_ALIASES = {"owner", "him", "the owner", OWNER, OWNER_DIGITS}

# A row from a self-test is not a production failure. `wake.py` marks its own
# with kind='selftest'; the relay and CFO stores mark them in the ref/body.
SELFTEST_MARKERS = ("selftest", "proof-", "selftest-")

# "A CFO/USD-amount question": a money amount with cents, or an explicit currency
# form. The 2-decimal form is what the CFO door actually writes -- measured
# 2026-10-18: "CFO [ask-1792163692]: what was 114.04 at adjust membership fee".
CURRENCY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d{1,2})?"
    r"|\b\d{1,3}(?:,\d{3})*\.\d{2}\b"
    r"|\b\d[\d,]*\s?(?:USD|dollars?|bucks)\b",
    re.IGNORECASE,
)
TRUNCATION_MARKERS = ("cut short", "[cut")
ELLIPSIS = "\u2026"


# --------------------------------------------------------------------------- #
# paths -- read AT CALL TIME, so a test can point them at a temporary database
# --------------------------------------------------------------------------- #
def _path(env: str, default: str) -> Path:
    return Path(os.environ.get(env) or default)


def authority_db() -> Path:
    return _path("OWNER_TEXT_AUDIT_AUTHORITY_DB", "/root/authority.db")


def relay_db() -> Path:
    return _path("OWNER_TEXT_AUDIT_RELAY_DB", "/root/.owner-text/relay.db")


def cfo_db() -> Path:
    return _path("OWNER_TEXT_AUDIT_CFO_DB", "/root/.cfo-asks/asks.db")


def wake_cli() -> Path:
    return Path(os.environ.get("WAKE_PY") or "/home/zabz/bin/wake.py")


DB_PATHS = {"authority": authority_db, "relay": relay_db, "cfo": cfo_db}


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class Unreadable(Exception):
    """The signal behind one metric could not be read. It becomes null + reason."""


# --------------------------------------------------------------------------- #
# small helpers, in the shape of ~/bin/sources/_flag.py
# --------------------------------------------------------------------------- #
def ro_connect(path: Path) -> sqlite3.Connection:
    """Open a database strictly read-only.

    A sensor that can write the thing it watches is a sensor that can corrupt it.
    `mode=ro` also turns a missing or locked database into an error HERE rather
    than a surprise write later.
    """
    if not path.is_file():
        raise Unreadable(f"no database at {path}")
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise Unreadable(f"cannot open {path}: {exc}") from exc


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def require_table(conn: sqlite3.Connection, name: str, where: str) -> None:
    if not table_exists(conn, name):
        raise Unreadable(f"no {name} table in {where}")


def parse_dt(raw) -> datetime | None:
    """Parse the several timestamp shapes this system really writes.

    Seen in the wild: '2026-10-18T01:33:42.514819+00:00',
    '2026-10-16T15:14:52.544194Z', '2026-10-16T15:14:52+00:00' (no fraction) and
    a bare naive form. A naive value is read as UTC, which is what every writer
    in this estate means by one.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            value = parsedate_to_datetime(text)
        except Exception:                                     # noqa: BLE001
            return None
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalise(body) -> str:
    """The repeat key: lowercase, whitespace collapsed."""
    return " ".join(str(body or "").lower().split())


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def is_owner(number) -> bool:
    return digits(number).endswith(OWNER_DIGITS)


def fmt(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def iso(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def iso_ms(dt: datetime | None) -> str | None:
    """Millisecond precision, for evidence where two rows share a second."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if dt else None


def iso_week(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def snippet(body, limit: int = 120) -> str:
    return " ".join(str(body or "").split())[:limit]


def value_counts(values) -> dict:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# the audit context
# --------------------------------------------------------------------------- #
class Audit:
    """One run: the window and the three connections, opened lazily."""

    def __init__(self, since: datetime, until: datetime, days: int,
                 since_label: str = "--days"):
        self.since = since
        self.until = until
        self.days = days
        self.since_label = since_label
        self.now = until
        self._conns: dict[str, sqlite3.Connection] = {}

    def conn(self, which: str) -> sqlite3.Connection:
        if which not in self._conns:
            self._conns[which] = ro_connect(DB_PATHS[which]())
        return self._conns[which]

    def close(self) -> None:
        for conn in self._conns.values():
            try:
                conn.close()
            except Exception:                                  # noqa: BLE001
                pass
        self._conns.clear()

    def in_window(self, raw) -> datetime | None:
        dt = parse_dt(raw)
        if dt is None or dt < self.since or dt > self.until:
            return None
        return dt

    def windowed(self, rows, col: str) -> list[tuple[datetime, sqlite3.Row]]:
        """Rows whose `col` parses inside the window, oldest first.

        Filtering happens in Python rather than in SQL ON PURPOSE. `created_at`
        is written in more than one shape ('2026-10-18T01:33:42.514819+00:00',
        '2026-10-18T00:53:43.212034+00:00', '...Z'), and SQLite's TEXT comparison
        puts a space-form timestamp BEFORE a T-form one on the same day, so a SQL
        `>=` bound silently drops rows at the boundary. `parse_dt` is the one
        reading of a timestamp this file trusts.
        """
        out = []
        for row in rows:
            dt = self.in_window(row[col])
            if dt is not None:
                out.append((dt, row))
        out.sort(key=lambda pair: pair[0])
        return out


# --------------------------------------------------------------------------- #
# metric 1 -- delivery
# --------------------------------------------------------------------------- #
DELIVERY_SQL = """
SELECT id, twilio_sid, direction, from_number, to_number, status, created_at
  FROM sms_log
"""


def m_delivery(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "sms_log", str(authority_db()))
    rows = conn.execute(DELIVERY_SQL).fetchall()

    outbound, inbound = [], 0
    for row in rows:
        dt = a.in_window(row["created_at"])
        if dt is None:
            continue
        direction = str(row["direction"]).lower()
        if direction == "inbound":
            inbound += 1
            continue
        if direction != "outbound" or not is_owner(row["to_number"]):
            continue
        outbound.append((dt, row))

    delivered_rows = [r for _, r in outbound
                      if str(r["status"]).lower() in ("delivered", "sent")]
    delivered_sids = {
        str(r["twilio_sid"]) for r in delivered_rows if (r["twilio_sid"] or "").strip()
    }
    refused_rows = [r for _, r in outbound if str(r["status"]).lower() == "suppressed"]
    failed_rows = [r for _, r in outbound if str(r["status"]).lower() == "failed"]
    failed_sids = {str(r["twilio_sid"]) for r in failed_rows
                   if (r["twilio_sid"] or "").strip()}

    delivered, refused, failed = len(delivered_sids), len(refused_rows), len(failed_rows)

    # The denominator mixes DISTINCT SIDS with ROWS on purpose, because the
    # metric definition says so: `delivered` is deduped (a twice-logged send is
    # one delivery) while `refused` is rows (a suppressed row carries no sid at
    # all -- measured: 814 suppressed rows, 0 distinct sids). Printed with the
    # numbers so nobody reads the rate as a homogeneous ratio.
    denominator = delivered + refused + failed
    refusal_rate = (refused / denominator) if denominator else None

    return {
        "value": {
            "delivered": delivered,
            "refused": refused,
            "failed": failed,
            "inbound": inbound,
            "refusal_rate": refusal_rate,
        },
        "raw": {
            "sql": DELIVERY_SQL.strip(),
            "filter": ("direction='outbound', to_number == +18483897895 (digits), "
                       "created_at inside the window; inbound counted separately"),
            "window": {"since": iso(a.since), "until": iso(a.until)},
            "outbound_rows_to_owner": len(outbound),
            "outbound_distinct_sids_to_owner": len({
                str(r["twilio_sid"]) for _, r in outbound
                if (r["twilio_sid"] or "").strip()}),
            "delivered_rule": ("COUNT(DISTINCT twilio_sid) where status in "
                               "(delivered,sent) and sid non-empty"),
            "delivered_rows_not_deduped": len(delivered_rows),
            "duplicate_log_rows_collapsed": len(delivered_rows) - delivered,
            "failed_rows": failed,
            "failed_distinct_sids": len(failed_sids),
            "refused_rows": refused,
            "refused_distinct_sids": len({
                str(r["twilio_sid"]) for r in refused_rows
                if (r["twilio_sid"] or "").strip()}),
            "refusal_rate_formula": f"{refused} / ({delivered} + {refused} + {failed})",
            "refusal_rate_units_note": ("numerator and the refused/failed terms are "
                                        "ROWS; the delivered term is DISTINCT SIDS"),
            "inbound_rows": inbound,
            "status_counts": value_counts(
                [str(r["status"]).lower() for _, r in outbound]),
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 2 -- repeat_index
# --------------------------------------------------------------------------- #
REPEAT_SQL = """
SELECT id, twilio_sid, body, status, created_at, to_number
  FROM sms_log
 WHERE direction = 'outbound'
"""


def m_repeat_index(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "sms_log", str(authority_db()))
    rows = [r for r in conn.execute(REPEAT_SQL).fetchall() if is_owner(r["to_number"])]
    windowed = a.windowed(rows, "created_at")

    # One send = one sid. A row with no sid was never a send (suppressed rows
    # carry no sid at all), so it cannot be a repeat of anything.
    groups: dict[str, dict] = {}
    rows_without_sid = 0
    for dt, row in windowed:
        sid = (row["twilio_sid"] or "").strip()
        if not sid:
            rows_without_sid += 1
            continue
        key = normalise(row["body"])
        if not key:
            continue
        entry = groups.setdefault(key, {"sids": {}, "body": row["body"]})
        # A sid seen twice is the duplicate LOG, not a second send.
        entry["sids"].setdefault(sid, dt)

    repeated = []
    for key, entry in groups.items():
        count = len(entry["sids"])
        if count > 1:
            times = sorted(entry["sids"].values())
            repeated.append({
                "body": snippet(entry["body"], 120),
                "count": count,
                "first": iso(times[0]),
                "last": iso(times[-1]),
                "sids": sorted(entry["sids"])[:5],
            })
    repeated.sort(key=lambda e: (-e["count"], e["first"] or ""))
    max_repeat = max((e["count"] for e in repeated), default=0)

    return {
        "value": {"repeat_index": repeated[:TOP_N], "max_repeat": max_repeat},
        "raw": {
            "sql": REPEAT_SQL.strip() + "  -- then owner + window filtered in Python",
            "rule": ("a body is repeated when it was carried by MORE THAN ONE DISTINCT "
                     "twilio_sid to the owner inside the window; rows sharing a sid are "
                     "the duplicate log, not a second send"),
            "outbound_rows_to_owner_in_window": len(windowed),
            "rows_without_sid_skipped": rows_without_sid,
            "distinct_bodies": len(groups),
            "bodies_with_more_than_one_send": len(repeated),
            "max_repeat": max_repeat,
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 3 -- double_sends
# --------------------------------------------------------------------------- #
OWNER_DOUBLE_SQL = """
SELECT id, twilio_sid, body, status, created_at, to_number
  FROM sms_log
 WHERE direction = 'outbound'
"""
RELAY_DOUBLE_SQL = """
SELECT attempt_id, at, door, body, sid, status, verdict, verdict_reason, to_number
  FROM attempt
"""


def _pairs_within(items, seconds: int) -> list[dict]:
    """items: [(dt, ident, sid, body[, recipient])] -> consecutive same-body pairs.

    A pair only counts as a duplicate send when the recipient is the same. Entries may carry a
    fifth element (the recipient); when both sides have one and they differ, the two rows are
    one message to two people -- correct behaviour, not a duplicate. Measured 2026-10-18: the
    seven pairs this metric found in `relay.attempt` were exactly that, because the family_chat
    door posts one leg to the owner and one to a family member, and the ledger had no recipient
    column to tell them apart.
    """
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            dt_i, id_i, sid_i, body_i = items[i][:4]
            dt_j, id_j, sid_j, _ = items[j][:4]
            rec_i = items[i][4] if len(items[i]) > 4 else None
            rec_j = items[j][4] if len(items[j]) > 4 else None
            if rec_i and rec_j and rec_i != rec_j:
                continue
            delta = abs((dt_j - dt_i).total_seconds())
            if delta > seconds or sid_i == sid_j:
                continue
            pairs.append({
                "delta_seconds": round(delta, 3),
                "a": {"id": id_i, "sid": sid_i, "at": iso(dt_i),
                      "at_precise": iso_ms(dt_i)},
                "b": {"id": id_j, "sid": sid_j, "at": iso(dt_j),
                      "at_precise": iso_ms(dt_j)},
                "body": snippet(body_i, 100),
            })
    pairs.sort(key=lambda p: p["delta_seconds"])
    return pairs


def _group_by_body(entries) -> dict:
    groups: dict[str, list] = {}
    for entry in entries:
        dt, ident, sid, body = entry[:4]
        key = normalise(body)
        if not key:
            continue
        groups.setdefault(key, []).append(entry)
    for key in groups:
        groups[key].sort(key=lambda e: e[0])
    return groups


def m_double_sends(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "sms_log", str(authority_db()))
    rows = [r for r in conn.execute(OWNER_DOUBLE_SQL).fetchall()
            if is_owner(r["to_number"])]

    owner_entries = []
    for dt, row in a.windowed(rows, "created_at"):
        sid = (row["twilio_sid"] or "").strip()
        if not sid or str(row["status"]).lower() == "suppressed":
            continue
        owner_entries.append((dt, row["id"], sid, row["body"]))
    owner_pairs = []
    for group in _group_by_body(owner_entries).values():
        owner_pairs.extend(_pairs_within(group, DOUBLE_SEND_SECONDS))

    # The relay half is not optional: the relay is the owner-text relay, and its
    # family_chat door posts one leg to the owner and one to a family member -- so a naive
    # same-body pair count reports correct behaviour as a defect. The recipient is part of the
    # identity of a send; when it is missing (legacy rows, written before 2026-10-18) the pair
    # cannot be judged and is reported separately rather than counted.
    rconn = a.conn("relay")
    require_table(rconn, "attempt", str(relay_db()))
    relay_sql = RELAY_DOUBLE_SQL
    try:
        cols = {r[1] for r in rconn.execute("PRAGMA table_info(attempt)")}
    except Exception:                                   # noqa: BLE001
        cols = set()
    if "to_number" not in cols:
        # An older store, or a store whose migration has not run yet. Report the pairs as
        # unjudgeable instead of asserting a defect the ledger cannot support.
        relay_sql = RELAY_DOUBLE_SQL.replace(", to_number", "")
    relay_entries = []
    unjudgeable = []
    for dt, row in a.windowed(rconn.execute(relay_sql).fetchall(), "at"):
        sid = (row["sid"] or "").strip()
        if not sid or str(row["status"]).lower() in ("pending", "failed"):
            continue
        try:
            recipient = (row["to_number"] or "").strip()
        except (IndexError, KeyError):
            recipient = ""
        entry = (dt, row["attempt_id"], sid, row["body"], recipient or None)
        if recipient:
            relay_entries.append(entry)
        else:
            unjudgeable.append(entry)
    relay_pairs = []
    for group in _group_by_body(relay_entries).values():
        relay_pairs.extend(_pairs_within(group, DOUBLE_SEND_SECONDS))

    worst = sorted(owner_pairs + relay_pairs, key=lambda p: p["delta_seconds"])
    total = len(owner_pairs) + len(relay_pairs)

    return {
        "value": {
            "total": total,
            "owner_sms_log": len(owner_pairs),
            "relay_attempt": len(relay_pairs),
            "worst": worst[0] if worst else None,
            "pairs": worst[:5],
        },
        "raw": {
            "owner_sql": OWNER_DOUBLE_SQL.strip(),
            "relay_sql": RELAY_DOUBLE_SQL.strip(),
            "rule": (f"same normalised body, DISTINCT twilio_sid/sid, |delta| <= "
                     f"{DOUBLE_SEND_SECONDS}s; owner half from sms_log rows to "
                     f"{OWNER}, relay half from attempt rows with a sid whose status "
                     f"is not pending/failed"),
            "window_seconds": DOUBLE_SEND_SECONDS,
            "owner_pairs": len(owner_pairs),
            "relay_pairs": len(relay_pairs),
            "relay_pairs_without_recipient": len(_group_by_body(unjudgeable)),
            "recipient_rule": ("a relay pair is a duplicate only when both rows name the same "
                               "recipient; rows written before the `to_number` column existed "
                               "carry none and are counted as unjudgeable, not as defects"),
            "total_is_sum_of_two_stores": True,
            "overlap_note": ("one relay duplicate that reached him is visible in BOTH "
                             "stores, so `total` counts pair-MEASUREMENTS, not unique "
                             "incidents; the owner and relay counts are printed "
                             "separately so the overlap is not hidden"),
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 4 -- silent_outcomes
# --------------------------------------------------------------------------- #
SILENT_SQL = """
SELECT attempt_id, at, door, subsystem, body, status, verdict,
       verdict_reason, sid, substr(body, 1, 60) AS sub
  FROM attempt
 WHERE status IN ('pending', 'queued')
"""


def m_silent_outcomes(a: Audit) -> dict:
    conn = a.conn("relay")
    require_table(conn, "attempt", str(relay_db()))
    rows = conn.execute(SILENT_SQL).fetchall()
    cutoff = a.now - timedelta(hours=SILENT_HOURS)

    stale = []
    for row in rows:
        dt = parse_dt(row["at"])
        if dt is None or dt > a.until:
            continue
        if dt < cutoff:
            stale.append((dt, row))
    stale.sort(key=lambda pair: pair[0])

    def row_dict(pair) -> dict:
        dt, r = pair
        return {
            "attempt_id": r["attempt_id"],
            "at": iso(dt),
            "door": r["door"],
            "status": r["status"],
            "verdict": r["verdict"],
            "verdict_reason": r["verdict_reason"],
            "body": r["sub"],
            "age_hours": round((a.now - dt).total_seconds() / 3600.0, 1),
        }

    # TWO DIFFERENT FAILURES THAT LOOK ALIKE, and only one of them is silence.
    #
    # `pending` with no sid means a door cleared the message and then nothing sent it: nobody
    # was told, and that is the defect this metric exists for (attempts 74/75/76, 2026-10-18).
    # `queued` WITH a sid means Twilio accepted it and our own ledger never learned the final
    # status -- a real gap, but a different one, and calling it "silent" would raise an alarm
    # about messages that did reach him. They are reported separately and only `no_sid` counts
    # against the threshold.
    #
    # The examples shown with the headline are taken from the set the headline counts. A report
    # whose number and whose evidence come from different sets is how a woken session fixes the
    # wrong thing.
    def has_sid(row) -> bool:
        try:
            return bool((row["sid"] or "").strip())
        except (IndexError, KeyError):
            return False

    def cleared(row) -> bool:
        """Did the relay tell its caller to send this? Only SEND rows were ever promised."""
        try:
            return str(row["verdict"]).upper() == "SEND"
        except (IndexError, KeyError):
            return False

    # A row held by DEDUPE / SUPPRESS / FLOOR was deliberately NOT sent -- a recorded decision,
    # not a silence. Thirty such rows sit in this store from the app's 2026-10-14 receipt loop,
    # and counting them as "messages that never went" is the same false crisis as counting the
    # 2,036 suppressed rows as 2,036 messages. Only a row the relay cleared and nobody delivered
    # is silent.
    silent = [(dt, r) for dt, r in stale if not has_sid(r) and cleared(r)]
    held = [(dt, r) for dt, r in stale if not has_sid(r) and not cleared(r)]
    unpromoted = [(dt, r) for dt, r in stale if has_sid(r)]
    oldest = [row_dict(p) for p in silent[:3]]

    return {
        "value": {
            "count": len(silent),
            "oldest": oldest,
            "held_by_policy": len(held),
            "not_promoted": len(unpromoted),
            "oldest_not_promoted": [row_dict(p) for p in unpromoted[:3]],
        },
        "raw": {
            "sql": SILENT_SQL.strip(),
            "rule": (f"status in (pending, queued) AND at older than {SILENT_HOURS}h; "
                     f"`count` = verdict SEND with NO sid (cleared, never delivered); "
                     f"`held_by_policy` = no sid and verdict not SEND (deliberately not sent); "
                     f"`not_promoted` = has a sid (sent, outcome never recorded)"),
            "cutoff": iso(cutoff),
            "rows_pending_or_queued_total": len(rows),
            "count": len(silent),
            "held_by_policy": len(held),
            "not_promoted": len(unpromoted),
            "oldest_three": oldest,
            "oldest_not_promoted": [row_dict(p) for p in unpromoted[:3]],
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 5 -- unanswered_backlog (+ answered_after_expiry)
# --------------------------------------------------------------------------- #
BACKLOG_SQL = """
SELECT id, sent_at, answered_at, body, reason, sid
  FROM owner_text_turn
 WHERE answered_at IS NULL
"""
TURNS_SQL = """
SELECT id, sent_at, answered_at, body, reason
  FROM owner_text_turn
"""


def m_unanswered_backlog(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "owner_text_turn", str(authority_db()))
    open_rows = conn.execute(BACKLOG_SQL).fetchall()
    cutoff = a.now - timedelta(hours=BACKLOG_HOURS)

    backlog = []
    for row in open_rows:
        dt = parse_dt(row["sent_at"])
        if dt is None or dt > cutoff:
            continue
        backlog.append((dt, row))
    backlog.sort(key=lambda pair: pair[0])

    answered_after_expiry = []
    for row in conn.execute(TURNS_SQL).fetchall():
        sent = parse_dt(row["sent_at"])
        answered = parse_dt(row["answered_at"])
        if sent is None or answered is None:
            continue
        if answered > sent + timedelta(days=EXPIRY_DAYS):
            answered_after_expiry.append((answered - sent, sent, answered, row))
    answered_after_expiry.sort(key=lambda e: e[0], reverse=True)

    oldest = [{
        "id": r["id"],
        "sent_at": iso(dt),
        "reason": r["reason"],
        "body": snippet(r["body"], 100),
        "age_hours": round((a.now - dt).total_seconds() / 3600.0, 1),
    } for dt, r in backlog[:3]]

    return {
        "value": {
            "count": len(backlog),
            "oldest": oldest,
            "answered_after_expiry": len(answered_after_expiry),
        },
        "raw": {
            "sql": BACKLOG_SQL.strip(),
            "expiry_sql": TURNS_SQL.strip(),
            "rule": f"answered_at IS NULL AND sent_at older than {BACKLOG_HOURS}h",
            "cutoff": iso(cutoff),
            "open_turns_total": len(open_rows),
            "count": len(backlog),
            "oldest_three": oldest,
            "answered_after_expiry": len(answered_after_expiry),
            "answered_after_expiry_rule": (f"answered_at > sent_at + {EXPIRY_DAYS}d: "
                                           f"these answered a gate that had expired"),
            "answered_after_expiry_worst": [{
                "id": r["id"],
                "sent_at": iso(sent),
                "answered_at": iso(answered),
                "days": round(delta.total_seconds() / 86400.0, 1),
            } for delta, sent, answered, r in answered_after_expiry[:3]],
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 6 -- answer_latency
# --------------------------------------------------------------------------- #
LATENCY_SQL = """
SELECT id, sent_at, answered_at,
       (julianday(answered_at) - julianday(sent_at)) * 24.0 * 60.0 AS minutes
  FROM owner_text_turn
 WHERE answered_at IS NOT NULL
   AND answered_at <> ''
"""


def m_answer_latency(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "owner_text_turn", str(authority_db()))
    rows = conn.execute(LATENCY_SQL).fetchall()

    minutes, skipped = [], []
    for row in rows:
        sent = parse_dt(row["sent_at"])
        if sent is None or sent < a.since or sent > a.until:
            continue
        value = row["minutes"]
        if value is None:
            skipped.append({"id": row["id"],
                            "why": "julianday could not parse a timestamp"})
            continue
        if value < 0:
            skipped.append({"id": row["id"], "why": f"negative latency {value:.1f} min"})
            continue
        minutes.append(float(value))

    return {
        "value": {"median_minutes": median(minutes), "answered_turns": len(minutes)},
        "raw": {
            "sql": LATENCY_SQL.strip(),
            "window_filter": ("sent_at inside the window, applied in Python because "
                              "sent_at is stored in more than one shape"),
            "median_rule": ("SQLite has no median; the exact SQL above fetches the "
                            "pairs and Python averages the two middle values"),
            "answered_turns_in_window": len(minutes),
            "median_minutes": median(minutes),
            "min_minutes": min(minutes) if minutes else None,
            "max_minutes": max(minutes) if minutes else None,
            "skipped": skipped,
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 7 -- internal_asks
# --------------------------------------------------------------------------- #
ASK_SQL = """
SELECT ask_id, ref, subsystem, topic, body, asked_at, answered_at, answered_by, answer
  FROM ask
 WHERE answer IS NOT NULL AND answer <> ''
   AND answered_at IS NOT NULL AND answered_at <> ''
"""
CLARIFY_SQL = """
SELECT id, reference, merchant, question, asked_at, answered_at, answered_via, answer
  FROM clarification
 WHERE answer IS NOT NULL AND answer <> ''
   AND answered_at IS NOT NULL AND answered_at <> ''
"""


def _is_selftest(*values) -> bool:
    blob = " ".join(str(v or "") for v in values).lower()
    return any(marker in blob for marker in SELFTEST_MARKERS)


def _ask_key(text: str) -> str | None:
    match = re.search(r"ask-\d+", str(text or ""))
    return match.group(0) if match else None


def _count_answered_by_not_owner(ask_rows) -> int:
    """`ask` rows whose answered_by is neither the owner's number nor its alias."""
    total = 0
    for row in ask_rows:
        raw = str(row["answered_by"] or "").strip()
        if not raw:
            continue
        if raw.lower() in OWNER_ALIASES or digits(raw).endswith(OWNER_DIGITS):
            continue
        total += 1
    return total


def m_internal_asks(a: Audit) -> dict:
    conn = a.conn("relay")
    require_table(conn, "ask", str(relay_db()))
    ask_rows = conn.execute(ASK_SQL).fetchall()

    # The CFO store records HOW it was answered, and `answered_via='reference'` is
    # the provable self-answer: the question went out, then a reference match
    # closed it without him. Read it first, so a relay failure cannot be reported
    # as "no internal asks".
    cconn = a.conn("cfo")
    require_table(cconn, "clarification", str(cfo_db()))
    cfo_rows = cconn.execute(CLARIFY_SQL).fetchall()

    candidates: dict[str, dict] = {}
    excluded_selftest = no_currency = zero_latency = 0

    for row in ask_rows:
        if _is_selftest(row["ref"], row["body"]):
            excluded_selftest += 1
            continue
        if not CURRENCY_RE.search(str(row["body"] or "")):
            no_currency += 1
            continue
        asked, answered = parse_dt(row["asked_at"]), parse_dt(row["answered_at"])
        if asked is None or answered is None:
            continue
        minutes = (answered - asked).total_seconds() / 60.0
        if minutes <= 0:
            zero_latency += 1
            continue
        key = _ask_key(row["ref"]) or _ask_key(row["body"]) or f"ask:{row['ask_id']}"
        candidates[key] = {
            "key": key,
            "source": "relay.ask",
            "ask_id": row["ask_id"],
            "subsystem": row["subsystem"],
            "asked_at": iso(asked),
            "answered_at": iso(answered),
            "minutes": round(minutes, 1),
            "answered_by": row["answered_by"],
            "body": snippet(row["body"], 100),
        }

    self_answered_non_owner = []
    for row in cfo_rows:
        via = str(row["answered_via"] or "").strip().lower()
        if via in OWNER_ALIASES:
            continue
        self_answered_non_owner.append(row)
        asked, answered = parse_dt(row["asked_at"]), parse_dt(row["answered_at"])
        minutes = ((answered - asked).total_seconds() / 60.0
                   if asked and answered else None)
        key = _ask_key(row["reference"]) or f"clarify:{row['id']}"
        if key in candidates:
            # One question, measured at both ends: count it once.
            candidates[key]["also_in_cfo"] = via
            continue
        candidates[key] = {
            "key": key,
            "source": "cfo.clarification",
            "ask_id": row["id"],
            "subsystem": "cfo_ask",
            "asked_at": iso(asked),
            "answered_at": iso(answered),
            "minutes": round(minutes, 1) if minutes is not None else None,
            "answered_by": via,
            "body": snippet(row["question"], 100),
        }

    ranked = sorted(candidates.values(),
                    key=lambda c: (-(c["minutes"] or 0.0), c["asked_at"] or ""))

    return {
        "value": {"count": len(ranked), "worst": ranked[:3]},
        "raw": {
            "ask_sql": ASK_SQL.strip(),
            "clarify_sql": CLARIFY_SQL.strip(),
            "currency_pattern": CURRENCY_RE.pattern,
            "rule": ("a question carrying a money amount that was ANSWERED, where "
                     "answered_at is later than asked_at by more than 0 minutes -- "
                     "i.e. it asked, then closed it itself"),
            "union_rule": ("relay.ask and cfo.clarification are unioned on the "
                           "ask-<n> reference so one question is counted once"),
            "count": len(ranked),
            "relay_candidates": sum(1 for c in candidates.values()
                                    if c["source"] == "relay.ask"),
            "cfo_self_answered": len(self_answered_non_owner),
            "excluded_selftest_rows": excluded_selftest,
            "rows_without_currency_pattern": no_currency,
            "rows_answered_at_zero_minutes": zero_latency,
            "answered_by_values": value_counts(
                [str(r["answered_by"] or "") for r in ask_rows]),
            "answered_via_values": value_counts(
                [str(r["answered_via"] or "") for r in cfo_rows]),
            "answered_by_not_owner_or_number": _count_answered_by_not_owner(ask_rows),
            "note_owner_alias": ("`answered_by='owner'` is the alias the ledger writes "
                                 "for a genuine owner answer; a literal comparison "
                                 "with the number alone would call every answered row "
                                 "foreign, so both forms are accepted"),
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# metric 8 -- truncation
# --------------------------------------------------------------------------- #
TRUNC_SQL = """
SELECT id, twilio_sid, body, status, created_at, to_number
  FROM sms_log
 WHERE direction = 'outbound'
"""


def _is_truncated(body: str) -> bool:
    text = str(body or "")
    if any(marker in text.lower() for marker in TRUNCATION_MARKERS):
        return True
    return text.rstrip().endswith(ELLIPSIS)


def m_truncation(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "sms_log", str(authority_db()))
    rows = [r for r in conn.execute(TRUNC_SQL).fetchall() if is_owner(r["to_number"])]
    hits = [(dt, r) for dt, r in a.windowed(rows, "created_at")
            if str(r["status"]).lower() != "suppressed" and _is_truncated(r["body"])]

    # Is the original recoverable? Only if the relay recorded which queue row the
    # send came from AND that row still holds it. Measured 2026-10-18: attempts
    # 6 and 8 carry the detail "nothing on record holds this text", yet their ref
    # `owner_message_queue:<id>` DOES resolve and that row holds 543 / 612 chars
    # against the 194 / 281 that were sent. So this is a measured join, not an
    # assumption.
    rconn = a.conn("relay")
    require_table(rconn, "attempt", str(relay_db()))
    ref_by_body: dict[str, int] = {}
    for row in rconn.execute(
            "SELECT attempt_id, body, ref FROM attempt "
            "WHERE ref LIKE 'owner_message_queue:%'"):
        key = normalise(row["body"])
        match = re.match(r"owner_message_queue:(\d+)$", str(row["ref"] or ""))
        if key and match:
            ref_by_body[key] = int(match.group(1))

    originals: dict[int, int] = {}
    queue_ids = sorted(set(ref_by_body.values()))
    if queue_ids and table_exists(conn, "owner_message_queue"):
        marks = ",".join("?" * len(queue_ids))
        for row in conn.execute(
                f"SELECT id, body FROM owner_message_queue WHERE id IN ({marks})",
                queue_ids):
            originals[int(row["id"])] = len(str(row["body"] or ""))

    recovered, unrecoverable = [], 0
    for dt, row in hits:
        queue_id = ref_by_body.get(normalise(row["body"]))
        original_len = originals.get(queue_id) if queue_id is not None else None
        if original_len:
            kept = len(str(row["body"] or ""))
            recovered.append({
                "sms_id": row["id"],
                "queue_id": queue_id,
                "kept_chars": kept,
                "original_chars": original_len,
                "dropped_chars": max(0, original_len - kept),
                "at": iso(dt),
            })
        else:
            unrecoverable += 1

    return {
        "value": {
            "count": len(hits),
            "originals_recoverable": len(recovered),
            "original_chars_recovered": sum(e["original_chars"] for e in recovered),
            "dropped_chars": sum(e["dropped_chars"] for e in recovered),
        },
        "raw": {
            "sql": TRUNC_SQL.strip(),
            "rule": ("outbound rows to the owner in the window (not suppressed) whose "
                     "body contains 'cut short' or '[cut' or ends in U+2026"),
            "count": len(hits),
            "marker_values": sorted({
                m for _, r in hits for m in TRUNCATION_MARKERS
                if m in str(r["body"] or "").lower()
            } | ({ELLIPSIS} if any(str(r["body"] or "").rstrip().endswith(ELLIPSIS)
                                   for _, r in hits) else set())),
            "kept_chars_total": sum(len(str(r["body"] or "")) for _, r in hits),
            "originals_recoverable": len(recovered),
            "originals_unrecoverable": unrecoverable,
            "recovery_route": ("attempt.ref = 'owner_message_queue:<id>' -> authority "
                               "owner_message_queue.body"),
            "original_chars_recovered": sum(e["original_chars"] for e in recovered),
            "kept_chars_of_recovered": sum(e["kept_chars"] for e in recovered),
            "dropped_chars": sum(e["dropped_chars"] for e in recovered),
            "examples": recovered[:3],
            "sample_bodies": [
                {"sms_id": r["id"], "at": iso(dt), "status": r["status"],
                 "body": snippet(r["body"], 90)} for dt, r in hits[:3]
            ],
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# supporting measurement -- owner_decision_queue (no threshold)
# --------------------------------------------------------------------------- #
DECISION_SQL = """
SELECT id, asked_at, question, severity, status, source
  FROM owner_decision_queue
 WHERE status = 'pending'
"""


def m_decision_queue(a: Audit) -> dict:
    conn = a.conn("authority")
    require_table(conn, "owner_decision_queue", str(authority_db()))
    rows = conn.execute(DECISION_SQL).fetchall()
    cutoff = a.now - timedelta(hours=BACKLOG_HOURS)

    stale = []
    for row in rows:
        dt = parse_dt(row["asked_at"])
        if dt is not None and dt < cutoff:
            stale.append((dt, row))
    stale.sort(key=lambda pair: pair[0])

    return {
        "value": {
            "pending": len(rows),
            "pending_over_48h": len(stale),
            "oldest_three": [{
                "id": r["id"],
                "asked_at": iso(dt),
                "severity": r["severity"],
                "source": r["source"],
                "question": snippet(r["question"], 80),
            } for dt, r in stale[:3]],
        },
        "raw": {
            "sql": DECISION_SQL.strip(),
            "note": ("supporting measurement only: no threshold in THRESHOLDS, but a "
                     "stale decision queue is the same disease as an unanswered text"),
        },
        "reason": None,
    }


# --------------------------------------------------------------------------- #
# running every metric, independently
# --------------------------------------------------------------------------- #
METRICS = (
    ("delivery", m_delivery),
    ("repeat_index", m_repeat_index),
    ("double_sends", m_double_sends),
    ("silent_outcomes", m_silent_outcomes),
    ("unanswered_backlog", m_unanswered_backlog),
    ("answer_latency", m_answer_latency),
    ("internal_asks", m_internal_asks),
    ("truncation", m_truncation),
    ("decision_queue", m_decision_queue),
)


def collect(a: Audit) -> dict:
    """Run every metric. One failure nulls ONE metric and nothing else."""
    results = {}
    for name, fn in METRICS:
        try:
            block = fn(a)
            block["name"] = name
            block.setdefault("reason", None)
            results[name] = block
        except Unreadable as exc:
            results[name] = {"name": name, "value": None, "raw": None,
                             "reason": str(exc)}
        except sqlite3.Error as exc:
            results[name] = {"name": name, "value": None, "raw": None,
                             "reason": f"sqlite: {exc}"}
        except Exception as exc:                              # noqa: BLE001
            results[name] = {"name": name, "value": None, "raw": None,
                             "reason": f"{type(exc).__name__}: {exc}"}
    return results


def flat_values(results: dict) -> dict:
    """The flat number dict the thresholds and the table read."""
    def val(metric, key):
        value = (results.get(metric) or {}).get("value")
        return value.get(key) if isinstance(value, dict) else None

    return {
        "delivered": val("delivery", "delivered"),
        "refused": val("delivery", "refused"),
        "failed": val("delivery", "failed"),
        "inbound": val("delivery", "inbound"),
        "refusal_rate": val("delivery", "refusal_rate"),
        "max_repeat": val("repeat_index", "max_repeat"),
        "double_sends": val("double_sends", "total"),
        "silent_outcomes": val("silent_outcomes", "count"),
        "unanswered_backlog": val("unanswered_backlog", "count"),
        "answered_after_expiry": val("unanswered_backlog", "answered_after_expiry"),
        "answer_latency_min": val("answer_latency", "median_minutes"),
        "internal_asks": val("internal_asks", "count"),
        "truncation": val("truncation", "count"),
        "decision_queue_pending_48h": val("decision_queue", "pending_over_48h"),
    }


TABLE_ROWS = (
    ("delivered (distinct sids)", "delivered"),
    ("refused (rows)", "refused"),
    ("failed (rows)", "failed"),
    ("inbound (rows)", "inbound"),
    ("refusal_rate", "refusal_rate"),
    ("max_repeat", "max_repeat"),
    ("double_sends", "double_sends"),
    ("silent_outcomes", "silent_outcomes"),
    ("unanswered_backlog", "unanswered_backlog"),
    ("answered_after_expiry", "answered_after_expiry"),
    ("answer_latency (median min)", "answer_latency_min"),
    ("internal_asks", "internal_asks"),
    ("truncation", "truncation"),
)


def breaches(values: dict) -> list[dict]:
    """Which thresholds a MEASURED value breaches. null never breaches."""
    out = []
    for key, limit in THRESHOLDS.items():
        value = values.get(key)
        if value is None:
            continue
        try:
            fired = float(value) > float(limit)
        except (TypeError, ValueError):
            continue
        if fired:
            out.append({"metric": key, "value": value, "threshold": limit})
    return out


# --------------------------------------------------------------------------- #
# ranking the defects
# --------------------------------------------------------------------------- #
# Order is severity for HIM, not for the database: a text he sees twice beats a
# row stuck in a table he never reads.
DEFECT_ORDER = (
    "double_sends", "silent_outcomes", "unanswered_backlog", "max_repeat",
    "internal_asks", "refusal_rate", "truncation", "answered_after_expiry",
)
# A threshold key is not always a metric key.
DEFECT_SOURCE = {"refusal_rate": "delivery", "max_repeat": "repeat_index"}


def _is_defect(name: str, values: dict, fired: set) -> bool:
    if name in fired:
        return True
    # A truncated outbound body is a defect in its own right, threshold or not.
    return name == "truncation" and (values.get("truncation") or 0) > 0


def rank_defects(results: dict, values: dict) -> list[dict]:
    """The top three DEFECTS with exact evidence, worst first."""
    fired = {b["metric"] for b in breaches(values)}
    defects = [_defect(name, results)
               for name in DEFECT_ORDER if _is_defect(name, values, fired)]
    order = {name: i for i, name in enumerate(DEFECT_ORDER)}
    defects.sort(key=lambda d: order.get(d["metric"], 99))
    return defects[:3]


def _defect(metric: str, results: dict) -> dict:
    block = results.get(DEFECT_SOURCE.get(metric, metric)) or {}
    value = block.get("value") or {}
    raw = block.get("raw") or {}

    if metric == "double_sends":
        worst = value.get("worst") or {}
        a_, b_ = worst.get("a") or {}, worst.get("b") or {}
        return {
            "metric": metric,
            "headline": (f"{value.get('total')} duplicate-send pair(s) "
                         f"(owner {value.get('owner_sms_log')}, relay "
                         f"{value.get('relay_attempt')})"),
            "evidence": (f"closest: ids {a_.get('id')}/{b_.get('id')} sids "
                         f"{a_.get('sid')}/{b_.get('sid')}, "
                         f"{worst.get('delta_seconds')}s apart at "
                         f"{a_.get('at_precise') or a_.get('at')} .. "
                         f"{b_.get('at_precise') or b_.get('at')}; "
                         f"body \"{worst.get('body')}\"")
                        if worst else "no pair",
        }
    if metric == "silent_outcomes":
        oldest = (value.get("oldest") or [{}])[0]
        return {
            "metric": metric,
            "headline": (f"{value.get('count')} relay row(s) cleared SEND, never delivered, "
                         f"older than {SILENT_HOURS}h"),
            "evidence": (f"oldest: attempt_id {oldest.get('attempt_id')} door "
                         f"{oldest.get('door')} at {oldest.get('at')} "
                         f"({oldest.get('age_hours')}h) status {oldest.get('status')} "
                         f"verdict {oldest.get('verdict')}/"
                         f"{oldest.get('verdict_reason')} body "
                         f"\"{oldest.get('body')}\""
                         f"; the store also holds {value.get('held_by_policy')} row(s) "
                         f"held by policy and {value.get('not_promoted')} sent row(s) whose "
                         f"outcome was never recorded") if oldest else "none",
        }
    if metric == "unanswered_backlog":
        oldest = (value.get("oldest") or [{}])[0]
        return {
            "metric": metric,
            "headline": (f"{value.get('count')} unanswered turn(s) older than "
                         f"{BACKLOG_HOURS}h"),
            "evidence": (f"oldest: owner_text_turn id {oldest.get('id')} sent_at "
                         f"{oldest.get('sent_at')} ({oldest.get('age_hours')}h) reason "
                         f"{oldest.get('reason')} body \"{oldest.get('body')}\"")
                        if oldest else "none",
        }
    if metric == "max_repeat":
        top = (value.get("repeat_index") or [{}])[0]
        return {
            "metric": metric,
            "headline": f"one body went out {value.get('max_repeat')} time(s)",
            "evidence": (f"{top.get('count')} distinct sids for \"{top.get('body')}\" "
                         f"between {top.get('first')} and {top.get('last')} (sids "
                         f"{', '.join(top.get('sids') or [])})")
                        if top else "none",
        }
    if metric == "internal_asks":
        worst = (value.get("worst") or [{}])[0]
        return {
            "metric": metric,
            "headline": (f"{value.get('count')} question(s) asked then answered by "
                         f"the system"),
            "evidence": (f"worst {worst.get('minutes')} min: {worst.get('source')} "
                         f"{worst.get('key')} asked {worst.get('asked_at')} answered "
                         f"{worst.get('answered_at')} by {worst.get('answered_by')} "
                         f"body \"{worst.get('body')}\"") if worst else "none",
        }
    if metric == "refusal_rate":
        return {
            "metric": metric,
            "headline": f"refusal_rate {fmt(value.get('refusal_rate'))}",
            "evidence": raw.get("refusal_rate_formula") or "",
        }
    if metric == "truncation":
        sample = (raw.get("sample_bodies") or [{}])[0]
        return {
            "metric": metric,
            "headline": f"{value.get('count')} truncated outbound body(ies)",
            "evidence": (f"{value.get('originals_recoverable')} original(s) "
                         f"recoverable, {value.get('dropped_chars')} char(s) dropped; "
                         f"e.g. sms id {sample.get('id')} at {sample.get('at')}"),
        }
    if metric == "answered_after_expiry":
        return {
            "metric": metric,
            "headline": (f"{value.get('answered_after_expiry')} answer(s) after the "
                         f"7-day gate expired"),
            "evidence": str((raw.get("answered_after_expiry_worst") or [{}])[0]),
        }
    return {"metric": metric, "headline": "defect", "evidence": ""}


# --------------------------------------------------------------------------- #
# the flag
# --------------------------------------------------------------------------- #
def build_prompt(a: Audit, values: dict, fired: list[dict], defects: list[dict],
                 results: dict) -> str:
    week = iso_week(a.now)
    unmeasured = [name for name, block in results.items() if block.get("reason")]

    lines = [
        f"OWNER-TEXT AUDIT {week} - {len(fired)} threshold(s) breached.",
        f"Window {iso(a.since)} .. {iso(a.until)} ({a.days}d, by {a.since_label}). "
        f"Owner {OWNER}.",
        "",
        "METRIC                       VALUE  THRESHOLD",
    ]
    for label, key in TABLE_ROWS:
        limit = THRESHOLDS.get(key)
        thr = f"> {limit:g}" if limit is not None else "-"
        lines.append(f"{label:<28}{fmt(values.get(key)):>8}  {thr}")

    lines += ["", "BREACHED"]
    for item in fired:
        lines.append(f"- {item['metric']} = {fmt(item['value'])} > "
                     f"{item['threshold']:g}")

    if unmeasured:
        lines += ["", "UNMEASURED (never claim a number for these): "
                  + ", ".join(unmeasured)]

    lines += ["", "TOP DEFECTS, WORST FIRST"]
    for i, defect in enumerate(defects, 1):
        lines.append(f"{i}. {defect['headline']}")
        lines.append(f"   {defect['evidence']}")

    lines += [
        "",
        "STANDING INSTRUCTION",
        "Find the single worst defect, fix it at the composer or the door that owns",
        "it, prove the fix against the live ledger, record the decision, and leave",
        "the next week's audit a note.",
        "",
        "Do not send anything to anyone, do not touch secratary (frozen), and do not",
        "widen a threshold to make this quiet.",
    ]
    return _fit("\n".join(lines), 2500)


def _fit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 20]
    at = cut.rfind("\n")
    return (cut[:at] if at > 0 else cut).rstrip() + "\n[truncated]"


def file_flag(a: Audit, prompt: str) -> str:
    """Call the frozen flag CLI directly. ssh-free: this runs ON the authority."""
    cli = wake_cli()
    if not cli.is_file():
        return f"suppressed:error (no wake cli at {cli}; set WAKE_PY)"
    cmd = [
        sys.executable or "python3", str(cli), "flag",
        "--subject", f"owner-text-audit:{iso_week(a.now)}",
        "--prompt", prompt,
        "--kind", "owner-text",
        "--source", "owner-text-audit",
        "--priority", "high",
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:                                  # noqa: BLE001
        return f"suppressed:error ({type(exc).__name__}: {exc})"
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            result = str(json.loads(line).get("result") or "")
            if result:
                return result
        except Exception:                                      # noqa: BLE001
            pass
        if line in ("filed", "deduped", "capped") or line.startswith("suppressed"):
            return line
    detail = " ".join(((proc.stderr or "").strip().splitlines() or [""])[-1:])[:200]
    return f"suppressed:error (rc={proc.returncode}{'; ' + detail if detail else ''})"


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def human_report(a: Audit, results: dict, values: dict, fired: list[dict],
                 defects: list[dict]) -> str:
    out = [
        "OWNER-TEXT AUDIT  " + iso_week(a.now),
        f"window   {iso(a.since)} .. {iso(a.until)}  ({a.days} days, by {a.since_label})",
        f"owner    {OWNER}",
        "source   /root/authority.db + /root/.owner-text/relay.db + "
        "/root/.cfo-asks/asks.db (read-only)",
        "NOTE     sms_log logs one outbound send TWICE with the same twilio_sid;",
        "         `delivered` counts DISTINCT twilio_sid, `refused`/`failed` count ROWS.",
        "",
    ]

    def section(title, body):
        out.append(title)
        out.extend(body)
        out.append("")

    d = results["delivery"]
    if d["reason"]:
        section("1. DELIVERY", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        section("1. DELIVERY", [
            f"   delivered {fmt(v['delivered']):>6}   distinct twilio_sid, "
            f"status in (delivered,sent)",
            f"   refused   {fmt(v['refused']):>6}   rows, status='suppressed'",
            f"   failed    {fmt(v['failed']):>6}   rows, status='failed'",
            f"   inbound   {fmt(v['inbound']):>6}   rows, direction='inbound'",
            f"   refusal_rate {fmt(v['refusal_rate'])}   = {r['refusal_rate_formula']}"
            f"   [threshold > {THRESHOLDS['refusal_rate']:g}]",
            f"   units: delivered is deduped sids ({r['delivered_rows_not_deduped']} "
            f"rows); refused/failed are rows -- the denominator mixes them by definition",
            f"   duplicate log rows collapsed: {r['duplicate_log_rows_collapsed']}; "
            f"failed rows carrying {r['failed_distinct_sids']} distinct sid(s)",
        ])

    d = results["repeat_index"]
    if d["reason"]:
        section("2. REPEAT_INDEX", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        body = [
            f"   max_repeat {fmt(v['max_repeat']):>6}   [threshold > "
            f"{THRESHOLDS['max_repeat']:g}]",
            f"   distinct bodies {r['distinct_bodies']}, bodies sent more than once "
            f"{r['bodies_with_more_than_one_send']}, rows without a sid skipped "
            f"{r['rows_without_sid_skipped']}",
        ]
        for entry in v["repeat_index"][:5]:
            body.append(f"     {entry['count']}x  {entry['first']} .. {entry['last']}  "
                        f"\"{entry['body']}\"")
        section("2. REPEAT_INDEX", body)

    d = results["double_sends"]
    if d["reason"]:
        section("3. DOUBLE_SENDS", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        body = [
            f"   double_sends {fmt(v['total']):>6}   [threshold > "
            f"{THRESHOLDS['double_sends']:g}]   owner {v['owner_sms_log']} + relay "
            f"{v['relay_attempt']}, same body, distinct sids, within "
            f"{r['window_seconds']}s",
        ]
        for pair in v["pairs"][:3]:
            body.append(f"     {pair['delta_seconds']}s  ids {pair['a']['id']}/"
                        f"{pair['b']['id']}  {pair['a']['at']}  sids "
                        f"{pair['a']['sid']}/{pair['b']['sid']}  \"{pair['body']}\"")
        section("3. DOUBLE_SENDS", body)

    d = results["silent_outcomes"]
    if d["reason"]:
        section("4. SILENT_OUTCOMES", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        body = [
            f"   silent_outcomes {fmt(v['count']):>6}   [threshold > "
            f"{THRESHOLDS['silent_outcomes']:g}]   pending/queued older than "
            f"{SILENT_HOURS}h (cutoff {r['cutoff']})",
        ]
        for entry in v["oldest"]:
            body.append(f"     attempt {entry['attempt_id']}  {entry['at']}  "
                        f"{entry['age_hours']}h  door={entry['door']}  "
                        f"{entry['status']}  \"{entry['body']}\"")
        section("4. SILENT_OUTCOMES", body)

    d = results["unanswered_backlog"]
    if d["reason"]:
        section("5. UNANSWERED_BACKLOG", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        body = [
            f"   unanswered_backlog {fmt(v['count']):>6}   [threshold > "
            f"{THRESHOLDS['unanswered_backlog']:g}]   answered_at IS NULL and "
            f"sent_at older than {BACKLOG_HOURS}h",
            f"   answered_after_expiry {fmt(v['answered_after_expiry']):>3}   "
            f"answered_at > sent_at + {EXPIRY_DAYS}d (answered a gate that had expired)",
        ]
        for entry in v["oldest"]:
            body.append(f"     id {entry['id']}  {entry['sent_at']}  "
                        f"{entry['age_hours']}h  reason={entry['reason']}  "
                        f"\"{entry['body']}\"")
        section("5. UNANSWERED_BACKLOG", body)

    d = results["answer_latency"]
    if d["reason"]:
        section("6. ANSWER_LATENCY", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        section("6. ANSWER_LATENCY", [
            f"   median {fmt(v['median_minutes'])} minutes over "
            f"{v['answered_turns']} answered turn(s)  (min {fmt(r['min_minutes'])}, "
            f"max {fmt(r['max_minutes'])})",
            "   SQL:",
            "     SELECT id, sent_at, answered_at,",
            "            (julianday(answered_at) - julianday(sent_at)) * 24.0 * 60.0",
            "              AS minutes",
            "       FROM owner_text_turn",
            "      WHERE answered_at IS NOT NULL AND answered_at <> ''",
            "   (median computed in Python: SQLite has no median)",
        ])

    d = results["internal_asks"]
    if d["reason"]:
        section("7. INTERNAL_ASKS", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        body = [
            f"   internal_asks {fmt(v['count']):>6}   [threshold > "
            f"{THRESHOLDS['internal_asks']:g}]   a money question answered later than "
            f"it was asked, i.e. asked then closed itself",
            f"   relay.ask candidates {r['relay_candidates']}, cfo self-answered "
            f"{r['cfo_self_answered']}, excluded selftest "
            f"{r['excluded_selftest_rows']}, zero-latency "
            f"{r['rows_answered_at_zero_minutes']}",
            f"   answered_by values {r['answered_by_values']}; not-owner "
            f"{r['answered_by_not_owner_or_number']}",
        ]
        for entry in v["worst"]:
            body.append(f"     {entry['minutes']} min  {entry['source']} "
                        f"{entry['key']}  {entry['asked_at']} -> "
                        f"{entry['answered_at']}  \"{entry['body']}\"")
        section("7. INTERNAL_ASKS", body)

    d = results["truncation"]
    if d["reason"]:
        section("8. TRUNCATION", [f"   UNMEASURED -- {d['reason']}"])
    else:
        v, r = d["value"], d["raw"]
        section("8. TRUNCATION", [
            f"   truncation {fmt(v['count']):>6}   bodies with 'cut short' / '[cut' / "
            f"trailing U+2026",
            f"   originals recoverable {v['originals_recoverable']} of {v['count']} "
            f"via attempt.ref -> owner_message_queue",
            f"   recovered original chars {fmt(v['original_chars_recovered'])}, kept "
            f"{fmt(r['kept_chars_of_recovered'])}, dropped {fmt(v['dropped_chars'])}",
            f"   kept chars total (all truncated rows) {fmt(r['kept_chars_total'])}",
        ])

    d = results["decision_queue"]
    if not d["reason"]:
        v = d["value"]
        section(f"SUPPORTING - owner_decision_queue (no threshold)", [
            f"   pending {v['pending']}, pending over {BACKLOG_HOURS}h "
            f"{v['pending_over_48h']}",
        ])

    out.append("THRESHOLDS BREACHED: " + (", ".join(
        f"{b['metric']}={fmt(b['value'])}>{b['threshold']:g}" for b in fired)
        or "none"))
    out.append("")
    out.append("DEFECTS, WORST FIRST")
    if not defects:
        out.append("   none measured")
    for i, defect in enumerate(defects, 1):
        out.append(f"   {i}. [{defect['metric']}] {defect['headline']}")
        out.append(f"      {defect['evidence']}")
    return "\n".join(out)


def json_payload(a: Audit, results: dict, values: dict, fired: list[dict],
                 defects: list[dict], exit_code: int) -> dict:
    return {
        "generated_at": iso(a.now),
        "host": socket.gethostname(),
        "owner": OWNER,
        "window": {"since": iso(a.since), "until": iso(a.until),
                   "days": a.days, "chosen_by": a.since_label},
        "owner_text_note": ("sms_log logs the same outbound send twice with the same "
                            "twilio_sid; delivered counts DISTINCT twilio_sid, "
                            "refused/failed count rows"),
        "thresholds": THRESHOLDS,
        "values": values,
        "metrics": results,
        "breaches": fired,
        "defects": defects,
        "unmeasured": {name: block["reason"] for name, block in results.items()
                       if block.get("reason")},
        "exit_code": exit_code,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; this tool's contract says 3."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(3)


def parse_args(argv):
    parser = Parser(
        description="Audit the owner text channel: eight numbers + a defect list.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("exit 0 = all metrics computed; 2 = a source was unreadable; "
                "3 = usage error"))
    parser.add_argument("--days", type=int, default=14,
                        help="window length in days (default 14)")
    parser.add_argument("--since", default=None,
                        help="window start, YYYY-MM-DD (UTC midnight); wins over --days")
    parser.add_argument("--json", action="store_true", help="one JSON object")
    parser.add_argument("--flag", action="store_true",
                        help="file a wake flag IF a threshold is breached")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --flag: print the brief, file nothing")
    args = parser.parse_args(argv)

    if args.json and args.flag:
        parser.error("--json and --flag are different output contracts; pick one")
    if args.days <= 0:
        parser.error("--days must be a positive integer")
    return args


def resolve_window(args, now: datetime):
    if not args.since:
        return now - timedelta(days=args.days), args.days, "--days"
    try:
        start = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise SystemExit(_usage(f"--since must be YYYY-MM-DD, got {args.since!r}"))
    days = max(1, int((now - start).total_seconds() // 86400))
    return start, days, "--since"


def _usage(message: str) -> int:
    print(f"owner-text-audit: error: {message}", file=sys.stderr)
    return 3


def main(argv=None) -> int:
    # Message bodies are arbitrary unicode and a cp1252 console pipe would raise
    # on the first ellipsis. Replace rather than die: a broken glyph must never
    # cost the whole report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    args = parse_args(sys.argv[1:] if argv is None else argv)
    now = now_utc()
    try:
        since, days, label = resolve_window(args, now)
    except SystemExit as exc:
        return int(exc.code or 3)
    if since >= now:
        return _usage("--since is in the future: nothing to measure")

    a = Audit(since=since, until=now, days=days, since_label=label)
    try:
        results = collect(a)
        values = flat_values(results)
        fired = breaches(values)
        defects = rank_defects(results, values)
    finally:
        a.close()

    exit_code = 2 if any(b.get("reason") for b in results.values()) else 0
    unmeasured = [name for name, b in results.items() if b.get("reason")]
    if unmeasured:
        print("UNMEASURED: " + ", ".join(unmeasured), file=sys.stderr)
        for name in unmeasured:
            print(f"  {name}: {results[name]['reason']}", file=sys.stderr)

    if args.json:
        print(json.dumps(json_payload(a, results, values, fired, defects, exit_code),
                         indent=2, default=str))
        return exit_code

    print(human_report(a, results, values, fired, defects))
    print("")

    if not args.flag:
        return exit_code
    if not fired:
        print("no flag: all metrics within threshold")
        return exit_code

    prompt = build_prompt(a, values, fired, defects, results)
    if args.dry_run:
        print("dry-run: would file owner-text-audit:%s (%d chars); nothing written"
              % (iso_week(a.now), len(prompt)))
        print("-" * 70)
        print(prompt)
        return exit_code

    result = file_flag(a, prompt)
    print(f"flag owner-text-audit:{iso_week(a.now)} -> {result} ({len(prompt)} chars)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
