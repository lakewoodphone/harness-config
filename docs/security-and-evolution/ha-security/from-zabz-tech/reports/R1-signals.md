# R1 — measured inventory of every "a person is here" / "a door moved" signal

**LOCAL (zabz-tech)** · read-only (no edits, no state changes, no restarts, no POST, no outbound)
HA `2025.10.3`, tz `America/New_York`, 1,036 entities reachable now.
Tagged on every number below with the store it came from.

---

## 0. How this was measured (so the numbers can be re-run)

| step | command / call | result |
|---|---|---|
| reachability | `. ha.ps1 -Path /api/states` | **1,036 entities** (121 `binary_sensor`, 245 `sensor`, 58 `device_tracker`, 25 `camera`, 124 `automation`, 3 `person`, 8 `media_player`, 2 `lock`) |
| registries | WebSocket `config/entity_registry/list`, `device_registry/list`, `area_registry/list` | **1,929 entity rows, 131 devices, 10 areas** — this is where "what it physically is" comes from, not inference |
| history | `/api/history/period/<start>?end_time=<+24h>&filter_entity_id=<144 ids>&minimal_response&no_attributes` × **30 chunks** | **641,790 rows**, 144 arrays/chunk, 47.9 s total |
| window | first chunk with data `2026-09-28T00:26:00Z` → `2026-10-26T18:43:00Z` | **28.76 days** |
| credential events | same chunked call on `input_text.phoenix_access_control_log` | **101 events** |
| live sampling | `/api/states` every 5 s for 14.2 min (2,805 samples) | used only for the two recorder-excluded sensors |

**Two corrections to the brief, both measured, both load-bearing:**

1. **The recorder does not hold 1.8 days. It holds 28.76 days.** Walking back in 24 h windows on
   `sensor.thermostat_current_temperature`: the window `2026-09-26T18:43Z → 09-27T18:43Z` and every
   earlier window returned **0 rows**; the window starting `2026-09-28T00:00Z` returned data whose
   oldest row is `2026-09-27T20:26:38` local = `2026-09-28T00:26:38Z`. Chunk 1 of the 30-window
   fetch (`09-27T00:00Z → 09-28T00:00Z`) returned **0 rows** ; chunk 2 returned 14,706. So retention
   is ~28.8 days, consistent with `purge_keep_days: 30` in `config/configuration.yaml`. Anything
   that reported ~1.8 days was reading a different store or a single entity's coverage.
2. **The 24 h cap is real and I obeyed it** — every fetch above is a ≤24 h window. I did not make a
   full-range `/api/logbook` call at all; one 24 h `/api/logbook` probe returned **31,689 entries**
   (27,386 of them `switch.*`), which is why the logbook is not used as the measurement backbone.

**A refusal is not a negative.** Two signals are *excluded from the recorder by configuration*
(`config/configuration.yaml` `recorder.exclude.entity_globs`): `binary_sensor.control_room_hub_control_room_moving_target`
and `binary_sensor.presence_sensor_motion`. Probing them returned **ZERO arrays** while the control
entity in the same call returned 98 rows. Their history is *unknown*, not zero. I measured them live
instead (§1, and §2 "not measurable").

---

## 1. The inventory — 30 rows

`edges` = rising (off→on) edges in the 28.76-day window. `med gap` = median seconds between those
edges. `on lasts` = median duration of an "on". `duty` = share of the window spent "on".

**Read `on lasts` next to `duty`, not instead of it.** For the outside door contact the distribution
is bimodal: 113 open-episodes of which 107 last a median of 5.9 s and **3 last 168.6 h, 142.9 h and
167.9 h**. The median describes the normal case; the 83 % duty is set entirely by the three latches.
Any rule that reads the median and assumes a door closes in six seconds is reading the wrong half.

