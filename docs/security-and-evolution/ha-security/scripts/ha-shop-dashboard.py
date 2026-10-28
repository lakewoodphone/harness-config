#!/usr/bin/env python3
"""Create a simple 'Shop' dashboard in Home Assistant: pictures, a timeline, alerts.

No files are written on the HA host — this uses the websocket API's lovelace commands
(dashboards/create + config/save), which is the only route available when /config is not
reachable over ssh or samba (measured 2026-10-27: only 8123 answers).
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys

import websockets

ENV = '/opt/company/.env'
URL_PATH = 'shop'
TITLE = 'Shop'


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


CONFIG = {
    "title": TITLE,
    "views": [
        {
            "title": "Now",
            "path": "now",
            "icon": "mdi:storefront",
            "cards": [
                {
                    "type": "markdown",
                    "content": (
                        "{% set away = is_state('binary_sensor.phoenix_everyone_away','on') %}"
                        "{% set intr = is_state('input_boolean.phoenix_intrusion_active','on') %}"
                        "{% if intr %}## 🔴 INTRUSION ACTIVE\n{% elif away %}## 🟢 Empty and armed\n"
                        "{% else %}## 🟡 Someone is here\n{% endif %}"
                        "Door: {{ states('binary_sensor.phoenix_control_room_interior_door_contact') }} · "
                        "Apartment: {{ states('binary_sensor.phoenix_control_room_exterior_door_contact') }} · "
                        "Keypad: {{ states('input_boolean.phoenix_house_guest_mode_active') }}"
                    ),
                },
                {
                    "type": "picture-glance",
                    "title": "Shop door (hallway)",
                    "camera_image": "camera.cam_front_hallway_main",
                    "camera_view": "auto",
                    "entities": [],
                },
                {
                    "type": "picture-glance",
                    "title": "Drop-off / pickup",
                    "camera_image": "camera.cam_waiting_room_main",
                    "camera_view": "auto",
                    "entities": [],
                },
                {
                    "type": "picture-glance",
                    "title": "Outside (doorbell)",
                    "camera_image": "camera.reolink_video_doorbell_poe_clear",
                    "camera_view": "auto",
                    "entities": [],
                },
                {
                    "type": "entities",
                    "title": "Doors and presence",
                    "entities": [
                        "binary_sensor.phoenix_control_room_interior_door_contact",
                        "binary_sensor.phoenix_control_room_exterior_door_contact",
                        "binary_sensor.phoenix_outside_door_contact",
                        "binary_sensor.video_doorbell_person",
                        "binary_sensor.control_room_hub_control_room_presence",
                    ],
                },
            ],
        },
        {
            "title": "Timeline",
            "path": "timeline",
            "icon": "mdi:timeline-clock",
            "cards": [
                {
                    "type": "logbook",
                    "title": "Doors and keypad, last 24 hours",
                    "hours_to_show": 24,
                    "entities": [
                        "binary_sensor.phoenix_control_room_interior_door_contact",
                        "binary_sensor.phoenix_control_room_exterior_door_contact",
                        "binary_sensor.phoenix_outside_door_contact",
                        "binary_sensor.video_doorbell_person",
                        "input_boolean.phoenix_house_guest_mode_active",
                    ],
                },
                {
                    "type": "history-graph",
                    "title": "Doors, last 24 hours",
                    "hours_to_show": 24,
                    "entities": [
                        "binary_sensor.phoenix_control_room_interior_door_contact",
                        "binary_sensor.phoenix_control_room_exterior_door_contact",
                        "binary_sensor.video_doorbell_person",
                    ],
                },
                {
                    "type": "markdown",
                    "title": "What the record holds",
                    "content": (
                        "Every arrival, keypad press and verdict is also kept outside Home Assistant, "
                        "on the company server, with a picture and a hash for each one. This view is the "
                        "quick look; the full record lives in the company."
                    ),
                },
            ],
        },
    ],
}


async def main() -> int:
    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing from', ENV)
        return 1
    ws_url = ha.replace('https://', 'wss://').replace('http://', 'ws://') + '/api/websocket'
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    async with websockets.connect(ws_url, ssl=ctx, max_size=32 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        if hello.get('type') != 'auth_required':
            print('unexpected hello:', hello)
        await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        auth = json.loads(await ws.recv())
        print('auth:', auth.get('type'))
        if auth.get('type') != 'auth_ok':
            return 1

        msg_id = 1

        async def call(payload: dict) -> dict:
            nonlocal msg_id
            payload = dict(payload)
            payload['id'] = msg_id
            msg_id += 1
            await ws.send(json.dumps(payload))
            while True:
                raw = json.loads(await ws.recv())
                if raw.get('id') == payload['id']:
                    return raw

        existing = await call({'type': 'lovelace/dashboards/list'})
        have = {d.get('url_path') for d in (existing.get('result') or [])}
        print('existing storage dashboards:', sorted(have) or '(none)')
        if URL_PATH not in have:
            created = await call({
                'type': 'lovelace/dashboards/create',
                'url_path': URL_PATH,
                'title': TITLE,
                'icon': 'mdi:storefront',
                'show_in_sidebar': True,
                'require_admin': False,
                'mode': 'storage',
            })
            print('create:', created.get('success'), (created.get('error') or {}).get('message', ''))
        else:
            print('dashboard already exists, updating its config')

        saved = await call({
            'type': 'lovelace/config/save',
            'url_path': URL_PATH,
            'config': CONFIG,
        })
        print('config save:', saved.get('success'), (saved.get('error') or {}).get('message', ''))

        back = await call({'type': 'lovelace/config', 'url_path': URL_PATH})
        cfg = back.get('result') or {}
        views = cfg.get('views') or []
        print('readback: %d view(s)' % len(views),
              '|', ', '.join('%s (%d cards)' % (v.get('title'), len(v.get('cards') or [])) for v in views))
        return 0 if saved.get('success') else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
