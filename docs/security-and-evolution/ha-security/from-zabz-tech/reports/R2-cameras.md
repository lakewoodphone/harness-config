# R2 — Cameras: what they see, what they classify, what vision exists

**LOCAL (zabz-tech)** — Windows, `pwsh`. All Home Assistant reads went over the REST API from this host
(`http://homeassistant.local:8123`) using the bearer token in `personal-secretary-mvp/.env`. Nothing was
posted, no service was called, no file on HA was written. `camera_proxy` is a read-only GET that writes
nothing; the empty NVR channel was probed **once, as instructed**, and never retried.

Read at the top of this session, not remembered:

| Fact | Where I read it |
|---|---|
| HA version **2025.10.3**, `state: RUNNING`, `config_dir: /config` | `GET /api/config` |
| **1,036** entities | `GET /api/states` → `.Count` |
| **229** loaded components | `GET /api/config` → `.components` |
| **25** camera entities | `/api/states`, domain `camera` |
| Recorder `purge_keep_days: 30`, `commit_interval: 30`, two excluded entities | `config/configuration.yaml:177-191` |

---

## 0. Two premises in the brief are wrong, and they change the answers

**(a) The recorder holds ~28 days, not ~1.8 days.** `configuration.yaml:177` sets `purge_keep_days: 30`.
Measured on `binary_sensor.video_doorbell_person` with isolated single-day `/api/history/period` calls:
real rows on the days ending −5 d (93 points), −8 d (42), −11 d (135), −14 d (125), −17 d (343), −20 d (399),
−24 d (217), −28 d (143), and **0 points at −32 d**. So "has it ever fired" is answerable over a month, not
a day — and I answered it over a month (section 3).

**(b) `camera.cam_larry_s_exit_main_2` is not a dead channel.** I fetched it once: **HTTP 200, 2560×1440,
300,843 B**, and the frame's burned-in OSD reads **"Deserted House Exit"** — it is the main-room camera.
`cams.yaml:130-134` and finding S51 both say this entity points at empty NVR channel 3 and "can never produce
a picture". That is false as measured. Only `cam_larry_s_interior_main` is dead (HTTP 500). Details and the
code path that makes this dangerous are in section 8.

---

## 1. Every camera entity, with the resolution it actually delivers

Measured by fetching `GET /api/camera_proxy/<entity>` and parsing the JPEG SOF marker myself (dimensions are
read from the bytes, not from the name). One attempt per entity, no retries.

### Standalone — Reolink Video Doorbell PoE, `192.168.50.231`

| Entity | State | Stream role | Delivered | Bytes | Pixels |
|---|---|---|---|---|---|
| `camera.reolink_video_doorbell_poe_clear` | `idle` | main / "clear" | **2560×1920** | 605,216 | **4,915,200** |
| `camera.reolink_video_doorbell_poe_snapshots_clear` | `idle` | snapshot API | **2560×1920** | 591,797 | **4,915,200** |
| `camera.video_doorbell_fluent` | `idle` | low-latency "fluent" | **640×480** | 48,185 | **307,200** |

### Dahua NVR `192.168.50.170` — 18 live entities, 6 config groups

Every one of the 12 probed non-Larry Dahua entities returned **2560×1440 (3,686,400 px) `image/jpeg`**.
`_main`, `_sub_4` and `_sub_2_2` are **not** different resolutions:

| Group (config entry) | Entities | State | Delivered still | Bytes (main / sub_4 / sub_2_2) |
|---|---|---|---|---|
| Deserted Exit | `cam_deserted_exit_main`, `_sub_4`, `_sub_2_2` | all `idle` | 2560×1440 | 315,044 / 315,039 / 315,165 |
| Deserted Interior | `cam_deserted_interior_main`, `_sub_4`, `_sub_2_2` | all `idle` | 2560×1440 | 251,391 / 327,816 / 220,279 |
| Front Hallway | `cam_front_hallway_main`, `_sub_4`, `_sub_2_2` | all `idle` | 2560×1440 | 149,583 / 149,350 / 149,264 |
| Waiting Room | `cam_waiting_room_main`, `_sub_4`, `_sub_2_2` | all `idle` | 2560×1440 | 205,862 / 206,461 / 206,595 |
| Larry's Exit | `cam_larry_s_exit_main_2` | `idle` | 2560×1440 | 300,843 |
| Larry's Interior | `cam_larry_s_interior_main` | `idle` | **HTTP 500, 0 B, no picture** | — |

