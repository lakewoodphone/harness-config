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
    Runs exactly the three existing, idempotent functions with exactly the windows and limits the
    reconciliation uses (`_get_dialpad_calls_for_push`: 7 days / 500; `_get_dialpad_sms_for_push`:
    7 days / 1000; `_get_dialpad_voicemails_for_push`: 7 days / 500). It invents no matching
    logic and writes no SQL of its own: the dedup, the customer match and the `external_ref`
    guard are the application's own.

VOICEMAILS (gap A4, added 2026-09-16) - and the duplicate this clock must not create
    `sync_dialpad_voicemails_to_website` had no caller anywhere in the tree, so no row with
    `external_ref LIKE 'dialpad:voicemail:%'` has ever reached the website. It is wired in here
    as a third block.

    But voicemails are ALREADY on the website: `sync_dialpad_calls_to_website` does not filter
    them out of `dialpad_call_full`, and `_build_call_body` appends a `[Voicemail]:` section,
    so every voicemail is stored as `dialpad:call:<call_id>`. Measured 2026-09-16: 24 of 24
    in-window voicemails present as call rows, all 24 carrying `[Voicemail]` in the content.
    Neither sync function can see the other's ref, so a naive wiring would insert a SECOND row
    per voicemail - the A2/A3 duplicate class, on the surface customers read.

    So this clock only passes voicemails the website does not already hold under EITHER ref
    (`_voicemails_not_yet_on_website`), and the vm_id it sends is the Dialpad `call_id`, so the
    voicemail row and the call row share one identity. A run reporting `voicemails synced 0`
    while `already-on-website` is non-zero is the guard working, not the push failing.

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


def _get_dialpad_voicemails_for_push(settings) -> list[dict]:
    """Fetch recent Dialpad voicemails to push to the website. Added 2026-09-16 (gap A4).

    THE SOURCE TABLE, AND WHY IT IS NOT `dialpad_ui_voicemail_row`
        That table's columns match `sync_dialpad_voicemails_to_website`'s input contract exactly, so
        it looks like the obvious source - and it is dead. Measured 2026-09-16: 3,036 rows, newest
        `captured_at` 2026-06-14T15:56Z, **0 rows in the last 7 days**. Pulling from it would give a
        clock that reports a healthy `synced: 0` forever.

        The live voicemail lineage is `dialpad_call_full`: a voicemail is a call row carrying a
        `voicemail_link`. Measured 2026-09-16: 921 rows all-time have a non-empty `voicemail_link`
        (matching axis G's 916), 24 of them inside this 7-day window.

    `vm_id` IS THE DIALPAD `call_id`, DELIBERATELY
        `sync_dialpad_calls_to_website` has already stored these same voicemails as
        `dialpad:call:<call_id>` - it selects all of `dialpad_call_full` and `_build_call_body`
        appends a `[Voicemail]:` section. Giving the voicemail row the same id makes
        `dialpad:voicemail:<call_id>` an identity a human can line up with the call row, and lets the
        caller's duplicate guard see that both refs describe one voicemail. Using
        `voicemail_recording_id` would dedup against nothing and double-report every voicemail.

    Window and order match the other two getters (7 days), so all three blocks describe one window.
    """
    from app.database import _get_conn

    conn = _get_conn(settings.database_url)
    try:
        cutoff_ms = int(__import__("time").time() * 1000) - 7 * 86400 * 1000
        rows = conn.execute(
            "SELECT call_id, direction, contact_phone, external_number, contact_name, "
            "duration_seconds, transcription_text, voicemail_link, voicemail_recording_id "
            "FROM dialpad_call_full "
            "WHERE date_started_ms > ? "
            "AND (COALESCE(voicemail_link, '') <> '' "
            "OR COALESCE(voicemail_recording_id, '') <> '') "
            "ORDER BY date_started_ms DESC LIMIT 500",
            (cutoff_ms,),
        ).fetchall()
    except Exception:
        return []

    out: list[dict] = []
    for row in rows:
        r = dict(row)
        out.append({
            "vm_id": r.get("call_id"),
            "ccall_id": r.get("call_id"),
            "phone_number": r.get("contact_phone") or r.get("external_number") or "",
            "direction": r.get("direction") or "inbound",
            "duration_seconds": r.get("duration_seconds") or 0,
            "transcript": r.get("transcription_text") or "",
            "recording_url": r.get("voicemail_link") or "",
            "contact_name": r.get("contact_name") or "",
        })
    return out


