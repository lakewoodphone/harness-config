#!/usr/bin/env python3
"""plaid-freshness -- a wake source: the nightly money pull must not go quiet unnoticed.

WHY (journal pain P2926 part 1; housekeeping item 231)
  Measured 2026-09-30: 6 of the last 8 nightly Plaid runs failed and NOTHING alerted.
  plaid-freshness-guard.py already judges ~/.plaid-sync-status.json (FRESH / STALE /
  FAILED / UNVERIFIABLE) but nothing invoked it, so a dead pull stayed silent. This
  turns the guard's verdict into a wake flag: only a process that KNOWS there is work
  may raise a flag, and a money pull that has been dead past its ceiling is work.

CONTRACT (same as every source in this directory)
  quiet            -> nothing to file
  any other stdout -> a flag was filed (or deduped); run-wake-sources.sh logs the line
  exit 0 always    -> a source that breaks its caller is worse than no source.

Read-only apart from the single flag it files. It never runs the pull and never sends
anything to a human.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
GUARD = HOME / "bin" / "plaid-freshness-guard.py"
WAKE = HOME / "bin" / "wake.py"
SUBJECT = "plaid-pull-not-fresh"
SUBJECT_COVERAGE = "plaid-account-missing"
LEDGER = "/root/accounting-data/live/accounting.db"
# The work ledger (ledger item 449). A coverage condition an OPEN work_item already
# tracks must not be refiled every 1800 s: the flag is real, but no shift can act on
# it until the tracking item moves, so every release only re-derives the same
# blocked report and spends a shift's budget on it.
WORK_DB = os.environ.get("WORK_DB") or str(HOME / "work" / "work.db")
OPEN_STATES = ("todo", "running", "blocked")
# A plaid-api account absent this many days while the pull itself is fresh is a DROPPED
# ACCOUNT, not a quiet one. Measured 2026-10-16: 17/day -> 16 on 2026-09-08 -> 15 on
# 2026-09-28, with ok=true the whole time.
COVERAGE_DAYS = 3


def run_guard(guard, status_file=None, now=None, ceiling=None):
    cmd = ["/usr/bin/python3", str(guard), "--json"]
    if status_file:
        cmd += ["--status-file", status_file]
    if now:
        cmd += ["--now", now]
    if ceiling:
        cmd += ["--max-age-hours", str(ceiling)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "UNVERIFIABLE",
                "reason": "guard did not run: %s: %s" % (type(exc).__name__, exc)}
    try:
        return json.loads(proc.stdout)
    except Exception:  # noqa: BLE001
        return {"verdict": "UNVERIFIABLE",
                "reason": "guard produced no parsable JSON (rc=%s): %s"
                          % (proc.returncode, (proc.stderr or "").strip()[:200])}


def build_prompt(verdict, reason):
    return ("The nightly Plaid money pull is not fresh: %s - %s. (journal pain P2926 "
            "part 1). Read ~/.plaid-sync-status.json and the nightly-plaid-sync log, fix "
            "the pull against the DEPLOYED tree, and confirm the next run writes ok=true. "
            "Reproduce with: python3 %s --json "
            "(36h ceiling)." % (verdict, reason, GUARD))


def retired_accounts(ledger):
    """Accounting account ids the books no longer treat as live.

    A closed/archived account cannot report a Plaid balance, so its silence is expected,
    not a coverage failure. `accounts.status` is the books' own statement of whether an
    account is still live; `archived` is the established value for a retired account.

    Returns an EMPTY SET when the accounts table is absent or unreadable: a coverage guard
    that cannot see the books must fail OPEN, not silently mute a dropped account.
    """
    if not os.path.exists(ledger):
        return set()
    try:
        con = sqlite3.connect("file:%s?mode=ro" % ledger, uri=True)
        try:
            rows = con.execute(
                "select id from accounts where coalesce(status,'active') != 'active'"
            ).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return set()
    return {r[0] for r in rows}


def account_coverage(ledger, days, now=None):
    """Accounts with a plaid-api history that have not reported inside `days`.

    Returns [] when the ledger is unreadable or has no plaid-api history at all, because a
    coverage check that cannot see its own baseline must not raise a flag it cannot support.
    """
    if not os.path.exists(ledger):
        return []
    today = (now or datetime.datetime.now(datetime.timezone.utc)).date()
    try:
        con = sqlite3.connect("file:%s?mode=ro" % ledger, uri=True)
        rows = con.execute(
            "select account_id, max(substr(captured_at,1,10)) last_day, count(*) n"
            " from balance_snapshots where source='plaid-api' group by 1").fetchall()
        con.close()
    except Exception:  # noqa: BLE001
        return []
    out = []
    if not rows:
        return []
    retired = retired_accounts(ledger)
    for account_id, last_day, n in rows:
        if account_id in retired:
            continue
        try:
            last = datetime.date.fromisoformat(last_day)
        except Exception:  # noqa: BLE001
            continue
        missing = (today - last).days
        if missing > days:
            out.append({"account_id": account_id, "last_day": last_day,
                        "days_missing": missing, "readings": n})
    return sorted(out, key=lambda r: -r["days_missing"])


def coverage_prompt(missing, days):
    names = ", ".join("%s (last %s, %dd)" % (m["account_id"], m["last_day"], m["days_missing"])
                      for m in missing[:6])
    return ("Plaid is returning fewer accounts than its own history: %d account(s) have not "
            "reported inside %d days while the pull itself looks fresh - %s. A money feed that "
            "silently stops returning an account reads healthy on every other check here "
            "(~/.plaid-sync-status.json says ok=true). Check the Plaid Item for each account: a "
            "re-auth, a closed account, or an account removed from the Item. Reproduce with: "
            "python3 /root/bin/sources/plaid-freshness.py --dry-run"
            % (len(missing), days, names))


def open_ledger_items(db, states=OPEN_STATES):
    """Open work_item rows that may already be tracking a coverage condition.

    Returns [] if the ledger is unreadable, so a guard that cannot see the ledger fails
    OPEN - it files the flag. Muting a real dropped account is worse than a repeat.
    """
    if not db or not os.path.exists(str(db)):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        con.row_factory = sqlite3.Row
        marks = ",".join("?" * len(states))
        rows = con.execute(
            "select id, state, project, title, coalesce(why,'') as why from work_item"
            " where state in (%s)" % marks, tuple(states)).fetchall()
        con.close()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def _account_tokens(account_id):
    """The strings that name an account in ledger prose: the id, and its mask suffix."""
    toks = [account_id]
    tail = account_id.rsplit("-", 1)[-1]
    if len(tail) >= 4 and tail.isdigit():
        toks.append(tail)
    return toks


def coverage_tracking(missing, items):
    """Map each missing account to the open ledger item ids whose text names it.

    The mask suffix is matched as a whole number because the ledger writes "Chase 4673",
    not the balance_snapshots key "personal-self-directed-4673".
    """
    track = {}
    for m in missing:
        acct = m["account_id"]
        ids = []
        for it in items:
            blob = ("%s %s" % (it.get("title") or "", it.get("why") or "")).lower()
            for tok in _account_tokens(acct):
                tok = tok.lower()
                if tok.isdigit():
                    hit = re.search(r"(?<!\d)%s(?!\d)" % re.escape(tok), blob) is not None
                else:
                    hit = tok in blob
                if hit:
                    ids.append(it["id"])
                    break
        track[acct] = ids
    return track


def coverage_suppression(missing, items):
    """(suppressed, tracked_item_ids).

    Suppress ONLY when EVERY missing account is named by an open work_item. One new
    dropped account that nothing tracks keeps the whole flag, so this cannot mute a
    first alert for a newly dropped account.
    """
    track = coverage_tracking(missing, items)
    if any(not ids for ids in track.values()):
        return False, []
    return True, sorted({i for ids in track.values() for i in ids})


def file_coverage_flag(wake, prompt):
    proc = subprocess.run(
        ["/usr/bin/python3", str(wake), "flag",
         "--subject", SUBJECT_COVERAGE, "--prompt", prompt,
         "--kind", "plaid-coverage", "--source", "plaid-freshness", "--priority", "high"],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def file_flag(wake, prompt):
    proc = subprocess.run(
        ["/usr/bin/python3", str(wake), "flag",
         "--subject", SUBJECT, "--prompt", prompt,
         "--kind", "plaid-stale", "--source", "plaid-freshness", "--priority", "high"],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def selftest(args):
    now = "2026-10-09T16:00:00+00:00"
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        def write(name, obj):
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(obj, handle)
            return path
        cases.append(("fresh", write("fresh.json",
                     {"at": "2026-10-09T12:00:00+00:00", "ok": True}), "quiet"))
        cases.append(("stale", write("stale.json",
                     {"at": "2026-10-08T00:00:00+00:00", "ok": True}), "WOULD-FILE"))
        cases.append(("failed", write("failed.json",
                     {"at": "2026-10-09T12:00:00+00:00", "ok": False,
                      "failed_steps": ["plaid"]}), "WOULD-FILE"))
        cases.append(("absent", os.path.join(tmp, "nope.json"), "WOULD-FILE"))
        # coverage: a temp ledger with one account reporting today and one 40 days silent
        cdb = os.path.join(tmp, "cov.db")
        con = sqlite3.connect(cdb)
        con.execute("create table balance_snapshots (account_id text, source text, captured_at text)")
        today = datetime.datetime.fromisoformat(now)
        con.execute("insert into balance_snapshots values (?,?,?)",
                    ("acct-fresh", "plaid-api", today.isoformat()))
        con.execute("insert into balance_snapshots values (?,?,?)",
                    ("acct-fresh", "plaid-api", (today - datetime.timedelta(days=1)).isoformat()))
        con.execute("insert into balance_snapshots values (?,?,?)",
                    ("acct-dropped", "plaid-api", (today - datetime.timedelta(days=40)).isoformat()))
        # The books say which accounts are still live. An archived account's silence is
        # expected; a dropped account that is still active is the failure.
        con.execute("create table accounts (id text primary key, status text)")
        for aid, status in (("acct-fresh", "active"), ("acct-dropped", "active"),
                            ("acct-retired", "archived")):
            con.execute("insert into accounts values (?,?)", (aid, status))
        con.execute("insert into balance_snapshots values (?,?,?)",
                    ("acct-retired", "plaid-api", (today - datetime.timedelta(days=40)).isoformat()))
        con.commit(); con.close()
        cov = account_coverage(cdb, 3, today)
        cases.append(("cov-finds", None, "WOULD-FILE"))
        failures = 0
        if [c["account_id"] for c in cov] != ["acct-dropped"]:
            failures += 1
            print("  %-7s expect=%-11s got=%-11s %s" % ("cov-finds", "['acct-dropped']",
                                                        [c["account_id"] for c in cov], "FAIL"))
        else:
            print("  %-7s expect=%-11s got=%-11s %s" % ("cov-finds", "['acct-dropped']",
                                                        [c["account_id"] for c in cov], "ok"))
        cov_ids = [c["account_id"] for c in cov]
        retired_seen = "acct-retired" in cov_ids
        if retired_seen:
            failures += 1
        print("  %-10s expect=%-11s got=%-11s %s"
              % ("cov-retired", "skipped", "FLAGGED" if retired_seen else "skipped",
                 "FAIL" if retired_seen else "ok"))
        # Fail-open: an older ledger with no accounts table must still flag its silence.
        legacy = os.path.join(tmp, "legacy.db")
        con = sqlite3.connect(legacy)
        con.execute("create table balance_snapshots (account_id text, source text, captured_at text)")
        con.execute("insert into balance_snapshots values (?,?,?)",
                    ("acct-dropped", "plaid-api", (today - datetime.timedelta(days=40)).isoformat()))
        con.commit(); con.close()
        legacy_ids = [c["account_id"] for c in account_coverage(legacy, 3, today)]
        legacy_ok = legacy_ids == ["acct-dropped"]
        if not legacy_ok:
            failures += 1
        print("  %-10s expect=%-11s got=%-11s %s"
              % ("cov-no-table", "['acct-dropped']", legacy_ids,
                 "ok" if legacy_ok else "FAIL"))
        empty = account_coverage(os.path.join(tmp, "absent.db"), 3, today)
        if empty != []:
            failures += 1
            print("  %-7s expect=[] got=%s FAIL" % ("cov-no-baseline", empty))
        else:
            print("  %-7s expect=[] got=[] ok" % ("cov-no-baseline",))
        for name, path, expect in [c for c in cases if c[1] is not None]:
            verdict = run_guard(args.guard, path, now, None)
            got = "quiet" if verdict.get("verdict") == "FRESH" else "WOULD-FILE"
            ok = got == expect
            failures += 0 if ok else 1
            print("  %-7s expect=%-11s got=%-11s verdict=%-13s %s"
                  % (name, expect, got, verdict.get("verdict"), "ok" if ok else "FAIL"))
        # item 449: an OPEN work_item that already names the dropped accounts must stop
        # the refile; a NEW dropped account nothing names must still file.
        ldb = os.path.join(tmp, "ledger.db")
        con = sqlite3.connect(ldb)
        con.execute("create table work_item (id integer primary key, project text,"
                    " title text, why text, state text)")
        con.execute("insert into work_item values (424,'cfo',"
                    "'Chase accounts 4673 and 8512: apply the owner decision',"
                    "'item AXBkO6Vo no longer returns mask 4673 or mask 8512','blocked')")
        con.execute("insert into work_item values (393,'cfo',"
                    "'Plaid Item no longer returns card *8512 or Self-Directed *4673',"
                    "'diagnosed, done','done')")
        con.commit(); con.close()
        planted = [{"account_id": "personal-chase-8512", "days_missing": 21},
                   {"account_id": "personal-self-directed-4673", "days_missing": 39}]
        items = open_ledger_items(ldb)
        sup, ids = coverage_suppression(planted, items)
        if sup and ids == [424]:
            print("  %-13s expect=%-13s got=%-13s %s"
                  % ("cov-tracked", "suppressed@424", "suppressed@%s" % ids, "ok"))
        else:
            failures += 1
            print("  %-13s expect=%-13s got=%-13s FAIL"
                  % ("cov-tracked", "suppressed@424", (sup, ids)))
        sup2, ids2 = coverage_suppression(
            planted + [{"account_id": "personal-newbank-9999", "days_missing": 5}], items)
        if not sup2:
            print("  %-13s expect=%-13s got=%-13s %s"
                  % ("cov-newdrop", "WOULD-FILE", "WOULD-FILE", "ok"))
        else:
            failures += 1
            print("  %-13s expect=%-13s got=%-13s FAIL"
                  % ("cov-newdrop", "WOULD-FILE", (sup2, ids2)))
        con = sqlite3.connect(ldb)
        con.execute("update work_item set state='done'")
        con.commit(); con.close()
        sup3, ids3 = coverage_suppression(planted, open_ledger_items(ldb))
        if not sup3:
            print("  %-13s expect=%-13s got=%-13s %s"
                  % ("cov-closed", "WOULD-FILE", "WOULD-FILE", "ok"))
        else:
            failures += 1
            print("  %-13s expect=%-13s got=%-13s FAIL"
                  % ("cov-closed", "WOULD-FILE", (sup3, ids3)))
    print("SELFTEST %s (%d failure(s))" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status-file")
    parser.add_argument("--now")
    parser.add_argument("--max-age-hours", type=float)
    parser.add_argument("--guard", default=str(GUARD))
    parser.add_argument("--wake", default=str(WAKE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--ledger", default=LEDGER)
    parser.add_argument("--ledger-db", default=WORK_DB)
    parser.add_argument("--coverage-days", type=int, default=COVERAGE_DAYS)
    parser.add_argument("--skip-coverage", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args)

    verdict = run_guard(args.guard, args.status_file, args.now, args.max_age_hours)
    fresh = verdict.get("verdict") == "FRESH"
    filed = 0
    noted = False

    if not fresh:
        prompt = build_prompt(verdict.get("verdict"), verdict.get("reason"))
        if args.dry_run:
            print("WOULD-FILE %s: %s" % (SUBJECT, verdict.get("reason")))
        else:
            rc, out, err = file_flag(args.wake, prompt)
            first = out.splitlines()[0] if out else ""
            print("plaid-freshness %s verdict=%s rc=%s %s"
                  % ("flagged" if rc == 0 else "flag-failed",
                     verdict.get("verdict"), rc, (first or err[:160])))
        filed += 1

    # COVERAGE: independent of freshness. A pull can be perfectly fresh and still be missing
    # accounts; that is the failure this source could not see until 2026-10-16.
    missing = [] if args.skip_coverage else account_coverage(
        args.ledger, args.coverage_days, _parse_now(args.now))
    if missing:
        prompt = coverage_prompt(missing, args.coverage_days)
        summary = "; ".join("%s(%dd)" % (m["account_id"], m["days_missing"]) for m in missing[:4])
        # Noise guard (ledger item 449): if an OPEN work_item already names every dropped
        # account, a shift is already on it and refiling can only produce a no-op report.
        suppressed, tracked = coverage_suppression(missing, open_ledger_items(args.ledger_db))
        if suppressed:
            noted = True
            print("suppressed:already-tracked-in-ledger %s tracked-by item %s"
                  % (summary, ",".join(str(i) for i in tracked)))
        elif args.dry_run:
            print("WOULD-FILE %s: %d account(s) not reporting - %s"
                  % (SUBJECT_COVERAGE, len(missing), summary))
            filed += 1
        else:
            rc, out, err = file_coverage_flag(args.wake, prompt)
            first = out.splitlines()[0] if out else ""
            print("plaid-freshness %s subject=%s rc=%s %s"
                  % ("flagged" if rc == 0 else "flag-failed", SUBJECT_COVERAGE, rc,
                     (first or err[:160])))
            filed += 1

    if filed == 0 and not noted:
        print("quiet")
    return 0


def _parse_now(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    raise SystemExit(main())
