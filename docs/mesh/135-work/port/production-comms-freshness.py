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

PORTED TO THE CLOUD AUTHORITY, 2026-10-11 (workstream 135)
----------------------------------------------------------
The office copy named two literals. Both are now environment-overridable with the OFFICE value as
the default, so the office behaviour of this file is unchanged:

    SECRETARY_DB  "/home/zabz/personal-secretary-mvp/data/secretary.db"   -> FRESHNESS_SECRETARY_DB
    ENV_FILE      "/home/zabz/personal-secretary-mvp/.env"                -> FRESHNESS_ENV_FILE
    STATE         office path                                             -> FRESHNESS_STATE

ON THE CLOUD BOX THE DB IS /root/authority.db AND THE READ STAYS READ-ONLY (`mode=ro`, uri=True).
That is not a preference: /root/authority.db is the single live authority and a monitor must never
be a second writer against it. The 1.8 MB `/opt/company/data/secretary.db` stub left by the cutover
is NOT this file's business and must never be pointed at here — a monitor that measures a dead copy
reports a confident wrong number, which is the worst outcome in this estate's history.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SECRETARY_DB = os.environ.get(
    "FRESHNESS_SECRETARY_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db")
ENV_FILE = os.environ.get(
    "FRESHNESS_ENV_FILE", "/home/zabz/personal-secretary-mvp/.env")
STATE = Path(os.environ.get(
    "FRESHNESS_STATE", "/home/zabz/.lpt-recon/production-comms-freshness.json"))
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



# --- DEAD-FEED GUARD (item 402, 2026-10-05) ---------------------------------------------------
# A feed whose table stops advancing is dead even while its sync cursor keeps moving. Every
# comparison in this file used to be cursor-relative, so a stopped table read as fresh forever.
# The guard below measures the TABLE, and only calls silence a fault when the shop was open.
# weekday() -> 0=Mon .. 6=Sun. Local times are America/New_York; in October that is EDT = UTC-4,
# so 12:00 local = 16:00 UTC and 17:30 local = 21:30 UTC. Revisit if the machine's zone changes.
# America/New_York in October is EDT = UTC-4, so a local closing of 16:00 is 20:00 UTC - do not
# "simplify" these numbers without converting first (my own first pass got this wrong).
OPEN_HOURS_UTC = {6: (16.0, 20.0),       # Sunday    12:00-16:00 local = 16:00-20:00 UTC
                  1: (14.5, 21.5),       # Tuesday   10:30-17:30 local = 14:30-21:30 UTC
                  3: (14.5, 21.5)}       # Thursday  10:30-17:30 local = 14:30-21:30 UTC
# The longest normal quiet stretch is the Sunday 16:00 -> Tuesday 10:30 closure = 10.5 open hours.
FEED_MAX_SILENCE = {"dialpad_calls": 12.0, "dialpad_sms": 6.0}   # hours of OPEN time
# A second, calendar-blind bound. Learned the hard way while writing this guard: the open-hours
# bound alone is too generous during a quiet week - dialpad_call_full last advanced
# 2026-10-01T20:18:15 (77.8 wall-clock hours, 3.2 days) yet only 5.2 of those were shop-open, so an
# open-hours-only rule stays silent on a feed that is plainly dead. Either condition fires.
# Derived from the shop's own longest closure rather than guessed: the longest stretch the shop is
# shut is Sunday 16:00 -> Tuesday 10:30 = 42.5 wall-clock hours. One whole missed open day on top
# of that is 42.5 + 24 = 66.5 for calls; SMS arrives more often, so it gets the closure plus a few
# hours. First pass of this guard used a flat 96/48 and stayed silent on a feed already 77.8 hours
# dead - the bound has to come from the business, not from a round number.
FEED_MAX_WALL_SILENCE = {"dialpad_calls": 66.5, "dialpad_sms": 48.0}   # hours, any time at all

