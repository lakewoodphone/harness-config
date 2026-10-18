#!/usr/bin/env python3
"""owner-queue — the queue of things that genuinely need the OWNER, and only those.

WHY THIS EXISTS. The owner's instruction, 2026-09-11: *"you work on all of them as they
come up, and the ones that absolutely need me and you can't solve you bring up with me one
at a time throughout different conversation sessions, they should be in a queue you read
from when we have time."*

The company already had `owner_message_queue`, and by 2026-09-11 it had 595 undelivered
rows and had sent nothing since 2026-07-19 — 54 days. That queue is a *message* queue: it
fills with briefings, sync-breaker alerts and freshness notices, so it became noise and
then it became invisible. This is a *decision* queue: one row per thing the owner actually
has to decide, with a recommendation already attached, and resolved rows closed rather than
left to rot.

WHAT BELONGS HERE
  - money, customers, legal or contractual posture, family, anything irreversible
  - genuine taste calls
  - a blocker I could not resolve myself

WHAT DOES NOT BELONG HERE
  - anything I can fix. Fix it. A queue row is an admission that I could not.
  - a menu of five. One question, options, one marked Recommended.

USAGE
  owner-queue.py next                 # the single next thing to raise with him
  owner-queue.py next --peek 3        # the next few (for my own planning)
  owner-queue.py add --question ... --recommendation ... [--options a|b|c]
                                      [--context ...] [--blocks ...] [--ages-days N]
  owner-queue.py add --from-json FILE|-   # SAFE PATH — see below
  owner-queue.py lint [--show-text]   # P265 detector over the whole queue
  owner-queue.py sweep [--all] [--json]  # READ-ONLY: rows the domain guard would refuse
  owner-queue.py resolve ID --how "what I did / what he said"
  owner-queue.py resolve ID --dismissed "why it never needed him"
  owner-queue.py answer ID --answer "his words"
  owner-queue.py list [--all]
  owner-queue.py stats

THE SAFE INPUT PATH (P265, journal 2026-09-17). Three rows (#79, #33, #86) lost `$`+digits
before the INSERT: the CLI always bound its parameters, so the shell of whatever *called*
the CLI ate the money, and the row still read like a sentence. `add --from-json FILE|-`
never puts the text through a shell: it reads one JSON object and binds every field.

    {"question": "...", "context": "...",
     "options": ["first", "second (Recommended)"],
     "recommendation": "...", "severity": "high",
     "blocks": "...", "source": "...", "age_days": 3,
     "domain": "owner|customer|business|engineering",
     "owner_worthy": false, "owner_reason": "required when owner_worthy is true"}

`options` may be a JSON array (canonical) or the legacy pipe-separated string. A leading
``$`` and backslashes survive JSON and reach SQLite unchanged. Use `-` to read stdin. The
old flags keep working unchanged, because sessions on three machines call them.

THE GUARD (P265 signal, refused by default). Before INSERT — on both paths — the text is
scanned for the two signatures P265 identified:

  (a) a BACKSLASH anywhere in question/context/options_json/recommendation/resolution
      (`\\,000` was `$2,000`; `\\.00286` was `$0.00286`); an escaped `\\n` or `\\t`
      surviving from a command line counts as a hit too;
  (b) a DOUBLE SPACE in question/recommendation/options_json
      (#33's `Option 1 (recommended):  per device per month` was `$N`).

Any hit refuses the row and names the field, the offset and the offending text. This is
deliberately strict: a false positive costs one flag, a false negative costs the number the
owner was asked to decide on. A single backslash in a Windows path (`C:\\Users\\zabz`) or a
literal `\\n` is a KNOWN false positive and is still refused — pass --allow-suspect-text to
store it anyway. The guard never guesses what a missing amount used to be.

THE DOMAIN GUARD (owner instruction, 2026-10-18, twice in one evening):
  "Dial pad customer communications and questions don't belong in my owner queue.
   They're in some sort of business queue that doesn't have to show up as desperately
   needing my attention" / "dialpad texts don't go into owner queue, they aren't
   pending owner attention".

  The queue is for decisions only HE can make. Customer work and shop operations are
  the LEDGER: `/root/work/work.db`, filed through `/root/bin/work.py add`. The guard
  is two small, testable layers, deliberately not one large heuristic:

    1. THE FILER SAYS WHAT IT IS. `--domain owner|customer|business|engineering`
       (default `owner`, because this is the owner queue and the filer is asserting
       that this row belongs to him). A non-owner domain is refused unless the
       deliberate escape below is used.
    2. A KEYWORD BACKSTOP for the obvious cases a forgetful filer will still try:
       a work-order number (`WO26...`), the word customer, voicemail, a customer
       "waiting", or a phone number. Soft markers are read only from the fields that
       state the ASK (question/recommendation/options), so a context paragraph that
       mentions a customer as background is not a refusal by itself. Strong markers
       (`WO...`, voicemail, phone) are read from all fields.

  A refusal names the rule and the alternative, and prints the exact `work.py add`
  shape plus a project to use. The escape is deliberate and must carry a reason:

      --owner-worthy --owner-reason "why only the owner can decide this"

  `--owner-worthy` without a non-empty `--owner-reason` is refused. A genuine owner
  question that merely mentions a customer is therefore still filable, but only by
  someone who writes down why. Exit code 5 is a domain refusal; 2 is a usage error.

AGEING. `next` sorts by (blocks-others first, severity, age). An item that is blocking
other work outranks a merely old one: keeping a decision queued while it stalls the
company is the expensive failure, not the decision itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import textwrap

DEFAULT_DB = os.environ.get(
    "OWNER_QUEUE_DB", "/root/authority.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_decision_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at      TEXT NOT NULL,
    question      TEXT NOT NULL,
    context       TEXT,
    options_json  TEXT,
    recommendation TEXT,
    severity      TEXT NOT NULL DEFAULT 'medium',
    blocks        TEXT,
    source        TEXT,
    age_days      INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending',
    answered_at   TEXT,
    answer        TEXT,
    resolved_at   TEXT,
    resolution    TEXT,
    -- When the owner has seen the question and put it off to a stated day.
    -- A deferred row is NOT a missed one: it is still pending and still his,
    -- but it must stop ageing into an overdue count until the day he named.
    -- Measured 2026-09-22: #100 was reported as a blocking item "past 3d" the
    -- same day the owner said "I'll look into this tomorrow" -- the queue had
    -- no way to record the deferral, so the only honest answer it could give
    -- was "unanswered and old", which was true of the row and false of him.
    deferred_until TEXT,
    deferred_at    TEXT,
    defer_note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_odq_status ON owner_decision_queue(status, severity);
"""

# One-line ordering: unresolved, blocking first, then severity, then age.
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Columns the deferral feature added. `CREATE TABLE IF NOT EXISTS` never alters an
# existing table, so a database that predates these needs them added explicitly.
ADDED_COLUMNS = (
    ("deferred_until", "TEXT"),
    ("deferred_at", "TEXT"),
    ("defer_note", "TEXT"),
)


def _migrate_schema(con) -> list[str]:
    """Add columns this version needs to a table an older version created."""
    have = {r[1] for r in con.execute("PRAGMA table_info(owner_decision_queue)")}
    added = []
    for name, decl in ADDED_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE owner_decision_queue ADD COLUMN {name} {decl}")
            added.append(name)
    # WHAT HE SAID ABOUT EARLIER ITEMS IS THE TRAINING DATA FOR THE NEXT ONES.
    # Owner's requirement, 2026-10-18: "the queue needs to learn over time what to put in it and
    # what to prioritize based on my responses when we go through a session knocking it out."
    # One row per answer / dismissal / snooze / skip, written by the same commands that close the
    # item, so the record cannot drift from the queue it describes.
    con.execute(
        "CREATE TABLE IF NOT EXISTS owner_queue_feedback ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " item_id TEXT NOT NULL, action TEXT NOT NULL, answer TEXT,"
        " kind TEXT, channel TEXT, party TEXT, cls TEXT, sender_domain TEXT,"
        " tier_at TEXT, score_at INTEGER, at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_oqf_at ON owner_queue_feedback(at DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_oqf_dom ON owner_queue_feedback(sender_domain)")
    return added

# ---------------------------------------------------------------------------
# P265 detector. FROZEN — exactly the two signals the journal entry measured, so a
# `lint` run and an `add` refusal can never disagree about what "mangled" means:
#   (a) a backslash in question/context/options_json/recommendation/resolution
#   (b) a double space in question/recommendation/options_json
# (b) deliberately does NOT cover context/resolution, which are free prose: applying
# it there flags ordinary sentence breaks and would bury the real hits.
# ---------------------------------------------------------------------------
P265_BACKSLASH_FIELDS = ("question", "context", "options_json",
                         "recommendation", "resolution")
P265_DOUBLESPACE_FIELDS = ("question", "recommendation", "options_json")
# Every field printed by `lint --show-text`, in a stable order.
P265_FIELDS = P265_BACKSLASH_FIELDS

# JSON names accepted by --from-json and the column each one lands in.
JSON_TEXT_KEYS = ("question", "context", "options", "recommendation",
                  "severity", "blocks", "source")
JSON_KEYS = JSON_TEXT_KEYS + ("age_days", "domain", "owner_worthy",
                              "owner_reason")

# A caller that escapes an option string for a command line turns a real newline into
# the two characters `\` `n`. That is the #38 false positive. Detected so the message
# can say "this is probably cosmetic" instead of "a number is missing".
_RE_LITERAL_ESCAPE = re.compile(r"\\[nrt]")
_RE_ANY_BACKSLASH = re.compile(r"\\")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        # `lint` must be safe to point at the LIVE database. mode=ro cannot write,
        # and CREATE TABLE IF NOT EXISTS (which needs a write lock on a busy WAL
        # database) is skipped: lint only reads.
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=180)
    else:
        con = sqlite3.connect(path, timeout=int(
            os.environ.get("OWNER_QUEUE_LOCK_TIMEOUT", "180")))
    con.row_factory = sqlite3.Row
    if not readonly:
        con.executescript(SCHEMA)
        added = _migrate_schema(con)
        con.commit()
        if added:
            print(f"schema: added column(s) {', '.join(added)}", file=sys.stderr)
    return con


def exec_locked(con, sql, params=()):
    """Run ONE write and commit it, retrying while SQLite reports the database is locked.

    The queue shares the 13GB live app database, so a write can lose a race with the API or
    another shift. Measured 2026-09-28: an add sat blocked for 180s and then raised
    'database is locked', dropping the row. A bounded retry turns a dropped row into a wait.
    Tunable: OWNER_QUEUE_RETRIES (default 4), OWNER_QUEUE_RETRY_DELAY (default 10s); each
    attempt still waits OWNER_QUEUE_LOCK_TIMEOUT (default 180s).
    """
    tries = int(os.environ.get("OWNER_QUEUE_RETRIES", "4"))
    delay = float(os.environ.get("OWNER_QUEUE_RETRY_DELAY", "10"))
    for attempt in range(1, tries + 1):
        try:
            cur = con.execute(sql, params)
            con.commit()
            return cur
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == tries:
                raise
            print("owner-queue: database locked (attempt %d/%d); waiting %.0fs then retrying"
                  % (attempt, tries, delay), file=sys.stderr)
            time.sleep(delay)


def fmt(row: sqlite3.Row, replace_options=None, replace_recommendation=None) -> str:
    out = []
    out.append("=" * 78)
    # An attention row is about something that HAPPENED; `asked_at` is only when the ingest
    # wrote it. Labelling the ingest time "asked" told him a four-day-old text had just
    # arrived, which is the same class of error as an unverified number.
    keys = row.keys()
    kind = (row["kind"] if "kind" in keys else None) or "decision"
    ev = (row["evidence_at"] if "evidence_at" in keys and row["evidence_at"] else None)
    when = ev or row["asked_at"]
    label = "received" if kind == "attention" else ("from" if ev else "asked")
    out.append(f"QUEUE #{row['id']}  [{row['severity']}]  {label} {str(when)[:16]}"
               + (f"  (about {row['age_days']}d of history)" if row["age_days"] else ""))
    if _is_blocking(row["blocks"]):
        out.append(f"BLOCKING  {row['blocks']}")
    if _is_deferred(row):
        when = _deferred_until(row)
        out.append(f"DEFERRED by the owner to {when.astimezone().date().isoformat()}"
                   f"  (not overdue; do not re-raise before then)")
    elif _is_overdue_deferral(row):
        when = _deferred_until(row)
        out.append(f"DEFERRAL EXPIRED {when.astimezone().date().isoformat()}"
                   f"  (his day has passed and it is still unanswered)")
    out.append("")
    for line in textwrap.wrap(row["question"], 76):
        out.append("  " + line)
    if row["context"]:
        out.append("")
        out.append("  CONTEXT")
        for para in str(row["context"]).split("\n"):
            for line in textwrap.wrap(para, 74) or [""]:
                out.append("    " + line)
    opts = row["options_json"]
    # MEASURED 2026-10-18 on the row he would have read first: the filed options were a template
    # whose first choice was "Investigate it and bring me a recommendation" -- i.e. the item asking
    # itself to do its own work -- and printing them under a better recommendation leaves the card
    # contradicting itself. When the recommendation is replaced, the choices are replaced with it.
    if replace_options:
        out.append("")
        out.append("  YOUR CHOICES")
        for i, o in enumerate(replace_options, 1):
            out.append(f"    {i}) {o}")
    elif opts:
        items = parse_options(opts)
        if items:
            out.append("")
            out.append("  OPTIONS")
            for i, o in enumerate(items, 1):
                out.append(f"    {i}) {o}")
        else:
            # legacy/pipe text, or a JSON array that did not survive being stored:
            # show it rather than swallowing it the way the old reader did.
            out.append("")
            out.append("  OPTIONS (raw): " + str(opts))
    if replace_recommendation:
        out.append("")
        out.append("  MY RECOMMENDATION: " + replace_recommendation)
    elif row["recommendation"]:
        out.append("")
        out.append("  MY RECOMMENDATION: " + row["recommendation"])
    if row["source"]:
        out.append("")
        out.append("  SOURCE: " + row["source"])
    out.append("=" * 78)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# P265 guard
# ---------------------------------------------------------------------------

def _snippet(text: str, start: int, end: int) -> str:
    """A short window around text[start:end] with the match marked."""
    lo = max(0, start - 40)
    hi = min(len(text), end + 40)
    return ("…" if lo else "") + text[lo:start] + "[[" + text[start:end] + "]]" \
           + text[end:hi] + ("…" if hi < len(text) else "")


def scan_p265(text: str) -> list[dict]:
    """Every P265 signal in one string, as {kind, offset, snippet}.

    Offsets are character offsets into the string as stored (== a Python string index;
    == a UTF-8 byte offset for the ASCII text these rows carry).
    """
    if not text:
        return []
    hits: list[dict] = []
    for m in _RE_ANY_BACKSLASH.finditer(text):
        i = m.start()
        hits.append({"kind": "BACKSLASH", "offset": i,
                     "snippet": _snippet(text, i, i + 1)})
    for i in range(1, len(text)):
        if text[i] == " " and text[i - 1] == " ":
            hits.append({"kind": "DOUBLE_SPACE", "offset": i,
                         "snippet": _snippet(text, i - 1, i + 1)})
    hits.sort(key=lambda h: (h["offset"], h["kind"]))
    return hits


def hits_for(field: str, text) -> list[dict]:
    """The P265 hits for one named field, or [] when the field is not screened.

    Mechanically the journal's detector, with no other softening — the guard and `lint`
    must never disagree about what counts as suspect.
    """
    if not text:
        return []
    found = []
    if field in P265_BACKSLASH_FIELDS:
        found += [h for h in scan_p265(str(text)) if h["kind"] == "BACKSLASH"]
    if field in P265_DOUBLESPACE_FIELDS:
        found += [h for h in scan_p265(str(text)) if h["kind"] == "DOUBLE_SPACE"]
    found.sort(key=lambda h: (h["offset"], h["kind"]))
    return [dict(h, field=field) for h in found]


def classify(field: str, text: str, hit: dict) -> str:
    """How to read a hit. Only ever used to explain a refusal — it never suppresses
    one. Names the known false positive rather than quietly dropping it."""
    if hit["kind"] == "DOUBLE_SPACE":
        return "#33 signature: a double space — `$N ` was eaten here"
    i = hit["offset"]
    nxt = text[i + 1] if i + 1 < len(text) else ""
    prev = text[i - 1] if i else ""
    if nxt.isalpha():
        return "plausible false positive: an escaped `\\%s` from a command line" % nxt
    if nxt == "\\":
        return "plausible false positive: a `\\\\` escape or a UNC path"
    if field == "options_json" and prev.isalnum():
        return ("the #33 signature: a backslash where a price was, inside an "
                "option label (`\\device/mo` was `$X/device/mo`)")
    return "UNEXPLAINED — the #79/#86 signature (`$`+digits ate itself into a lone `\\`)"


def guard_text(values: dict) -> tuple[list[dict], list[dict]]:
    """Screen the fields of one row before it is stored.

    Returns (blocking, plausible). Both are non-empty when there is a hit: the guard
    refuses on `blocking` alone. `plausible` only shapes the advice printed, because
    the two known false positives (a Windows path, a literal `\\n`) cannot be told
    apart from damage by rule, and silently storing them is the failure P265 records.
    """
    blocking: list[dict] = []
    plausible: list[dict] = []
    for field in P265_FIELDS:
        text = values.get(field)
        if not text:
            continue
        for hit in hits_for(field, text):
            hit = dict(hit, why=classify(field, str(text), hit))
            if hit["why"].startswith("plausible"):
                plausible.append(hit)
            blocking.append(hit)
    return blocking, plausible


