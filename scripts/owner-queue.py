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


def fmt(row: sqlite3.Row) -> str:
    out = []
    out.append("=" * 78)
    out.append(f"QUEUE #{row['id']}  [{row['severity']}]  asked {row['asked_at'][:16]}"
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
    if opts:
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
    if row["recommendation"]:
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
    rows = con.execute(
        "SELECT * FROM owner_decision_queue WHERE status='pending'"
    ).fetchall()
    if not rows:
        print("QUEUE EMPTY — nothing is waiting on the owner.")
        return 0

    def key(r):
        return (
            # A row the owner has already seen and put off to a day he named is
            # still his, but it is not the thing to put in front of him now.
            1 if _is_deferred(r) else 0,
            0 if (r["severity"] or "").lower() == "critical" else 1,
            0 if _is_blocking(r["blocks"]) else 1,
            SEV_RANK.get((r["severity"] or "medium").lower(), 2),
            -_age_days(r),
            r["id"],
        )

    rows.sort(key=key)
    live = [r for r in rows if not _is_deferred(r)]
    shown = live or rows
    if a.peek and a.peek > 1:
        for r in shown[:a.peek]:
            print(f"  #{r['id']:<4} [{r['severity']:<8}] "
                  f"{'BLOCKING ' if _is_blocking(r['blocks']) else '         '}"
                  f"{r['question'][:90]}")
        if not live:
            print(f"  (all {len(rows)} pending row(s) are deferred; showing the "
                  f"earliest-deferred one)")
        return 0
    _moved = _premise_moved_rows()
    if _moved:
        print("  %d pending row(s) have a premise that MOVED since filing "
              "- the row is not wrong, it is OUT OF DATE:" % len(_moved))
        for _id, _detail in _moved:
            print("     #%-5s %s" % (_id, (_detail or "")[:112]))
        print("     re-measure all of them: python3 /root/bin/premise-check.py sweep --apply")
        print()
    _pv = _premise_verdict(shown[0]["id"])
    if _pv and "verdict=changed" in _pv:
        print("  !! PREMISE MOVED since this row was filed - re-measured by premise-check.py:")
        for _l in _pv.splitlines():
            print("     " + _l)
        print("     (the row's context now carries this measurement; read it before acting)")
        print()
    elif _pv and "verdict=fresh" in _pv:
        _d = [l.strip() for l in _pv.splitlines() if l.strip().startswith("due ") or "newest" in l
              or "confirmed" in l or "present" in l or "balance" in l]
        if _d:
            print("  premise re-measured: " + _d[0][:120])
            print()
    print(fmt(shown[0]))
    n = len(live)
    if not live:
        print(f"(nothing live: all {len(rows)} pending row(s) are deferred to a day "
              f"he named)")
    else:
        print(f"({n} live, {len(rows) - n} deferred)" if n > 1 else "(last live one)")
    return 0


def cmd_list(con, a) -> int:
    q = "SELECT * FROM owner_decision_queue"
    if not a.all:
        q += " WHERE status='pending'"
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
    return 0


def cmd_resolve(con, a) -> int:
    if a.dismissed:
        return _close(con, a, "dismissed", a.dismissed)
    if not a.how:
        print("resolve needs --how or --dismissed")
        return 1
    return _close(con, a, "resolved", a.how)


#: Seconds between the `claim` and the retried append. MEASURED 2026-10-21: after `journal.py
#: claim decisions` printed "already reserved ... nothing to publish", the very next append
#: minted D9473 and D9474.
JOURNAL_CLAIM_PAUSE = 2.5


def _journal_copy(row_id, question, answer) -> str:
    """Append the owner's words to the journal so the answer survives the row.

    MEASURED 2026-10-13: 14 of 67 answered rows had NO journal copy anywhere. This table is
    mutable -- `amend` can overwrite `answer` -- and the journal is append-only, and nothing
    connected them, so a decision he had given lived in one cell that a later edit could replace.
    Backfill for the backlog: journal/tools/reconcile-owner-answers.py.

    BEST EFFORT BY DESIGN: if the journal is unreachable the ANSWER IS STILL RECORDED and this
    says so. His answer must never fail because a secondary copy failed.

    RETURNS "" WHEN THE ENTRY LANDED, AND A REASON WHEN IT DID NOT (2026-10-21). It used to print
    a note and return None for every outcome, so `cmd_answer` reported the row answered with exit
    0 while his words existed nowhere but a mutable table cell. MEASURED that night: queue #901
    lost D9345 and #904 lost D9473 exactly that way. A non-empty return is a FAILURE; the caller
    must make it visible, never swallow it.
    """
    import os
    import re
    import subprocess
    import time
    # An explicit override first, so this is testable against a throwaway journal tree and so an
    # operator can point it somewhere else without editing the tool.
    j = os.environ.get("OWNER_QUEUE_JOURNAL") or None
    if j and not os.path.exists(j):
        return "OWNER_QUEUE_JOURNAL names a path that does not exist (%s)" % j
    if not j:
        for cand in (os.path.expanduser("~/code/harness-config/journal/tools/journal.py"),
                     "/root/code/harness-config/journal/tools/journal.py"):
            if os.path.exists(cand):
                j = cand
                break
    if not j:
        return "journal.py not found (looked in ~/code/harness-config and /root/code/harness-config)"
    title = "Owner answer, queue row #%s: %s" % (
        row_id, re.sub(r"\s+", " ", question or "")[:80])
    body = ("Recorded by `owner-queue.py answer` on %s. The row is a mutable table; this entry is\n"
            "the append-only copy. If the two ever disagree, the row was edited.\n\n"
            "**Asked**: %s\n\n**His answer**: %s" % (now(), question or "(not recorded)", answer or ""))
    cmd = [sys.executable, j, "append", "decisions", "--title", title, "--body", body,
           "--quiet", "--no-fetch", "--tags", "owner-answer",
           "--refs", "owner_decision_queue#%s" % row_id]

    def _run(argv):
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)

    try:
        out = _run(cmd)
    except Exception as exc:  # noqa: BLE001
        return "could not reach the journal (%s)" % exc
    # THE COLLISION IS TRANSIENT AND THE TOOL SAYS SO. MEASURED 2026-10-21: #901 refused D9345 and
    # #904 refused D9473, each with exit 4 and "REFUSING to write ... LOCALLY"; the window had just
    # been reserved locally, one `claim` published it, and the very next append minted. The old
    # code printed that refusal as a note and returned 0, so his words were never written and
    # nothing said so. One claim, one short pause, one retry.
    blob = (out.stderr or "") + (out.stdout or "")
    if out.returncode != 0 and "REFUSING to write" in blob and "LOCALLY" in blob:
        try:
            cl = _run([sys.executable, j, "claim", "decisions"])
            claim = "claim rc=%d %s" % (
                cl.returncode, (cl.stdout or cl.stderr or "").strip()[:160])
        except Exception as exc:  # noqa: BLE001
            claim = "claim could not run (%s)" % exc
        reason = next((l for l in blob.splitlines() if "REFUSING to write" in l), "")
        print("  journal: id collision (%s); %s; retrying once in %.1fs"
              % (" ".join((reason or blob).split())[:140], claim, JOURNAL_CLAIM_PAUSE))
        time.sleep(JOURNAL_CLAIM_PAUSE)
        try:
            out = _run(cmd)
        except Exception as exc:  # noqa: BLE001
            return "journal refused the id, then %s, then the retry could not run (%s)" % (
                claim, exc)
        if out.returncode != 0:
            return "journal refused the id twice; %s; retry said: %s" % (
                claim, (out.stderr or out.stdout or "").strip()[:220])
        print("  journal: claimed the window and landed it on the retry -- "
              + (out.stdout or "").strip()[:100])
        return ""
    if out.returncode == 0:
        print("  journal: " + (out.stdout or "").strip()[:120])
        return ""
    return "journal append failed: " + (out.stderr or out.stdout or "").strip()[:200]


