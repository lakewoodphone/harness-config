"""The shop review surface — one page: live, recent, then the days back.

Design rules, all from the owner's own words and the review that followed them:
  * thumbnails first, text second;
  * the live situation at the top, then the most recent captures, then today, then yesterday;
  * every event expands to what actually happened (door, sensor, who, when, how long, every picture);
  * a clip plays when one exists, and when it does not the card says WHY instead of showing a dead player;
  * nothing claims more than the record holds — no "all clear", no confident blank.

Served server-side from the authority database, because that is where the visits, the pictures and the
clip references live. The browser never holds a Home Assistant token: cameras and clips are proxied
through this module.

The URL carries a long token (`/webhook/ha/shop/r/<token>`) rather than a login. That is the same trust model as
the MMS evidence host — unguessable rather than authenticated — and it is a deliberate, stated
trade-off: it can be moved behind the dashboard's session later without changing anything below.
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter()

DB = '/root/authority.db'
ENV = '/opt/company/.env'
MEDIA_ROOT = '/root/shop-media'

CSS = """
:root{--bg:#0b0d12;--card:#181d28;--line:#242b38;--txt:#e8ebf2;--muted:#98a2b3;--accent:#3b82f6;--warn:#f59e0b;--bad:#ef4444;--ok:#22c55e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
a{color:var(--accent);text-decoration:none}
.wrap{max-width:520px;margin:0 auto;padding:10px 12px 60px}
.bar{display:flex;align-items:center;justify-content:space-between;padding:6px 0 12px}
.bar h1{font-size:20px;margin:0;font-weight:650}
.chip{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:3px 9px}
h2{font-size:16px;margin:18px 0 8px;font-weight:600;display:flex;justify-content:space-between;align-items:baseline}
h2 span{font-size:12px;color:var(--muted);font-weight:400}
.grid{display:grid;gap:8px}
.g2{grid-template-columns:1fr 1fr}
.tile{position:relative;border-radius:10px;overflow:hidden;background:var(--card);aspect-ratio:16/9}
.tile img{width:100%;height:100%;object-fit:cover;display:block}
.tile .lbl{position:absolute;left:0;right:0;bottom:0;padding:14px 8px 6px;font-size:12px;background:linear-gradient(transparent,rgba(0,0,0,.78))}
.recent{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.recent a{display:block;position:relative;border-radius:10px;overflow:hidden;background:var(--card);aspect-ratio:1/1}
.recent img{width:100%;height:100%;object-fit:cover}
.recent .t{position:absolute;left:0;right:0;bottom:0;font-size:11px;padding:12px 6px 4px;background:linear-gradient(transparent,rgba(0,0,0,.8))}
.day{margin-top:22px}
.day .hdr{display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line)}
.day .hdr b{font-size:17px}
.day .hdr i{font-style:normal;font-size:12px;color:var(--muted)}
details.ev{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
details.ev>summary{display:flex;gap:10px;align-items:center;padding:8px;cursor:pointer;list-style:none}
details.ev>summary::-webkit-details-marker{display:none}
.thumb{width:88px;height:66px;border-radius:7px;overflow:hidden;background:#0f1420;flex:0 0 auto;display:grid;place-items:center;font-size:10px;color:var(--muted);text-align:center;line-height:1.15}
.thumb img{width:100%;height:100%;object-fit:cover}
.meta{min-width:0;flex:1}
.meta .t{font-size:15px;font-weight:600}
.meta .s{font-size:12px;color:var(--muted);margin-top:2px}
.badges{display:flex;gap:5px;margin-top:4px;flex-wrap:wrap}
.b{font-size:10px;border-radius:999px;padding:1px 7px;border:1px solid var(--line);color:var(--muted)}
.b.clip{color:#0b0d12;background:var(--accent);border-color:var(--accent);font-weight:600}
.b.warn{color:var(--warn);border-color:var(--warn)}
.body{padding:0 10px 12px}
.body video{width:100%;border-radius:8px;background:#000;margin:6px 0 8px}
.shots{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:8px 0}
.shots a{display:block;aspect-ratio:4/3;border-radius:6px;overflow:hidden;background:#0f1420}
.shots img{width:100%;height:100%;object-fit:cover}
table.sig{width:100%;border-collapse:collapse;font-size:12px;color:var(--muted)}
table.sig td{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top}
table.sig td.n{white-space:nowrap;color:var(--txt);padding-right:8px}
.note{font-size:12px;color:var(--muted);margin:6px 0}
.warnbox{font-size:12px;color:var(--warn)}
.empty{border:1px dashed var(--line);border-radius:10px;padding:18px;text-align:center;color:var(--muted);font-size:13px}
""".strip()


def env(key: str) -> str | None:
    try:
        for line in open(ENV, encoding='utf-8', errors='replace'):
            line = line.strip()
            if line.upper().startswith(key.upper() + '='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def ha_base() -> str:
    return (env('HA_URL') or '').rstrip('/')


def ha_get(path: str) -> tuple[int, bytes, str]:
    req = urllib.request.Request(ha_base() + path,
                                 headers={'Authorization': 'Bearer ' + (env('HA_TOKEN') or '')})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read(), r.headers.get('Content-Type', 'application/octet-stream')


def require(token: str) -> None:
    expected = env('SHOP_REVIEW_TOKEN') or ''
    if not expected or token != expected:
        raise HTTPException(status_code=404, detail='Not found')


def preferred_camera(doors: list[str], has_person: int) -> str:
    """Which camera would have seen this visit.

    Sorting the stills alphabetically put the hallway camera on every card — including the one
    labelled "Person outside" — because `cam_front_hallway_main` sorts first. A thumbnail that
    shows the wrong room is worse than no thumbnail: it looks like evidence and is not.
    """
    if 'shop_door' in doors:
        return 'camera.cam_front_hallway_main'
    if 'street_door' in doors or has_person:
        return 'camera.reolink_video_doorbell_poe_clear'
    if 'apartment_door' in doors:
        return 'camera.cam_front_hallway_main'
    return 'camera.cam_front_hallway_main'


def still_for(conn: sqlite3.Connection, visit_id: str, prefer: str | None = None) -> sqlite3.Row | None:
    rows = conn.execute(
        "SELECT camera_id, path, sha256, result FROM shop_visit_media "
        "WHERE visit_id=? AND kind='still' ORDER BY (result='ok') DESC, camera_id", (visit_id,)).fetchall()
    ok = [r for r in rows if r['result'] == 'ok' and r['path']]
    if prefer:
        for r in ok:
            if r['camera_id'] == prefer:
                return r
    return ok[0] if ok else None


def clip_for(conn: sqlite3.Connection, visit_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT camera_id, path, result, error FROM shop_visit_media "
        "WHERE visit_id=? AND kind='clip' LIMIT 1", (visit_id,)).fetchone()


def visit_title(v: sqlite3.Row) -> str:
    doors = json.loads(v['doors'] or '[]')
    person = bool(v['has_person'])
    if person and 'shop_door' in doors:
        return 'Person at the shop door'
    if person:
        return 'Person outside'
    if 'shop_door' in doors:
        return 'Shop door opened'
    if 'apartment_door' in doors:
        return 'Apartment door opened'
    if 'street_door' in doors:
        return 'Street door opened'
    return 'Activity'


def duration(v: sqlite3.Row) -> str:
    if not v['ended_at']:
        return 'open now'
    a = datetime.fromisoformat(v['started_at'].replace('Z', '+00:00'))
    b = datetime.fromisoformat(v['ended_at'].replace('Z', '+00:00'))
    m = int((b - a).total_seconds() // 60)
    if m < 1:
        return '<1 min'
    if m < 60:
        return '%d min' % m
    return '%dh %02dm' % (m // 60, m % 60)


def clock(iso: str | None) -> str:
    if not iso:
        return '--:--'
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).strftime('%H:%M')
    except Exception:
        return '--:--'


def day_label(d: str) -> str:
    today = datetime.now(timezone.utc).date()
    try:
        dd = datetime.fromisoformat(d).date()
    except Exception:
        return d
    delta = (today - dd).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Yesterday'
    if delta < 7:
        return dd.strftime('%A')
    return dd.strftime('%a, %d %b')


def render_visit(conn: sqlite3.Connection, v: sqlite3.Row, token: str) -> str:
    want = preferred_camera(json.loads(v['doors'] or '[]'), v['has_person'])
    st = still_for(conn, v['id'], want)
    cl = clip_for(conn, v['id'])
    if st:
        # WRAPPED IN THE SIZED BOX (2026-10-28). Without the wrapper the image is a direct child
        # of <summary> and renders at its natural 2560 px: one event card filled an entire phone
        # screen. The box is what makes a thumbnail a thumbnail.
        thumb = ('<div class="thumb"><img loading="lazy" src="/webhook/ha/shop/r/%s/full/%s/%s" alt=""></div>'
                 % (token, v['id'], html.escape(st['camera_id'])))
    else:
        thumb = '<div class="thumb">No image</div>'
    badges = []
    if cl and cl['result'] == 'ok':
        badges.append('<span class="b clip">&#9654; clip</span>')
    elif cl:
        badges.append('<span class="b warn">clip failed</span>')
    if v['signal_count'] and v['signal_count'] > 6:
        badges.append('<span class="b">%d signals</span>' % v['signal_count'])

    # the expanded body
    parts = []
    if cl and cl['result'] == 'ok':
        parts.append('<video controls preload="none" poster="/webhook/ha/shop/r/%s/img/%s" '
                     'src="/webhook/ha/shop/r/%s/clip/%s"></video>' % (token, v['id'], token, v['id']))
    elif cl:
        parts.append('<p class="warnbox">A clip was attempted and failed: %s</p>'
                     % html.escape(str(cl['error'] or 'unknown reason')))
    else:
        parts.append('<p class="note">No clip for this event — recording starts only when a visit '
                     'begins, so older events will never have one.</p>')

    shots = conn.execute("SELECT camera_id, path FROM shop_visit_media WHERE visit_id=? AND "
                         "kind='still' AND result='ok' ORDER BY camera_id", (v['id'],)).fetchall()
    if shots:
        cells = ''.join('<a href="/webhook/ha/shop/r/%s/full/%s/%s"><img loading="lazy" '
                        'src="/webhook/ha/shop/r/%s/full/%s/%s"></a>'
                        % (token, v['id'], html.escape(s['camera_id']), token, v['id'],
                           html.escape(s['camera_id'])) for s in shots)
        parts.append('<div class="shots">%s</div>' % cells)
    else:
        parts.append('<p class="note">No picture was saved for this event.</p>')

    sigs = conn.execute("SELECT occurred_at, entity_id, new_state FROM shop_visit_signal WHERE "
                        "visit_id=? ORDER BY occurred_at LIMIT 12", (v['id'],)).fetchall()
    if sigs:
        rows = ''.join(
            '<tr><td class="n">%s</td><td>%s %s</td></tr>'
            % (clock(s['occurred_at']),
               html.escape(s['entity_id'].replace('binary_sensor.', '').replace('_', ' ')),
               html.escape(str(s['new_state'] or '')))
            for s in sigs)
        parts.append('<table class="sig">%s</table>' % rows)

    doors = json.loads(v['doors'] or '[]')
    parts.append('<p class="note">%s · %s · %d signals · doors: %s</p>'
                 % (clock(v['started_at']), duration(v), v['signal_count'],
                    ', '.join(doors) or 'none'))

    return ('<details class="ev"><summary>%s<div class="meta"><div class="t">%s</div>'
            '<div class="s">%s · %s</div><div class="badges">%s</div></div></summary>'
            '<div class="body">%s</div></details>'
            % (thumb, visit_title(v), clock(v['started_at']), duration(v),
               ''.join(badges), ''.join(parts)))


@router.get('/webhook/ha/shop/r/{token}', response_class=HTMLResponse)
async def shop_review(token: str, days: int = 4) -> HTMLResponse:
    require(token)
    conn = db()
    try:
        # live tiles: four cameras, proxied so no HA token reaches the browser
        live = [('camera.cam_front_hallway_main', 'Shop door'),
                ('camera.reolink_video_doorbell_poe_clear', 'Outside'),
                ('camera.cam_waiting_room_main', 'Drop-off'),
                ('camera.cam_deserted_interior_main', 'Bench')]
        tiles = ''.join('<a class="tile" href="/webhook/ha/shop/r/%s/live/%s"><img loading="lazy" '
                        'src="/webhook/ha/shop/r/%s/cam/%s"><span class="lbl">%s</span></a>'
                        % (token, c, token, c, html.escape(n)) for c, n in live)

        # recent: the three newest visits that have a picture
        recent_rows = conn.execute(
            "SELECT v.* FROM shop_visit v JOIN shop_visit_media m ON m.visit_id=v.id AND m.kind='still' "
            "AND m.result='ok' GROUP BY v.id ORDER BY v.started_at DESC LIMIT 3").fetchall()
        def _recent_card(v):
            want = preferred_camera(json.loads(v['doors'] or '[]'), v['has_person'])
            return ('<a href="#%s"><img loading="lazy" src="/webhook/ha/shop/r/%s/full/%s/%s">'
                    '<span class="t">%s %s</span></a>'
                    % (v['id'], token, v['id'], html.escape(want), clock(v['started_at']),
                       html.escape(visit_title(v))))
        recent = ''.join(_recent_card(v) for v in recent_rows)

        # days
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        visits = conn.execute("SELECT * FROM shop_visit WHERE started_at >= ? "
                              "ORDER BY started_at DESC", (since,)).fetchall()
        by_day: dict[str, list] = {}
        for v in visits:
            by_day.setdefault(v['started_at'][:10], []).append(v)
        blocks = []
        for day in sorted(by_day, reverse=True):
            vs = by_day[day]
            people = sum(1 for v in vs if v['has_person'])
            cards = ''.join(render_visit(conn, v, token) for v in vs[:40])
            more = ('<p class="note">%d more on this day</p>' % (len(vs) - 40)) if len(vs) > 40 else ''
            blocks.append(
                '<section class="day"><div class="hdr"><b>%s</b><i>%d visits · %d with a person</i></div>'
                '%s%s</section>' % (day_label(day), len(vs), people, cards, more))
        if not blocks:
            blocks.append('<div class="empty">No visits recorded in the last %d days.</div>' % days)

        body = ('<div class="wrap"><div class="bar"><h1>Shop</h1>'
                '<span class="chip">%d visits · %d days</span></div>'
                '<h2>Live now</h2><div class="grid g2">%s</div>'
                '<h2>Most recent</h2><div class="recent">%s</div>'
                '%s</div>'
                % (len(visits), len(by_day), tiles, recent or '<div class="empty">Nothing yet.</div>',
                   ''.join(blocks)))
        return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                            '<meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<title>Shop — review</title><style>%s</style></head><body>%s</body></html>'
                            % (CSS, body))
    finally:
        conn.close()


@router.get('/webhook/ha/shop/r/{token}/img/{visit_id}')
async def shop_img(token: str, visit_id: str, camera: str | None = None) -> Response:
    require(token)
    conn = db()
    try:
        if camera:
            row = conn.execute("SELECT path FROM shop_visit_media WHERE visit_id=? AND camera_id=? "
                               "AND kind='still' AND result='ok'", (visit_id, camera)).fetchone()
        else:
            r = still_for(conn, visit_id)
            row = {'path': r['path']} if r else None
    finally:
        conn.close()
    if not row or not row['path'] or not os.path.exists(row['path']):
        raise HTTPException(404, 'no image')
    with open(row['path'], 'rb') as fh:
        data = fh.read()
    return Response(data, media_type='image/jpeg',
                    headers={'Cache-Control': 'public, max-age=86400'})


@router.get('/webhook/ha/shop/r/{token}/full/{visit_id}/{camera}')
async def shop_full(token: str, visit_id: str, camera: str) -> Response:
    return await shop_img(token, visit_id, camera)


@router.get('/webhook/ha/shop/r/{token}/cam/{camera}')
async def shop_cam(token: str, camera: str) -> Response:
    """A live snapshot, proxied. The browser never sees the Home Assistant token."""
    require(token)
    if not camera.startswith('camera.'):
        raise HTTPException(404, 'not a camera')
    try:
        status, body, ctype = ha_get('/api/camera_proxy/' + camera)
    except Exception:
        raise HTTPException(404, 'camera unavailable')
    return Response(body, media_type=ctype or 'image/jpeg',
                    headers={'Cache-Control': 'no-store'})


@router.get('/webhook/ha/shop/r/{token}/live/{camera}', response_class=HTMLResponse)
async def shop_live(token: str, camera: str) -> HTMLResponse:
    require(token)
    return HTMLResponse(
        '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{margin:0;background:#000}img{width:100%%;display:block}'
        'a{color:#9ad;font:14px sans-serif;display:block;padding:8px}</style>'
        '<img src="/webhook/ha/shop/r/%s/cam/%s"><a href="/webhook/ha/shop/r/%s">back</a>' % (token, camera, token))


@router.get('/webhook/ha/shop/r/{token}/clip/{visit_id}')
async def shop_clip(token: str, visit_id: str) -> RedirectResponse:
    """Resolve the stored clip to a Home Assistant signed URL, at request time.

    Signatures expire, so they must never be stored — resolving on demand is what keeps a
    week-old page from serving dead links.
    """
    require(token)
    conn = db()
    try:
        row = clip_for(conn, visit_id)
    finally:
        conn.close()
    if not row or row['result'] != 'ok' or not row['path']:
        raise HTTPException(404, 'no clip')
    import asyncio
    import ssl

    import websockets

    ha = ha_base()
    ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
    kw: dict = {'max_size': 8 * 1024 * 1024}
    if ws_url.startswith('wss://'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw['ssl'] = ctx
    rel = row['path'].replace('/media/', '')
    media_id = 'media-source://media_source/local/' + rel.lstrip('/')
    async with websockets.connect(ws_url, **kw) as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'access_token': env('HA_TOKEN')}))
        await ws.recv()
        await ws.send(json.dumps({'id': 1, 'type': 'media_source/resolve_media',
                                  'media_content_id': media_id}))
        while True:
            raw = json.loads(await ws.recv())
            if raw.get('id') == 1:
                break
    url = (raw.get('result') or {}).get('url')
    if not url:
        raise HTTPException(404, 'clip not resolvable')
    if url.startswith('/'):
        url = ha + url
    return RedirectResponse(url, status_code=302)