def _voicemails_not_yet_on_website(pg_url: str, voicemails: list[dict]) -> tuple[list[dict], int]:
    """Drop voicemails the website already holds, under EITHER ref.

    `sync_dialpad_calls_to_website` stores every `dialpad_call_full` row - voicemails included - as
    `dialpad:call:<call_id>`, and `sync_dialpad_voicemails_to_website` stores as
    `dialpad:voicemail:<vm_id>`. Those are two refs for one voicemail, and neither sync can see the
    other's, so without this guard the clock would add a second visible row for every voicemail the
    call path already delivered - 24 of 24 in the window measured on 2026-09-16.

    Checking both refs also makes the clock order-independent: a voicemail row that landed before its
    call row still blocks the duplicate.

    Fails OPEN, and says so: if production cannot be read the caller gets every voicemail back and
    the sync's own dedup still applies. Fails SOUND for the duplicate guard only if the voicemail
    path has not yet written the row - which the second clock run would catch.
    """
    if not voicemails:
        return [], 0
    try:
        from app.services.website_db import _get_pg_connection

        pg_conn = _get_pg_connection(pg_url)
        if not pg_conn:
            print("voicemail guard: no Postgres connection; not filtering", file=sys.stderr)
            return voicemails, 0
        refs: list[str] = []
        for vm in voicemails:
            cid = vm.get("ccall_id") or vm.get("call_id") or ""
            if cid:
                refs.append(f"dialpad:call:{cid}")
                refs.append(f"dialpad:voicemail:{cid}")
        existing: set[str] = set()
        cur = pg_conn.cursor()
        for i in range(0, len(refs), 200):
            chunk = refs[i:i + 200]
            # The alias is load-bearing: the pool opens a RealDictCursor, and an unaliased
            # `metadata->>%s` comes back keyed `?column?`. Named access works on RealDict rows,
            # positional access does not - learned by running it, which is why the guard prints
            # its own failure instead of failing silently to a wrong count.
            cur.execute(
                'SELECT metadata->>%s AS ref FROM communications WHERE metadata->>%s = ANY(%s)',
                ("external_ref", "external_ref", chunk),
            )
            existing.update(r["ref"] for r in cur.fetchall() if r.get("ref"))
    except Exception as exc:  # noqa: BLE001
        print(f"voicemail guard failed ({type(exc).__name__}: {exc}); not filtering",
              file=sys.stderr)
        return voicemails, 0

    pending, already = [], 0
    for vm in voicemails:
        cid = vm.get("ccall_id") or vm.get("call_id") or ""
        if not cid:
            continue
        if f"dialpad:call:{cid}" in existing or f"dialpad:voicemail:{cid}" in existing:
            already += 1
        else:
            pending.append(vm)
    return pending, already


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
        sync_dialpad_voicemails_to_website,
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
        voicemails = _get_dialpad_voicemails_for_push(settings)
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

    result["candidates"] = {"calls": len(calls), "sms": len(sms),
                            "voicemails": len(voicemails)}
    result["withheld_pci"] = held
    result["window"] = ("calls: 7d/500, sms: 7d/1000, voicemails: 7d/500 "
                        "(the reconciliation's own getters, plus the A4 voicemail getter)")

    # Gap A4: the call path already stores voicemails as `dialpad:call:<call_id>` with a
    # `[Voicemail]:` section in the body, and neither sync can see the other's ref. Push only
    # the voicemails the website does not already hold, under either ref.
    voicemails, already_on_website = _voicemails_not_yet_on_website(pg_url, voicemails)
    result["voicemails_already_on_website"] = {
        "count": already_on_website,
        "to_push": len(voicemails),
    }

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
    try:
        result["voicemails"] = sync_dialpad_voicemails_to_website(
            pg_url=pg_url, secretary_db_url=settings.database_url, voicemails=voicemails)
    except Exception as exc:  # noqa: BLE001
        result["voicemails"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    ok = (bool((result.get("calls") or {}).get("ok"))
          and bool((result.get("sms") or {}).get("ok"))
          and bool((result.get("voicemails") or {}).get("ok")))
    result["ok"] = ok

    if args.json:
        print(json.dumps(result, indent=1, default=str))
    else:
        c, s = result.get("calls") or {}, result.get("sms") or {}
        v = result.get("voicemails") or {}
        print(f"calls : synced={c.get('synced')} errors={c.get('errors')} "
              f"skipped_dedup={c.get('skipped_dedup')} {c.get('error') or ''}")
        print(f"sms   : synced={s.get('synced')} errors={s.get('errors')} "
              f"skipped_dedup={s.get('skipped_dedup')} {s.get('error') or ''}")
        print(f"vm    : synced={v.get('synced')} errors={v.get('errors')} "
              f"skipped_dedup={v.get('skipped_dedup')} "
              f"already_on_website={result.get('voicemails_already_on_website', {}).get('count')} "
              f"{v.get('error') or ''}")
        if held:
            print(f"WITHHELD (awaiting the owner, queue 67): {held}")
        print("ok" if ok else "NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