The three Deserted Exit stills agree within **126 bytes of each other** (315,039–315,165) — the same scene,
the same camera, moments apart. Deserted Interior's three differ by up to 30 % in bytes while being
identical in pixels; that is scene change between probes, not a resolution difference. **Every still is
2560×1440.**

The other four Larry's `_sub_*` entities (`larry_s_exit_sub_4`, `larry_s_exit_sub_2_2`, `larry_s_interior_sub_4`,
`larry_s_interior_sub_2_2`) were **deliberately not probed**: the repo warns that retries against the empty
channel lock the NVR account, so the empty channel got exactly one probe (`larry_s_interior_main`, HTTP 500)
and nothing more. Their stills are therefore unmeasured, not measured-and-fine.

**Why the suffix does not matter for a still.** The Dahua component's snapshot routine hardcodes the mainstream: `config/custom_components/dahua/client.py:88-89` builds
`/cgi-bin/snapshot.cgi?channel=N` and `…&subtype=0`. The subtype only governs the RTSP *live* stream
(`client.py:46-58`, `rtsp://…/cam/realmonitor?channel=N&subtype=S`). So `cams.yaml:11-19`'s
"subtype 0 = 2560×1440, subtype 1 = 704×480" is correct **about live video** and irrelevant **to every
evidence still this system writes** — which is the thing that matters here.

### Four further camera entities exist that are not cameras

| Entity | State | Reality |
|---|---|---|
| `camera.cam_waiting_room_main_stale_placeholder` | `unavailable` (`restored: true`) | ghost of a deleted config entry — `GET` → **404** |
| `camera.cam_waiting_room_sub` | `unavailable` (`restored: true`) | ghost — **404** |
| `camera.cam_waiting_room_sub_2` | `unavailable` (`restored: true`) | ghost — **404** |
| `camera.cam_waiting_room_sub_3` | `unavailable` (`restored: true`) | ghost — **404** |

They are restored-state placeholders. `restored: true` in the attributes is the tell. Four of the 25 camera
entities cannot produce a picture and never will.

### The snapshot tiles, measured the same way

`/local/snapshots/` maps to `/config/www/snapshots/`, which is **gitignored** (`.gitignore:69`), so the repo
cannot show it — I measured the live files over HTTP instead.

