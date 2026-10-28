#!/usr/bin/env python3
"""Preflight: every entity the Shop view references must exist in Home Assistant.

Why this exists (2026-10-28). A wrong entity id is NOT a save error: `lovelace/config/save`
performs no schema validation, the config is stored exactly as sent, and the card then renders
"Entity not found" or an empty tile at run time. Nothing in the apply path can catch that, and
nobody sees it until the owner opens the dashboard. Two ids in this view were already
UNCERTAIN in the audit (`camera.reolink_video_doorbell_poe_clear`, the two doorbell
`binary_sensor.*`), and one entity referenced by an earlier draft
(`event.esphome.access_control_keypad_entry`) turned out not to exist at all.

It also reports which card types are custom (``custom:``) — a custom card is a dependency on a
HACS resource, and if that resource goes missing the card becomes an error box. The view should
need as few as possible.

usage:  PYTHONPATH=/opt/company python3 check-shop-entities.py [/root/ha-shop-dashboard.py]
exit 0 = every referenced entity exists; 1 = something is missing; 2 = cannot reach HA.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import ssl
import sys

GEN = sys.argv[1] if len(sys.argv) > 1 else '/root/ha-shop-dashboard.py'
ENV = '/opt/company/.env'
ENTITY_RE = re.compile(r'\b((?:binary_sensor|sensor|camera|input_boolean|input_text|input_number|'
                       r'event|switch|light|script|automation|person|device_tracker|weather|sun|'
                       r'media_player|number|select|button|scene|timer|calendar|update|'
                       r'sensor_template)\.[a-z0-9_]+)')


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def referenced(cfg: dict) -> dict[str, list[str]]:
    """entity id -> [where it is used], so a failure names the card."""
    found: dict[str, list[str]] = {}
    cards = cfg.get('views', [{}])[0].get('cards') or []
    for idx, card in enumerate(cards, 1):
        label = 'card %d (%s%s)' % (idx, card.get('type'),
                                    ' "' + card['title'] + '"' if card.get('title') else '')
        blob = json.dumps(card)
        for ent in set(ENTITY_RE.findall(blob)):
            found.setdefault(ent, []).append(label)
    return found


def custom_cards(cfg: dict) -> list[str]:
    out = []
    for card in cfg.get('views', [{}])[0].get('cards') or []:
        stack = [card]
        while stack:
            c = stack.pop()
            t = c.get('type') or ''
            if t.startswith('custom:'):
                out.append(t)
            stack.extend(c.get('cards') or [])
            if isinstance(c.get('card'), dict):
                stack.append(c['card'])
    return out


async def main() -> int:
    spec = importlib.util.spec_from_file_location('gen', GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    cfg = gen.config()

    used = referenced(cfg)
    print('entities referenced by the view: %d' % len(used))

    import websockets

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing')
        return 2
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
        await ws.send(json.dumps({'id': 1, 'type': 'get_states'}))
        while True:
            raw = json.loads(await ws.recv())
            if raw.get('id') == 1:
                break
        live = {s['entity_id'] for s in raw.get('result') or []}

    missing = {e: w for e, w in used.items() if e not in live}
    unused_ok = [e for e in used if e in live]

    print('  present: %d' % len(unused_ok))
    if missing:
        print('  MISSING: %d' % len(missing))
        for e, where in sorted(missing.items()):
            print('    %-58s used by %s' % (e, ', '.join(where)))
    else:
        print('  MISSING: 0')

    custom = custom_cards(cfg)
    print('custom cards depended on: %s' % (', '.join(sorted(set(custom))) if custom else 'none'))

    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