| entity | what it physically measures | now | edges | med gap | on lasts | duty | false fire | misses | edge/level | battery / last_changed |
|---|---|---|---|---|---|---|---|---|---|---|
| `binary_sensor.0x286d97000115ca7a_contact` | Outside door **reed** — SmartThings Multipurpose 2018, z2m/MQTT | off | 113 | 407 s | 5.9 s | **83 %** | latched "open" for days — 3 episodes of **168.6 h, 142.9 h, 167.9 h** | welded reed → silence; 83 % duty *is* the miss | edge | 51 %, 18:31Z |
| `binary_sensor.0x286d97000115ca7a_moving` | same device's **accelerometer** | off | 1,318 | 234 s | 16.2 s | ~20 % | door slam, someone leaning on the door, HVAC vibration | a slow push below threshold | edge | 51 % |
| `binary_sensor.0x286d97000115ca7a_tamper` | magnet removed / case opened | off | **0** | — | — | 0 | — | — | edge | 51 % |
| `binary_sensor.0x286d97000115ca7a_battery_low` | battery threshold | off | **0** | — | — | 0 | — | set late; 51 % and never warned | level | 51 % |
| `binary_sensor.external_control_room_door_sensor_contact` | Apartment door **reed** (same model) | off | 99 | 2,855 s | 38.2 s | 12 % | latched 17.6 h once | — | edge | 48.5 % |
| `..._external_..._moving` | same accelerometer | off | 655 | 669 s | 14.1 s | 9 % | vibration | — | edge | 48.5 % |
| `binary_sensor.interior_control_room_door_sensor_contact` | Control-room **maglock door reed** | **on** | 65 | 21,231 s | **2,066 s (34 min)** | **57 %** | propped open all day — max **82.9 h** | open 57 % of the time = no information | edge | 47.5 % |
| `..._interior_..._moving` | same accelerometer | off | 518 | 902 s | 14.1 s | 4 % | vibration | — | edge | 47.5 % |
| `binary_sensor.control_room_hub_control_room_presence` | **LD2410 mmWave** (ESPHome, `delayed_off: 30s`) | off | 1,255 | 376 s | 63.6 s | **14.1 %** | fans, curtains, moving air, a chair | someone perfectly still >30 s after the last micro-motion | level | mains |
| `binary_sensor.control_room_hub_control_room_still_target` | LD2410 "static target" channel | off | 3,775 | 74 s | 22.5 s | 9 % | breathing/AC — this is the noisy channel | — | level | mains |
| `binary_sensor.control_room_hub_control_room_moving_target` | LD2410 "moving target" channel | off | **not recorded** | — | — | — | — | — | level | **recorder-excluded** |
| `binary_sensor.presence_sensor_occupancy` | **second mmWave**, `ld2410_ble` HLK-LD2410_B9AD via Bluetooth | off | 1,859 | 182 s | 29.6 s | 11.2 % | same class as above, and BLE re-pairing | BLE dropouts (no `delayed_off`) | level | 0 transitions in 14.2 min live |
| `binary_sensor.presence_sensor_motion` | same device's motion channel | off | **not recorded** | — | — | — | — | — | level | **recorder-excluded** |
| `binary_sensor.business_area_occupied` | template: hub-presence OR waiting-room-camera-human OR sim, `delay_off 5 s` | off | 1,185 | 405 s | 71.1 s | 14.4 % | **1,184 of 1,207 rising edges had hub presence on** → it is the hub with a 5 s filter | the camera term contributes **0** | level | — |
| `binary_sensor.hallway_humans_recent` | template over the two hallway **camera human** channels, `delay_off 2 min` | off | **0** | — | — | 0 | — | **DEAD** — its two inputs have never fired | level | 26 availability flaps |
| `binary_sensor.zone_hallway_active` | template: 2 hallway cams + doorbell person + 2 door contacts | off | 102 | 182 s | 8.9 s | 12 % | person at the doorbell (outside) → "hallway active" | **blind for 23 days** — see §2 | level | — |
| `binary_sensor.zone_outside_active` | template: doorbell person/visitor/motion | off | 2,060 | 102 s | 8.5 s | 0.5 % | the doorbell's night detection | doorbell offline | level | — |
| `binary_sensor.zone_control_room_active` | template: 2 CR camera humans + 2 CR door contacts | **on** | 75 | 12,182 s | 143 s | **57 %** | none (it tracks a door) | cameras contribute **0**; a stuck door pins it on 82.9 h | level | — |
| `binary_sensor.zone_control_room_occupied` | template: hub presence OR BLE boolean OR Echo `playing` | off | 1,279 | 376 s | 63.6 s | 14.1 % | 1,278/1,279 edges = hub presence; Echo gave 1 | — | level | — |
| `binary_sensor.phoenix_everyone_away` | template: NOT user_is_here AND NOT worker_is_here AND NOT guest | **on** | 281 | 1,491 s | **678 s** | **43.2 %** | **9.77 "empty" declarations/day** | goes off 0.13 s after the radar sees someone | level | — |
| `binary_sensor.video_doorbell_person` | **Reolink doorbell PoE person AI** (area "Outside Steps") | off | **1,981** | 103 s | 8.6 s | 0.7 % | night insects/headlights (see hourly profile §2) | someone hugging the wall | edge (8.6 s hold) | mains |
| `binary_sensor.video_doorbell_visitor` | Reolink "visitor" (button-class) | off | 26 | 63,862 s | 15.1 s | 0.02 % | — | — | edge | mains |
| `binary_sensor.video_doorbell_motion` | Reolink generic motion | off | 212 | 1,665 s | 2.8 s | 0.1 % | rain/leaves | — | edge | mains |
| `binary_sensor.video_doorbell_pet` / `_vehicle` | Reolink AI classes | off | **0** / **0** | — | — | 0 | — | not enabled/not present | edge | mains |
| `binary_sensor.cam_*_smart_motion_human_2` ×6 | Dahua NVR on-camera **human** detection | off ×6 | **0** ×6 | — | — | 0 | — | **its enable switch is OFF** (`switch.cam_*_smart_motion_detection = off`) | edge | NVR |
| `binary_sensor.cam_*_motion_alarm_2`, `_cross_line_`, `_cross_region_`, `_audio_mutation_`, `_video_loss_`, `_video_blind_` ×6 (42 more entities) | Dahua video motion / tripwire / intrusion / audio / tamper | off | **0** across all 48 | — | — | 0 | — | same disabled switches + duplicate "Generic RTSP" device set that is `unavailable` | edge | NVR |
| `lock.0x002446fffd0a4705` | **Kwikset SmartCode** deadbolt (z2m), event-driven state | unlocked | 98 changes | — | — | — | re-publishes "unlocked" — door log shows **1,113 "unlocked" vs 301 "locked" lines** | — | edge | 90 % |
| `sensor.apartment_door_smart_lock_action_user` / `_source_name` | **who/what** operated the lock (`manual`, `keypad`, `rf`, user name) | unknown / manual | 104 / 215 changes | — | — | — | — | — | edge | — |
| `sensor.0x002446fffd0a4705_pin_code` | **the last PIN used** (plaintext) | "" | 25 changes | — | — | — | — | — | edge | — |
| `input_boolean.phoenix_user_is_here` / `worker_is_here` | presence latches | off / off | 38 / 417 | 33,788 s / 1,756 s | **910 s / 506 s** | 4 % / 30 % | flapping: worker latch opens 14.5×/day | — | level | — |
| `media_player.control_room` (Office Echo Dot) | Echo `playing` used as occupancy | idle | 15 changes | — | — | — | — | never `playing` at an occupancy edge except once in 1,279 | level | — |
| `person.*` (3) and `device_tracker.*` (58) | phone/GPS/BLE presence | not_home / home / unknown | **0 across every one** | — | — | — | — | **FROZEN for 28.76 days** — including `device_tracker.zabz_ble_tracker`, which an arrival automation *requires* to be `home` | level | — |
| `switch.smart_switch_l1` / `_l2` | **Outside Door Electric Strike** / **Escape Room Maglock** relays | off / on | 30 / 72 changes | — | — | — | — | — | edge | — |
| `binary_sensor.control_room_hub_control_room_button` | physical button on the hub (buzz-in) | off | 2 | 553,134 s | **0.2 s** | — | — | a 0.2 s press is not a usable signal | edge | mains |

