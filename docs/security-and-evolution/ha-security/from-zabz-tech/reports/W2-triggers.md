# W2 — When the intrusion alarm arms

**LOCAL (zabz-tech)** · read-only audit · no edits, no state-changing calls, no restarts.

## STEP 0 — revision check: PASS

```
pwd = C:\Users\ezabz\Code

e6b45f6b1c04  14472 bytes  mtime=2026-10-26T14:08:52  config\packages\phoenix_security.yaml
a2ebbfb67212  13541 bytes  mtime=2026-10-18T01:10:53  config\packages\presence_architecture.yaml
```

Both match the expected hashes. Note the first file's mtime is `2026-10-26T14:08:52` — 5 min 37 s after the incident, i.e. this revision already contains the 14:03 fix and is not the code that ran at 14:03.

Live HA reached at `http://homeassistant.local:8123`; `/api/states` returns **1036 entities**.

## Evidence base

Logbook pulled in four bounded windows (the single full-range request silently returns a truncated subset — see F13):

```
10-24 19:44:33 -> 10-26 14:25:13 local   = 42.68 h   40,325 entries with entity_id
```

The whole analysis is validated by **replaying the YAML's own logic against that logbook**. The replay reproduces all six arms to the exact second (F1), so the model of the automation below is measured, not inferred.

---

# 1. Every trigger input

Five `entity_id`s feed the state trigger (`phoenix_security.yaml:23-36`):

```yaml
    trigger:
      # Any unauthorized entry point opening
      - platform: state
        entity_id:
          - binary_sensor.phoenix_outside_door_contact
          - binary_sensor.phoenix_control_room_exterior_door_contact
          - binary_sensor.phoenix_control_room_interior_door_contact
        to: "on"
      # Motion in secure zones
      - platform: state
        entity_id:
          - binary_sensor.zone_hallway_active
          - binary_sensor.zone_control_room_active
        to: "on"
```

No `for:`, no `from:`, so **any single off→on edge arms**, subject only to the two conditions and the 6 s re-check. Measured `on`-edges in 42.68 h: **148 total** (`outside_door` 56, `zone_control_room_active` 13, `interior_door` 10, `exterior_door` 8, `zone_hallway_active` 61).

### F1 — SEVERITY: CRITICAL — the trigger that actually fires is the zone sensor, never the doors

**Claim.** All six false arms came from `binary_sensor.zone_hallway_active`. Not one came from a door contact or from `zone_control_room_active`.

**Proof.** Replay of the trigger list + both conditions + the 6 s re-check against the logbook:

```
trigger on-edges total = 148
  blocked: everyone_away not on = 111
  blocked: intrusion_active already on = 28
  reached delay (after same-second dedupe) = 8
  aborted by 6s re-check = 2
  PREDICTED ARMS = 6
     10-24 22:21:31  <- binary_sensor.zone_hallway_active
     10-25 16:59:15  <- binary_sensor.zone_hallway_active
     10-25 19:57:45  <- binary_sensor.zone_hallway_active
     10-25 21:38:24  <- binary_sensor.zone_hallway_active
     10-25 23:23:21  <- binary_sensor.zone_hallway_active
     10-26 14:03:21  <- binary_sensor.zone_hallway_active
```

The logbook's own `input_boolean.phoenix_intrusion_active` transitions are `22:21:31, 16:59:15, 19:57:45, 21:38:24, 23:23:21, 14:03:21` — identical, to the second. A seventh arm at `10-26 14:16:10` was the owner's drill (`phoenix_intrusion_test_mode -> on` at the same second), not a sensor.

**Fix.** The defect is not in the trigger list; it is in what `zone_hallway_active` is composed of. See F2.

### F2 — SEVERITY: CRITICAL — `zone_hallway_active` is fed by an explicitly *outside* sensor

**Claim.** `binary_sensor.video_doorbell_person` is classified as an OUTSIDE/perimeter sensor at line 16 of the same file and then reused as an INTERIOR hallway sensor at line 42. Every person who walks past the front door — delivery, neighbour, a passer-by on the street — turns on the interior hallway zone and arms the alarm.

**Proof.** `presence_architecture.yaml:12-18`, "ZONE 1: OUTSIDE (Perimeter)":

