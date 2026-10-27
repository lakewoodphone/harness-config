#!/usr/bin/env python3
"""Page the owner for a level-3 security decision ONLY when nothing already paged.

Why this exists (2026-10-27). Two independent things exist and do not know about each
other: Home Assistant pages on its own automation (real SMS/MMS to the owner and the
extra recipients), and the Python judge records level-3 decisions and sends nothing.
If HA's page never leaves -- its evidence script aborts, the API refuses, the network is
down -- the judge holds a level-3 decision and nobody is told.

So this is a FALLBACK, not a second sender. It looks at each recent level-3 decision,
asks the record whether a page was already recorded for that episode, and only acts when
the answer is no. It posts to the SAME webhook Home Assistant posts to, so there is one
transport, one audit path and one set of guards.

usage:
  security-page-fallback.py --dry-run     decide and print, send nothing (the harness)
  security-page-fallback.py               page where the record shows nothing was sent
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DB = '/root/authority.db'
ENV_FILE = '/opt/company/.env'
LOCAL_API = 'http://127.0.0.1:8002/webhook/ha/security-alert'

# How far back to look for level-3 decisions this run has not already considered.
DECISION_WINDOW_S = 1800
# A recorded page this close to the decision covers that episode. HA pages within
# seconds of the door edge; the judge settles an episode ~125 s later, so a page
# anywhere in this window means "already told him".
PAGE_COVER_S = 300
# Do not page twice for the same decision inside this period.
REPEAT_SUPPRESS_S = 3600


def env(key: str) -> str | None:
    try:
        with open(ENV_FILE, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                if k.strip().upper() == key:
                    return v.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def parse(ts: str) -> datetime:
    t = ts.replace('Z', '+00:00')
    d = datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def door_from_episode(episode_id: str | None) -> str:
    if not episode_id:
        return 'a door'
    return episode_id.split('@', 1)[0]


def level3_decisions(conn, since: datetime):
    return conn.execute(
        "SELECT id, episode_id, rule_id, avs_level, confidence, reason_one_line, created_at "
        "FROM security_decision "
        "WHERE avs_level >= 3 AND decision = 'ESCALATE' AND created_at >= ? "
        "ORDER BY created_at",
        (since.strftime('%Y-%m-%dT%H:%M:%SZ'),),
    ).fetchall()


def page_exists(conn, when: datetime) -> tuple[bool, str | None]:
    lo = (when - timedelta(seconds=PAGE_COVER_S)).strftime('%Y-%m-%dT%H:%M:%S')
    hi = (when + timedelta(seconds=PAGE_COVER_S)).strftime('%Y-%m-%dT%H:%M:%S')
    row = conn.execute(
        "SELECT attempted_at, result, recipient FROM security_action "
        "WHERE action IN ('PAGE','PAGE_FAILED') AND attempted_at BETWEEN ? AND ? "
        "AND result = 'ok' ORDER BY attempted_at DESC LIMIT 1",
        (lo, hi),
    ).fetchone()
    return (True, row[0]) if row else (False, None)


def already_attempted_by_us(conn, decision_id: str, when: datetime) -> bool:
    lo = (when - timedelta(seconds=REPEAT_SUPPRESS_S)).strftime('%Y-%m-%dT%H:%M:%S')
    row = conn.execute(
        "SELECT 1 FROM security_action "
        "WHERE actor = 'security-page-fallback' AND attempted_at >= ? LIMIT 1",
        (lo,),
    ).fetchone()
    return bool(row)


def page(detail: str) -> tuple[bool, str]:
    key = env('HA_SECURITY_API_KEY')
    if not key:
        return False, 'HA_SECURITY_API_KEY missing from /opt/company/.env'
    body = json.dumps({'event': 'intrusion', 'detail': detail, 'avs_level': 3}).encode()
    req = urllib.request.Request(
        LOCAL_API, data=body,
        headers={'Content-Type': 'application/json', 'x-ps-api-key': key},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode() or '{}')
            return bool(payload.get('ok')), json.dumps(payload)[:400]
    except urllib.error.HTTPError as exc:
        return False, 'HTTP %s: %s' % (exc.code, exc.read().decode()[:200])
    except Exception as exc:  # noqa: BLE001
        return False, '%s: %s' % (type(exc).__name__, exc)


def record(conn, ok: bool, detail: str, error: str | None) -> None:
    conn.execute(
        "INSERT INTO security_action (decision_id, episode_id, action, actor, attempted_at,"
        " result, recipient, error) VALUES (?,?,?,?,?,?,?,?)",
        (None, None, 'PAGE' if ok else 'PAGE_FAILED', 'security-page-fallback',
         datetime.now(timezone.utc).isoformat(), 'ok' if ok else 'failed',
         env('OWNER_PHONE_NUMBER'), error))
    conn.commit()


def main(argv: list[str]) -> int:
    dry = '--dry-run' in argv
    since = datetime.now(timezone.utc) - timedelta(seconds=DECISION_WINDOW_S)
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        rows = level3_decisions(conn, since)
        print('level-3 decisions in the last %d min: %d%s'
              % (DECISION_WINDOW_S // 60, len(rows), '  [DRY RUN - sends nothing]' if dry else ''))
        acted = 0
        for r in rows:
            when = parse(r['created_at'])
            covered, at = page_exists(conn, when)
            door = door_from_episode(r['episode_id'])
            if covered:
                print('  %s  %-16s level %s  -> COVERED (a page is recorded at %s); fallback silent'
                      % (r['created_at'], door, r['avs_level'], at))
                continue
            if already_attempted_by_us(conn, r['id'], when):
                print('  %s  %-16s -> SUPPRESSED (this fallback already tried inside %d min)'
                      % (r['created_at'], door, REPEAT_SUPPRESS_S // 60))
                continue
            detail = ('%s opened with no key code while the shop was closed'
                      % door.replace('_', ' '))
            if dry:
                print('  %s  %-16s -> WOULD PAGE: %r' % (r['created_at'], door, detail))
                acted += 1
                continue
            ok, note = page(detail)
            record(conn, ok, detail, None if ok else note)
            print('  %s  %-16s -> %s (%s)' % (r['created_at'], door,
                                              'PAGED' if ok else 'PAGE FAILED, recorded', note))
            acted += 1
        print('would act on %d, left %d alone' % (acted, len(rows) - acted) if dry
              else 'acted on %d, left %d alone' % (acted, len(rows) - acted))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
