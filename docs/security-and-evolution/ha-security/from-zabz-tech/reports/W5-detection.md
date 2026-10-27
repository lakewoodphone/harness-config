# W5 — DETECTION COVERAGE AUDIT

**LOCAL (zabz-tech)** · host `ZABZ-TECH` · read 2026-10-26T18:26:48Z (14:26:48 -04:00) · **READ-ONLY, nothing edited, no state changed, no service restarted**

## 0. Basis of this report

| Step | Result |
|---|---|
| `pwd` | `C:\Users\ezabz\Code` |
| SHA256[:12] `phoenix_security.yaml` | `e6b45f6b1c04` — **matches expected**, so revision is the one under audit |
| Live `GET /api/states` | **1036 entities**, saved to `states-live.json` (467,832 bytes) |
| Live `GET /api/logbook/…` | 3 windows, 24 h each; saved to `logbook-24h.json` (31,689 entries) and `logbook-7d.json` |
| Live `GET /api/history/period/…` | 6 single-entity windows, used where logbook could not answer |
| Snapshot artefacts | 10 tiles probed with `GET /local/snapshots/…`; 4 downloaded and **viewed** |
| Company SMS record | `sqlite3 /root/authority.db` on `secratary-cloud`, one hop, SELECT only |
| Config | `phoenix_security.yaml`, `presence_architecture.yaml`, `scripts.yaml`, `automations/access_control.yaml`, `configuration.yaml`, `lovelace/cams.yaml` |

**A measurement rule I had to establish first, because it silently truncated three of my own reads:** `/api/logbook/<start>` and `/api/history/period/<start>` both return **at most 24 hours from the start timestamp**, not "to now". My first logbook call asked for 7 days and got 2,872 entries ending exactly 24 h after the start. Any count taken from an unbounded call is a count of one day, not of the period you think you asked for.

---

## 1. Entry-point inventory

### 1.1 What physically exists

Three contact sensors, three tamper sensors, one Zigbee device. That is the entire perimeter.

| Door (as the access model names it) | Detecting entity | Raw device | Live state 18:26:48Z | Battery |
|---|---|---|---|---|
| Front / outside door (`strike`) | `binary_sensor.phoenix_outside_door_contact` | `binary_sensor.0x286d97000115ca7a_contact` — "Outside door sensor Door" | `off` (10/26 14:16:26) | 51 % |
| Apartment door (`apartment`) | `binary_sensor.phoenix_control_room_exterior_door_contact` | `binary_sensor.external_control_room_door_sensor_contact` — **friendly name "Apartment Door Sensor Door"** | `off` (14:24:28) | 48.5 % |
| Control-room interior door (`interior`) | `binary_sensor.phoenix_control_room_interior_door_contact` | `binary_sensor.interior_control_room_door_sensor_contact` — "Control Room Door Sensor Door" | **`on`** (14:16:25) | 47.5 % |
| `maglock` door | **nothing** | — | — | — |
| Every window | **nothing** | — | — | — |
| Roof / hatch / back-of-shop / shop floor | **nothing** | — | — | — |

Zone fusion, live: `zone_hallway_active` = `off`, `zone_control_room_active` = **`on`** (because the interior contact is `on`), `zone_control_room_occupied` = `off`, `zone_outside_active` = `off`.

### F1 — SEVERITY: CRITICAL — the perimeter is three door magnets and nothing else

**Claim.** The installation can detect exactly three doors opening. It has no window sensor, no glass-break, no shock/vibration sensor, no roof or hatch sensor, and no sensor on the `maglock` door that the access model itself treats as a real door (`access_control.yaml:499-506` unlocks it by name).

**Proof.** `GET /api/states` filtered to `device_class: door` returns exactly 6 entities = 3 contacts plus their 3 template twins (`configuration.yaml:366-388`). Filtered to `device_class: window|opening|garage_door|smoke|gas|moisture|heat`: **0 window sensors**, 1 heat (thermostat). Zigbee `binary_sensor.0x*` returns 4 entities, all belonging to one device (`0x286d97000115ca7a`). `tamper` class = 3 entities, all `off`. There are 43 motion-class binary sensors but 34 of them are the Dahua NVR's own per-channel alarms (all dead, see F6) and the rest are interior occupancy.