| Tile | HTTP | Delivered | Bytes | Written (Last-Modified, GMT) |
|---|---|---|---|---|
| `latest_person_doorbell.jpg` | 200 | **2560×1920** | 542,147 | 26 Oct 18:28:41 |
| `latest_person_hallway.jpg` | 200 | **2560×1440** | 163,737 | 26 Oct 18:28:48 |
| `latest_person_waiting_room.jpg` | 200 | **2560×1440** | 181,098 | 26 Oct 18:28:54 |
| `latest_intrusion_doorbell.jpg` | 200 | **640×480** | 55,143 | 26 Oct 18:16:39 |
| `latest_intrusion_front_hallway.jpg` | 200 | 2560×1440 | 149,503 | 26 Oct 18:16:41 |
| `latest_intrusion_control_room_interior.jpg` | 200 | 2560×1440 | 298,175 | 26 Oct 18:16:41 |
| `latest_intrusion_control_room_exit.jpg` | 200 | 2560×1440 | 315,554 | 26 Oct 18:16:29 |
| `latest_intrusion_waiting_room.jpg` | 200 | 2560×1440 | 213,689 | 26 Oct 18:16:36 |
| `latest_intrusion_larry_interior.jpg` | **404** | — | 0 | — |
| `latest_strike_unlock_doorbell.jpg` | **404** | — | 0 | — |
| `latest_hallway_periodic_front_hallway.jpg` | **404** | — | 0 | — |
| `latest_doorbell_ring_doorbell.jpg` | 200 | 2560×1920 | 580,202 | **12 Oct 21:29:46 — 14 days stale** |
| `latest_doorbell_ring_hallway.jpg` | 200 | 2560×1440 | 149,441 | 12 Oct 21:29:53 |
| `latest_doorbell_ring_waiting_room.jpg` | 200 | 2560×1440 | 201,183 | 12 Oct 21:29:58 |
| `latest_control_room_open_doorbell.jpg` | 200 | 2560×1920 | 812,686 | 26 Oct 18:24:28 |
| `latest_control_room_open_hallway.jpg` | 200 | 2560×1440 | 152,043 | 26 Oct 18:24:36 |
| `latest_snapshot_waiting_room.jpg` | 200 | 2560×1440 | 205,744 | 26 Oct 18:37:05 |
| `latest_outside_door_doorbell.jpg` | 200 | 2560×1920 | 678,630 | 26 Oct 18:31:16 |

Two things fall out. The **intrusion** doorbell tile is 640×480 while the **person** doorbell tile from the
same camera, same day, is 2560×1920 — S50 confirmed independently, and the pixel ratio is **16.0×**
(4,915,200 ÷ 307,200). And the `doorbell_ring_*` family has not been written since **12 October**, so that
path is dead rather than idle.

---

## 2. Duplicates: same physical camera, more than one entity

### The doorbell — confirmed, and it is exactly 16× fewer pixels

`camera.video_doorbell_fluent` and `camera.reolink_video_doorbell_poe_clear` are **one camera**. I pulled both
and looked at them: identical lens, identical framing (wrought-iron fence, concrete stairwell, neighbouring
house), identical burned-in OSD `Reolink Video Doorbell PoE`, OSD timestamps within seconds. Dimensions:
**640×480 = 307,200 px** versus **2560×1920 = 4,915,200 px** — a factor of **16.0**.

It is not a fault. The Reolink integration publishes three camera entities per device: the low-latency
"fluent" stream (what a live tile should use — cheap to decode), the "clear" main stream, and a "snapshots"
entity on the still API. **The two "clear" entities are the same 2560×1920 frame.** The bug is not the
duplication; it is that the doorbell **evidence** path uses the 640×480 one while the **parcel** path uses the
2560×1920 one (`cams.yaml:67` also puts the fluent stream on the wall).

### The Dahua cameras — three entities each, identical stills

Each working Dahua config entry produces `_main`, `_sub_4` and `_sub_2_2`. Per `cams.yaml:20-24` these are
unique_id collision suffixes from the integration's scheme change (MD5 hash → NVR serial `8C03EA3PAZC4C2D`).
`_sub_4` is the *live* subtype-1 stream; `_sub_2_2` was documented as having no stream behind it. For
**stills** all three return the identical 2560×1440 frame, because of the hardcoded `subtype=0` above.
So the estate has **18 Dahua camera entities covering 4 physical cameras**, and 20 of the 25 camera entities
are noise or ghosts for evidence purposes.

### Larry's — a duplicate of the main room wearing a different room's name

`cam_larry_s_exit_main_2` returned a 2560×1440 frame whose OSD says **"Deserted House Exit"**, visually the
same composition as `cam_deserted_exit_*`. So the estate has **5 physical cameras**, not the 5-plus-two-dead
that `cams.yaml:107-112` describes:

1. Deserted House Exit — main room, colour
2. Deserted House inwards — repair bench, colour
3. Main Entrance — vestibule with keypad, **monochrome**
4. IPC (unnamed) — drop-off/pick-up door and storage rack, colour
5. Reolink Video Doorbell PoE — outside the door, colour

