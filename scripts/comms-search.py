#!/usr/bin/env python3
"""comms-search — ask the business's own history a question, and get an answer.

WHY. `commsindex.py` builds the index and `comms-refresh.py` keeps it current, but
an index nobody can query is a filing cabinet with no door. This is the door: one
self-contained, read-only reader over `~/.fsearch/comms.db` that works three ways —

  * as a CLI on the authority, for me and for cron,
  * as an HTTP-callable dynamic tool (`data/tools/comms_search.py` -> `run()`), so
    any agent on any machine can reach the index through the live secretary API,
  * as an importable module for anything on this host.

THE THREE QUESTIONS IT IS BUILT TO ANSWER
  1. "What did this customer say?"          -> mode=thread, party=<phone>
  2. "When did anyone mention <topic>?"      -> mode=search, q=<terms>
  3. "Is this index actually usable?"        -> mode=health

READ-ONLY, ALWAYS. It opens the index with `mode=ro` and never touches the company
database. If the index is stale it says so in the result rather than answering from
memory as if it were current — a search that is quietly behind is worse than none.

USAGE
  comms-search.py search "water damage" --kind sms --limit 20
  comms-search.py thread 7325551234 --limit 50
  comms-search.py health
  comms-search.py --json search "screen" --since 2026-06-01
  (HTTP)  POST /tools/run/comms_search  {"mode":"search","q":"screen","limit":"20"}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.fsearch/comms.db")
STATE = os.path.expanduser("~/.fsearch/comms-state.json")

# Stale enough that an answer could mislead. comms-refresh rebuilds every 30 min.
STALE_HOURS = 1.5


def _connect(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise SystemExit(f"comms-search: no index at {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _meta(con: sqlite3.Connection) -> dict:
    try:
        return {r[0]: r[1] for r in con.execute("SELECT key,value FROM meta")}
    except sqlite3.Error:
        return {}


def _age_hours(meta: dict) -> float | None:
    last = meta.get("last_index")
    if not last:
        return None
    try:
        when = dt.datetime.fromisoformat(last)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0


# How a communication is attributed to a party when no person is known: the phone
# number if there is one, else whatever name the record carried.
_PARTY_KEY = ("COALESCE(NULLIF(REPLACE(REPLACE(REPLACE(REPLACE("
              "COALESCE(address,''),'(',''),')',''),'-',''),' ',''),''), "
              "LOWER(TRIM(COALESCE(counterparty,''))))")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _row(r: sqlite3.Row) -> dict:
    out = {
        "kind": r["kind"],
        "day": r["day"],
        "ts": r["ts"],
        "direction": r["direction"],
        "who": r["counterparty"],
        "phone": r["address"],
        "subject": r["subject"],
        "text": r["text"],
        "ref": r["ref"],
        "source_table": r["source_table"],
    }
    # FTS5 can hand back the passage that matched, marked up. A reader (human or
    # agent) should not have to scan 300 characters of a call transcript to find the
    # word they searched for, so the hit is included when the query produced one.
    try:
        if r["snip"]:
            out["match"] = r["snip"]
    except (IndexError, KeyError):
        pass
    return out


# ── turning what an agent typed into a query FTS5 will actually accept ────────
# An agent has not read this schema. It arrives with `query=` because that is what
# every other search tool calls it, or with a whole sentence, or with "screen
# replacement?" and a trailing question mark -- and raw FTS5 answers all three with
# `syntax error near "?"`, which reads to the caller as "this tool is broken".
# A tool that dead-ends on the first try is a tool the fleet stops calling, and
# 34 calls later, every one of them mine, is the measurement of that. So: accept
# the aliases, sanitise instead of refusing, and when the search has to loosen to
# find anything at all, say so in the result rather than passing a loose match off
# as an exact one (L1489).
_FTS_TOKEN = re.compile(r'"[^"]+"|[A-Za-z0-9_]+')
_RELATIVE = re.compile(r"^(\d+)\s*(h|d|w|m|y)$", re.I)
_WORD_DAYS = {"today": 0, "now": 0, "yesterday": 1, "week": 7, "month": 30, "year": 365}

# Words that appear in almost every record, so in a disjunction they match everything
# and rank nothing. Used ONLY on the loose fallback path: if the conjunction matched,
# no word is ever removed from a query.
_STOPWORDS = frozenset("""
a an the and or but if of to in on at for with about from by as is are was were be been being
do does did doing have has had we you i he she it they me my our your us them his her its their
what when where who whom which why how that this these those there here then than so such
no not only own same too very can will would should could just now also get got
""".split())

# What a caller might reasonably call each parameter.
_Q_ALIASES = ("query", "term", "terms", "text", "keywords", "keyword", "search", "q", "what")
_PARTY_ALIASES = ("party", "customer", "person", "name", "phone", "number", "who",
                  "contact", "caller", "from")
_KIND_ALIASES = ("kind", "type", "channel", "source")
_SINCE_ALIASES = ("since", "after", "from", "start", "date_from", "start_date")
_UNTIL_ALIASES = ("until", "before", "to", "end", "date_to", "end_date")
_LIMIT_ALIASES = ("limit", "n", "max", "count", "max_results", "top")
_DAYS_ALIASES = ("days", "window", "last_days")
_MODE_ALIASES = {
    "find": "search", "grep": "search", "lookup": "search", "query": "search",
    "conversation": "thread", "history": "thread", "messages": "thread",
    "who": "person", "identity": "person", "about": "person", "profile": "person",
    "unanswered": "waiting", "needs_reply": "waiting", "pending": "waiting",
    "status": "health", "check": "health", "index": "health", "freshness": "health",
}
VALID_MODES = ("search", "thread", "person", "waiting", "health")


def _first(extra: dict, names: tuple[str, ...]) -> str:
    """The first alias the caller actually supplied, as a string."""
    for name in names:
        v = extra.get(name)
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = " ".join(str(x) for x in v)
        v = str(v).strip()
        if v:
            return v
    return ""


def _fts_terms(q: str) -> list[str]:
    """Natural language -> FTS5-safe pieces, keeping explicit "quoted phrases"."""
    return [t for t in _FTS_TOKEN.findall(q or "") if t.strip('"')]


def _match_expr(terms: list[str], joiner: str) -> str:
    """Every piece quoted, so no punctuation can reach the FTS5 parser as syntax."""
    return joiner.join(t if t.startswith('"') else f'"{t}"' for t in terms)


def _significant(term: str) -> bool:
    """Does this word carry meaning in a search of this corpus?"""
    word = term.strip('"').lower()
    if not word:
        return False
    if any(c.isdigit() for c in word):
        return True          # a phone number or model number is always meaningful
    if len(word) <= 2:
        return False
    return word not in _STOPWORDS


def normalize_since(value: str | None, today: str | None = None) -> str | None:
    """Accept what a person types: 2026-09-01, 7d, 24h, 3w, 'last week', 'today'.

    Returns YYYY-MM-DD, or None when the value is not a date at all -- and the
    caller must then DROP the bound rather than apply a guess, because a silently
    wrong `since` returns an empty answer that reads like "nothing happened".
    """
    v = " ".join(str(value or "").split()).lower()
    v = re.sub(r"^(last|past|previous)\s+", "", v).strip()
    if not v or v in ("all", "any", "ever", "always", "none"):
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    if v in _WORD_DAYS:
        days = _WORD_DAYS[v]
    else:
        m = _RELATIVE.match(v)
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2).lower()
        days = n * {"h": 0, "d": 1, "w": 7, "m": 30, "y": 365}[unit]
        if unit == "h" and n >= 24:
            days = n // 24
    base = (dt.datetime.strptime(today, "%Y-%m-%d")
            if today else dt.datetime.now(dt.timezone.utc))
    return (base - dt.timedelta(days=days)).strftime("%Y-%m-%d")


def _party_filter(con: sqlite3.Connection, party: str, persons: int = 3) -> tuple[str, list, dict]:
    """Match one party, expanding a NAME through the person layer first.

    `party='Dovid'` used to match only records whose counterparty string happened to
    contain "Dovid", so a customer we know by number returned nothing and the caller
    concluded we had never spoken. The name is now resolved to every identifier we
    hold for that person, and which identity was used comes back in the result -- a
    resolution that cannot say who it resolved to is not evidence.

    The literal match is always OR-ed in beside the resolved one, because resolution
    can pick the wrong Dovid and a person's own name is always on their records. Same
    helper for search and thread: the two modes disagreeing about who a party is was
    the bug that made `thread Dovid` return nothing while `search --party Dovid`
    returned his messages.
    """
    clauses, args, info = [], [], {}
    try:
        found = resolve_people(con, party, limit=5)
    except sqlite3.Error:
        found = []
    if found:
        chosen = found[:max(1, int(persons))]
        info = {
            "party_resolved": chosen[0].get("display_name") or chosen[0].get("person_key"),
            "party_matched_by": chosen[0].get("matched_by"),
            "party_confidence": ("exact" if str(chosen[0].get("matched_by", "")).endswith("exact")
                                 else "estimated"),
        }
        others = [p.get("display_name") or p.get("person_key") for p in found[len(chosen):]]
        if others:
            # Saying which OTHER people share the name is what stops a caller reading a
            # merged thread as one customer when it is three.
            info["other_candidates"] = others[:4]
        for p in chosen:
            clause, args_p = _person_clause(p)
            clauses.append(clause)
            args.extend(args_p)
    clauses.append("c.counterparty LIKE ?")
    args.append(f"%{party}%")
    dig = _digits(party)
    if dig:
        clauses.append("REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(c.address,''),'(',''),')',''),"
                       "'-',''),' ','') LIKE ?")
        args.append(f"%{dig[-10:]}%")
    return "(" + " OR ".join(clauses) + ")", args, info


def search(db: str, q: str, kind: str | None = None, limit: int = 20,
           exact: bool = False, since: str | None = None,
           until: str | None = None, party: str | None = None,
           rank: str = "recent") -> dict:
    con = _connect(db)
    try:
        meta = _meta(con)
        q = " ".join(str(q or "").split())
        since = normalize_since(since)
        until = normalize_since(until)
        terms = _fts_terms(q)

        where: list = []
        args: list = []
        info: dict = {}
        if kind:
            where.append("c.kind = ?")
            args.append(kind)
        if since:
            where.append("c.day >= ?")
            args.append(since)
        if until:
            where.append("c.day <= ?")
            args.append(until)
        if party:
            clause, args_p, info = _party_filter(con, party)
            where.append(clause)
            args.extend(args_p)

        if not terms and not where:
            return {"ok": False, "mode": "search", "query": q,
                    "error": ("nothing to search for — pass q (words to look for) "
                              "and/or party (a name, number or email)")}

        table = "comms_tri" if exact else "comms_fts"
        rows: list = []
        match_mode = None
        note = None

        def _run(match: str, by: str | None = None) -> list:
            sql = (f"SELECT c.*, snippet({table}, 0, '[[', ']]', ' … ', 14) AS snip, "
                   f"bm25({table}) AS score FROM {table} f JOIN comms c ON c.id = f.rowid "
                   f"WHERE {table} MATCH ?")
            a = [match, *args]
            if where:
                sql += " AND " + " AND ".join(where)
            # Recency is the right default for this corpus ("who said this lately"),
            # but a rare term in a year-old call is what relevance ranking is for.
            sql += (" ORDER BY score LIMIT ?" if (by or rank) == "relevance"
                    else " ORDER BY c.ts DESC LIMIT ?")
            return con.execute(sql, [*a, int(limit)]).fetchall()

        if terms:
            # Trigram cannot stem, so it must be given a literal; porter gets terms.
            primary = f'"{q}"' if exact else _match_expr(terms, " AND ")
            try:
                rows = _run(primary)
                match_mode = "exact-phrase" if exact else "all-terms"
            except sqlite3.OperationalError:
                rows = []          # fall through to the looser, always-safe form
            if not rows and len(terms) > 1:
                # A sentence has two ways to fail. As a conjunction it matches nothing
                # ("when did we last talk about a cracked screen" is not a sentence
                # anyone said); as a disjunction its stopwords match everything. The
                # first attempt did exactly that and put "It's a iPhone 16 pro max" on
                # top of a question about a cracked screen, because the loose path was
                # still ordered by date -- and a loose match sorted by recency is
                # indistinguishable from no search at all. So the loose path drops the
                # empty words and is ordered by relevance, and it says which words it
                # actually used.
                significant = [t for t in terms if _significant(t)] or terms
                loose = _match_expr(significant, " OR ")
                try:
                    loose_rows = _run(loose, by="relevance")
                except sqlite3.OperationalError:
                    loose_rows = []
                if loose_rows:
                    rows = loose_rows
                    match_mode = "any-term"
                    note = ("no single record contained every term; these contain at "
                            "least one of " + str([t.strip('"') for t in significant])
                            + ", best match first — treat the match as loose")
                else:
                    match_mode = match_mode or "all-terms"
                    note = "no record contained any of these terms"
            elif not rows:
                note = "no record matched"
        else:
            # Filters only: "everything from this customer", "all calls in June".
            # Previously this path did not exist, so a caller with a party and no
            # keywords got an FTS5 syntax error instead of their history.
            match_mode = "filter-only"
            sql = ("SELECT c.*, substr(COALESCE(c.text,''),1,400) AS snip, 0 AS score "
                   "FROM comms c WHERE " + " AND ".join(where) +
                   " ORDER BY c.ts DESC LIMIT ?")
            rows = con.execute(sql, [*args, int(limit)]).fetchall()

        age = _age_hours(meta)
        out = {
            "ok": True,
            "mode": "search",
            "query": q,
            "rank": rank,
            "match_mode": match_mode,
            "count": len(rows),
            "results": [_row(r) for r in rows],
            "index_age_hours": None if age is None else round(age, 2),
            "index_stale": bool(age is not None and age > STALE_HOURS),
            "indexed_total": con.execute("SELECT COUNT(*) FROM comms").fetchone()[0],
            "last_index": meta.get("last_index"),
        }
        if terms:
            out["terms"] = [t.strip('"') for t in terms]
        if since or until:
            out["date_filter"] = {"since": since, "until": until}
        if note:
            out["note"] = note
        out.update(info)
        return out
    finally:
        con.close()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def resolve_people(con: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Find the person (or people) a query refers to: a number, an email, or a name.

    Resolution is deliberately layered from certain to fuzzy: an exact phone or email
    first, then an exact name, then a substring/trigram name match. The layer that
    matched is returned, because "we matched 848-480-5115 exactly" and "we guessed a
    half-remembered spelling" are different claims and an agent should see which.
    """
    q = " ".join(str(query or "").split())
    if not q:
        return []
    keys: dict[str, str] = {}      # person_key -> how it matched

    def _add(rows, how):
        for r in rows:
            keys.setdefault(r[0], how)

    dig = _digits(q)
    if dig and len(dig) >= 10:
        _add(con.execute("SELECT person_key FROM person_alias "
                         "WHERE alias_kind='phone' AND alias_value=?", (dig[-10:],)),
             "phone-exact")
    if "@" in q:
        _add(con.execute("SELECT person_key FROM person_alias "
                         "WHERE alias_kind='email' AND alias_value=?", (q.lower(),)),
             "email-exact")
    if q and not dig:
        _add(con.execute("SELECT person_key FROM person_alias "
                         "WHERE alias_kind='name' AND alias_value=?", (_slug(q),)),
             "name-exact")
    if not keys:
        # Trigram FTS over display_name + every observed spelling.
        try:
            _add(con.execute(
                "SELECT person_key FROM people_fts WHERE people_fts MATCH ? LIMIT ?",
                (f'"{q}"', limit)), "name-fuzzy")
        except sqlite3.OperationalError:
            pass
    if not keys:
        _add(con.execute(
            "SELECT person_key FROM people WHERE display_name LIKE ? OR phones LIKE ?"
            " OR names LIKE ? LIMIT ?", (f"%{q}%", f"%{dig or q}%", f"%{q}%", limit)),
            "name-contains")

    out = []
    for key, how in list(keys.items())[:limit]:
        row = con.execute("SELECT * FROM people WHERE person_key = ?", (key,)).fetchone()
        if not row:
            continue
        person = dict(row)
        person["matched_by"] = how
        try:
            person["phones"] = json.loads(person.get("phones") or "[]")
            person["emails"] = json.loads(person.get("emails") or "[]")
            person["names"] = json.loads(person.get("names") or "[]")
            person["kinds"] = json.loads(person.get("kinds") or "{}")
        except ValueError:
            pass
        out.append(person)
    return out


