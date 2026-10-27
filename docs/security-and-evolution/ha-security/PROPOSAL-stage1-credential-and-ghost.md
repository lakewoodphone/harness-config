# PROPOSAL — stage 1: make the alarm disarm on a credential, not on a ghost

**Status:** ready to apply, NOT applied. Every command below is written to be reversible in one line.
**Written:** 2026-10-26 22:1xZ · ZABZ-YOGA · read from the live host, not the repo.

---

## 1. What is actually wrong (measured today)

Three facts, each read from the running system:

| # | Fact | Evidence |
|---|---|---|
| 1 | The building disarms for anyone who walks in | `phoenix_v2_worker_auto_arrival_gps` fired `21:06:07.422Z` → `worker_is_here` on → `everyone_away` off → `phoenix_extreme_intrusion_disarm` fired `21:06:07.627Z` |
| 2 | The ghost that does it is a departed worker's GPS | `device_tracker.monty = home` (unchanged since the last restart); the second ghost `phoenix_passive_arrival_montrose_phone_room_occupied` fired `20:29:15Z` today |
| 3 | The keypad chain is severed at **one** point | `automation.phoenix_keypad_event_handler` = **off**, last triggered `2025-12-16`. Everything downstream is on and has **never** fired: `phoenix_set_context_eliyahu_pin`, `phoenix_active_arrival_eliyahu_pin_occupancy`, `phoenix_set_context_worker_pin` — all `last_triggered = None` |

And the current state as I write this: `input_boolean.phoenix_worker_is_here = on` with every presence signal
off, so `binary_sensor.phoenix_everyone_away = off`. **The building has been unarmed since 21:06Z.**

## 2. Why the two fixes are one change

Turning the keypad back on gives the shop door a **named** credential: `phoenix_access_manager` fires
`phoenix.valid_pin` with `name` and `pin_name`, which is exactly what the record's `entry_event` needs and
exactly what the disarm should be keyed on. Fixing the disarm without it would trade "disarms for intruders"
for "alarms on every legitimate entry", because nothing else in this building reports a credential.

## 3. The four reversible service calls (no file edit, no restart)

```
POST /api/services/automation/turn_off   {"entity_id": "automation.phoenix_v2_worker_auto_arrival_gps"}
POST /api/services/automation/turn_off   {"entity_id": "automation.phoenix_passive_arrival_montrose_phone_room_occupied"}
POST /api/services/automation/turn_on    {"entity_id": "automation.phoenix_keypad_event_handler"}
POST /api/services/input_boolean/turn_off {"entity_id": "input_boolean.phoenix_worker_is_here"}
```

**Revert, one line each:** `turn_on` the two, `turn_off` the keypad handler, and set the boolean back.

**Risk, stated plainly:** turning the keypad handler on means a valid PIN now runs
`script.phoenix_relay_unlock_sequence` — it **opens a door**. That is the designed behaviour of an entry
keypad, and it is why this is a change to be made with a person at the shop, not remotely at midnight. The
handler's own `initial_state: false` means a restart reverts it by itself, which is both a safety property
and the reason a durable fix needs the file edit below.

## 4. The durable edits (file, then reload — not part of the go/no-go above)

| File | Change | Why |
|---|---|---|
| `/config/packages/phoenix_core.yaml` | remove `initial_state: false` from `phoenix_keypad_event_handler` (line 40) | otherwise every HA restart silently re-severs the keypad |
| `/config/packages/presence_architecture.yaml` | add `initial_state: false` to both ghost automations, or delete them | a departed worker's GPS and a dead man's phone must not credit presence after a restart either |
| `/config/custom_components/phoenix_access_manager/__init__.py` | line: `_LOGGER.warning(f"Invalid PIN entered: {pin}")` → log **without the PIN** | a mistyped PIN is one digit from the real one. The logbook line beside it already says only "Invalid PIN entered at keypad." and is fine |

Deploy discipline, unchanged from this estate's rules: `base64` the file through the HA shell, `sha256sum`
both sides, `ha core check`, then `automation.reload` (or `ha core restart` for the component).

## 5. What "done" looks like — the acceptance test

1. With the shop empty: `worker_is_here = off`, `user_is_here = off`, **`everyone_away = on`**.
2. One real keypad entry → `phoenix.valid_pin` fires → a `security_event` row appears → the sentinel writes an
   `entry_event` row **with a subject name and confidence 0.9** → `everyone_away` goes off → the alarm is
   disarmed **by a credential**.
3. `grep -r "Invalid PIN entered: [0-9]" /var/log` returns nothing after a deliberately wrong code.
4. The record's scorecard shows the episode labelled by evidence, not by a disarm.

## 6. What this does NOT fix, so nobody assumes it does

- The apartment door still reports nothing usable — the lock's only transitions are `locked`/`unlocked` plus
  Zigbee flapping (**13 transitions in 24 h, 3 of them `unavailable`**), so `unlocked` cannot be treated as a
  credential.
- The reflex still has no entry delay, no AVS level and no bounded siren — that is stage 2.
- Nothing pages anyone yet: the sentinel and agent are shadow-only and write no `security_action`.
