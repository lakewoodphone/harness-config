#!/usr/bin/env python3
"""website-comms-push.py — give the production website a clock.

WHY THIS EXISTS (axis G, 2026-09-15)
    The production website's customer-message history stopped at 2026-09-15T11:34:24.649Z and
    stayed stopped for 11.5 hours, unnoticed, because the writer has NO SCHEDULE:

        sync_dialpad_calls_to_website / sync_dialpad_sms_to_website (app/services/website_db.py)
        are called only from app/services/daily_reconciliation.py:1582/:1591, which runs only when
        app/autopilot.py:_maybe_check_comms_freshness() decides dialpad_sms is stale - behind a 24 h
        per-source alert backoff and reconciliation_interval_hours=24. Both triggers were spent, so
        nothing ran. The only Dialpad cron harvests into secretary.db and never touches the website.

    Worse, the staleness check that gates it reads `MAX(dialpad_sms_cache.fetched_at)` - the LOCAL
    receive clock, which the live webhook keeps fresh - so it reported healthy while the website
    received nothing. The watchdog was watching the wrong clock.

WHAT THIS DOES
    Runs exactly the two existing, idempotent functions with exactly the windows and limits the
    reconciliation uses (`_get_dialpad_calls_for_push`: 7 days / 500; `_get_dialpad_sms_for_push`:
    7 days / 1000). It invents no matching logic and writes no SQL of its own: the dedup, the
    customer match and the `external_ref` guard are the application's own.

    This is a REPORTER + a clock. It sends nothing outbound (no SMS, no email) - it inserts rows into
    the website's own `communications` table, which is the customer-facing record of record.

PCI EXCLUSION - deliberately withheld, for the owner to decide (queue item 67)
    `dialpad_sms_cache` message_id 6252044111880192 carries a full card number, expiry, CVV and ZIP.
    Axis G flagged it, and the owner has been asked how to handle it. Until he answers it is NOT
    copied into production by this script. Everything else in the window is pushed. Pass
    --include-pci to override, and only do that once he has answered.

USAGE
    python3 website-comms-push.py --dry-run     # count candidates, write nothing
    python3 website-comms-push.py               # push
    python3 website-comms-push.py --json        # machine-readable result

EXIT    0 pushed (or nothing to do) · 1 a sync reported not-ok · 2 could not even build the payload
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/zabz/personal-secretary-mvp")

# The message the owner has not ruled on yet. Not a secret-scanner guess: axis G read it.
PCI_HOLD_MESSAGE_IDS = {"6252044111880192"}

ENV_FILE = "/home/zabz/personal-secretary-mvp/.env"


def dsn_from_env_file() -> str:
    """Read the DSN straight from .env by ABSOLUTE path.

    Why this exists: the first cron-triggered run of the wrapper failed with
    "no PHONE_TECH_FULL_* DSN available" purely because the wrapper did not `cd` into the repo
    first, and `app.config` loads `.env` relative to the working directory. A tool that works
    interactively and fails under cron because of an unstated cwd dependency is a trap - the same
    class as a job that dies quietly. Reading the file by absolute path removes the dependency
    instead of documenting it.
    """
    try:
        with open(ENV_FILE, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k in ("PHONE_TECH_FULL_DIRECT_URL", "PHONE_TECH_FULL_DATABASE_URL"):
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
    except OSError:
        pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--include-pci", action="store_true",
                    help="push the withheld message too (only after the owner answers queue 67)")
    args = ap.parse_args()

    from app.config import settings
    from app.services.daily_reconciliation import (
        _get_dialpad_calls_for_push,
        _get_dialpad_sms_for_push,
    )
    from app.services.website_db import (
        sync_dialpad_calls_to_website,
        sync_dialpad_sms_to_website,
    )

    pg_url = (os.environ.get("PHONE_TECH_FULL_DIRECT_URL")
              or os.environ.get("PHONE_TECH_FULL_DATABASE_URL")
              or getattr(settings, "phone_tech_full_database_url", None)
              or dsn_from_env_file()
              or "")
    result: dict = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "pg_url_present": bool(pg_url)}
    if not pg_url:
        result["error"] = "no PHONE_TECH_FULL_* DSN available; cannot reach production"
        print(json.dumps(result, indent=1), file=sys.stderr)
        return 2

    try:
        calls = _get_dialpad_calls_for_push(settings)
        sms = _get_dialpad_sms_for_push(settings)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"payload build failed: {type(exc).__name__}: {exc}"
        print(json.dumps(result, indent=1), file=sys.stderr)
        return 2

    held = []
    if not args.include_pci:
        kept = []
        for m in sms:
            if str(m.get("message_id") or "") in PCI_HOLD_MESSAGE_IDS:
                held.append(m.get("message_id"))
            else:
                kept.append(m)
        sms = kept

    result["candidates"] = {"calls": len(calls), "sms": len(sms)}
    result["withheld_pci"] = held
    result["window"] = "calls: 7d/500, sms: 7d/1000 (the reconciliation's own getters)"

    if args.dry_run:
        result["dry_run"] = True
        print(json.dumps(result, indent=1))
        return 0

    try:
        result["calls"] = sync_dialpad_calls_to_website(
            pg_url=pg_url, secretary_db_url=settings.database_url, calls=calls)
    except Exception as exc:  # noqa: BLE001
        result["calls"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        result["sms"] = sync_dialpad_sms_to_website(
            pg_url=pg_url, secretary_db_url=settings.database_url, sms_messages=sms)
    except Exception as exc:  # noqa: BLE001
        result["sms"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    ok = bool((result.get("calls") or {}).get("ok")) and bool((result.get("sms") or {}).get("ok"))
    result["ok"] = ok

    if args.json:
        print(json.dumps(result, indent=1, default=str))
    else:
        c, s = result.get("calls") or {}, result.get("sms") or {}
        print(f"calls : synced={c.get('synced')} errors={c.get('errors')} "
              f"skipped_dedup={c.get('skipped_dedup')} {c.get('error') or ''}")
        print(f"sms   : synced={s.get('synced')} errors={s.get('errors')} "
              f"skipped_dedup={s.get('skipped_dedup')} {s.get('error') or ''}")
        if held:
            print(f"WITHHELD (awaiting the owner, queue 67): {held}")
        print("ok" if ok else "NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