def _person_clause(person: dict) -> tuple[str, list]:
    """A WHERE fragment matching every identifier we know for one person."""
    clauses, args = [], []
    for phone in person.get("phones") or []:
        clauses.append(
            "REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(c.address,''),'(',''),')',''),"
            "'-',''),' ','') LIKE ?")
        args.append(f"%{phone}%")
    for email in person.get("emails") or []:
        clauses.append("LOWER(COALESCE(c.address,'')) = ?")
        args.append(email)
    for name in person.get("names") or []:
        clauses.append("LOWER(COALESCE(c.counterparty,'')) = ?")
        args.append(name.lower())
    if not clauses:
        clauses = ["0"]
    return "(" + " OR ".join(clauses) + ")", args


def person_view(db: str, query: str, limit: int = 40,
                since: str | None = None) -> dict:
    """Everything we know about one person, across every channel and every identifier."""
    con = _connect(db)
    try:
        people = resolve_people(con, query)
        if not people:
            return {"ok": False, "mode": "person", "query": query,
                    "error": ("no person matches that name/number/email — try "
                              "mode=search to look in the text instead")}
        results = []
        for p in people:
            clause, args = _person_clause(p)
            sql = f"SELECT c.* FROM comms c WHERE {clause}"
            a = list(args)
            if since:
                sql += " AND c.day >= ?"
                a.append(since)
            sql += " ORDER BY c.ts DESC LIMIT ?"
            a.append(int(limit))
            rows = con.execute(sql, a).fetchall()
            entry = {
                "person": p.get("display_name"),
                "person_key": p.get("person_key"),
                "matched_by": p.get("matched_by"),
                "basis": p.get("basis"),
                "phones": p.get("phones"),
                "emails": p.get("emails"),
                "names": p.get("names"),
                "comm_count": p.get("comm_count"),
                "kinds": p.get("kinds"),
                "first_seen": p.get("first_seen"),
                "last_seen": p.get("last_seen"),
                "returned": len(rows),
                "timeline": [_row(r) for r in reversed(rows)],
            }
            results.append(entry)
        meta = _meta(con)
        age = _age_hours(meta)
        return {
            "ok": True, "mode": "person", "query": query,
            "matched": len(results), "people": results,
            "index_age_hours": None if age is None else round(age, 2),
            "index_stale": bool(age is not None and age > STALE_HOURS),
        }
    finally:
        con.close()


