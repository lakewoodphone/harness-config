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


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _row(r: sqlite3.Row) -> dict:
    return {
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


def search(db: str, q: str, kind: str | None = None, limit: int = 20,
           exact: bool = False, since: str | None = None,
           until: str | None = None, party: str | None = None) -> dict:
    con = _connect(db)
    try:
        meta = _meta(con)
        table = "comms_tri" if exact else "comms_fts"
        # Trigram cannot stem, so it must be given a literal; porter gets the terms.
        match = f'"{q}"' if exact else q
        sql = (f"SELECT c.* FROM {table} f JOIN comms c ON c.id = f.rowid "
               f"WHERE {table} MATCH ?")
        args: list = [match]
        if kind:
            sql += " AND c.kind = ?"
            args.append(kind)
        if since:
            sql += " AND c.day >= ?"
            args.append(since)
        if until:
            sql += " AND c.day <= ?"
            args.append(until)
        if party:
            dig = _digits(party)
            clause = "c.counterparty LIKE ?"
            pargs: list = [f"%{party}%"]
            if dig:
                clause += (" OR REPLACE(REPLACE(REPLACE(c.address,'+',''),'-',''),' ','')"
                           " LIKE ?")
                pargs.append(f"%{dig[-10:]}%")
            sql += f" AND ({clause})"
            args.extend(pargs)
        sql += " ORDER BY c.ts DESC LIMIT ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
        age = _age_hours(meta)
        return {
            "ok": True,
            "mode": "search",
            "query": q,
            "count": len(rows),
            "results": [_row(r) for r in rows],
            "index_age_hours": None if age is None else round(age, 2),
            "index_stale": bool(age is not None and age > STALE_HOURS),
            "indexed_total": con.execute("SELECT COUNT(*) FROM comms").fetchone()[0],
            "last_index": meta.get("last_index"),
        }
    finally:
        con.close()


def thread(db: str, party: str, limit: int = 60,
           since: str | None = None) -> dict:
    """Everything we have with one person, oldest first — the actual conversation."""
    con = _connect(db)
    try:
        dig = _digits(party)
        if not dig and not party:
            return {"ok": False, "error": "party is required"}
        clauses = ["c.counterparty LIKE ?"]
        args: list = [f"%{party}%"]
        if dig:
            tail = dig[-10:]
            clauses.append(
                "REPLACE(REPLACE(REPLACE(REPLACE(c.address,'+',''),'-',''),' ',''),"
                "'.','') LIKE ?")
            args.append(f"%{tail}%")
        sql = (f"SELECT c.* FROM comms c WHERE ({' OR '.join(clauses)})")
        if since:
            sql += " AND c.day >= ?"
            args.append(since)
        sql += " ORDER BY c.ts DESC LIMIT ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
        rows = list(reversed(rows))  # chronological reads better for a conversation
        meta = _meta(con)
        age = _age_hours(meta)
        return {
            "ok": True,
            "mode": "thread",
            "party": party,
            "count": len(rows),
            "results": [_row(r) for r in rows],
            "index_age_hours": None if age is None else round(age, 2),
            "index_stale": bool(age is not None and age > STALE_HOURS),
        }
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
    finally:
        con.close()

    state = {}
    try:
        with open(STATE, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass

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
    return {
        "ok": not problems,
        "problems": problems,
        "total": total,
        "by_kind": by_kind,
        "index_age_hours": None if age is None else round(age, 2),
        "last_index": meta.get("last_index"),
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
        db: str = DEFAULT_DB) -> dict:
    """Called by POST /tools/run/comms_search with string params."""
    try:
        n = int(limit or 20)
    except (TypeError, ValueError):
        n = 20
    n = max(1, min(n, 200))
    truthy = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")  # noqa: E731

    if mode == "health":
        return dict(health(db), mode="health")
    if mode == "thread":
        return thread(db, party, limit=n, since=since or None)
    try:
        return search(db, q, kind=kind or None, limit=n, exact=truthy(exact),
                      since=since or None, until=until or None,
                      party=party or None)
    except sqlite3.OperationalError as exc:
        # A malformed FTS query is a user error, not a crash: say which.
        return {"ok": False, "mode": mode, "query": q,
                "error": f"{exc} — FTS5 syntax; quote phrases, e.g. \"water damage\""}


def _render(res: dict) -> str:
    if not res.get("ok"):
        return f"comms-search: ERROR {res.get('error') or res.get('problems')}"
    lines = []
    if res.get("mode") == "health":
        lines.append(f"comms index: {res['total']:,} communications "
                     f"({res['index_age_hours']}h old)")
        for k, v in (res.get("by_kind") or {}).items():
            lines.append(f"  {k:<10} {v:>9,}")
        if res.get("problems"):
            lines.append("  PROBLEMS: " + "; ".join(res["problems"]))
        return "\n".join(lines)
    stale = "  [INDEX STALE]" if res.get("index_stale") else ""
    lines.append(f"{res['count']} result(s) for {res.get('query') or res.get('party')}"
                 f"{stale}")
    for r in res["results"]:
        who = " ".join(str(r["who"] or r["phone"] or "").split())[:24]
        body = " ".join((r["text"] or "").split())
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
    p.add_argument("q")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--party")
    p.set_defaults(mode="search")

    p = sub.add_parser("thread")
    p.add_argument("party")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--since")
    p.set_defaults(mode="thread")

    sub.add_parser("health").set_defaults(mode="health")

    a = ap.parse_args()
    if a.mode == "health":
        res = dict(health(a.db), mode="health")
    elif a.mode == "thread":
        res = thread(a.db, a.party, limit=a.limit, since=a.since)
    else:
        try:
            res = search(a.db, a.q, kind=a.kind, limit=a.limit, exact=a.exact,
                         since=a.since, until=a.until, party=a.party)
        except sqlite3.OperationalError as exc:
            res = {"ok": False, "error": f"{exc} — FTS5 syntax; quote phrases"}
    print(json.dumps(res, indent=1) if a.json else _render(res))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