**Fix.** Cheapest first, in this order: (a) two Zigbee contact sensors on the shop-side and back windows — same vendor, same mesh, ~same battery profile, no new integration; (b) one glass-break on the front glazing; (c) put a contact on the `maglock` door so the two-door path is fully sensed. Do not add a fourth sensor type before the three that exist are proven alive (F2, F3).

### F2 — SEVERITY: HIGH — all three contacts sit at ~half battery and nothing watches them

**Claim.** The three primary intrusion sensors are at 51 %, 48.5 % and 47.5 %. Nothing in the configuration fires on a sensor becoming `unavailable` or `unknown`, so a dead sensor is invisible — which is exactly how the six-day outage in P17 happened, and how the 67-hour outage in F3 happened.

**Proof.** `sensor.0x286d97000115ca7a_battery` = `51`; `sensor.external_control_room_door_sensor_battery` = `48.5`; `sensor.interior_control_room_door_sensor_battery` = `47.5`. All `*_battery_low` flags `off`, so nothing warns yet. Grep of every YAML outside `custom_components` for `to: 'unavailable'` / `to: 'unknown'` / `watchdog` / `heartbeat` / `stale` returns **zero automations that react to a sensor dying**; the only matches are prose in guest-mode comments. There *are* ESPHome system-health automations (`automation.system_health_control_room_hub_offline`, `…security_hub_offline`) — they watch the **hubs**, not the sensors that carry the alarm.

**Fix.** One automation, one condition, no new hardware: trigger on any of the three raw contacts going `unavailable`/`unknown` for 5 minutes, and page the same roster the intrusion page uses. Battery arithmetic for the deadline: they have lost ~50 % in 41 days since the 2026-09-15 replacement, so ~85 days total life, so they are due to fail on or about **2026-12-09**. A `< 30 %` battery warning automation should be in place before then, not after.

### F3 — SEVERITY: CRITICAL — a latched contact is invisible, and one is latched right now

**Claim.** The intrusion trigger fires on the *edge* `to: "on"` only (`phoenix_security.yaml:24-36`). A contact that is stuck `on` therefore cannot ever fire it — and a contact that is stuck `on` also pins `zone_hallway_active` / `zone_control_room_active` `on`, which kills the zone half of the same trigger for the same reason. Right now the control-room interior door reads `on`, so that door and that zone are both edge-dead.

**Proof, live.** `binary_sensor.phoenix_control_room_interior_door_contact` = **`on`**, `last_changed 10/26/2026 14:16:25`; consequently `binary_sensor.zone_control_room_active` = `on` with the same timestamp. The trigger's condition set includes "`input_boolean.phoenix_intrusion_active` is `off`" and an edge on one of five entities — there is no level test anywhere.

**Proof, historical — this is not hypothetical.** `/api/history/period/2026-10-19T00:00:00Z?filter_entity_id=binary_sensor.phoenix_outside_door_contact&minimal_response=true` returns **exactly one point for 24 hours**: `10/18/2026 20:00:00 on`. The front door did not change state once in a full business day — it was **latched `on`**, not `unavailable`, not `off`. In the same 24 h the control-room interior door recorded 13 points of normal traffic, so the recorder was healthy and the shop was open. Following it out: window starting 10/20 shows `20:00 on → 12:00:38 unavailable → 12:01:04 on`; window starting 10/21 shows `20:00 on → 15:02:03 off`. **The front door was latched `on` from at or before 18 Oct 20:00 until 21 Oct 15:02:03 — at least 67 hours** — during which the main entrance could not raise an alarm, could not clear the zone, and read as a door standing open. Zero `automation.phoenix_extreme_intrusion_trigger` entries exist in that window while `script.phoenix_intrusion_reset` ran 51 times (17 disarms × 3 state writes).

**Fix.** Make the trigger level-aware and the latch loud. Two changes: (a) add a second trigger branch on `for: "00:01:00"` for each contact (a door standing open for a minute while `everyone_away` is on *is* the event); (b) alert on a contact whose state has not changed for 24 h while its sibling doors have — the latch detector, which is the only thing that catches this class without new hardware. Then clear today's `on` state and find out whether the interior door is genuinely open.

### F4 — SEVERITY: MEDIUM — the exact silent route in