---

## 2. Dead, noisy, reliable — with the counts

**Dead (0 rising edges in 28.76 days), 52 entities**
- All **48** Dahua detector entities on all 6 cameras: `_smart_motion_human_2`, `_smart_motion_vehicle_2`,
  `_motion_alarm_2`, `_cross_line_alarm_2`, `_cross_region_detection_2`, `_audio_mutation_2`,
  `_video_loss_2`, `_video_blind_2`. Cause is measured, not guessed: the enable switches are off —
  `switch.cam_front_hallway_smart_motion_detection = off`, `switch.cam_front_hallway_motion_detection_2 = off`,
  and the same for `cam_deserted_exit`, `cam_deserted_interior`, `cam_waiting_room`, `cam_larry_s_exit`,
  `cam_larry_s_interior`. `_event_notifications` is `on`, which is why the cameras *look* configured.
- `binary_sensor.hallway_humans_recent` (0 edges) — its only two inputs are the dead hallway camera channels.
  Two live automations consume it: `snapshot_hallway_loop_start_humans_recent`,
  `hallway_guard_extend_window_on_people_detection`.
- `video_doorbell_pet`, `video_doorbell_vehicle` (0 edges each).
- `*_tamper` and `*_battery_low` on all three door sensors (0 edges).
- **Every identity tracker is frozen.** Probing all **60 enabled** `person.*` + `device_tracker.*`
  entities (3 person + 57 trackers) over the last 24 h: **0 of 60 had more than the single carry row**
  — none changed state. Eight of them were also carried across the full 28.76-day series with
  **0 changes** each, including `device_tracker.zabz_ble_tracker`, which has been `not_home` the whole
  time and which `phoenix_passive_arrival_bluetooth_owner` *requires* to be `home` — that automation
  cannot fire. (The other 550 `device_tracker` registry rows are `disabled_by: integration` and are
  not recorded at all; I am not counting those as "no edges", they are simply not measured.)