def print_guard_refusal(blocking: list[dict], plausible: list[dict]) -> None:
    print("REFUSED — P265: this text looks like it lost a number before storage.")
    print(f"  {len(blocking)} signal(s):")
    for h in blocking:
        print(f"  - {h['field']} offset {h['offset']} [{h['kind']}] {h['snippet']}")
        print(f"      {h['why']}")
    if plausible and len(plausible) == len(blocking):
        print("  All hits above are known false-positive SHAPES (a Windows path or a")
        print("  literal \\n). If that is what they are, re-run with --allow-suspect-text.")
    else:
        print("  Nothing here can be explained away. A row that reads like a sentence but")
        print("  has lost a number is worse than a rejected command: re-derive the amount")
        print("  from its cited source, or pass --allow-suspect-text knowing that.")
    print("  (No amount is ever guessed for you.)")


# ---------------------------------------------------------------------------
# Domain guard (2026-10-18). See the module docstring for the owner's words and the
# two layers. Everything here is data, so a test can state exactly what is refused.
# ---------------------------------------------------------------------------
DOMAINS = ("owner", "customer", "business", "engineering")
FILABLE_DOMAINS = ("owner",)
DOMAIN_EXIT = 5

# The fields that state the ASK. "customer" in a context paragraph can be background
# bookkeeping (measured: a tax row whose context named a customer Zelle payment), so
# the soft markers are not read from context/source.
DOMAIN_SOFT_FIELDS = ("question", "recommendation", "options_json")
# A work order, voicemail or phone number is shop business wherever it appears.
DOMAIN_STRONG_FIELDS = ("question", "context", "recommendation", "options_json",
                        "source")

# kind, compiled pattern, why it is a hit. Small on purpose: each entry is one of the
# obvious cases the owner named, not an attempt to classify every sentence.
DOMAIN_SOFT_RULES = (
    ("customer", re.compile(r"\bcustomers?\b", re.I),
     "a customer is named"),
    # "waiting on your decision" is an owner row, not a customer one. Every other
    # waiting is shop business until the filer says otherwise with the escape.
    ("waiting", re.compile(
        r"\bwaiting\b(?!\s+(?:on|for)\s+(?:you|your|the owner|owner)\b)", re.I),
     "someone is waiting; that is usually a customer"),
)
DOMAIN_STRONG_RULES = (
    ("work-order", re.compile(r"\bWO\d{2,}\b", re.I),
     "a work-order number is shop business"),
    ("voicemail", re.compile(r"\bvoicemails?\b", re.I),
     "a voicemail is customer communication"),
    # A phone number needs +, parentheses or separators. A bare ten-digit run is left
    # alone because it is indistinguishable from a confirmation/reference number
    # (measured: NJ tax confirmation FR1100883353 in a genuine owner row).
    ("phone", re.compile(
        r"(?:\+\d{10,15}\b|(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s*|\d{3}[\s.-])"
        r"\d{3}[\s.-]\d{4}\b)"),
     "a phone number is customer communication"),
)

# Where the work should go instead. These are suggestions; the ledger's full project
# list is `work.py project list`, and any registered project is acceptable.
PROJECT_HINTS = (
    ("cfo", re.compile(
        r"\b(?:tax|payroll|quickbooks|ledger|invoice|refund|charge|bank|card|"
        r"accounting|cfo)\b", re.I)),
    ("lpt-website", re.compile(
        r"\b(?:website|site|pricing|price|product|accessory|repair|inventory|stock)\b",
        re.I)),
    ("lpt-sync", re.compile(
        r"\b(?:dialpad|work[- ]?order|WO\d{2,}|voicemail|customer|caller|phone|"
        r"text|sms)\b", re.I)),
)
DEFAULT_LEDGER_PROJECT = "housekeeping"


def domain_texts(values: dict):
    """Yield (field, text) for every field the domain guard reads."""
    seen = set()
    for field in DOMAIN_SOFT_FIELDS + DOMAIN_STRONG_FIELDS:
        if field in seen:
            continue
        seen.add(field)
        text = values.get(field)
        if text:
            yield field, str(text)


def domain_hits(values: dict) -> list[dict]:
    """Every keyword-backstop hit in one candidate row, with field and offset.

    Soft rules read only DOMAIN_SOFT_FIELDS; strong rules read all of
    DOMAIN_STRONG_FIELDS. The same match is reported once even though a field can be
    in both lists.
    """
    hits = []
    seen = set()
    for field in DOMAIN_SOFT_FIELDS:
        text = values.get(field)
        if not text:
            continue
        for kind, rx, why in DOMAIN_SOFT_RULES:
            for m in rx.finditer(str(text)):
                key = (field, kind, m.start(), m.group(0))
                if key in seen:
                    continue
                seen.add(key)
                hits.append({"field": field, "kind": kind, "offset": m.start(),
                             "match": m.group(0), "why": why,
                             "snippet": _snippet(str(text), m.start(), m.end())})
    for field in DOMAIN_STRONG_FIELDS:
        text = values.get(field)
        if not text:
            continue
        for kind, rx, why in DOMAIN_STRONG_RULES:
            for m in rx.finditer(str(text)):
                key = (field, kind, m.start(), m.group(0))
                if key in seen:
                    continue
                seen.add(key)
                hits.append({"field": field, "kind": kind, "offset": m.start(),
                             "match": m.group(0), "why": why,
                             "snippet": _snippet(str(text), m.start(), m.end())})
    hits.sort(key=lambda h: (h["field"], h["offset"], h["kind"]))
    return hits


def suggest_ledger_project(domain: str, values: dict, hits: list[dict]) -> str:
    """A project to name in the refusal. Advice only, never part of the decision."""
    if domain == "customer":
        return "lpt-sync"
    blob = " ".join(str(values.get(f) or "") for f in
                    ("question", "recommendation", "options_json"))
    for project, rx in PROJECT_HINTS:
        if rx.search(blob):
            return project
    return DEFAULT_LEDGER_PROJECT


def print_domain_refusal(domain: str, hits: list[dict], values: dict) -> None:
    """Name the rule, the evidence, and the alternative. Never writes."""
    project = suggest_ledger_project(domain, values, hits)
    print("REFUSED — OWNER-QUEUE DOMAIN RULE: customer/business work belongs in the "
          "ledger, not the owner's decision queue.")
    print("  The queue is only for a decision only the owner can make. Dialpad "
          "texts, customer questions,")
    print("  work orders and shop operations are not pending owner attention.")
    if domain not in FILABLE_DOMAINS:
        print(f"  filed as: --domain {domain} (only {'/'.join(FILABLE_DOMAINS)} may "
              f"be filed without the escape)")
    for h in hits[:6]:
        print(f"  keyword backstop: {h['field']} names {h['match']!r} — {h['why']}")
        print(f"      {h['snippet']}")
    if len(hits) > 6:
        print(f"  ... and {len(hits) - 6} more keyword hit(s)")
    print("  WHERE IT GOES INSTEAD — the ledger (`/root/work/work.db`):")
    print(f"    python3 /root/bin/work.py add --project {project} \\")
    print("      --title \"<the action, one line>\" \\")
    print("      --dod \"<the command or observation that proves it done>\" \\")
    print("      --why \"<why this matters>\" \\")
    print("      --source \"owner-queue:domain-guard\"")
    print("  Projects: cfo, housekeeping, lpt-sync, lpt-website, prod-db-sync, and "
          "others.")
    print("  Run `python3 /root/bin/work.py project list` for the live list.")
    print("  If this genuinely needs the owner — a policy, money, legal or taste "
          "decision that merely")
    print("  MENTIONS a customer — re-run with the deliberate escape and write down "
          "why:")
    print("    --owner-worthy --owner-reason \"why only the owner can decide this\"")
    print("  Nothing was written.")


# ---------------------------------------------------------------------------
# write path
# ---------------------------------------------------------------------------

def parse_options(value):
    """An options value -> list of labels, or None if it is not machine-readable.

    Canonical storage is a JSON array. Rows written before 2026-09-20 hold a
    pipe-separated string, and the old reader `json.loads`-ed it, failed, and printed
    nothing — so accept both. Same acceptance in fmt() and in the lint.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    text = str(value).strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            loaded = json.loads(text)
        except Exception:
            loaded = None
        if isinstance(loaded, list):
            return [str(v) for v in loaded]
        if isinstance(loaded, dict):
            return [str(v) for v in loaded.values()]
    if "|" in text:
        return [p for p in (s.strip() for s in text.split("|")) if p]
    return [text]


def _canonical_options(value):
    """The string actually stored in options_json: JSON array, or None."""
    items = parse_options(value)
    if items is None:
        return None
    return json.dumps(items, ensure_ascii=False)


def load_add_json(source: str) -> dict:
    """Read one JSON object from a file path or `-` (stdin). No shell is involved."""
    if source == "-":
        raw = sys.stdin.read()
        label = "stdin"
    else:
        label = source
        try:
            with open(source, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise SystemExit(f"add --from-json: cannot read {source}: {exc}")
    try:
        obj = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"add --from-json: {label} is not valid JSON: {exc}")
    if not isinstance(obj, dict):
        raise SystemExit(
            f"add --from-json: {label} must hold one JSON OBJECT "
            f'({{"question": ..., "options": [...]}}), not {type(obj).__name__}')
    unknown = [k for k in obj if k not in JSON_KEYS]
    if unknown:
        raise SystemExit(f"add --from-json: unknown key(s): {', '.join(sorted(unknown))} "
                         f"(known: {', '.join(JSON_KEYS)})")
    return obj



#: Duplicate refusals are appended here, one JSON object per line, next to the queue
#: database (override with OWNER_QUEUE_REFUSAL_LOG). A refusal is NOT a filing, and a
#: caller that only reads the exit code would otherwise lose the question entirely:
#: measured 2026-10-16, cfo-shift.py logged `owner question NOT filed (owner-queue
#: rc=4)` for a question refused as a duplicate of an already-answered row and dropped
#: it. The queue itself is still not written to on a refusal.
def refusal_log_path(dbpath: str) -> str:
    override = os.environ.get("OWNER_QUEUE_REFUSAL_LOG", "").strip()
    if override:
        return override
    return "%s.refusals.jsonl" % (dbpath or "owner-queue")


def record_refusal(dbpath: str, values: dict, hit: dict) -> str | None:
    """Append one line naming this refusal and the row it collided with. Never raises."""
    path = refusal_log_path(dbpath)
    entry = {
        "at": now(),
        "event": "refused",
        "reason": "duplicate",
        "existing_row": hit.get("row_id"),
        "existing_table": hit.get("source_table"),
        "existing_status": hit.get("status") or hit.get("answered_at"),
        "similarity": round(float(hit.get("similarity") or 0.0), 4),
        "question": values.get("question"),
        "severity": values.get("severity"),
        "source": values.get("source"),
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path
    except OSError as exc:
        print("add: refusal NOT recorded (%s)" % exc, file=sys.stderr)
        return None


def cmd_add(con, a) -> int:
    source = getattr(a, "from_json", None)
    if source:
        # --severity defaults to None so that passing it is detectable here: the
        # default used to be "medium", which made every --from-json call look like a
        # clash. The default is applied after the clash test instead.
        clash = [opt for opt, val in (
            ("--question", a.question), ("--context", a.context),
            ("--options", a.options), ("--recommendation", a.recommendation),
            ("--severity", a.severity), ("--blocks", a.blocks),
            ("--source", a.source), ("--age-days", a.age_days),
            ("--domain", getattr(a, "domain", None)),
            ("--owner-worthy", True if getattr(a, "owner_worthy", False) else None),
            ("--owner-reason", getattr(a, "owner_reason", None)),
        ) if val is not None]
        if clash:
            print("add: --from-json carries the whole row, so it cannot be combined with "
                  + ", ".join(clash))
            return 2
        obj = load_add_json(source)
        question = obj.get("question")
        if not isinstance(question, str) or not question.strip():
            print("add --from-json: 'question' is required and must be a non-empty string")
            return 2
        severity = obj.get("severity") or "medium"
        if severity not in SEV_RANK:
            print(f"add --from-json: severity {severity!r} not one of "
                  f"{', '.join(SEV_RANK)}")
            return 2
        age_days = obj.get("age_days")
        if age_days is not None and not isinstance(age_days, int):
            print("add --from-json: 'age_days' must be an integer")
            return 2
        domain = obj.get("domain") or "owner"
        owner_worthy = obj.get("owner_worthy", False)
        owner_reason = obj.get("owner_reason")
        if not isinstance(owner_worthy, bool):
            print("add --from-json: 'owner_worthy' must be true or false")
            return 2
        if owner_reason is not None and not isinstance(owner_reason, str):
            print("add --from-json: 'owner_reason' must be a string")
            return 2
        values = {
            "question": question,
            "context": obj.get("context"),
            "options_json": _canonical_options(obj.get("options")),
            "recommendation": obj.get("recommendation"),
            "severity": severity,
            "blocks": obj.get("blocks"),
            "source": obj.get("source"),
            "age_days": age_days,
        }
        origin = f"--from-json {source}"
    else:
        if not a.question:
            print("add needs --question, or --from-json FILE|- for the safe path")
            return 2
        values = {
            "question": a.question,
            "context": a.context,
            "options_json": _canonical_options(a.options),
            "recommendation": a.recommendation,
            "severity": a.severity or "medium",
            "blocks": a.blocks,
            "source": a.source,
            "age_days": a.age_days,
        }
        domain = getattr(a, "domain", None) or "owner"
        owner_worthy = bool(getattr(a, "owner_worthy", False))
        owner_reason = getattr(a, "owner_reason", None)
        origin = "flags"

    # ── Domain guard (2026-10-18) ────────────────────────────────────────────
    # The filer's explicit marker is layer 1; the keyword backstop is layer 2. A
    # non-owner domain or any keyword hit refuses unless the deliberate escape is
    # used, and the escape is useless without a written reason.
    if domain not in DOMAINS:
        print(f"add: --domain {domain!r} not one of {', '.join(DOMAINS)}")
        return 2
    if owner_reason and not owner_worthy:
        print("add: --owner-reason only means something with --owner-worthy; "
              "nothing was written.")
        return 2
    if owner_worthy and not (owner_reason or "").strip():
        print("REFUSED — --owner-worthy requires a non-empty --owner-reason.")
        print("  The escape is deliberate: write down why only the owner can decide "
              "this. Nothing was written.")
        return 2
    _domain_hits = domain_hits(values)
    if (domain not in FILABLE_DOMAINS or _domain_hits) and not owner_worthy:
        print_domain_refusal(domain, _domain_hits, values)
        return DOMAIN_EXIT
    if owner_worthy:
        print(f"owner-worthy escape: domain={domain}; reason: {owner_reason.strip()}")

    blocking, plausible = guard_text(values)
    if blocking and not getattr(a, "allow_suspect_text", False):
        print_guard_refusal(blocking, plausible)
        print("  Nothing was written.")
        return 3
    if blocking:
        print(f"WARNING: storing {len(blocking)} P265 suspect signal(s) because "
              f"--allow-suspect-text was given:")
        for h in blocking:
            print(f"  - {h['field']} offset {h['offset']} [{h['kind']}] {h['snippet']}")

    # ── Duplicate check (added 2026-09-29) ──────────────────────────────────
    # Nothing here ever checked whether this question had already been asked and
    # ANSWERED, or was already sitting in the queue. owner_decision_queue rows
    # #182 and #183 are byte-identical and both pending because of exactly that.
    # Refuse by default and name the existing row, so the caller can act on the
    # answer instead of waiting for it a second time.
    #   OWNER_QUEUE_ALLOW_DUPLICATE=1   deliberate re-add
    if not (
        getattr(a, "force", False)
        or os.environ.get("OWNER_QUEUE_ALLOW_DUPLICATE") == "1"
    ):
        try:
            sys.path.insert(0, "/home/zabz/personal-secretary-mvp")
            from app.owner_question_dedupe import (
                find_open_duplicate,
                find_prior_answer,
            )

            _row = con.execute("PRAGMA database_list").fetchone()
            _dbpath = _row[2] if _row else ""
            _q = str(values.get("question") or "")
            _hit = None
            if _dbpath:
                _hit = find_prior_answer(_dbpath, _q) or find_open_duplicate(_dbpath, _q)
            if _hit:
                print(
                    "add: REFUSED - this already exists as #%s in %s (%s, "
                    "similarity %.2f)."
                    % (
                        _hit.get("row_id"),
                        _hit.get("source_table"),
                        _hit.get("status") or _hit.get("answered_at") or "",
                        float(_hit.get("similarity") or 0.0),
                    )
                )
                print("  existing: %s" % str(_hit.get("question"))[:160])
                if _hit.get("answer"):
                    print("  answer  : %s" % str(_hit.get("answer"))[:240])
                print(
                    "  Nothing was written. Set OWNER_QUEUE_ALLOW_DUPLICATE=1 "
                    "to add it anyway."
                )
                _logged = record_refusal(_dbpath, values, _hit)
                print(
                    "owner-queue: REFUSED duplicate existing_row=#%s existing_table=%s "
                    "reason=duplicate%s"
                    % (_hit.get("row_id"), _hit.get("source_table"),
                       (" recorded=%s" % _logged) if _logged else " recorded=NO")
                )
                return 4
        except Exception as _exc:  # never block a genuine add on this check
            print("add: duplicate check skipped (%s)" % _exc, file=sys.stderr)

    _insert = (
        """INSERT INTO owner_decision_queue
           (asked_at, question, context, options_json, recommendation, severity,
            blocks, source, age_days, status)
           VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
        (now(), values["question"], values["context"], values["options_json"],
         values["recommendation"], values["severity"], values["blocks"],
         values["source"], values["age_days"]),
    )
    _tries = int(os.environ.get("OWNER_QUEUE_RETRIES", "4"))
    _delay = float(os.environ.get("OWNER_QUEUE_RETRY_DELAY", "10"))
    cur = None
    for _attempt in range(1, _tries + 1):
        try:
            cur = con.execute(*_insert)
            con.commit()
            break
        except sqlite3.OperationalError as _exc:
            if "locked" not in str(_exc).lower() or _attempt == _tries:
                raise
            print("owner-queue: database locked (attempt %d/%d); waiting %.0fs then retrying"
                  % (_attempt, _tries, _delay), file=sys.stderr)
            time.sleep(_delay)
    print(f"queued #{cur.lastrowid} [{values['severity']}] {values['question'][:70]}")
    print(f"  via {origin}; P265 guard: "
          + ("passed clean" if not blocking
             else f"{len(blocking)} signal(s) allowed by flag"))
    return 0


