# The record outranks the alarm — what Q1's answer changes

**2026-10-27 · written after the owner answered Q1.** Source: `SECURITY-DISCUSSION.md` Q1 (answer block),
journal `D9373`. The whole of this file is a consequence of one sentence of his:

> *"I want to know every person who came and want a little picture or video of them. I want to know when they
> came, when they left. And very good tracking of everything that ever happened there is more important to me
> even."*

Burglary is still wanted — *"it's a pretty secure neighborhood, I'm not so scared of that"* — but it is second.

---

## 1. What the requirement actually is, stated so it can be tested

The product is an **observation record with four properties**, in this order of importance:

| # | Property | The test that proves it |
|---|---|---|
| O1 | **Every person who enters appears in the record** | For a week, count the people who physically walk in and the people in the record; the second number must not be smaller, and every gap must be explainable by a named camera failure. |
| O2 | **Each one carries a likeness** — a still or a clip, from this event, from the camera that saw it | Sample 20 events across a week, open the image, and confirm it shows *that* person at *that* door at *that* time. A picture of the right moment from the wrong camera fails this test. |
| O3 | **Arrival and departure times are right, and comparable between cameras** | The same door opening, seen by two cameras, must not disagree by more than a second. Sixteen minutes is the measured current disagreement. |
| O4 | **The history is complete and readable months later** | Ask "who came on the 3rd, between 14:00 and 15:00" and get a list with pictures, with no dependence on a camera's local storage. |

`O1` through `O4` are the acceptance tests. Nothing else in this folder is allowed to outrank them any more.

## 2. What already exists, and honestly does not have to be rebuilt

- **The edge record**: a listener on the authority ingests HA events into nine tables via
  `security-listener` → `security-sentinel` → `security-agent` (deployed, in shadow, self-testing 7/7).
  `00-WORKLOG.md`, `20-OPERATIONS.md`.
- **The identity vocabulary**: `30-IDENTITY.md` already defines subject, credential, and *unknown is a correct
  answer*; a keypad event lands with a name on it today (`SECURITY-DISCUSSION.md`, status block).
- **The replay harness**: `corpus/replay-corpus-v1.json` and `security-replay.py` — twelve historical episodes
  plus one synthetic intrusion. This is what makes a change to the recording path provable instead of hopeful.

So this is not a rebuild. It is a change of what is measured, plus the capture path that was never built.

## 3. The measured blockers, each with where it was read

1. **Clocks.** Two cameras are **sixteen minutes** apart; any cross-camera timeline is wrong today
   (`05-LIVE-FINDINGS.md` L4; `from-zabz-tech/reports/R2-cameras.md`). This alone fails O3 and O4.
2. **No picture has ever been stored.** The evidence chain never reached its capture step, and pruning runs at
   fourteen days (`05-LIVE-FINDINGS.md` L5/L6; `OPEN-THREAD-nonblocking-evidence.md`). Fails O2.
3. **A snapshot can return the wrong camera's frame with HTTP 200** — a failure that looks like a success
   (`from-zabz-tech/security-audit-2026-10-26.md` S62–S66). Fails O2, and worse: it fails it silently.
4. **Coverage.** Five physical cameras only — four Dahua channels and the Reolink doorbell; channels 2/3/4 have
   no lens, one channel is dead, and 25 camera entities are mostly substreams, a stale placeholder and a
   channel-fallback duplicate (`05-LIVE-FINDINGS.md` L4, `research/B` §4). Fails O1 at the doors that have no
   camera.
5. **No machine vision.** The estate has none; the Dahua detectors are switched off and 54 detectors have been
   zero for thirty days (`from-zabz-tech/reports/R2-cameras.md`). Without it "every person" depends entirely on
   door edges — a person who walks in behind someone, or through a door with no contact, is invisible.
6. **The company cannot see an event in real time** — `events` and `routing_log` are at 0 rows, because
   `enqueue_job(task_type=)` meets `job_type` and the TypeError is swallowed (`05-LIVE-FINDINGS.md` L6). The
   record still fills through the listener, but nothing downstream is woken by it.