_AUTOMATED_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?@|alerts?@|bounce|mailer|"
    r"newsletter|marketing|updates?@|support@|service@|info@|team@|hello@)", re.I)

# A message that is only an acknowledgement is a conversation closing, not one waiting
# on an answer. Without this the list leads with "Thanks!" and "Perfect thank you so
# much" -- true by the letter (their word was last, nobody replied) and useless as a
# signal. Everything it removes is *counted and reported*, so the judgement is visible
# rather than silent.
#
# Token-based rather than a regex on the whole string, because acknowledgements are
# combinations ("perfect thank you so much", "have a good shabbos") and a phrase list
# would grow forever. Any question mark disqualifies: a question is waiting on an
# answer by definition.
_ACK_WORDS = {
    "a", "all", "amen", "and", "awesome", "best", "bye", "cool", "day", "do", "fine",
    "good", "got", "great", "gutn", "have", "it", "k", "kk", "lot", "many", "much",
    "nice", "night", "no", "np", "ok", "okay", "perfect", "please", "problem",
    "right", "see", "shabbat", "shabbos", "shalom", "so", "sounds", "sure", "t",
    "thank", "thanks", "thx", "to", "too", "tov", "ttyl", "ty", "tyvm", "u", "very",
    "welcome", "weekend", "will", "ya", "yeah", "yep", "yes", "you", "yom",
    "👍", "🙏", "✅", "😀", "😊", "🙂", "❤️",
}