---

## 3. What the cameras detect by themselves — and whether it has ever fired

**63** `binary_sensor.cam_*` entities exist: **54 live** (6 config groups × 9 detectors) plus **9
restored-`unavailable` ghosts** of the deleted Waiting Room entry. Nine detector families per camera:

| Detector | What it is meant to detect | Fired in 29 retained days? |
|---|---|---|
| `smart_motion_human` | Dahua SMD/IVS: a **person**-shaped object | **0** |
| `smart_motion_vehicle` | Dahua SMD/IVS: a **vehicle**-shaped object | **0** |
| `cross_line_alarm` | tripwire — an object crossing a drawn line (direction-aware) | **0** |
| `cross_region_detection` | intrusion into a drawn polygon | **0** |
| `motion_alarm` | classic video motion detection (pixel change) | **0** |
| `alarm_local` | the camera's own local alarm-output relay | **0** |
| `video_loss` | video signal lost | **0** |
| `video_blind` | lens masked or covered | **0** |
| `audio_mutation` | sudden audio-level change | **0** |

**Measurement.** `/api/history/period` over **30 consecutive 24 h chunks**, filtered to the **54 live**
detectors, `minimal_response`:

```
chunks  0..28  (2026-09-27 .. 2026-10-26)   series=54  points=54  ON=0   in every chunk
chunk   29     (2026-09-26 .. 2026-09-27)   series=0   points=0   ON=0   <- retention edge
TOTAL ON points: 0.   Chunks containing any ON point: 0 of 30.
```

`points=54` in **every** chunk is the control that matters: 54 entities, one point each, changing never. If
the query had been filtered or the entities excluded from the recorder, `series` would have been 0 — as it
correctly was in chunk 29, past the retention edge.

**The negative is real, and this is what proves it.** In the same query, same recorder, same window,
`binary_sensor.video_doorbell_person` fired **99 times in 72 h** (203 state points), `video_doorbell_motion`
3 times, `video_doorbell_visitor` 3 times. The recorder captures camera-triggered events perfectly well. It
captures none from the Dahua because there are none.

**And the reason is visible in the entity states.** Nothing is broken in HA — the detection is switched off
upstream:

```
switch.cam_deserted_exit_motion_detection_2        off    switch.cam_deserted_exit_smart_motion_detection        off
switch.cam_deserted_interior_motion_detection_2    off    switch.cam_deserted_interior_smart_motion_detection    off
switch.cam_front_hallway_motion_detection_2        off    switch.cam_front_hallway_smart_motion_detection        off
switch.cam_waiting_room_motion_detection_2         off    switch.cam_waiting_room_smart_motion_detection         off
switch.cam_larry_s_exit_motion_detection_2         off    switch.cam_larry_s_exit_smart_motion_detection         off
switch.cam_larry_s_interior_motion_detection_2     off    switch.cam_larry_s_interior_smart_motion_detection     off
```

while `switch.cam_*_event_notifications` is **`on`** on all six — the integration is subscribed and would
record an event. So the two-zone presence architecture in `presence_architecture.yaml` is, on its camera half,
**a detector that has been switched off at the camera**, dressed as one that is running. This is the
mechanism behind S57, and it is a switch, not a hardware limit. Turning these on is a configuration change
with a real cost: with `motion_alarm` enabled these become 24/7 pixel-change emitters on a Pi recorder.

`video_loss` never firing is its own finding: `cam_larry_s_interior_main` returns HTTP 500 and has **no
picture at all**, yet its `video_loss` sensor has been `off` for 29 days.

---

## 4. Is there any real machine vision on this estate?

### No. There is none, anywhere.

This is the most important answer in this round, so here is the whole search and all of it is negative.