## 4. The build order this forces

1. **One clock.** Make every camera and the HA host agree to the second: NTP on the cameras, verified by reading
   each camera's OSD time against the host clock in the same call, and store **both** timestamps on every frame
   so a wrong clock is visible rather than trusted. Nothing else is worth doing first — a record with wrong
   times is not a record.
2. **Capture on every edge.** For every door contact, keypad event and person detection: one still per camera
   that covers that door, written to the estate store, with a row that carries the event, the camera, the
   offsets, and the sha256 of the file. Verified by opening the image, not by the call returning 200 —
   the wrong-camera defect at S62–S66 is precisely a 200.
3. **Coverage of every entrance.** Name each way a person can physically get in, and for each one say which
   camera sees a face and which sees only a corridor. The gaps are then a shopping list, not a surprise:
   `D17` already prices the contact on the maglock door, the UPS, the glass and a second audible device.
4. **Retention that matches the requirement.** Stills and the metadata rows are small and are kept **forever**;
   video is the expensive part and gets a number once the bitrate is measured (see §5). "Everything that ever
   happened" is affordable as stills-plus-rows; it is not affordable as full-resolution video for years.
5. **A query surface.** The requirement is only met if the answer comes back in seconds: "who came in the last
   thirty days", "what happened on Tuesday at 14:02", "every visit by this person". That is a read over the
   record tables plus the image index — the pieces exist (`schema/01-security-record.sql`), the surface does not.
6. **Only then** the alarm refinements and paging (`D1`–`D5`), which stay as designed.

## 5. The one number I still need to measure, and how I will choose it

Retention for video is a disk number, not a taste number: bytes per hour per camera is unmeasured on this
estate, so any figure quoted now would be invented. The measurement is one camera's segment size over one hour,
multiplied by the cameras that matter, against the free space on the box that holds them. I will pick the
retention from that arithmetic and write it into `D19` rather than asking for a preference on a number he cannot
know either.

## 6. What this does not license

- **No camera at the public hallway beyond what the law allows** — `Q9` is unanswered and this document does not
  pre-empt it.
- **No retention of audio** until `Q9` is answered; New Jersey is one-party for audio and this is a business
  premises with employees.
- **The record is not a substitute for the alarm.** A record tells him after; the alarm is what a customer behind
  a counter needs in the ten seconds that matter. Both are wanted, in this order of *build*, not of *running*.

---

## 7. Measured 2026-10-27 on the live system — the clock, and the picture

Read from ZABZ-TECH through `homeassistant.local`: HA **2025.10.3**, tz `America/New_York`, `GET /api/` **200 in
116 ms**, `GET /api/states` **1,040 entities**, of which **368 are unavailable or unknown (35.4 %)** and **25 are
camera entities** (21 `idle`, 4 `unavailable`). Every still below was fetched with
`GET /api/camera_proxy/<entity>` and its burned-in timestamp read off the image itself.

| what | burned into the picture | host clock at fetch | offset |
|---|---|---|---|
| `camera.cam_front_hallway_main` — Dahua, "Main Entrance" | 2026-10-27 11:30:01 | 12:21:25 | **51 m 24 s behind** |
| the same camera, 23 s later | 2026-10-27 11:30:22 | 12:21:48 | 51 m 26 s behind |
| `camera.cam_larry_s_exit_main_2` — Dahua | 2026-10-27 11:30:03 | 12:21:25 | 51 m 22 s behind |
| `camera.reolink_video_doorbell_poe_clear` — Reolink doorbell | 27/10/2026 11:13:51 | 12:21:25 | **67 m 34 s behind** |

Three things follow. The first **corrects** the prior audit, and correcting it changes the size of the job.