See §3.

---

## 2. The 2026-09-15 findings, re-measured against live today

Every row is a claim from P227 / P17 / H431 / H432 checked against the live installation or the file as it stands at commit `e6b45f6b1c04`.

| # | 2026-09-15 finding | Today | Proof |
|---|---|---|---|
| F5 | **No `alarm_control_panel`; "armed" is a bare boolean** (P227 §1) | **STILL TRUE** | Domain census of 1036 entities: no `alarm_control_panel` key at all. `input_boolean.phoenix_intrusion_active` = `off`, last changed 14:17:21. `input_select.phoenix_security_mode` = `Home`. The real gate is `binary_sensor.phoenix_everyone_away`. |
| F6 | **NVR's own motion/IVS never reaches HA** (P227 §2) | **STILL TRUE, and now measured harder** | 63 `binary_sensor.cam_*` entities: 54 `off`, 9 `unavailable`. In the 24 h logbook window there are **0 `on` states** across every `cam_*` `smart_motion_human` / `cross_line` / `cross_region` / `motion_alarm` entity, while the same window holds 23 outside-door opens and 52 doorbell person detections. The `_2` twins are available (`off`) and simply never fire; the unsuffixed twins are `unavailable`. |
| F7 | **96 of 174 security entities unavailable, ghost pairs** (P227 §3) | **BETTER BUT STILL TRUE** | 310 of 1036 entities are `unavailable` = **29.9 %** (was 40.3 %). Of 124 `automation.*` entities, **49 are `unavailable`**; of 54 `script.*`, **19**. The ghost twins are still the working ones: `automation.evidence_person_at_doorbell_clip_rate_limited` = `unavailable` while its `_2` twin is live. |
| F8 | **Clips cost ~1 min of Pi CPU; NVR records H.265** (P227 §4) | **NOT RE-TESTED** | I have no CPU measurement from this host and will not assert one. See "what I could not verify". |
| F9 | **A sensor outage is invisible; nothing runs the collector** (P17) | **STILL TRUE** | F2: zero automations react to `unavailable`. The 67-hour front-door latch (F3) is the same failure with a worse shape, and it happened 5 weeks after the pain was filed. |
| F10 | **The snapshot step of the intrusion response fails 100 %** (P17) | **CHANGED — it now produces files, but only 3 of 4** | Drill `script.phoenix_test_intrusion_sequence` at 14:16:10 today → logbook `Intrusion Evidence: captured 3 image(s) for intrusion_test: …_doorbell.jpg, …_front_hallway.jpg, …_control_room_interior.jpg` at 14:16:40. The 4th roster slot produced nothing (F16). |
| F11 | **Entering the drop-off PIN fires a full intrusion alarm** (H431, URGENT) | **CLOSED — properly** | `access_control.yaml:562-566` now reads `entered_code == drop_off_pin and drop_off_pin_enabled`, and the comment records the 2026-10-18 owner confirmation. `input_boolean.phoenix_drop_off_pin_enabled` = `off` and `input_text.phoenix_drop_off_pin` is now **empty**. Note the old line reference (`:511-516`) no longer resolves — the code moved to `:556-566`. |
| F12 | Scenario 8 BUSINESS ACCESS has the same shape but cannot fire (H431) | **STILL TRUE (latent)** | `access_control.yaml:596` gates on `customer_pin_enabled`; `input_boolean.phoenix_customer_pin_enabled` = `off`. But the sequence still sets **no presence boolean** — it sets `input_select.phoenix_security_mode` to `Customer` at `:627-630`, and `phoenix_security.yaml` never reads that select. So a customer PIN, if ever enabled, opens the strike while `everyone_away` stays `on` and the alarm runs. Same defect, one flag away. |
| F13 | **Test mode is write-only; the drill really pages all three** (H431) | **CLOSED** | `phoenix_security.yaml:120` now evaluates `test_mode` once, and `:184-194` suppresses lights, siren and overhead audio, changing the event to `intrusion_test`. Proven live at 14:16:35: the script logged "TEST MODE: lights, siren and overhead audio were suppressed" and no SMS exists in `sms_log` for it. |
| F14 | **The status-light feedback is entirely inert** (H431) | **STILL TRUE** | `light.downstairs_status_light` is **absent** from the live state machine. `light.smart_notification_light` = `unavailable`; `light.control_room_smart_light` = `unavailable`. So `phoenix_v2_master_light_controller` still branches and issues no command. |
| F15 | **"The alarms go off" has no audible alarm in it; siren unused** (H431) | **STILL TRUE, and worse than filed** | `siren.video_doorbell_siren` = `unknown` and is referenced by **zero** YAML files outside `custom_components` (grep for `video_doorbell_siren` returns nothing). The only audible artefact is `rest_command.phoenix_alarm_mac_on` → `POST http://192.168.50.45:8128/alarm/on` (`packages/secretary.yaml:37-40`). If the Mac mini at 192.168.50.45 is asleep or off, the "alarm" is silently just lights. `phoenix_intrusion_loop` is a strobe and a comment — `phoenix_security.yaml:246-248` is still the heading "Periodic Audio Overlay (Every ~15s)" followed by nothing. |
| F16 | Trigger never reads `security_mode`; any valid credential disarms (H431) | **BOTH STILL TRUE** | `phoenix_security.yaml:37-45` conditions are `phoenix_everyone_away == on` and `phoenix_intrusion_active == off`; no reference to `input_select.phoenix_security_mode` anywhere in the package (grep). The disarm automation still listens on event `phoenix.valid_pin` with **no** `event_data` filter (`:82-96`). |
| F17 | **No producer exists for `phoenix.valid_pin`** (H432) | **STILL TRUE** | Grep of every YAML outside `custom_components` for `^\s*-\s*event:` (the fire-event action) returns **0 matches**. `phoenix.valid_pin` appears only as a *consumer* in 3 places. So a valid code cannot directly silence the alarm; it can only do so indirectly by setting a presence boolean before the door opens (which is what Scenario 1 does at `:171-172`). |
| F18 | **Each contact is exposed twice, so events count double** (H432) | **STILL TRUE, and it is the correct design** | `configuration.yaml:366-388`: three template twins fed by three raw sensors, each carrying an `availability` guard. This is duplication without double-counting — the twins are the only entities the alarm reads. Worth stating plainly because it is the one thing on this surface that behaves better than its reputation. |
| F19 | **The doorbell is the only camera reporting people** (H432) | **STILL TRUE** | 24 h: `binary_sensor.video_doorbell_person` rose 52 times; the Dahua per-channel human sensors rose 0 times (F6). |