# THE HARVEST HEARTBEAT (2026-10-05, correcting item 402's first pass).
# Both feed tables are INSERT-only: the upsert on conflict updates `updated_at`
# and deliberately leaves `fetched_at` alone, so a healthy pass that finds
# nothing new advances NOTHING, and the newest row ages at exactly the rate a
# dead job's would. The wall bound above (66.5h) is also exactly the shop's own
# longest weekly closure - Thursday 21:30 UTC close -> Sunday 16:00 UTC open =
# 66.5h - so a table-only rule fires on a working feed during any quiet
# Thu->Sun stretch, which is what happened at 2026-10-05T02:15Z (newest call
# 2026-10-01T20:18Z, a genuine 78h of no calls; the API then delivered four
# calls at 02:08-02:12Z). The harvest writes a completion marker on every
# finished pass; that marker is the honest "the feed is being read" signal and
# the kernel already judges both feeds by it
# (ceo-kernel/ck/sentinel.py check_comms_freshness). The table rules below stay
# as the fallback when the marker is absent or stale.
HARVEST_HEARTBEAT = {
    "dialpad_calls": ".dialpad-harvest.last_run",
    "dialpad_sms": ".dialpad-sms-harvest.last_run",
}
HARVEST_MAX_AGE_HOURS = 1.5   # calls run */30, texts :15,:45 -> 3 missed passes


def _harvest_age_hours(sync_type: str) -> float | None:
    """Age of the harvest's own completion marker, or None if unavailable."""
    name = HARVEST_HEARTBEAT.get(sync_type)
    if not name:
        return None
    try:
        raw = (Path.home() / name).read_text().strip()
    except OSError:
        return None
    dt = parse_ts(raw)
    if dt is None:
        return None
    return round((now() - dt).total_seconds() / 3600, 2)


def _open_hours_between(start, end) -> float:
    """Hours of shop-open time inside [start, end], in UTC. Owner hours of 2026-10-05."""
    if start is None or end is None or end <= start:
        return 0.0
    total = 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        span = OPEN_HOURS_UTC.get(day.weekday())
        if span:
            o = day + timedelta(hours=span[0])
            c = day + timedelta(hours=span[1])
            lo, hi = max(o, start), min(c, end)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
        day += timedelta(days=1)
    return round(total, 2)


def _dead_feed_problems(local_dt, sync_type: str,
                        heartbeat_age_h: float | None = None) -> list:
    """Fail when the table itself has not advanced - by open hours, or by plain wall clock."""
    limit = FEED_MAX_SILENCE.get(sync_type)
    wall_limit = FEED_MAX_WALL_SILENCE.get(sync_type, limit)
    if limit is None:
        return []
    if local_dt is None:
        return [f"{sync_type}: the local table has NO rows at all - cannot measure the feed"]
    # A fresh harvest heartbeat proves the feed is being READ: the quiet table is
    # a quiet shop, not a dead job. Absent/stale marker -> fall through to the
    # table rules, which still catch a harvester that has actually stopped.
    if heartbeat_age_h is not None and heartbeat_age_h <= HARVEST_MAX_AGE_HOURS:
        return []
    silent = (now() - local_dt).total_seconds() / 3600
    open_silent = _open_hours_between(local_dt, now())
    if open_silent > limit:
        return [f"{sync_type}: DEAD FEED - the local table has not advanced in "
                f"{round(silent, 2)}h wall clock, of which {open_silent}h was shop-open time "
                f"(limit {limit}h open). The sync cursor moving is NOT evidence of health; the "
                f"table is the evidence. newest={local_dt.isoformat()}"]
    if wall_limit is not None and silent > wall_limit:
        return [f"{sync_type}: DEAD FEED - the local table has produced nothing for "
                f"{round(silent, 2)}h of wall-clock time (limit {wall_limit}h), of which only "
                f"{open_silent}h was shop-open, so no open-hours rule can see it. The sync cursor "
                f"moving is NOT evidence of health; the table is the evidence. "
                f"newest={local_dt.isoformat()}"]
    return []
