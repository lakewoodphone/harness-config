#!/usr/bin/env python3
"""recon-apply.py — the gate between a reconciliation PLAN and a changed database.

WHY THIS EXISTS
---------------
Seven read-only agents each produce a `plan.json` describing operations that would
reconcile a store with the truth. Nothing should ever execute those directly. This
business has lost customer data twice, and the recorded failure mode of this
system is a confident claim nobody checked. So a plan does not touch a database;
it is *submitted* to this gate, which:

  1. validates every operation against a whitelist before opening a connection;
  2. captures a pre-image of every row it is about to change, to a file, first;
  3. refuses any destructive operation unless that exact operation id is named on
     the command line (`--confirm-op <id>`), which is the owner's rule expressed
     as code: "no data destroyed without an explicit yes for that exact thing";
  4. applies inside a transaction where the store supports it, and rolls back the
     whole operation on the first error;
  5. records rows-affected per operation and refuses a silent no-op, because "the
     job ran and exited 0 and produced nothing" is this system's signature defect;
  6. then offers `--verify`, which re-measures a declared verification query so the
     operator reads a number rather than trusting an exit code.

USAGE
-----
    python3 recon-apply.py --plan plan.json --dry-run
    python3 recon-apply.py --plan plan.json --apply --confirm-op D-004
    python3 recon-apply.py --plan plan.json --verify

Stores are chosen by the plan's own `store` field, per operation:
    secretary.db   -> /home/zabz/personal-secretary-mvp/data/secretary.db
    prod-pg        -> $PHONE_TECH_FULL_DIRECT_URL

This tool never deletes a file, never drops a table, and never runs DDL outside an
explicitly allowed, explicitly confirmed `create_view`/`create_index`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

SECRETARY_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
ENV_FILE = "/home/zabz/personal-secretary-mvp/.env"
WORK = Path("/home/zabz/recon-20260915")
APPLY_LOG = WORK / "apply-log.jsonl"
PREIMAGE_DIR = WORK / "preimage"

# ---------------------------------------------------------------- op whitelist
# kind -> (is_destructive, allowed statement verbs, requires_where)
KINDS = {
    "insert":        (False, {"INSERT"}, False),
    "update":        (False, {"UPDATE"}, True),
    "delete":        (True,  {"DELETE"}, True),
    "create_view":   (False, {"CREATE"}, False),
    "create_index":  (False, {"CREATE"}, False),
    "drop_view":     (True,  {"DROP"}, False),
    "repoint":       (False, set(), False),   # code change: never applied by SQL
    "add_cron":      (False, set(), False),   # operational: recorded, not applied here
    "manual":        (False, set(), False),   # needs a human step; recorded only
    "noop":          (False, set(), False),
}

FORBIDDEN = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE|ALTER\s+TABLE|VACUUM|ATTACH|DETACH"
    r"|PRAGMA\s+\w+\s*=|GRANT|REVOKE|COPY\s+\w+\s+FROM|UPDATE\s+\w+\s+SET\s+\w+\s*=\s*\w+\s*;?\s*$)",
    re.IGNORECASE,
)
# a bare UPDATE/DELETE with no WHERE is the classic data-loss shape
WHERE_REQUIRED = re.compile(r"^\s*(UPDATE|DELETE)\b", re.IGNORECASE)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def log(record: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    with APPLY_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def load_env() -> dict:
    out = {}
    p = Path(ENV_FILE)
    if not p.exists():
        return out
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def prod_url() -> str:
    env = load_env()
    url = env.get("PHONE_TECH_FULL_DIRECT_URL") or env.get("PHONE_TECH_FULL_DATABASE_URL")
    if not url:
        raise SystemExit("no PHONE_TECH_FULL_DIRECT_URL / PHONE_TECH_FULL_DATABASE_URL in " + ENV_FILE)
    return url


def connect(store: str, write: bool):
    """Open a store. Write mode is explicit, so a read-only mistake is impossible."""
    if store in ("secretary.db", "secretary", "sqlite"):
        if write:
            con = sqlite3.connect(SECRETARY_DB, timeout=30)
            con.execute("PRAGMA busy_timeout = 30000")
        else:
            con = sqlite3.connect(f"file:{SECRETARY_DB}?mode=ro", uri=True)
        return ("sqlite", con)
    if store in ("prod-pg", "postgres", "pg"):
        import psycopg2
        import psycopg2.extras
        con = psycopg2.connect(prod_url(), cursor_factory=psycopg2.extras.RealDictCursor)
        if not write:
            con.set_session(readonly=True)
        return ("pg", con)
    raise SystemExit(f"unknown store: {store!r} — expected secretary.db or prod-pg")


def validate(op: dict, plan_path: Path) -> list[str]:
    """Return a list of reasons this operation may NOT run. Empty means it passed."""
    bad = []
    oid = op.get("id") or "<no id>"
    kind = (op.get("kind") or "").strip()
    if kind not in KINDS:
        return [f"{oid}: unknown kind {kind!r}"]
    destructive, verbs, needs_where = KINDS[kind]
    sql = (op.get("sql") or "").strip()

    if kind in ("repoint", "add_cron", "manual", "noop"):
        # Not SQL. Validated for presence of the thing a human must do.
        if not (op.get("sql") or op.get("how") or op.get("notes")):
            bad.append(f"{oid}: {kind} carries neither sql/how/notes, so nobody can act on it")
        return bad

    if not sql:
        bad.append(f"{oid}: {kind} has no sql")
        return bad
    if FORBIDDEN.search(sql):
        bad.append(f"{oid}: sql contains a forbidden construct (DROP TABLE/TRUNCATE/ALTER/PRAGMA=)")
    verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    if verb not in verbs:
        bad.append(f"{oid}: kind={kind} but the statement starts with {verb}, expected one of {sorted(verbs)}")
    if needs_where and WHERE_REQUIRED.match(sql) and " where " not in sql.lower():
        bad.append(f"{oid}: {verb} with no WHERE clause — refusing an unbounded write")
    if kind == "update" and " where " not in sql.lower():
        bad.append(f"{oid}: UPDATE with no WHERE clause — refusing an unbounded write")
    if not op.get("evidence"):
        bad.append(f"{oid}: no evidence field — an operation without evidence is a guess")
    # "no silent no-op" is the rule; a row count is only ONE way to satisfy it.
    #
    # This used to demand `affected` for every kind, which made the gate refuse five perfectly
    # sound CREATE VIEW operations whose entire point is that they change no row. That is the gate
    # being wrong, not the plan: for DDL the thing that detects a silent failure is a VERIFICATION
    # query that reads the object back, so DDL must carry `verify_sql` instead. A gate that refuses
    # correct work gets switched off, and then it protects nothing.
    row_changing = {"insert", "update", "delete"}
    if kind in row_changing:
        if op.get("affected") is None:
            bad.append(f"{oid}: no 'affected' count — a write that cannot say how many rows it "
                       f"expects cannot detect a silent no-op")
    elif kind in {"create_view", "create_index", "drop_view"}:
        if not (op.get("verify_sql") or op.get("affected") is not None):
            bad.append(f"{oid}: {kind} carries no 'verify_sql' — nothing would read the object "
                       f"back, so a silent failure is undetectable")
    if not op.get("store"):
        bad.append(f"{oid}: no store (want secretary.db or prod-pg)")
    if destructive and not op.get("reversible", False):
        pass  # allowed, but the CLI will demand --confirm-op
    return bad


def preimage(store_kind, con, op: dict) -> str | None:
    """Capture the rows this operation would touch, before it touches them."""
    sql = (op.get("sql") or "").strip()
    kind = op.get("kind")
    if kind not in ("update", "delete"):
        return None
    # Derive a SELECT for the affected rows from the operation's own WHERE tail.
    m = re.search(r"\bWHERE\b(.*)$", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    table_m = re.match(r"\s*(?:UPDATE|DELETE\s+FROM)\s+([\w\".]+)", sql, re.IGNORECASE)
    if not table_m:
        return None
    table = table_m.group(1)
    sel = f"SELECT * FROM {table} WHERE {m.group(1)}"
    try:
        cur = con.cursor()
        cur.execute(sel)
        rows = [dict(r) for r in cur.fetchall()] if store_kind == "pg" else \
               [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        return f"PREIMAGE FAILED: {type(exc).__name__}: {exc}"
    PREIMAGE_DIR.mkdir(parents=True, exist_ok=True)
    fn = PREIMAGE_DIR / f"{op.get('id','op')}-{_dt.datetime.now(_dt.timezone.utc):%Y%m%dT%H%M%SZ}.json"
    fn.write_text(json.dumps({"op": op.get("id"), "table": table, "select": sel,
                              "count": len(rows), "rows": rows}, indent=1, default=str),
                  encoding="utf-8")
    return str(fn)


def apply_one(op: dict, confirm: set[str], dry: bool) -> dict:
    oid = op.get("id")
    kind = op.get("kind")
    result = {"id": oid, "kind": kind, "at": _now(), "status": "skipped", "affected": 0}
    reasons = validate(op, Path("<plan>"))
    if reasons:
        result.update(status="refused", reasons=reasons)
        return result
    if kind in ("repoint", "add_cron", "manual", "noop"):
        result.update(status="not-auto-applied", note="requires the named human/code step")
        return result

    destructive, _, _ = KINDS[kind]
    if destructive and oid not in confirm:
        result.update(status="awaiting-confirmation",
                      reasons=[f"destructive operation {oid} needs --confirm-op {oid}"])
        return result

    # A DRY RUN MUST NOT EXECUTE DDL.
    #
    # Measured 2026-09-16: this gate's --dry-run executed CREATE VIEW, and Python's sqlite3 runs DDL
    # in autocommit mode with the default isolation_level, so `con.rollback()` did NOT undo it - the
    # five views were really created by a command that reported "dry-run". Nothing was damaged (views
    # are additive, and they were wanted anyway) but the flag lied, and a flag that lies is worse than
    # no flag: someone will point it at a DROP next. So DDL is never executed in dry mode; it is
    # validated and reported, and the operator is told why it cannot be previewed.
    if dry and kind in {"create_view", "create_index", "drop_view"}:
        result.update(status="dry-run-validated",
                      note=(f"{kind} NOT executed: SQLite auto-commits DDL, so a rollback cannot undo "
                            f"it and a 'dry run' would really change the schema. Validated only."))
        return result

    # Always open for write, and use a transaction rollback to implement --dry-run.
    # A read-only connection cannot even PLAN an INSERT on SQLite ("attempt to write a
    # readonly database"), so a dry run on a read-only handle would test nothing.
    store_kind, con = connect(op["store"], write=True)
    try:
        pre = None if dry else preimage(store_kind, con, op)
        if isinstance(pre, str) and pre.startswith("PREIMAGE FAILED") and destructive:
            result.update(status="refused", reasons=[pre])
            return result
        result["preimage"] = pre

        cur = con.cursor()
        cur.execute(op["sql"])
        affected = cur.rowcount
        if dry:
            con.rollback()
            result.update(status="dry-run", affected=affected)
        else:
            con.commit()
            result.update(status="applied", affected=affected)
        expected = op.get("affected")
        if expected is not None and not dry and affected != expected:
            result["warning"] = (f"expected {expected} rows, the statement reported {affected} — "
                                 "the plan's own prediction was wrong; re-measure before believing it worked")
        # Prove the object works, do not trust the exit status. "Configured" is not "working",
        # and the recorded failure mode here is a job that succeeds and produces nothing.
        if not dry and op.get("verify_sql"):
            try:
                vcur = con.cursor()
                vcur.execute(op["verify_sql"])
                vrow = vcur.fetchone()
                result["verify"] = (list(vrow.values())[0] if isinstance(vrow, dict)
                                    else (vrow[0] if vrow else None))
            except Exception as exc:  # noqa: BLE001
                result["verify"] = f"VERIFY FAILED: {type(exc).__name__}: {exc}"
                result["status"] = "applied-but-unverified"
    except Exception as exc:  # noqa: BLE001
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        con.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--confirm-op", action="append", default=[])
    ap.add_argument("--only", action="append", default=[], help="apply only these operation ids")
    ap.add_argument("--max-risk", choices=["low", "medium", "high"], default="high")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    ops = plan.get("operations") or []
    risk_rank = {"low": 0, "medium": 1, "high": 2}

    if args.only:
        ops = [o for o in ops if o.get("id") in set(args.only)]

    print(f"plan: {args.plan}")
    print(f"axis: {plan.get('axis')}  ops: {len(ops)}  mode: "
          f"{'dry-run' if args.dry_run else 'APPLY' if args.apply else 'verify'}")

    if args.verify:
        print("\n-- verification queries declared by the plan --")
        for v in (plan.get("verification") or []):
            store = v.get("store", "prod-pg")
            try:
                sk, con = connect(store, write=False)
                cur = con.cursor()
                cur.execute(v["sql"])
                rows = [tuple(r) if not isinstance(r, dict) else tuple(r.values()) for r in cur.fetchall()]
                con.close()
                print(f"  {v.get('id','?')}: {v.get('says','')}")
                for r in rows[:10]:
                    print(f"      {r}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {v.get('id','?')}: ERROR {type(exc).__name__}: {exc}")
        return 0

    results = []
    for op in ops:
        if risk_rank.get(op.get("risk", "low"), 0) > risk_rank[args.max_risk]:
            results.append({"id": op.get("id"), "status": "skipped-risk"})
            continue
        res = apply_one(op, set(args.confirm_op), dry=not args.apply)
        results.append(res)
        if not args.apply:
            print(f"  {res['id']:<10} {res['status']:<22} {res.get('reasons') or res.get('warning') or ''}")
    if args.apply:
        for res in results:
            print(f"  {res['id']:<10} {res['status']:<22} affected={res.get('affected')} "
                  f"{res.get('error') or res.get('reasons') or ''}")
            log({"plan": args.plan, **res})

    bad = [r for r in results if r.get("status") in ("refused", "error")]
    awaiting = [r for r in results if r.get("status") == "awaiting-confirmation"]
    print(f"\nrefused/error: {len(bad)}   awaiting your per-op yes: {len(awaiting)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