---

## 3. The silent entry path — the exact route

### F20 — SEVERITY: CRITICAL — walk in through the front door while it is latched, or while the alarm is already latched

**The route, in order, with nothing to defeat:**

1. The front door contact is either **latched `on`** (measured: 67 hours, 18–21 Oct) or the alarm boolean is **already latched `on`** from an earlier trigger (measured: 25 Oct 23:23:21 → 26 Oct 11:25:25, **12 h 2 m**). In both cases the trigger's condition `input_boolean.phoenix_intrusion_active == off` or its edge requirement is unsatisfiable.
2. Open the front door normally. No `to: "on"` transition occurs, because either the contact never left `on`, or `zone_hallway_active` was already `on`, or the whole automation is blocked by its own "not already active" guard.
3. Walk through the `maglock` doorway — **no sensor exists** there (F1).
4. Walk into the control room through the interior door. If that door is already `on` — **it is, right now, since 14:16:25** — no transition occurs and `zone_control_room_active` is already `on`.
5. Stand in the control room. `zone_control_room_occupied` will eventually go `on`, but nothing in the intrusion logic reads it for detection; it only drives auto-departure and periodic snapshots.

**Net result: no entity goes true, no automation fires, no page is sent, and the only trace is optional snapshot tiles that are written on *other* automations' schedules.**

**Proof.** F3 for the latch; `phoenix_security.yaml:43-45` for the self-blocking condition; the 12-hour latch is in the 24 h logbook — `input_boolean.phoenix_intrusion_active on` at `10/25 23:23:21`, `off` at `10/26 11:25:25`, with no other writer in the file (grep: only `:76-78` turn_on, `:93-95` turn_off, and the test script). Nothing clears it on a timer.