```yaml
      - name: "Zone Outside Active"
        unique_id: zone_outside_active
        device_class: motion
        state: >
          {{ is_state('binary_sensor.video_doorbell_person', 'on') or
             is_state('binary_sensor.video_doorbell_visitor', 'on') or
             is_state('binary_sensor.video_doorbell_motion', 'on') }}
```

and `presence_architecture.yaml:35-45`, "ZONE 2: FRONT HALLWAY (Transitional)":

```yaml
      - name: "Zone Hallway Active"
        unique_id: zone_hallway_active
        device_class: motion
        state: >
          {{ 
            is_state('binary_sensor.cam_front_hallway_smart_motion_human_2', 'on') or
            is_state('binary_sensor.cam_waiting_room_smart_motion_human_2', 'on') or
            is_state('binary_sensor.video_doorbell_person', 'on') or
            is_state('binary_sensor.phoenix_outside_door_contact', 'on') or
            is_state('binary_sensor.phoenix_control_room_exterior_door_contact', 'on')
          }}
```

The same entity appears in both. Attribution of all 61 `zone_hallway_active` on-edges to the input that changed within 8 s before:

```
video_doorbell_person                          40
phoenix_outside_door_contact                   12
phoenix_control_room_exterior_door_contact      5
phoenix_control_room_interior_door_contact      4
```

`video_doorbell_person` fired **92 times in 42.68 h** (2.16/h). Of those 92, **47 had no control-room occupancy within 300 s** — nobody entered. Those 47 are pure outside-the-door events capable of arming the alarm.

**Fix.** Delete the `video_doorbell_person` term from `zone_hallway_active` (F16 diff shape). It already lives where it belongs, in `zone_outside_active`.

### F3 — The incident, second by second

**Claim.** The person was still outside when the alarm decided to arm. The door opened 11 s after the trigger, and presence was credited 3 s after that.

**Proof.** Logbook, all entities, 14:03:00–14:03:47 (local):

```
14:03:00  input_boolean.phoenix_worker_is_here            -> off
14:03:00  binary_sensor.phoenix_everyone_away             -> on
14:03:15  binary_sensor.video_doorbell_person             -> on
14:03:15  binary_sensor.zone_outside_active               -> on
14:03:15  binary_sensor.zone_hallway_active               -> on
14:03:15  automation.phoenix_extreme_intrusion_trigger    ->
14:03:21  input_boolean.phoenix_intrusion_active          -> on          <- 6 s grace expired
14:03:21  script.phoenix_intrusion_initial_response       -> on
14:03:26  binary_sensor.0x286d97000115ca7a_contact        -> on          <- the door actually opens, 11 s late
14:03:26  binary_sensor.phoenix_outside_door_contact      -> on
14:03:29  binary_sensor.control_room_hub_control_room_presence -> on
14:03:29  binary_sensor.zone_control_room_occupied        -> on
14:03:29  automation.phoenix_passive_arrival_montrose_phone_room_occupied ->
14:03:29  input_boolean.phoenix_worker_is_here            -> on
14:03:29  binary_sensor.phoenix_everyone_away             -> off
14:03:29  input_boolean.phoenix_intrusion_active          -> off         <- disarm
14:03:43  script.phoenix_intrusion_loop                   -> on          <- siren, 14 s AFTER the disarm
```

**Fix.** Two independent repairs, and the arithmetic for them is in §5. (a) Do not arm on the outside doorbell. (b) The 14:03:43 orphaned siren is already fixed in this revision by the `condition` at `phoenix_security.yaml:180-182`, which aborts the sequence if the flag went off — I confirmed the file contains it, but I could not watch it execute (F22).

### F4 — SEVERITY: HIGH — the remaining three trigger inputs, and whether a legitimate arrival sets them off

**Claim.** All three door contacts and `zone_control_room_active` fire on a legitimate arrival, by construction: they are the same contacts the owner and workers use. They are safe only because the presence gate usually blocks them.

