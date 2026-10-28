#!/usr/bin/env python3
"""Photograph the moment a person actually triggers a sensor — not the moment a timer fires.

WHY THIS EXISTS (2026-10-28, the owner's own report):

    "someone just came a few minutes ago to the hallway to pick something up and i don't see any pics of him"

He was right, and the reason is structural. The gallery was fed by a three-minute timer, and a person picking
something up is in the hallway for fifteen seconds. Measured: the 18:18 visit's newest still was taken at 18:28 and
shows **an empty hallway** — the timer fired ten minutes after he had gone. A periodic capture can never reliably
photograph an arrival; it samples the room, it does not watch the door.

So this watches the event record instead. The listener already writes every person, door and keypad signal into
`security_event` in real time; this polls that table a few times a second, and when a signal that means "a person is
here" lands, it takes the picture **within seconds, while they are still in frame**.

Rules that keep it honest:
  * only person-capable signals trigger a capture (person detectors, door contacts, keypad, occupied zones);
  * a cooldown stops one arrival producing twenty pictures;
  * every capture records when it was taken, and the page shows that time, so a picture of "three seconds after the
    door opened" is never presented as the door opening itself;
  * if the cameras fail, the failure is stored, not hidden.

usage:
  python3 shop-live-capture.py                  # watch, forever (this is what the service runs)
  python3 shop-live-capture.py --replay 300     # process signals from the last 300 s, then exit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone

DB = '/root/authority.db'
ENV = '/opt/company/.env'
MEDIA_ROOT = '/root/shop-media'

CAMERAS = [
    ('camera.cam_front_hallway_main', 'shop door threshold'),
    ('camera.reolink_video_doorbell_poe_clear', 'outside stairwell'),
    ('camera.cam_waiting_room_main', 'drop-off and pickup'),
]

# what counts as "a person is here". Zones are context, not triggers, so they are deliberately absent:
# a zone going "occupied" can be a fan or a shadow, and one arrival would fire four cameras.
TRIGGERS = ('_smart_motion_human', '_person', '_visitor', 'door_contact', 'keypad', 'presence')

COOLDOWN_S = 45          # one arrival, one round of pictures
MAX_PER_VISIT_HOUR = 8   # an occupancy sensor alone fires ~60 times an hour; without this cap one
                         # afternoon would write hundreds of near-identical pictures
POLL_S = 3.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_visit_media (
    visit_id   TEXT NOT NULL,
    camera_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    path       TEXT,
    sha256     TEXT,
    bytes      INTEGER,
    captured_at TEXT NOT NULL,
    result     TEXT NOT NULL,
    error      TEXT,
    clip_seconds INTEGER,
    clip_offset_s INTEGER,
    local_path TEXT,
    PRIMARY KEY (visit_id, camera_id, kind)
);
CREATE INDEX IF NOT EXISTS ix_vmedia_visit ON shop_visit_media(visit_id);
"""


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def fetch_still(ha: str, token: str, camera: str) -> tuple[bytes | None, str | None]:
    req = urllib.request.Request(ha + '/api/camera_proxy/' + camera,
                                 headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read()
        if not body or len(body) < 1000 or body[:2] != b'\xff\xd8':
            return None, 'not a JPEG (%d bytes)' % len(body or b'')
        return body, None
    except Exception as exc:
        return None, '%s %s' % (type(exc).__name__, getattr(exc, 'code', ''))


def visit_for(conn: sqlite3.Connection, when: str) -> str | None:
    """The visit this moment belongs to: the open one, else the nearest that contains it."""
    row = conn.execute(
        "SELECT id FROM shop_visit WHERE started_at <= ? AND (ended_at IS NULL OR ended_at >= ?) "
        "ORDER BY started_at DESC LIMIT 1", (when, when)).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT id FROM shop_visit WHERE started_at <= ? ORDER BY started_at DESC LIMIT 1",
        (when,)).fetchone()
    return row[0] if row else None


