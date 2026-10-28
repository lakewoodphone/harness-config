#!/usr/bin/env python3
"""Test the deployed Shop banner against the states that matter, without touching Home Assistant.

The banner is a Jinja template compiled with `strict: true` by Home Assistant, and a runtime
error there is SUPPRESSED outside the editor: the card goes blank or stale rather than showing
an error. So the only way to know what it says in an ugly state is to render it — and the only
safe way to render an ugly state is with stubbed states, not by flipping the owner's live alarm
flags.

This renders the ACTUAL BANNER constant from the deployed generator, so the test always tests
what is live rather than a copy that has drifted.

usage:  python3 test-banner-states.py [/root/ha-shop-dashboard.py]
exit 0 = every assertion passed, 1 = at least one failed.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone

import jinja2

GEN = sys.argv[1] if len(sys.argv) > 1 else '/root/ha-shop-dashboard.py'

ENTITIES = [
    'input_boolean.phoenix_intrusion_active',
    'input_boolean.phoenix_intrusion_test_mode',
    'input_boolean.phoenix_access_control_lockdown',
    'input_boolean.phoenix_house_guest_mode_active',
    'input_boolean.phoenix_user_is_here',
    'input_boolean.phoenix_worker_is_here',
    'binary_sensor.phoenix_everyone_away',
    'binary_sensor.phoenix_control_room_interior_door_contact',
    'binary_sensor.phoenix_control_room_exterior_door_contact',
    'binary_sensor.phoenix_outside_door_contact',
    'binary_sensor.video_doorbell_person',
    'binary_sensor.video_doorbell_visitor',
    'binary_sensor.control_room_hub_control_room_presence',
]

NOW = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


class _Node:
    """Supports states.input_boolean.foo.last_changed attribute chains.

    `changed` maps a full entity id to the datetime it last changed, so a test can say
    "guest mode has been on for nine hours" -- without that, every entity is always
    freshly changed, `guest_latched` can never be true, and the latched path is untested.
    """

    def __init__(self, path: str, changed: dict):
        object.__setattr__(self, '_path', path)
        object.__setattr__(self, '_changed', changed)

    def __getattr__(self, item: str):
        path = object.__getattribute__(self, '_path')
        changed = object.__getattribute__(self, '_changed')
        if item == 'last_changed':
            return changed.get(path, NOW)
        return _Node(path + '.' + item, changed)


class _States:
    def __init__(self, values: dict, changed: dict):
        self._values = values
        self._changed = changed

    def __getattr__(self, item: str):
        return _Node(item, self._changed)

    def __call__(self, entity_id: str) -> str:
        return self._values.get(entity_id, 'off')

    def get(self, entity_id: str) -> str:
        return self._values.get(entity_id, 'off')


def render(banner: str, values: dict, changed: dict) -> str:
    states_obj = _States(values, changed)

    def states(entity_id: str) -> str:
        return states_obj(entity_id)

    def is_state(entity_id: str, want) -> bool:
        cur = states_obj(entity_id)
        return cur in want if isinstance(want, (list, tuple)) else cur == want

    def as_timestamp(dt) -> float:
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        under = (NOW - dt).total_seconds()

        def relative_time(_ignored=None):
            return '%d minutes' % max(1, int(under // 60))
        return under + NOW.timestamp()

    def now() -> datetime:
        return NOW

    def relative_time(dt) -> str:
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = (NOW - dt).total_seconds()
        else:
            delta = float(dt)
        if delta < 90:
            return '%d seconds' % max(1, int(delta))
        if delta < 5400:
            return '%d minutes' % int(delta // 60)
        return '%d hours' % int(delta // 3600)

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    # `states` must be BOTH callable (states('x')) and attribute-accessible
    # (states.input_boolean.y.last_changed), exactly as it is in Home Assistant. The _States
    # object implements __call__ and __getattr__, so it is passed as-is -- wrapping it in a
    # second object loses callability and fails with "'_StatesFunction' object is not callable".
    env.globals.update(states=states_obj, is_state=is_state, as_timestamp=as_timestamp,
                       now=now, relative_time=relative_time)
    return env.from_string(banner).render().strip()


def base() -> dict:
    v = {e: 'off' for e in ENTITIES}
    v['binary_sensor.phoenix_everyone_away'] = 'on'
    return v


CASES = []


def case(name, values, expect_prefix, must_contain=(), must_not_contain=(), changed=None):
    CASES.append((name, values, expect_prefix, must_contain, must_not_contain, changed or {}))


# 1. the state the analysis called the most dangerous: tripped AND silenced
v = base(); v['input_boolean.phoenix_intrusion_active'] = 'on'; v['input_boolean.phoenix_intrusion_test_mode'] = 'on'
case('alarm + muted siren', v, 'INTRUSION ACTIVE', must_contain=('muted',))

# 2. muted alone -- a calm word must never appear here
v = base(); v['input_boolean.phoenix_intrusion_test_mode'] = 'on'
case('muted siren alone', v, 'SIREN MUTED', must_not_contain=('QUIET', 'siren live'))

# 3. guest code latched for 9 hours while the building is marked empty
v = base(); v['input_boolean.phoenix_house_guest_mode_active'] = 'on'
case('guest latched while away', v, 'ARMING BLOCKED', must_contain=('9 hours', 'latched'),
     changed={'input_boolean.phoenix_house_guest_mode_active': NOW - timedelta(hours=9)})

# 4. both doors open with a worker inside
v = base(); v['binary_sensor.phoenix_everyone_away'] = 'off'
v['input_boolean.phoenix_worker_is_here'] = 'on'
v['binary_sensor.phoenix_control_room_interior_door_contact'] = 'on'
v['binary_sensor.phoenix_control_room_exterior_door_contact'] = 'on'
case('both doors open, worker inside', v, 'DOORS OPEN', must_contain=('shop door open', 'apartment door open'), must_not_contain=('QUIET',))

# 5. a safety sensor has gone unavailable
v = base(); v['binary_sensor.phoenix_everyone_away'] = 'unavailable'
case('sensor unavailable', v, 'STATUS UNVERIFIED', must_contain=('unavailable',))

# 6. quiet building
case('quiet', base(), 'BUILDING QUIET', must_contain=('siren live', 'doors closed'))

# 7. door open while marked empty
v = base(); v['binary_sensor.phoenix_control_room_interior_door_contact'] = 'on'
case('door open while away', v, 'DOOR OPEN WHILE AWAY', must_contain=('shop door open',))

# 8. someone at the outer door
v = base(); v['binary_sensor.video_doorbell_person'] = 'on'
case('person at door', v, 'SOMEONE AT THE DOOR', must_contain=('person at door',))

# 9. lockdown
v = base(); v['input_boolean.phoenix_access_control_lockdown'] = 'on'
case('lockdown', v, 'LOCKDOWN ON',)

# 10. guest on but not latched, someone here
v = base(); v['binary_sensor.phoenix_everyone_away'] = 'off'
v['input_boolean.phoenix_user_is_here'] = 'on'
v['input_boolean.phoenix_house_guest_mode_active'] = 'on'
case('guest on, owner present', v, 'GUEST MODE ON', must_not_contain=('latched',))


def main() -> int:
    spec = importlib.util.spec_from_file_location('gen', GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    banner = gen.BANNER

    failures = 0
    for name, values, prefix, must, must_not, changed in CASES:
        out = render(banner, values, changed)
        problems = []
        if not out.startswith('**' + prefix):
            problems.append('expected prefix %r, got %r' % (prefix, out[:60]))
        for token in must:
            if token.lower() not in out.lower():
                problems.append('missing %r' % token)
        for token in must_not:
            if token.lower() in out.lower():
                problems.append('must not contain %r' % token)
        status = 'ok  ' if not problems else 'FAIL'
        if problems:
            failures += 1
        print('%s %-32s %s' % (status, name, out[:120]))
        for p in problems:
            print('       ->', p)

    print('\n%d case(s), %d failure(s)' % (len(CASES), failures))
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
