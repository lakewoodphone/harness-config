#!/usr/bin/env python3
"""plaid-item-check.py -- did Plaid stop returning an account, and is it OUR fault?

WHY (wake #1125, subject `plaid-account-missing`, 2026-10-16)
  The `plaid-freshness` source can now see that a Plaid account has stopped
  reporting into accounting.db `balance_snapshots` while the pull itself is
  FRESH. What it cannot say -- and what a shift then has to re-derive by hand --
  is WHICH of three things happened:

    REAUTH                  the Item needs the owner to re-authenticate
                            (Plaid returns item.error, e.g. ITEM_LOGIN_REQUIRED)
    DROPPED                 the Item is healthy and authenticates, but Plaid no
                            longer returns this account's mask in /accounts/get
                            -- the account was closed at the bank or removed from
                            the Item. Nothing in this estate removes a single
                            account, so this is a bank-side change.
    PRESENT-NOT-REPORTING   Plaid STILL returns the account mask, but no balance
                            has landed in the books -- an ingest fault on ours.

  Those three need three different responses, and telling them apart by hand took
  a live Plaid API call and two DB reads. This is that check, made repeatable.

  Accounts are keyed by MASK, not by Plaid's account_id: Plaid's account_id
  changes whenever the row is re-upserted, while the accounting link
  (PLAID_MASK_MAP in app/services/plaid_ledger_ingest.py) is by mask.

READ-ONLY. It never writes a database, never links, never removes, never sends.
It reads credentials from /opt/company/.env and calls only `item/get` and
`accounts/get`.

USAGE
  plaid-item-check.py --account personal-chase-8512 --account personal-self-directed-4673
  plaid-item-check.py --all            # every mapped account with a plaid-api history
  plaid-item-check.py --all --json

EXIT
  0  every checked account is PRESENT and current
  1  this job itself failed (unreadable store, no Plaid client)
  3  CONDITION: at least one account is REAUTH, DROPPED, or PRESENT-NOT-REPORTING
     (3 is this estate's word for a condition a checker correctly reports)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

ENV = "/opt/company/.env"
APP_DIR = "/opt/company"
ACCOUNTING = "/root/accounting-data/live/accounting.db"
PLAID_DB = "/root/authority.db"
DEFAULT_DAYS = 3

REAUTH = "REAUTH"
DROPPED = "DROPPED"
PRESENT = "PRESENT"
PRESENT_SILENT = "PRESENT-NOT-REPORTING"
UNMAPPED = "NO-PLAID-MASK"


def classify(present: bool, item_error, missing_days, days) -> str:
    """The whole decision, pure: one account -> one verdict.

    A REAUTH outranks everything: if the Item is broken we cannot trust its
    account list at all. PRESENT-NOT-REPORTING is our fault; DROPPED is not.
    """
    if item_error:
        return REAUTH
    if not present:
        return DROPPED
    if missing_days is not None and missing_days > days:
        return PRESENT_SILENT
    return PRESENT


def last_snapshot_days(conn, account_id, today) -> int | None:
    row = conn.execute(
        "select max(substr(captured_at,1,10)) from balance_snapshots"
        " where source='plaid-api' and account_id=?", (account_id,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        return (today - dt.date.fromisoformat(row[0])).days
    except ValueError:
        return None


def accounts_with_history(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "select distinct account_id from balance_snapshots"
        " where source='plaid-api' order by 1")]


def _app_imports():
    # app.config reads .env relative to the CWD (SettingsConfigDict(env_file=".env")),
    # so the app dir must be the CWD before the settings module is imported. Without
    # this the tool worked only when launched from /opt/company and refused with
    # "Plaid not configured" from anywhere else.
    if os.path.isdir(APP_DIR):
        os.chdir(APP_DIR)
    sys.path.insert(0, APP_DIR)
    from app.services.plaid_ledger_ingest import PLAID_MASK_MAP
    return PLAID_MASK_MAP


def mask_by_accounting_id() -> dict[str, str]:
    out: dict[str, str] = {}
    for mask, (acct, _entity, _kw) in _app_imports().items():
        out.setdefault(acct, mask)
    return out


def plaid_snapshot() -> tuple[dict, list[dict], dict]:
    """-> (item_by_db_id, live_accounts, item_error_by_db_id). Read-only."""
    _app_imports()
    from app.services.plaid_service import _get_client
    from plaid.model.accounts_get_request import AccountsGetRequest
    from plaid.model.item_get_request import ItemGetRequest
    import plaid

    con = sqlite3.connect("file:%s?mode=ro" % PLAID_DB, uri=True)
    con.row_factory = sqlite3.Row
    items = {r["id"]: dict(r) for r in con.execute(
        "select id,item_id,institution_name,access_token,status"
        " from plaid_items order by id")}
    con.close()

    client = _get_client()
    live: list[dict] = []
    errors: dict[int, object] = {}
    for db_id, it in items.items():
        if it["status"] != "active":
            continue
        err = None
        try:
            item = client.item_get(ItemGetRequest(access_token=it["access_token"])).item
            err = getattr(item, "error", None)
        except plaid.ApiException as exc:
            err = str(exc)[:200]
        except Exception as exc:  # noqa: BLE001
            err = "%s: %s" % (type(exc).__name__, exc)
        errors[db_id] = err
        if err:
            continue
        try:
            for a in client.accounts_get(AccountsGetRequest(access_token=it["access_token"])).accounts:
                live.append({"mask": a.mask or "", "plaid_account_id": a.account_id,
                             "item_db_id": db_id, "name": a.name})
        except Exception as exc:  # noqa: BLE001
            errors[db_id] = "%s: %s" % (type(exc).__name__, exc)
    return items, live, errors


def last_item_for_mask(plaid_db, mask):
    con = sqlite3.connect("file:%s?mode=ro" % plaid_db, uri=True)
    row = con.execute("select plaid_item_id from plaid_accounts where mask=?"
                      " order by id desc limit 1", (mask,)).fetchone()
    con.close()
    return row[0] if row else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="is a Plaid account still on its Item?")
    ap.add_argument("--account", action="append", default=[],
                    help="accounting account_id (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="check every account with a plaid-api balance history")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help="a present account with no reading inside this many days "
                         "is PRESENT-NOT-REPORTING (default 3)")
    ap.add_argument("--accounting", default=ACCOUNTING)
    ap.add_argument("--plaid-db", default=PLAID_DB)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        cases = [
            (True, None, 0, PRESENT),
            (True, None, 10, PRESENT_SILENT),
            (False, None, 39, DROPPED),
            (False, "ITEM_LOGIN_REQUIRED", 0, REAUTH),
            (True, "ITEM_LOGIN_REQUIRED", 0, REAUTH),
        ]
        bad = 0
        for present, err, missing, want in cases:
            got = classify(present, err, missing, 3)
            ok = got == want
            bad += 0 if ok else 1
            print("  classify present=%-5s err=%-20r missing=%-3s -> %-22s %s"
                  % (present, err, missing, got, "ok" if ok else "FAIL want " + want))
        print("SELFTEST %s (%d failure(s))" % ("PASS" if bad == 0 else "FAIL", bad))
        return 0 if bad == 0 else 1

    today = dt.datetime.now(dt.timezone.utc).date()
    acc = sqlite3.connect("file:%s?mode=ro" % args.accounting, uri=True)
    try:
        masks = mask_by_accounting_id()
    except Exception as exc:  # noqa: BLE001
        print("plaid-item-check: cannot load PLAID_MASK_MAP: %s: %s"
              % (type(exc).__name__, exc), file=sys.stderr)
        return 1

    wanted = list(args.account)
    if args.all or not wanted:
        wanted = accounts_with_history(acc)

    try:
        items, live, errors = plaid_snapshot()
    except Exception as exc:  # noqa: BLE001
        print("plaid-item-check: cannot ask Plaid: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 1

    out, worst = [], 0
    for acct in wanted:
        mask = masks.get(acct)
        missing = last_snapshot_days(acc, acct, today)
        if mask is None:
            out.append({"account": acct, "verdict": UNMAPPED, "mask": None,
                        "item_db_id": None, "item_id": None, "institution": "",
                        "item_error": None, "in_plaid_account_list": None,
                        "last_plaid_api_reading": None if missing is None else
                            (today - dt.timedelta(days=missing)).isoformat(),
                        "days_since_reading": missing})
            continue
        matches = [a for a in live if a["mask"] == mask]
        present = bool(matches)
        if present:
            item_db = matches[0]["item_db_id"]
        else:
            item_db = last_item_for_mask(args.plaid_db, mask)
        it = items.get(item_db) or {}
        err = errors.get(item_db)
        verdict = classify(present, err, missing, args.days)
        if verdict != PRESENT:
            worst = 3
        out.append({
            "account": acct, "verdict": verdict, "mask": mask,
            "item_db_id": item_db, "item_id": it.get("item_id"),
            "institution": it.get("institution_name") or "",
            "item_error": err, "in_plaid_account_list": present,
            "last_plaid_api_reading": None if missing is None else
                (today - dt.timedelta(days=missing)).isoformat(),
            "days_since_reading": missing,
        })

    if args.json:
        print(json.dumps({"check": "plaid-item", "exit": worst, "results": out}, sort_keys=True))
    else:
        print("%-32s %-6s %-22s %-9s %-14s %-12s %s" % (
            "account", "mask", "item", "in_plaid", "item_error", "last_read", "verdict"))
        for r in out:
            print("%-32s %-6s %-22s %-9s %-14s %-12s %s" % (
                r["account"], r["mask"] or "-", r["item_id"] or "-",
                "yes" if r["in_plaid_account_list"] else "ABSENT",
                (r["item_error"] or "None")[:14],
                r["last_plaid_api_reading"] or "-", r["verdict"]))
        if worst:
            print("\nCONDITION: one or more accounts are not being returned by a healthy"
                  " Plaid Item. DROPPED = bank-side (closed or removed from the Item);"
                  " REAUTH = the owner must re-link; PRESENT-NOT-REPORTING = our ingest.")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