**A second, cheaper silent path: the shop side.** No sensor covers the shop floor, the windows, or the back. With 3 doors sensed and every other opening unwatched, the alarm's coverage is the three door frames and nothing between them.

**Fix.** Ranked by cost: (1) a latch guard — if `phoenix_intrusion_active` has been `on` for more than 30 minutes with `everyone_away` `on`, page the owner and log it; an alarm nobody can clear is not an alarm, it is a blindfold. (2) The level-trigger branch from F3. (3) A `maglock` contact. (4) A glass-break on the front glazing.

---

## 4. The cameras

### 4.1 Roster versus reality

| Camera | NVR ch | In intrusion evidence roster? | Works right now? | Proof |
|---|---|---|---|---|
| `camera.video_doorbell_fluent` (Reolink) | — | **yes**, role `doorbell` | yes, **but 640×480** | tile `latest_intrusion_doorbell.jpg` → 200, 55,143 B, viewed: 640×480, OSD `2026/10/26 14:16:35`, shows the front approach |
| `camera.reolink_video_doorbell_poe_clear` | — | **no** | yes, **2560×1920** | tile `latest_person_doorbell.jpg` → 200, 542,147 B, viewed: person with a parcel, face at three-quarter angle, fully identifiable |
| `camera.cam_front_hallway_main` | 6 | **yes**, role `front_hallway` | yes | tile 200, 149,503 B, viewed: 2560×1440, OSD `2026-10-26 13:25:14`, labelled "Main Entrance" |
| `camera.cam_deserted_interior_main` | 7 | **yes**, role `control_room_interior` | yes | tile 200, 298,175 B, viewed: 2560×1440, OSD `13:25:12`, labelled "Deserted House inwards" — bench, back doorway, both internal doors in frame |
| `camera.cam_larry_s_interior_main` | 2 | **yes**, role `larry_interior` | **NO — never** | tile `latest_intrusion_larry_interior.jpg` → **404**; every other tile in the same directory returns 200 |
| `camera.cam_deserted_exit_main` | 1 | **no** | **yes** | tile `latest_control_room_open_control_room_exit.jpg` → 200, **315,534 B** |
| `camera.cam_waiting_room_main` | 5 | **no** | **yes** | tile `latest_outside_door_waiting_room.jpg` → 200, **204,070 B** |

### F21 — SEVERITY: CRITICAL — the intrusion doorbell photo is one-sixteenth the resolution of the one the shop already takes

**Claim.** The evidence roster captures the doorbell through `camera.video_doorbell_fluent` at **640×480**, while the routine person-detection path captures the same camera through `camera.reolink_video_doorbell_poe_clear` at **2560×1920**. A face at door distance in 640×480 is a few pixels. We would have a picture and not an identification.

**Proof, measured and viewed.** `latest_intrusion_doorbell.jpg` = **55,143 bytes, 640×480**, OSD `2026/10/26 14:16:35 MON` (the drill). `latest_person_doorbell.jpg` = **542,147 bytes, 2560×1920**, showing a person carrying a box, face and clothing clearly distinguishable. Pixel ratio 640×480 versus 2560×1920 = 1 : 16. `scripts.yaml:241-244` already states the correct entity — *"camera.video_doorbell_fluent still exists but is NOT the entity the evidence path uses … Point at it"* — and `scripts.yaml:248` does point at `reolink_video_doorbell_poe_clear`. The intrusion roster at `phoenix_intrusion_evidence.yaml:126-127` was never updated to match.

**Fix.** One line: change `phoenix_intrusion_evidence.yaml:126` from `camera.video_doorbell_fluent` to `camera.reolink_video_doorbell_poe_clear`. Then re-run `script.phoenix_test_intrusion_sequence` with test mode on and view the tile — the drill is safe and already proven not to page.

### F22 — SEVERITY: HIGH — a quarter of the roster is a camera that cannot exist, and the two best cameras are not in it

**Claim.** `camera.cam_larry_s_interior_main` is NVR **channel 2**, which has no camera attached. It returns HTTP 400 from `snapshot.cgi` — which means *authenticated, but no camera on that channel*. It has never written an evidence file. Meanwhile channels 5 and 1 both work and are absent from the roster.