def _journal_failure_on_row(con, row_id, why) -> str:
    """Write a dropped journal copy ON THE ROW, so the row itself records what happened.

    The journal is the durable record; when the mirror fails, the row is the only place his words
    still exist and the only place a later session looks. A terminal note scrolls away, so a dated
    line naming the failure and the repair is appended to `context` -- the row's own audit field,
    rendered whenever the row is read and preserved by `amend`. An ANSWERED row is not what `show`
    renders, so this is the durable half of the alarm; the loud half is the exit code and the
    stderr line `cmd_answer` prints. Never raises: the answer is already recorded and must not be
    lost to a reporting failure.
    """
    line = ("JOURNAL COPY FAILED %s: the durable copy of this answer was NOT written (%s). "
            "His words survive in this row only -- re-append them with `journal.py append "
            "decisions`, or run journal/tools/reconcile-owner-answers.py."
            % (now(), " ".join(str(why).split())[:600]))
    try:
        con.commit()
        exec_locked(con,
                    "UPDATE owner_decision_queue SET context = COALESCE(context, '') || ? "
                    "WHERE id = ?", ("\n\n" + line, row_id))
        con.commit()
    except Exception as exc:  # noqa: BLE001
        print("  (could not write the failure onto row #%s either: %s)" % (row_id, exc),
              file=sys.stderr)
    return line


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
    why = _journal_copy(a.id, row[0], a.answer)
    if why:
        # DO NOT REPORT SUCCESS (2026-10-21): the row is answered, the durable copy is not.
        line = _journal_failure_on_row(con, a.id, why)
        sys.stdout.flush()   # keep the failure AFTER "#N -> answered" in a piped log
        print("  " + line, file=sys.stderr)
        print("  the answer IS recorded on the row -- do NOT re-run `answer`; repair the journal "
              "copy instead", file=sys.stderr)
        return 3
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

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true", help="machine-readable, for the journal mirror")

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

    p = sub.add_parser("answer")
    p.add_argument("id", type=int)
    p.add_argument("--answer", required=True)

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

    a = ap.parse_args()
    fn = {"add": cmd_add, "next": cmd_next, "list": cmd_list,
          "stats": cmd_stats, "lint": cmd_lint, "sweep": cmd_sweep,
          "resolve": cmd_resolve, "answer": cmd_answer,
          "defer": cmd_defer, "amend": cmd_amend}[a.cmd]
    # lint and sweep on the live database must not need a write lock
    con = connect(a.db, readonly=(a.cmd in ("lint", "list", "next", "stats",
                                            "sweep")))
    return fn(con, a)


if __name__ == "__main__":
    sys.exit(main())