def _is_acknowledgement(text: str) -> bool:
    t = " ".join(str(text or "").split())
    if not t or len(t) > 80 or "?" in t:
        return False
    tokens = [w.strip("!.,;:\"'()[]") for w in t.lower().split()]
    tokens = [w for w in tokens if w]
    if not tokens or len(tokens) > 7:
        return False
    return all(w in _ACK_WORDS for w in tokens)



def _is_human_email(con: sqlite3.Connection, address: str) -> bool:
    """Is this an address a person would expect an answer at?

    Two conditions. The address must be on file from something other than mail
    arriving (`email_auto_discovered` / `email_thread_state` contacts are created
    mechanically from senders — uber@uber.com is one of them, and a "known contact"
    built that way is not evidence of a customer). And it must not look like a
    machine. The second is a labelled heuristic; the first is provenance.
    """
    addr = (address or "").strip().lower()
    if not addr or "@" not in addr:
        return False
    if _AUTOMATED_SENDER.search(addr):
        return False
    row = con.execute(
        "SELECT 1 FROM person_alias WHERE alias_kind='email' AND alias_value = ?"
        " AND reason NOT LIKE '%email_auto_discovered%'"
        " AND reason NOT LIKE '%email_thread_state%' LIMIT 1", (addr,)).fetchone()
    return bool(row)