**Proof.** `latest_intrusion_larry_interior.jpg` → **404**, the only 404 among ten probes. `lovelace/cams.yaml:108-112` and `:127-141` state it directly: five cameras exist on channels 1, 5, 6, 7 plus the Reolink; channels 2, 3 and 4 have **no camera attached**, and `cam_larry_s_interior_main` (ch2) and `cam_larry_s_exit_main_2` (ch3) "can never produce a picture, and that is not a fault to chase". The drill at 14:16:40 confirms the consequence: **3 images captured, not 4**.

**Note the GIVEN holds, with one correction to its wording and one caveat to mine.** `camera.cam_larry_s_interior_main` is not a broken interior camera; it is a live-looking entity bound to an empty channel. I did **not** re-issue the HTTP 400 call, deliberately — `phoenix_snapshot_cameras.yaml:40-46` warns that every retry is another failed login against an NVR that locks the account — so my proof is the missing artefact (404) plus the repository's own measurement, not a fresh 400.

**Fix.** Delete the `larry_interior` line from `phoenix_intrusion_evidence.yaml:132-133` (and its capture and tile blocks at `:176-185` and `:223-232`), and add `camera.cam_waiting_room_main` (ch5) and `camera.cam_deserted_exit_main` (ch1) in its place. This costs nothing, removes a guaranteed failure from every intrusion, and adds two working views. Also disable the two ch2/ch3 config entries as `cams.yaml:134` recommends, so the next session does not repeat this audit.

### F23 — SEVERITY: MEDIUM — the interior stills carry a timestamp 51 minutes behind the doorbell's

**Claim.** The two Dahua stills captured by the same 14:16 drill carry OSD timestamps of `13:25:12` and `13:25:14`, while the Reolink still from the same drill carries `14:16:35`. Either the NVR's clock is ~51 minutes slow, or those two tiles were not rewritten by the drill.

**Proof.** The two offsets are 51 m 23 s and 51 m 21 s — consistent to two seconds, which is what a fixed clock offset looks like, not what a stale file looks like. Viewed in all three images.

**Fix.** Set the NVR to NTP against the same source as HA and verify by capturing a still and comparing its OSD to `now()`. Evidence that misdates itself is worse than no evidence in a dispute.

### 4.2 What a real event actually produces, and what it misses

In the 14:16 drill, after the `bash -c` fix landed, a real intrusion produces **three stills**: a 640×480 doorbell frame, a 2560×1440 hallway frame aimed at the doors rather than the threshold, and a good 2560×1440 control-room frame. It does **not** produce: the waiting room (ch5, working), the control-room exit side (ch1, working), any frame of the shop floor, any clip attached to the page, or a picture with a usable face unless the intruder happens to be inside the doorbell's 640×480 frame at the right moment.

And in the **most recent real alarm** — 14:03:15 today — it produced *nothing usable at all*. Timeline from the logbook: `14:03:15 zone_hallway_active on` → `14:03:21 intrusion_active on` → `14:03:26` front door opens → `14:03:29` presence credited, disarm → `14:03:43 script.phoenix_intrusion_evidence_and_page started` → `14:03:50 off`. There is **no** "INTRUSION — entry snapshots" line and **no** "captured N image(s)" line for 14:03, against both appearing for 14:16. The evidence script died at its verify step and the page was never sent.

### F24 — SEVERITY: CRITICAL — no intrusion page has ever been recorded, and the fix that would send one has only ever been exercised in test mode

**Claim.** Across the authoritative `sms_log` — 4,507 rows spanning 2025-09-02 to 2026-10-26 17:44 — there is **not one** intrusion page. Not one row contains `LPT-SECURITY` (the literal first line of the page body, `main.py:8599`). The `bash -c` defect that suppressed the page was fixed in the repo today, and HA restarted at 14:15:47, but the only run since then was the 14:16 drill, which by design skips the SMS.

**Proof.** `ssh secratary-cloud` → `sqlite3 /root/authority.db`: `rows|4507|2025-09-02T06:19:25+00:00|2026-10-26T17:44:57+00:00`; `lptsec|0`; `intrusion|0`; `extreme|0`. The 45 rows matching `securit` are all Gmail and T-Mobile alerts from the CEO chat, none of them an HA page. This corroborates the file's own note at `phoenix_intrusion_evidence.yaml:56-58`: *"6 intrusion episodes on 2026-10-24..26, 0 SMS in sms_log"*.

