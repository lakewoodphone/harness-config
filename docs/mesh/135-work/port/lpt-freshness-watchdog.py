#!/usr/bin/env python3
"""FRESHNESS WATCHDOG — measures how far behind the SOURCE each channel is, repairs, and alerts.

WHY IT MEASURES AGAINST THE SOURCE AND NOT AGAINST US
A channel that is quiet and a channel that is broken look identical from inside. On 2026-10-06
the SMS backfill's cursor froze for fifteen days and logged `read: 0 ... ok` every thirty
minutes - a healthy-looking heartbeat - while production held 828 newer rows. Meanwhile
`dialpad_call_full.fetched_at` is not even updated by the upsert on re-fetch, so it only moves
when a NEW call arrives; on a quiet night it reads hours old while the harvester is fine.

So this compares what the SOURCE has newest against what WE hold newest, per channel. That is
the only number that can tell healthy-and-quiet from actually-behind.

WHAT IT DOES EACH RUN
  1. measures lag per channel in seconds
  2. if lag > REPAIR_AT seconds, runs that channel's own repair and re-measures
  3. alerts ONLY when the repair did not close the gap - alert fatigue destroys the value
  4. appends one line per run so the trend is visible

PORTED TO THE CLOUD AUTHORITY, 2026-10-11 (workstream 135)
----------------------------------------------------------
The office copy had three office literals. Each is now a single overridable constant whose DEFAULT
is the office value, so dropping this file back onto the office box changes nothing:

  REPO   `~/personal-secretary-mvp`                     -> LPT_REPO            (cloud: /opt/company)
  DB     `$REPO/data/secretary.db`                      -> LPT_SECRETARY_DB    (cloud: /root/authority.db)
  LOG/STATE `~/.lpt-ops/dialpad/...`                    -> WATCHDOG_LOG / WATCHDOG_STATE

WHY THE DB OVERRIDE IS NOT OPTIONAL. On the cloud box `/opt/company/data/secretary.db` EXISTS and
is 1.8 MB against the real authority's 23.7 GB — a stale stub left by the cutover. Measuring THAT
file would compare a dead table against a live source and report a permanent phantom lag, or, worse
on a quiet day, report healthy. This is the estate's most expensive failure shape: a monitor that
reports success while measuring nothing. It must point at /root/authority.db, and the cron line
says so explicitly rather than trusting a default.

DESIGN NOTES
  * Every check is bounded and cheap: the call check makes ONE Dialpad API call with limit=1.
  * Repairs are the same scripts the crons already run, so there is one implementation of each.
  * An unreadable source is reported as UNKNOWN, never as OK. A refusal is a correct answer;
    a confident wrong number is not.
  * Exit code: 0 when every channel is OK or was repaired; 3 when this watch has a FINDING
    it cannot clear itself (a channel behind, an unreadable source, or nothing to compare).
    3 -- CONDITION_EXIT -- is this repo's word for 'condition, not fault', used the same way
    by check-phoenix-evidence.py, supplier-delivery-watch.py and ai-gateway-health.py. Every
    failure this watch can reach is a finding: its only inputs are the source and the local
    store, so it can neither create nor clear a problem in either, and a job that exits 1 for
    a condition it is correctly reporting trains every reader to ignore the record. Measured
    2026-10-07: 16 consecutive runs exited 1 while the stderr column stayed EMPTY, because
    exit 1 was the 'a channel stayed behind' signal and every reader read it as a fault.
    1 remains reserved for a fault in THIS JOB (a crash, a bug) and is not returned by any
    ordinary finding path.

Usage: freshness_watchdog.py [--json] [--repair-at 120] [--no-repair] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = os.environ.get("LPT_REPO") or os.path.expanduser("~/personal-secretary-mvp")
ENV = os.environ.get("LPT_ENV") or os.path.join(REPO, ".env")
DB = os.environ.get("LPT_SECRETARY_DB") or os.path.join(REPO, "data", "secretary.db")
PY = os.environ.get("LPT_PY") or os.path.join(REPO, ".venv", "bin", "python")
LOG = os.environ.get("WATCHDOG_LOG") or os.path.expanduser("~/.lpt-ops/dialpad/freshness.log")
STATE = os.environ.get("WATCHDOG_STATE") or os.path.expanduser("~/.lpt-ops/dialpad/freshness-state.json")

# The one channel that is genuinely push-based, so a slow poll here is expected and fine.
PROBE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def envval(key: str) -> str | None:
    try:
        for line in open(ENV, encoding="utf-8", errors="replace"):
            m = re.match(rf"\s*{key}\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def newest_production_sms() -> datetime | None:
    """Newest genuine SMS in the production source. None if unreadable.

    MUST apply the same external_ref exclusion the backfill applies. Production also holds
    rows that are OUR OWN EXPORTS echoed back (metadata->>'external_ref' = 'dialpad:sms:<id>'
    or 'ptf-...'), and the backfill deliberately skips them. Without this filter the watchdog
    compares production-including-our-exports against a cache that excludes them, and reports
    a permanent false 'BEHIND' - which is exactly what it did on its first run: 53 minutes of
    phantom lag while the pipeline was fine. A watchdog that cries wolf gets ignored.
    """
    try:
        import psycopg2
    except ImportError:
        return None
    url = envval("PHONE_TECH_FULL_DATABASE_URL")
    if not url:
        return None
    try:
        con = psycopg2.connect(url, connect_timeout=15)
        try:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT MAX("createdAt") FROM communications
                     WHERE "type"='SMS'
                       AND coalesce("content",'') <> ''
                       AND strpos(coalesce("metadata"->>'external_ref',''), 'dialpad:') <> 1
                       AND strpos(coalesce("metadata"->>'external_ref',''), 'ptf-') <> 1
                """)
                got = cur.fetchone()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None
    if not got or not got[0]:
        return None
    dt = got[0]
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def newest_dialpad_call() -> datetime | None:
    """Newest call Dialpad itself knows about. ONE API call, limit=1."""
    tok = envval("DIALPAD_API_KEY")
    if not tok:
        return None
    base = envval("DIALPAD_API_BASE") or "https://dialpad.com/api/v2"
    req = urllib.request.Request(
        f"{base}/call?limit=1",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                 "User-Agent": PROBE_UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.load(r)
    except Exception:  # noqa: BLE001
        return None
    items = body.get("items") or []
    if not items:
        return None
    c = items[0]
    ms = c.get("date_started") or c.get("dateStarted")
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def newest_ours(table: str, col: str, is_ms: bool = False) -> datetime | None:
    """Newest row WE hold. Read-only, never a writer against the authority."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        try:
            row = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    v = row[0]
    if is_ms:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def run_repair(name: str, argv: list[str], timeout: int = 900) -> tuple[bool, str]:
    try:
        p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        return p.returncode == 0, f"rc={p.returncode} {tail[0][:120]}"
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair-at", type=int, default=120,
                    help="seconds behind before a repair is attempted (default 120)")
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)

    channels = []

    # ---- SMS -------------------------------------------------------------
    src = newest_production_sms()
    ours = newest_ours("dialpad_sms_cache", "created_at")
    channels.append({
        "channel": "sms",
        "source_newest": src.isoformat() if src else None,
        "ours_newest": ours.isoformat() if ours else None,
        "lag_s": None if (src is None or ours is None)
        else round((src - ours).total_seconds(), 1),
        "source_readable": src is not None,
        # NOTE: the SMS repair is a SHELL script, so it runs under bash. Passing it to the
        # venv python returns rc=1 and silently disables the repair - which the trip test on
        # 2026-10-07 caught. The call repair is a python script, so it uses the interpreter.
        "repair": ["bash", "scripts/dialpad-sms-harvest-cron.sh"],
    })

    # ---- calls -----------------------------------------------------------
    src_c = newest_dialpad_call()
    ours_c = newest_ours("dialpad_call_full", "date_started_ms", is_ms=True)
    channels.append({
        "channel": "calls",
        "source_newest": src_c.isoformat() if src_c else None,
        "ours_newest": ours_c.isoformat() if ours_c else None,
        "lag_s": None if (src_c is None or ours_c is None)
        else round((src_c - ours_c).total_seconds(), 1),
        "source_readable": src_c is not None,
        "repair": [PY, "scripts/dialpad-call-fresh.py", "--hours", "2"],
    })

    results = []
    worst_rc = 0        # 0 ok | 3 CONDITION (see docstring); 1 reserved for a fault
    consecutive_bad_path = os.path.join(os.path.dirname(STATE), "consecutive-bad.txt")
    try:
        with open(consecutive_bad_path, encoding="utf-8") as fh:
            prior_bad = int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        prior_bad = 0
    ALERT_AFTER = 3   # consecutive failed/unknown runs before the owner is told
    for ch in channels:
        lag = ch["lag_s"]
        entry = dict(ch)
        entry.pop("repair", None)
        if not ch["source_readable"]:
            entry["state"] = "UNKNOWN"
            entry["action"] = "none - source unreadable, refusing to call this OK"
            worst_rc = 3
        elif lag is None:
            entry["state"] = "UNKNOWN"
            entry["action"] = "none - nothing to compare"
            worst_rc = 3
        elif lag <= args.repair_at:
            entry["state"] = "OK"
            entry["action"] = "none"
        else:
            entry["state"] = "BEHIND"
            if args.no_repair:
                entry["action"] = "repair suppressed by --no-repair"
                worst_rc = 3
            else:
                ok, detail = run_repair(ch["channel"], ch["repair"])
                # RE-MEASURE. A repair that is not verified is not a repair.
                if ch["channel"] == "sms":
                    after_src, after_ours = newest_production_sms(), newest_ours(
                        "dialpad_sms_cache", "created_at")
                else:
                    after_src, after_ours = newest_dialpad_call(), newest_ours(
                        "dialpad_call_full", "date_started_ms", is_ms=True)
                after_lag = None if (after_src is None or after_ours is None) \
                    else round((after_src - after_ours).total_seconds(), 1)
                entry["repair_ok"] = ok
                entry["repair_detail"] = detail
                entry["lag_after_s"] = after_lag
                if after_lag is not None and after_lag <= args.repair_at:
                    entry["state"] = "REPAIRED"
                    entry["action"] = f"ran {ch['channel']} repair; lag {lag}s -> {after_lag}s"
                else:
                    entry["state"] = "STILL_BEHIND"
                    entry["action"] = f"repair did NOT close it ({lag}s -> {after_lag}s)"
                    worst_rc = 3
        results.append(entry)

    payload = {"at": now.isoformat(), "repair_at_s": args.repair_at, "channels": results,
               "repo": REPO, "db": DB}
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
    except OSError:
        pass

    # ---- ALERTING -------------------------------------------------------------------------
    # Alert ONLY when the trouble persists. A single bad minute is noise; three in a row is a
    # fault. Alert fatigue is what made the previous message queue useless (595 undelivered
    # rows, nothing sent for 54 days), so this stays quiet unless it is genuinely wrong.
    bad = [e["channel"] for e in results if e["state"] in ("STILL_BEHIND", "UNKNOWN")]
    if bad:
        prior_bad += 1
    else:
        prior_bad = 0
    try:
        with open(consecutive_bad_path, "w", encoding="utf-8") as fh:
            fh.write(str(prior_bad))
    except OSError:
        pass

    if bad and prior_bad >= ALERT_AFTER:
        alert_path = os.path.join(os.path.dirname(STATE), "freshness-ALERT.log")
        detail = "; ".join(
            f"{e['channel']} {e['state']} lag={e['lag_s']}s "
            f"after={e.get('lag_after_s')} ({e['action']})"
            for e in results if e["channel"] in bad)
        line = (f"{now.isoformat()}  {prior_bad} consecutive runs with a bad channel\n"
                f"    {detail}\n")
        try:
            with open(alert_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass

        # DELIVER IT, once per episode. The owner's own standing instruction is that texts must
        # be short and he will not read a wall of text, so this is one or two lines naming the
        # channel, the lag and what was tried. send_owner_update owns the hard parts: it honours
        # the owner SMS kill switch (queuing instead of sending when it is active), normalises
        # urgency, and sits behind a flood guard with a daily ceiling. Calling sms_service
        # directly would bypass all three.
        once = os.path.join(os.path.dirname(STATE), "alert-raised.flag")
        if not os.path.exists(once):
            sent = "not attempted"
            try:
                sys.path.insert(0, REPO)
                from app.tool_factory import send_owner_update  # noqa: E402

                worst = max(
                    (e for e in results if e["channel"] in bad),
                    key=lambda e: (e["lag_s"] or 0))
                mins = round((worst["lag_s"] or 0) / 60.0, 1)
                body = (f"Dialpad sync is behind on {worst['channel']}: {mins} min, and the "
                        f"automatic repair did not close it. {prior_bad} checks in a row. "
                        f"Nothing else is affected yet.")
                res = send_owner_update(
                    body,
                    reason="freshness_watchdog:dialpad_behind",
                    urgency="high")
                sent = f"ok={res.get('ok')} status={res.get('status') or res.get('error')}"
            except Exception as exc:  # noqa: BLE001
                sent = f"FAILED {type(exc).__name__}: {exc}"
            try:
                with open(once, "w", encoding="utf-8") as fh:
                    fh.write(f"{line}delivery: {sent}\n")
            except OSError:
                pass
            print(f"ALERT sent ({sent}): {detail}")
        print(f"ALERT ACTIVE: {prior_bad} consecutive runs with a bad channel: {detail}")
    elif not bad:
        # episode over - clear the flag so a FUTURE fault alerts again
        for f in ("alert-raised.flag",):
            p = os.path.join(os.path.dirname(STATE), f)
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    if args.json:
        print(json.dumps(payload, indent=1))
    else:
        print(f"{now.isoformat()[:19]}Z  repair_at={args.repair_at}s  repo={REPO} db={DB}")
        for e in results:
            lag = e["lag_s"]
            print(f"  {e['channel']:6} {e['state']:14} "
                  f"lag={'-' if lag is None else str(lag)+'s':>10}  {e['action']}")
    return worst_rc


if __name__ == "__main__":
    sys.exit(main())