**Loaded integrations** — `GET /api/config` → 229 components. The `image_processing` domain is **absent**:
not `image_processing` itself, and not a single `<platform>.image_processing`. That is the domain Home
Assistant uses for *every* image classifier — Facebox, `tensorflow`, `doods`, `deepstack`, `seven_segments`,
`qrcode`, `openalpr`. With the domain unloaded, no classifier can exist even in principle. Also absent by
name: `frigate`, `doods`, `deepstack`, `codeproject_ai`, `tensorflow`, `opencv`, `yolov*`, `coral`,
`edgetpu`, `rekognition`, `face_recognition`, `insightface`.

**Entities** — 1,036 entities across 32 domains. There is no `image.` domain at all. Nothing in the estate
consumes a frame and emits a label.

**Custom components** — `config/custom_components/` contains exactly 7:
`alexa_media`, `bermuda`, `browser_mod`, `dahua`, `hacs`, `keymaster`, `phoenix_access_manager`. None
classifies images. (`dahua` is the camera integration; `bermuda` is BLE trilateration.)

**Add-ons** — I could not list the supervisor directly (that needs a supervisor token, not the HA token), so
I enumerated the installed add-ons from the `update.*` entities, which the supervisor creates one of per
add-on: `advanced_ssh_web_terminal`, `mosquitto_broker`, `file_editor`, `zigbee2mqtt`, `cloudflared`,
`esphome_device_builder`, `network_ups_tools`. Plus core, OS and supervisor updates. **No Frigate. No
CodeProject.AI. No DeepStack. No DOODS. No vision add-on of any kind.**

**Repo-wide text search** for `frigate|deepstack|codeproject|doods|tensorflow|opencv|yolo|image_processing|coral|edgetpu|rekognition|face_recog|insightface`
across `ha-config` returned only false positives — the CSS colour `coral`, and minified vendor JavaScript.

So: every instance of the word "detection" in this system means one of two things, and neither is machine
vision on this estate.

1. **Inference running inside the camera.** The Reolink doorbell classifies person / vehicle / pet / visitor
   on its own silicon and reports them as `binary_sensor.video_doorbell_*`. That is genuine edge AI and it
   works — 99 person firings in 72 h. The Dahua cameras expose the same class of thing
   (`smart_motion_human`, `smart_motion_vehicle`, `cross_line`, `cross_region`) and it is **switched off**.
2. **Cheap non-AI heuristics** — door contacts, PIR, pixel-difference motion.

Nothing on this estate can answer "is that the owner", "is there a parcel", "how many people", or "which way
did they go". The existing system does not detect an intruder; it detects a door opening while the
`everyone_away` flag is set (S52).

---

## 5. Night and low light

**What the hardware has.** Both camera families are IR-capable and IR is enabled on the doorbell:

- `switch.video_doorbell_infrared_lights_in_night_mode` = **`on`** — IR illuminators are enabled for night.
- `select.video_doorbell_day_night_mode` = **`auto`**.
- `sensor.video_doorbell_day_night_state` = **`day`** — and it read `day` in **every** retained sample over
  3 days (4 points), never once `night`. Either the doorbell genuinely stayed in day mode through three
  nights, or this sensor is not tracking. It cannot be used as evidence of anything.
- Dahua: `light.cam_*_infrared_2` = **`off`** on all six groups, and `light.cam_*_illuminator` = **`off`** on
  all six, in every retained sample over 3 days — **not one state change in 72 h**. An entity that never
  changes carries no information about the illuminator. Do not trust it.

**What they actually deliver at night — and I can show you, by accident.** `camera.cam_front_hallway_*`
(OSD "Main Entrance") is delivering a **monochrome** frame at 13:52 in the afternoon: evenly lit, no colour,
no hot spots, the characteristic look of an IR-lit sensor in night mode. So for that camera the 03:00 output
is already visible now, in daylight, and it is **usable for presence, silhouette and movement, and useless
for colour** — clothing colour, vehicle colour, and skin tone are all gone.

The other three Dahua cameras return **colour** at the same moment, which means they see enough visible light
to stay in day mode; at 03:00 they will switch to their own IR, and I have no frame from them in the dark.