**Fix.** Do not declare the paging path fixed. The only way to prove it is a real page with `force`, to the owner's own number, at a time he has agreed to — then read the `To` header and the row back. Until that has happened, the honest status of the intrusion page is **unproven end-to-end**, and every other detection improvement is downstream of it.

---

## 5. Is "owner versus intruder" distinguishable today?

### F25 — SEVERITY: CRITICAL — not at the alarm, yes in the data, and the gap is one condition

**Claim.** The alarm cannot tell the owner from an intruder. But the credential event that *would* tell it apart is already firing, already carries a name, and is already being logged.

**Proof that the alarm cannot.** The trigger's entire condition set is `binary_sensor.phoenix_everyone_away == on` and `intrusion_active == off` (`phoenix_security.yaml:37-45`). "Everyone away" is a template over three presence booleans (`:8-15`). Those booleans are set by occupancy inference — `zone_control_room_occupied`, which is mmWave presence, BLE, or the Echo playing (`presence_architecture.yaml:69-84`) — and cleared by a 5- or 10-minute auto-departure (`:90-146`). So the discriminator is *"is the room empty"*, not *"did someone badge"*. Measured consequence: `everyone_away` rose 12 times in 24 h and the alarm fired 4 times, all four from `zone_hallway_active`, and three of the four were disarmed within 38 seconds by occupancy. In 24 h the false-alarm rate is 4 of 4.

**Proof that the data exists.** The keypad path is live and named. `input_text.phoenix_access_control_log` currently reads, verbatim: `Oct 26, 1:22 PM - Owner Access at Interior / Oct 26, 12:03 PM - Owner Access at Interior / Oct 26, 11:29 AM - Owner Access at Interior / Oct 26, 11:28 AM - Owner Access at Maglock / Oct 25, 12:04 PM - Yocheved Access at Interior …`. That text is written by `access_control.yaml:160-169` from an `esphome.access_control_keypad_entry` event whose data carries `code`, `door_name`, and a resolved role. `automation.phoenix_access_control_master_presence` is `on`. RFID roles exist too (`input_text.phoenix_rfid_owner_tag` = `3800389`, wife, and three worker tags).

**The smallest mechanism that would distinguish them.** One `input_boolean.phoenix_credential_valid`, one 120-second timer, and **one added condition**.

- Add to the master automation's action, immediately after the role is resolved: `input_boolean.turn_on phoenix_credential_valid` and `timer.start phoenix_credential_valid_window` for 2 minutes.
- Add to `phoenix_security.yaml:37-45`, as one more condition: `condition: state, entity_id: input_boolean.phoenix_credential_valid, state: "off"`.

That single line changes the rule from *"a door opened while nobody is marked present"* to *"a door opened and nobody badged"* — which is the rule the owner actually stated in `docs/SECURITY_DECISIONS.md`. It also collapses the false-alarm class: a customer walking up to the front door would no longer fire a three-person family alarm, because the trigger would be gated on the *credential* rather than on inferred occupancy, and the perimeter approach sensor could be removed from the trigger while staying in the snapshot trigger.

Second-order, nearly free: the page body already has a `detail` field (`phoenix_security.yaml:214`). Populate it from the last credential — `"no credential presented"` versus `"owner credential at Interior 14 s earlier"` — and the first line the owner reads at 2 a.m. distinguishes the two cases without him opening anything.

---

## 6. The highest-value detection gaps, ranked

### 1. The alarm cannot fire on a latched or self-latched state (F3, F20) — CRITICAL
Measured twice: 67 hours of a latched front door, 12 hours of a latched alarm boolean, both inside the last nine days. This is the only gap on the list that has demonstrably made the main entrance blind for days at a time, and both of its mechanisms are still armed right now. Everything else on this list is a gap *in theory*; this one is a gap in fact.

### 2. The page has never been proven to arrive (F24) — CRITICAL
4,507 SMS rows, zero intrusion pages, ever. A detection system whose alerting has never fired in production is a recorder, not an alarm. It ranks second only because it is *known* and the fix is written; it would rank first if a second real event happened before it is proven.