def is_trigger(entity: str) -> bool:
    """A sensor or an event, never an automation.

    Measured against an hour of record: the substring list matched
    `automation.phoenix_access_control_master_presence` and `automation.phoenix_keypad_event_handler` as
    well as the real sensors. An automation firing is a consequence of a signal, not the signal, so
    counting it would take the same photograph twice and inflate the record with moments nothing
    happened in.
    """
    e = entity.lower()
    if any(bad in e for bad in ('pin_code', 'password', 'token', 'secret')):
        return False
    if e.startswith(('automation.', 'input_', 'script.', 'scene.')):
        return False
    return any(t in e for t in TRIGGERS)


def shoot(conn: sqlite3.Connection, ha: str, token: str, when: str, why: str) -> int:
    vid = visit_for(conn, when)
    if not vid:
        return 0
    recent = conn.execute(
        "SELECT COUNT(1) FROM shop_visit_media WHERE visit_id=? AND kind='still' "
        "AND captured_at > datetime('now','-1 hour')", (vid,)).fetchone()[0]
    if recent >= MAX_PER_VISIT_HOUR * 3:
        return 0
    day = when[:10]
    outdir = os.path.join(MEDIA_ROOT, day)
    os.makedirs(outdir, exist_ok=True)
    took = 0
    for cam, _why in CAMERAS:
        body, err = fetch_still(ha, token, cam)
        now = datetime.now(timezone.utc).isoformat()
        if body is None:
            conn.execute(
                "INSERT OR REPLACE INTO shop_visit_media (visit_id, camera_id, kind, path, sha256, "
                "bytes, captured_at, result, error) VALUES (?,?,?,?,?,?,?,?,?)",
                (vid, cam, 'still', None, None, None, now,
                 'http_500' if (err and '500' in err) else 'unavailable', err))
            continue
        sha = hashlib.sha256(body).hexdigest()
        path = os.path.join(outdir, '%s_%s.jpg' % (vid, cam.split('.')[-1]))
        with open(path, 'wb') as fh:
            fh.write(body)
        conn.execute(
            "INSERT OR REPLACE INTO shop_visit_media (visit_id, camera_id, kind, path, sha256, "
            "bytes, captured_at, result, error) VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, cam, 'still', path, sha, len(body), now, 'ok', None))
        took += 1
    conn.commit()
    print('[%s] %s -> visit %s, %d picture(s)' % (datetime.now().strftime('%H:%M:%S'), why, vid, took),
          flush=True)
    return took


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--replay', type=int, default=0)
    args = ap.parse_args()

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing')
        return 2

    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)

    if args.replay:
        since = (datetime.now(timezone.utc) - timedelta(seconds=args.replay)).isoformat()
        rows = conn.execute("SELECT occurred_at, entity_id FROM security_event WHERE occurred_at >= ? "
                            "ORDER BY occurred_at", (since,)).fetchall()
        hits = [(w, e) for w, e in rows if is_trigger(e)]
        print('%d signal(s) in the window, %d person-capable' % (len(rows), len(hits)))
        for when, entity in hits[-5:]:
            print('  %s %s' % (when[11:19], entity.replace('binary_sensor.', '')))
        last = 0.0
        for when, entity in hits:
            t = datetime.fromisoformat(when.replace('Z', '+00:00')).timestamp()
            if t - last < COOLDOWN_S:
                continue
            shoot(conn, ha, token, when, entity.replace('binary_sensor.', ''))
            last = t
        conn.close()
        return 0

    print('watching for person-capable signals; poll every %.1fs, cooldown %ds'
          % (POLL_S, COOLDOWN_S), flush=True)
    last_seen = datetime.now(timezone.utc).isoformat()
    last_shot = 0.0
    while True:
        try:
            rows = conn.execute(
                "SELECT occurred_at, entity_id FROM security_event WHERE occurred_at > ? "
                "ORDER BY occurred_at", (last_seen,)).fetchall()
            for when, entity in rows:
                last_seen = when
                if not is_trigger(entity):
                    continue
                t = datetime.fromisoformat(when.replace('Z', '+00:00')).timestamp()
                if t - last_shot < COOLDOWN_S:
                    continue
                last_shot = t
                shoot(conn, ha, token, when, entity.replace('binary_sensor.', ''))
        except Exception as exc:
            print('watch error: %s %s' % (type(exc).__name__, exc), flush=True)
        time.sleep(POLL_S)


if __name__ == '__main__':
    raise SystemExit(main())