**Measured contrast, from the same delivery:** the doorbell (colour, 2560×1920) captured the courier at
13:21:03; the Main Entrance camera (monochrome, 2560×1440) captured the same courier with the same parcel at
13:37:21. One is colour, one is not, at the same doorway, seconds apart in reality.

**What would settle 03:00 properly**, in order of cost:
1. Have the existing snapshot automation write one tile per camera at a fixed 03:00 — one automation, no new
   hardware, and it produces the artefact instead of an argument.
2. Read each camera's Day/Night setting on the NVR itself (Dahua: Setup → Camera → Conditions → Day/Night;
   Reolink: Display → Day/Night), rather than trusting `light.*_infrared`, which demonstrably does not
   reflect reality.
3. Check whether `sensor.video_doorbell_day_night_state` ever leaves `day`. It has not in 3 days, so treat it
   as broken until it does.

---

## 6. The honest ceiling, per capability

Grounding facts: the compute is a **Raspberry Pi** (`raspberry_pi`, `rpi_power` components loaded;
`configuration.yaml:161-165` reasons about the SD card and `mmcblk0p8`). There is **no GPU and no
accelerator** on the estate. Source stills are 2560×1440 (3.69 Mpx) and 2560×1920 (4.92 Mpx).

**The one hard pixel measurement I can offer.** In `latest_person_doorbell.jpg` (2560×1920) a real visitor
fills roughly **310 px of head height** — her hair spans about 185 px in the 1512-px preview, scaled by 1.693.
That is comfortably above the ~80–120 px interpupillary distance a modern face-recognition model needs. **The
pixels are sufficient. The geometry is not:** in that same frame she is at the extreme left edge, in profile,
half out of frame, because the doorbell sits at the bottom of a stairwell looking outward at the yard. A
recogniser fed this would get a profile of a face leaving the frame.

| Capability | Verdict | Why |
|---|---|---|
| **Person vs animal** | **Possible now, doorbell only, no GPU** | Already done in-camera: `binary_sensor.video_doorbell_person` (99 firings/72 h) and `_pet` (0 firings — `number.video_doorbell_ai_pet_sensitivity` = 0, i.e. disabled, not broken). Dahua equivalent exists and is switched off. |
| **Vehicle** | **Possible now, no GPU** | `binary_sensor.video_doorbell_vehicle` exists; 0 firings because `ai_vehicle_sensitivity` = 0 *and* the view is a courtyard. Sensitivity is the only change. |
| **Face identification** | **Needs a GPU box, plus a geometry fix, plus your decision** | Pixel count is adequate (head ≈ 310 px) but the doorbell's sightline gives a profile at the frame edge, and **all four** Dahua views are mounted high in a corner looking down — the two frames I measured put the bench and the vestibule floor in the centre and a standing head near the top edge. Needs: a recognition service (GPU or cloud), a camera at face height at the door, and an explicit decision from you on storing biometrics. |
| **Person count** | **Needs a GPU box** | No camera exposes a count. Dahua NVRs support people counting, but nothing in this estate surfaces it — I found no entity, no switch and no service for it in 1,036 entities. |
| **Direction of travel** | **Needs no new camera and no GPU — but is impossible today** | The doorbell looks *out* and Main Entrance looks *in* at the same doorway, so ordering two detections gives in/out. That is a two-sensor ordering problem, not a vision problem. It cannot work until the clocks agree: the same delivery is stamped **13:21:03** on the doorbell and **13:37:26** on a Dahua — **16 m 23 s apart**. Fix the clocks and this capability is free. Otherwise it needs cross_line IVS enabled on the NVR. |
| **Loitering** | **Needs a GPU box, or NVR-side IVS** | Requires dwell time per tracked object. The Dahua `cross_region`/`cross_line` IVS can do duration rules on the NVR, but nothing in HA can currently arm or read it — the switches are off and there is no duration control exposed. |
| **Package vs person** | **Needs a GPU box. Not possible on this hardware as configured.** | Measured counter-example: the courier in `latest_person_doorbell.jpg` is holding a large cardboard box, and the camera's own classifier called it **person**. No camera here has a parcel class. This is the single capability that most needs a real vision layer, because the business is packages. |

