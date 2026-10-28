#!/usr/bin/env python3
"""Render and apply ONE shop dashboard to Home Assistant, idempotently.

Why a generator and not a JSON blob: the dashboard is applied over the websocket API
(`lovelace/dashboards/create` + `lovelace/config/save`) because this machine has no file
route into /config — only 8123 answers from anywhere else. A generator means the layout is
reviewable in git, can be re-applied after a mistake, and is the single source of truth for
what the owner's phone shows.

Design rules (owner: "way too complex … i don't need the whole backend data dump", and
"one clear simplified view"):
  * ONE view, one column, readable on a phone.
  * The first thing on the screen is one honest sentence about the building.
  * A calm sentence can never appear while the siren is muted — guaranteed by branch
    POSITION, not by remembering to check (the three test-mode branches exhaust test==on
    before any calm branch is reachable).
  * It says "No alerts", never "safe": every input is a flag, and none of them is panel
    health, armed state or siren continuity. A disarmed panel, a cut siren wire and a quiet
    building all look identical from here.
  * The three cameras that see something useful, in the order a person arrives.
  * The timeline last, because it is for looking back, not for a glance.
  * Sensor health last, small: a frozen last_changed is the only way this view can show a
    sensor that died without going `unavailable`.

Banner credit: designed 2026-10-28, 18 state rows rendered through Jinja2 3.1.6 with stubbed
states()/is_state(), so the sentences are literal output rather than intention.

usage:  PYTHONPATH=/opt/company python3 ha-shop-dashboard.py [--url-path shop-view] [--dry]
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys

ENV = '/opt/company/.env'

# `<br>` because markdown eats bare newlines inside a paragraph.
BANNER = """{%- set intr = is_state('input_boolean.phoenix_intrusion_active','on') -%}
{%- set test = is_state('input_boolean.phoenix_intrusion_test_mode','on') -%}
{%- set lock = is_state('input_boolean.phoenix_access_control_lockdown','on') -%}
{%- set away = is_state('binary_sensor.phoenix_everyone_away','on') -%}
{%- set here = is_state('input_boolean.phoenix_user_is_here','on') -%}
{%- set work = is_state('input_boolean.phoenix_worker_is_here','on') -%}
{%- set guest = is_state('input_boolean.phoenix_house_guest_mode_active','on') -%}
{%- set motion = is_state('binary_sensor.control_room_hub_control_room_presence','on') -%}
{%- set shop = is_state('binary_sensor.phoenix_control_room_interior_door_contact','on') -%}
{%- set apt = is_state('binary_sensor.phoenix_control_room_exterior_door_contact','on') -%}
{%- set bell = is_state('binary_sensor.video_doorbell_person','on') -%}
{%- set unknown = states('input_boolean.phoenix_intrusion_active') in ['unknown','unavailable']
   or states('input_boolean.phoenix_intrusion_test_mode') in ['unknown','unavailable']
   or states('binary_sensor.phoenix_everyone_away') in ['unknown','unavailable']
   or states('binary_sensor.phoenix_control_room_interior_door_contact') in ['unknown','unavailable']
   or states('binary_sensor.phoenix_control_room_exterior_door_contact') in ['unknown','unavailable'] -%}
{%- set doors = 'Both doors' if shop and apt else ('Shop door' if shop else 'Apartment door') -%}
{%- set who = 'You are in the building.' if here else ('A worker is in the building.' if work else 'No one is flagged as present.') -%}
{%- if intr and test -%}
**ALARM TRIPPED, SIREN SILENCED.**<br>Test mode is on. Turn it off to hear the siren.
{%- elif intr -%}
**ALARM GOING OFF NOW.**<br>Check cameras.
{%- elif test and unknown -%}
**CANNOT CONFIRM, SIREN SILENCED.**<br>Test mode is on and a sensor is offline.
{%- elif test -%}
**SIREN SILENCED — TEST MODE ON.**<br>No alarm will sound. Turn test mode off when done.
{%- elif unknown -%}
**CANNOT CONFIRM THE BUILDING.**<br>A sensor is offline. This card cannot see the building.
{%- elif away and (here or work or motion) -%}
**CANNOT TELL IF ANYONE IS HOME.**<br>Away flag and presence sensors disagree. Check cameras.
{%- elif away and (shop or apt) -%}
**DOOR OPEN, NOBODY HOME.**<br>{{ doors }} open.
{%- elif guest and away -%}
**GUEST MODE ON, NOBODY HOME.**<br>Alarm cannot arm. Turn guest mode off.
{%- elif lock -%}
**ACCESS CONTROL LOCKED DOWN.**<br>Doors stay locked until it is cleared.
{%- elif guest -%}
**GUEST MODE ON.**<br>Alarm cannot arm. Turn it off when the guest leaves.
{%- elif motion and not here and not work -%}
**MOVEMENT IN THE CONTROL ROOM.**<br>No one is flagged as present.
{%- elif shop or apt -%}
**{{ doors }} open.**<br>{{ who }}
{%- elif bell -%}
**SOMEONE AT THE OUTER DOOR.**
{%- else -%}
**No alerts.**
{%- endif -%}"""

SAFETY = [
    "input_boolean.phoenix_intrusion_active",
    "input_boolean.phoenix_intrusion_test_mode",
    "binary_sensor.phoenix_everyone_away",
    "binary_sensor.phoenix_control_room_interior_door_contact",
    "binary_sensor.phoenix_control_room_exterior_door_contact",
]


def config() -> dict:
    return {
        "title": "Shop",
        "views": [
            {
                "title": "Shop",
                "path": "main",
                "icon": "mdi:storefront",
                "cards": [
                    {"type": "markdown", "content": BANNER},
                    {"type": "custom:mushroom-title-card", "title": "Cameras"},
                    {"type": "picture-glance", "title": "Shop door",
                     "camera_image": "camera.cam_front_hallway_main",
                     "camera_view": "auto", "entities": []},
                    {"type": "picture-glance", "title": "Drop-off and pickup",
                     "camera_image": "camera.cam_waiting_room_main",
                     "camera_view": "auto", "entities": []},
                    {"type": "picture-glance", "title": "Outside",
                     "camera_image": "camera.reolink_video_doorbell_poe_clear",
                     "camera_view": "auto", "entities": []},
                    {"type": "custom:mushroom-title-card", "title": "Today"},
                    {"type": "logbook", "hours_to_show": 24,
                     "entities": [
                         "binary_sensor.phoenix_control_room_interior_door_contact",
                         "binary_sensor.phoenix_control_room_exterior_door_contact",
                         "binary_sensor.video_doorbell_person",
                         "input_boolean.phoenix_house_guest_mode_active",
                     ]},
                    {"type": "custom:mushroom-title-card", "title": "Sensor health",
                     "subtitle": "a frozen time here means the sensor has stopped talking"},
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


async def apply(url_path: str, dry: bool) -> int:
    import websockets

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing from', ENV)
        return 1
    ws_url = ha.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'
    _kw: dict = {"max_size": 64 * 1024 * 1024}
    if ws_url.startswith('wss://'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _kw['ssl'] = ctx

    cfg = config()
    if dry:
        cards = cfg['views'][0]['cards']
        print('dry run: %d cards, %d bytes of config' % (len(cards), len(json.dumps(cfg))))
        for c in cards:
            print('  -', c.get('type'), c.get('title') or '')
        return 0

    async with websockets.connect(ws_url, **_kw) as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        if json.loads(await ws.recv()).get('type') != 'auth_ok':
            print('auth failed')
            return 1

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


if __name__ == '__main__':
    argv = sys.argv[1:]
    path = 'shop-view'
    if '--url-path' in argv:
        path = argv[argv.index('--url-path') + 1]
    sys.exit(asyncio.run(apply(path, '--dry' in argv)))