| Input | What makes it true | How fast | Legit arrival sets it off? | on-edges / 42.68 h |
|---|---|---|---|---|
| `phoenix_outside_door_contact` | template over `binary_sensor.0x286d97000115ca7a_contact` (`configuration.yaml:366-372`) | instant on magnet separation | **yes, every single entry** | 56 |
| `phoenix_control_room_exterior_door_contact` | template over `binary_sensor.external_control_room_door_sensor_contact` (`configuration.yaml:378-380`) | instant | **yes** | 8 |
| `phoenix_control_room_interior_door_contact` | template over `binary_sensor.interior_control_room_door_sensor_contact` (`configuration.yaml:386-388`) | instant | **yes** | 10 |
| `zone_control_room_active` | 2 Dahua human sensors (**both dead, F5**) + the two control-room contacts | instant | **yes** | 13 |
| `zone_hallway_active` | 2 Dahua human sensors (**dead**) + doorbell person + outside & exterior doors | instant | **yes** | 61 |

The door templates are thin wrappers and add nothing but an availability guard, e.g. `configuration.yaml:366-372`:

```yaml
      - name: "phoenix_outside_door_contact"
        unique_id: phoenix_outside_door_contact
        ...
          {{ is_state('binary_sensor.0x286d97000115ca7a_contact', 'on') }}
        ...
          {{ states('binary_sensor.0x286d97000115ca7a_contact') not in ['unknown', 'unavailable'] }}
```

So the entire trigger set is "the three doors the authorised people use, plus one sensor that watches people who never come in".

**Fix.** §5.

### F5 — SEVERITY: CRITICAL — the "camera half" of both zones is dead, again

**Claim.** All 35 `binary_sensor.cam_*_2` entities produced **zero** logbook entries in 42.68 h. The Dahua human-detection layer that the 2026-09-16 comment says was "verified live" contributes nothing. The interior motion detection the fusion was built for does not exist.

**Proof.** Recorder excludes exactly two entities (`configuration.yaml:188-191`): `binary_sensor.control_room_hub_control_room_moving_target` and `binary_sensor.presence_sensor_motion`. `cam_*_2` is **not** excluded, so absence from the logbook means absence of state changes:

```
=== ANY Dahua cam_*_2 entity in the 43h logbook? ===
entries: 0
```

They exist and are available (state `off`, `last_changed` = the 14:15 restart), across `cam_deserted_exit`, `cam_deserted_interior`, `cam_front_hallway`, `cam_waiting_room`, `cam_larry_s_exit`, `cam_larry_s_interior` — five event types each. The comment at `presence_architecture.yaml:23-34` says the `_2` suffix was chosen because the bare names "answer `unavailable` forever"; the bare `cam_waiting_room_*` names are indeed `unavailable` right now, so the diagnosis was right and the replacement did not take effect.

**Fix.** This is the highest-value repair in the audit and it is upstream of everything else: until the Dahua events arrive, both zones are door-contact detectors wearing a motion sensor's name. Diagnose the NVR→HA event push separately; do not paper over it (§5, item 5).

---

# 2. False-positive classes, ranked by observed frequency

Counted over 42.68 h / 40,325 logbook entries. **The logbook does not go back far enough to do better than this** (F13): retention is configured at 30 days but the oldest surviving row is 42.68 h old, so ~28 days of promised history is missing and the six arms are all the arms that exist in the record.

### F6 — Class A: outside-the-door person detection — 5 of 6 arms

`video_doorbell_person` → `zone_hallway_active` → arm. 92 detections, 40 of them moved the zone, 47 of them had nobody enter at all. Arms at `16:59:15`, `19:57:45`, `21:38:24`, `23:23:21`, `14:03:21`. Measured latency from doorbell detection to control-room occupancy for the 45 events that were followed by an entry:

```
min=1  p50=66  p90=275  max=298   seconds
```

**This is the class to kill, and it is not killable with a grace window** — see the arithmetic in §5.

### F7 — Class B: a door contact firing while presence is stale — 21 zone edges, 1 arm

The three door contacts drove 21 of the 61 `zone_hallway` on-edges. They arm only when `phoenix_everyone_away` is on at that instant, i.e. when the system has already de-credited the person who is walking through the door. The `14:03:00` transition is the exemplar: `worker_is_here -> off` at `14:03:00`, doorbell at `14:03:15`, credit back at `14:03:29`.

### F8 — Class C: restart / reload burst — 1 arm

At `10-24 22:21:25` **70 entities changed state inside one second** (row 2 of the burst table, versus a median second of ~1 entry). All four door/zone inputs announced `on` in that second, the arm followed at `22:21:31` exactly 6 s later, and the first presence credit came at `22:25:14` — **223 s after the arm**. The same burst pattern repeats at `22:22:39` (59), `22:23:58` (59), `22:25:03` (67), `00:05:54` (78), `00:08:17` (77), `14:13:16` (73), `14:16:26` (61).