Read that table as: two of seven are free today (person-vs-animal, vehicle — both already in the doorbell),
one is free after a clock fix (direction), and four need a GPU box. Nothing needs a new camera except face
identification, which needs a re-aim as well.

---

## 7. Which camera the evidence roster should use, with the pixels that justify it

| Role | Use this entity | Pixels | Delivered | Replaces |
|---|---|---|---|---|
| **Doorbell** | `camera.reolink_video_doorbell_poe_clear` | **4,915,200** | 2560×1920 | `camera.video_doorbell_fluent` at **307,200** (640×480) — **16.0× fewer** |
| **Hallway / entry** | `camera.cam_front_hallway_main` | **3,686,400** | 2560×1440 | already used, keep |
| **Control room** | `camera.cam_deserted_interior_main` | **3,686,400** | 2560×1440 | already used, keep |
| **Waiting room** | `camera.cam_waiting_room_main` | **3,686,400** | 2560×1440 | already used, keep |
| **Exit** | `camera.cam_deserted_exit_main` | **3,686,400** | 2560×1440 | already used, keep |

**Two entities to remove from the roster, and they are not the same fault:**
- `cam_larry_s_interior_main` — **HTTP 500, no picture.** This is the genuine dead channel (`latest_intrusion_larry_interior.jpg` is the only 404 among the intrusion tiles). Removing it costs nothing.
- `cam_larry_s_exit_main_2` — **HTTP 200, and it shows the main room.** It is not a dead channel and it is
  not "Larry's exit"; it is a second view of `cam_deserted_exit_main`. Keeping it in the roster does not lose
  a picture, it **relabels one** — see section 8.

**Use `_main`, not `_sub_4` or `_sub_2_2`, for evidence stills.** All three deliver the identical
2560×1440 frame (section 1), so there is no pixel argument; the argument is that `_main` is the entity whose
name is not a unique_id collision artefact, and `_sub_2_2` is the one the repo documents as stream-less. For
the **live wall**, leave `_sub_4` alone — that is the entity with a real subtype-1 RTSP stream behind it
(`cams.yaml:20-24`) and changing it would cost Pi CPU for no evidence gain.

---

## 8. Evidence-integrity findings that came out of the measurements

**(i) Two cameras disagree about when the same person arrived, by 16 minutes.** The `latest_person_*` tiles
are written by one automation run, seconds apart. The three tiles I opened are the **same courier with the
same parcel**:

| Tile | OSD timestamp | File write (GMT) |
|---|---|---|
| `latest_person_doorbell.jpg` | `26/10/2026 13:21:03 MON` | 18:28:41 |
| `latest_person_hallway.jpg` | `2026-10-26 13:37:21` | 18:28:48 |
| `latest_person_waiting_room.jpg` | `2026-10-26 13:37:26` | 18:28:54 |

A matched pair captured within seconds is stamped **16 m 18 s apart** (doorbell → hallway) and **16 m 23 s**
(doorbell → waiting room). Against real local time (14:44 when I measured), the Reolink is about **67 minutes
slow** and the Dahua NVR about **51 minutes slow**. S17 recorded
"two camera clocks, both wrong, sixteen minutes apart"; this is that, measured again with a same-subject
control. Consequence: any cross-camera timeline of an incident is wrong by sixteen minutes, and every
timestamp on every piece of camera evidence is wrong by the better part of an hour.

**(ii) A still named for one room can contain another room.** `config/custom_components/dahua/client.py:74-92`
builds a candidate list and walks it:

```python
channel_candidates = [channel_number]
... alt_channel = channel_number - 1 ...  fallback_channel in (1, 0)
urls_to_try.append("/cgi-bin/snapshot.cgi?channel={0}".format(candidate))
urls_to_try.append("/cgi-bin/snapshot.cgi?channel={0}&subtype=0".format(candidate))
urls_to_try.append("/cgi-bin/snapshot.cgi")          # no channel at all
```

