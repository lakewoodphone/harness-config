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
     "blocks": "...", "source": "...", "age_days": 3}

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

AGEING. `next` sorts by (blocks-others first, severity, age). An item that is blocking
other work outranks a merely old one: keeping a decision queued while it stalls the
company is the expensive failure, not the decision itself.

DEPLOYED AS: `~/bin/owner-queue.py` on **secratary only** (the authoritative
database is on that host). This file is the source; that path is the deployment.
To update a host: copy this over `~/bin/owner-queue.py` and `chmod +x` it. Every
other machine reads the queue through
`ssh secratary-ts "python3 ~/bin/owner-queue.py next"` or the journal mirror at
`journal/state/owner-questions.md`.

`defer` exists because a row the owner has seen and put off to a day he named is
still his but is not a missed deadline, and before 2026-09-22 the table had no
field to say so -- three rows were reported as blocking "past 3d" while he had
already answered each one with "tomorrow" / "after Yom Kippur". The kernel check
that reads this table honours `deferred_until`; see ceo-kernel `ck/sentinel.py`
`check_owner_queue`.

  ~/bin/owner-queue.py defer 100 --until tomorrow --note "he said: tomorrow"
  ~/bin/owner-queue.py defer 127 --until 2026-10-02 --note "after Yom Kippur"
  ~/bin/owner-queue.py defer 78 --clear

A deferral does NOT close a row: it stays pending, stays visible, and re-raises
once the day passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import textwrap

DEFAULT_DB = os.environ.get(
    "OWNER_QUEUE_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db"
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
JSON_KEYS = JSON_TEXT_KEYS + ("age_days",)

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
        con = sqlite3.connect(path, timeout=180)
    con.row_factory = sqlite3.Row
    if not readonly:
        con.executescript(SCHEMA)
        added = _migrate_schema(con)
        con.commit()
        if added:
            print(f"schema: added column(s) {', '.join(added)}", file=sys.stderr)
    return con


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
        origin = "flags"

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

    cur = con.execute(
        """INSERT INTO owner_decision_queue
           (asked_at, question, context, options_json, recommendation, severity,
            blocks, source, age_days, status)
           VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
        (now(), values["question"], values["context"], values["options_json"],
         values["recommendation"], values["severity"], values["blocks"],
         values["source"], values["age_days"]),
    )
    con.commit()
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
    con.execute(
        "UPDATE owner_decision_queue SET status=?, resolved_at=?, resolution=? WHERE id=?",
        (status, now(), text, a.id),
    )
    con.commit()
    print(f"#{a.id} -> {status}")
    return 0


def cmd_resolve(con, a) -> int:
    if a.dismissed:
        return _close(con, a, "dismissed", a.dismissed)
    if not a.how:
        print("resolve needs --how or --dismissed")
        return 1
    return _close(con, a, "resolved", a.how)


def cmd_answer(con, a) -> int:
    row = con.execute("SELECT 1 FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()

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

    p = sub.add_parser("resolve")
    p.add_argument("id", type=int)
    p.add_argument("--how")
    p.add_argument("--dismissed")

    p = sub.add_parser("answer")
    p.add_argument("id", type=int)
    p.add_argument("--answer", required=True)

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
          "stats": cmd_stats, "lint": cmd_lint,
          "resolve": cmd_resolve, "answer": cmd_answer,
          "defer": cmd_defer}[a.cmd]
    # lint on the live database must not need a write lock
    con = connect(a.db, readonly=(a.cmd == "lint"))
    return fn(con, a)


if __name__ == "__main__":
    sys.exit(main())