# --- end DEAD-FEED GUARD ----------------------------------------------------------------------

def main() -> int:
    report: dict = {"checked_at": now().isoformat(timespec="seconds"),
                    "threshold_hours": THRESHOLD_HOURS, "db": SECRETARY_DB,
                    "env_file": ENV_FILE}
    problems: list[str] = []

    # 1 + 2: the cursors and the local truth, from secretary.db (read-only)
    try:
        con = sqlite3.connect(f"file:{SECRETARY_DB}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT sync_type, last_synced_at FROM website_sync_cursor")
        cursors = {r[0]: r[1] for r in cur.fetchall()}
        # What the push is allowed to deliver. `ptf-comm-%` rows are website-origin copies
        # the push deliberately never sends back (`_get_dialpad_sms_for_push`), so the local
        # truth has to use the push's own filter or the check can never catch up to them.
        _PUSHABLE_SMS = ("message_id NOT LIKE 'test-%' "
                         "AND message_id NOT LIKE 'self-%' "
                         "AND message_id NOT LIKE 'ptf-comm-%'")
        cur.execute(f"SELECT MAX(created_at) FROM dialpad_sms_cache WHERE {_PUSHABLE_SMS}")
        local_sms_newest = cur.fetchone()[0]
        # The newest message the push has had time to deliver. The website's MAX("createdAt")
        # is its last INSERT time, so comparing it to an SMS that arrived seconds ago reads the
        # whole preceding quiet period as lag: on 2026-09-22 a 21.7h SMS lull ended at
        # 13:44:17Z and the 13:45 check called the website 10.59h behind, although the website
        # held every message and the next 30-minute push was due at 14:09. Only a message old
        # enough to have been pushed can prove the website is behind.
        _due_cutoff = (now() - timedelta(hours=THRESHOLD_HOURS)).isoformat()
        cur.execute(f"SELECT MAX(created_at) FROM dialpad_sms_cache "
                    f"WHERE {_PUSHABLE_SMS} AND created_at <= ?", (_due_cutoff,))
        local_sms_due = cur.fetchone()[0]
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
    local_due_dt = parse_ts(local_sms_due)
    report["local_sms_due"] = local_sms_due

    for sync_type, local_dt in (("dialpad_calls", local_call_dt), ("dialpad_sms", local_sms_dt)):
        hb_age = _harvest_age_hours(sync_type)
        problems.extend(_dead_feed_problems(local_dt, sync_type, hb_age))
        raw = cursors.get(sync_type)
        dt = parse_ts(raw)
        age_h = round((now() - dt).total_seconds() / 3600, 2) if dt else None
        lag_h = (round((local_dt - dt).total_seconds() / 3600, 2)
                 if (dt and local_dt) else None)
        report[sync_type] = {"cursor": raw, "cursor_age_hours": age_h,
                             "behind_local_hours": lag_h,
                             "harvest_heartbeat_age_hours": hb_age}
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
            if age_h is not None and age_h > THRESHOLD_HOURS and local_due_dt is not None:
                behind = round((local_due_dt - dt).total_seconds() / 3600, 2)
                if behind > THRESHOLD_HOURS:
                    problems.append(
                        f"the website's newest message is {behind}h older than the local store's "
                        f"- the website is not receiving what the shop already has")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not read the website: {type(exc).__name__}: {exc}")

    report["problems"] = problems
    report["ok"] = not problems
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    except OSError as exc:
        print(f"WARN: could not write {STATE}: {exc}", file=sys.stderr)

    print(f"production comms freshness — {report['checked_at']}")
    print(f"  db={SECRETARY_DB}")
    for k in ("dialpad_calls", "dialpad_sms"):
        if k in report:
            d = report[k]
            print(f"  {k:<14} cursor={d['cursor']} age={d['cursor_age_hours']}h "
                  f"behind_local={d['behind_local_hours']}h "
                  f"harvest_heartbeat_age={d.get('harvest_heartbeat_age_hours')}h")
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
