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
import re
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
    """The view, in reading order, built to the measured phone budget.

    A 390 px phone gives about 700 px above the fold. Measured height of the previous layout:
    banner 76 + two camera tiles 420 + keypad 164 = 692 px, so the timeline started exactly at
    the fold and was never seen. Three changes came out of that measurement:

      * ONE hero camera instead of two. The hallway camera is kept because it is the shop-door
        threshold and the best face view (measured 2026-10-27); the street-door tile cost 210 px
        to duplicate a job the banner already does in words.
      * The doors get their own two-up row with the STATE IN WORDS. Before this, open-vs-closed
        existed only as an icon colour, which is the most important fact on the page rendered as
        a swatch.
      * The self-describing titles are gone. "Keypad and codes - most recent first" and "More
        cameras - tap for live" cost about 140 px of a screen to explain themselves.
    """
    logbook_titles: dict = {}

    # A COLOURED EDGE SO AN ALARM LOOKS LIKE AN ALARM (2026-10-28). The render showed the
    # banner reading identically whether the building was quiet or a door was open with
    # nobody home -- same weight, same colour, same height. That is the one place in this
    # layout where typography alone fails. card-mod styles the standard markdown card, so if
    # card-mod is ever missing the style is simply ignored and the card still works: this
    # adds no custom-card dependency to the view.
    banner = {
        "type": "markdown",
        "content": BANNER,
        "card_mod": {"style": """ha-card {
  {% set intr = is_state('input_boolean.phoenix_intrusion_active','on') %}
  {% set test = is_state('input_boolean.phoenix_intrusion_test_mode','on') %}
  {% set lock = is_state('input_boolean.phoenix_access_control_lockdown','on') %}
  {% set away = is_state('binary_sensor.phoenix_everyone_away','on') %}
  {% set shop = is_state('binary_sensor.phoenix_control_room_interior_door_contact','on') %}
  {% set apt = is_state('binary_sensor.phoenix_control_room_exterior_door_contact','on') %}
  {% set guest = is_state('input_boolean.phoenix_house_guest_mode_active','on') %}
  {% if intr or test or lock or (away and (shop or apt)) %}
    border-left: 8px solid var(--error-color);
    background: rgba(219, 68, 55, 0.12);
  {% elif guest or shop or apt %}
    border-left: 8px solid var(--warning-color);
    background: rgba(255, 152, 0, 0.10);
  {% else %}
    border-left: 8px solid var(--success-color);
  {% endif %}
}"""},
    }
    cards: list = [
        banner,
        # the shop door: the threshold where customers appear, and the best face view
        {"type": "picture-glance", "title": "Shop door",
         "camera_image": "camera.cam_front_hallway_main",
         "camera_view": "auto",
         "entities": [{"entity": DOORS[0]}]},
        # open/closed in WORDS, two-up. Built-in glance, so nothing depends on a custom card.
        {"type": "glance", "columns": 2, "show_state": True,
         "entities": [{"entity": DOORS[0], "name": "Shop door"},
                      {"entity": DOORS[1], "name": "Apartment"}]},
        # keypad: no title, four lines. `- ` bullets are why this renders as a list at all;
        # markdown collapses bare newlines.
        {"type": "markdown", "content": KEYPAD.replace('lines[:5]', 'lines[:4]')},
        # doors over 24h as bands: an open door is a coloured bar with a start and an end,
        # which is easier to read than rows you have to pair up by eye.
        {"type": "history-graph", "title": "Doors - last 24 hours",
         "hours_to_show": 24,
         "entities": [{"entity": DOORS[0], "name": "Shop"},
                      {"entity": DOORS[1], "name": "Apartment"}]},
        # THE OTHER THREE CAMERAS, AS REAL CAMERA TILES (2026-10-28).
        # A `glance` of camera entities is a trap on 2025.10.3: it has no camera branch, so it
        # renders a 40x40 state badge fed by `entity_picture` -- an 80x80 crop, fetched once,
        # with NO refresh interval. A dead camera and a live one look identical, and the state
        # text that would say "unavailable" is hidden. `picture-entity` with the camera as its
        # own entity polls the still every ~10 s, so a frozen frame cannot masquerade as live.
        # THE LOGBOOK CARD IS GONE (2026-10-28) -- it renders NOTHING on this instance.
        # Rendered headless at 390 px and looked at: with `target.entity_id` AND with the
        # deprecated `entities` form it drew a 479 px EMPTY white card, no rows, and no
        # console error. The backend is not the problem -- a direct `logbook/get_events` call
        # for the same two entities and the same 12-hour window returns rows. So the card is
        # dead here for a reason I could not find from the outside, and a half-screen of
        # blank white is worse than no list at all.
        # What replaces it: the graph above already shows WHEN (a band with a start and an
        # end), and the keypad card shows WHO. Those two answer the question between them.
        # FOUR cameras, 2x2 (2026-10-28). The outside doorbell was dropped in the relayout and
        # the preflight caught it: the view referenced four cameras, not five, so the one camera
        # that sees a person BEFORE they reach the door had no view at all. It is first in this
        # grid because it is the most useful of the four. Two columns rather than three, because
        # three across a 390 px phone leaves ~118 px per tile and a face is unreadable at that
        # size.
        {"type": "grid", "columns": 2, "square": True, "cards": [
            {"type": "picture-entity", "entity": "camera.reolink_video_doorbell_poe_clear",
             "name": "Outside", "show_name": True, "show_state": False, "camera_view": "auto"},
            {"type": "picture-entity", "entity": "camera.cam_waiting_room_main",
             "name": "Drop-off", "show_name": True, "show_state": False, "camera_view": "auto"},
            {"type": "picture-entity", "entity": "camera.cam_deserted_exit_main",
             "name": "Control", "show_name": True, "show_state": False, "camera_view": "auto"},
            {"type": "picture-entity", "entity": "camera.cam_deserted_interior_main",
             "name": "Bench", "show_name": True, "show_state": False, "camera_view": "auto"},
        ]},
    ]

    # THE SENSOR-HEALTH CARD IS GONE (2026-10-28). Five rows plus a title card came to about
    # 364 px -- half a phone screen -- for values he never sets and cannot act on from there.
    # Its one unique fact, "a sensor has stopped talking", is what the banner's STATUS
    # UNVERIFIED state already exists for. The card added pixels, not capability.

    return {"title": "Shop", "views": [{"title": "Shop", "path": "main",
                                        "icon": "mdi:storefront", "cards": cards}]}


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
        # REFUSE TO SAVE A VIEW THAT POINTS AT SOMETHING THAT DOES NOT EXIST (2026-10-28).
        # `lovelace/config/save` performs no schema validation at all: a wrong entity id is
        # stored happily and renders "Entity not found" or an empty tile at run time, where
        # nobody sees it until the owner opens the dashboard. One entity referenced by an
        # earlier draft of this view (event.esphome.access_control_keypad_entry) did not exist
        # at all. This gate costs one get_states call and makes that class of mistake
        # impossible to ship.
        _ENT = re.compile(r'\b((?:binary_sensor|sensor|camera|input_boolean|input_text|'
                          r'input_number|event|switch|light|script|automation|person|'
                          r'device_tracker|weather|sun|media_player|number|select|button|'
                          r'scene|timer|calendar|update)\.[a-z0-9_]+)')
        _states = (await call({'type': 'get_states'})).get('result') or []
        _live = {x['entity_id'] for x in _states}
        _used = set(_ENT.findall(json.dumps(cfg)))
        _missing = sorted(_used - _live)
        if _missing:
            print('REFUSING TO SAVE: %d entity id(s) do not exist on this instance:' % len(_missing))
            for _m in _missing:
                print('   -', _m)
            return 1
        print('preflight: %d entity ids all present, %d custom card(s)'
              % (len(_used), len([t for t in re.findall(r'"type": "(custom:[^"]+)"', json.dumps(cfg))])))

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
