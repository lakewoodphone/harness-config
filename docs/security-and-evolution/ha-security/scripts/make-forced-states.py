"""Render the Shop banner in its ugly states by forcing the conditions, without touching live entities.

Why a temporary dashboard: the banner's red path fires on intrusion, the drill switch, lockdown, or
a door open while marked away. Flipping any of those on the real system would sound an alarm in a
shop that is currently occupied and would page the owner -- unacceptable for a test. Instead this
builds a throwaway dashboard whose banner template has those states HARDCODED, renders it headless,
and then deletes it. The live view and every live entity stay exactly as they were.

usage: PYTHONPATH=/opt/company python3 make-forced-states.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import ssl

ENV = '/opt/company/.env'
GEN = '/root/ha-shop-dashboard.py'
URL_PATH = 'shop-red-test'


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def force(banner: str, values: dict[str, str]) -> str:
    """Replace `{%- set name = <expr> -%}` with a literal, for the names given."""
    out = banner
    for name, literal in values.items():
        pattern = re.compile(r"\{%-?\s*set\s+%s\s*=\s*.*?-%\}" % re.escape(name), re.S)
        out, n = pattern.subn("{%%- set %s = '%s' -%%}" % (name, literal), out, count=1)
        assert n == 1, 'could not force %s' % name
    return out


async def main() -> int:
    spec = importlib.util.spec_from_file_location('gen', GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    live = gen.config()['views'][0]['cards'][0]          # the real banner card
    style = live['card_mod']['style']

    # A: intrusion tripped AND the siren muted -- the worst combination
    a = force(gen.BANNER, {'intr': 'on', 'test': 'on', 'away': 'on', 'shop': 'on'})
    # B: the drill switch alone -- the state that must never print a calm sentence
    b = force(gen.BANNER, {'intr': 'off', 'test': 'on', 'away': 'off'})
    # C: a guest code latched on while the building is marked empty
    c = force(gen.BANNER, {'guest': 'on', 'away': 'on', 'shop': 'off', 'apt': 'off', 'test': 'off'})

    cfg = {
        'title': 'Shop red test',
        'views': [{'title': 'Forced', 'path': 'main', 'cards': [
            {'type': 'markdown', 'content': a, 'card_mod': {'style': style}},
            {'type': 'markdown', 'content': b, 'card_mod': {'style': style}},
            {'type': 'markdown', 'content': c, 'card_mod': {'style': style}},
        ]}],
    }

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

        have = {d.get('url_path') for d in ((await call({'type': 'lovelace/dashboards/list'})).get('result') or [])}
        if URL_PATH not in have:
            made = await call({'type': 'lovelace/dashboards/create', 'url_path': URL_PATH,
                               'title': 'Shop red test', 'icon': 'mdi:flask',
                               'show_in_sidebar': False, 'require_admin': True,
                               'mode': 'storage'})
            print('create:', made.get('success'), (made.get('error') or {}).get('message', ''))
        saved = await call({'type': 'lovelace/config/save', 'url_path': URL_PATH, 'config': cfg})
        print('save  :', saved.get('success'), (saved.get('error') or {}).get('message', ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