Either reading is a defect: if it was boot-time initialisation, the alarm armed on a synthetic edge; if it was a real door sequence, presence took 223 s to be credited. I cannot separate the two from the logbook (F21).

### F9 — Class D: presence de-credited while the person is still on site — the upstream cause of A/B/C

`binary_sensor.phoenix_everyone_away` made **64 transitions in 42.68 h** — it never settles. The writers are the auto-departure timers (`presence_architecture.yaml:90-146`), which fire on `zone_control_room_occupied -> off` for 5 or 10 minutes, plus the BLE leave path (`phoenix_beacon_presence.yaml:276-299`, 2 minutes). Any of these can de-credit a person who is between rooms, at the door, or whose mmWave reading dropped.

**Observed frequency ranking:** A (5 arms) > C (1 arm) > B (0 arms in this window, 21 zone edges) — with D as the precondition for every one of them.

---

# 3. Every way a real intrusion fails to arm

### F10 — SEVERITY: CRITICAL — the "not already active" condition is a 12-hour deafness

**Claim.** While `input_boolean.phoenix_intrusion_active` is on, every trigger is silently discarded. Nothing bounds how long it stays on. Measured: it was on for **12 h 02 m** and the alarm was deaf for all of it.

**Proof.** Condition at `phoenix_security.yaml:43-45`, re-checked at `73-75`:

```yaml
      # Not already active (prevent re-triggering the initial sequence)
      - condition: state
        entity_id: input_boolean.phoenix_intrusion_active
        state: "off"
```

Armed durations from the logbook:

```
10-24 22:21:31 -> 22:25:14    223 s
10-25 16:59:15 -> 16:59:21      5 s
10-25 19:57:45 -> 21:00:58   3794 s   (1 h 03 m)
10-25 21:38:24 -> 21:38:53     29 s
10-25 23:23:21 -> 10-26 11:25:25  43324 s   (12 h 02 m)
10-26 14:03:21 -> 14:03:29      8 s
```

and **28 of the 148 trigger on-edges were discarded by this condition alone** — a fifth of all trigger traffic landed inside a window where the system could not respond.

**Fix.** Do not remove the condition (it prevents a re-entrant siren), but bound it: a `time` trigger on `input_boolean.phoenix_intrusion_active` for 30 minutes that pages the owner and logs an escalation without clearing the alarm. Arithmetic in §5.

### F11 — SEVERITY: CRITICAL — `phoenix_everyone_away` can read `unavailable`, and `unavailable` is not `on`

**Claim.** Both the condition and the 6 s re-check test `state: "on"`. While the template sensor is `unavailable`, the alarm cannot arm and the alarm cannot be re-checked into arming. Measured 12 such episodes.

**Proof.**

```
binary_sensor.phoenix_everyone_away   unavailable= 12  last=10-25 00:08:17
binary_sensor.zone_hallway_active     unavailable= 12
binary_sensor.phoenix_outside_door_contact unavailable= 15  last=10-26 14:15:47
```

The template has no guard for a missing or unavailable input (`phoenix_security.yaml:12-15`):

```yaml
        state: >
          {{ is_state('input_boolean.phoenix_user_is_here', 'off') and
             is_state('input_boolean.phoenix_worker_is_here', 'off') and
             is_state('input_boolean.phoenix_house_guest_mode_active', 'off') }}
```

`is_state()` returns `False` for an entity that does not exist yet, so during a partial boot the expression evaluates `False` and the sensor reads `off` — then flips to `on` once the helpers restore, which is a spurious "everyone left" edge produced by the restart itself.

**Fix.** Guard the template on input availability so that a boot yields `unknown`, not a guess (F16 diff shape).

### F12 — SEVERITY: HIGH — no window or glass-break coverage exists at all

**Claim.** Of 1036 entities there are exactly six `device_class: door` binary sensors — three real contacts and three template copies of them. There is no `window`, no `vibration`, no `glass_break` device class anywhere. An entry through a window arms nothing.

**Proof.** Enumeration of `/api/states`:

```
binary_sensor.phoenix_outside_door_contact                  dc=door  (template)
binary_sensor.0x286d97000115ca7a_contact                    dc=door  (real)
binary_sensor.phoenix_control_room_exterior_door_contact    dc=door  (template)
binary_sensor.external_control_room_door_sensor_contact     dc=door  (real)
binary_sensor.phoenix_control_room_interior_door_contact    dc=door  (template)
binary_sensor.interior_control_room_door_sensor_contact     dc=door  (real)
```

No `window` / `opening` / `garage_door` class, and the only `vibration`/`sound`-class entities are Dahua camera diagnostic flags (`cam_*_audio_mutation_2`), not glass-break sensors.

**Fix.** Out of scope for a trigger rewrite — this is a hardware gap and the owner's decision. Recorded, not recommended for me to solve.

### F13 — SEVERITY: HIGH — the logbook cannot answer "has this ever happened before"

**Claim.** `purge_keep_days: 30` is configured, but the oldest surviving row is only 42.68 h old. Roughly 28 days of promised security history is absent, and no arm before 2026-10-24 19:44:33 can be examined.

**Proof.** `configuration.yaml:176-177` sets `purge_keep_days: 30`. The four bounded queries return earliest `10/24/2026 19:44:33` local regardless of how far back the window starts, and that instant is immediately followed by a 48-entity and a 33-entity burst (`19:44:49`, `19:44:55`) — a fresh database being written, not a purge horizon.

Separately, the **full-range** request `GET /api/logbook/2026-10-24T00:00:00Z` returns **357 entries spanning 14 minutes** and exits 0, while the same range in four bounded windows returns **40,325**. The truncation is silent; only cross-checking the counts caught it.

**Fix.** Nothing here is mine to change under a read-only rule. Flagged for the owner: the security record is 1.8 days deep while the config promises 30.

### F14 — SEVERITY: HIGH — `mode: single` plus the grace window can swallow a whole burst

**Claim.** The automation is `single` by default (asserted deliberately at `phoenix_security.yaml:67-68`: *"Keep `mode` at its default (single)"*). Combined with the 6 s `delay`, a simultaneous burst of triggers produces one run and drops the rest — measured at `22:21:25`, where **four** inputs fired in the same second and one run proceeded.

That is benign when the run completes. It is not benign when the run is the one the presence re-check aborts: the other three triggers in the burst are gone, and nothing re-fires because they are edge-triggered. A transient presence blip during the delay therefore discards a real intrusion that the same second also detected.

**Proof.** 70 entities changed at `22:21:25`; the replay, which dedupes same-second edges, still yields exactly one arm there and reproduces the log.

**Fix.** Keep `single`, but the re-check should re-arm on the *latest* trigger rather than abort: change the post-delay condition to a `choose` that arms if `everyone_away` is on, and separately re-evaluates. Simpler and safer: arm on interior evidence only (F16), where a burst is one event anyway.

### F15 — SEVERITY: HIGH — a drill leaves the alarm silent, permanently

**Claim.** `script.phoenix_test_intrusion_sequence` turns `phoenix_intrusion_test_mode` on and **nothing in the configuration ever turns it off**. While it is on, the siren, strobe and overhead audio are suppressed and the page is sent as `intrusion_test`, which the backend deliberately skips. `phoenix_intrusion_reset` does not clear it; the disarm automation does not clear it; `initial: false` does not help because `initial` only applies at entity creation and input booleans restore their prior state on restart (`phoenix_helpers.yaml:113-114` states exactly this).

**Proof.** `phoenix_security.yaml:259-268`:

```yaml
  phoenix_test_intrusion_sequence:
    alias: 'Phoenix: TEST Intrusion Sequence'
    mode: single
    sequence:
      - service: input_boolean.turn_on
        target:
          entity_id:
            - input_boolean.phoenix_intrusion_active
            - input_boolean.phoenix_intrusion_test_mode
      - service: script.phoenix_intrusion_initial_response
```