def waiting(db: str, days: int = 7, limit: int = 25) -> dict:
    """Customers whose last word was theirs — nobody has answered them yet.

    The business question this answers is "who is waiting on us", and it is the one a
    readable archive is actually for: the last message per party, inbound, with no
    outbound after it.

    THREE SET-BASED SCANS, NOT THREE QUERIES PER PARTY. The first version asked the
    database a question per conversation (~4,000 parties x 3 queries) and did not
    finish in two minutes. This does one scan to find each party's newest timestamp,
    one to fetch that row, and one to find the newest outbound per party -- then
    compares them in memory.
    """
    con = _connect(db)
    try:
        rows = con.execute(
            f"""
            WITH base AS (
                SELECT kind, direction, ts, day, text, counterparty, address,
                       {_PARTY_KEY} AS party_key
                FROM comms
                WHERE kind IN ('sms','message','call','voicemail','email')
                  AND ts IS NOT NULL
            ),
            newest AS (
                SELECT party_key, MAX(ts) AS mts FROM base GROUP BY party_key
            ),
            outbound AS (
                SELECT party_key, MAX(ts) AS ots FROM base
                WHERE direction = 'outbound' GROUP BY party_key
            )
            SELECT b.party_key, b.kind, b.direction, b.day, b.ts, b.text,
                   b.counterparty, b.address
            FROM base b
            JOIN newest n ON n.party_key = b.party_key AND n.mts = b.ts
            LEFT JOIN outbound o ON o.party_key = b.party_key
            WHERE b.direction = 'inbound'
              AND (o.ots IS NULL OR o.ots < b.ts)
            """).fetchall()
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
                  ).strftime("%Y-%m-%d") if days else ""
        waiting, missed = [], []
        acknowledged: list = []
        for r in rows:
            if cutoff and (r["day"] or "") < cutoff:
                continue
            text = str(r["text"] or "")
            is_call = r["kind"] == "call"
            entry = {
                "party": r["party_key"],
                "who": r["counterparty"] or r["address"],
                "since": r["day"],
                "hours_waiting": (round((dt.datetime.now(dt.timezone.utc).timestamp()
                                         - r["ts"]) / 3600.0, 1) if r["ts"] else None),
                "last_kind": r["kind"],
                "last_text": text[:400],
            }
            if is_call and text.startswith("[no transcript]"):
                # Nobody got to speak, so there is nothing to answer -- it belongs in
                # the "they tried to reach us" list, not the "someone is waiting on an
                # answer" one. Mixing the two is what makes such a list stop being read.
                missed.append(entry)
            elif is_call:
                # A call that was actually held is a conversation that happened. Even
                # if the customer spoke last, they were answered -- in a phone business
                # nearly every completed call would otherwise appear here, and a list
                # that is mostly false stops being a signal.
                continue
            elif r["kind"] == "email" and not _is_human_email(con, str(r["party_key"] or "")):
                # Measured: without this the list is 137 rows of Stripe payouts, GitHub
                # notifications and Lowe's marketing -- automated mail outnumbers real
                # customer mail, and it pushed every actual customer off the page.
                continue
            else:
                if _is_acknowledgement(text):
                    acknowledged.append(entry)
                else:
                    waiting.append(entry)
        waiting.sort(key=lambda x: x["since"] or "", reverse=True)
        missed.sort(key=lambda x: x["since"] or "", reverse=True)
        # Resolve identities only for the rows being returned, not for every party.
        for w in (waiting[:max(limit, 1)] + missed[:max(limit, 1)]):
            w["person"] = None
            people = resolve_people(con, w["party"], limit=1)
            if people:
                w["person"] = people[0]["display_name"]
                w["person_key"] = people[0]["person_key"]
        meta = _meta(con)
        age = _age_hours(meta)
        return {"ok": True, "mode": "waiting", "days": days,
                "count": len(waiting[:limit]),
                "total_waiting": len(waiting),
                "total_missed_calls": len(missed),
                "closed_by_acknowledgement": len(acknowledged),
                "waiting": waiting[:limit],
                "missed_calls": missed[:limit],
                "index_age_hours": None if age is None else round(age, 2),
                "index_stale": bool(age is not None and age > STALE_HOURS)}
    finally:
        con.close()