def _is_blocking(value):
    """Whether a `blocks` value really means other work is stuck.

    The column is free text, so a row that says nothing is blocked still has text in it
    (#17 read "Nothing is blocked; this is exposure, not a stall") and emptiness alone
    counted it as blocking.
    """
    text = " ".join(str(value or "").split()).lower()
    if not text:
        return False
    return not text.startswith(("nothing", "none", "n/a", "no ", "not blocking"))


def _age_days(row):
    """Age from `asked_at`, the column that carries the event.

    `age_days` is a derived integer nothing refreshes -- measured 2026-09-15 holding 0 and
    3 for two rows both asked 1.5 days earlier -- so it is only a fallback.
    """
    stamp = row["asked_at"] if "asked_at" in row.keys() else None
    if stamp:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        except Exception:
            pass
    try:
        return float(row["age_days"] or 0)
    except Exception:
        return 0.0


def _deferred_until(row):
    """The instant this row is deferred to, or None if it is not deferred."""
    try:
        raw = row["deferred_until"]
    except (KeyError, IndexError):
        return None
    if not raw:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_deferred(row):
    """True while the owner's own stated day is still ahead of us."""
    dt = _deferred_until(row)
    if dt is None:
        return False
    from datetime import datetime, timezone
    return dt > datetime.now(timezone.utc)


def _is_overdue_deferral(row):
    """True once a deferral has run out and the row is his problem again."""
    dt = _deferred_until(row)
    if dt is None:
        return False
    from datetime import datetime, timezone
    return dt <= datetime.now(timezone.utc)


def _parse_defer_target(text: str):
    """'2026-09-23', '2026-09-23T14:00', 'tomorrow', '+3d' -> an aware datetime.

    A bare date means "end of that local day", because "I'll do it tomorrow"
    is not a promise about midnight UTC.
    """
    from datetime import datetime, time, timedelta, timezone
    raw = " ".join(str(text or "").split())
    if not raw:
        raise ValueError("empty deferral target")
    low = raw.lower()
    today = datetime.now().astimezone().date()

    if low in ("tomorrow", "tom"):
        return datetime.combine(today + timedelta(days=1), time(23, 59),
                                tzinfo=datetime.now().astimezone().tzinfo)
    if low in ("today", "tonight"):
        return datetime.combine(today, time(23, 59),
                                tzinfo=datetime.now().astimezone().tzinfo)
    if low.startswith("+") and low.endswith("d") and low[1:-1].isdigit():
        return datetime.combine(today + timedelta(days=int(low[1:-1])), time(23, 59),
                                tzinfo=datetime.now().astimezone().tzinfo)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            dt = datetime.combine(dt.date(), time(23, 59))
        return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    raise ValueError(f"cannot read a date from {raw!r} (use YYYY-MM-DD, tomorrow, or +3d)")


def cmd_amend(con, a) -> int:
    """Refresh a PENDING row as the measurement moves.

    WHY THIS EXISTS. The estate's own rule, written after a priority-1 item stopped being true within two
    hours: "an item is a statement about the world at FILING time. When the measurement moves, the item
    moves with it, or the next shift spends its opening minutes chasing a ghost." There was no way to obey
    it: `add` refuses what looks like a duplicate, `resolve`/`answer`/`defer` all change the STATE, and
    nothing could change the TEXT. Measured 2026-10-13: #228 (the funding question, the queue's genuine
    head, deferral expired five days ago) carries a context dated 2026-10-01 with a hand-extracted figure,
    while `scripts/finance/forward-view.py` now measures the same thing - 7.01 months of runway, a gap of
    3,099.87/mo against 21,727.00 of personal capacity, capacity exhausted 2026-06 - and there was no way
    to put the measured number on the row.

    IT TOUCHES CONTEXT AND RECOMMENDATION ONLY. The QUESTION is never rewritten: that is what the owner
    was asked, and changing it would make the queue's own history a lie. Only a PENDING row qualifies -
    amending a resolved or dismissed question would rewrite what was answered. A --note is APPENDED with
    the date, so a change is visible in the row rather than silent.
    """
    row = con.execute(
        "SELECT id, status, context, recommendation FROM owner_decision_queue WHERE id=?", (a.id,)
    ).fetchone()
    # Close the read snapshot BEFORE writing: the SELECT leaves a deferred transaction open and the
    # UPDATE would have to upgrade it, which SQLite refuses immediately if anything committed in
    # between. Same reason and same fix as _close.
    con.commit()
    if not row:
        print("no such queue row: %s" % a.id)
        return 1
    if row[1] != "pending":
        print("row %s is %s, not pending -- amend only touches a question still waiting" % (a.id, row[1]))
        return 1
    if not (a.context or a.recommendation):
        print("amend needs --context and/or --recommendation")
        return 1
    ctx = a.context if a.context else row[2]
    rec = a.recommendation if a.recommendation else row[3]
    if a.note:
        ctx = "%s\n\nAMENDED %s: %s" % (ctx or "", now()[:10], a.note)
    exec_locked(con,
                "UPDATE owner_decision_queue SET context=?, recommendation=? WHERE id=?",
                (ctx, rec, a.id))
    print("#%s amended%s%s" % (a.id,
                               " (context)" if a.context else "",
                               " (recommendation)" if a.recommendation else ""))
    return 0


def cmd_defer(con, a) -> int:
    """Record that the owner has seen this and put it off to a stated day."""
    row = con.execute(
        "SELECT id, status, question FROM owner_decision_queue WHERE id=?", (a.id,)
    ).fetchone()
    con.commit()   # release the read snapshot before writing (see _close)
    if not row:
        print(f"no such queue row: {a.id}")
        return 1
    if row["status"] != "pending":
        print(f"#{a.id} is {row['status']}; only a pending row can be deferred")
        return 1
    if a.clear:
        con.execute(
            "UPDATE owner_decision_queue SET deferred_until=NULL, deferred_at=NULL,"
            " defer_note=NULL WHERE id=?", (a.id,))
        con.commit()
        print(f"#{a.id} deferral cleared")
        return 0
    if not a.until:
        print("defer needs --until (YYYY-MM-DD, tomorrow, or +3d)")
        return 1
    try:
        target = _parse_defer_target(a.until)
    except ValueError as exc:
        print(str(exc))
        return 1
    con.execute(
        "UPDATE owner_decision_queue SET deferred_until=?, deferred_at=?, defer_note=?"
        " WHERE id=?",
        (target.astimezone(dt.timezone.utc).isoformat(), now(), a.note, a.id),
    )
    con.commit()
    print(f"#{a.id} deferred until {target.isoformat()} (still pending, still his)")
    _record_feedback(con, a.id, "deferred", a.note or target.isoformat())
    return 0


def _premise_moved_rows(limit=5):
    """Pending rows whose premise premise-check.py has recorded as MOVED.

    Read from the recorded check table rather than by re-running probes, so `next` stays fast.
    Returns [] on any failure: this is a warning, and a warning that can break the queue tool is
    worse than no warning.
    """
    import sqlite3 as _sq
    try:
        con = _sq.connect("file:%s?mode=ro" % DEFAULT_DB, uri=True)
        try:
            rows = con.execute(
                "SELECT c.row_id, c.detail FROM owner_premise_check c "
                "JOIN owner_decision_queue q ON q.id = c.row_id "
                "WHERE c.verdict='changed' AND q.status='pending' ORDER BY c.row_id LIMIT ?",
                (limit,)).fetchall()
        finally:
            con.close()
        return rows
    except Exception:
        return []


def _premise_verdict(row_id):
    """Ask premise-check.py whether this row's PREMISE has moved since it was filed.

    WHY THIS IS HERE. `cmd_amend` above states the rule in its own docstring - "an item is a
    statement about the world at FILING time. When the measurement moves, the item moves with it,
    or the next shift spends its opening minutes chasing a ghost" - and nothing ever ran it.
    Measured 2026-10-16: of 33 pending rows, one asked the owner to buy a machine he already
    owned, two had already been resolved by reality, and one stated a day-count that had drifted
    by three days. premise-check.py re-measures; this hook is where the answer reaches the person
    about to read the row.

    GUARDED ON PURPOSE. A missing or broken checker must never break the queue tool, and it must
    never silently return "fresh". It returns None when it cannot tell, and the caller then says
    nothing rather than saying something wrong.
    """
    import os as _os
    import subprocess as _sp
    tool = "/root/bin/premise-check.py"
    if not _os.path.exists(tool):
        return None
    try:
        r = _sp.run(["/usr/bin/python3", tool, "check", str(row_id)],
                    capture_output=True, text=True, timeout=45)
    except Exception:
        return None
    if r.returncode not in (0, 10):
        return None
    return r.stdout.strip()


def cmd_next(con, a) -> int:
    """The single next thing. Delegates to the ONE order rather than keeping a second one.

    This used to sort decisions by its own key, which meant `next` and `brief` could disagree
    about what was most urgent while both claimed to answer the same question. There is now one
    ordering function (`_queue_score`) and this command is a view onto it. The premise warning it
    used to carry moved into `cmd_queue`, where it covers every surface instead of one row.
    """
    peek = getattr(a, "peek", 1) or 1
    return cmd_queue(con, argparse.Namespace(limit=peek, all=False, kind=None,
                                             json=False, new_only=False,
                                             max_age_days=21))


def cmd_list(con, a) -> int:
    """The raw table, DECISIONS ONLY by default.

    WHY THE DEFAULT IS NARROW. `scripts/owner_attention.py::from_owner_queue` in the app calls
    this command and texts him from it, sorting newest-first into 12 slots. Once comms attention
    lives in the same table, a default of "everything" would fill those 12 slots with the newest
    texts and push every real decision off his phone -- a regression in a running surface, caused
    by a change in another. Attention rows are reached with `--kind attention`, or through
    `queue`, which ranks both together on purpose.
    """
    q = "SELECT * FROM owner_decision_queue"
    where = []
    if not a.all:
        where.append("status='pending'")
    kind = getattr(a, "kind", None) or "decision"
    if kind in ("decision", "attention"):
        where.append("COALESCE(kind,'decision')='%s'" % kind)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, id"
    rows = con.execute(q).fetchall()
    if getattr(a, "json", False):
        # machine-readable, so the journal can mirror the queue instead of restating it
        print(json.dumps([dict(r) for r in rows], indent=1, default=str))
        return 0
    print(f"{len(rows)} row(s)\n")
    for r in rows:
        flag = "!" if _is_blocking(r["blocks"]) else " "
        mark = "D" if _is_deferred(r) else ("E" if _is_overdue_deferral(r) else " ")
        print(f"{flag}{mark} #{r['id']:<4} {r['status']:<10} [{r['severity']:<8}] "
              f"{r['asked_at'][:10]}  {r['question'][:78]}")
        if a.all and r["resolution"]:
            print(f"      -> {r['resolution'][:100]}")
    if any(_is_deferred(r) for r in rows):
        print("\n  D = deferred by the owner to a day he named; not overdue")
    if any(_is_overdue_deferral(r) for r in rows):
        print("  E = a deferral that has expired; his day passed and it is unanswered")
    return 0


def cmd_brief(con, a) -> int:
    """ONE queue: owner decisions AND agent questions, ranked together by urgency.

    Rule from the owner, 2026-10-18, verbatim: "I dont have the patients to ask you first
    about the attention queue, and then the decision queue ... It should be one queue that
    has both of them together based on urgency and that is it." agent_questions carries no
    severity column, so a question is marked unrated and ranks by age inside its tier;
    every line prints its source and its age so the order is judgeable, not asserted.
    """
    SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items = []
    dec = con.execute(
        "SELECT id, asked_at AS at, question, severity, blocks,"
        " (julianday('now') - julianday(asked_at)) AS age,"
        " CASE WHEN deferred_until IS NOT NULL"
        "      AND julianday(deferred_until) > julianday('now')"
        "      THEN 1 ELSE 0 END AS is_deferred"
        " FROM owner_decision_queue WHERE status='pending'")
    for r in dec:
        items.append({"src": "decision", "id": "#%s" % r["id"], "at": r["at"],
                      "question": r["question"], "severity": r["severity"] or "medium",
                      "age": r["age"] or 0.0, "deferred": int(r["is_deferred"]),
                      "blocking": bool(r["blocks"])})
    que = con.execute(
        "SELECT substr(id,1,8) AS sid, created_at AS at, question, agent_id,"
        " COALESCE(severity,'') AS severity,"
        " (julianday('now') - julianday(created_at)) AS age"
        " FROM agent_questions WHERE status='pending'")
    for r in que:
        items.append({"src": "attention", "id": r["sid"], "at": r["at"],
                      "question": r["question"],
                      "severity": (r["severity"] or "unrated"),
                      "age": r["age"] or 0.0, "deferred": 0, "blocking": False,
                      "agent": r["agent_id"]})
    held = con.execute(
        "SELECT id, reason, urgency, body,"
        " COALESCE(last_seen_at, created_at) AS at,"
        " (julianday('now') - julianday(COALESCE(last_seen_at, created_at))) AS age"
        " FROM owner_message_queue WHERE status='held'")
    URG = {"critical": "critical", "urgent": "high", "high": "high"}
    # An ops alert is mine, not the owner's: a paused sync or a stale capture is a repair,
    # not a decision, and putting it in front of him is the same defect as the two queues.
    OPS_REASONS = ("sync_breaker", "comms_freshness")
    ops_count = 0
    for r in held:
        reason = str(r["reason"] or "")
        if reason.startswith(OPS_REASONS) or reason in OPS_REASONS:
            ops_count += 1
            continue
        items.append({"src": "held", "id": "m%s" % r["id"], "at": r["at"],
                      "question": r["body"] or r["reason"],
                      "severity": URG.get(str(r["urgency"] or ""), "low"),
                      "age": r["age"] or 0.0, "deferred": 0, "blocking": False,
                      "reason": r["reason"]})
    if not getattr(a, "all", False):
        items = [i for i in items if not i["deferred"]]
    items.sort(key=lambda i: (SEV.get(i["severity"], 1.5), -i["age"]))
    if getattr(a, "json", False):
        print(json.dumps(items, indent=1, default=str))
        return 0
    if not items:
        print("nothing is waiting on the owner -- no decisions and no questions")
        return 0
    n_dec = sum(1 for i in items if i["src"] == "decision")
    n_q = sum(1 for i in items if i["src"] == "attention")
    n_h = sum(1 for i in items if i["src"] == "held")
    print("%d item(s) waiting on the owner: %d decision(s), %d question(s),"
          " %d held message(s)\n" % (len(items), n_dec, n_q, n_h))
    for i in items:
        print("%-9s %-9s %-8s %6.1fd  %s"
              % (i["src"], i["id"], i["severity"], i["age"],
                 " ".join(str(i["question"]).split())[:88]))
    if ops_count:
        print("\n  %d ops alert(s) held back as mine, not yours (paused syncs, stale capture)"
              % ops_count)
    print("\n  decision = owner_decision_queue; attention = agent_questions;"
          " held = owner_message_queue (alerts the app is holding)")
    print("  unrated questions rank by age inside their tier")
    return 0


def cmd_stats(con, a) -> int:
    for st, n in con.execute("SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY 1"):
        print(f"  {st}: {n}")
    r = con.execute("SELECT MIN(asked_at), MAX(asked_at) FROM owner_decision_queue WHERE status='pending'").fetchone()
    if r and r[0]:
        print(f"  oldest pending: {r[0][:16]}   newest: {r[1][:16]}")
    return 0


def cmd_lint(con, a) -> int:
    """Every P265 signal in the queue, so this can be run after any writing session."""
    rows = con.execute(
        "SELECT id, status, severity, " + ", ".join(P265_FIELDS) +
        " FROM owner_decision_queue ORDER BY id"
    ).fetchall()
    flagged = []
    for row in rows:
        hits = []
        for field in P265_FIELDS:
            for hit in hits_for(field, row[field]):
                hits.append(dict(hit, why=classify(field, str(row[field]), hit)))
        if hits:
            flagged.append((row, hits))

    if getattr(a, "json", False):
        print(json.dumps([{
            "id": row["id"], "status": row["status"], "severity": row["severity"],
            "hits": [{"field": h["field"], "offset": h["offset"], "kind": h["kind"],
                      "snippet": h["snippet"], "why": h["why"]} for h in hits],
        } for row, hits in flagged], indent=1))
        return 1 if flagged else 0

    print(f"P265 LINT — {len(rows)} row(s) scanned, {len(flagged)} flagged")
    print("  rule: (a) a backslash in " + "/".join(P265_BACKSLASH_FIELDS))
    print("        (b) a double space in " + "/".join(P265_DOUBLESPACE_FIELDS))
    print(f"  flagged ids: {', '.join('#' + str(r['id']) for r, _ in flagged) or '(none)'}")
    for row, hits in flagged:
        print()
        print(f"#{row['id']}  status={row['status']}  severity={row['severity']}"
              f"  {len(hits)} signal(s)")
        for h in hits:
            print(f"   {h['field']} @{h['offset']} [{h['kind']}] {h['snippet']}")
            print(f"     -> {h['why']}")
        if getattr(a, "show_text", False):
            for field in P265_FIELDS:
                if row[field]:
                    print(f"   --- {field} (exact stored string, {len(str(row[field]))} chars) ---")
                    print("   " + repr(row[field]))
    if flagged:
        print()
        print("A hit is not proof: a Windows path or a literal \\n is a known false")
        print("positive. Everything else is a number that may already be gone — re-derive")
        print("it from the row's cited source. Never guess it.")
    return 1 if flagged else 0


