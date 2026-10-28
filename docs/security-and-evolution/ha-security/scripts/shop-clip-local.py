#!/usr/bin/env python3
"""Pull a recorded clip onto the authority and make it playable everywhere.

WHY THIS EXISTS (2026-10-28). The first real clip recorded fine and then failed to play in the
browser with MEDIA_ERR_SRC_NOT_SUPPORTED. The file was not corrupt: it is **HEVC** (`hev1` /
`hvcC`), which Chrome cannot decode. Safari on an iPhone can — but a security page that plays on one
browser and shows an error on every other is a trap, and the owner cannot be expected to know which
device is allowed to work.

So the recording is copied here and transcoded to H.264 with `-movflags +faststart` (so it starts
playing before the whole file arrives) and served from local disk. That also removes the dependency
on Home Assistant's expiring signed URLs at playback time: the bytes are ours.

usage:
  python3 shop-clip-local.py              # every clip that is not yet local
  python3 shop-clip-local.py --dry
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import subprocess
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone

DB = '/root/authority.db'
ENV = '/opt/company/.env'
OUT_DIR = '/root/shop-media/clips'


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def probe(path: str) -> tuple[str, int]:
    """codec and width. Width matters as much as codec: an H.264 file can still be 14 MB of
    2560-pixel video, which is 4.4 Mbit/s of mobile data to watch someone cross a hallway."""
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                              '-show_entries', 'stream=codec_name,width', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=60)
        parts = (out.stdout or '').strip().split(',')
        codec = parts[0].strip() if parts else ''
        width = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        return codec, width
    except Exception:
        return '', 0


def transcode(src: str, dst: str) -> tuple[bool, str]:
    cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
           '-i', src,
           '-map', '0:v:0',
           # 1280 px wide, not 2560: a 25-second clip at full resolution measured 14 MB, which is
           # 4.4 Mbit/s of mobile data to watch a person cross a hallway. Scale down, keep it sharp
           # enough to recognise a face, and let the full-resolution stills carry the detail.
           '-vf', 'scale=1280:-2',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p',
           '-movflags', '+faststart',
           dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, (r.stderr or '')[-300:]
        return True, ''
    except Exception as exc:
        return False, '%s %s' % (type(exc).__name__, exc)


async def resolve(media_path: str) -> str | None:
    import websockets
    ha = (env('HA_URL') or '').rstrip('/')
    ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
    kw: dict = {'max_size': 8 * 1024 * 1024}
    if ws_url.startswith('wss://'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw['ssl'] = ctx
    rel = media_path.replace('/media/', '').lstrip('/')
    async with websockets.connect(ws_url, **kw) as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'access_token': env('HA_TOKEN')}))
        await ws.recv()
        await ws.send(json.dumps({'id': 1, 'type': 'media_source/resolve_media',
                                  'media_content_id': 'media-source://media_source/local/' + rel}))
        while True:
            raw = json.loads(await ws.recv())
            if raw.get('id') == 1:
                url = (raw.get('result') or {}).get('url')
                if url and url.startswith('/'):
                    url = ha + url
                return url


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shop_visit_media)")}
    if 'local_path' not in cols:
        conn.execute("ALTER TABLE shop_visit_media ADD COLUMN local_path TEXT")
        conn.commit()
        print('added shop_visit_media.local_path')

    rows = conn.execute(
        "SELECT visit_id, path FROM shop_visit_media WHERE kind='clip' AND result='ok' "
        "AND (local_path IS NULL OR local_path='')").fetchall()
    print('%d clip(s) to bring local' % len(rows))
    if args.dry:
        for vid, path in rows:
            print('  would localise', vid)
        return 0

    done = failed = 0
    for vid, media_path in rows:
        dst = os.path.join(OUT_DIR, vid + '.mp4')
        src = dst + '.src'
        try:
            url = await resolve(media_path)
            if not url:
                print('  %s: could not resolve' % vid)
                failed += 1
                continue
            with urllib.request.urlopen(url, timeout=120) as r, open(src, 'wb') as fh:
                fh.write(r.read())
            codec, width = probe(src)
            if codec == 'h264' and 0 < width <= 1280:
                os.replace(src, dst)
                note = 'h264 %dpx already' % width
            else:
                ok, err = transcode(src, dst)
                os.remove(src) if os.path.exists(src) else None
                if not ok:
                    print('  %s: transcode failed %s' % (vid, err[:120]))
                    failed += 1
                    continue
                note = '%s %dpx -> h264 1280px' % (codec or '?', width)
            size = os.path.getsize(dst)
            conn.execute("UPDATE shop_visit_media SET local_path=? WHERE visit_id=? AND kind='clip'",
                         (dst, vid))
            conn.commit()
            print('  %s: %s, %d bytes' % (vid, note, size))
            done += 1
        except Exception as exc:
            print('  %s: %s %s' % (vid, type(exc).__name__, str(exc)[:120]))
            failed += 1
    print('localised %d, failed %d' % (done, failed))
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
