#!/usr/bin/env python3
"""Render and apply ONE shop dashboard to Home Assistant, idempotently.

Why a generator and not a JSON blob: the dashboard is applied over the websocket API
(`lovelace/dashboards/create` + `lovelace/config/save`) because this machine has no file
route into /config — only 8123 answers from anywhere else. A generator means the layout is
reviewable in git, can be re-applied after a mistake, and is the single source of truth for
what the owner's phone shows.

Design rules behind it (2026-10-28, owner's words: "way too complex … i don't need the whole
backend data dump" and "one clear simplified view"):
  * ONE view, one column, readable on a phone.
  * The first thing on the screen is one honest sentence about the building.
  * The muted-siren state can never hide under a calm sentence.
  * The three cameras that see something useful, in the order a person arrives.
  * Today's timeline last, because it is for looking back, not for a glance.

usage:  PYTHONPATH=/opt/company python3 ha-shop-dashboard.py [--url-path shop-view] [--dry]
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys

ENV = '/opt/company/.env'

BANNER = (
    "{% set intr = is_state('input_boolean.phoenix_intrusion_active','on') %}"
    "{% set test = is_state('input_boolean.phoenix_intrusion_test_mode','on') %}"
    "{% set lock = is_state('input_boolean.phoenix_access_control_lockdown','on') %}"
    "{% set away = is_state('binary_sensor.phoenix_everyone_away','on') %}"
    "{% set guest = is_state('input_boolean.phoenix_house_guest_mode_active','on') %}"
    "{% set shopdoor = is_state('binary_sensor.phoenix_control_room_interior_door_contact','on') %}"
    "{% set aptdoor = is_state('binary_sensor.phoenix_control_room_exterior_door_contact','on') %}"
    "{% set here = is_state('input_boolean.phoenix_user_is_here','on') "
    "or is_state('binary_sensor.control_room_hub_control_room_presence','on') %}"
    "{# THE MUTED SIREN OUTRANKS A CALM SENTENCE. Siren silenced is the one state where the "
    "building looks fine and an alarm would do nothing. #}"
    "{% if test and intr %}"
    "## 🔴 ALARM GOING OFF — AND THE SIREN IS MUTED\nA drill switch is on, so nothing is sounding."
    "{% elif test %}"
    "## ⚠️ Siren is MUTED (drill switch on)\nA real alarm right now would be silent. Turn the drill switch off."
    "{% elif intr %}"
    "## 🔴 ALARM GOING OFF"
    "{% elif lock %}"
    "## ⚠️ Access control is locked down"
    "{% elif guest and away %}"
    "## ⚠️ Marked empty, but a house code is still active\nThe alarm cannot arm while that is on."
    "{% elif shopdoor and away %}"
    "## ⚠️ Shop door is open while the building is marked empty"
    "{% elif aptdoor %}"
    "## 🟡 Apartment door is open"
    "{% elif not here %}"
    "## 🟢 Empty and armed"
    "{% else %}"
    "## 🟡 Someone is inside"
    "{% endif %}"
)


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
                    {
                        "type": "conditional",
                        "conditions": [
                            {"condition": "state",
                             "entity": "input_boolean.phoenix_intrusion_test_mode",
                             "state": "on"},
                        ],
                        "card": {
                            "type": "markdown",
                            "content": (
                                "**The siren will not sound.** While the drill switch is on, an intruder "
                                "gets silence. Nothing turns it off automatically."
                            ),
                        },
                    },
                    {"type": "custom:mushroom-title-card", "title": "Cameras"},
                    {
                        "type": "picture-glance",
                        "title": "Shop door",
                        "camera_image": "camera.cam_front_hallway_main",
                        "camera_view": "auto",
                        "entities": [],
                    },
                    {
                        "type": "picture-glance",
                        "title": "Drop-off and pickup",
                        "camera_image": "camera.cam_waiting_room_main",
                        "camera_view": "auto",
                        "entities": [],
                    },
                    {
                        "type": "picture-glance",
                        "title": "Outside",
                        "camera_image": "camera.reolink_video_doorbell_poe_clear",
                        "camera_view": "auto",
                        "entities": [],
                    },
                    {"type": "custom:mushroom-title-card", "title": "Today"},
                    {
                        "type": "logbook",
                        "hours_to_show": 24,
                        "entities": [
                            "binary_sensor.phoenix_control_room_interior_door_contact",
                            "binary_sensor.phoenix_control_room_exterior_door_contact",
                            "binary_sensor.video_doorbell_person",
                            "input_boolean.phoenix_house_guest_mode_active",
                        ],
                    },
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
        print(json.dumps(cfg, indent=1)[:1200])
        print('... (%d cards in one view; dry run, nothing applied)' % len(cfg['views'][0]['cards']))
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
