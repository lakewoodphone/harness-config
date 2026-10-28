#!/usr/bin/env python3
"""Group raw Home Assistant signals into human visits.

Why this exists. `security_event` holds 8,092 rows and grows by thousands a day, most of them
one `control_room_moving` detector firing continuously. A person cannot scroll that, and an
"event gallery" built on it would be a data dump with pictures. A *visit* is the unit a human
actually thinks in: someone arrived, was in the building for N minutes, and left.

The rule, deliberately simple and explainable:
  * only signals that can mean a person are considered -- a camera's human detector, a door
    contact, the doorbell's person/visitor, a keypad credential, or an occupied zone;
  * a visit opens at the first such signal and absorbs every later one within GAP seconds;
  * a gap longer than GAP closes it. A visit always has a start; the end is either the last
    signal plus GAP, or "still open" if that last signal was recent.

Nothing here invents data: a visit records which signals formed it, so the UI can expand it and
show the raw rows.

usage:
  python3 shop-visits.py --rebuild --since 24h      # rebuild the last 24 hours
  python3 shop-visits.py --show --since 24h         # print what the rule produces, change nothing
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB = '/root/authority.db'
GAP_SECONDS = 150          # a pause longer than this ends a visit

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_visit (
    id           TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,                 -- NULL means still open at build time
    last_signal  TEXT NOT NULL,
    doors        TEXT,                 -- JSON list of door ids touched
    cameras      TEXT,                 -- JSON list of cameras that saw a person
    subjects     TEXT,                 -- JSON list of names from credentials
    signal_count INTEGER NOT NULL DEFAULT 0,
    has_person   INTEGER NOT NULL DEFAULT 0,
    built_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_visit_started ON shop_visit(started_at);
CREATE TABLE IF NOT EXISTS shop_visit_signal (
    visit_id   TEXT NOT NULL,
    event_row  INTEGER NOT NULL,
    entity_id  TEXT NOT NULL,
    new_state  TEXT,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (visit_id, event_row)
);
CREATE INDEX IF NOT EXISTS ix_vsignal_visit ON shop_visit_signal(visit_id);
"""

# which entities can mean a person, and what they contribute
HUMAN_SUFFIX = '_smart_motion_human_2'
DOOR_ENTITIES = {
    'binary_sensor.phoenix_control_room_interior_door_contact': 'shop_door',
    'binary_sensor.phoenix_control_room_exterior_door_contact': 'apartment_door',
    'binary_sensor.phoenix_outside_door_contact': 'street_door',
}
PERSON_ENTITIES = {
    'binary_sensor.video_doorbell_person': 'doorbell',
    'binary_sensor.video_doorbell_visitor': 'doorbell',
}
ZONE_ENTITIES = {
    'binary_sensor.zone_hallway_active': 'hallway',
    'binary_sensor.zone_control_room_occupied': 'control_room',
    'binary_sensor.business_area_occupied': 'business',
}


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def classify(entity_id: str) -> tuple[str, str | None] | None:
    """Return (kind, label) for a signal that can mean a person, else None."""
    if entity_id in DOOR_ENTITIES:
        return 'door', DOOR_ENTITIES[entity_id]
    if entity_id in PERSON_ENTITIES:
        return 'person', PERSON_ENTITIES[entity_id]
    if entity_id in ZONE_ENTITIES:
        # A ZONE IS CONTEXT, NOT AN ARRIVAL (2026-10-28). `business_area_occupied` and
        # `control_room_occupied` stay on for long stretches, so letting them open or extend a
        # visit glued unrelated arrivals into one and labelled every visit with rooms rather
        # than cameras. They are recorded, and they never start or stretch a visit.
        return 'zone', ZONE_ENTITIES[entity_id]
    if entity_id.startswith('event.') and 'keypad' in entity_id:
        return 'credential', 'keypad'
    if entity_id.endswith(HUMAN_SUFFIX):
        cam = entity_id[len('binary_sensor.'):-len(HUMAN_SUFFIX)]
        return 'person', cam
    return None


def load_signals(conn: sqlite3.Connection, since: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT rowid, occurred_at, entity_id, new_state FROM security_event "
        "WHERE occurred_at >= ? ORDER BY occurred_at", (since.isoformat(),)).fetchall()
    out = []
    for rid, occurred_at, entity_id, new_state in rows:
        c = classify(entity_id or '')
        if not c:
            continue
        kind, label = c
        # a detector turning OFF is bookkeeping, not an arrival; door contacts keep both edges
        if kind == 'person' and (new_state or '').lower() != 'on':
            continue
        if kind == 'zone' and (new_state or '').lower() != 'on':
            continue
        if kind == 'zone':
            # keep for context, but flagged so the builder does not let it extend a visit
            out.append({'row': rid, 'at': occurred_at, 'entity': entity_id,
                        'state': new_state, 'kind': 'zone', 'label': label})
            continue
        out.append({'row': rid, 'at': occurred_at, 'entity': entity_id, 'state': new_state,
                    'kind': kind, 'label': label})
    return out