def thread(db: str, party: str, limit: int = 60,
           since: str | None = None) -> dict:
    """Everything we have with one person, oldest first — the actual conversation.

    Identity-aware: the query is first resolved to a person, and if one is found the
    thread includes every identifier that person uses (two mobiles, a landline, an
    email), because "the conversation" is not the same thing as "the phone number".
    """
    con = _connect(db)
    try:
        dig = _digits(party)
        if not dig and not party:
            return {"ok": False, "mode": "thread", "error": "party is required"}
        # One person, not three: a thread is a claim that these words are one
        # conversation, so merging every Dovid would invent a correspondent who does
        # not exist. Any other people sharing the name are reported alongside instead.
        clause, args, info = _party_filter(con, party, persons=1)
        if info:
            how = (f"person {info.get('party_resolved')!r} "
                   f"({info.get('party_matched_by')}), plus a literal match on {party!r}")
            if info.get("other_candidates"):
                how += ("; other people share this name — " +
                        ", ".join(str(o) for o in info["other_candidates"]) +
                        " — use mode=person to pick one")
        else:
            how = f"raw match on {party!r} (no known person)"
        sql = f"SELECT c.* FROM comms c WHERE {clause}"
        if since:
            sql += " AND c.day >= ?"
            args.append(since)
        sql += " ORDER BY c.ts DESC LIMIT ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
        rows = list(reversed(rows))  # chronological reads better for a conversation
        meta = _meta(con)
        age = _age_hours(meta)
        out = {
            "ok": True,
            "mode": "thread",
            "party": party,
            "resolved": how,
            "count": len(rows),
            "results": [_row(r) for r in rows],
            "index_age_hours": None if age is None else round(age, 2),
            "index_stale": bool(age is not None and age > STALE_HOURS),
        }
        out.update(info)
        return out
    finally:
        con.close()


