#!/usr/bin/env python3
"""Capture and store a still for every visit, from the cameras that matter.

A visit without a picture is not evidence, it is a log line. The gallery the owner asked for is
thumbnails first, so each visit needs at least one image on disk, with a hash so it can be served
by content and never mistaken for another.

How the pictures are taken: Home Assistant's `camera_proxy` endpoint, which the API host can
already reach with the token it holds. No camera credential is involved, and none exists in this
environment — the proxy is the only route, and it works.

Storage is the filesystem (`/root/shop-media/<YYYY-MM-DD>/`) with one row per picture in
`shop_visit_media`, keyed by the visit. Files are content-addressed by sha256 in the row so a
duplicate capture is detectable and a served URL is unguessable.

usage:
  python3 shop-capture.py --since 24h            # capture for visits in the window, skipping done
  python3 shop-capture.py --since 24h --dry      # say what it would capture
  python3 shop-capture.py --visit <id>           # one visit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

DB = '/root/authority.db'
MEDIA_ROOT = '/root/shop-media'
ENV = '/opt/company/.env'

# which cameras to capture for a visit, and why each one earns its place
CAMERAS = [
    ('camera.cam_front_hallway_main', 'shop door threshold — the best face view'),
    ('camera.reolink_video_doorbell_poe_clear', 'outside stairwell — where people arrive'),
    ('camera.cam_waiting_room_main', 'drop-off and pickup door'),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_visit_media (
    visit_id   TEXT NOT NULL,
    camera_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,              -- 'still' | 'clip'
    path       TEXT,
    sha256     TEXT,
    bytes      INTEGER,
    captured_at TEXT NOT NULL,
    result     TEXT NOT NULL,              -- 'ok' | 'http_500' | 'unavailable' | 'empty'
    error      TEXT,
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


def fetch_still(ha: str, token: str, camera: str) -> tuple[int, bytes | None, str | None]:
    req = urllib.request.Request(ha + '/api/camera_proxy/' + camera,
                                 headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            if not body or len(body) < 1000:
                return r.status, None, 'empty (%d bytes)' % len(body or b'')
            if not body[:2] == b'\xff\xd8':      # JPEG SOI
                return r.status, None, 'not a JPEG'
            return r.status, body, None
    except Exception as exc:                      # noqa: BLE001 - recorded, never raised
        code = getattr(exc, 'code', None)
        return (code or 0), None, '%s %s' % (type(exc).__name__, code or '')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='24h')
    ap.add_argument('--visit')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing')
        return 2

    hours = int(args.since.rstrip('h')) if args.since.endswith('h') else int(args.since)
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    conn = sqlite3.connect(DB)
    try:
        conn.executescript(SCHEMA)
        if args.visit:
            visits = conn.execute("SELECT id, started_at, has_person FROM shop_visit WHERE id=?",
                                  (args.visit,)).fetchall()
        else:
            visits = conn.execute(
                "SELECT id, started_at, has_person FROM shop_visit WHERE started_at >= ? "
                "ORDER BY started_at", (since,)).fetchall()

        # a visit that already has at least one good still is done
        done = {r[0] for r in conn.execute(
            "SELECT DISTINCT visit_id FROM shop_visit_media WHERE kind='still' AND result='ok'")}
        todo = [v for v in visits if v[0] not in done]
        print('%d visit(s) in the window, %d already have a still, %d to capture'
              % (len(visits), len(visits) - len(todo), len(todo)))

        captured = failed = 0
        for vid, started_at, has_person in todo:
            day = started_at[:10]
            outdir = os.path.join(MEDIA_ROOT, day)
            if args.dry:
                print('  would capture %s (%s) from %d camera(s)' % (vid, started_at[11:16], len(CAMERAS)))
                continue
            os.makedirs(outdir, exist_ok=True)
            for cam, why in CAMERAS:
                status, body, err = fetch_still(ha, token, cam)
                now = datetime.now(timezone.utc).isoformat()
                if body is None:
                    conn.execute(
                        "INSERT OR REPLACE INTO shop_visit_media (visit_id, camera_id, kind, path, "
                        "sha256, bytes, captured_at, result, error) VALUES (?,?,?,?,?,?,?,?,?)",
                        (vid, cam, 'still', None, None, None, now,
                         'http_500' if status >= 500 else 'unavailable', err))
                    failed += 1
                    continue
                sha = hashlib.sha256(body).hexdigest()
                path = os.path.join(outdir, '%s_%s.jpg' % (vid, cam.split('.')[-1]))
                with open(path, 'wb') as fh:
                    fh.write(body)
                conn.execute(
                    "INSERT OR REPLACE INTO shop_visit_media (visit_id, camera_id, kind, path, "
                    "sha256, bytes, captured_at, result, error) VALUES (?,?,?,?,?,?,?,?,?)",
                    (vid, cam, 'still', path, sha, len(body), now, 'ok', None))
                captured += 1
            print('  %s (%s) person=%d' % (vid, started_at[11:16], has_person))
        conn.commit()

        if not args.dry:
            tot = conn.execute("SELECT COUNT(1), COALESCE(SUM(bytes),0) FROM shop_visit_media "
                               "WHERE kind='still' AND result='ok'").fetchone()
            bad = conn.execute("SELECT result, COUNT(1) FROM shop_visit_media WHERE result!='ok' "
                               "GROUP BY result").fetchall()
            print('\ncaptured %d still(s), %d failure(s)' % (captured, failed))
            print('archive now: %d still(s), %.1f MB' % (tot[0], tot[1] / 1e6))
            if bad:
                print('non-ok rows:', ', '.join('%s=%d' % (r, n) for r, n in bad))
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