So if the configured channel has no camera, the client falls back to channel 1, then 0, then throws the
channel parameter away entirely. **On an NVR, the channel-less call returns the first channel's frame.** Which
means a still written under the name of a camera that does not exist can silently be a picture of a camera
that does — with no error, because HTTP 200 came back.

I cannot tell from outside which of two things made `cam_larry_s_exit_main_2` return the main room: a second
config entry genuinely pointed at channel 1, or this fallback substituting channel 1's frame for an empty
channel. **Both produce exactly what I measured**, and `.storage/core.config_entries` is not in the repo
checkout, so the channel numbers are not readable from here. What would settle it: read the Dahua config entry
for that entity in the HA UI (Settings → Devices & Services → Dahua → the Larry's Exit entry → its channel),
or simply re-aim/remove it either way. This is worth settling because the difference is "a redundant view" versus
"evidence that lies", and the code path makes the second one possible for any empty channel — including
future ones.

**(iii) Names do not describe what the cameras watch.** From the burned-in OSD on the frames themselves:
"Waiting Room" is an OSD-less Dahua reading `IPC` (never named) watching the **drop-off / pick-up door and a
storage rack**; "Front Hallway" reads **"Main Entrance"**; "Control Room" is burned in as **"Deserted House
Exit"** and **"Deserted House inwards"**. `cams.yaml` warns that entity ids are mangled on purpose; the OSD
shows the *room* labels are mangled too. Do not assign a role from an entity name.

**(iv) The intrusion doorbell tile is the 16×-worse entity, and three roster tiles do not exist.** Confirmed
independently of S50 and S51: `latest_intrusion_doorbell.jpg` is 640×480 while the parcel path from the same
camera is 2560×1920; `latest_intrusion_larry_interior.jpg`, `latest_strike_unlock_doorbell.jpg` and
`latest_hallway_periodic_front_hallway.jpg` are all **404**.

---

## 9. What I could not verify, stated plainly

- **The live RTSP resolution.** Every number above is a **still**. `cams.yaml:11-19` claims 2560×1440 main /
  704×480 sub for live video, verified there against go2rtc's producers on 2026-10-06. I did not re-verify it:
  `go2rtc` on port 1984 **refused the connection** from this host, so the live stream profile is unmeasured
  here. My stills neither confirm nor contradict it — they are a different code path.
- **NVR channel numbers per entity.** `.storage/` is not in the repo checkout, and the camera entity
  attributes carry only `id: "None"`, `integration: dahua`, `supported_features: 2` — no channel.
- **A 03:00 frame from any camera.** Section 5 says what would produce one.
- **The live add-on list from the supervisor API** — enumerated from `update.*` entities instead (section 4),
  which names every add-on the supervisor manages.

## 10. Bottom line for the redesign

The cameras are good enough. **Four 2560×1440 views — three in colour, one monochrome in IR — plus a
2560×1920 doorbell, all working, all reachable, all free to read** — that is a real sensor estate and it does
not need replacing.

What is missing is not hardware and not pixels. It is three things, in this order:

1. **Nothing classifies a frame.** No `image_processing` domain, no vision add-on, no accelerator. Every
   claim about "detection" today is either in-camera edge AI on the doorbell (which works) or a detector
   that is switched off (all 54 of them, 29 days, zero events).
2. **The clock is wrong by an hour and the cameras disagree with each other by sixteen minutes**, which
   breaks cross-camera reasoning before any vision layer exists to do it.
3. **The evidence path points at the 16×-worse doorbell entity and at three tiles that 404.**

Fix 2 and 3 first: they are configuration, they cost nothing, and they make the existing cameras worth
something. Then, if you want parcel-vs-person or face identification, that is a GPU box and a decision from
you — not a camera.