def health(db: str) -> dict:
    con = _connect(db)
    try:
        meta = _meta(con)
        age = _age_hours(meta)
        by_kind = {r[0]: r[1] for r in con.execute(
            "SELECT kind, COUNT(*) FROM comms GROUP BY kind ORDER BY 2 DESC")}
        total = sum(by_kind.values())
        fts = con.execute("SELECT COUNT(*) FROM comms_fts").fetchone()[0]
        tri = con.execute("SELECT COUNT(*) FROM comms_tri").fetchone()[0]
        # Ingestion freshness, per channel: the newest communication we hold. This is
        # the half the index cannot see about itself -- a fresh index over a database
        # nothing is writing to reports "ok" forever (P29: the SMS crawler worked and
        # nothing called it).
        newest: dict[str, float] = {}
        for r in con.execute("SELECT kind, MAX(ts) AS m FROM comms GROUP BY kind"):
            if r["m"]:
                newest[r["kind"]] = r["m"]
        people = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        aliases = con.execute("SELECT COUNT(*) FROM person_alias").fetchone()[0]
        # The completeness ceiling, on the surface where an agent asks "is this everything".
        # A gap that is KNOWN and has a reason is different from a gap nobody has looked at,
        # and only the second one is a defect. Counted from the index itself: a call row
        # whose text is still the synthetic "[no transcript]" marker has no words anywhere.
        unreadable = con.execute(
            "SELECT COUNT(*) FROM comms WHERE kind='call' AND text LIKE '[no transcript]%'"
        ).fetchone()[0]
        calls_total = con.execute("SELECT COUNT(*) FROM comms WHERE kind='call'").fetchone()[0]
    finally:
        con.close()

    state = {}
    try:
        with open(STATE, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    ingest = {}
    for kind, ts in sorted(newest.items(), key=lambda kv: -(kv[1] or 0)):
        hours = (now - ts) / 3600.0
        ingest[kind] = {
            "newest": dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(),
            "age_hours": round(hours, 1),
        }

    # Only channels that flow daily are enforced. Voicemail and email are quiet for days
    # at a time on a real business, and a budget on them would be a standing false alarm
    # that teaches a reader to ignore this output.
    LIVENESS_BUDGET_HOURS = {"sms": 30.0, "call": 30.0}

    problems = []
    if age is None:
        problems.append("index has never been built")
    elif age > STALE_HOURS:
        problems.append(f"index is {age:.1f}h old (limit {STALE_HOURS}h)")
    if fts != total or tri != total:
        problems.append(f"base/fts/trigram disagree: {total}/{fts}/{tri}")
    if state and not state.get("ok"):
        problems.append(f"last refresh failed: {state.get('reason') or 'unknown'}")
    if state.get("missing"):
        problems.append(f"{state['missing']} source rows are not indexed")
    for kind, budget in LIVENESS_BUDGET_HOURS.items():
        info = ingest.get(kind)
        if not info:
            problems.append(f"no {kind} in the index at all")
        elif info["age_hours"] > budget:
            problems.append(
                f"ingestion: newest {kind} is {info['age_hours']:.0f}h old "
                f"(budget {budget:.0f}h) — the index is current but the database is not "
                f"being fed (P29)")
    return {
        "ok": not problems,
        "problems": problems,
        "total": total,
        "by_kind": by_kind,
        "people": people,
        "person_aliases": aliases,
        "calls_without_transcript": unreadable,
        "calls_total": calls_total,
        "index_age_hours": None if age is None else round(age, 2),
        "last_index": meta.get("last_index"),
        "ingestion": ingest,
        "fts_rows": fts,
        "trigram_rows": tri,
        "coverage_state": {
            k: state.get(k) for k in ("ok", "at", "missing", "collapsed_duplicates",
                                      "seconds", "coverage_ok")
        } if state else None,
    }


# ── HTTP / dynamic-tool entry point ───────────────────────────────────────────
def run(mode: str = "search", q: str = "", party: str = "", kind: str = "",
        limit: str = "20", exact: str = "", since: str = "", until: str = "",
        days: str = "", db: str = DEFAULT_DB, **extra) -> dict:
    """Called by POST /tools/run/comms_search with string params.

    Tolerant on purpose. This is called by LLM agents that were told what it does,
    not what its parameters are named, and an unknown argument used to raise
    TypeError while a guessed argument name used to search for the empty string and
    return an FTS5 syntax error -- both of which read as "broken tool". So unknown
    keys are accepted and ignored, every plausible spelling of every parameter is
    honoured, and a mode we do not have says which modes we do.
    """
    q = q or _first(extra, _Q_ALIASES)
    party = party or _first(extra, _PARTY_ALIASES)
    kind = kind or _first(extra, _KIND_ALIASES)
    since = since or _first(extra, _SINCE_ALIASES)
    until = until or _first(extra, _UNTIL_ALIASES)
    limit = limit if str(limit or "").strip() else _first(extra, _LIMIT_ALIASES)
    days = days or _first(extra, _DAYS_ALIASES)

    mode = re.sub(r"[^a-z]", "", str(mode or "").strip().lower()) or "search"
    mode = _MODE_ALIASES.get(mode, mode)
    if mode not in VALID_MODES:
        return {"ok": False, "mode": mode, "error": f"unknown mode {mode!r} — use one of: "
                + ", ".join(VALID_MODES)}

    try:
        n = int(limit or 20)
    except (TypeError, ValueError):
        n = 20
    n = max(1, min(n, 200))
    truthy = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")  # noqa: E731

    if mode == "health":
        return dict(health(db), mode="health")
    if mode == "thread":
        if not (party or q):
            return {"ok": False, "mode": "thread",
                    "error": "thread needs party= (a name, phone number or email)"}
        return thread(db, party or q, limit=n, since=normalize_since(since))
    if mode == "person":
        if not (party or q):
            return {"ok": False, "mode": "person",
                    "error": "person needs party= (a name, phone number or email)"}
        return person_view(db, query=party or q, limit=n, since=normalize_since(since))
    if mode == "waiting":
        try:
            d = int(days or 7)
        except (TypeError, ValueError):
            d = 7
        return waiting(db, days=max(1, min(d, 365)), limit=n)

    # A caller who says "the last 30 days" without a date is common enough that it
    # should not silently search all time.
    if not since and days:
        since = f"{days}d"
    rank = "relevance" if _first(extra, ("rank", "sort", "order_by", "order")).lower() in (
        "relevance", "relevant", "score", "best", "bm25") else "recent"
    try:
        return search(db, q, kind=kind or None, limit=n, exact=truthy(exact),
                      since=since or None, until=until or None,
                      party=party or None, rank=rank)
    except sqlite3.OperationalError as exc:
        # A malformed FTS query is a user error, not a crash: say which, and say what
        # would have worked, because the caller is going to retry with this message.
        return {"ok": False, "mode": mode, "query": q,
                "error": f"{exc} — FTS5 rejected the expression; retry with plain "
                         f"words, e.g. q=\"water damage\""}


def _render(res: dict) -> str:
    if not res.get("ok"):
        return f"comms-search: ERROR {res.get('error') or res.get('problems')}"
    lines = []
    mode = res.get("mode")
    if mode == "health":
        lines.append(f"comms index: {res['total']:,} communications "
                     f"({res['index_age_hours']}h old)")
        # `message` and `history` come from the Playwright UI crawl, which stopped in
        # June; texts and calls are covered by the REST harvest and the webhook, so a
        # stale crawl is not a data loss. Labelled, so a reader does not mistake it for
        # one -- an unlabelled old number reads as a broken system.
        supplementary = {"message", "history"}
        for k, v in (res.get("by_kind") or {}).items():
            age_h = (res.get("ingestion") or {}).get(k, {}).get("age_hours")
            note = "  (supplementary: UI crawl, frozen by design)" if k in supplementary else ""
            lines.append(f"  {k:<10} {v:>9,}   newest "
                         f"{age_h if age_h is not None else '?'}h ago{note}")
        if res.get("people"):
            lines.append(f"  people: {res['people']:,} "
                         f"({res.get('person_aliases', 0):,} aliases)")
        if res.get("calls_total"):
            pct = 100.0 * (res["calls_total"] - res.get("calls_without_transcript", 0)) / res["calls_total"]
            lines.append(f"  call records with words: {res['calls_total'] - res.get('calls_without_transcript', 0):,}"
                         f"/{res['calls_total']:,} ({pct:.0f}%) — indexed records, so multi-leg calls are "
                         f"collapsed; the rest have no audio anywhere (source limitation, not a backlog)")
        if res.get("problems"):
            lines.append("  PROBLEMS: " + "; ".join(res["problems"]))
        return "\n".join(lines)
    if mode == "person":
        for p in res.get("people") or []:
            lines.append(f"{p['person'] or '(no name)'}  [{p['person_key']}]  "
                         f"matched by {p['matched_by']}")
            lines.append(f"  numbers: {', '.join(p.get('phones') or []) or '—'}")
            if p.get("emails"):
                lines.append(f"  emails:  {', '.join(p['emails'])}")
            kinds = ", ".join(f"{k} {v}" for k, v in (p.get("kinds") or {}).items())
            lines.append(f"  history: {p.get('comm_count') or 0} communications "
                         f"({kinds})")
            for r in p.get("timeline") or []:
                who = " ".join(str(r["who"] or r["phone"] or "").split())[:20]
                body = " ".join((r["text"] or "").split())[:170]
                arrow = {"inbound": "<-", "outbound": "->"}.get(r["direction"] or "", "  ")
                lines.append(f"    {r['day'] or '?'} [{r['kind']:<9}] {arrow} {body}")
        return "\n".join(lines)
    if mode == "waiting":
        lines.append(f"{res['total_waiting']} customer(s) waiting on an answer "
                     f"(their words, nobody replied, within {res['days']} days)")
        for w in res.get("waiting") or []:
            body = " ".join((w["last_text"] or "").split())[:150]
            who = str(w.get("person") or w["who"] or w["party"])[:26]
            lines.append(f"  {w['since']}  {who:<26} [{w['last_kind']}] {body}")
        missed = res.get("missed_calls") or []
        if missed:
            lines.append(f"{res.get('total_missed_calls', 0)} missed call(s), "
                         f"no message left (newest first)")
            for w in missed[:5]:
                who = str(w.get("person") or w["who"] or w["party"])[:26]
                lines.append(f"  {w['since']}  {who:<26} [call] no answer, no message")
        return "\n".join(lines)
    stale = "  [INDEX STALE]" if res.get("index_stale") else ""
    lines.append(f"{res['count']} result(s) for {res.get('query') or res.get('party')}"
                 f"{stale}")
    if res.get("resolved"):
        lines.append(f"  resolved: {res['resolved']}")
    for r in res["results"]:
        who = " ".join(str(r["who"] or r["phone"] or "").split())[:24]
        body = r.get("match") or " ".join((r["text"] or "").split())
        body = " ".join(str(body).split())
        if len(body) > 220:
            body = body[:220] + "…"
        arrow = {"inbound": "<-", "outbound": "->"}.get(r["direction"] or "", "  ")
        lines.append(f"  {r['day'] or '?'} [{r['kind']:<9}] {arrow} {who:<24} {body}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search")
    # Optional, not required: `search --party <customer>` with no keywords is a real
    # question ("everything from this customer"), and requiring a positional forced
    # the caller to invent one.
    p.add_argument("q", nargs="?", default="")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--party")
    p.add_argument("--days", default="")
    p.add_argument("--rank", default="recent", choices=("recent", "relevance"))
    p.set_defaults(mode="search")

    p = sub.add_parser("thread")
    p.add_argument("party")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--since")
    p.set_defaults(mode="thread")

    p = sub.add_parser("person")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--since")
    p.set_defaults(mode="person")

    p = sub.add_parser("waiting")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(mode="waiting")

    sub.add_parser("health").set_defaults(mode="health")

    a = ap.parse_args()
    if a.mode == "health":
        res = dict(health(a.db), mode="health")
    elif a.mode == "person":
        res = person_view(a.db, a.query, limit=a.limit, since=a.since)
    elif a.mode == "waiting":
        res = waiting(a.db, days=a.days, limit=a.limit)
    elif a.mode == "thread":
        res = thread(a.db, a.party, limit=a.limit, since=a.since)
    else:
        try:
            res = search(a.db, a.q, kind=a.kind, limit=a.limit, exact=a.exact,
                         since=a.since or (f"{a.days}d" if a.days else None),
                         until=a.until, party=a.party, rank=a.rank)
        except sqlite3.OperationalError as exc:
            res = {"ok": False, "error": f"{exc} — FTS5 syntax; quote phrases"}
    print(json.dumps(res, indent=1) if a.json else _render(res))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