1. **The two Dahua cameras agree with each other to two seconds.** The "sixteen minutes apart" recorded on
   2026-10-26 is real, but it is not scatter between four cameras: the Dahua group shares **one** wrong clock
   (51 m 25 s behind) and the Reolink doorbell has **another** (67 m 34 s behind). 67:34 − 51:25 = **16 m 09 s**,
   which is exactly the audit's figure. So this is **two clock corrections, not five** — and one of the two is the
   doorbell, the camera that sees a face at the entrance at all.
2. **The stills are live, not cached.** The same camera's OSD advanced 21 s across 23 s of real time. The 51-minute
   error is in the camera, so every picture taken today is filed under the wrong minute by an hour.
3. **A picture does come back today, with nothing built.** 166 KB in 2,273 ms (hallway), 317 KB in 2,766 ms
   (Larry's exit), 1.09 MB in 277 ms (doorbell). So `05-LIVE-FINDINGS.md` L5's "no picture has ever been stored" is
   exact only about the **storage path**: the API produces the frame and nothing ever wrote it down. The capture
   step is therefore a *save plus a row*, not a new imaging system — which is a much smaller job than the audit
   implied.

**The shape of the defect this exposes.** The edge rows come from Home Assistant's clock, which agrees with the
host to the second; the pictures come from the cameras, which are 51 and 67 minutes behind. So the record would
say a person arrived at 12:21 and their photograph would say 11:30. Every episode query would be right and every
image would contradict it. That is a record that looks complete and is wrong — the failure this document exists to
prevent, and the reason the clock is step 1 rather than housekeeping.

---

## 8. Scope A, and the coverage it demands (decided 2026-10-27)

He chose **A** of A/B/C: every entrance and every shop/public area; the apartment interior is **not** covered, only
its door from the hallway side; stills and their rows are kept **forever**; video **thirty days**; **no audio** —
New Jersey is one-party for audio and this is a premises with a tenant and employees; the tenant is a named
subject whose entries are *expected*, not suspicious. Journal `D9375`.

### What each camera actually sees — read off the pictures, not the names

Every row below was established by fetching `GET /api/camera_proxy/<entity>` at 2026-10-27 12:21–12:54 local and
reading the frame and the burned-in OSD label.

| entity | OSD label | what the frame shows | the door it can answer for |
|---|---|---|---|
| `camera.cam_front_hallway_main` | "Main Entrance" | **the entrance door itself**, from inside and above: a closed six-panel door dead ahead, the keypad on the left wall, an open leaf blocking the right third | the shop door — **the best face view in the building** (3–4 m, frontal) |
| `camera.cam_larry_s_exit_main_2` | "Deserted House Exit" | the same control room as `cam_deserted_exit_main` — two angles or one duplicated stream, unresolved | **no exit in frame**; the name refers to nothing visible |
| `camera.cam_deserted_exit_main` | "Deserted House Exit" | **the same room** from the opposite corner, including a white door | same room, complementary angle |
| `camera.cam_deserted_interior_main` | "Deserted House inwards" | the repair bench with two staff, the back-room doorway, white double doors | the work area — no exterior door |
| `camera.cam_waiting_room_main` | "IPC" | the public **drop-off / pick-up** door with the LPT sign, from inside and very close | the door every customer uses |
| `camera.reolink_video_doorbell_poe_snapshots_clear` | "Reolink Video Doorbell PoE" | the exterior stairwell, railing and street — the camera faces **away** from the building | the approach, **not** the doorway |
| `camera.cam_larry_s_interior_main` | — | **no still at all: HTTP 500** while the entity reports `idle` | unknown |

### The four gaps this exposes

> **CORRECTED within the hour of first writing this.** The first version of this section said "the doorway itself is
> the blind spot, and it is the door that matters". That was wrong, and it was wrong because I read
> `cam_front_hallway_main` as a hallway when the frame is the **shop door itself, dead ahead from inside, 3–4 m,
> with the keypad on the wall beside it**. The shop entrance has a camera on its threshold and it is the best face
> view in the building. The gaps are elsewhere, and they are four.

1. **The apartment door has no camera on it.** The only remotely-unlockable door in the building — smart lock
   `lock.0x002446fffd0a4705`, contact `external_control_room_door_sensor`, and `script.buzz_in_apartment_door` —
   and **none of the seven stills shows a deadbolt door at all**. Under scope A the apartment interior is out of
   scope but **its door is explicitly in scope**, and today it is unwatched. *Inferred from six frames, not from a
   config file: confirm against the physical layout before buying anything.*
2. **"Larry's exit" is a name with no exit.** `camera.cam_larry_s_exit_main_2` burns `Deserted House Exit` into
   every frame and shows the same control room as `cam_deserted_exit_main`. Whether that is two angles of one room
   or one stream duplicated is unresolved — either way **no exit is in either frame**, so whatever door the name
   refers to is unwatched.
3. **The doorbell sees the approach, not the door.** It looks up the exterior stairwell; its own door is out of
   frame (a white sliver at the extreme left edge). A person coming down the steps is captured; a person standing
   flat at the door is not. It and `cam_front_hallway_main` are complementary rather than redundant — the doorbell
   for who is coming, the hallway camera for the face at the door.
4. **`cam_larry_s_interior_main` is dead and reports healthy** — HTTP 500 on `_main`, `_sub_4` and `_sub_2_2`,
   while the state machine says `idle`. Liveness must be established by *the bytes arriving*, never by an entity's
   state. This is the same shape as the estate's most expensive recurring defect: a failure that reports success.

### The entity trap that decides whether a picture is evidence

The same physical doorbell, at the same instant, produced two different timestamps: the high-resolution
`snapshots_clear` entity burned **11:47:03** while the 640×480 `fluent` substream burned **11:42:04** — five
minutes apart, because the substream serves a lagging frame while the snapshot entity is current. So *which entity
inside Home Assistant you capture from* is part of the evidence chain, not an implementation detail: capture from
the snapshot/clear entity, and keep the OSD time beside the file.

### The record cannot hold a picture yet

`grep -E 'image|file|path|snapshot|photo|jpeg|media'` over `schema/01-security-record.sql` returns **nothing**: the
nine tables have no column that can reference an image. So O2 needs a tenth table before it can pass — an evidence
row keyed to the event, carrying the file's path, its sha256, the camera, the host capture time **and** the OSD time.

### What today's record already proves, and cannot answer

The record is live: `security_event` holds **2,800 rows** from 2026-10-26T21:53:20Z to 2026-10-27T16:53:30Z,
`security_decision` 9, `subject` 5, `credential` 5, and `entry_event` 3 — of which the newest is a real keypad
press at **`shop_door`, 2026-10-27T14:33:15Z, with no subject and confidence 0.0**. A person entered the shop
today, the record knows the door and the minute, and it cannot say who and has no picture. That is precisely the
gap scope A exists to close, in one row.

### The clock state, as of this measurement

- **Dahua group** (5 working streams): **51 m 25 s behind**, agreeing with each other to 2 s → **one** correction.
- **Reolink doorbell**: **67 m 26–34 s behind**, stable across 33 minutes → **one** correction.
- Home Assistant's own edge timestamps are right to the second, so today the record's times and its pictures
  disagree by up to an hour.

**Independently reproduced** the same afternoon from a second machine (ZABZ-YOGA, over the tailnet at
`100.85.153.96:8123`, read-only): Dahua **−51 m 27 s**, doorbell **−67 m 37 s**, and the frames shown live by
re-fetching — the OSD advanced **82 s in 82 s** of wall time. Two machines, two paths, the same two offsets to
within seconds, so this is a property of the devices and not of the reader.

Both corrections live in the devices' own web interfaces, and this box has no shell on the Home Assistant host
(port 22 and port 445 both closed from ZABZ-TECH; only 8123 answers), and no camera credential exists in any
`.env` on this machine. That is the one thing standing between the record and a correct timestamp.