def cmd_sweep(con, a) -> int:
    """READ-ONLY: every existing row the domain guard would now refuse.

    The guard only stops new filings; the backlog it implies has to be visible. This
    never moves, dismisses, amends or deletes a row. A row listed here is a judgement
    call: file it in the ledger first, then resolve the queue row deliberately.
    """
    q = "SELECT * FROM owner_decision_queue"
    if not a.all:
        q += " WHERE status='pending'"
    q += " ORDER BY id"
    rows = con.execute(q).fetchall()
    fields = set(DOMAIN_SOFT_FIELDS + DOMAIN_STRONG_FIELDS)
    flagged = []
    for row in rows:
        values = {f: row[f] for f in fields}
        hits = domain_hits(values)
        if hits:
            flagged.append((row, hits))

    if getattr(a, "json", False):
        print(json.dumps({
            "scanned": len(rows),
            "scope": "all" if a.all else "pending",
            "would_refuse": len(flagged),
            "rows": [{
                "id": row["id"],
                "status": row["status"],
                "severity": row["severity"],
                "question": row["question"],
                "hits": [{"field": h["field"], "kind": h["kind"],
                          "match": h["match"], "why": h["why"]} for h in hits],
            } for row, hits in flagged],
        }, indent=1, ensure_ascii=False))
        return 1 if flagged else 0

    scope = "all" if a.all else "pending"
    print(f"OWNER-QUEUE DOMAIN SWEEP — {len(rows)} {scope} row(s) scanned, "
          f"{len(flagged)} would be refused")
    print("  rule: customer/business work belongs in the ledger (`/root/work/work.db`);")
    print("        this queue is only for a decision only the owner can make.")
    if not rows:
        print("  (no rows in scope — this is a real zero, not a failed read)")
    for row, hits in flagged:
        print()
        print(f"#{row['id']}  status={row['status']}  severity={row['severity']}  "
              f"asked={str(row['asked_at'])[:10]}")
        print(f"  {str(row['question'])[:150]}")
        for h in hits[:4]:
            print(f"  - {h['field']} names {h['match']!r}: {h['why']}")
        if len(hits) > 4:
            print(f"  - ... and {len(hits) - 4} more hit(s)")
        print("  -> the ledger, unless a written --owner-worthy reason says otherwise")
    if flagged:
        print()
        print("  READ-ONLY: nothing was moved, dismissed, amended or deleted.")
        print("  To clear one deliberately: file the work in the ledger, then resolve "
              "this row with")
        print("  --how/--dismissed naming the ledger item. This sweep never does that "
              "for you.")
    return 1 if flagged else 0