def build_visits(signals: list[dict], now: datetime) -> list[dict]:
    visits: list[dict] = []
    current: dict | None = None
    for sig in signals:
        at = parse(sig['at'])
        if current and (at - current['last']).total_seconds() > GAP_SECONDS:
            visits.append(current)
            current = None
        if current is None:
            current = {'start': at, 'last': at, 'signals': [], 'doors': set(),
                       'cameras': set(), 'subjects': set(), 'has_person': False}
        if sig['kind'] != 'zone':
            current['last'] = at
        current['signals'].append(sig)
        if sig['kind'] == 'door':
            current['doors'].add(sig['label'])
        elif sig['kind'] == 'person':
            # A KEYPAD PRESS IS NOT A PERSON DETECTED (2026-10-28). Counting credentials as people
            # made the page claim "16 with a person" on a day when several visits were the owner
            # typing a code and nothing else. A code is evidence that a credential was used; only a
            # person detector is evidence that a person was there.
            current['has_person'] = True
            current['cameras'].add(sig['label'])
        elif sig['kind'] == 'credential':
            current.setdefault('creds', set()).add(sig['label'])
        elif sig['kind'] == 'zone':
            current.setdefault('zones', set()).add(sig['label'])
    if current:
        visits.append(current)

    out = []
    for v in visits:
        if not v['doors'] and not v['has_person']:
            continue   # zones alone are not an arrival
        closed = (now - v['last']).total_seconds() > GAP_SECONDS
        out.append({
            'id': v['start'].strftime('%Y%m%dT%H%M%S'),
            'started_at': v['start'].isoformat(),
            'ended_at': (v['last'] + timedelta(seconds=GAP_SECONDS)).isoformat() if closed else None,
            'last_signal': v['last'].isoformat(),
            'doors': sorted(v['doors']),
            'cameras': sorted(v['cameras']),
            'zones': sorted(v.get('zones') or []),
            'subjects': sorted(v['subjects']),
            'signal_count': len(v['signals']),
            'has_person': int(v['has_person']),
            'signals': v['signals'],
        })
    return out


def write_visits(conn: sqlite3.Connection, visits: list[dict], since: datetime) -> None:
    conn.execute("DELETE FROM shop_visit_signal WHERE visit_id IN "
                 "(SELECT id FROM shop_visit WHERE started_at >= ?)", (since.isoformat(),))
    conn.execute("DELETE FROM shop_visit WHERE started_at >= ?", (since.isoformat(),))
    built = datetime.now(timezone.utc).isoformat()
    for v in visits:
        conn.execute(
            "INSERT OR REPLACE INTO shop_visit (id, started_at, ended_at, last_signal, doors, "
            "cameras, subjects, signal_count, has_person, built_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (v['id'], v['started_at'], v['ended_at'], v['last_signal'],
             json.dumps(v['doors']), json.dumps(v['cameras']), json.dumps(v['subjects']),
             v['signal_count'], v['has_person'], built))
        for s in v['signals']:
            conn.execute(
                "INSERT OR IGNORE INTO shop_visit_signal (visit_id, event_row, entity_id, "
                "new_state, occurred_at) VALUES (?,?,?,?,?)",
                (v['id'], s['row'], s['entity'], s['state'], s['at']))
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='24h')
    ap.add_argument('--rebuild', action='store_true')
    ap.add_argument('--show', action='store_true')
    args = ap.parse_args()

    n = int(args.since.rstrip('h')) if args.since.endswith('h') else int(args.since)
    since = datetime.now(timezone.utc) - timedelta(hours=n)
    now = datetime.now(timezone.utc)

    conn = sqlite3.connect(DB)
    try:
        conn.executescript(SCHEMA)
        signals = load_signals(conn, since)
        visits = build_visits(signals, now)
        print('%d signals that can mean a person in the last %dh -> %d visit(s)'
              % (len(signals), n, len(visits)))
        for v in visits[-20:]:
            dur = ''
            if v['ended_at']:
                dur = '%4d min' % round((parse(v['ended_at']) - parse(v['started_at'])).total_seconds() / 60)
            print('  %s  %-9s %-2d sig  person=%d  doors=%-22s cams=%s'
                  % (v['started_at'][11:16], dur, v['signal_count'], v['has_person'],
                     ','.join(v['doors']) or '-', ','.join(v['cameras']) or '-'))
        if args.rebuild and not args.show:
            write_visits(conn, visits, since)
            print('\nwritten: %d visit(s) from %s' % (len(visits), since.isoformat()[:19]))
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
