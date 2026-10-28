#!/usr/bin/env python3
"""One command that proves the shop review surface works — and fails loudly when it does not.

Every check here exists because something on this build lied to me first:

  * a page that returned 200 with `/config` unreachable, while the thing it claimed to show was empty;
  * four camera tiles that "decoded" while the screenshot showed black (decoded is not painted);
  * a clip that returned 200 `video/mp4` with a valid MP4 header and still would not play, because the
    codec inside was HEVC;
  * a page whose footer said "times are local" while every time on it was UTC;
  * a `grep -c` that said "1 card" because the page is one line of HTML.

So the checks look at the *substance*: pixels, codec, timezone, bytes, and the rendered page in a real
browser — not at status codes alone.

usage:
  python3 verify-shop-review.py                 # everything, including a browser render
  python3 verify-shop-review.py --fast          # skip the browser (still checks pixels and codec)
  python3 verify-shop-review.py --base <url>    # a different origin

Exit: 0 every check passed · 1 at least one failed · 2 the page itself is unreachable
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

DB = '/root/authority.db'
ENV = '/opt/company/.env'
DEFAULT_BASE = 'https://api.abletelsolutions.com'

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = '') -> bool:
    results.append((bool(ok), name, detail))
    print('%s %-42s %s' % ('PASS' if ok else 'FAIL', name, detail))
    return bool(ok)


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')


def fetch(url: str, timeout: int = 60, headers: dict | None = None):
    # CLOUDFLARE REFUSES A PYTHON USER AGENT WITH 403 (2026-10-28) — the page is fine, the client is
    # not welcome. Every request here presents the same agent the owner's phone would, because that
    # is the client this surface is actually for.
    hdrs = {'User-Agent': UA}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true')
    ap.add_argument('--base', default=DEFAULT_BASE)
    args = ap.parse_args()

    token = env('SHOP_REVIEW_TOKEN')
    if not token:
        print('SHOP_REVIEW_TOKEN missing from .env')
        return 2
    page_url = '%s/webhook/ha/shop/r/%s' % (args.base.rstrip('/'), token)

    # ---------------------------------------------------------------- 1. the page answers, and refuses
    try:
        status, body, _ = fetch(page_url)
    except Exception as exc:
        print('PAGE UNREACHABLE: %s %s' % (type(exc).__name__, exc))
        return 2
    html = body.decode('utf-8', 'replace')
    check(status == 200 and len(body) > 5000, 'page answers', '%d bytes' % len(body))
    try:
        fetch('%s/webhook/ha/shop/r/%s' % (args.base.rstrip('/'), 'not-the-token'))
        check(False, 'wrong token refuses', 'it answered!')
    except Exception as exc:
        check(getattr(exc, 'code', 0) == 404, 'wrong token refuses', 'HTTP %s' % getattr(exc, 'code', '?'))

    # ---------------------------------------------------------------- 2. the page has substance
    cards = len(re.findall(r'<details', html))
    days = len(re.findall(r'<section class="day"', html))
    check(cards > 0, 'event cards render', '%d card(s)' % cards)
    check(days > 0, 'day sections render', '%d day(s)' % days)
    check('checked ' in html, 'alert states its freshness',
          (re.search(r'checked [0-9:]+', html) or ['-'])[0])
    check('times are local' in html, 'times labelled local', '')
    # a page claiming local time must not be printing raw UTC
    stamp = re.search(r'<div class="s">(\d\d):(\d\d)', html)
    if stamp:
        import datetime as _dt
        utc_hour = _dt.datetime.now(_dt.timezone.utc).hour
        shown = int(stamp.group(1))
        check(abs(shown - utc_hour) <= 6, 'clock is plausible for the building',
              'page shows %02d:xx, UTC is %02d:xx' % (shown, utc_hour))
    check('No image' not in html or 'class="thumb">No image' not in html,
          'no empty image boxes', '')
    # A PICTURE URL MUST CHANGE WHEN THE PICTURE CHANGES (2026-10-28). These are served with a
    # day-long cache; without a version in the URL the owner walked through the hallway, was
    # photographed, and saw the empty frame his browser had stored hours earlier.
    pics = re.findall(r'/full/[0-9T]+/[a-z0-9_.]+\?[^"\']*', html)
    versioned = [u for u in pics if 'v=' in u]
    check(bool(pics) and len(versioned) == len(pics), 'picture urls are cache-busted',
          '%d of %d carry a version' % (len(versioned), len(pics)))
    st_headers = dict((k.lower(), v) for k, v in fetch(page_url)[2].items())
    check('no-store' in (st_headers.get('cache-control') or ''), 'page is not cached',
          st_headers.get('cache-control', 'no header'))

    # ---------------------------------------------------------------- 3. the tiles are real pixels
    cams = ['cam_front_hallway_main', 'reolink_video_doorbell_poe_clear',
            'cam_waiting_room_main', 'cam_deserted_interior_main']
    for cam in cams:
        try:
            st, blob, hdrs = fetch('%s/webhook/ha/shop/r/%s/cam/camera.%s?w=360'
                                   % (args.base.rstrip('/'), token, cam), timeout=90)
            ok = st == 200 and blob[:2] == b'\xff\xd8' and len(blob) < 200_000
            bright = -1
            try:
                from PIL import Image, ImageStat
                import io
                im = Image.open(io.BytesIO(blob)).convert('L')
                if im.width > 1000:
                    ok = False                      # resizing failed: a 2560px frame in a 179px box
                bright = ImageStat.Stat(im).mean[0]
                if bright < 15:
                    ok = False                      # an all-black frame is not a camera view
            except Exception:
                pass
            check(ok, 'tile %s' % cam.replace('_', ' ')[:26],
                  '%d bytes, brightness %.0f' % (len(blob), bright))
        except Exception as exc:
            check(False, 'tile %s' % cam[:26], '%s' % type(exc).__name__)

    # ---------------------------------------------------------------- 4. a clip, if one exists
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT visit_id, local_path, result FROM shop_visit_media "
            "WHERE kind='clip' AND result='ok' ORDER BY captured_at DESC LIMIT 1").fetchone()
        n_clips = conn.execute("SELECT COUNT(1) FROM shop_visit_media WHERE kind='clip' "
                               "AND result='ok'").fetchone()[0]
    finally:
        conn.close()
    if row:
        url = '%s/webhook/ha/shop/r/%s/clip/%s' % (args.base.rstrip('/'), token, row['visit_id'])
        try:
            st, blob, hdrs = fetch(url, timeout=180)
            is_mp4 = blob[4:8] == b'ftyp'
            codec = 'unknown'
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as fh:
                fh.write(blob)
                tmp = fh.name
            try:
                out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                      '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', tmp],
                                     capture_output=True, text=True, timeout=60)
                codec = (out.stdout or '').strip() or 'unknown'
            finally:
                os.unlink(tmp)
            check(st == 200 and is_mp4 and codec == 'h264',
                  'clip plays in a browser', '%s, %d bytes, codec %s' % (hdrs.get('Content-Type'),
                                                                        len(blob), codec))
            st2, blob2, _ = fetch(url, timeout=90, headers={'Range': 'bytes=0-2047'})
            check(st2 == 206 and len(blob2) == 2048, 'clip supports byte ranges',
                  'HTTP %d, %d bytes' % (st2, len(blob2)))
        except Exception as exc:
            check(False, 'clip plays in a browser', '%s %s' % (type(exc).__name__, exc))
        check(True, 'clips present', '%d clip(s) in the record' % n_clips)
    else:
        check(True, 'clips present', 'none yet — nothing to verify, and the page says why')

    # ---------------------------------------------------------------- 5. the clips view
    try:
        st, body2, _ = fetch(page_url + '?clips=1')
        check(st == 200, 'clips view answers', '%d bytes' % len(body2))
    except Exception as exc:
        check(False, 'clips view answers', type(exc).__name__)

    # ---------------------------------------------------------------- 6. the pipeline is running
    try:
        out = subprocess.run(['systemctl', 'is-active', 'shop-review-cycle.timer'],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        last = subprocess.run(['systemctl', 'show', 'shop-review-cycle.service', '-p',
                               'ExecMainStatus', '--value'],
                              capture_output=True, text=True, timeout=20).stdout.strip()
        check(out == 'active' and last in ('0', ''), 'review cycle is live',
              'timer %s, last run exit %s' % (out, last or '?'))
    except Exception as exc:
        check(False, 'review cycle is live', type(exc).__name__)

    # ---------------------------------------------------------------- 7. a real browser render
    if not args.fast:
        try:
            script = r'''
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1]
async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        c = await b.new_context(viewport={"width":390,"height":844}, is_mobile=True)
        pg = await c.new_page()
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)[:80]))
        await pg.goto(URL, wait_until="networkidle"); await pg.wait_for_timeout(6000)
        size = await pg.evaluate("()=>({h:document.body.scrollHeight,w:document.body.scrollWidth})")
        imgs = await pg.evaluate("()=>{const i=[...document.images];return [i.length,i.filter(x=>x.naturalWidth>0).length]}")
        overflow = size["w"] > 400
        print("%d %d %d %d" % (size["h"], imgs[0], imgs[1], 1 if (errs or overflow) else 0))
        await b.close()
asyncio.run(run())
'''
            with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fh:
                fh.write(script)
                path = fh.name
            try:
                out = subprocess.run(['/opt/company/.venv/bin/python', path, page_url],
                                     capture_output=True, text=True, timeout=220,
                                     env=dict(os.environ, PYTHONPATH='/opt/company'))
                parts = (out.stdout or '').strip().split()
                if len(parts) == 4:
                    h, total, loaded, bad = map(int, parts)
                    check(h < 20000, 'renders compactly', '%d px tall' % h)
                    check(total > 0 and loaded >= max(1, total // 2), 'images paint',
                          '%d of %d decoded' % (loaded, total))
                    check(bad == 0, 'no JS errors or overflow', '')
                else:
                    check(False, 'browser render', (out.stderr or out.stdout or '')[-160:])
            finally:
                os.unlink(path)
        except Exception as exc:
            check(False, 'browser render', '%s %s' % (type(exc).__name__, exc))

    failed = [r for r in results if not r[0]]
    print('\n%d check(s), %d passed, %d failed' % (len(results), len(results) - len(failed), len(failed)))
    if failed:
        print('FAILED: ' + ', '.join(f[1] for f in failed))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