### 3. Owner and intruder are indistinguishable, and the fix is one condition (F25) — CRITICAL
This is P227's own headline, still open 41 days later. It is third because it is the root of the 4-in-4 false-alarm rate, and because the credential data needed to fix it already exists and is already being written.

### 4. The intrusion photo is 640×480 (F21) — CRITICAL
One line. The difference between evidence and decoration. It ranks this high because the shop already takes a 2560×1920 frame of the same door for routine parcel deliveries — the good version is already in use, on the wrong path.

### 5. Nothing watches the sensors (F2) — HIGH
The three sensors the whole system rests on are at ~half battery, due around 2026-12-09, and no automation anywhere reacts to one dying. The hubs are watched; the sensors are not. The 2026-09-11 and 2026-10-18 incidents are both this gap.

### 6. The roster is wrong in both directions (F22) — HIGH
One slot that can never work, two working cameras left out. Cheap, and it makes every real event produce less evidence than the hardware is capable of.

### 7. No perimeter beyond three door frames (F1) — HIGH
No window, no glass, no shop side, no back, no roof, and the `maglock` door — a door the access model unlocks by name — has no sensor at all. This is the largest *structural* gap but ranks below the others because it needs hardware and money, and the cheaper items above make the existing hardware tell the truth first.

### 8. The audible alarm is an HTTP call to a Mac mini (F15) — MEDIUM
`siren.video_doorbell_siren` exists and is referenced by nothing. If the Mac is asleep the "alarm" strobes lights silently. Worth fixing, but only after the system reliably notices things.

### 9. 40 % of the automations display as unavailable (F7) — MEDIUM
49 of 124. The working twin is often the `_2`. A human reading the UI cannot tell what is running, which is how a future session automates against a dead entity. Costs operator trust in the surface, not detection coverage directly.

### 10. The NVR clock is 51 minutes off (F23) — LOW
No effect on detection, real effect on evidence in a dispute.

---

## What I could not verify

1. **Whether `camera.cam_larry_s_interior_main` returns HTTP 400 right now.** I did not issue the call. `phoenix_snapshot_cameras.yaml:40-46` documents that retries on a bad NVR channel cause account lockouts, and the task was read-only. My evidence is the 404 on its evidence tile and the repository's own statement that channels 2–4 are empty.
2. **Whether the tiles were rewritten by the 14:16 drill or are stale.** The 51-minute OSD offset is consistent with an NVR clock error, but a stale tile is not excluded, because `camera.snapshot` failures are silent (`continue_on_error: true` with no else branch on the roster path). The `bash -c` fix means the *verifier* now catches missing files; it does not catch files that were written from an old buffered frame.
3. **The physical floor plan.** `door_name` values in the access model are `strike`, `maglock`, `interior`, `apartment`. I have matched three of them to three sensors by friendly name and door name. I have **not** established whether `maglock` is a separate door or a second lock on the front door, so "the maglock door has no sensor" may mean "a door in the path is unsensed" or "one door has one of its two locks unsensed". Both are gaps; they are not the same size. Nothing in the config or the live states disambiguates it, and it needs eyes on the doorway.
4. **Whether `phoenix_intrusion_active` was `on` at any point between 02:14:22 and 11:25:25 on 26 Oct in a way the logbook did not capture.** I read the state change at 23:23:21 and the change at 11:25:25 and nothing between, but there was an HA restart at 02:14:22 and restarts can mask transitions.
5. **The CPU cost claim in P227 §4** (H.265 transcode). I have no process or thermal measurement from the HA host, and the SSH add-on is off, so I cannot get one read-only from here. Not re-tested, therefore not confirmed.
6. **Whether `notify.mobile_app_zabz_waze` resolves.** It is referenced at `access_control.yaml:1742` for the armed-occupancy alert. `notify` services are not entities, so `/api/states` cannot tell me; I would need `GET /api/services`.
7. **Whether the secretary API would accept a real page right now.** I read the handler and the send path, and the SMS record, but I did not POST to `/webhook/ha/security-alert` — that would be an outbound message and needs an explicit per-message instruction, which I do not have.
8. **Anything on the HA host filesystem** beyond what `/local/snapshots/` serves: the `intrusion_<stamp>_*.jpg` files from the 14:03 abort, `/media/phoenix/history`, and the recorder database directly. All would need host access.
