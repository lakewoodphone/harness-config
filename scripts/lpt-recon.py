#!/usr/bin/env python3
"""lpt-recon.py — the reconciliation check: does every store agree with the truth?

WHY THIS EXISTS
---------------
"Full reconciliation" is a term this company already uses, and it has run exactly once
(lpt-hub `docs/customer-operations/reconciliation/2026-08-27-full-reconciliation.md`).
That run was manual, so nothing could notice when it stopped being true. By 2026-09-15:
sync-records had gone 289 -> 372 with no push to production; the production website's
customer comms had been silent for 11.5 hours; the company's own `/communications/summary`
answered zeros against 127,879 stored texts; and `devices` held 1 row for 584 orders.

This tool is the part that makes reconciliation survive: it states, in numbers, whether the
stores agree, and **exits non-zero** when they do not, so a cron can fail on it. A check that
cannot fail is decoration, and this system has a recorded history of jobs that ran, exited 0
and produced nothing.

Every line prints the figure, the store it came from, and that store's own mtime/age, so no
reading is ever reported without its provenance. A check that cannot measure something says
"could not measure" — it never reports a failure to read as health.

USAGE
    python3 lpt-recon.py                 # human table, exit 1 if any check FAILs
    python3 lpt-recon.py --json          # machine-readable
    python3 lpt-recon.py --only comms    # a name prefix
    python3 lpt-recon.py --quiet         # only what is failing
    python3 lpt-recon.py --history       # what has changed since the baseline

EXIT CODES  0 all passed · 1 at least one failed · 2 something could not be measured
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import signal
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path


class _Timeout(Exception):
    """A single check exceeded its budget. Reported as a refusal, never as health."""


@contextmanager
def _deadline(seconds: int):
    """Bound one check in wall-clock time.

    Why: a check that can hang forever makes the whole tool untrustworthy, because it
    hides the answer of every check queued behind it. On 2026-09-15 a full integrity
    check on the live 5.5 GB store wedged two runs of this tool completely.
    """
    def _fire(signum, frame):  # noqa: ARG001
        raise _Timeout()
    old = None
    try:
        old = signal.signal(signal.SIGALRM, _fire)
        signal.alarm(seconds)
    except (ValueError, AttributeError):
        old = None  # not on the main thread / not POSIX: no deadline, still correct
    try:
        yield
    finally:
        try:
            signal.alarm(0)
            if old is not None:
                signal.signal(signal.SIGALRM, old)
        except (ValueError, AttributeError):
            pass

SECRETARY_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
ENV_FILE = "/home/zabz/personal-secretary-mvp/.env"
FSEARCH_DB = "/home/zabz/.fsearch/comms.db"
LPT_REFRESH = "/home/zabz/.lpt-hub-refresh/status.json"
LPT_REPO = "/home/zabz/repos/lpt-hub"
LPT_RECORDS = LPT_REPO + "/docs/customer-operations/sync-records"
BASELINE = Path("/home/zabz/recon-20260915/recon-baseline.json")


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def env_value(key: str, default: str = "") -> str:
    p = Path(ENV_FILE)
    if not p.exists():
        return default
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return default


def open_store(store: str):
    if store == "secretary":
        return sqlite3.connect(f"file:{SECRETARY_DB}?mode=ro", uri=True)
    if store == "fsearch":
        return sqlite3.connect(f"file:{FSEARCH_DB}?mode=ro", uri=True)
    if store == "prod":
        import psycopg2
        import psycopg2.extras
        url = (env_value("PHONE_TECH_FULL_DIRECT_URL")
               or env_value("PHONE_TECH_FULL_DATABASE_URL"))
        if not url:
            raise RuntimeError("no PHONE_TECH_FULL_DIRECT_URL / _DATABASE_URL in .env")
        con = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
        con.set_session(readonly=True)
        return con
    raise ValueError(f"unknown store {store!r}")


def q(con, sql, args=()):
    cur = con.cursor()
    cur.execute(sql, args)
    return [tuple(r) if not isinstance(r, dict) else tuple(r.values()) for r in cur.fetchall()]


def provenance(store: str) -> str:
    if store == "secretary":
        st = Path(SECRETARY_DB).stat()
        return f"secretary.db mtime={_dt.datetime.fromtimestamp(st.st_mtime, _dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
    if store == "fsearch":
        st = Path(FSEARCH_DB).stat()
        return f"fsearch/comms.db mtime={_dt.datetime.fromtimestamp(st.st_mtime, _dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
    return "prod-pg (live read-only)"


# ------------------------------------------------------------------ the checks
# Each returns (value, ok, unit, says, provenance_extra)
def c_prod_comms_age():
    """Measure the LAG, not the absolute age.

    2026-09-16: this check used to fail when the website's newest message was over 2 hours old, which
    is a FALSE ALARM whenever the shop has simply been quiet - and a check that cries wolf during a
    quiet afternoon trains its reader to ignore it, which is the decoration failure this tool exists
    to avoid. The defect that matters is the website being BEHIND THE LOCAL STORE, so that is what is
    measured now: local newest minus website newest. It still catches a stalled push, and it stays
    silent when nothing has happened.

    This is axis G's "the watchdog measured the local receive clock" mistake arriving from the other
    side: a clock that can go quiet is not a measure of whether anything is lost.
    """
    con = open_store("secretary")
    rows = q(con, "SELECT MAX(created_at) FROM dialpad_sms_cache "
                  "WHERE message_id NOT LIKE 'test-%' AND message_id NOT LIKE 'self-%'")
    con.close()
    local = rows[0][0] if rows else None
    con = open_store("prod")
    rows = q(con, 'SELECT MAX("createdAt") FROM communications')
    con.close()
    web = rows[0][0] if rows else None

    def _parse(v):
        if v is None:
            return None
        s = str(v).replace("Z", "+00:00")
        try:
            d = _dt.datetime.fromisoformat(s)
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)

    ld, wd = _parse(local), _parse(web)
    if ld is None or wd is None:
        return None, False, "h", "could not read both newest timestamps", \
            f"local={local!r} website={web!r}"
    lag = round((ld - wd).total_seconds() / 3600.0, 2)
    age = round((_dt.datetime.now(_dt.timezone.utc) - wd).total_seconds() / 3600.0, 2)
    return lag, (lag < 2.0), "h", \
        "the website's lag behind the local store (NOT its absolute age)", \
        (f"website is {age}h old in absolute terms, which is expected when the shop is quiet. "
         f"A positive lag means the website is missing something the shop already holds.")


def c_dialpad_sms_age():
    con = open_store("secretary")
    rows = q(con, "SELECT (strftime('%s','now') - strftime('%s', MAX(created_at)))/3600.0 "
                  "FROM dialpad_sms_cache")
    con.close()
    v = float(rows[0][0]) if rows and rows[0][0] is not None else None
    return v, (v is not None and v < 2.0), "h", \
        "age of the newest text in the Dialpad harvest (the truth being mirrored)", ""


def c_prod_calls_vs_link():
    con = open_store("prod")
    prod_calls = float(q(con, "SELECT COUNT(*) FROM communications WHERE type='PHONE_CALL'")[0][0])
    con.close()
    con = open_store("secretary")
    link = float(q(con, "SELECT COUNT(*) FROM dialpad_call_link")[0][0])
    full = float(q(con, "SELECT COUNT(*) FROM dialpad_call_full")[0][0])
    con.close()
    ratio = round(prod_calls / link, 4) if link else None
    return (f"prod={prod_calls:.0f} link={link:.0f} full={full:.0f} ratio={ratio}", True, "", \
        "production calls vs dialpad_call_link vs the harvested calls", \
        "informational: prod held 4,873 calls against 12,552 harvested; 4,873 == "
        "dialpad_call_link's size, so the bridge is the suspect, not a cap")


def c_legacy_call_orphans():
    con = open_store("secretary")
    rows = q(con, """
      SELECT COUNT(*) FROM call_log l
      WHERE NOT EXISTS (SELECT 1 FROM dialpad_call_full d WHERE d.call_id = l.call_sid)
        AND NOT EXISTS (SELECT 1 FROM dialpad_call_link k WHERE k.call_sid = l.call_sid)
    """)
    total = q(con, "SELECT COUNT(*) FROM call_log")[0][0]
    con.close()
    v = int(rows[0][0])
    return (
        v, True, "",
        f"legacy call_log rows absent from BOTH Dialpad tables (of {total})",
        "informational until axis B fixes the join key; the company's /communications/summary "
        "reads only call_log/sms_log, which is why it answers zeros",
    )


def c_legacy_sms_orphans():
    con = open_store("secretary")
    rows = q(con, """
      SELECT COUNT(*) FROM sms_log s
      WHERE NOT EXISTS (SELECT 1 FROM dialpad_sms_cache d WHERE d.message_id = s.twilio_sid)
    """)
    total = q(con, "SELECT COUNT(*) FROM sms_log")[0][0]
    con.close()
    v = int(rows[0][0])
    return v, True, "", f"legacy sms_log rows absent from dialpad_sms_cache (of {total})", ""


def c_identity_gap():
    con = open_store("secretary")
    contacts = int(q(con, "SELECT COUNT(*) FROM contacts")[0][0])
    links = int(q(con, "SELECT COUNT(DISTINCT phone_normalized) FROM comms_identity_link")[0][0])
    con.close()
    con = open_store("fsearch")
    # the column is display_name, not name — measured, after this check failed with
    # "no such column: name" on its first run. The indexer is the authority on its own schema.
    people = int(q(con, "SELECT COUNT(*) FROM people")[0][0])
    named = int(q(con, "SELECT COUNT(*) FROM people WHERE COALESCE(display_name,'') <> ''")[0][0])
    # The headline of axis C: numbers that carry traffic but reach no identity record at all.
    # `people.phones` is a JSON array, so it is unwrapped with json_each and compared against the
    # distinct addresses in `comms`. This is the number that matters - it counts real humans the
    # company cannot name - and axis C measured 1,463 of them, 90 of which are production customers.
    orphans = int(q(con, """
      SELECT COUNT(*) FROM (
        SELECT DISTINCT COALESCE(address,'') AS a FROM comms
      ) c
      WHERE LENGTH(REPLACE(REPLACE(REPLACE(c.a,'+',''),'-',''),' ','')) >= 10
        AND c.a NOT IN (SELECT je.value FROM people p, json_each(p.phones) je)
    """)[0][0])
    con.close()
    val = (f"contacts={contacts} identity_phones={links} people={people} "
           f"named={named} unmatched_comms_numbers={orphans}")
    # INFORMATIONAL, deliberately. This counts raw `address` against the raw values in
    # `people.phones` without normalising either side, which yields 4,255 where axis C's
    # normalised comparison (strip non-digits, drop a leading 1 when 11 remain) yields 1,463.
    # Axis C's figure is the authoritative one; this is a trend line. A permanent FAIL here
    # would be decoration, and this tool exists to avoid exactly that. The value is watching for
    # the number to MOVE, which means the indexer's person build changed.
    return (
        val, True, "",
        "how many humans each store claims to know, and how many traffic numbers match nobody",
        "informational: unnormalised, so it reads high; axis C's normalised headline is 1,463 "
        "traffic numbers reaching no identity record, 90 of them production customers. Watch it move.",
    )


def c_dup_calls():
    con = open_store("secretary")
    total = int(q(con, "SELECT COUNT(*) FROM dialpad_call_full")[0][0])
    uniq = int(q(con, "SELECT COUNT(DISTINCT call_id) FROM dialpad_call_full")[0][0])
    con.close()
    # NOTE: call_id IS unique, so this check passes — and that is a true statement, not a
    # clean bill of health. The indexer collapses 12,630 -> 10,348 by a DIFFERENT ref
    # (axis D owns the identity rule). Reported honestly rather than as an all-clear.
    return f"{total} rows / {uniq} unique call_id (12,630 -> 10,348 by the indexer's ref)", True, "", \
        "duplicate rows inside dialpad_call_full, by call_id", \
        "call_id is unique, so this passes; the indexer's collapse uses another key - axis D's finding"


def c_dup_sms():
    """Fail only on a real conflict, not on benign duplication.

    Axis D measured this on 2026-09-15: dialpad_sms_cache holds 2,744 duplicate groups / 5,488
    rows, and ALL of them differ ONLY in `session_id` - the same message stored under both its raw
    message id and 'ptf-thread-<phone>'. **0 groups differ in body_text.** So dedup-by-message_id
    discards no distinct text, and the row count is not a defect. A check that failed on the row
    count would be permanently red and would train its reader to ignore it - the exact "decoration"
    failure this tool exists to avoid. What WOULD be a defect is two rows with the same message_id
    and DIFFERENT text, so that is what this fails on.
    """
    con = open_store("secretary")
    total = int(q(con, "SELECT COUNT(*) FROM dialpad_sms_cache")[0][0])
    uniq = int(q(con, "SELECT COUNT(DISTINCT message_id) FROM dialpad_sms_cache")[0][0])
    conflicting = int(q(con, """
        SELECT COUNT(*) FROM (
          SELECT message_id
          FROM dialpad_sms_cache
          WHERE COALESCE(message_id,'') <> ''
          GROUP BY message_id
          HAVING COUNT(DISTINCT COALESCE(body_text,'')) > 1
        )
    """)[0][0])
    con.close()
    # informational row counts; FAIL only on a genuine content conflict
    return (f"{total} rows / {uniq} unique message_id, {conflicting} conflicting"), \
        (conflicting == 0), "", \
        "duplicate rows inside dialpad_sms_cache (axis D: benign unless text differs)", \
        "axis D measured 2,744 groups / 5,488 rows differing ONLY in session_id, 0 in body_text"


def c_prod_push_age():
    con = open_store("prod")
    rows = q(con, 'SELECT EXTRACT(EPOCH FROM (now() - MAX("createdAt")))/3600.0 FROM orders')
    con.close()
    v = float(rows[0][0]) if rows and rows[0][0] is not None else None
    return v, True, "h", "age of the newest order in production (is the case push alive?)", \
        "informational: the 2026-08-27 full reconciliation pushed 60 cases and nothing has run since"


def c_recon_run_failure():
    con = open_store("secretary")
    rows = q(con, "SELECT SUM(status='error'), COUNT(*), MAX(CASE WHEN status='error' THEN started_at END) "
                  "FROM reconciliation_runs")
    err, tot, last_err = (int(rows[0][0] or 0), int(rows[0][1] or 0), rows[0][2])
    con.close()
    rate = round(err / tot, 3) if tot else None
    return f"{err}/{tot} error (rate {rate}, last error {last_err})", True, "", \
        "the company's own agentic reconciliation runs", ""


def c_sqlite_integrity():
    # EXPENSIVE. On 2026-09-15 this hung the whole run twice on the live 5.5 GB store:
    # a full-table check while the company writes to it can take minutes. It is therefore
    # gated behind --deep. The existing cron already runs integrity_check every 15 minutes,
    # so the default run does not need to duplicate it - and a check that wedges the tool
    # is worse than a check that is absent, because it hides every other check's answer.
    con = open_store("secretary")
    rows = q(con, "SELECT COUNT(*) FROM sqlite_master")
    con.close()
    return f"{rows[0][0]} objects (integrity not run; pass --deep)", True, "", \
        "secretary.db object count", ""


def c_sqlite_integrity_deep():
    con = open_store("secretary")
    rows = q(con, "PRAGMA quick_check")
    con.close()
    v = rows[0][0] if rows else None
    return v, (v == "ok"), "", "secretary.db quick_check (--deep)", ""


def fs_checks():
    out = []
    wal = Path(SECRETARY_DB + "-wal")
    size = wal.stat().st_size if wal.exists() else 0
    out.append(dict(name="db.wal_bytes", value=size, ok=size < 200 * 1024 * 1024, unit="B",
                    says="secretary.db write-ahead log size", prov="filesystem"))
    db = Path(SECRETARY_DB)
    if db.exists():
        out.append(dict(name="db.size_bytes", value=db.stat().st_size, ok=True, unit="B",
                        says="secretary.db size", prov="filesystem"))
    p = Path(LPT_RECORDS)
    if p.exists():
        files = sorted(p.glob("*.json"))
        newest = max((f.stat().st_mtime for f in files), default=0)
        age_h = round((utcnow().timestamp() - newest) / 3600.0, 2) if newest else None
        out.append(dict(name="lpt.newest_record_age_h", value=age_h,
                        ok=(age_h is not None and age_h < 72), unit="h",
                        says=f"age of the newest of {len(files)} lpt-hub sync records",
                        prov=f"{p}"))
    else:
        out.append(dict(name="lpt.newest_record_age_h", value=None, ok=False, unit="h",
                        says="lpt-hub sync-records directory", prov=f"MISSING: {p}"))
    st = Path(LPT_REFRESH)
    if st.exists():
        d = json.loads(st.read_text())
        age = None
        try:
            ts = _dt.datetime.strptime(d.get("updated", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt.timezone.utc)
            age = round((utcnow() - ts).total_seconds() / 60.0, 1)
        except Exception:  # noqa: BLE001
            pass
        out.append(dict(name="lpt.refresh_age_min", value=age, ok=(age is not None and age < 60),
                        unit="min", says="age of the lpt-hub corpus refresh",
                        prov=f"records={d.get('records')} ff={d.get('fast_forward')}"))
        out.append(dict(name="lpt.records_count", value=d.get("records"), ok=True, unit="",
                        says="sync records the refresh sees", prov="refresh status.json"))
    return out


CHECKS = {
    "comms.prod_newest_age_h": c_prod_comms_age,
    "comms.dialpad_newest_age_h": c_dialpad_sms_age,
    "comms.prod_calls_vs_link": c_prod_calls_vs_link,
    "comms.legacy_call_orphans": c_legacy_call_orphans,
    "comms.legacy_sms_orphans": c_legacy_sms_orphans,
    "identity.gap": c_identity_gap,
    "dedup.dialpad_call_full": c_dup_calls,
    "dedup.dialpad_sms_cache": c_dup_sms,
    "lpt.production_push_age_h": c_prod_push_age,
    "company.recon_run_failure": c_recon_run_failure,
    "company.sqlite_integrity": c_sqlite_integrity,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--deep", action="store_true", help="also run the expensive integrity check")
    ap.add_argument("--check-timeout", type=int, default=60,
                    help="seconds allowed per check before it is reported as timing out")
    ap.add_argument("--baseline", action="store_true", help="write this run as the comparison baseline")
    ap.add_argument("--history", action="store_true", help="diff against the last baseline")
    args = ap.parse_args()

    todo = dict(CHECKS)
    if args.deep:
        todo["company.sqlite_integrity"] = c_sqlite_integrity_deep

    results = []
    unmeasurable = 0
    for name, fn in todo.items():
        if args.only and not name.startswith(args.only):
            continue
        # Progress goes to stderr, so a wedged check is NAMED instead of silently
        # holding every other check's answer hostage. Learned by hanging this tool twice.
        print(f"  ... {name}", file=sys.stderr, flush=True)
        t0 = _dt.datetime.now()
        try:
            with _deadline(args.check_timeout):
                val, ok, unit, says, extra = fn()
            results.append(dict(name=name, value=val, ok=bool(ok), unit=unit, says=says,
                                prov=extra, error=None,
                                secs=round((_dt.datetime.now() - t0).total_seconds(), 1)))
        except _Timeout:
            unmeasurable += 1
            results.append(dict(name=name, value=None, ok=False, unit="", says=name, prov="",
                                secs=args.check_timeout,
                                error=f"TIMED OUT after {args.check_timeout}s - this check is "
                                      f"too slow against the live store to be useful; it is a "
                                      f"refusal, not a pass"))
        except Exception as exc:  # noqa: BLE001
            unmeasurable += 1
            results.append(dict(name=name, value=None, ok=False, unit="", says=name, prov="",
                                secs=round((_dt.datetime.now() - t0).total_seconds(), 1),
                                error=f"COULD NOT MEASURE: {type(exc).__name__}: {exc}"))
    for f in fs_checks():
        if args.only and not f["name"].startswith(args.only):
            continue
        f.setdefault("error", None)
        results.append(f)

    if args.history and BASELINE.exists():
        base = {c["name"]: c["value"] for c in json.loads(BASELINE.read_text()).get("checks", [])}
        for r in results:
            if r["name"] in base and base[r["name"]] != r["value"]:
                r["changed_from"] = base[r["name"]]

    if args.baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"at": utcnow().isoformat(timespec="seconds"),
                                        "checks": results}, indent=1, default=str))

    if args.json:
        print(json.dumps({"at": utcnow().isoformat(timespec="seconds"), "checks": results},
                         indent=1, default=str))
    else:
        print(f"LPT RECONCILIATION — {utcnow().isoformat(timespec='seconds')}")
        for r in results:
            if args.quiet and r["ok"]:
                continue
            v = r["value"]
            if isinstance(v, float):
                vs = f"{v:,.2f}"
            elif isinstance(v, int):
                vs = f"{v:,}"
            else:
                vs = "-" if v is None else str(v)
            mark = "OK  " if r["ok"] else ("????" if r["error"] else "FAIL")
            chg = f"  (was {r['changed_from']})" if "changed_from" in r else ""
            print(f"{mark} {r['name']:<30} {vs:>14} {r['unit']:<4} {r['says']}{chg}")
            if r["prov"]:
                print(f"     {'':<30} {'':>14}      {r['prov']}")
            if r["error"]:
                print(f"     {'':<30} {'':>14}      {r['error']}")

    fails = [r for r in results if not r["ok"] and not r["error"]]
    errs = [r for r in results if r["error"]]
    # The human summary must NOT print in --json mode: it would append a second
    # document after the JSON and break every consumer. Found by running it.
    if not args.json:
        print(f"\n{len(results) - len(fails) - len(errs)} ok · {len(fails)} FAIL · {len(errs)} could not measure")
    if errs:
        return 2
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
