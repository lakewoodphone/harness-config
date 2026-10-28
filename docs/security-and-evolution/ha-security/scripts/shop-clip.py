#!/usr/bin/env python3
"""Record a clip for a visit that is happening now.

THE HARD CONSTRAINT, stated up front because it shapes the whole feature: `camera.record` records
from the moment it is called. It cannot go back. So a clip exists only for a visit that is open or
has just ended — an event from this morning can never have one. That is why the page must show
"no clip" honestly for older events rather than a player that fails.

What this does:
  * finds person-visits that are open or ended in the last RECENT_MINUTES;
  * picks the camera that would have seen them (shop-door threshold for a shop-door visit, the
    outside doorbell otherwise);
  * records into `/media/shop/<visit_id>.mp4`, where Home Assistant serves it and the review page
    can resolve a signed URL at request time;
  * records the outcome in `shop_visit_media` with kind='clip', including the failure reason.

usage:
  python3 shop-clip.py --recent 10          # record for visits open/ended in the last 10 minutes
  python3 shop-clip.py --visit <id>         # one visit, explicitly
  python3 shop-clip.py --recent 10 --dry
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import ssl
from datetime import datetime, timedelta, timezone

DB = '/root/authority.db'
ENV = '/opt/company/.env'
MEDIA_DIR = '/media/shop'          # on the Home Assistant host, served via media_source

SHOP_DOOR_CAM = 'camera.cam_front_hallway_main'
OUTSIDE_CAM = 'camera.reolink_video_doorbell_poe_clear'
CLIP_SECONDS = 25                  # long enough to watch a person move, short enough to store


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def choose_camera(doors: list[str], has_person: int) -> str:
    if 'shop_door' in doors:
        return SHOP_DOOR_CAM
    return OUTSIDE_CAM


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--recent', type=int, default=10)
    ap.add_argument('--visit')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    try:
        if args.visit:
            rows = conn.execute("SELECT id, started_at, ended_at, doors, has_person FROM shop_visit "
                                "WHERE id=?", (args.visit,)).fetchall()
        else:
            # A CLIP MUST COVER THE VISIT, NOT MERELY BE ATTACHED TO IT (2026-10-28).
            # camera.record starts at the moment it is called, so recording for a visit that
            # began twenty minutes ago records an empty room and labels it with someone else's
            # arrival. Only visits that STARTED inside the last few minutes can honestly have a
            # clip; everything older gets an honest "no clip" instead.
            now = datetime.now(timezone.utc)
            since = (now - timedelta(minutes=args.recent)).isoformat()
            oldest_ok = (now - timedelta(seconds=CLIP_SECONDS + 90)).isoformat()
            rows = conn.execute(
                "SELECT id, started_at, ended_at, doors, has_person FROM shop_visit "
                "WHERE has_person=1 AND (ended_at IS NULL OR ended_at >= ?) AND started_at >= ? "
                "ORDER BY started_at", (since, oldest_ok)).fetchall()

        already = {r[0] for r in conn.execute(
            "SELECT DISTINCT visit_id FROM shop_visit_media WHERE kind='clip' AND result='ok'")}
        todo = [r for r in rows if r[0] not in already]
        print('%d person-visit(s) in range, %d already have a clip, %d to record'
              % (len(rows), len(rows) - len(todo), len(todo)))
        if not todo:
            return 0

        import websockets

        ha = (env('HA_URL') or '').rstrip('/')
        token = env('HA_TOKEN')
        ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
        kw: dict = {'max_size': 64 * 1024 * 1024}
        if ws_url.startswith('wss://'):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw['ssl'] = ctx

        async with websockets.connect(ws_url, **kw) as ws:
            await ws.recv()
            await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
            if json.loads(await ws.recv()).get('type') != 'auth_ok':
                print('auth failed')
                return 2
            ctr = {'id': 1}

            async def call(payload: dict) -> dict:
                payload = dict(payload)
                payload['id'] = ctr['id']
                ctr['id'] += 1
                await ws.send(json.dumps(payload))
                while True:
                    raw = json.loads(await ws.recv())
                    if raw.get('id') == payload['id']:
                        return raw

            for vid, started_at, ended_at, doors_json, has_person in todo:
                doors = json.loads(doors_json or '[]')
                cam = choose_camera(doors, has_person)
                target = '%s/%s.mp4' % (MEDIA_DIR, vid)
                if args.dry:
                    print('  would record %s from %s -> %s' % (vid, cam, target))
                    continue
                r = await call({'type': 'call_service', 'domain': 'camera', 'service': 'record',
                                'service_data': {'filename': target,
                                                 'duration': CLIP_SECONDS,
                                                 'lookback': 3},
                                'target': {'entity_id': cam}})
                ok = r.get('success', False)
                now = datetime.now(timezone.utc).isoformat()
                err = None if ok else str((r.get('error') or {}).get('message', 'call failed'))
                conn.execute(
                    "INSERT OR REPLACE INTO shop_visit_media (visit_id, camera_id, kind, path, "
                    "sha256, bytes, captured_at, result, error, clip_seconds) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (vid, cam, 'clip', target, None, None, now,
                     'ok' if ok else 'failed', err, CLIP_SECONDS if ok else None))
                print('  %s -> %s : %s' % (vid, cam.split('.')[-1], 'recording' if ok else err))
                # Home Assistant needs the recording to finish before the file exists
                await asyncio.sleep(CLIP_SECONDS + 6)
            conn.commit()
    finally:
        conn.close()
    return 0


async def selftest() -> int:
    """Prove the whole clip chain on demand, without touching any visit.

    Records a short clip, waits, then resolves it through media_source and fetches the signed URL
    the way a browser would. Nothing is attached to a visit: this is a test of the plumbing, not
    evidence about an event.
    """
    import time as _t

    import websockets

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
    kw: dict = {'max_size': 16 * 1024 * 1024}
    if ws_url.startswith('wss://'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw['ssl'] = ctx
    name = '%s/selftest_%d.mp4' % (MEDIA_DIR, int(_t.time()))
    async with websockets.connect(ws_url, **kw) as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        await ws.recv()
        ctr = {'id': 1}

        async def call(payload):
            payload = dict(payload)
            payload['id'] = ctr['id']
            ctr['id'] += 1
            await ws.send(json.dumps(payload))
            while True:
                raw = json.loads(await ws.recv())
                if raw.get('id') == payload['id']:
                    return raw

        r = await call({'type': 'call_service', 'domain': 'camera', 'service': 'record',
                        'service_data': {'filename': name, 'duration': 6, 'lookback': 2},
                        'target': {'entity_id': SHOP_DOOR_CAM}})
        print('1. record requested :', r.get('success'))
        await asyncio.sleep(11)
        rel = name.replace('/media/', '')
        mid = 'media-source://media_source/local/' + rel.lstrip('/')
        res = await call({'type': 'media_source/resolve_media', 'media_content_id': mid})
        url = (res.get('result') or {}).get('url')
        print('2. resolved         :', bool(url), (url or '')[:60])
        if not url:
            return 1
        full = url if url.startswith('http') else ha + url
        import urllib.request as _u
        with _u.urlopen(full, timeout=30) as resp:
            body = resp.read()
        head = body[4:8]
        ok = resp.status == 200 and head == b'ftyp'
        print('3. fetched          :', resp.status, resp.headers.get('Content-Type'),
              '%d bytes  mp4 magic=%s' % (len(body), head == b'ftyp'))
        return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(asyncio.run(selftest()))
    raise SystemExit(asyncio.run(main()))