A `grep` for `phoenix_intrusion_test_mode` across `config\` returns 20 matches and **not one of them is a `turn_off`** — only the UI card, the helpers block, and the read at `phoenix_security.yaml:120`. Observed on from `14:16:10` to `14:17:21` (71 s), cleared by hand.

**Fix.** Add `input_boolean.turn_off` for both flags at the end of `phoenix_test_intrusion_sequence`, and a `time` trigger that clears test mode after 15 minutes regardless. Severity would be CRITICAL if a drill were routine; it is HIGH because the toggle is currently manual.

---

# 4. What makes `phoenix_everyone_away` false

The sensor is the AND of three booleans (`phoenix_security.yaml:10-15`). To keep the alarm silent while someone is inside, a burglar — or a misfire — needs exactly one of these three to read `on`. The full writer set, from `grep` across `config\`:

### F16 — `input_boolean.phoenix_user_is_here`

Writers that turn it **on** (five independent paths):

1. Owner PIN or owner/wife RFID at any door — `automations/access_control.yaml:170-172`
2. BLE triangulation into the control room — `packages/phoenix_beacon_presence.yaml:239-244`
3. BLE latch sync — `packages/phoenix_beacon_presence.yaml:266-269`
4. Passive arrival: `device_tracker.zabz_ble_tracker == home` **and** control room becomes occupied — `presence_architecture.yaml:262-280`
5. PIN-context arrival: `phoenix.valid_pin` for Eliyahu + control room occupied — `presence_architecture.yaml:172-197`

Writer that turns it **off**: auto-departure only — `presence_architecture.yaml:125-128` and `137-141` (5 or 10 minutes of an empty control room), plus BLE leave at `phoenix_beacon_presence.yaml:290-294`.

**Attack surface.** `device_tracker.zabz_ble_tracker` is a phone. A phone left in the shop, or a BLE beacon in range, keeps path 4 armed to re-credit on the next occupancy edge.

### F17 — `input_boolean.phoenix_worker_is_here`

Writers that turn it **on**:

1. Worker keypad PIN or `worker_montrose`/`worker_bachrach` RFID at any door — `access_control.yaml:435-436` (unconditional, at any door, including from outside)
2. Worker PIN + control room occupied — `presence_architecture.yaml:229-252`
3. Passive arrival: `device_tracker.monty == home` **and** control room becomes occupied — `presence_architecture.yaml:287-308`
4. `automations/presence_beacon.yaml:38`, `106`, `115`, `127`

**Measured now:** `device_tracker.monty = home` (live state). This is the path that disarmed the alarm at `14:03:29` — the logbook names the automation: `automation.phoenix_passive_arrival_montrose_phone_room_occupied`.

### F18 — `input_boolean.phoenix_house_guest_mode_active`

Three credential paths turn it **on**, and the file says so itself at `access_control.yaml:2325-2330`:

> *"MEASURED: input_boolean.phoenix_house_guest_mode_active is switched ON by three credential scenarios in this very file (parent PIN :241, house-access PIN :433, Yitz PIN :477) and switched OFF by nothing anywhere. It is the third term of binary_sensor.phoenix_everyone_away, so while it is on the alarm CANNOT arm. A parent entry at 2026-10-18 02:01 left the shop disarmed for twenty hours, through a full business day and after closing, and nobody noticed."*

Verified in this revision at:

- `access_control.yaml:224-225` — Yocheved PIN → `turn_on`
- `access_control.yaml:486-487` — house-access PIN → `turn_on`
- `access_control.yaml:530-531` — Yitz PIN → `turn_on`

Two clears now exist: the 23:00 night reset (`access_control.yaml:2339-2362`) and a one-minute watchdog requiring `control_room_hub_control_room_presence` off for 240 s (`access_control.yaml:2376-2405`).

**Measured:** guest mode was on from `10-25 12:04:28` to `16:48:00` — **4 h 43 m 32 s** during which the alarm could not arm, and indeed no arm occurred in that window.

### F19 — SEVERITY: CRITICAL — the chain, stated plainly

To keep the alarm silent while someone is inside, it is enough to influence **one** of:

1. **`input_boolean.phoenix_house_guest_mode_active`** — the cheapest. One use of a shared "house access" PIN, or Yitz's, or Yocheved's, disables the alarm until 23:00 and only if the shop is empty *at that instant* and the mmWave has been quiet for 4 minutes.
2. **`binary_sensor.control_room_hub_control_room_presence`** — an mmWave sensor that fired **80 times in 42.68 h** (1.9/h) in an empty shop. Every false `on` blocks the guest-mode watchdog, and every false `on` while `device_tracker.monty` is home re-credits worker presence through `presence_architecture.yaml:287-308`.
3. **`media_player.control_room`** — it is a term of `zone_control_room_occupied` (`presence_architecture.yaml:74-77`), the trigger for every passive-arrival automation. Music left playing keeps occupancy on, which keeps auto-departure from ever firing, which keeps presence on, which keeps `everyone_away` off.
4. **`input_boolean.phoenix_boss_in_control_room_ble`** — same role, one more latch.
5. **The 6 s grace itself** — anyone who can open the outside door and reach the control room inside 6 s is never armed on; measured latency to credit was as low as **1 s** in 45 arrival events.

Items 2 and 3 are the ones that misfire on their own, with nobody attempting anything.

---

# 5. Recommended change set

**Ranked. Nothing applied — diff shapes only.**

### Change 1 — stop arming on people who never come in (fixes 5 of 6 arms)

Delete one term from `zone_hallway_active`, `presence_architecture.yaml:38-45`:

```
-            is_state('binary_sensor.video_doorbell_person', 'on') or
```

Keep it in `zone_outside_active` where it already is (line 16). This removes 40 of 61 zone edges and 5 of the 6 measured arms. Verified against the incident: with this change the `14:03:15` trigger never happens; the first trigger becomes the door contact at `14:03:26`, and the 6 s re-check at `14:03:32` lands after the `14:03:29` disarm — **the false arm is aborted by the existing grace window, with no other change.**

### Change 2 — arm on interior evidence, not on outside edges

Replace the trigger block `phoenix_security.yaml:23-36` so the outside door is a *precondition* rather than a trigger. Diff shape:

```
     trigger:
-      - platform: state
-        entity_id:
-          - binary_sensor.phoenix_outside_door_contact
-          - binary_sensor.phoenix_control_room_exterior_door_contact
-          - binary_sensor.phoenix_control_room_interior_door_contact
-        to: "on"
-      # Motion in secure zones
-      - platform: state
-        entity_id:
-          - binary_sensor.zone_hallway_active
-          - binary_sensor.zone_control_room_active
-        to: "on"
+      # Interior crossing only. The outside door is corroboration, below.
+      - platform: state
+        id: interior
+        entity_id:
+          - binary_sensor.phoenix_control_room_exterior_door_contact
+          - binary_sensor.phoenix_control_room_interior_door_contact
+          - binary_sensor.zone_control_room_active
+        to: "on"
+      # Outside door opened, then an interior zone within 120 s.
+      - platform: state
+        id: outside
+        entity_id: binary_sensor.phoenix_outside_door_contact
+        to: "on"
+      - platform: state
+        id: interior_corroborates
+        entity_id: binary_sensor.zone_control_room_active
+        to: "on"
+        for: { seconds: 0 }
```

with a `condition: trigger id == interior` branch, or an `input_datetime`/`input_boolean` "outside door seen recently" that the `outside` trigger sets and the `interior` trigger consumes within 120 s. I recommend the simpler form: **one trigger list containing only the three interior entities**, and let the outside door contribute nothing. That loses one real signal (a burglar who opens the outside door and stays in the hallway) — which is precisely the signal that is currently 95% noise, and which `zone_hallway_active` should be rebuilt to detect from the interior camera instead (F5).

### Change 3 — the grace window: keep it small; the arithmetic says do not enlarge it

The proposal to widen 6 s is measured and rejected:

```
doorbell-detection -> control-room occupancy, 45 matched arrivals
min=1  p50=66  p90=275  max=298   seconds
```

- To catch the median false arm you would need a **66 s** grace. To catch 90% you would need **275 s** — four and a half minutes during which a real intruder walks the premises with the siren off.
- Cost of 66 s against a real intrusion: the siren, strobe, overhead audio and the family page all arrive 66 s after the door opens instead of 6 s. The Mac-mini alarm and the evidence snapshots are what make the alarm useful; delaying them by a minute is a real loss of deterrence and of evidence.
- With Change 1 applied the driver disappears: the remaining trigger is a door contact, and the incident's own numbers show 6 s suffices — the door opened `14:03:26`, credit landed `14:03:29`, so the re-check at `14:03:32` was 3 s clear.

**Recommendation: keep the mechanism, raise 6 s to 12 s** (`phoenix_security.yaml:69`, `- delay: "00:00:06"` → `"00:00:12"`). Cost is 6 s of additional siren latency with 9 s of margin over the measured 3 s. Not more: every further second is paid on every real intrusion to buy a class of false arm that Change 1 already removed.

### Change 4 — bound the deafness

Add a `time` trigger on `input_boolean.phoenix_intrusion_active` with `for: { minutes: 30 }` that pages the owner and writes a logbook entry, **without** clearing the flag. 30 minutes is chosen against the measured distribution of armed durations — `223, 5, 3794, 29, 43324, 8` seconds — where the median is under a minute and the single pathological case is 12 h. A 30-minute page fires on the pathological case and on none of the five legitimate ones.

Do not auto-disarm on that timer: an intruder who can wait 30 minutes would then be rewarded. Page, keep the siren, let a human decide.

### Change 5 — make the dead inputs live, or stop pretending

Both zone sensors name four Dahua entities that produced zero events in 42.68 h (F5). Until that stream is fixed, `zone_hallway_active` and `zone_control_room_active` are door contacts with extra steps, and the config comments claiming otherwise are actively misleading — the 2026-09-16 comment says the `_2` entities were "verified live", and they have never fired once. This is a separate workstream (NVR event push → HA), and it is the only change that adds real interior detection.

### Change 6 — availability guard on `phoenix_everyone_away`

```
         state: >
