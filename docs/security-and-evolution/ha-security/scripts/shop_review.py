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
import io
import json
import os
import re
import time
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# TIMES ARE THE BUILDING'S, NOT UTC (2026-10-28). A review of the live page found the newest event
# reading 17:15 next to a camera frame stamped 12:40, with no timezone stated anywhere — so the page
# looked five hours wrong. Everything the owner reads is now local, labelled once, and days are cut
# at local midnight rather than UTC midnight (which was putting evening activity in the wrong day).
# The zone is a literal, not a lookup: resolving it through env() at import time failed silently
# (env is defined further down), the except branch caught it, and the page spent an hour claiming
# "times are local" while printing UTC. A fallback that changes the meaning of every number on the
# screen must not be reachable by an import-order accident.
try:
    LOCAL_TZ = ZoneInfo('America/New_York')          # the building's zone
except Exception:                                    # pragma: no cover - defensive
    LOCAL_TZ = timezone.utc

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
.nav{display:flex;gap:6px;margin:0 0 10px}
.nav a{font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 12px}
.nav a.on{color:var(--txt);border-color:var(--accent);background:rgba(59,130,246,.14)}
.live-note{font-size:10px;color:var(--muted);margin:6px 0 2px}
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
.thumb.none{background:transparent;border:1px solid rgba(255,255,255,.06)}
.thumb{width:88px;height:66px;border-radius:7px;overflow:hidden;background:#0f1420;flex:0 0 auto;display:grid;place-items:center;font-size:10px;color:var(--muted);text-align:center;line-height:1.15}
.thumb img{width:100%;height:100%;object-fit:cover}
.meta{min-width:0;flex:1}
.meta .t{font-size:15px;font-weight:600}
.meta .s{font-size:12px;color:var(--muted);margin-top:2px}
.badges{display:flex;gap:5px;margin-top:4px;flex-wrap:wrap}
.b{font-size:10px;border-radius:999px;padding:1px 7px;border:1px solid var(--line);color:var(--muted)}
.b.clip{color:#0b0d12;background:var(--accent);border-color:var(--accent);font-weight:600}
.b.person{color:#bfe3ff;border-color:rgba(59,130,246,.5)}
.b.warn{color:var(--warn);border-color:var(--warn)}
.body{padding:0 10px 12px}
.body video{width:100%;border-radius:8px;background:#000;margin:6px 0 8px}
.shots{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:8px 0}
.shots a{display:block;position:relative;aspect-ratio:4/3;border-radius:6px;overflow:hidden;background:#0f1420}
.shots .shotat{position:absolute;left:0;right:0;bottom:0;font-size:9px;padding:8px 4px 2px;
  background:linear-gradient(transparent,rgba(0,0,0,.8));color:#dbe3ef}
.shots img{width:100%;height:100%;object-fit:cover}
table.sig{width:100%;border-collapse:collapse;font-size:12px;color:var(--muted)}
table.sig td{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top}
table.sig td.n{white-space:nowrap;color:var(--txt);padding-right:8px}
.note{font-size:12px;color:var(--muted);margin:6px 0}
.warnbox{font-size:12px;color:var(--warn)}
.alert{border-radius:10px;padding:10px 12px;margin:2px 0 4px;border-left:8px solid var(--line);background:var(--card)}
.alert b{display:block;font-size:15px}
.alert span{display:block;font-size:12px;color:var(--muted);margin-top:2px}
.alert .ts2{font-size:10px;opacity:.75}
.alert.ok{border-left-color:var(--ok)}
.alert.warn{border-left-color:var(--warn);background:rgba(255,152,0,.10)}
/* an 18% wash let the day header show THROUGH the pinned alert (2026-10-28): two texts on top of
   each other at the exact moment the alert matters most. A pinned bar must be opaque. */
.alert.bad{border-left-color:var(--bad);background:#3a1418;
  position:sticky;top:0;z-index:20;border-radius:0;margin:0 -12px;padding:12px}
.tile .ts{font-style:normal;color:#c9d2e0;margin-left:6px;font-size:10px}
.alert.unknown{border-left-color:var(--muted)}
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



SAFETY = {
    'intr': 'input_boolean.phoenix_intrusion_active',
    'test': 'input_boolean.phoenix_intrusion_test_mode',
    'lock': 'input_boolean.phoenix_access_control_lockdown',
    'guest': 'input_boolean.phoenix_house_guest_mode_active',
    'away': 'binary_sensor.phoenix_everyone_away',
    'shop': 'binary_sensor.phoenix_control_room_interior_door_contact',
    'apt': 'binary_sensor.phoenix_control_room_exterior_door_contact',
}


def safety_state() -> dict:
    """The same severity logic the Home Assistant banner uses, so the two never disagree.

    A gallery that shows a calm page while the siren is muted would be worse than no gallery: it
    is the one lie this whole system exists to avoid. If Home Assistant cannot be reached the
    banner says so instead of assuming the building is fine.
    """
    try:
        status, body, _ = ha_get('/api/states')
        states = {s['entity_id']: s['state'] for s in json.loads(body)}
    except Exception:
        return {'level': 'unknown', 'head': 'Cannot reach the building', 'detail': ''}
    v = {k: states.get(e, 'unknown') for k, e in SAFETY.items()}
    unknown = [k for k, x in v.items() if x in ('unknown', 'unavailable')]
    on = lambda k: v.get(k) == 'on'          # noqa: E731
    door = on('shop') or on('apt')
    if on('intr') and on('test'):
        return {'level': 'bad', 'head': 'ALARM TRIPPED, SIREN SILENCED',
                'detail': 'Test mode is on — nothing is sounding.'}
    if on('intr'):
        return {'level': 'bad', 'head': 'ALARM GOING OFF NOW', 'detail': 'Check the cameras.'}
    if on('test'):
        return {'level': 'bad', 'head': 'SIREN SILENCED — TEST MODE ON',
                'detail': 'No alarm will sound. Turn test mode off when you are done.'}
    if on('lock'):
        return {'level': 'bad', 'head': 'ACCESS CONTROL LOCKED DOWN',
                'detail': 'Doors stay locked until it is cleared.'}
    if on('away') and door:
        return {'level': 'bad', 'head': 'DOOR OPEN WHILE AWAY',
                'detail': 'Nobody is meant to be here.'}
    if on('guest') and on('away'):
        return {'level': 'warn', 'head': 'GUEST MODE ON, NOBODY HOME',
                'detail': 'The alarm cannot arm while that is on.'}
    if unknown:
        return {'level': 'warn', 'head': 'CANNOT CONFIRM THE BUILDING',
                'detail': 'Offline: ' + ', '.join(unknown)}
    if door:
        return {'level': 'warn', 'head': 'DOOR OPEN', 'detail': 'Someone is in the building.'}
    if on('guest'):
        return {'level': 'warn', 'head': 'GUEST MODE ON', 'detail': 'The alarm cannot arm.'}
    return {'level': 'ok', 'head': 'No alerts', 'detail': 'Doors closed.'}


_TILE_CACHE: dict[str, tuple[float, bytes]] = {}
_CLIP_URL_CACHE: dict[str, tuple[float, str]] = {}
TILE_TTL_S = 5.0


def shrink_jpeg(body: bytes, width: int = 360, quality: int = 70) -> bytes:
    """Return a small JPEG for a phone tile.

    A 2560 px camera frame was being drawn into a 179×101 box: 756 KB and up to 2.5 s per tile,
    four tiles, so the first screen paid ~1.3 MB and several seconds of empty bordered boxes.
    Resizing on the server is the difference between a tile that appears and one that does not.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(body)) as im:
            im = im.convert('RGB')
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))),
                               Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, format='JPEG', quality=quality, optimize=True)
            return out.getvalue()
    except Exception:
        return body          # never fail a tile because resizing failed


def require(token: str) -> None:
    expected = env('SHOP_REVIEW_TOKEN') or ''
    if not expected or token != expected:
        raise HTTPException(status_code=404, detail='Not found')


INSIDE = 'camera.cam_front_hallway_main'          # the shop door, from inside
OUTSIDE = 'camera.reolink_video_doorbell_poe_clear'  # the street, from outside


def camera_priority(doors: list[str], has_person: int, subjects: list | None = None) -> list[str]:
    """Which camera to show for this visit, best first.

    The owner's correction, verbatim: *"most recent capture should include in the shop, not just
    outside it."* He was right — most visits fire only the doorbell, so the gallery was wall-to-wall
    outside views of the street and never showed anyone actually inside the shop.

    So the inside camera is preferred whenever the visit has one, and it is preferred FIRST for a
    visit that came through the door. A thumbnail of the wrong room is still worse than none, so
    the order is a preference over stills that exist, never an invention:

        shop door touched   -> inside, then outside
        apartment door      -> inside, then drop-off
        street door / person-> outside, then inside (the inside shot is the arrival)
        nothing known       -> inside
    """
    # A TITLE SAYS INTERIOR, THE PICTURE MUST TOO (2026-10-28). A keypad entry logged "at Interior"
    # was showing the street because the visit had no door signal, only a person. The credential is
    # the strongest evidence of where someone went, so it decides the camera.
    for sub in (subjects or []):
        where = (sub.get('where') if isinstance(sub, dict) else '') or ''
        if where.lower().startswith('int'):
            return [INSIDE, OUTSIDE]
    if 'shop_door' in doors:
        return [INSIDE, OUTSIDE]
    if 'apartment_door' in doors:
        return [INSIDE, 'camera.cam_waiting_room_main']
    if 'street_door' in doors or has_person:
        return [OUTSIDE, INSIDE]
    return [INSIDE, OUTSIDE]


def preferred_camera(doors: list[str], has_person: int, subjects: list | None = None) -> str:
    return camera_priority(doors, has_person, subjects)[0]


def still_for(conn: sqlite3.Connection, visit_id: str,
              prefer: str | list[str] | None = None) -> sqlite3.Row | None:
    rows = conn.execute(
        "SELECT camera_id, path, sha256, result, captured_at FROM shop_visit_media "
        "WHERE visit_id=? AND kind='still' ORDER BY (result='ok') DESC, camera_id", (visit_id,)).fetchall()
    ok = [r for r in rows if r['result'] == 'ok' and r['path']]
    order = [prefer] if isinstance(prefer, str) else list(prefer or [])
    for want in order:
        for r in ok:
            if r['camera_id'] == want:
                return r
    return ok[0] if ok else None


def clip_for(conn: sqlite3.Connection, visit_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT camera_id, path, result, error, clip_seconds, clip_offset_s, local_path FROM shop_visit_media "
        "WHERE visit_id=? AND kind='clip' LIMIT 1", (visit_id,)).fetchone()


CLIP_GRACE_S = 120        # a clip starting later than this after a visit began is not that visit


def clip_state(v: sqlite3.Row, cl: sqlite3.Row | None) -> str:
    """'playable', 'failed' or 'too_old' -- decided server-side, each with its own sentence.

    Recording can only start when a visit starts, so an older event can never have a clip. Saying
    "no clip" without saying why invites the owner to think the system is broken.
    """
    if cl and cl['result'] == 'ok' and cl['path']:
        return 'playable'
    if cl:
        return 'failed'
    started = to_local(v['started_at'])
    old_enough = started and (datetime.now(LOCAL_TZ) - started).total_seconds() > CLIP_GRACE_S
    if not old_enough:
        return 'failed'          # young enough that a recording may still be on its way
    # a visit that has not ended is not "too old": someone is in the shop now, and saying "too old"
    # about an event that is still happening is the sort of sentence that makes a page untrustworthy
    return 'open_no_clip' if not v['ended_at'] else 'too_old'


def mmss(total: float) -> str:
    total = int(max(0, total))
    return '%d:%02d' % (total // 60, total % 60)


def visit_title(v: sqlite3.Row) -> str:
    doors = json.loads(v['doors'] or '[]')
    person = bool(v['has_person'])
    # A NAME BEATS A DESCRIPTION (2026-10-28). When the keypad record says who used a code, that is
    # the most useful thing on the card -- "Owner access at the shop door" answers the owner's own
    # question ("who came") in a way "Person at the shop door" never can.
    try:
        subjects = json.loads(v['subjects'] or '[]')
    except Exception:
        subjects = []
    if subjects:
        who = subjects[0].get('who') if isinstance(subjects[0], dict) else str(subjects[0])
        where = subjects[0].get('where', '') if isinstance(subjects[0], dict) else ''
        if who:
            # the rolling log truncates mid-word ("at Int", "at Magl"), so a short fragment is
            # dropped rather than shown as a typo
            w = where.lower().strip()
            if w.startswith('int'):
                w = 'interior'
            elif w.startswith('magl'):
                w = 'the maglock'
            label = (' at ' + w) if len(w) >= 5 else ''
            return '%s access%s' % (who, label)
    if person and 'shop_door' in doors:
        return 'Person at the interior shop door'
    if person:
        return 'Person outside'
    if 'shop_door' in doors:
        return 'Interior shop door opened'
    if 'apartment_door' in doors or 'exterior_door' in doors:
        # the owner corrected the naming: the exterior SHOP door carries this sensor. The apartment
        # door has no sensor yet, so nothing here may claim one.
        return 'Exterior shop door opened'
    if 'street_door' in doors:
        return 'Outside door opened'
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


def to_local(iso: str | None) -> datetime | None:
    """UTC in the record, local on the screen. The building's clock, not the server's."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(LOCAL_TZ)
    except Exception:
        return None


def clock(iso: str | None, with_seconds: bool = False) -> str:
    """Every time the owner reads is the building's local time, not the record's UTC."""
    d = to_local(iso)
    if not d:
        return '--:--'
    return d.strftime('%H:%M:%S' if with_seconds else '%H:%M')

def local_day(iso: str) -> str:
    d = to_local(iso)
    return d.date().isoformat() if d else iso[:10]


def day_label(d: str) -> str:
    today = datetime.now(LOCAL_TZ).date()
    try:
        dd = datetime.fromisoformat(d).date()
    except Exception:
        return d
    delta = (today - dd).days
    stamp = dd.strftime('%a %d %b')
    if delta == 0:
        return 'Today · ' + stamp
    if delta == 1:
        return 'Yesterday · ' + stamp
    return stamp


def render_visit(conn: sqlite3.Connection, v: sqlite3.Row, token: str) -> str:
    try:
        _subs = json.loads(v['subjects'] or '[]')
    except Exception:
        _subs = []
    order = camera_priority(json.loads(v['doors'] or '[]'), v['has_person'], _subs)
    st = still_for(conn, v['id'], order)
    cl = clip_for(conn, v['id'])
    if st:
        # WRAPPED IN THE SIZED BOX (2026-10-28). Without the wrapper the image is a direct child
        # of <summary> and renders at its natural 2560 px: one event card filled an entire phone
        # screen. The box is what makes a thumbnail a thumbnail.
        # A NEW CAPTURE MUST BE A NEW URL (2026-10-28). These are served with max-age=86400, so a
        # card whose picture was replaced kept showing the FIRST frame the browser ever saw -- the
        # owner walked through the hallway, was photographed, and saw an empty room for a day. The
        # capture time is now part of the URL, so replacing the picture replaces the address.
        import hashlib as _h
        ver = _h.sha1(str(st['captured_at']).encode()).hexdigest()[:8]
        thumb = ('<div class="thumb"><img loading="lazy" decoding="async" '
                 'src="/webhook/ha/shop/r/%s/full/%s/%s?w=176&v=%s" alt=""></div>'
                 % (token, v['id'], html.escape(st['camera_id']), ver))
    else:
        # ONE ROW GEOMETRY (2026-10-28). Removing the empty box fixed the "broken image" look but
        # left two row heights and two left edges in the same list. The slot now always exists and
        # stays quiet: no border, no words, just an anchor point for the text.
        thumb = '<div class="thumb none" aria-hidden="true"></div>'
    badges = []
    if v['has_person']:
        badges.append('<span class="b person">person</span>')
    if cl and cl['result'] == 'ok':
        badges.append('<span class="b clip">&#9654; clip</span>')
    elif cl:
        badges.append('<span class="b warn">clip failed</span>')
    if v['signal_count'] and v['signal_count'] > 6:
        badges.append('<span class="b">%d signals</span>' % v['signal_count'])

    # the expanded body
    parts = []
    state = clip_state(v, cl)
    visit_span = 0.0
    if v['ended_at']:
        visit_span = (to_local(v['ended_at']) - to_local(v['started_at'])).total_seconds()
    if state == 'playable':
        # NO POSTER AND NO AUTOPLAY (2026-10-28): a poster is a claim about footage, the stills
        # below already carry the picture, and 2-4 MB must not start on its own. preload=none
        # means a card that is never opened never requests the file.
        parts.append('<video controls playsinline preload="none" width="358" height="201" '
                     'aria-label="Clip: %s, %s" src="/webhook/ha/shop/r/%s/clip/%s"></video>'
                     % (html.escape(visit_title(v)), clock(v['started_at']), token, v['id']))
        keys = cl.keys()
        secs = cl['clip_seconds'] if 'clip_seconds' in keys else None
        offset = cl['clip_offset_s'] if 'clip_offset_s' in keys else None
        if secs and visit_span:
            parts.append('<p class="note">Clip %s of a %s visit. This is not the whole visit; the '
                         'rest is not on video.</p>' % (mmss(secs), mmss(visit_span)))
        elif secs:
            parts.append('<p class="note">Clip %s. The visit had not finished when it was recorded, '
                         'so this is part of it, not all of it.</p>' % mmss(secs))
        else:
            parts.append('<p class="note">This clip covers only part of the visit.</p>')
        # A clip that began part-way through must say so, or it implies it caught the arrival
        if offset and offset > 60:
            if visit_span and offset > visit_span:
                # the two numbers disagree, so neither is repeated: say when the recording began
                began = to_local(cl['captured_at']) if 'captured_at' in keys else None
                if began:
                    parts.append('<p class="note">Recording began at %s — after the arrival, so the '
                                 'arrival is not on it.</p>' % began.strftime('%H:%M:%S'))
            else:
                parts.append('<p class="note">Clip starts %s into the visit — recording began after '
                             'the visit did, so the arrival is not on it.</p>' % mmss(offset))
        parts.append('<p class="note">Clip links expire. If it will not play, reload the page.</p>')
    elif state == 'open_no_clip':
        parts.append('<p class="note">No clip for this visit — recording did not start when it '
                     'began. This visit is still open.</p>')
    elif state == 'failed':
        parts.append('<p class="warnbox">Recording failed. A recording was attempted but no clip '
                     'was saved. A clip cannot be recorded after the visit.</p>')
    else:
        parts.append('<p class="note">No clip — this visit is too old. Clips can only be recorded '
                     'when a visit starts.</p>')

    shots = conn.execute("SELECT camera_id, path, captured_at FROM shop_visit_media WHERE "
                         "visit_id=? AND kind='still' AND result='ok' ORDER BY camera_id",
                         (v['id'],)).fetchall()
    if shots:
        import hashlib as _h2
        def _shot(sh):
            ver = _h2.sha1(str(sh['captured_at']).encode()).hexdigest()[:8]
            return ('<a href="/webhook/ha/shop/r/%s/full/%s/%s?v=%s"><img loading="lazy" '
                    'src="/webhook/ha/shop/r/%s/full/%s/%s?w=320&v=%s">'
                    '<span class="shotat">%s</span></a>'
                    % (token, v['id'], html.escape(sh['camera_id']), ver, token, v['id'],
                       html.escape(sh['camera_id']), ver, clock(sh['captured_at'])))
        cells = ''.join(_shot(sh) for sh in shots)
        parts.append('<div class="shots">%s</div>' % cells)
    else:
        parts.append('<p class="note">No picture — none was captured when this began.</p>')

    total_sigs = conn.execute("SELECT COUNT(1) FROM shop_visit_signal WHERE visit_id=?",
                               (v['id'],)).fetchone()[0]
    sigs = conn.execute("SELECT occurred_at, entity_id, new_state FROM shop_visit_signal WHERE "
                        "visit_id=? ORDER BY occurred_at LIMIT 8", (v['id'],)).fetchall()
    if sigs:
        def plain(entity: str, state: str) -> str:
            e = entity.replace('binary_sensor.', '').replace('input_boolean.', '')
            e = e.replace('event.esphome.', '').replace('automation.phoenix_', '')
            e = e.replace('phoenix_', '').replace('_', ' ').strip()
            if 'keypad' in e:
                return 'keypad entry'
            if 'door contact' in e or e.endswith('door contact'):
                return ('%s %s' % (e.replace(' control room', ''), 'opened' if state == 'on' else 'closed'))
            if 'zone' in e or 'occupied' in e or 'business area' in e:
                return '%s %s' % (e, state)
            return '%s %s' % (e, state)
        rows = ''.join('<tr><td class="n">%s</td><td>%s</td></tr>'
                       % (clock(x['occurred_at']), html.escape(plain(x['entity_id'], str(x['new_state'] or ''))))
                       for x in sigs)
        more = ''
        if total_sigs > len(sigs):
            more = ('<tr><td class="n">…</td><td>showing %d of %d signals</td></tr>'
                    % (len(sigs), total_sigs))
        parts.append('<table class="sig">%s%s</table>' % (rows, more))

    doors = json.loads(v['doors'] or '[]')
    parts.append('<p class="note">%s · %s · %d signal%s · doors: %s · times are local</p>'
                 % (clock(v['started_at']), duration(v), v['signal_count'],
                    '' if v['signal_count'] == 1 else 's',
                    ', '.join({'shop_door': 'interior shop door',
                               'apartment_door': 'exterior shop door',
                               'exterior_door': 'exterior shop door',
                               'street_door': 'outside door'}.get(d, d.replace('_', ' '))
                              for d in doors) or 'none'))

    return ('<details class="ev" name="event" id="%s"><summary>%s<div class="meta"><div class="t">%s</div>'
            '<div class="s">%s · %s</div><div class="badges">%s</div></div></summary>'
            '<div class="body">%s</div></details>'
            % (v['id'], thumb, visit_title(v), clock(v['started_at']), duration(v),
               ''.join(badges), ''.join(parts)))


@router.get('/webhook/ha/shop/r/{token}', response_class=HTMLResponse)
async def shop_review(token: str, days: int = 7, clips: int = 0) -> HTMLResponse:
    require(token)
    conn = db()
    try:
        # live tiles: four cameras, proxied so no HA token reaches the browser
        live = [('camera.cam_front_hallway_main', 'Shop door'),
                ('camera.reolink_video_doorbell_poe_clear', 'Outside'),
                ('camera.cam_waiting_room_main', 'Drop-off'),
                ('camera.cam_deserted_interior_main', 'Bench')]
        # a tile labelled "live" that was fetched at page load is a lie a minute later, so each
        # one states when its frame was taken and refreshes itself in place
        # NO PER-TILE CLOCK (2026-10-28). A caption that proves when the PHONE asked, rather than when
        # the camera answered, is worse than no caption: a failed fetch leaves an old frame wearing a
        # new time. One line under the strip states when the server last read the building.
        as_of = datetime.now(LOCAL_TZ).strftime('%H:%M:%S')
        tiles = ''.join(
            '<a class="tile" href="/webhook/ha/shop/r/%s/live/%s" data-cam="%s">'
            '<img loading="lazy" decoding="async" width="360" alt="%s" '
            'src="/webhook/ha/shop/r/%s/cam/%s?w=360&t=%s">'
            '<span class="lbl">%s</span></a>'
            % (token, c, c, html.escape(n), token, c, as_of.replace(':', ''),
               html.escape(n)) for c, n in live)

        # recent: the three newest visits that have a picture
        # MOST RECENT = THE THREE MOST RECENT *PLACES* (2026-10-28). Taking the three newest visits
        # gave three outside shots, because the doorbell fires on every approach and the indoor
        # camera only fires when a door opens. The owner asked for the shop to be included, so the
        # strip deliberately takes the newest in-shop capture, the newest outside capture, and then
        # the newest of anything else. If a place has no capture, the strip is shorter -- it never
        # invents one.
        candidates = conn.execute(
            "SELECT v.* FROM shop_visit v JOIN shop_visit_media m ON m.visit_id=v.id AND m.kind='still' "
            "AND m.result='ok' GROUP BY v.id ORDER BY v.started_at DESC LIMIT 40").fetchall()
        recent_rows, used = [], set()
        for wanted in ('inside', 'outside', None):
            for v in candidates:
                if v['id'] in used:
                    continue
                cams = {m['camera_id'] for m in conn.execute(
                    "SELECT camera_id FROM shop_visit_media WHERE visit_id=? AND kind='still' "
                    "AND result='ok'", (v['id'],))}
                if wanted == 'inside' and INSIDE not in cams:
                    continue
                if wanted == 'outside' and OUTSIDE not in cams:
                    continue
                recent_rows.append(v)
                used.add(v['id'])
                break
        recent_rows = recent_rows[:3]
        def _recent_card(v):
            # name a camera that actually has a still for this visit, inside first
            try:
                _subs = json.loads(v['subjects'] or '[]')
            except Exception:
                _subs = []
            order = camera_priority(json.loads(v['doors'] or '[]'), v['has_person'], _subs)
            st = still_for(conn, v['id'], order)
            if not st:
                return ''
            import hashlib as _h3
            rver = _h3.sha1(str(st['captured_at']).encode()).hexdigest()[:8]
            return ('<a href="#%s"><img loading="lazy" '
                    'src="/webhook/ha/shop/r/%s/full/%s/%s?w=176&v=%s">'
                    '<span class="t">%s %s</span></a>'
                    % (v['id'], token, v['id'], html.escape(st['camera_id']), rver,
                       clock(v['started_at']), html.escape(visit_title(v))))
        recent = ''.join(_recent_card(v) for v in recent_rows)

        # days
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        if clips:
            # CLIPS ONLY (2026-10-28): the stream is for browsing, this is for watching. Server-side
            # so it is one query parameter, deep-linkable, and works with no JavaScript at all.
            visits = conn.execute(
                "SELECT v.* FROM shop_visit v JOIN shop_visit_media m ON m.visit_id=v.id "
                "AND m.kind='clip' AND m.result='ok' WHERE v.started_at >= ? "
                "ORDER BY v.started_at DESC", (since,)).fetchall()
        else:
            visits = conn.execute("SELECT * FROM shop_visit WHERE started_at >= ? "
                                  "ORDER BY started_at DESC", (since,)).fetchall()
        by_day: dict[str, list] = {}
        for v in visits:
            # LOCAL DAY, NOT UTC (2026-10-28). The bucket key was the first ten characters of the
            # UTC timestamp, while the headers and the window were local -- so an 8:42 PM visit sat
            # under the next day, and the two halves of the page disagreed about what "today" means.
            by_day.setdefault(local_day(v['started_at']), []).append(v)
        # A QUIET DAY IS INFORMATION (2026-10-28). Rendering only the days that have visits makes a
        # day with nothing in it indistinguishable from a day the record does not cover -- the same
        # class of blank this build exists to avoid. Every day in the window gets a header; the ones
        # with nothing say so, and say whether the record even reaches that far.
        first_visit = conn.execute("SELECT MIN(started_at) FROM shop_visit").fetchone()[0]
        window = [(datetime.now(LOCAL_TZ).date() - timedelta(days=n)).isoformat()
                  for n in range(days)]
        blocks = []
        for day in window:
            vs = by_day.get(day, [])
            if not vs:
                covered = bool(first_visit and first_visit[:10] <= day)
                if clips and covered:
                    note = 'No clip kept for this day — the visits are in All events.'
                elif covered:
                    note = 'No visits recorded on this day.'
                else:
                    note = 'The record starts later than this day — nothing was kept for it.'
                blocks.append('<section class="day"><div class="hdr"><b>%s</b>'
                              '<i>no visits</i></div><p class="note">%s</p></section>'
                              % (day_label(day), note))
                continue
            people = sum(1 for v in vs if v['has_person'])
            cards = ''.join(render_visit(conn, v, token) for v in vs[:40])
            more = ('<p class="note">%d more on this day</p>' % (len(vs) - 40)) if len(vs) > 40 else ''
            blocks.append(
                '<section class="day"><div class="hdr"><b>%s</b><i>%d visits · %d with a person</i></div>'
                '%s%s</section>' % (day_label(day), len(vs), people, cards, more))
        if not blocks:
            blocks.append('<div class="empty">No visits recorded in the last %d days.</div>' % days)

        st = safety_state()
        st['checked'] = datetime.now(LOCAL_TZ).strftime('%H:%M:%S')
        n_clips = conn.execute(
            "SELECT COUNT(1) FROM shop_visit_media WHERE kind='clip' AND result='ok'").fetchone()[0]
        nav = ('<div class="nav"><a class="%s" href="?">All events</a>'
               '<a class="%s" href="?clips=1">Clips (%d)</a></div>'
               % ('on' if not clips else '', 'on' if clips else '', n_clips))
        body = ('<div class="wrap"><div class="bar"><h1>Shop</h1>'
                '<span class="chip">%d visits · %d days</span></div>%s'
                '<div class="alert %s" id="alert"><b>%s</b><span>%s</span>'
                '<span class="ts2">checked %s</span></div>'
                '<h2>Live now</h2><div class="grid g2">%s</div>'
                '<p class="live-note"><span id="asof">snapshots read at %s</span>'
                ' · <span id="tick">refreshing every 30s</span></p>'
                '<h2>Most recent</h2><div class="recent">%s</div>'
                '%s</div>'
                % (len(visits), len(by_day), nav, st['level'], html.escape(st['head']),
                   html.escape(st['detail']), st['checked'], tiles, as_of,
                   recent or '<div class="empty">Nothing yet.</div>', ''.join(blocks)))
        resp = HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                            '<meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<title>Shop — review</title><style>%s</style></head><body>%s'
                            '<script>(function(){'
                            'var base="/webhook/ha/shop/r/%s";'
                            'function tick(){'
                            'fetch(base+"/state.json",{cache:"no-store"})'
                            '.then(function(r){return r.json()}).then(function(j){'
                            'var a=document.getElementById("asof");'
                            'if(a)a.textContent="snapshots read at "+j.as_of;'
                            'var el=document.getElementById("alert");'
                            'if(el){el.className="alert "+j.alert.level;'
                            'el.querySelector("b").textContent=j.alert.head;'
                            'var t2=el.querySelector(".ts2"); if(t2)t2.textContent="checked "+j.as_of;}'
                            'document.querySelectorAll("a.tile img").forEach(function(i){'
                            'var c=i.closest("a.tile").dataset.cam;'
                            'i.src=base+"/cam/"+c+"?w=360&t="+j.epoch;});'
                            '}).catch(function(){'
                            'var a=document.getElementById("asof");'
                            'if(a)a.textContent="cannot reach the building — last good reading above";'
                            '});}'
                            'setInterval(tick,30000);'
                            'document.addEventListener("visibilitychange",function(){'
                            'if(!document.hidden)tick();});'
                            '})();</script></body></html>'
                            % (CSS, body, token))
        # the page states the situation at a moment; a cached copy of it is a stale claim
        resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        return resp
    finally:
        conn.close()


@router.get('/webhook/ha/shop/r/{token}/state.json')
def shop_state(token: str) -> Response:
    """The live half of the page, as data, so the browser never invents a time.

    The old tile strip wrote its caption from the phone's `new Date()` *before* the fetch finished, so a
    stalled camera left an old frame under a brand-new timestamp — a false "live", and the most
    dangerous thing on the page after staleness. Now every time shown comes from here, produced by the
    server at the moment it read the building.
    """
    require(token)
    st = safety_state()
    return Response(
        json.dumps({'as_of': datetime.now(LOCAL_TZ).strftime('%H:%M:%S'),
                    'epoch': int(time.time()),
                    'alert': {'level': st['level'], 'head': st['head'], 'detail': st['detail']}}),
        media_type='application/json',
        headers={'Cache-Control': 'no-store'})


@router.get('/webhook/ha/shop/r/{token}/img/{visit_id}')
def shop_img(token: str, visit_id: str, camera: str | None = None) -> Response:
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
def shop_full(token: str, visit_id: str, camera: str, w: int = 0) -> Response:
    """One stored still, optionally at thumbnail size.

    `w=0` serves the original for the lightbox. A card passes `w=176`, because a 2560 px frame in an
    88×66 box costs 152 KB per card and a page can hold fifty of them — the same waste the live
    tiles had, in the one place it multiplies.
    """
    resp = shop_img(token, visit_id, camera)
    if not w:
        return resp
    return Response(shrink_jpeg(resp.body, width=max(96, min(720, w)), quality=68),
                    media_type='image/jpeg',
                    headers={'Cache-Control': 'public, max-age=86400'})


@router.get('/webhook/ha/shop/r/{token}/cam/{camera}')
def shop_cam(token: str, camera: str, w: int = 360) -> Response:
    """A small, current snapshot, proxied. The browser never sees the Home Assistant token.

    A 2560 px frame was being drawn into a 179×101 box — 756 KB and up to 2.5 s per tile, four
    tiles, so the first screen paid ~1.3 MB and several seconds of empty bordered boxes.
    Resized here, cached for five seconds (short, because a stale "live" tile is a lie).
    """
    require(token)
    if not camera.startswith('camera.'):
        raise HTTPException(404, 'not a camera')
    now = time.monotonic()
    hit = _TILE_CACHE.get(camera)
    if hit and (now - hit[0]) < TILE_TTL_S:
        return Response(hit[1], media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
    try:
        status, body, ctype = ha_get('/api/camera_proxy/' + camera)
    except Exception:
        raise HTTPException(404, 'camera unavailable')
    data = shrink_jpeg(body, width=max(160, min(720, w)))
    _TILE_CACHE[camera] = (now, data)
    return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


@router.get('/webhook/ha/shop/r/{token}/live/{camera}', response_class=HTMLResponse)
async def shop_live(token: str, camera: str) -> HTMLResponse:
    require(token)
    return HTMLResponse(
        '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{margin:0;background:#000}img{width:100%%;display:block}'
        'a{color:#9ad;font:14px sans-serif;display:block;padding:8px}</style>'
        '<img src="/webhook/ha/shop/r/%s/cam/%s"><a href="/webhook/ha/shop/r/%s">back</a>' % (token, camera, token))


@router.get('/webhook/ha/shop/r/{token}/clip/{visit_id}')
async def shop_clip(token: str, visit_id: str, request: Request) -> Response:
    """Stream one stored clip through THIS origin, with byte-range support.

    A 302 to Home Assistant's signed URL does not work from a phone: the page is https and the
    signature points at an http tailnet address, which the browser refuses as mixed content — the
    first real clip failed with MEDIA_ERR_SRC_NOT_SUPPORTED for exactly that reason. iOS Safari also
    requires byte-range support before it will play inline video at all.

    So the bytes come through here. The signature is still minted at request time (never at page
    render, or every URL on a page would be dead after the TTL) and cached briefly, and the client's
    Range header is passed straight through so seeking works.
    """
    require(token)
    conn = db()
    try:
        row = clip_for(conn, visit_id)
    finally:
        conn.close()
    if not row or row['result'] != 'ok' or not row['path']:
        raise HTTPException(404, 'no clip')

    # THE PLAYABLE COPY FIRST (2026-10-28). The camera records HEVC, which Chrome cannot decode —
    # the first real clip failed with MEDIA_ERR_SRC_NOT_SUPPORTED while every check said it was
    # fine. shop-clip-local.py pulls the file here and transcodes it to H.264; this serves that copy
    # from disk with real byte ranges, which iOS also requires before it will play inline video.
    local = row['local_path'] if 'local_path' in row.keys() else None
    if local and os.path.exists(local):
        size = os.path.getsize(local)
        rng = request.headers.get('range') or ''
        m = re.match(r'bytes=(\d*)-(\d*)', rng)
        if m:
            start = int(m.group(1) or 0)
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start > end:
                raise HTTPException(416, 'bad range')
            with open(local, 'rb') as fh:
                fh.seek(start)
                chunk = fh.read(end - start + 1)
            return Response(chunk, status_code=206, headers={
                'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes',
                'Content-Range': 'bytes %d-%d/%d' % (start, end, size),
                'Content-Length': str(len(chunk)), 'Cache-Control': 'no-store'})
        with open(local, 'rb') as fh:
            body = fh.read()
        return Response(body, media_type='video/mp4', headers={
            'Accept-Ranges': 'bytes', 'Content-Length': str(len(body)),
            'Cache-Control': 'no-store'})

    import urllib.request as _u

    now = time.monotonic()
    hit = _CLIP_URL_CACHE.get(visit_id)
    if hit and (now - hit[0]) < 480:            # signatures are short-lived; refresh well inside
        url = hit[1]
    else:
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
        _CLIP_URL_CACHE[visit_id] = (now, url)

    rng = request.headers.get('range')
    req = _u.Request(url, headers={'Range': rng} if rng else {})
    try:
        with _u.urlopen(req, timeout=90) as upstream:
            body = upstream.read()
            headers = {'Content-Type': 'video/mp4',
                       'Accept-Ranges': 'bytes',
                       'Cache-Control': 'no-store'}
            for h in ('Content-Range', 'Content-Length'):
                if upstream.headers.get(h):
                    headers[h] = upstream.headers[h]
            return Response(body, status_code=upstream.status, headers=headers)
    except Exception as exc:
        raise HTTPException(502, 'clip unavailable: %s' % type(exc).__name__)
