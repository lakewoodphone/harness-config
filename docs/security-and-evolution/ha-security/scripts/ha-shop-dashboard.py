#!/usr/bin/env python3
"""Render and apply ONE Shop dashboard to Home Assistant, idempotently.

Why a generator and not a JSON blob: the dashboard is applied over the websocket API
(`lovelace/dashboards/create` + `lovelace/config/save`) because this machine has no file
route into /config — only 8123 answers from anywhere else. A generator means the layout is
reviewable in git, can be re-applied after a mistake, and is the single source of truth for
what the owner's phone shows.

Design rules (owner: "way too complex … i don't need the whole backend data dump", and
"one clear simplified view"):
  * ONE view, one column, readable on a phone. The first screen is what matters.
  * Two hero cameras only — the shop door (best face view) and the street door. The other
    three are one-tap shortcuts, not full-width pictures, so the timeline is not pushed off
    the first screen.
  * The timeline filters to `on` transitions, so it reads as arrivals and detections
    rather than an open/close state table.
  * The banner is always rendered (never conditional, so it cannot silently disappear) and
    leads with a status word in capitals. A calm sentence can never appear while the siren
    is muted: "SIREN MUTED" is the headline whenever test mode is on, unless an intrusion is
    already active.
  * No switches and no mode toggles on this page. An accidental tap on test mode, guest mode
    or lockdown is worse than the convenience of having it here.
  * Sensor health sits last and small: a frozen `last-changed` is the only way this view can
    show a sensor that stopped talking *without* going `unavailable`.

Credits: layout and banner designed 2026-10-28 by fanned-out analyses; the 18-state banner
table was rendered through Jinja2 with stubbed states()/is_state(), and this template was
re-rendered through Home Assistant itself before being applied.

usage:  PYTHONPATH=/opt/company python3 ha-shop-dashboard.py [--url-path shop-view] [--dry]
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys

ENV = '/opt/company/.env'

BANNER = """{%- set test = states('input_boolean.phoenix_intrusion_test_mode') -%}
{%- set guest = states('input_boolean.phoenix_house_guest_mode_active') -%}
{%- set intr = states('input_boolean.phoenix_intrusion_active') -%}
{%- set lock = states('input_boolean.phoenix_access_control_lockdown') -%}
{%- set away_state = states('binary_sensor.phoenix_everyone_away') -%}
{%- set away = away_state == 'on' -%}
{%- set shop = states('binary_sensor.phoenix_control_room_interior_door_contact') -%}
{%- set apt = states('binary_sensor.phoenix_control_room_exterior_door_contact') -%}
{%- set street = states('binary_sensor.phoenix_outside_door_contact') -%}
{%- set bell_person = states('binary_sensor.video_doorbell_person') -%}
{%- set bell_visitor = states('binary_sensor.video_doorbell_visitor') -%}
{%- set guest_hours = (as_timestamp(now()) - as_timestamp(states.input_boolean.phoenix_house_guest_mode_active.last_changed)) / 3600 -%}
{%- set guest_latched = guest == 'on' and guest_hours >= 8 -%}
{%- set any_open = shop == 'on' or apt == 'on' or street == 'on' -%}
{%- set bell = bell_person == 'on' or bell_visitor == 'on' -%}
{%- set unknown_core = intr not in ['on', 'off'] or lock not in ['on', 'off'] or guest not in ['on', 'off'] or test not in ['on', 'off'] or away_state not in ['on', 'off'] or bell_person not in ['on', 'off'] or bell_visitor not in ['on', 'off'] -%}
{%- set ns = namespace(parts=[]) -%}
{%- if test == 'on' -%}
  {%- set ns.parts = ns.parts + ['siren muted ' ~ relative_time(states.input_boolean.phoenix_intrusion_test_mode.last_changed) ~ ' ago, no auto-expiry'] -%}
{%- elif test == 'off' -%}
  {%- set ns.parts = ns.parts + ['siren live'] -%}
{%- else -%}
  {%- set ns.parts = ns.parts + ['siren unverified (' ~ test ~ ')'] -%}
{%- endif -%}
{%- if intr not in ['on', 'off'] -%}
  {%- set ns.parts = ns.parts + ['intrusion ' ~ intr] -%}
{%- endif -%}
{%- if lock == 'on' -%}
  {%- set ns.parts = ns.parts + ['lockdown on'] -%}
{%- elif lock not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['lockdown ' ~ lock] -%}
{%- endif -%}
{%- if guest == 'on' -%}
  {%- set ns.parts = ns.parts + ['guest mode on for ' ~ relative_time(states.input_boolean.phoenix_house_guest_mode_active.last_changed) ~ (', latched, arming blocked' if guest_latched else ', arming blocked')] -%}
{%- elif guest not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['guest mode ' ~ guest ~ ', arming unverified'] -%}
{%- endif -%}
{%- set all_closed = shop == 'off' and apt == 'off' and street == 'off' -%}
{%- if shop == 'on' -%}
  {%- set ns.parts = ns.parts + ['shop door open ' ~ relative_time(states.binary_sensor.phoenix_control_room_interior_door_contact.last_changed)] -%}
{%- elif shop not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['shop-door sensor ' ~ shop] -%}
{%- endif -%}
{%- if apt == 'on' -%}
  {%- set ns.parts = ns.parts + ['apartment door open ' ~ relative_time(states.binary_sensor.phoenix_control_room_exterior_door_contact.last_changed)] -%}
{%- elif apt not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['apartment-door sensor ' ~ apt] -%}
{%- endif -%}
{%- if street == 'on' -%}
  {%- set ns.parts = ns.parts + ['street door open ' ~ relative_time(states.binary_sensor.phoenix_outside_door_contact.last_changed)] -%}
{%- elif street not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['street-door sensor ' ~ street] -%}
{%- endif -%}
{%- if all_closed -%}
  {%- set ns.parts = ns.parts + ['doors closed'] -%}
{%- endif -%}
{%- if bell_person == 'on' -%}
  {%- set ns.parts = ns.parts + ['person at door'] -%}
{%- elif bell_visitor == 'on' -%}
  {%- set ns.parts = ns.parts + ['visitor at door'] -%}
{%- elif bell_person == 'off' and bell_visitor == 'off' -%}
  {%- set ns.parts = ns.parts + ['no doorbell'] -%}
{%- else -%}
  {%- set ns.parts = ns.parts + ['doorbell unverified'] -%}
{%- endif -%}
{%- if away_state == 'on' -%}
  {%- set ns.parts = ns.parts + ['everyone away'] -%}
{%- elif away_state not in ['off'] -%}
  {%- set ns.parts = ns.parts + ['occupancy ' ~ away_state] -%}
{%- endif -%}
{%- set prefix -%}
{# DOORS OPEN IS ITS OWN HEADLINE (2026-10-28). Found by the state tests: with a worker inside
   and BOTH doors open, `away` is false, so DOOR OPEN WHILE AWAY cannot fire, no other branch
   matched, and the banner said "BUILDING QUIET" while two doors stood open. Quiet is a claim
   about the building; it must not be made while a door is open. #}
{%- if intr == 'on' -%}INTRUSION ACTIVE
{%- elif test == 'on' -%}SIREN MUTED
{%- elif test not in ['on', 'off'] -%}SIREN UNVERIFIED
{%- elif lock == 'on' -%}LOCKDOWN ON
{%- elif away and any_open -%}DOOR OPEN WHILE AWAY
{%- elif bell -%}SOMEONE AT THE DOOR
{%- elif guest_latched -%}ARMING BLOCKED
{%- elif guest == 'on' -%}GUEST MODE ON
{%- elif any_open -%}DOORS OPEN
{%- elif unknown_core or shop not in ['on','off'] or apt not in ['on','off'] or street not in ['on','off'] -%}STATUS UNVERIFIED
{%- else -%}BUILDING QUIET
{%- endif -%}
{%- endset -%}
**{{ prefix }}** — {{ ns.parts | join(' · ') }}."""

# Keypad and code entries are not in a logbook-friendly entity on this instance: the
# `event.esphome.access_control_keypad_entry` entity does not exist at all, and the rolling
# `input_text.phoenix_access_control_log` produces 83 logbook events a day, most of them
# auto-departure noise. The clean read is the text itself, formatted as the top five lines —
# "Oct 28, 11:36 AM - Owner Access at Interior" is exactly the sentence he wants.
KEYPAD = """{%- set raw = states('input_text.phoenix_access_control_log') -%}
{%- set lines = raw.split('
') | reject('eq', '') | list -%}
{%- if lines -%}
{% for l in lines[:5] %}- {{ l }}
{% endfor %}
{%- else -%}
Nothing recorded yet.
{%- endif -%}"""

DOORS = [
    "binary_sensor.phoenix_control_room_interior_door_contact",
    "binary_sensor.phoenix_control_room_exterior_door_contact",
    "binary_sensor.phoenix_outside_door_contact",
    "binary_sensor.video_doorbell_person",
    "binary_sensor.video_doorbell_visitor",
]

SAFETY = [
    "input_boolean.phoenix_intrusion_active",
    "input_boolean.phoenix_intrusion_test_mode",
    "binary_sensor.phoenix_everyone_away",
    "binary_sensor.phoenix_control_room_interior_door_contact",
    "binary_sensor.phoenix_control_room_exterior_door_contact",
]


def config(use_target: bool = False) -> dict:
    # VERSION-PINNED (2026-10-28): this instance is Home Assistant 2025.10.3, frontend
    # 20251001.4. On that version the logbook card has NO `state_filter` -- the property
    # exists only in later docs and is SILENTLY IGNORED here. A "show arrivals only" filter
    # written against current docs would look correct in the config and do nothing on the
    # screen, which is the worst kind of bug: it survives review and lies to the eye.
    # So the noise is cut a different way -- fewer entities. Three, not five: the two doors
    # that matter and the doorbell's person detector.
    # `target.entity_id` is the canonical form on 2025.10.3; `entities:` still works but is
    # deprecated, so the canonical one is used.
    logbook: dict = {
        "type": "logbook",
        "title": "Doors and doorbell — last 12 hours",
        "hours_to_show": 12,
        "target": {"entity_id": [DOORS[0], DOORS[1], DOORS[3]]},
    }

    return {
        "title": "Shop",
        "views": [
            {
                "title": "Shop",
                "path": "main",
                "icon": "mdi:storefront",
                "cards": [
                    {"type": "markdown", "content": BANNER},
                    {
                        "type": "picture-glance",
                        "title": "Shop door — tap for live",
                        "camera_image": "camera.cam_front_hallway_main",
                        "camera_view": "auto",
                        "entities": [
                            {"entity": DOORS[0], "show_state": False},
                            {"entity": DOORS[3], "show_state": False},
                            {"entity": DOORS[4], "show_state": False},
                        ],
                    },
                    {
                        "type": "picture-glance",
                        "title": "Street door — outside stairwell",
                        "camera_image": "camera.reolink_video_doorbell_poe_clear",
                        "camera_view": "auto",
                        "entities": [
                            {"entity": DOORS[2], "show_state": False},
                            {"entity": DOORS[3], "show_state": False},
                        ],
                    },
                    {"type": "markdown", "title": "Keypad and codes — most recent first",
                     "content": KEYPAD},
                    logbook,
                    {
                        "type": "glance",
                        "title": "More cameras — tap for live",
                        "columns": 3,
                        "show_state": False,
                        "entities": [
                            {"entity": "camera.cam_waiting_room_main", "name": "Drop-off"},
                            {"entity": "camera.cam_deserted_exit_main", "name": "Control room"},
                            {"entity": "camera.cam_deserted_interior_main", "name": "Bench"},
                        ],
                    },
                    {"type": "custom:mushroom-title-card", "title": "Sensor health",
                     "subtitle": "an old time here means the sensor stopped talking"},
                    {"type": "entities", "state_color": True,
                     "entities": [{"entity": e, "secondary_info": "last-changed"} for e in SAFETY]},
                ],
            }
        ],
    }


def env(key: str) -> str | None:
    try:
        with open(ENV, encoding='utf-8', errors='replace') as fh:
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


async def _connect():
    import websockets

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        raise SystemExit('HA_URL or HA_TOKEN missing from ' + ENV)
    ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
    _kw: dict = {"max_size": 64 * 1024 * 1024}
    if ws_url.startswith('wss://'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _kw['ssl'] = ctx
    ws = await websockets.connect(ws_url, **_kw)
    await ws.recv()
    await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
    if json.loads(await ws.recv()).get('type') != 'auth_ok':
        raise SystemExit('auth failed')
    return ha, token, ws


async def apply(url_path: str, dry: bool, use_target: bool) -> int:
    cfg = config(use_target)
    if dry:
        cards = cfg['views'][0]['cards']
        print('dry run: %d cards, %d bytes' % (len(cards), len(json.dumps(cfg))))
        for c in cards:
            print('  -', c.get('type'), c.get('title') or '')
        return 0

    ha, token, ws = await _connect()
    counter = {'id': 1}

    async def call(payload: dict) -> dict:
        payload = dict(payload)
        payload['id'] = counter['id']
        counter['id'] += 1
        await ws.send(json.dumps(payload))
        while True:
            raw = json.loads(await ws.recv())
            if raw.get('id') == payload['id']:
                return raw

    try:
        have = {d.get('url_path') for d in ((await call({'type': 'lovelace/dashboards/list'})).get('result') or [])}
        if url_path not in have:
            made = await call({'type': 'lovelace/dashboards/create', 'url_path': url_path,
                               'title': 'Shop', 'icon': 'mdi:storefront',
                               'show_in_sidebar': True, 'require_admin': False,
                               'mode': 'storage'})
            print('create:', made.get('success'), (made.get('error') or {}).get('message', ''))
        saved = await call({'type': 'lovelace/config/save', 'url_path': url_path, 'config': cfg})
        print('save  :', saved.get('success'), (saved.get('error') or {}).get('message', ''))
        back = (await call({'type': 'lovelace/config', 'url_path': url_path})).get('result') or {}
        views = back.get('views') or []
        kinds = [c.get('type') for c in (views[0].get('cards') if views else [])]
        print('readback: %d view(s); %d cards: %s' % (len(views), len(kinds), ', '.join(kinds)))
        return 0 if saved.get('success') else 1
    finally:
        await ws.close()


if __name__ == '__main__':
    argv = sys.argv[1:]
    path = 'shop-view'
    if '--url-path' in argv:
        path = argv[argv.index('--url-path') + 1]
    sys.exit(asyncio.run(apply(path, '--dry' in argv, '--target' in argv)))