-          {{ is_state('input_boolean.phoenix_user_is_here', 'off') and
-             is_state('input_boolean.phoenix_worker_is_here', 'off') and
-             is_state('input_boolean.phoenix_house_guest_mode_active', 'off') }}
+          {% set ins = ['input_boolean.phoenix_user_is_here',
+                        'input_boolean.phoenix_worker_is_here',
+                        'input_boolean.phoenix_house_guest_mode_active'] %}
+          {% if ins | select('is_state', ['unknown','unavailable']) | list | count > 0 %}
+            unknown
+          {% else %}
+            {{ ins | select('is_state', 'off') | list | count == 3 }}
+          {% endif %}
```

so a boot yields `unknown` rather than a synthetic `on`/`off` edge (F11, F8).

### Change 7 — let the drill end itself

Append to `phoenix_test_intrusion_sequence` (`phoenix_security.yaml:259-268`):

```
       - service: script.phoenix_intrusion_initial_response
+      - service: input_boolean.turn_off
+        target:
+          entity_id:
+            - input_boolean.phoenix_intrusion_test_mode
+            - input_boolean.phoenix_intrusion_active
```

F15.

### What I would do first, in one line

Change 1 alone. One deleted term, and the measured record says it removes five of the six false arms and would have aborted the 2026-10-26 incident on the existing grace window.

---

# What I could not verify

1. **Whether the `10-24 22:21:25` arm was boot initialisation or a real door sequence.** 70 entities changed in one second and four trigger inputs announced `on` simultaneously, which is the signature of a restart; but the logbook records state, not cause, and there is no HA restart marker in the retained data. Both readings are defects; I cannot say which occurred.
2. **Whether the Dahua `cam_*_2` entities are broken or merely quiet.** Zero logbook entries across 42.68 h with recorder exclusion ruled out (only two entities are excluded). I did not open the NVR, the MQTT broker or the integration logs — so I can prove they never fired, not why.
3. **That the 14:08 `condition` fix at `phoenix_security.yaml:180-182` actually prevents the orphaned siren.** I confirmed the YAML contains it and that the file's mtime is after the incident, and the `14:16:10` drill ran 30 s without starting the loop — but the drill was in test mode, which suppresses the siren anyway, so it exercised a different branch. It has not been proven against a non-test disarm.
4. **Physical sensor health.** I read states and logbook only. I did not verify that the three door magnets are mounted, that the mmWave is aimed correctly, or that the 47 doorbell detections with no entry were passers-by rather than people who entered through an unwatched path.
5. **Anything before 2026-10-24 19:44:33.** Retention is configured at 30 days; the oldest row is 42.68 h old. Every count in this report is bounded by that window, and the earlier incidents cited in the file's own comments (`2026-09-15/16`) are unverifiable from here.
6. **Guest-mode and arm history outside the window.** The 20-hour disarmed period cited at `access_control.yaml:2329` is quoted from the file's comment, not re-measured.
7. **Nothing was changed.** No edits, no service calls, no restarts — read-only throughout, and the only writes are this report and its four logbook cache files under `_scratch\audit-2026-10-26\`.
