#!/usr/bin/env python3
"""production-comms-freshness.py — the check that would have caught the 11.5-hour silence.

WHY THIS EXISTS (axis G, 2026-09-15)
    The website received no customer message for 11.5 hours and nothing noticed, because the only
    staleness signal in the tree measured the WRONG CLOCK:

        capture_freshness() checks MAX(dialpad_sms_cache.fetched_at)

    - the LOCAL receive time, which the live Dialpad webhook keeps refreshing every few minutes. So
    while the website received nothing, the local clock looked perfectly healthy and the signal said
    "fresh". The watchdog watched the clock that could not go wrong.

    The clock that matters is the WEBSITE's: `website_sync_cursor.last_synced_at`, and the row the
    website actually holds. Both are read here.

WHAT IT MEASURES
    1. website_sync_cursor.last_synced_at per sync_type   (when the push last ran)
    2. local newest Dialpad message/call                   (what there is to push)
    3. production's newest communications row               (what the website actually has)
    and it fails when the local store is meaningfully ahead of what the website has received.

EXIT    0 fresh · 1 stale (something is failing) · 2 could not measure (a refusal, never health)

SCHEDULED: */15 in crontab, because a check that is scheduled nowhere is decoration - the other
half of this defect was that `comms-refresh.py --check` already exited non-zero on staleness and
was in no crontab at all.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SECRETARY_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
ENV_FILE = "/home/zabz/personal-secretary-mvp/.env"
STATE = Path("/home/zabz/.lpt-recon/production-comms-freshness.json")
THRESHOLD_HOURS = 2.0


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(v) -> datetime | None:
    if v is None:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def env_value(key: str) -> str:
    p = Path(ENV_FILE)
    if not p.exists():
        return ""
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return ""


def main() -> int:
    report: dict = {"checked_at": now().isoformat(timespec="seconds"),
                    "threshold_hours": THRESHOLD_HOURS}
    problems: list[str] = []

    # 1 + 2: the cursors and the local truth, from secretary.db (read-only)
    try:
        con = sqlite3.connect(f"file:{SECRETARY_DB}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT sync_type, last_synced_at FROM website_sync_cursor")
        cursors = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT MAX(created_at) FROM dialpad_sms_cache "
                    "WHERE message_id NOT LIKE 'test-%' AND message_id NOT LIKE 'self-%'")
        local_sms_newest = cur.fetchone()[0]
        cur.execute("SELECT MAX(date_started_ms) FROM dialpad_call_full")
        local_call_ms = cur.fetchone()[0]
        con.close()
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"could not read secretary.db: {type(exc).__name__}: {exc}"
        print(f"CANNOT MEASURE: {report['error']}")
        return 2

    local_sms_dt = parse_ts(local_sms_newest)
    local_call_dt = (datetime.fromtimestamp(local_call_ms / 1000, timezone.utc)
                     if local_call_ms else None)
    report["local_newest_sms"] = local_sms_newest
    report["local_newest_call"] = local_call_dt.isoformat() if local_call_dt else None

    for sync_type, local_dt in (("dialpad_calls", local_call_dt), ("dialpad_sms", local_sms_dt)):
        raw = cursors.get(sync_type)
        dt = parse_ts(raw)
        age_h = round((now() - dt).total_seconds() / 3600, 2) if dt else None
        lag_h = (round((local_dt - dt).total_seconds() / 3600, 2)
                 if (dt and local_dt) else None)
        report[sync_type] = {"cursor": raw, "cursor_age_hours": age_h, "behind_local_hours": lag_h}
        if dt is None:
            problems.append(f"{sync_type}: no cursor row at all - the push has never run")
        elif lag_h is not None and lag_h > THRESHOLD_HOURS:
            problems.append(
                f"{sync_type}: the website is {lag_h}h behind the local store "
                f"(cursor {age_h}h old) - this is the 2026-09-15 failure shape")

    # 3: what the website actually holds
    try:
        import psycopg2
        import psycopg2.extras
        url = (env_value("PHONE_TECH_FULL_DIRECT_URL")
               or env_value("PHONE_TECH_FULL_DATABASE_URL"))
        if not url:
            problems.append("no PHONE_TECH_FULL_* DSN in .env - cannot read the website")
        else:
            pg = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
            pg.set_session(readonly=True)
            c = pg.cursor()
            c.execute('SELECT COUNT(*), MAX("createdAt") FROM communications')
            n, newest = c.fetchone()
            pg.close()
            dt = parse_ts(newest)
            age_h = round((now() - dt).total_seconds() / 3600, 2) if dt else None
            report["website"] = {"rows": n, "newest": str(newest), "newest_age_hours": age_h}
            if age_h is not None and age_h > THRESHOLD_HOURS and local_sms_dt is not None:
                behind = round((local_sms_dt - dt).total_seconds() / 3600, 2)
                if behind > THRESHOLD_HOURS:
                    problems.append(
                        f"the website's newest message is {behind}h older than the local store's "
                        f"- the website is not receiving what the shop already has")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not read the website: {type(exc).__name__}: {exc}")

    report["problems"] = problems
    report["ok"] = not problems
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")

    print(f"production comms freshness — {report['checked_at']}")
    for k in ("dialpad_calls", "dialpad_sms"):
        if k in report:
            d = report[k]
            print(f"  {k:<14} cursor={d['cursor']} age={d['cursor_age_hours']}h "
                  f"behind_local={d['behind_local_hours']}h")
    if "website" in report:
        w = report["website"]
        print(f"  website        rows={w['rows']} newest={w['newest']} age={w['newest_age_hours']}h")
    if problems:
        print("\nSTALE:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nfresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