**Not measurable (recorder-excluded, so "0" would be a lie):** `control_room_hub_control_room_moving_target`
and `presence_sensor_motion`. Live sampling for 14.2 min: moving_target **2 transitions** (≈8/h),
presence_sensor_motion **0 transitions**.

**Noise (too many edges to act on)**
| signal | edges/28.76 d | per day | why it is noise |
|---|---|---|---|
| `video_doorbell_person` | 1,981 | 69 | the single chattiest signal in the estate; 0.7 % duty, 8.6 s per hit |
| `zone_outside_active` | 2,060 | 72 | pure function of the above |
| `presence_sensor_occupancy` | 1,859 | 65 | 182 s between hits — someone walking past |
| `control_room_hub_*_still_target` | 3,775 | 131 | the still-channel flickers every 74 s |
| `0x286..._moving` | 1,318 | 46 | accelerometer, not a door |
| `phoenix_worker_is_here` | 417 | 14.5 | median 8.4 min "on" — it is motion, not presence |
| `phoenix_everyone_away` | 281 | **9.77** | see §4 |

**Reliable (clean, interpretable, believable)**
| signal | edges | evidence |
|---|---|---|
| 3 door reeds (outside / apartment / control-room) | 113 / 99 / 65 | each is 1:1 with a physical door event; median 5.9 s, 38 s, 2,066 s "on" — durations match human behaviour |
| `video_doorbell_person` | 1,981 | 69/day, and it is a *leading* indicator: door opens a median **8 s** after it (§3) |
| `control_room_hub control_room_presence` | 1,255 | 14.1 % duty, 63.6 s median, 2 h 59 m maximum — the only signal that means "a body is in the room" |
| `lock` + `action_user` + `action_source_name` (98 / 104 / 215 state *changes*, not edges) | 98 | gives **who** opened it (`manual`, `keypad`, `rf`, named user) |
| access-control log | 101 events | Owner 69, Parent 25, Yocheved 4, manual buzz-in 2, one "Test" |

