#!/usr/bin/env python3
"""Attach a name to a visit, from the only place that knows one: the access log text.

Why this is not in the keypad event: measured on the live record, every `entry_event` row for the
shop keypad has an empty `subject_id`, and the raw `security_event` payload is the automation that
fired, not the credential. The name exists in exactly one place — Home Assistant's
`input_text.phoenix_access_control_log`, a rolling text field whose lines read:

    Oct 28, 12:26 PM - Owner Access at Interior

So this reads that text, parses the name and the time, converts the time from the building's local
zone to UTC, and attaches the nearest entry to any visit that had a keypad signal. A visit with no
keypad signal gets nothing — it is not a guess about a face, it is a fact about a code.

usage:
  python3 shop-attribute.py --since 12h
  python3 shop-attribute.py --since 12h --dry
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DB = '/root/authority.db'
ENV = '/opt/company/.env'
LOG_ENTITY = 'input_text.phoenix_access_control_log'
WINDOW_S = 300          # a keypad press and its log line are the same moment, give or take

LINE = re.compile(
    r'^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),\s+(?P<hour>\d{1,2}):(?P<min>\d{2})\s*(?P<ap>[AP]M)'
    r'\s*-\s*(?P<who>[A-Za-z\'\u2019 -]+?)\s+Access\s+at\s+(?P<where>.+?)\s*$')


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def fetch_log() -> str:
    ha = (env('HA_URL') or '').rstrip('/')
    req = urllib.request.Request(ha + '/api/states/' + LOG_ENTITY,
                                 headers={'Authorization': 'Bearer ' + (env('HA_TOKEN') or '')})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get('state', '')


def parse_entries(text: str, tz: ZoneInfo, now: datetime) -> list[dict]:
    out = []
    for raw in text.split('\n'):
        m = LINE.match(raw.strip())
        if not m:
            continue
        try:
            hour = int(m.group('hour')) % 12 + (12 if m.group('ap') == 'PM' else 0)
            local = datetime(now.year, datetime.strptime(m.group('mon'), '%b').month,
                             int(m.group('day')), hour, int(m.group('min')), tzinfo=tz)
            # a log line from December seen in January belongs to last year; not our case, but
            # guard the obvious wrap rather than storing a visit from the future
            if local > now + timedelta(days=1):
                local = local.replace(year=local.year - 1)
        except Exception:
            continue
        out.append({'at': local.astimezone(timezone.utc),
                    'who': m.group('who').strip(), 'where': m.group('where').strip(),
                    'line': raw.strip()})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='24h')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    # THE ACCESS LOG IS IN THE BUILDING'S ZONE, NOT THE OWNER'S ALERT ZONE (2026-10-28).
    # `OWNER_TIMEZONE` is set to `UTC` on this host — it governs when alerts may be sent, not what
    # clock wrote a log line. Trusting it put every entry four hours away from its visit and the
    # matcher silently named nothing. The authority on "what time is it in the building" is the
    # Home Assistant instance itself, so ask it.
    tz_name = None
    try:
        cfg = json.loads(urllib.request.urlopen(
            urllib.request.Request((env('HA_URL') or '').rstrip('/') + '/api/config',
                                   headers={'Authorization': 'Bearer ' + (env('HA_TOKEN') or '')}),
            timeout=15).read().decode())
        tz_name = cfg.get('time_zone')
    except Exception:
        tz_name = None
    tz_name = tz_name or env('SHABBAT_TIMEZONE') or 'America/New_York'
    print('building timezone: %s' % tz_name)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo('America/New_York')

    hours = int(args.since.rstrip('h')) if args.since.endswith('h') else int(args.since)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    try:
        text = fetch_log()
    except Exception as exc:
        print('cannot read the access log: %s %s' % (type(exc).__name__, exc))
        return 2
    entries = parse_entries(text, tz, now)
    print('access log: %d readable entr%s, newest %s'
          % (len(entries), 'y' if len(entries) == 1 else 'ies',
             entries[0]['line'][:44] if entries else '-'))

    conn = sqlite3.connect(DB)
    try:
        visits = conn.execute(
            "SELECT id, started_at, ended_at, subjects FROM shop_visit WHERE started_at >= ? "
            "ORDER BY started_at", (since.isoformat(),)).fetchall()
        keypad = {}
        for vid, at in conn.execute(
                "SELECT visit_id, occurred_at FROM shop_visit_signal WHERE entity_id LIKE '%keypad%'"):
            keypad.setdefault(vid, at)
        print('%d visit(s) in range, %d with a keypad signal' % (len(visits), len(keypad)))

        named = 0
        for vid, started_at, ended_at, subjects in visits:
            if vid not in keypad:
                continue
            vstart = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            best, best_gap = None, None
            for e in entries:
                gap = abs((e['at'] - vstart).total_seconds())
                if gap <= WINDOW_S and (best_gap is None or gap < best_gap):
                    best, best_gap = e, gap
            if not best:
                continue
            payload = json.dumps([{'who': best['who'], 'where': best['where']}])
            if args.dry:
                print('  %s (%s) -> %s at %s' % (vid, started_at[11:16], best['who'], best['where']))
            else:
                conn.execute("UPDATE shop_visit SET subjects=? WHERE id=?", (payload, vid))
            named += 1
        if not args.dry:
            conn.commit()
        print('named %d visit(s)%s' % (named, ' (dry run)' if args.dry else ''))
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