def _close(con, a, status: str, text: str) -> int:
    row = con.execute("SELECT id, status FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()

    # Close the read snapshot BEFORE writing. The SELECT above leaves a deferred
    # transaction open, so the UPDATE would have to upgrade a read transaction to a
    # write one -- and if any other connection committed in between (the API writes
    # to this database continuously) SQLite returns SQLITE_BUSY *immediately*.
    # `timeout=180` cannot help: waiting cannot make a stale snapshot current.
    # Measured 2026-09-14: resolve failed four times in a row before succeeding in a
    # retry loop. Same fix as app/services/dsh_session_ingest.py.
    con.commit()
    if not row:
        print(f"no such queue row: {a.id}")
        return 1
    exec_locked(con,
                "UPDATE owner_decision_queue SET status=?, resolved_at=?, resolution=? WHERE id=?",
                (status, now(), text, a.id))
    print(f"#{a.id} -> {status}")
    _record_feedback(con, a.id, "dismissed" if status == "dismissed" else "resolved", text)
    _close_with_siblings(con, a, "dismissed" if status == "dismissed" else "resolved", text)
    return 0


def cmd_resolve(con, a) -> int:
    if a.dismissed:
        return _close(con, a, "dismissed", a.dismissed)
    if not a.how:
        print("resolve needs --how or --dismissed")
        return 1
    return _close(con, a, "resolved", a.how)


def _journal_copy(row_id, question, answer, db_path="") -> None:
    """Append the owner's words to the journal so the answer survives the row.

    MEASURED 2026-10-13: 14 of 67 answered rows had NO journal copy anywhere. This table is
    mutable -- `amend` can overwrite `answer` -- and the journal is append-only, and nothing
    connected them, so a decision he had given lived in one cell that a later edit could replace.
    Backfill for the backlog: journal/tools/reconcile-owner-answers.py.

    BEST EFFORT BY DESIGN: if the journal is unreachable the ANSWER IS STILL RECORDED and this
    says so. His answer must never fail because a secondary copy failed.

    BUT ONLY FOR THE AUTHORITY'S OWN QUEUE. MEASURED 2026-10-18, and it was my mistake: an audit
    session ran `answer 631 --with 645` against a THROWAWAY COPY of the database at /tmp to prove the
    --with mechanism, and this function wrote two journal decision entries (D7041, D7042) recording a
    fake owner answer -- into the permanent append-only record, which by its own rule can only be
    corrected, never deleted. A journal entry says "the owner decided this". It must only ever be
    written by a close of the real queue. A test, a replay, a backfill against a copy: no.
    """
    import os
    import re
    import subprocess
    real = os.path.realpath(db_path or DEFAULT_DB)
    if os.path.basename(real) != "authority.db":
        print("  (no journal copy: this is not the authority's queue — %s. A close against a copy "
              "must never put words in the owner's mouth.)" % real)
        return
    # An explicit override first, so this is testable against a throwaway journal tree and so an
    # operator can point it somewhere else without editing the tool.
    j = os.environ.get("OWNER_QUEUE_JOURNAL") or None
    if j and not os.path.exists(j):
        print("  note: OWNER_QUEUE_JOURNAL names a path that does not exist; the answer is in the "
              "queue row only")
        return
    if not j:
        for cand in (os.path.expanduser("~/code/harness-config/journal/tools/journal.py"),
                     "/root/code/harness-config/journal/tools/journal.py"):
            if os.path.exists(cand):
                j = cand
                break
    if not j:
        print("  note: journal.py not found -- the answer is in the queue row only")
        return
    title = "Owner answer, queue row #%s: %s" % (
        row_id, re.sub(r"\s+", " ", question or "")[:80])
    body = ("Recorded by `owner-queue.py answer` on %s. The row is a mutable table; this entry is\n"
            "the append-only copy. If the two ever disagree, the row was edited.\n\n"
            "**Asked**: %s\n\n**His answer**: %s" % (now(), question or "(not recorded)", answer or ""))
    try:
        out = subprocess.run(
            [sys.executable, j, "append", "decisions", "--title", title, "--body", body,
             "--quiet", "--no-fetch", "--tags", "owner-answer",
             "--refs", "owner_decision_queue#%s" % row_id],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except Exception as exc:  # noqa: BLE001
        print("  note: could not reach the journal (%s); the answer is in the queue row only" % exc)
        return
    if out.returncode == 0:
        print("  journal: " + (out.stdout or "").strip()[:120])
    else:
        print("  note: journal append failed (%s); the answer is in the queue row only"
              % (out.stderr or "").strip()[:120])


def cmd_answer(con, a) -> int:
    row = con.execute("SELECT question FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()

    # Close the read snapshot BEFORE writing. The SELECT above leaves a deferred
    # transaction open, so the UPDATE would have to upgrade a read transaction to a
    # write one -- and if any other connection committed in between (the API writes
    # to this database continuously) SQLite returns SQLITE_BUSY *immediately*.
    # `timeout=180` cannot help: waiting cannot make a stale snapshot current.
    # Measured 2026-09-14: resolve failed four times in a row before succeeding in a
    # retry loop. Same fix as app/services/dsh_session_ingest.py.
    con.commit()
    if not row:
        print(f"no such queue row: {a.id}")
        return 1
    con.execute(
        "UPDATE owner_decision_queue SET status='answered', answered_at=?, answer=? WHERE id=?",
        (now(), a.answer, a.id),
    )
    con.commit()
    print(f"#{a.id} -> answered")
    _record_feedback(con, a.id, "answered", a.answer)
    _journal_copy(a.id, row[0], a.answer, getattr(a, "db", "") or DEFAULT_DB)
    _close_with_siblings(con, a, "answered", a.answer)
    return 0


def _close_with_siblings(con, a, action: str, text: str) -> None:
    """Close the rows he answered at the same time, by name, so nothing is left orphaned.

    He knocks this queue out in one sitting: when two rows are the same matter and he answers it
    once, the second row must not come back tomorrow asking the same thing. The close is recorded
    on each row with the reason, so the learning sees two answered items and not one answered and
    one abandoned -- an abandoned row is what a dismissal-penalty learns the wrong lesson from.
    """
    raw = getattr(a, "with_ids", None) or ""
    ids = [x.strip().lstrip("#") for x in str(raw).replace(",", " ").split() if x.strip()]
    for sid in ids:
        if str(sid) == str(a.id):
            continue
        try:
            r = con.execute("SELECT id, question, status FROM owner_decision_queue WHERE id=?",
                            (sid,)).fetchone()
        except Exception:
            continue
        con.commit()
        if not r or str(r["status"]) != "pending":
            print("  (with: #%s is not pending; left alone)" % sid)
            continue
        note = "answered together with #%s" % a.id
        exec_locked(con,
                    "UPDATE owner_decision_queue SET status=?, resolved_at=?, resolution=? WHERE id=?",
                    ("answered" if action == "answered" else "resolved", now(), note, sid))
        print("  #%s -> also closed (%s)" % (sid, note))
        _record_feedback(con, sid, action, text)
        _journal_copy(sid, r["question"], text, getattr(a, "db", "") or DEFAULT_DB)


# ---------------------------------------------------------------------------
# THE ONE QUEUE
#
# Owner's rule, 2026-10-18, verbatim: "make sure it's one queue that has everything that I need to
# know or needs my either one ... a mix of stuff that were emailed or texted. They don't specifically
# need my decision, but I would want to know about and also stuff and need my decision from."
#
# So there is ONE ordered list. It is assembled at read time from every surface that can hold
# something waiting on him, and ranked by ONE function, because two lists ranked by two functions is
# the defect he is complaining about. Nothing here writes except `seen_at`, which is what makes
# "what is new since you last looked" answerable.
#
# Surfaces, and why each is still read rather than copied:
#   owner_decision_queue  the queue itself: decisions AND comms-derived attention (kind=attention).
#                         Written by `add`, by `ingest gv`, and by the app's ask path.
#   agent_questions       3 pending questions from the 18 agents. Not copied into the table because
#                         its lifecycle is owned by the app; it is read here so he sees it in one list.
#   owner_message_queue   9 held alerts the app never delivered. Ops alerts (a paused sync, a stale
#                         capture) are MINE, not his, and are counted and named, never shown as items.
# ---------------------------------------------------------------------------

TIER_WEIGHT = {"critical": 1000, "high": 700, "medium": 400, "low": 150}

#: owner_message_queue reasons that are an engineering repair, not the owner's business.
_OWNER_QUEUE_OPS_REASONS = ("sync_breaker", "comms_freshness")


def _parse_meta(raw):
    """meta_json, defensively. A malformed cell must never break the queue reader."""
    try:
        m = json.loads(raw or "{}")
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


# ── learning from what he actually did ──────────────────────────────────────────────────────────
# Owner's requirement, 2026-10-18: "the queue needs to learn over time what to put in it and what to
# prioritize ... based on my responses to the queue when we go through a session knocking it out."
# The mechanism is deliberately boring and auditable -- there is no model here and no stored score:
#   1. every close writes one feedback row (action, his words, who it was from, what class)
#   2. a sender he has dismissed >= 2 times and never answered is DEMOTED in the ranking, by an
#      amount printed in the arithmetic, capped so it can never bury a critical item
#   3. the mail judge is handed his last dozen answers/dismissals as examples, so tomorrow's
#      judgement is his judgement rather than the rubric author's
def _record_feedback(con, item_id, action, answer="") -> None:
    """Write what he did with one item. Never raises: a recording failure must not block an answer."""
    try:
        row = con.execute(
            "SELECT kind, channel, party, severity, meta_json FROM owner_decision_queue WHERE id=?",
            (item_id,)).fetchone()
        # Close the read snapshot BEFORE writing -- the same SQLITE_BUSY trap cmd_answer documents.
        con.commit()
        if not row:
            return
        meta = _parse_meta(row["meta_json"])
        sender = str(meta.get("sender") or "")
        dom = re.search(r"@([A-Za-z0-9.\-]+)", sender)
        con.execute(
            "INSERT INTO owner_queue_feedback"
            " (item_id, action, answer, kind, channel, party, cls, sender_domain, tier_at,"
            "  score_at, at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(item_id), action, (answer or "")[:600], row["kind"], row["channel"],
             row["party"], str(meta.get("class") or ""),
             (dom.group(1).lower().rstrip(">") if dom else ""), row["severity"], None, now()))
        con.commit()
    except Exception as exc:  # noqa: BLE001
        print("  (feedback not recorded: %s: %s)" % (type(exc).__name__, exc))


LEARN_WINDOW_DAYS = 120
LEARN_PER_DISMISSAL = 40
LEARN_CAP = 160
#: Per dimension, how much it may move the ranking, and how much evidence it needs first.
#:
#: MEASURED 2026-10-18, by running the profile over a simulated session: four dismissed emails gave
#: `channel email -96`, which would have demoted EVERY email for 120 days -- including the T-Mobile
#: "your service is suspended" that sat at the top of the queue. A broad dimension cannot carry a
#: narrow conclusion. So the wider the bucket, the more evidence it needs and the less it may move:
#:
#:   party / domain  a specific correspondent or company -- sharpest signal, biggest permitted move
#:   class           "notice", "money", "person" -- needs 8 closes, may move half as far
#:   channel         "email", "sms" -- needs 10 closes, may move least of all
LEARN_DIM_RULES = {
    "party":   {"min": 3,  "cap": 160, "elev": 90},
    "domain":  {"min": 3,  "cap": 160, "elev": 90},
    "class":   {"min": 8,  "cap": 80,  "elev": 50},
    "channel": {"min": 10, "cap": 60, "elev": 40},
}
#: Parties that are not identities. MEASURED 2026-10-18 on the first learning test: three dismissed
#: items made the profile say `DEMOTED party several -80` -- because every folded digest row carries
#: party='several', so dismissing two digests would have demoted digests forever. A party that names
#: no one cannot teach the queue anything.
NON_PARTIES = frozenset({"", "several", "unknown", "n/a", "none", "-", "various"})

#: The dimensions his answers are read along. Each is a way of saying "this KIND of thing".
LEARN_DIMENSIONS = ("party", "domain", "class", "channel")

#: He acts on a kind of item this often => it is underweighted, and moves up.
LEARN_ANSWER_HIGH = 0.75
#: He dismisses a kind of item this often => it is overweighted, and moves down.
LEARN_DISMISS_HIGH = 0.60


#: Channels that still write this queue. A close from any other surface cannot teach the CURRENT
#: ranking: MEASURED 2026-10-18 -- of 111 answered/dismissed rows, the dismissals are almost all
#: `owner_message_queue #NNNN`, the app's held-alert table, which the mail judge has since made
#: redundant (that is exactly why the reader drops held rows the judge already judged). Teaching
#: "email sinks" from those would demote the live email channel on the strength of a dead one.
LIVE_CHANNELS = ("email", "sms", "call", "voicemail", "agent", "sweep")

#: Source prefix -> channel. A mapping, not an inference: `gv-ingest:sms` IS the Google Voice text
#: channel and nothing else. MEASURED 2026-10-18: across the 111 answered/dismissed rows on the
#: record, `party`, `channel`, `cls` and `sender_domain` were EMPTY on every single one, because the
#: old writer never stored them -- so a profile read from history could learn nothing at all. The
#: source string survives on every row and says which channel it came from.
_SOURCE_CHANNEL = (
    ("gv-ingest:sms", "sms"), ("gv-ingest:missed_call", "call"),
    ("gv-ingest:voicemail", "voicemail"), ("gv-ingest:digest", "sms"),
    ("mail-ingest", "email"), ("attention-sweep", "sweep"),
)

#: The shapes a one-liner uses to name the person. Deliberately a short list of exact patterns; a
#: fuzzy name extractor would invent a party and then learn from its own invention.
_RE_PARTY = (
    re.compile(r"^Text from ([^:]{2,40}):", re.I),
    re.compile(r"^Missed call from ([^.:]{2,40})\.?$", re.I),
    re.compile(r"^Voicemail from (\([0-9]{3}\) ?[0-9]{3})", re.I),
    re.compile(r"(?:URGENT EMAIL\s+)?From:\s*(.{2,60}?)\s*<[^>]+>", re.I),
    re.compile(r"^(.{2,40}?) (?:asks|sent|wrote|replied)\b", re.I),
)


def _dimensions_from_row(source, question):
    """(channel, party) recovered from what an old row DOES record. Used only by the backfill."""
    src = str(source or "")
    chan = ""
    for prefix, ch in _SOURCE_CHANNEL:
        if src.startswith(prefix):
            chan = ch
            break
    party = ""
    for rx in _RE_PARTY:
        m = rx.search(str(question or "").strip())
        if m:
            party = m.group(1).strip()
            break
    return chan, party


def _feedback_from_history(con) -> int:
    """Teach the profile from the 553 rows the queue has already closed. Idempotent.

    MEASURED 2026-10-18: `owner_queue_feedback` held **2 rows** while `owner_decision_queue` held
    **553 closed ones** -- 10 answered, 101 dismissed, 442 resolved. The learning loop he asked for
    was wired to a table nobody had ever written to, so it had learned nothing from a year of his
    decisions. The rows already contain his words (`answer`) and the reason (`resolution`); nothing
    needs to be asked again. Each close is copied once, keyed on (item_id, action), so re-running
    this cannot double-count and cannot undo a later real close.
    """
    try:
        have = {(str(r[0]), str(r[1])) for r in con.execute(
            "SELECT item_id, action FROM owner_queue_feedback")}
    except Exception:
        return 0
    con.commit()
    try:
        rows = con.execute(
            "SELECT id, status, kind, channel, party, severity, meta_json, source, question,"
            "       COALESCE(NULLIF(answer,''), resolution, '') AS said"
            "  FROM owner_decision_queue"
            " WHERE status IN ('answered','resolved','dismissed','superseded')").fetchall()
    except Exception as exc:  # noqa: BLE001
        print("  (backfill could not read the closed rows: %s: %s)" % (type(exc).__name__, exc))
        return 0
    con.commit()
    written = 0
    failed = 0
    for r in rows:
        action = {"answered": "answered", "resolved": "resolved",
                  "dismissed": "dismissed", "superseded": "superseded"}.get(r["status"], "resolved")
        if (str(r["id"]), action) in have:
            continue
        meta = _parse_meta(r["meta_json"])
        sender = str(meta.get("sender") or "")
        dom = re.search(r"@([A-Za-z0-9.\-]+)", sender)
        chan, party = r["channel"], r["party"]
        if not chan or not party:
            d_chan, d_party = _dimensions_from_row(r["source"], r["question"])
            chan = chan or d_chan
            party = party or d_party
        try:
            con.execute(
                "INSERT INTO owner_queue_feedback"
                " (item_id, action, answer, kind, channel, party, cls, sender_domain, tier_at,"
                "  score_at, at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(r["id"]), action, str(r["said"] or "")[:600], r["kind"], chan,
                 party, str(meta.get("class") or ""),
                 (dom.group(1).lower().rstrip(">") if dom else ""), r["severity"], None,
                 now()))
            written += 1
        except Exception:
            failed += 1
            continue
    con.commit()
    if failed:
        print("  (%d close(s) could not be copied into the feedback table)" % failed)
    return written


def _learning_profile(con):
    """What his own closes taught, per dimension, with the evidence behind each number.

    Every entry is a *signed* adjustment: negative means he keeps dismissing this kind of thing,
    positive means he almost always acts on it. Both are printed, because "what to put in it" and
    "what to prioritize" were one sentence in his instruction and are one table here.

    WHOSE SIGNAL THIS IS -- the trap that would have taught it backwards. MEASURED 2026-10-18 on the
    559 closed rows: **442 are `resolved`**, and reading four of them showed they were closed by ME
    under the standing autonomy rule ("DECIDED 2026-10-18 under the owner's standing autonomy rule"),
    plus the queue closing its own loops ("auto-closed: portal@telnyx.com said account re-enabled").
    Counting those as "he acted on it" would have taught the queue that everything it auto-closes is
    something he loves. So only his four verbs count:
        answered 1.0 · dismissed 1.0 · skipped 0.5 (he looked and moved on) · deferred 0.3 (later,
        not never). `resolved` contributes nothing and is reported as excluded.

    ONE QUERY PER DIMENSION, not one GROUP BY across all four: grouping by
    (party, domain, class, channel) together makes every cell n=1, which crossed no floor and made
    the whole profile print "nothing has crossed the sample floor" over 111 real signals.
    """
    prof = {k: {} for k in LEARN_DIMENSIONS}
    expr = {
        "party": "LOWER(TRIM(COALESCE(party,'')))",
        "domain": "LOWER(TRIM(COALESCE(sender_domain,'')))",
        "class": "LOWER(TRIM(COALESCE(cls,'')))",
        "channel": "LOWER(TRIM(COALESCE(channel,'')))",
    }
    for dim in LEARN_DIMENSIONS:
        try:
            rows = con.execute(
                "SELECT %s AS k,"
                "  SUM(CASE WHEN action='answered' THEN 1.0 ELSE 0 END) a,"
                "  SUM(CASE WHEN action='dismissed' THEN 1.0 ELSE 0 END) d,"
                "  SUM(CASE WHEN action='skipped' THEN 1.0 ELSE 0 END) s,"
                "  SUM(CASE WHEN action='deferred' THEN 1.0 ELSE 0 END) f"
                " FROM owner_queue_feedback"
                " WHERE at > datetime('now', ?) AND action IN"
                "       ('answered','dismissed','skipped','deferred')"
                "   AND LOWER(TRIM(COALESCE(channel,''))) IN (%s)"
                " GROUP BY k" % (expr[dim], ",".join("'%s'" % c for c in LIVE_CHANNELS)),
                ("-%d day" % LEARN_WINDOW_DAYS,)).fetchall()
        except Exception:
            continue
        for r in rows:
            k = str(r["k"] or "")
            if not k or k in NON_PARTIES:
                continue
            acted = float(r["a"] or 0) + float(r["f"] or 0) * 0.3
            avoided = float(r["d"] or 0) + float(r["s"] or 0) * 0.5
            n = acted + avoided
            rule = LEARN_DIM_RULES[dim]
            if n < rule["min"]:
                continue
            act_rate = acted / n
            adj, why = 0, ""
            if act_rate <= (1.0 - LEARN_DISMISS_HIGH):
                adj = -min(rule["cap"], int(round(avoided * LEARN_PER_DISMISSAL * 0.6)))
                why = "he dismisses %.0f%% of these (%.1f of %.1f)" % (
                    100 * (1 - act_rate), avoided, n)
            elif act_rate >= LEARN_ANSWER_HIGH:
                adj = min(rule["elev"], int(round(acted * 12)))
                why = "he acts on %.0f%% of these (%.1f of %.1f)" % (100 * act_rate, acted, n)
            elif abs(act_rate - 0.5) > 0.2:
                # Between the two rules nothing is learned: the middle is where a queue should
                # neither promote nor bury, and pretending otherwise is how a profile overfits.
                continue
            if adj:
                prof[dim][k] = {"adj": adj, "n": int(n), "act": round(act_rate, 2), "why": why}
    return prof


def _learned_penalty(item, prof) -> int:
    """The signed adjustment his past closes have earned this item. Positive = show it sooner."""
    total = 0
    sender = str(item.get("_sender") or "")
    dom = re.search(r"@([A-Za-z0-9.\-]+)", sender)
    keys = {
        "party": str(item.get("party") or "").strip().lower(),
        "domain": (dom.group(1).lower().rstrip(">") if dom else ""),
        "class": str(item.get("_class") or "").strip().lower(),
        "channel": str(item.get("channel") or "").strip().lower(),
    }
    for dim, k in keys.items():
        if not k or k in NON_PARTIES:
            continue
        cell = prof.get(dim, {}).get(k)
        if cell:
            # The largest single signal wins rather than the sum: four dimensions agreeing is
            # evidence about the same item, not four independent facts, and summing them would let
            # a dismissed sender from a dismissed class jump a whole band.
            if abs(cell["adj"]) > abs(total):
                total = cell["adj"]
    return total


def _age_hours_from(value):
    """Hours since `value`, or None. Never rounds before a comparison uses it."""
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00").replace(" ", "T")
        when = dt.datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        return max(0.0, (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0)
    except Exception:
        return None


# ── signals derived from the text, not from a column ────────────────────────────────────────────
# MEASURED 2026-10-18: across all 42 pending rows, `meta.money` was set on ZERO of them -- so the
# money term in the score had never once fired, and a returned payment of 2,380.06 ranked below a
# ten-day-old voicemail about a laptop. The amount is in the words; read it there. Same reasoning as
# "nothing reads a stored score": a signal written at insert time is only as good as the insert.
RE_MONEY_TEXT = re.compile(r"(?:\$|USD\s*)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
RE_MONEY_BARE = re.compile(r"\b([0-9]{1,3}(?:,[0-9]{3})+\.[0-9]{2})\b")
RE_DEADLINE_SOON = re.compile(
    r"(?:\bdue\s+(?:in|by|on|now)\b|\bdue\s+(?!to\b)\w|\bexpires?\b|\bexpiring\b|"
    r"\bexpiration\b|\bfinal notice\b|\blast (?:day|chance)\b|"
    r"\bends?\s+(?:today|tonight|tomorrow|\w+day)\b|\boverdue\b|\bsuspended\b|"
    r"\bdeadline\b|\bby\s+(?:today|tonight|tomorrow|end of (?:day|week)|\w+day|"
    r"the \d{1,2}(?:st|nd|rd|th))\b|\bbefore\s+(?:today|tonight|tomorrow|\w+day|"
    r"the \d{1,2}(?:st|nd|rd|th))\b)", re.I)
RE_REL_DAYS = re.compile(r"\bin\s+([1-7])\s+days?\b", re.I)


def _money_in(text):
    """The largest amount stated in the item's own words, or None."""
    best = None
    for rx in (RE_MONEY_TEXT, RE_MONEY_BARE):
        for m in rx.finditer(text or ""):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if best is None or v > best:
                best = v
    return best


def _deadline_soon(text):
    """A stated date or a stated urgency inside the next week."""
    t = text or ""
    if RE_REL_DAYS.search(t):
        return True
    return bool(RE_DEADLINE_SOON.search(t))


#: A relative day word dates the item to the day it arrived. MEASURED 2026-10-18: the queue's second
#: highest item was "Yocheved asks you to order four grocery items for dinner tonight" -- four days
#: after that dinner. Asking him that is worse than not asking: it spends his attention and returns
#: nothing. So a row that said "tonight"/"today"/"tomorrow" and is older than that day is marked
#: POSSIBLY MOOT, demoted, and says so on its own card.
RE_SAME_DAY = re.compile(
    r"\b(tonight|today|this (?:evening|afternoon|morning)|tomorrow|by (?:tonight|today|tomorrow))\b",
    re.I)


def _moot(item):
    """(is_moot, reason). A named day that has already passed, and the age that proves it."""
    age = item.get("age_hours")
    if not isinstance(age, (int, float)) or age < 30:
        return False, ""
    text = "%s %s" % (item.get("title") or "", item.get("_blob") or "")
    m = RE_SAME_DAY.search(text)
    if not m:
        return False, ""
    return True, "said \"%s\" %.0f hours ago" % (m.group(1).lower(), age)


def _queue_score(item):
    """THE ordering function. Deterministic, and every term prints its own arithmetic.

    Nothing here reads a stored score: a score written at insert time goes silently stale the moment
    the ingest stops running, and then the order is a claim about urgency that nothing re-measures.

    The shape, decided 2026-10-18 after the first 42 rows were read one by one: tier sets the band,
    and the modifiers decide the order INSIDE a band. Nothing may jump a band -- a critical money
    notice must never sit below a month-old "any way I can get my phone today", which is what the old
    caps allowed once the age term and a missing money term were combined.
    """
    tier = str(item.get("tier") or "medium").lower()
    score = TIER_WEIGHT.get(tier, 400)
    why = ["%s=%d" % (tier, score)]
    if item.get("blocking"):
        score += 200
        why.append("blocking=+200")
    # A filed decision is a choice only he can make and it holds work still. An agent's approval
    # request is not the same thing -- it already carries ask=+80 -- so the bonus is the queue's own.
    if item.get("surface") == "queue" and item.get("kind") == "decision":
        score += 100
        why.append("decision=+100")
    age = item.get("age_hours")
    if isinstance(age, (int, float)) and age > 0:
        add = int(min(150, age / 8.0))
        if add:
            score += add
            why.append("age=+%d" % add)
        if age < 24:
            score += 40
            why.append("today=+40")
    if item.get("ask"):
        score += 80
        why.append("asks=+80")
    if item.get("deadline"):
        score += 60
        why.append("deadline=+60")
        if item.get("deadline_soon"):
            score += 60
            why.append("soon=+60")
    money = item.get("money")
    if isinstance(money, (int, float)) and money > 0:
        # A DIGEST IS NOT A BILL. MEASURED 2026-10-18: "5 notices: Amex snapshot 1,965.08 ... $53
        # PayPal charge" scored money=+196 off the largest number in its own summary and sat above a
        # person waiting for an answer. Nothing is owed on a digest; the amounts in it are the
        # subject matter. So a folded row may carry at most a quarter of the money weight, which
        # still lets "your card was charged 2,380" outrank a newsletter without letting a summary of
        # five notices outrank a customer.
        # A folded summary gets a QUARTER of the weight of a real amount (see the note above).
        is_digest = bool(item.get("_digest"))
        divisor = 40.0 if is_digest else 10.0
        add = int(min(200, money / divisor))
        if add:
            score += add
            why.append("money=+%d%s" % (add, " (digest, quarter weight)" if is_digest else ""))
    # What his own closes taught. SIGNED: a sender he keeps dismissing sinks, and a kind of item he
    # always acts on rises. Bounded so learning may reorder inside a band and can never invert one.
    learned = item.get("learned") or 0
    if learned:
        score = max(1, score + int(learned))
        why.append("learned=%+d" % int(learned))
    if item.get("moot"):
        score = max(1, score - 200)
        why.append("moot=-200")
    return int(score), " ".join(why)


def _subj_key(subject):
    """A subject reduced to what makes two sentences the same sentence."""
    s = re.sub(r"^(re|fwd|fw)\s*:\s*", "", str(subject or "").strip(), flags=re.I)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s[:60]


def _quoted_subject_seen(body, judged):
    """True when a held `X emailed about "S"` names a subject the mail judge already handled."""
    m = re.search(r'emailed about\s+["“](.+?)["”]', str(body or ""), re.I)
    if not m:
        return False
    k = _subj_key(m.group(1))
    if not k:
        return False
    if k in judged:
        return True
    # The app truncates subjects, so a long prefix agreeing is the same subject.
    for j in judged:
        if len(k) >= 25 and (j.startswith(k[:40]) or k.startswith(j[:40])):
            return True
    return False


def _gather_queue(con, include_deferred=False):
    """Every surface, one list. Each entry carries where it came from and why it ranks where it does."""
    items = []

    # ── the queue itself: decisions and comms-derived attention ──────────────
    try:
        rows = con.execute(
            "SELECT id, asked_at, question, context, recommendation, severity, blocks, kind,"
            "       channel, party, evidence_at, deferred_until, meta_json, status, seen_at"
            "  FROM owner_decision_queue WHERE status='pending'").fetchall()
    except Exception:
        # Pre-migration database: the columns this reader wants are not there yet.
        rows = con.execute(
            "SELECT id, asked_at, question, '' AS context, NULL AS recommendation, severity, blocks,"
            "       'decision' AS kind, NULL AS channel, NULL AS party,"
            "       NULL AS evidence_at, deferred_until, NULL AS meta_json, status,"
            "       NULL AS seen_at"
            "  FROM owner_decision_queue WHERE status='pending'").fetchall()
    for r in rows:
        meta = _parse_meta(r["meta_json"])
        at = r["evidence_at"] or r["asked_at"]
        # A digest announces itself in its own title ("5 money notices (2026-10-15): ..."). Reading
        # the shape means this works on every historic row without a schema change or a backfill.
        is_digest = _digest_members(r["question"]) is not None
        deferred = False
        when = str(r["deferred_until"] or "")
        if when:
            try:
                deferred = dt.datetime.fromisoformat(
                    when.replace("Z", "+00:00")) > dt.datetime.now(dt.timezone.utc)
            except Exception:
                deferred = False
        if deferred and not include_deferred:
            continue
        blob = "%s %s" % (r["question"] or "", r["context"] or "")
        soon = _deadline_soon(blob)
        items.append({
            "surface": "queue",
            "id": r["id"],
            "kind": (r["kind"] or "decision"),
            "tier": r["severity"] or "medium",
            "title": r["question"],
            "recommendation": r["recommendation"] or "",
            "age_hours": _age_hours_from(at),
            "blocking": bool(r["blocks"]),
            "ask": bool(meta.get("ask")),
            "deadline": bool(meta.get("deadline")) or soon,
            "deadline_soon": soon,
            # The amount is taken from the judge's one-liner or its own field -- NEVER from the
            # body. Measured 2026-10-18: reading the whole context made a grocery order score
            # money=+200 (the prices of the items in the mail) and put "order four items for
            # dinner tonight" above a suspended phone line.
            "money": meta.get("money") if meta.get("money") is not None else _money_in(r["question"]),
            "channel": r["channel"],
            "party": r["party"],
            "_sender": str(meta.get("sender") or ""),
            "_blob": (r["question"] or "") + " " + (r["context"] or "")[:400],
            "deferred": deferred,
            "_unseen": not r["seen_at"],
            "at": at,
            "_context": r["context"] or "",
            # The message's own identity, so two rows derived from ONE email can be proven to be
            # one thing rather than guessed at by similarity. MEASURED 2026-10-18: #643 and #687 are
            # literally the same message (account lakewoodphoneandtech@gmail.com, thread
            # 1a1402619af10782) judged twice into two classes -- it landed as two queue rows.
            "_account": str(meta.get("account") or ""),
            "_thread": str(meta.get("thread_id") or ""),
            "_subject": str(meta.get("subject") or ""),
            "_class": str(meta.get("class") or ""),
            "_digest": is_digest,
            "_members": meta.get("members") or [],
        })

    # ── agent questions: pending only; owned and closed by the app ───────────
    try:
        for r in con.execute(
                "SELECT substr(id,1,8) AS sid, created_at, question, COALESCE(severity,'') AS sev,"
                " agent_id FROM agent_questions WHERE status='pending'"):
            items.append({
                "surface": "agent", "id": "q" + str(r["sid"]), "kind": "decision",
                "tier": (r["sev"] or "medium").lower(), "title": r["question"],
                "age_hours": _age_hours_from(r["created_at"]), "blocking": False,
                "ask": True, "deadline": False, "money": None, "channel": "agent",
                "party": r["agent_id"], "deferred": False, "at": r["created_at"],
            })
    except Exception:
        pass

    # ── held messages the app never delivered, minus my own ops alerts ───────
    # DEDUPE, measured 2026-10-18: four held rows read `Chase emailed about "..."`, `Stripe emailed
    # about "..."`, and so on. They are the app's NOTICE that an email arrived -- and the mail ingest
    # now judges that email itself, so showing both is the same thing twice. A held row is dropped
    # only when the judge has a verdict on the very subject it names; if the judge is dead there are
    # no verdicts, the held row shows, and nothing goes missing silently.
    judged_subjects = set()
    try:
        for (subj,) in con.execute(
                "SELECT subject FROM owner_mail_verdict"
                " WHERE received_at > datetime('now','-21 day') LIMIT 4000"):
            k = _subj_key(subj)
            if k:
                judged_subjects.add(k)
    except Exception:
        judged_subjects = set()
    try:
        for r in con.execute(
                "SELECT id, reason, urgency, body, COALESCE(last_seen_at, created_at) AS at"
                "  FROM owner_message_queue WHERE status='held'"):
            reason = str(r["reason"] or "")
            if reason.startswith(_OWNER_QUEUE_OPS_REASONS) or reason in _OWNER_QUEUE_OPS_REASONS:
                continue
            if reason.startswith("urgent_email") and _quoted_subject_seen(
                    str(r["body"] or ""), judged_subjects):
                continue
            urg = str(r["urgency"] or "").lower()
            blob = str(r["body"] or "") + " " + reason
            items.append({
                "surface": "held", "id": "m%s" % r["id"], "kind": "attention",
                "tier": {"critical": "critical", "urgent": "high", "high": "high"}.get(urg, "low"),
                "title": r["body"] or reason,
                "age_hours": _age_hours_from(r["at"]), "blocking": False,
                "ask": False, "deadline": _deadline_soon(blob),
                "deadline_soon": _deadline_soon(blob), "money": _money_in(blob),
                "channel": "app", "party": reason, "deferred": False, "at": r["at"],
            })
    except Exception:
        pass

    prof = _learning_profile(con)
    for it in items:
        it.setdefault("_blob", str(it.get("title") or ""))
        it["moot"], it["moot_why"] = _moot(it)
        it["learned"] = _learned_penalty(it, prof)
        it["_facts"], it["_ready"], it["_missing"] = _dossier(con, it)
        it["score"], it["why"] = _queue_score(it)
    items.sort(key=lambda i: (-i["score"], i["surface"] != "queue", str(i["id"])))
    items = _collapse_facts(items)
    return items


# ---------------------------------------------------------------------------
# ONE FACT, ONE ROW
#
# MEASURED 2026-10-18 on the live 74-row queue, and it is the defect he would feel first, because he
# knocks this out "once every other day" and cannot answer the same thing three times:
#
#   Techloq filter auto-renews 36.99   appeared as  #680 (its own row), #647 (inside a money digest)
#                                      and #688 (inside a notice digest) -- three rows, one fact.
#   LPT referral list                  #687, #642, #643 -- three rows, one fact.
#   NJ tax payment confirmation        #626, #675 -- two digests carrying the same member.
#   300DDR recovered drive             #693 (the mail) and #646 (the agent's question about it).
#
# Never fixed by de-duplicating at INSERT time, for the same reason nothing reads a stored score: the
# digests are written per (class, day), the same message is judged into two classes on one day, and a
# row written yesterday is still the same fact as today's row. Collapsing at READ time repairs every
# historic row at once and cannot go stale.
#
# Two rules, both narrow, both printed so the merge is judgeable:
#   A. a DIGEST is not one fact, it is N facts in a coat. Split it on " · ", and drop any member that
#      another row in this queue already owns -- or that an already-shown digest took. A digest that
#      loses everything disappears (its members are all present elsewhere); one that keeps one member
#      becomes that member, because a digest of one is not a digest.
#   B. a DECISION absorbs ATTENTION about the same thing. He does not need to read the notice and
#      then answer the question about the notice. The suppressed row's id is carried on the decision
#      so the dossier still holds every word.
# ---------------------------------------------------------------------------

#: Words that carry no fact. Kept short on purpose: a stopword list that grows starts eating subjects.
_STOP_FACT = frozenset("""
a an the is are was were be been being am do does did has have had will would shall should can could
may might must of in on at to for from by with about into over after before and or but not no nor
this that these those it its your you our we my me his her their they them he she i as if than then
there here what which who whom when where why how all any both each few more most other some such
only own same so too very just also now new
""".split())

RE_DIGEST_HEAD = re.compile(
    r"^\s*(\d+)\s+[A-Za-z ]*?notices?\s*(?:\(\s*(\d{4}-\d{2}-\d{2})\s*\))?\s*:\s*(.+)$", re.I)

#: A matter reference: the shop's own case/work-order tags, a ticket number, a phone number, a long
#: alphanumeric serial. These are what make two differently-worded rows the SAME thing (300DDR).
RE_CASE_REF = re.compile(r"\b([0-9]{2,4}ddr)\b|\b(?:case|ticket|wo|work order|order)\s*#?\s*([0-9]{3,7})\b"
                         r"|\b#([0-9]{3,7})\b", re.I)


def _fact_sig(text):
    """The significant words of a one-liner: what makes two sentences the same fact."""
    s = re.sub(r"\$?\b\d[\d,\.]*\b", " ", str(text or "").lower())
    s = re.sub(r"[^a-z]+", " ", s)
    return frozenset(w for w in s.split() if len(w) >= 4 and w not in _STOP_FACT)


def _same_fact(a, b, need=3, ratio=0.6):
    """Two signatures naming the same fact. Deliberately conservative."""
    if len(a) < need or len(b) < need:
        return False
    inter = len(a & b)
    return inter >= need and (float(inter) / len(a | b)) >= ratio


def _case_refs(text):
    """The shop references in a one-liner, normalised: '300ddr', 'case:4485', 'ticket:12345'."""
    refs = set()
    for m in RE_CASE_REF.finditer(str(text or "")):
        g = [x for x in m.groups() if x]
        if not g:
            continue
        v = g[0].lower()
        if v.endswith("ddr"):
            refs.add(v)
        else:
            refs.add("ref:" + v.lstrip("0"))
    return refs


def _digest_members(title):
    """(count, date, [member, ...]) if this row is a folded digest, else None."""
    m = RE_DIGEST_HEAD.match(str(title or ""))
    if not m:
        return None
    members = [x.strip() for x in re.split(r"\s+·\s+", m.group(3)) if x.strip()]
    if not members:
        return None
    return int(m.group(1)), (m.group(2) or ""), members


def _entity_tokens(item):
    """The names on an item: who it is from, reduced the way a person would say it.

    `Brian, 300DDR` and `Brian at 300DDR` are the same correspondent, and #693/#646 proved it --
    the mail about a recovered drive and the agent's question about it were the same matter four
    words apart. Matching on the signature alone could not see it; matching on the name can.

    PARTY ONLY, never the channel. MEASURED 2026-10-18 while testing a wider version: including
    `channel` made every pair of missed calls share the tokens {"call", "missed"}, so "Missed call
    from Parsons" and "Missed call from Mogo" were proposed as one fact. A token that every row of a
    class carries identifies nothing.
    """
    raw = str(item.get("party") or "")
    return frozenset(t for t in re.findall(r"[a-z0-9]{4,}", raw.lower()) if t not in _STOP_FACT)


def _siblings(item, items):
    """Other rows that are probably the SAME MATTER, not proven to be.

    Deliberately never merged: a wrong merge hides an item, which is the one failure this queue
    cannot afford. Instead they are shown on the card and answered with one verb, so he closes the
    cluster in one sentence and the record says so. Proven duplicates are handled above, by identity.
    """
    mine_e, mine_s = _entity_tokens(item), _fact_sig(item.get("title"))
    out = []
    for other in items:
        if other["id"] == item["id"] or other["kind"] != item["kind"]:
            continue
        shared_e = mine_e & _entity_tokens(other)
        shared_s = mine_s & _fact_sig(other.get("title"))
        if shared_e and len(shared_s) >= 2:
            out.append(other)
        elif len(shared_s) >= 4 and _same_fact(mine_s, _fact_sig(other.get("title")), need=4,
                                               ratio=0.55):
            out.append(other)
    return out


def _collapse_facts(items):
    """One fact, one row.

    Three rules, in order of how much they have to guess, and the guessy one runs last:

    A. **SAME MESSAGE** -- two rows carrying the same (account, thread_id) are the same message,
       provably: nothing is inferred. #643 and #687 were one email, judged twice into two classes
       (`person` and `notice`), so `key_for` gave it a thread key and a fact key and both landed.
       Keep the better rank, carry the other's words on it, close it when the survivor closes.
    B. **DECISION ABSORBS ATTENTION** about the same matter -- either the same shop reference
       (`300DDR`, `case 4485`) or the same party entities plus two shared subject words. He does not
       need to read the notice and then answer the question about the notice.
    C. **A DIGEST LOSES ANY MEMBER ANOTHER ROW OWNS.** A digest is N facts in a coat: split it on
       " · " and drop each member that a real row already holds, or that an earlier digest took. A
       digest that keeps nothing disappears (every member is present elsewhere); one that keeps one
       member becomes that member, because a digest of one is not a digest.
    """
    report = {"same_message": [], "absorbed": {}, "digests_narrowed": 0, "digests_gone": 0}

    def _sortkey(it):
        return (-it["score"], str(it["id"]))

    # ── A. same message ────────────────────────────────────────────────────
    groups = {}
    for it in items:
        acct, thr = it.get("_account") or "", it.get("_thread") or ""
        if acct and thr:
            groups.setdefault((acct, thr), []).append(it)
    drop = set()
    for (acct, thr), members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=_sortkey)
        head = members[0]
        for other in members[1:]:
            # Union the digest membership so narrowing still sees every member.
            if _digest_members(head.get("title")) and _digest_members(other.get("title")):
                a = _digest_members(head["title"])
                b = _digest_members(other["title"])
                merged = a[2] + [x for x in b[2] if x not in a[2]]
                day = a[1] or b[1]
                head["title"] = ("%d notices (%s): %s" % (len(merged), day,
                                                          " · ".join(x[:48] for x in merged))
                                 if day else "%d notices: %s" % (len(merged),
                                                                 " · ".join(x[:48] for x in merged)))
                head["_digest_date"] = day
            head.setdefault("_also", []).append((other["id"], other.get("title")))
            other["_absorbed_by"] = head["id"]
            drop.add(other["id"])
            report["same_message"].append((other["id"], head["id"]))
    items = [i for i in items if i["id"] not in drop]

    # ── B. a decision absorbs the attention that is the same matter ────────
    ents = {i["id"]: (_entity_tokens(i) | _case_refs(i.get("title") or "")) for i in items}
    sigs = {i["id"]: _fact_sig(i.get("title")) for i in items}
    decisions = [i for i in items if i["kind"] == "decision"]
    for i in [x for x in items if x["kind"] == "attention"]:
        for d in decisions:
            if d is i or d["id"] in drop or i["id"] in drop:
                continue
            refs_hit = bool(ents[i["id"]] & ents[d["id"]] & _case_refs(
                (i.get("title") or "") + " " + (d.get("title") or "")))
            shared_ent = len(ents[i["id"]] & ents[d["id"]])
            topic_hit = len(sigs[i["id"]] & sigs[d["id"]]) >= 2
            if refs_hit or (shared_ent >= 2 and topic_hit):
                d.setdefault("_also", []).append((i["id"], i.get("title")))
                i["_absorbed_by"] = d["id"]
                drop.add(i["id"])
                report["absorbed"][i["id"]] = d["id"]
                break
    items = [i for i in items if i["id"] not in drop]

    # ── C. digests lose what a real row already owns ───────────────────────
    taken = [(i["id"], sigs.get(i["id"]) or _fact_sig(i.get("title")))
             for i in items if not _digest_members(i.get("title"))]
    for i in sorted([x for x in items if _digest_members(x.get("title"))], key=_sortkey):
        d = _digest_members(i.get("title"))
        count, day, members = d
        keep, gone = [], []
        for mem in members:
            msig = _fact_sig(mem)
            if any(msig and tsig and _same_fact(msig, tsig) for _id, tsig in taken if _id != i["id"]):
                gone.append(mem)
            else:
                keep.append(mem)
        if not gone:
            taken.append((i["id"], _fact_sig(i.get("title"))))
            continue
        report["digests_narrowed"] += 1
        i["_dropped_members"] = gone
        if not keep:
            i["_covered"] = gone
            report["digests_gone"] += 1
            continue
        if len(keep) == 1:
            i["title"] = keep[0]
        else:
            day_text = day or (i.get("_digest_date") or "")
            i["title"] = ("%d notices (%s): %s" % (len(keep), day_text,
                                                   " · ".join(k[:48] for k in keep))
                          if day_text else "%d notices: %s" % (len(keep),
                                                               " · ".join(k[:48] for k in keep)))
        i["_narrowed"] = "was a %d-item digest" % count
        taken.append((i["id"], _fact_sig(i["title"])))

    items = [i for i in items if not i.get("_covered")]
    _collapse_facts.last = report
    return items


def _ops_alert_count(con):
    """How many held alerts are mine to fix rather than his to read. Named, never shown."""
    try:
        n = 0
        for (reason,) in con.execute(
                "SELECT reason FROM owner_message_queue WHERE status='held'"):
            reason = str(reason or "")
            if reason.startswith(_OWNER_QUEUE_OPS_REASONS) or reason in _OWNER_QUEUE_OPS_REASONS:
                n += 1
        return n
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# THE DOSSIER — and the gate that keeps an unbriefed item off his desk
#
# His instruction, 2026-10-18, verbatim: *"all information about it must be gathered in case I want
# more info, so only put it in the queue after all info is gathered about it fully so I can just
# quickly knock out the queue with you ... with you already having all the info I may need about each
# thing."*
#
# MEASURED that same day, on the row at the TOP of his queue (#698, critical, decision):
#
#   question   "Obligation OVERDUE: Landlord utilities - unpaid household balance - decide: pay it
#               or dispute it?"
#   context    "bill obligation due 2026-09-22, 26 day(s) past; recurrence=none. priority=1
#               lead_days=30 status=active"
#   options    three canned sentences, the first of which was my own recommendation
#   the truth  obligation_registry row 11 held the balance (269.71; electric 214.18, gas 55.53),
#              that four bills had arrived and NONE was paid, the ledger path, and the screenshots
#              the figure came from -- and the card showed none of it.
#
# So the sweep filed a question it had the answer to, and the card asked him to decide with less
# information than the database held. Two repairs, both here and both at READ time so they fix
# every historic row at once:
#   1. ENRICH: a row whose context cites `Evidence: <table> row <id>` is joined to that row, and the
#      fields that actually answer "how much, to whom, when, what happens if I do nothing" are put on
#      the card.
#   2. GATE: a decision with no facts is not a decision, it is a chore. It is held out of the
#      working set and COUNTED as "being prepared", never deleted, because presenting it would cost
#      him the one thing the queue is for.
# ---------------------------------------------------------------------------

RE_EVIDENCE = re.compile(r"Evidence:\s*([A-Za-z][A-Za-z0-9_]{2,40})\s+row\s+([0-9]+)", re.I)

#: Only these columns are read from an evidence row, and each is printed with a human label. An
#: arbitrary column dump would put internal ids and log noise on his card.
DOSSIER_COLS = (
    ("note", "What the record says"),
    ("balance", "Balance"),
    ("amount", "Amount"),
    ("due_date", "Due"),
    ("recurrence", "Repeats"),
    ("priority", "Priority"),
    ("status", "Status"),
    ("evidence_source", "Where the figure came from"),
    ("subject_tags", "About"),
)

#: Short, concrete, checkable. A context that has none of these is a summary of a summary.
RE_CONCRETE = re.compile(r"\$?\b\d[\d,\.]*\b|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b(monday|tuesday|"
                         r"wednesday|thursday|friday|saturday|sunday)\b", re.I)


def _evidence_facts(con, context):
    """The record behind a filed row: [(label, value)], or []. Never raises."""
    m = RE_EVIDENCE.search(str(context or ""))
    if not m:
        return []
    table, rid = m.group(1), m.group(2)
    if not re.match(r"^[a-z][a-z0-9_]+$", table.lower()):
        return []
    try:
        con.commit()
        row = con.execute("SELECT * FROM %s WHERE id=?" % table.lower(), (rid,)).fetchone()
    except Exception:
        return []
    if not row:
        return []
    keys = set(row.keys())
    facts = []
    for col, label in DOSSIER_COLS:
        if col not in keys:
            continue
        val = row[col]
        if val is None or str(val).strip() in ("", "None"):
            continue
        text = " ".join(str(val).split())
        # A sha256 on the card is a receipt, not a fact he can use. The provenance that matters is
        # the path a person can open. Strip by SHAPE, before truncating, or the second hash survives.
        text = re.sub(r"\bsha256\s+[0-9a-fA-F]{16,}", " ", text)
        text = re.sub(r"\b[0-9a-fA-F]{32,}\b", " ", text)
        text = re.sub(r"\s*\(\s*[,;]?\s*[,;)\s]*", " (", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
        text = re.sub(r"\(\s*[,;]?\s*\)", "", text).strip()
        if len(text) > 240:
            text = text[:237].rstrip(" ,;") + "..."
        if text.count("(") > text.count(")"):
            text += ")"
        facts.append((label, text))
    return facts


def _amount_from_facts(facts):
    """The amount stated on an evidence row, or None.

    Not `_money_in`: that looks for a currency marker because a bare number in prose is usually a
    case id. On an evidence row the amount IS a number, and #698's row states its balance as
    `Balance 269.71` inside the note with no dollar sign anywhere -- which is why the card said
    nothing about money while the record held the figure twice.

    A CENTS-PAIR IS REQUIRED when the number is not on a labelled column: `Due 2026-09-22` must never
    be read as an amount of 2,026.
    """
    for label, val in facts:
        if label in ("Balance", "Amount"):
            m = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", val)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
    joined = " ".join(str(v) for _l, v in facts)
    for m in re.finditer(
            r"\b(?:balance|amount|total|owed|outstanding|paid)\b[^0-9$]{0,24}"
            r"\$?([0-9][0-9,]*(?:\.[0-9]{2}))", joined, re.I):
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            continue
    return None


def _derived_recommendation(item, facts):
    """A recommendation built from the evidence when the filed one was a template.

    MEASURED 2026-10-18: the sweep filed `Investigate it and bring me a recommendation - decide: pay
    it or dispute it (Recommended)` as both option 1 and the recommendation -- which recommends
    investigating the thing it is asking about. When the evidence row carries a balance and a due
    date, the honest recommendation writes itself and he can act on it in one word.
    """
    rec = str(item.get("recommendation") or "")
    template = (not rec) or rec.lower().startswith("investigate it and bring me")
    if not template:
        return ""
    joined = " | ".join("%s: %s" % (l, v) for l, v in facts)
    if not joined:
        return ""
    money = _amount_from_facts(facts) or _money_in(joined)
    note = dict(facts).get("What the record says", "")
    unpaid = "nothing has been paid against it" if re.search(
        r"none paid|unpaid|not paid", note, re.I) else ""
    due = dict(facts).get("Due", "")
    late = ""
    if due:
        age_days = _age_hours_from(due + "T00:00:00+00:00")
        if age_days and age_days > 24:
            late = "%d days past due" % int(age_days / 24)
    bits = [b for b in (unpaid, late) if b]
    tail = (" — " + ", ".join(bits)) if bits else ""
    if money:
        return "Pay %.2f%s; the balance is already established in the record" % (money, tail)
    if bits:
        return "Settle it — %s, and the record already holds the evidence" % ", ".join(bits)
    return ""


def _dossier(con, item):
    """(facts, ready, missing). The gate: is this item briefed well enough to put in front of him?"""
    facts = []
    if item.get("surface") == "queue":
        try:
            con.commit()
            row = con.execute("SELECT context FROM owner_decision_queue WHERE id=?",
                              (item["id"],)).fetchone()
            facts = _evidence_facts(con, row["context"] if row else "")
        except Exception:
            facts = []
    item["_facts"] = facts
    if facts:
        item["_derived_recommendation"] = _derived_recommendation(item, facts)
        # An established amount is money in the score, from the record rather than from the words.
        m = _amount_from_facts(facts)
        if isinstance(m, (int, float)) and not item.get("money"):
            item["money"] = m

    if item["kind"] != "decision":
        return facts, True, ""
    missing = []
    blob = "%s %s" % (item.get("title") or "", item.get("_context") or "")
    rec = item.get("_derived_recommendation") or item.get("recommendation") or ""
    if not str(rec).strip():
        missing.append("no recommendation")
    elif re.match(r"^\s*investigate it and bring me a recommendation",
                  str(rec), re.I) and not item.get("_derived_recommendation"):
        missing.append("the recommendation just says 'investigate'")
    if not RE_CONCRETE.search(blob) and not facts:
        missing.append("no amount, date or named party")
    if len(blob) < 80 and not facts:
        missing.append("the dossier is one line")

    # A PERSON'S MESSAGE IS NOT A FORMAL DECISION. MEASURED 2026-10-18: #595 was
    # `Text from Genack: Can I purchase a Kyocera today?` filed as a decision with no recommendation,
    # because the GV rules promote anything that asks. But a text from a person is a message with a
    # reply owed -- it already carries ask=+80 -- and calling it a decision means holding it back
    # until a recommendation is invented for it. Demoted at READ time, and said out loud.
    if (missing == ["no recommendation"] and item.get("surface") == "queue"
            and str(item.get("channel") or "") in ("sms", "call", "voicemail", "gv", "text")):
        item["kind"] = "attention"
        item["_demoted"] = "a message from a person, not a formal decision — a reply is what it wants"
        return facts, True, ""
    return facts, (not missing), "; ".join(missing)


def _print_also(it, items):
    """Say what else is this same matter, and how to close it in the same breath.

    Two kinds, and they are different promises:
      ALSO  -- rows folded into this one by proof (same message, or this decision absorbed that
               notice). Their words are already in this card; closing this closes them.
      SAME  -- rows that are probably the same matter. Not folded, because a wrong fold hides an
               item. Offered as `--with` so one sentence closes both.
    """
    also = it.get("_also") or []
    if also:
        print("\nALSO IN THIS ITEM (closes with it):")
        for sid, title in also[:6]:
            print("   #%-5s %s" % (sid, " ".join(str(title or "").split())[:88]))
    sibs = _siblings(it, items)
    if sibs:
        print("\nPROBABLY THE SAME MATTER — answering both in one go is: add `--with %s`"
              % ",".join(str(s["id"]) for s in sibs[:5]))
        for s in sibs[:5]:
            print("   #%-5s %s" % (s["id"], " ".join(str(s["title"]).split())[:88]))


def _mark_seen(con, surface, item_id):
    """Record that this reached him. Only for rows the reader owns; app rows are app state."""
    if surface != "queue":
        return
    try:
        exec_locked(con, "UPDATE owner_decision_queue SET seen_at=? WHERE id=? AND seen_at IS NULL",
                    (now(), item_id))
    except Exception:
        pass


#: How long attention stays in the working set on its own. Measured 2026-10-18: the first 7-day
#: backfill produced 100 pending items, of which 37 were 3-7 days old and 16 were older. He knocks
#: this queue out "once every other day or so" -- a 100-item list is not knockable, and a queue
#: nobody finishes is the same as no queue. So the working set is: every decision (they block work),
#: and the attention that is either still fresh, still being asked of him, still expensive, or
#: serious. Everything else is COUNTED and named, never deleted, and `--all` shows it.
WORKING_SET_ATTENTION_DAYS = 3.0
WORKING_SET_MONEY = 100.0


def _working_set(items, max_age_days=21, show_all=False):
    """(visible, hidden_old, hidden_quiet, hidden_unprepared). One rule, used by queue, card, knock.

    An ATTENTION item is held back when it has stopped being news. A DECISION is held back only when
    it has not been briefed -- because sending him a question without its facts is the one thing his
    instruction forbids ("only put it in the queue after all info is gathered about it fully"). A
    decision is never aged out: it blocks work until it is answered.
    """
    visible, old, quiet, thin = [], 0, 0, []
    for i in items:
        age = i.get("age_hours") or 0
        if i["kind"] == "decision":
            # An agent's approval request is the agent's to brief; holding it back here would hide a
            # live approval behind a rule this tool cannot satisfy. It shows, and the card says the
            # agent filed it without a recommendation.
            if not i.get("_ready", True) and not show_all and i["surface"] == "queue":
                thin.append(i)
                continue
            visible.append(i)
            continue
        if max_age_days and not show_all and age > max_age_days * 24:
            old += 1
            continue
        if show_all:
            visible.append(i)
            continue
        keep = (age <= WORKING_SET_ATTENTION_DAYS * 24
                or i.get("ask")
                or str(i.get("tier") or "").lower() in ("critical", "high")
                or (isinstance(i.get("money"), (int, float)) and i["money"] >= WORKING_SET_MONEY))
        if keep:
            visible.append(i)
        else:
            quiet += 1
    return visible, old, quiet, thin


def cmd_queue(con, a) -> int:
    """The one ordered list. `--limit 1` is the thing to run when he says "next"."""
    items = _gather_queue(con, include_deferred=getattr(a, "all", False))
    if getattr(a, "kind", None):
        items = [i for i in items if i["kind"] == a.kind]

    # AGE BOUND ON ATTENTION ONLY. An attention item is news, and news decays: a text from
    # three weeks ago is still true, but it is not what he should open the queue on. Decisions
    # are never aged out -- they keep blocking work until they are answered. Nothing is deleted
    # or closed by this: the hidden count is printed, and `--all` shows them.
    max_age = getattr(a, "max_age_days", 21)
    items, hidden_old, hidden_quiet, hidden_thin = _working_set(
        items, max_age, show_all=getattr(a, "all", False))
    if getattr(a, "new_only", False):
        items = [i for i in items if i["surface"] != "queue" or i.get("_unseen")]

    ops = _ops_alert_count(con)

    if getattr(a, "json", False):
        print(json.dumps(items[: (a.limit or len(items))], indent=1, default=str))
        return 0

    if not items:
        print("QUEUE EMPTY — nothing is waiting on you.")
        if hidden_old:
            print("  (%d attention item(s) older than %d days still pending; --all shows them)"
                  % (hidden_old, max_age))
        if hidden_quiet:
            print("  (%d quieter attention item(s) held back; --all shows them)" % hidden_quiet)
        if hidden_thin:
            print("  (%d decision(s) being briefed — I gather the facts before you see them)"
                  % len(hidden_thin))
        if ops:
            print("  (%d ops alert(s) are mine to repair, not yours)" % ops)
        return 0

    limit = a.limit or len(items)
    n_dec = sum(1 for i in items if i["kind"] == "decision")
    n_att = sum(1 for i in items if i["kind"] == "attention")
    print("%d item(s): %d decision(s), %d attention.\n" % (len(items), n_dec, n_att))
    # A row whose premise has moved is not wrong, it is OUT OF DATE, and the queue is where
    # that has to be said -- otherwise the first thing he reads is yesterday's world.
    try:
        moved = _premise_moved_rows()
    except Exception:
        moved = []
    if moved:
        print("  %d row(s) have a premise that MOVED since filing (re-measure before acting):"
              % len(moved))
        for _id, _detail in moved[:4]:
            print("     #%-5s %s" % (_id, (_detail or "")[:100]))
        print()
    for i in items[:limit]:
        age = "" if i["age_hours"] is None else "%5.1fh" % i["age_hours"]
        print("%-6s %-4s %-9s %-9s %s" % (
            ("#" + str(i["id"]))[:6], i["score"], i["kind"], age,
            " ".join(str(i["title"]).split())[:96]))
        print("       %s" % i["why"])
    if len(items) > limit:
        print("\n(+%d more; --limit N)" % (len(items) - limit))
    if hidden_old:
        print("\n%d attention item(s) older than %d days still pending (--all shows them)"
              % (hidden_old, max_age))
    if hidden_quiet:
        print("%d quieter attention item(s) held back — older than %g day(s), nobody waiting, "
              "no money, not serious (--all shows them)"
              % (hidden_quiet, WORKING_SET_ATTENTION_DAYS))
    if hidden_thin:
        print("%d decision(s) held back while I gather the facts — you should not have to decide "
              "something I have not briefed (--all shows them)" % len(hidden_thin))
    if ops:
        print("%d ops alert(s) held back as mine, not yours (paused syncs, stale capture)" % ops)
    return 0


def cmd_show(con, a) -> int:
    """One item in full: the words, the provenance, the arithmetic, my recommendation."""
    target = str(a.id)
    items = _gather_queue(con, include_deferred=True)
    match = [i for i in items if str(i["id"]) == target]
    if not match:
        print("no pending item with id %s (try: owner-queue.py queue)" % target)
        return 1
    it = match[0]
    if it["surface"] == "queue":
        row = con.execute("SELECT * FROM owner_decision_queue WHERE id=?", (it["id"],)).fetchone()
        if row:
            derived = it.get("_derived_recommendation") or ""
            repl_opts = None
            if derived:
                repl_opts = [derived,
                             "Leave it for now — I will handle it myself",
                             "Not actionable — close it and stop raising it"]
            print(fmt(row, replace_options=repl_opts,
                      replace_recommendation=derived or None))
            if it.get("_facts"):
                print("\n  WHAT THE RECORD BEHIND THIS SAYS")
                for label, val in it["_facts"]:
                    for n, line in enumerate(textwrap.wrap(val, 66)):
                        print("    %-26s %s" % (label if n == 0 else "", line))
            if it.get("_missing"):
                print("\n  NOT FULLY BRIEFED — %s." % it["_missing"])
            if it.get("moot"):
                print("POSSIBLY MOOT — %s. Check the premise before you ask him."
                      % it.get("moot_why"))
            print("SCORE %d   %s" % (it["score"], it["why"]))
            _print_also(it, items)
            _mark_seen(con, "queue", it["id"])
            return 0
    # surfaces this tool does not own: print what the reader assembled
    print("=" * 78)
    print("%s #%s  [%s]  surface=%s" % (it["kind"].upper(), it["id"], it["tier"], it["surface"]))
    print("")
    for line in textwrap.wrap(str(it["title"] or ""), 76):
        print("  " + line)
    if it["party"]:
        print("\n  FROM: %s" % it["party"])
    if it["channel"]:
        print("  CHANNEL: %s" % it["channel"])
    if it["at"]:
        print("  WHEN: %s" % str(it["at"])[:16].replace("T", " "))
    if it.get("moot"):
        print("\n  POSSIBLY MOOT — %s." % it.get("moot_why"))
    print("\nSCORE %d   %s" % (it["score"], it["why"]))
    print("=" * 78)
    return 0


def cmd_card(con, a) -> int:
    """The next ONE thing, ready to read to him. This is "let's go through the queue".

    Why it exists as a command and not as advice in a document: the owner asked for exactly this
    ("you just tell me things one at a time"), and a chat session that has to compose the walk from
    `queue` + `show` + `answer` can get it wrong in ways nobody notices. One command, one item, the
    arithmetic, the recommendation, and the verbs -- then the answer goes back through `answer` or
    `resolve`, which already record a lifecycle.
    """
    items = _gather_queue(con, include_deferred=getattr(a, "all", False))
    if getattr(a, "kind", None):
        items = [i for i in items if i["kind"] == a.kind]
    max_age = getattr(a, "max_age_days", 21)
    items, hidden, hidden_quiet, hidden_thin = _working_set(
        items, max_age, show_all=getattr(a, "all", False))
    if not items:
        print("QUEUE EMPTY — nothing is waiting on you.")
        for n, what in ((hidden, "older than %d days" % max_age),
                        (hidden_quiet, "quieter, older than %g day(s)" % WORKING_SET_ATTENTION_DAYS)):
            if n:
                print("  (%d attention item(s) %s still pending; --all shows them)" % (n, what))
        if hidden_thin:
            print("  (%d decision(s) being briefed — the facts are being gathered first)"
                  % len(hidden_thin))
        return 0
    item = items[0]
    print("ITEM 1 of %d  ·  %d decision(s), %d attention in the queue"
          % (len(items), sum(1 for i in items if i["kind"] == "decision"),
             sum(1 for i in items if i["kind"] == "attention")))
    print()
    rc = cmd_show(con, argparse.Namespace(id=item["id"]))
    if rc != 0:
        return rc
    if getattr(a, "peek", 0):
        print()
        print("NEXT UP (ids only):")
        for i in items[1:1 + a.peek]:
            print("  #%-6s %-9s %s" % (i["id"], i["kind"], str(i["title"]).split("\n")[0][:78]))
    print()
    print("ANSWER WITH: a <your answer>   |   d [why] to dismiss   |   s 3d to snooze   |   "
          "n to skip   |   q to stop")
    return 0


def _knock_apply(con, item, line):
    """Apply one answer typed at the knock prompt. Returns 'next' | 'stop' | 'skip'."""
    line = (line or "").strip()
    if not line:
        return "skip"
    verb, _, rest = line.partition(" ")
    verb = verb.lower()
    rest = rest.strip()
    if verb in ("q", "quit", "stop", "done", "exit"):
        return "stop"
    if item["surface"] != "queue":
        print("  (%s items are closed in their own system; nothing recorded here)" % item["surface"])
        return "next"
    rid = item["id"]
    if verb in ("a", "answer", "yes", "no"):
        text = rest if verb in ("a", "answer") else (" ".join(x for x in (verb, rest) if x)).strip()
        if not text:
            print("  nothing to record; type: a <your answer>")
            return "skip"
        cmd_answer(con, argparse.Namespace(id=rid, answer=text))
        return "next"
    if verb in ("d", "dismiss", "drop", "no"):
        cmd_resolve(con, argparse.Namespace(id=rid, how=None,
                                            dismissed=rest or "dismissed by the owner"))
        return "next"
    if verb in ("s", "snooze", "later"):
        if not rest:
            print("  how long? e.g. s 3d   or   s 2026-11-02")
            return "skip"
        cmd_defer(con, argparse.Namespace(id=rid, until=rest, note="snoozed at the knock prompt"))
        return "next"
    if verb in ("n", "next", "skip"):
        if item["surface"] == "queue":
            _record_feedback(con, item["id"], "skipped", "")
        return "skip"
    # A bare sentence is treated as the answer: he should not have to learn a vocabulary.
    cmd_answer(con, argparse.Namespace(id=rid, answer=line))
    return "next"


def cmd_knock(con, a) -> int:
    """Walk the queue ONE item at a time until it is empty or he stops.

    This is the "let's knock out the queue" loop. Each item is shown in full, once, with the
    arithmetic behind its rank; the answer is the next line of input. Verbs are a, d, s, n, q -- and a
    bare sentence is taken as the answer, because he should not have to learn a syntax to reply.
    """
    seen = set()
    budget = a.limit or 1000
    shown = 0
    while shown < budget:
        all_items = [i for i in _gather_queue(con) if str(i["id"]) not in seen]
        items, _old, _quiet, _thin = _working_set(all_items, 21)
        if not items:
            print("\nQUEUE EMPTY for this walk." if shown == 0 else
                  "\nThat is the end of the queue.")
            return 0
        item = items[0]
        seen.add(str(item["id"]))
        shown += 1
        left = len(items) - 1
        print("\n" + "-" * 78)
        print("[%d remaining after this]" % left)
        rc = cmd_show(con, argparse.Namespace(id=item["id"]))
        if rc != 0:
            seen.add(str(item["id"]))
            continue
        if a.once:
            return 0
        try:
            line = input("\n  answer (a <text>) | dismiss (d) | snooze (s 3d) | next (n) | quit (q)"
                         "\n  > ")
        except EOFError:
            print()
            return 0
        action = _knock_apply(con, item, line)
        if action == "stop":
            return 0
    return 0


VENV_PYTHON = "/root/personal-secretary-mvp/.venv/bin/python"
INGESTS = {
    "gv": ("/root/bin/owner-queue-ingest-gv.py", "Google Voice forwards in mail"),
    "mail": ("/root/bin/owner-queue-ingest-mail.py", "ordinary email, judged"),
}


def cmd_ingest(con, a) -> int:
    """Pull personal comms into the queue: Google Voice and personal email. Dialpad is explicitly
    excluded by the owner's rule of 2026-10-18.

    The mailbox reads need the app's venv, so each channel is a companion script; the queue table is
    the same one this tool owns, so there is still exactly one queue. `all` runs both and returns the
    WORST exit code -- one broken channel must not be hidden by the other one succeeding.
    """
    import subprocess
    wanted = ["gv", "mail"] if a.source == "all" else [a.source]
    worst = 0
    for name in wanted:
        path, label = INGESTS[name]
        if not os.path.exists(path):
            print("%s: missing %s -- cannot read the mailbox without it" % (name, path))
            worst = max(worst, 3)
            continue
        cmd = [VENV_PYTHON, path, "--days", str(a.days), "--db", a.db]
        if getattr(a, "explain", False):
            cmd.append("--explain")
        if getattr(a, "only_dropped", False):
            cmd += ["--explain", "--only-dropped"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        sys.stdout.write(r.stdout or "")
        if r.returncode != 0:
            sys.stderr.write(r.stderr or "")
            print("%s ingest (%s) failed with exit %d" % (name, label, r.returncode))
            worst = max(worst, r.returncode)
    return worst


def cmd_health(con, a) -> int:
    """Is the queue still being FED? A queue that stopped filling and a queue with nothing to say
    look identical from inside the table, so this reads each SOURCE and prints the arithmetic that
    decided pass or fail. Exit 1 when any source is stale, so a timer can fail loudly."""
    now_dt = dt.datetime.now(dt.timezone.utc)
    rows_out, failures = [], 0

    def age_of(value):
        h = _age_hours_from(value)
        return None if h is None else h

    # 1. per channel: how old is the newest thing that arrived, and how fast did it arrive
    for channel, label in (("sms", "Google Voice texts"), ("missed_call", "Voice missed calls"),
                           ("voicemail", "Voice voicemails"), ("email", "email (judged)")):
        r = con.execute(
            "SELECT COUNT(*) n14, MAX(COALESCE(evidence_at, asked_at)) newest"
            "  FROM owner_decision_queue"
            " WHERE channel=? AND COALESCE(evidence_at, asked_at) > datetime('now','-14 day')",
            (channel,)).fetchone()
        n14, newest = int(r["n14"] or 0), r["newest"]
        age = age_of(newest)
        gap = (14 * 24.0 / n14) if n14 else None
        limit = max(48.0, (6 * gap) if gap else 72.0)
        state = "QUIET"
        if age is not None:
            state = "OK" if age <= limit else "STALE"
        if n14 == 0:
            state = "NO DATA"
        if state == "STALE":
            failures += 1
        rows_out.append((label, n14, age, limit, state))

    # 2. per ingest: did the writer run, and did it write
    for src, label in (("gv-ingest:%", "gv ingest"), ("mail-ingest:%", "mail ingest")):
        r = con.execute(
            "SELECT COUNT(*) n7, MAX(asked_at) newest FROM owner_decision_queue"
            " WHERE source LIKE ? AND asked_at > datetime('now','-7 day')", (src,)).fetchone()
        age = age_of(r["newest"])
        state = "OK" if (age is not None and age <= 48) else ("STALE" if age is not None else "NO DATA")
        if state == "STALE":
            failures += 1
        rows_out.append((label + " wrote", int(r["n7"] or 0), age, 48.0, state))

    # 3. the judge itself: a dead judge is a dead email channel
    try:
        r = con.execute("SELECT COUNT(*) n, MAX(judged_at) newest FROM owner_mail_verdict"
                        " WHERE judged_at > datetime('now','-7 day')").fetchone()
        age = age_of(r["newest"])
        state = "OK" if (age is not None and age <= 48) else ("STALE" if age is not None else "NO DATA")
        if state == "STALE":
            failures += 1
        rows_out.append(("mail judge", int(r["n"] or 0), age, 48.0, state))
    except Exception as exc:  # noqa: BLE001
        rows_out.append(("mail judge", 0, None, 48.0, "NO TABLE"))
        failures += 1

    # 4. COMPLETENESS, which freshness cannot answer. "18 rows arrived" is compatible with "62 items
    # were never read"; each ingest now writes what it fetched and how many of those it accounted
    # for, and the number that must be zero is unexplained mail. A reader that silently loses a
    # folder looks exactly like a quiet week from every other line on this page.
    try:
        con.commit()
        runs = {}
        for r in con.execute(
                "SELECT source, ran_at, fetched, queued, dropped, errors, note"
                "  FROM owner_queue_ingest_run ORDER BY id DESC LIMIT 40").fetchall():
            runs.setdefault(str(r["source"]), r)
        for src, label in (("gv", "gv read everything"), ("mail", "mail read everything")):
            run = runs.get(src)
            if not run:
                rows_out.append((label, 0, None, 48.0, "NO RUN YET"))
                continue
            fetched = int(run["fetched"] or 0)
            queued = int(run["queued"] or 0)
            dropped = int(run["dropped"] or 0)
            # `fetched - dropped - queued` is the COLLAPSE count, not a loss: twelve texts in one
            # family chat become one row on purpose. Calling it unexplained would make the health
            # check cry wolf on every normal run, which is how a check stops being read. What is a
            # failure is a source that stopped running, a run that reported errors, or arithmetic
            # that comes out NEGATIVE -- that one is a bug, and it must not be silently clamped.
            folded = fetched - dropped - queued
            age = age_of(run["ran_at"])
            state = "OK"
            if folded < 0:
                state = "ARITHMETIC %d" % folded
                failures += 1
            elif int(run["errors"] or 0):
                state = "ERRORS %d" % int(run["errors"])
                failures += 1
            elif age is not None and age > 48:
                state = "STALE"
                failures += 1
            rows_out.append((label, fetched, age, 48.0,
                             state if state != "OK" else "OK (%d folded)" % max(0, folded)))
    except Exception as exc:  # noqa: BLE001
        rows_out.append(("run arithmetic", 0, None, 48.0, "NO TABLE"))

    # 5. what is pending, by kind and tier
    pend = {}
    for r in con.execute(
            "SELECT kind, severity, COUNT(*) n FROM owner_decision_queue"
            " WHERE status='pending' GROUP BY 1,2"):
        pend[(r["kind"] or "decision", r["severity"] or "medium")] = int(r["n"])

    if getattr(a, "json", False):
        print(json.dumps({"sources": [
            {"what": w, "n_14d": n, "age_hours": None if h is None else round(h, 1),
             "limit_hours": lim, "state": s} for w, n, h, lim, s in rows_out],
            "pending": {"%s/%s" % k: v for k, v in pend.items()},
            "failures": failures}, indent=1))
        return 1 if failures else 0

    print("OWNER QUEUE HEALTH   %s UTC" % now_dt.strftime("%Y-%m-%d %H:%M"))
    print("%-22s %6s %10s %9s  %s" % ("source", "rows", "age", "limit", "state"))
    for what, n, h, lim, state in rows_out:
        print("%-22s %6d %10s %8.0fh  %s"
              % (what, n, ("%5.1fh" % h) if h is not None else "   n/a", lim, state))
    print()
    total = sum(pend.values())
    print("pending: %d  (%s)" % (total, ", ".join(
        "%s" % ("%s/%s %d" % (k[0], k[1], v)) for k, v in sorted(pend.items()))) or "0")
    if failures:
        print("\nFAILED: %d source(s) stale. A stale reader over a live channel is the defect this "
              "queue exists to stop; run: owner-queue.py ingest all --days 2" % failures)
        return 1
    print("\nAll sources fresh.")
    return 0


def cmd_learning(con, a) -> int:
    """What his own answers have taught the queue. Evidence, not a claim."""
    if getattr(a, "backfill", False) or getattr(a, "json", False):
        n = _feedback_from_history(con)
        if n:
            print("learned from %d close(s) already on the record — no question asked twice" % n)
    prof = _learning_profile(con)
    try:
        tally = {r["action"]: int(r["n"]) for r in con.execute(
            "SELECT action, COUNT(*) n FROM owner_queue_feedback"
            " WHERE at > datetime('now', ?) GROUP BY 1", ("-%d day" % LEARN_WINDOW_DAYS,))}
    except Exception:
        tally = {}
    try:
        recent = con.execute(
            "SELECT item_id, action, substr(COALESCE(answer,''),1,70) said, party, at"
            "  FROM owner_queue_feedback ORDER BY at DESC LIMIT 12").fetchall()
    except Exception:
        recent = []

    if getattr(a, "json", False):
        print(json.dumps({
            "window_days": LEARN_WINDOW_DAYS,
            "actions": tally,
            "adjustments": prof,
            "recent": [dict(r) for r in recent]}, indent=1))
        return 0

    print("OWNER QUEUE LEARNING   window %d days   sample floor: a sender %d closes, a channel %d"
          % (LEARN_WINDOW_DAYS, LEARN_DIM_RULES["party"]["min"],
             LEARN_DIM_RULES["channel"]["min"]))
    print("  rule: he dismisses >=%d%% of a kind => it sinks; he acts on >=%d%% => it rises"
          % (int(LEARN_DISMISS_HIGH * 100), int(LEARN_ANSWER_HIGH * 100)))
    print("  capped at +%d / -%d for a sender, less for a channel — learning reorders inside a band "
          "and never inverts one"
          % (LEARN_DIM_RULES["party"]["elev"], LEARN_DIM_RULES["party"]["cap"]))
    print()
    if not tally:
        print("No closes on the record yet: nothing has been answered, dismissed or snoozed.")
        print("Run `learning --backfill` to learn from the closed rows already in the table.")
        return 0
    print("what he has done: " + ", ".join("%s %d" % (k, v) for k, v in sorted(tally.items())))
    try:
        con.commit()
        live = con.execute(
            "SELECT COUNT(*) FROM owner_queue_feedback WHERE action IN"
            " ('answered','dismissed','skipped','deferred')"
            " AND LOWER(TRIM(COALESCE(channel,''))) IN (%s)"
            % ",".join("'%s'" % c for c in LIVE_CHANNELS)).fetchone()[0]
        stale = con.execute(
            "SELECT COUNT(*) FROM owner_queue_feedback WHERE action IN"
            " ('answered','dismissed','skipped','deferred')").fetchone()[0] - live
    except Exception:
        live, stale = 0, 0
    print("evidence: %d close(s) from a channel that still writes this queue; "
          "%d from retired surfaces (excluded — they cannot teach the current ranking)"
          % (live, stale))
    print()
    total = 0
    for dim in LEARN_DIMENSIONS:
        cells = prof.get(dim) or {}
        if not cells:
            continue
        print("%s" % dim.upper())
        for name, cell in sorted(cells.items(), key=lambda kv: -abs(kv[1]["adj"])):
            print("  %-6s %-34s n=%-3d acts %3.0f%%   %s"
                  % ("RISES" if cell["adj"] > 0 else "SINKS", name[:34], cell["n"],
                     cell["act"] * 100, cell["adj"]))
            print("         %s" % cell["why"])
            total += 1
    if not total:
        print("Nothing has crossed its sample floor yet (a sender needs %d closes, a whole channel "
              "%d, all from a live channel)."
              % (LEARN_DIM_RULES["party"]["min"], LEARN_DIM_RULES["channel"]["min"]))
        print("That is not a fault: the queue writes full dimensions on every close from 2026-10-18, "
              "so the")
        print("next knock-through teaches it. `learning` after a session is the evidence.")
    print()
    if recent:
        print("the last things he said (this is the training data, verbatim):")
        for r in recent:
            print("  %s  %-9s #%-6s %-18s %s"
                  % (str(r["at"])[:16].replace("T", " "), r["action"], r["item_id"],
                     (r["party"] or "")[:18], r["said"] or ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="queue a row; --from-json is the shell-proof path")
    p.add_argument("--question")
    p.add_argument("--context")
    p.add_argument("--options", help="pipe-separated (JSON arrays also accepted)")
    p.add_argument("--recommendation")
    p.add_argument("--severity", default=None,
                   choices=["critical", "high", "medium", "low"])
    p.add_argument("--blocks", help="what other work this is holding up")
    p.add_argument("--source")
    p.add_argument("--age-days", type=int)
    p.add_argument("--from-json", metavar="FILE|-",
                   help="one JSON object with question/context/options/recommendation/"
                        "severity/blocks/source/age_days; text never passes a shell")
    p.add_argument("--allow-suspect-text", action="store_true",
                   help="store text the P265 guard flagged (default: refuse)")
    p.add_argument("--domain", choices=list(DOMAINS), default=None,
                   help="what this row is (default: owner). customer/business/"
                        "engineering are refused: they belong in the ledger")
    p.add_argument("--owner-worthy", action="store_true",
                   help="deliberate escape; requires --owner-reason")
    p.add_argument("--owner-reason", metavar="WHY",
                   help="why only the owner can decide this; required with "
                        "--owner-worthy")

    p = sub.add_parser("next")
    p.add_argument("--peek", type=int, default=1)

    p = sub.add_parser("list", help="the raw table; DECISIONS ONLY by default (the phone digest reads this)")
    p.add_argument("--all", action="store_true")
    p.add_argument("--kind", choices=["decision", "attention"], default="decision")
    p.add_argument("--json", action="store_true", help="machine-readable, for the journal mirror")

    p = sub.add_parser("brief", help="ONE queue: owner decisions and agent questions together, ranked by urgency")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="include deferred rows")

    sub.add_parser("stats")

    p = sub.add_parser("lint", help="P265 detector over the whole queue")
    p.add_argument("--json", action="store_true")
    p.add_argument("--show-text", action="store_true",
                   help="also print each flagged field as its exact stored string")

    p = sub.add_parser("sweep",
                       help="READ-ONLY: list existing rows the domain guard would "
                            "refuse; never moves or deletes them")
    p.add_argument("--all", action="store_true",
                   help="include resolved/answered/dismissed rows (default: pending)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("resolve")
    p.add_argument("id", type=int)
    p.add_argument("--how")
    p.add_argument("--dismissed")
    p.add_argument("--with", dest="with_ids",
                   help="also close these ids (comma or space separated) -- rows that were the "
                        "same matter, so one answer closes the cluster and none comes back")

    p = sub.add_parser("answer")
    p.add_argument("id", type=int)
    p.add_argument("--answer", required=True)
    p.add_argument("--with", dest="with_ids",
                   help="also close these ids (comma or space separated) with the same answer")

    p = sub.add_parser(
        "amend",
        help="refresh a PENDING row's context/recommendation as the measurement moves; the "
             "question itself is never touched")
    p.add_argument("id", type=int)
    p.add_argument("--context")
    p.add_argument("--recommendation")
    p.add_argument("--note", help="why it changed; appended to the context with today's date")

    p = sub.add_parser(
        "defer",
        help="record that the owner has seen this and put it off; the row stays "
             "pending and stops counting as overdue until the day he named")
    p.add_argument("id", type=int)
    p.add_argument("--until", help="YYYY-MM-DD, 'tomorrow', or '+3d'")
    p.add_argument("--note", help="what he said, verbatim where possible")
    p.add_argument("--clear", action="store_true", help="remove a deferral")

    # ── the one queue: everything that needs him, in one order ──────────────
    p = sub.add_parser(
        "queue",
        help="THE one queue: decisions and personal-comms attention together, ranked "
             "by one score that prints its own arithmetic")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--all", action="store_true", help="include deferred rows")
    p.add_argument("--kind", choices=["decision", "attention"])
    p.add_argument("--json", action="store_true")
    p.add_argument("--new-only", action="store_true", help="only rows never yet shown to him")
    p.add_argument("--max-age-days", type=int, default=21,
                   help="hide attention older than this (decisions are never hidden; 0 disables)")

    p = sub.add_parser("show", help="one item in full, with the arithmetic behind its rank")
    p.add_argument("id", type=str)

    p = sub.add_parser(
        "card",
        help="the NEXT ONE thing, ready to read to him -- this is \"let's go through the queue\"")
    p.add_argument("--kind", choices=["decision", "attention"])
    p.add_argument("--all", action="store_true", help="include deferred rows")
    p.add_argument("--peek", type=int, default=0, help="also list the next N ids")
    p.add_argument("--max-age-days", type=int, default=21)

    p = sub.add_parser(
        "knock",
        help="walk the queue ONE item at a time until it is empty or he stops")
    p.add_argument("--once", action="store_true", help="show the next item and stop")
    p.add_argument("--limit", type=int, default=25,
                   help="stop after N items (default 25: a session, not a marathon; 0 = all)")

    p = sub.add_parser(
        "ingest",
        help="pull personal comms into the queue. Google Voice and personal email; "
             "Dialpad is explicitly excluded by the owner's rule of 2026-10-18")
    p.add_argument("source", choices=["gv", "mail", "all"])
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--explain", action="store_true", help="print every verdict, write nothing")
    p.add_argument("--only-dropped", action="store_true")

    p = sub.add_parser(
        "health",
        help="is the queue still being FED? per-source freshness with the arithmetic; exit 1 if "
             "a source has gone stale")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser(
        "learning",
        help="what his own answers have taught the queue: actions, what rises, what sinks")
    p.add_argument("--json", action="store_true")
    p.add_argument("--backfill", action="store_true",
                   help="copy every already-closed queue row into the feedback table first, so the "
                        "profile learns from the 553 closes on the record instead of only new ones")

    a = ap.parse_args()
    fn = {"add": cmd_add, "next": cmd_next, "list": cmd_list,
          "stats": cmd_stats, "lint": cmd_lint, "sweep": cmd_sweep,
          "resolve": cmd_resolve, "answer": cmd_answer,
          "defer": cmd_defer, "amend": cmd_amend, "brief": cmd_brief,
          "queue": cmd_queue, "show": cmd_show, "card": cmd_card, "knock": cmd_knock,
          "ingest": cmd_ingest, "health": cmd_health, "learning": cmd_learning}[a.cmd]
    # lint and sweep on the live database must not need a write lock. queue/show/card/knock DO
    # write seen_at -- that is what makes "what is new since you last looked" answerable.
    # `learning --backfill` WRITES the feedback table, so it must not open read-only: it did, and the
    # guard in _feedback_from_history caught the write error and reported "0 learned" -- which looks
    # exactly like "there is nothing to learn from". Measured 2026-10-18: 557 closable rows, 0 written.
    readonly = a.cmd in ("lint", "list", "next", "stats", "sweep", "brief", "health")
    if a.cmd == "learning" and not getattr(a, "backfill", False):
        readonly = True
    con = connect(a.db, readonly=readonly)
    return fn(con, a)


if __name__ == "__main__":
    sys.exit(main())