**Battery / last seen** (all live reads): outside door **51 %**, apartment door **48.5 %**,
control-room door **47.5 %**, deadbolt **90 %**. All three door sensors stepped down 15+ points inside
one day (66→51 on 10-25 04:33, 64.5→48.5 on 10-25 01:09, 66→47.5 on 10-11 11:39) — z2m's
percentage is not a linear fuel gauge; treat 47–51 % as "replace now", not "months left".

---

## 3. Latency, and how each was measured

Method: take the rising edges of the physical signal and of the derived state, pair each derived edge
with the nearest preceding physical edge inside a stated window, report the median of the deltas
(timestamps are HA's own `last_changed`, so this is event-to-event, no polling in between).

| pair (physical → state) | pairs | median | p10 | p90 |
|---|---|---|---|---|
| doorbell person → `zone_outside_active` | 1,891 | **0.0 s** | 0.0 s | 0.1 s |
| outside door opens → `zone_hallway_active` | 33 | **0.1 s** | 0.0 s | 6.5 s |
| control-room interior door opens → `zone_control_room_active` | 59 | **0.0 s** | 0.0 s | 0.1 s |
| control-room exterior door opens → `zone_control_room_active` | 19 | 0.0 s | 0.0 s | 8.2 s |
| **credential presented (keypad) → a door opens** | 73 | **1.4 s** | 1.0 s | 54.3 s |
| **doorbell person → the door opens** | 71 | **8.0 s** | 3.4 s | 52.3 s |
| doorbell person → interior (maglock) door opens | 23 | 71 s | 30.9 s | 158.5 s |
| deadbolt unlocks → outside door opens | 6 | 7.9 s | 0.2 s | 274.7 s |

Read: template sensors propagate in **under 100 ms** — the fusion layer is not where latency lives.
The two useful human latencies are **8 s (person seen at the door → door opens)** and **1.4 s
(keypad → door opens)**. The second one is the whole argument for credential-gating in §4: the
credential is 1.4 s upstream of the door, so a rule that waits for a credential after a door opens
is waiting for something that already happened.

---

## 4. The single best fusion for "someone is inside the shop right now"

**Rule**
```
INSIDE (latch, level):
    hub mmWave presence            (14.1 % duty, 63.6 s median, 1255 edges)
 OR presence_sensor_occupancy      (11.2 % duty,  29.6 s median, 1859 edges)   -- independent radio
 OR any of the 3 door contacts opened in the last 600 s
 OR a credential event in the last 600 s
EMPTY  = INSIDE has been false continuously for 600 s
ARM    = EMPTY AND no door open AND no credential for the last 1800 s
```

**Why this combination — the arithmetic, all four numbers measured over 28.76 days**

1. **The two mmWaves are genuinely independent and they agree 77 % of the time.**
   hub = 97.6 occupied-hours, BLE = 77.3 h, union 98.7 h, intersection 76.2 h → Jaccard **77.3 %**.
   Of the hub's occupied hours, the BLE radar also called occupied **78.1 %**. Two different radios,
   two different firmwares (ESPHome LD2410 vs BLE LD2410), same room, one union of 14.3 % duty.
   That agreement is what makes a *level* trustworthy; a single radar's 14 % is not.
2. **Night phantoms are ~0.3–0.5 per night, not per hour.**
   Episodes starting 02:00–06:00 local: hub **9** (0.31/night), BLE **14** (0.49/night),
   `business_area_occupied` **9** (0.31), doorbell person **1** (0.03), any door contact **0**.
   So the two-radar OR will produce roughly one false "someone is inside" every two to three nights,
   each typically lasting under a minute (median 63.6 s, longest 2 h 59 m) — and the 600 s hold makes
   a one-minute phantom a non-event.
3. **The incumbent is 15× worse and I can count it.** `phoenix_everyone_away` (template: the three
   latches are off) produced **281 "empty" declarations in 28.76 days = 9.77/day**, median duration
   **11.3 min**, total duty 43.2 %. Each of those windows is an arming opportunity. Measured
   consequence: **15 `phoenix_intrusion_active` episodes in 28.76 days**, and the causal edge in the
   9 s before each one is `zone_hallway_active` in **13 of 15** cases — of which **4 were a person
   merely seen at the doorbell, never entering.** The median "on" is 3.7 min.
4. **The proposed latch produces 0.63 empty-declarations per day and 0 false empties.** Simulated on
   the same series: mmWave-or-door-600 s → occupied 625 h (90.5 % duty — it never claims empty while
   a door is in play), **0.63 empty declarations/day**, and **0** of them were re-occupied within
   5 min. Against the incumbent's 9.77/day, that is **15.5× fewer arming opportunities** for the same
   detection coverage.

**False-negative cost, stated as a number.** A person who never moves and never opens a door is
invisible to every signal in this estate: the only interior-coverage device is one LD2410 in the
control room and its still-channel (`still_target`) is the thing that sees a seated person — and that
channel is the noisy one (3,775 edges). The waiting room and the shop floor have **no** occupancy
sensor at all (`business_area_occupied`'s waiting-room term is a dead camera), so "inside the shop
but outside the control room" is covered only by the door latch — 600 s wide. That is the honest
false-negative: **up to 10 minutes of undetected presence after the last door event, in every room
except the control room, indefinitely.**

**The one thing that actually separates a person from an intruder here is the credential.**
286 door-open edges (counted on the three *template* contacts, which is what the automations trigger
on — the raw sensors show 113 / 99 / 65, and the 9-edge difference is restart blinks where a contact
re-published "open" after HA came back); only **87 (30 %)** had a credential event in the preceding
300 s; the outside door specifically: 118 opens, **12** credentialed. Applying the proposed rule,
**24 door opens (0.83/day)** have no credential in the prior 300 s *and* no radar presence in the
prior 600 s — those are the alarm population. Split by local clock: **11 inside 09:00–20:00, 13
outside it (0.45/day)**.
So the last 0.45/day can only be removed by making staff badge *in* as well as out, or by the
owner accepting a page every other night. That is a decision, not an engineering gap.

---

## 5. What is missing entirely

1. **No window sensor anywhere.** The device-class census of all 121 `binary_sensor` entities is:
   motion 43, safety 21, connectivity 7, problem 7, sound 7, **door 6**, occupancy 5, battery 3,
   moving 3, tamper 3, cold 1, heat 1, none 14 — and **window 0, smoke 0, carbon_monoxide 0,
   moisture 0, gas 0**. The entire perimeter is **three door magnets**.
2. **No glass-break, no shock, no audio detector.** The Dahua `audio_mutation` channels exist and are
   disabled and have never fired.
3. **No smoke, heat, CO or moisture detector** — zero entities with those `device_class` values. The
   single `heat` entity is `binary_sensor.thermostat_is_heating`, which is HVAC, not a heat alarm.
4. **No `alarm_control_panel` at all.** The "alarm" is `input_boolean.phoenix_intrusion_active` plus
   scripts. Consequently there is no arming keypad at the *exit*, no exit delay, no entry delay, no
   duress code and no disarm-without-a-credential path.
5. **No back-door or shop-side contact.** The cameras are named "Larry's Exit", "Deserted Exit",
   "Waiting Room" — three doors — and none of them has a contact. `switch.random` ("Deserted House
   Door Maglock") and `switch.0xffffb40e060040c4` ("Outside Door Electric Strike", a second one) are
   both `unavailable`.
6. **No occupancy sensor in the waiting room or on the shop floor.** One LD2410 in the control room,
   one BLE LD2410 in the control room, and nothing else. `business_area_occupied` is the control-room
   radar wearing a different name.
7. **No heartbeat / last-seen watchdog on the three contacts.** A reed that stops reporting is
   indistinguishable from a closed door; `_battery_low` has never fired even at 47.5 %.
8. **No persistence for credential events.** `esphome.access_control_keypad_entry` /
   `_rfid_entry` are HA events — not in the recorder, not in any table. The only surviving record is
   the first 255 characters of `input_text.phoenix_access_control_log` (101 events in 28 days) and the
   lock's own `action_user`. A break-in with a stolen PIN leaves almost no trace.
9. **The RFID layer is dead.** `counter.phoenix_access_control_rfid_events` and
   `_keypad_events` are `unavailable`; of the 57 enabled trackers, **47 are `ibeacon` and all 47 are
   `unavailable` right now**, 6 are `asuswrt`, 3 are `mobile_app`, 1 is `bermuda`; Bermuda has 44
   devices configured, 4 proxies, and every `sensor.*_distance` is `unknown`. There is no credential
   path other than the Wiegand keypad.
10. **49 of 124 automations are `unavailable`** (39.5 %), including every `Presence: Automatic …`,
    every `Access Control: Keypad …` and `Keypad PIN Entry to Phoenix Validator`. They are entity-registry
    ghosts of deleted automations; anything that lists "our presence automations" from the UI is
    reading a ruin.

---

## 6. Anomalies that matter for the redesign

1. **The outside door contact reported OPEN almost continuously for 22.7 days** — from
   `09-27 20:27:26` to `10-20 12:00:38` the "on" state is broken only by three closes totalling about
   7 minutes (`10-04 21:05:28→21:11:54`, `10-10 20:05:56→20:06:59`, `10-17 19:59:07→19:59:48`), each
   of which coincides with a restart — the z2m entities blipped `unavailable` at exactly those times.
   A fourth latch ran to `10-21 15:02:03`; normal service only from then (15–36 opens/day since,
   against 1/day before). At 83 % duty the reed is useless as a security signal, and it silently
   disabled `zone_hallway_active` for three weeks: zone-hallway rising edges per local day were
   **1** on 09-27, 10-04, 10-10, 10-17, 10-18 and 10-20 and **0 on every other day** in that span,
   against **9, 10, 9, 25, 26, 17** for 10-21 → 10-26. From HA's side a propped door and a failed
   magnet are the same reading — that ambiguity is the defect.
2. **The control-room interior door is open 57 % of the time**, longest single episode **82.9 h**. It
   pins `zone_control_room_active` on, which deafens the "not already active" condition.
3. **Every Dahua detector entity has never produced an event** — all 63 `binary_sensor.cam_*` rows
   (48 of them on the 6 live NVR channels), and the reason is two switches per camera, not the
   cameras: `smart_motion_detection` and `motion_detection_2` are `off` on all six.
4. **`phoenix_everyone_away` goes off 0.13 s after the radar sees someone** (251 overlapping intervals,
   33 s of overlap in total) — it is a *motion-gap detector*, not a presence detector, and it is the
   arming gate for a whole-building alarm.
5. **Restart cadence:** 10-04 21:05, 10-10 20:05, 10-17 19:59, 10-20 12:00, 10-22 18:56, 10-24 19:44,
   **10-26 14:12 and 14:15** — eight restarts in 28 days, two of them during today's audit. Each one
   resets every `last_triggered` (so `automation.security_outside_door_stuck_open_30_minutes` shows
   only 10-24 21:15 despite the 23-day latch), which is why automation `last_triggered` cannot be used
   as a long-run record.
6. **`sensor.0x002446fffd0a4705_pin_code` publishes the last PIN used in plaintext** as a state — it is
   in every history row and in the recorder for 28 days.

---

## 7. What I could not measure, and why

- `binary_sensor.control_room_hub_control_room_moving_target`, `binary_sensor.presence_sensor_motion` —
  recorder-excluded; live sample only (14.2 min, 2 and 0 transitions). Their 28-day behaviour is
  unrecoverable, and it cannot be reconstructed retroactively.
- The Dahua cameras' own event stream — the switches are off, so "would human detection work if
  enabled" is untested and I did not change state to find out (read-only).
- Anything before `2026-09-28T00:26:38Z` — purged, not present, not answerable.
- The keypad/RFID event stream itself — HA events are not recorded; only its side effects are.
