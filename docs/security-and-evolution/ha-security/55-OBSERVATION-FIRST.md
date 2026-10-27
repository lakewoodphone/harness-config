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

---

## 9. The recording hardware, and why the clock is still wrong (2026-10-27)

### What the devices are — read from Home Assistant's device registry, not guessed

| device | address | identity | notes |
|---|---|---|---|
| **Recorder / NVR** | **`192.168.50.170`** | `DHI-NVR4108-8P-4KS2-L`, serial `8C03EA3PAZC4C2D`, firmware `4.003.0000000.1.R` build 2024-05-15 | **every camera channel is a channel on this one box** (`_1`, `_2`, `_4`, `_5`, `_6`); it holds the disk, the retention, and the clock the cameras follow |
| Reolink doorbell | `192.168.50.231` | `Reolink Video Doorbell PoE`, firmware `v3.0.0.4662_2508071283`, serial `952700096CU6ET56` | its own clock, 67 m behind, independent of the NVR |
| Two "Generic RTSP" entries | `192.168.50.170` | sw `1.0` | `Cam Larry's Exit` and `Cam Waiting Room` are RTSP pulls, not integration channels — which is why they behave differently |

Two Dahua web UIs answer on the LAN (`192.168.50.170` and `192.168.50.95`), both 2021-generation HTML with a
`logonInfo`/`g_Lan` block; the NVR serves **HTTPS on 443 with a self-signed certificate** and redirects plain HTTP to
it. A 254-host sweep of 80 and 8000 found only four web devices on the whole network: the router (`.1`), a Shelly
(`.103`), the Reolink (`.231`) and those two Dahua hosts. **The cameras themselves are not individually addressable
from this LAN** — they sit behind the NVR's own 8-port PoE switch, which is why fixing the NVR fixes all channels at
once and why there is no per-camera web UI to log into.

### What the credential did, exactly

The owner supplied `admin` with a password on 2026-10-27. Result, stated plainly:

- **Reolink (`.231`): rejected, in its own words — `{"cmd":"Login","code":1,"error":{"detail":"password wrong",
  "rspCode":-502,"auth_warning_info":{"remain_times":10}}}`.** One attempt consumed; ten reported remaining.
- **NVR (`.170`): the endpoint is alive and issues a proper digest challenge** —
  `POST /RPC2_Login` returns `realm: "Login to 39b7c619…"`, a fresh `random`, `qop: auth` and an `opaque`. The
  challenge-response (`md5(user:random:md5(user:realm:pass))`, `loginType: Direct`, with the cookie jar carried
  across both calls) **did not complete**: the NVR answered
  `{"error":{"code":268632079,"message":"Component error: login challenge!"},"result":false}`, which is the same
  generic error it gives for any login it will not accept — **it does not distinguish a wrong password from a wrong
  handshake**, which is exactly what makes it unsafe to keep guessing at.

**Why I stopped rather than trying again.** A Dahua NVR locks an account after a handful of failures. The recorder
holds the only copy of the video evidence, and the owner is in the shop working right now; locking the admin account
on it to save a few minutes would be a self-inflicted outage on the one device that records. Two attempts on the NVR
and one on the Reolink is where this stops without a human.

### The rule this pays for

**Verify a device credential against the device whose error names the fault, first.** The Reolink says
"password wrong" and shows a remaining-attempts counter; the Dahua says "login challenge" for everything. So the
Reolink is the honest oracle and the Dahua is the dangerous one, and the order of testing should have been the
reverse of the order of value. Test on the device that cannot lock you out, or that tells you the truth, and stop
after one failure on the one that can.

### Why the API login cannot be completed from a script — read out of the device's own web client

After a dedicated account (`zabz`, group `admin`) was created in the NVR's UI, the login still failed with the same
`Component error: login challenge!`. So I read the recorder's own web application instead of guessing further:
`https://192.168.50.170/static/js/vendors~project.08638de9.chunk.js` (4.4 MB) contains the login code, and it settles
the question.

**The digest algorithm was right.** Their `Default` branch is:

```js
var u = hex_md5(`${userName}:${realm}:${password}`);   // HA1
return { pwd: hex_md5(`${userName}:${random}:${u}`) }; // user:random:HA1
```

which is exactly what I computed, three different ways, with the correct field name (`pwd`) as well as `password`.
So the failure is **not** a wrong password, a wrong username or a wrong hash.

**What the client does that a script does not:** every RPC payload is wrapped by `encryptInfo()` before it leaves the
browser — an RSA public key (`f.setPublic(N, E)`) encrypts a random AES key, and the body is AES-encrypted with that
key (`randLen:32, mode:"CBC"`, `iv:"0000000000000000"`, `pad:ZeroPadding`), sent as
`{cipher, salt, key, content}`, with `decryptKeyToCrx` in later calls. The RPC transport also defaults to the path
**`/RPC2`**, not `/RPC2_Login`. A plaintext JSON client is therefore refused by the server, and the refusal is
deliberately uninformative.

**The conclusion, and the decision:** speaking this API from a script means reimplementing the vendor's encryption
envelope, which is a day of work and will break on the next firmware — to set a clock that the owner can set in the
page he already has open. That is the wrong trade. **The clock gets fixed from the UI; the script work goes into the
record, where it has lasting value.**

### What is needed to finish it

One of these, and the clock work is a five-minute job:

1. **NTP switched on in the NVR's own UI** — `Setup → System → Date & Time`, enable NTP against `pool.ntp.org`,
   and do the same in the Reolink app for the doorbell. Nothing else is required; I verify from the burned-in
   timestamps and the offsets in §7 must fall to zero; or
2. **an API client with the vendor's encryption envelope implemented**, only if a future need is continuous
   unattended reads rather than a one-time fix — not worth it for this.

For the retention number in §5 I need, from the same UI: **Storage → HDD**, the disk capacity and the number of days
it currently holds. That plus the camera count gives bytes per hour per camera, and `D19` stops being a guess.

The password that was supplied is now in a session transcript that this estate archives permanently
(`AGENTS.md` §1), so the `zabz` account should be deleted once the clock is fixed, and the shop's admin password
rotated.

---

## 10. Measured again after the owner opened the recorder's UI — **this supersedes the clock numbers in §7 and §8**

The owner sent screenshots of `Setup → System → Date & Time`, `Storage → Basic / Disk Manager / Disk Quota / FTP`, and
I re-fetched two stills at **16:07:40 EDT** and read their burned-in times. The earlier diagnosis was wrong in a
useful way, so it is recorded here rather than quietly edited.

### 10.1 There were two faults, and the owner fixed the first one himself

> **CORRECTED by the owner, 2026-10-27: NTP was OFF, and he turned it on and pressed sync just before sending the
> screenshots.** The first version of this section said "NTP was already on, so that advice was aimed at a fault that
> did not exist". That was wrong, and the way it was wrong is worth keeping: **a screenshot shows the state *after*
> someone touched the machine, and I read it as the state before.** The advice to switch NTP on was correct.

So the recorder had **two independent faults**, and one is now fixed:

| # | fault | state | evidence |
|---|---|---|---|
| 1 | **No time source** — NTP off, so the clock free-ran and accumulated error | **FIXED by the owner** (NTP on, `pool.ntp.org`, port 123, interval 60 min, then synced) | the 8 m 35 s of drift in the morning reading is gone; what remains is a whole number |
| 2 | **Timezone / DST** — `(UTC-05:00) Eastern` with a DST window of `Jan 1 00:00 → Jan 2 00:00`, i.e. a one-day window in January, so daylight saving is never applied in summer and the shop is shown **standard** time during EDT | **STILL OPEN** | what survives fault 1's repair is *exactly* one hour |

| when | camera OSD | host clock | offset | what it means |
|---|---|---|---|---|
| 12:21:25 EDT (NTP off) | 11:30:01 | 12:21:25 | 51 m 24 s | one hour of timezone **plus** 8 m 35 s of accumulated drift |
| 16:07:40 EDT (after his fix) | **15:07:41** | 16:07:40 | **59 m 59 s** | the drift is gone; the hour that is left is the timezone |

That the remainder is a *round* hour is the whole diagnosis: a free-running clock does not land on exactly 3600
seconds, a timezone offset does. Fixing fault 1 is what made fault 2 visible — the measurement only became decisive
because he pressed sync before I looked again.

**Fix for fault 2, four fields, no NTP involved:** `DST → Type = Week`, `Start = Mar, 2nd week, Sunday, 02:00`,
`End = Nov, 1st week, Sunday, 02:00`. That is the US rule, so the display is right now *and* after the November
change — which a manual "set the clock forward an hour" would not be.

### 10.2 The doorbell has both faults too, and neither is fixed

Same moment, 16:07:43 EDT: the Reolink burned **27/10/2026 15:00:06**, i.e. **1 h 07 m 37 s behind** — and this
morning it was 1 h 07 m 26 s. The extra 11 seconds across about 73 minutes is a free-running clock at roughly
**0.25 % slow**, and the bulk of the 67 minutes is the same kind of one-hour offset as the NVR. So the doorbell
needs the same two things, in its own app: **correct timezone/DST, and NTP on**. Nothing done to the NVR touches it.

**Then the owner opened the Reolink app's own Date & Time panel, and it named the fault outright.** Its DST line
reads:

```
DST : 1 hour
Mar. 2nd Week Sun. 02:00:00  -  Oct. The last Week Sun. 02:00:00
```

That is the **pre-2007 United States rule**. Since 2007 the US ends daylight saving on the **first Sunday of
November**, not the last Sunday of October. On 2026-10-27 — two days after the last Sunday of October — the camera
has already decided daylight saving ended, so it displays standard time while the shop is still on EDT. That is where
its missing hour comes from, and it is the same class of fault as the NVR's `Jan 1 → Jan 2` window: **a DST rule that
does not match the United States.**

The panel also shows the two times side by side — `Current Time 15:11:35` and `Modified Time 16:11:35` — i.e. the owner
had typed the correct local time and was one **Confirm** from applying it.

**The trap in the order of operations, stated so it is not walked into:** if the camera's clock is set by hand to the
right local time while its DST rule still believes daylight saving is over, the *internal* time ends up an hour ahead
of true UTC — and the next **Synchronize** (NTP) will faithfully set it back from real UTC and restore the one-hour
error for as long as that rule says "standard time". So the DST window must be corrected **before** the time is
trusted from NTP, not after. Where the two dates are read-only in that panel, the working sequence is to set the time
by hand and leave Synchronize alone until 1 November, after which the rule is right by accident.

### 10.3 Where it stands after the owner's two fixes — measured at 17:22 EDT

The owner says the Reolink's DST dates are **not editable**, and his decision is to leave that one as it is. Both
devices were then measured again, from pictures:

| device | burned in | host clock | offset |
|---|---|---|---|
| `cam_front_hallway_main` (Dahua, via the NVR) | **16:22:00** | 17:22:01 | **60 m 01 s** |
| `reolink_video_doorbell_poe_snapshots_clear` | **16:22:05** | 17:22:04 | **59 m 59 s** |

**What the owner's two fixes achieved, which is not the clock.** This morning the two systems were **16 m 09 s apart**
from each other (Dahua −51 m 25 s, Reolink −67 m 34 s). They are now **five seconds apart**, with one constant hour on
top. O3 — "arrival and departure times are comparable between cameras" — was the requirement that mattered and it is
now met: a single constant can be subtracted from every stamp in the building. What remains is one known, uniform error
rather than two competing ones.

**What "leave it" costs, per device — and they are not the same cost:**

| device | its DST rule | hours per year that the picture is wrong |
|---|---|---|
| **NVR (4 channels)** | `Jan 1 → Jan 2`, so daylight saving **never** applies | roughly **eight months** — every March-to-November day, one hour early. Correct in winter only |
| **Reolink doorbell** | `Mar 2nd week → Oct last week` | up to **seven days** a year, in the window between the last Sunday of October and the first Sunday of November. Correct the rest of the year |

So leaving both alone is not one decision with one cost. The doorbell's is a rounding error against a year; **the NVR's
is eight months of every picture stamped an hour early**, and unlike the doorbell's, the NVR's two dates are **editable
dropdowns** (`Type = Week`, `Start = Mar 2nd week Sunday 02:00`, `End = Nov 1st week Sunday 02:00`). It is the one of
the two that is worth two minutes.

### 10.4 The engineering decision that makes either of them tolerable

**Host time is authoritative; the burned-in stamp is decoration with a measured offset.** Concretely, every evidence
row carries:

- `captured_at` — Home Assistant's clock at the moment the still was fetched, accurate to the second and verified;
- `camera_id` — which device produced the frame;
- `osd_offset_s` — that camera's measured offset **as of a date**, nullable;
- `osd_measured_at` — when that offset was last checked against a picture.

A picture is therefore never trusted for *when*; it is trusted for *who*, and its own stamp is a redundant second
opinion that can be checked against a known constant. The health check reports the age of the last offset measurement
per camera and raises when it is older than thirty days or the offset is not a whole hour — because a **round** hour
is a timezone and a **ragged** one is a dying clock, and those need different repairs. That distinction is the one
thing this whole excursion into the recorder's settings produced, and it is worth keeping in software rather than in a
conversation.

---

## 11. Built and verified 2026-10-27: the evidence table and the clock register

Both DST windows are left as they are (the owner's decision: "whatever you think", answered by making the record
independent of them rather than chasing a setting on two devices). The part that needed nobody's hands is done and
proved on the authority.

**`schema/02-evidence.sql`** adds two tables to `/root/authority.db`:

- **`security_evidence`** — one row per attempted capture, with `captured_at` (host clock, authoritative),
  `camera_id`, `osd_offset_s` and `osd_measured_at`, `path`, `sha256`, `bytes`, `source_host`, and a **`result`
  column** (`ok | http_500 | timeout | no_frame | too_small | wrong_camera`) plus the verbatim `detail`. The result
  column exists because of `cam_larry_s_interior_main`: a capture that fails must leave a row saying so, because an
  absent row and a row saying `http_500` are different facts and only one of them is honest.
- **`camera_clock`** — one row per camera per measurement of its burned-in stamp, with the offset in seconds and a
  `verdict` of `clean | whole_hour | ragged | unreadable`, so the difference between a timezone and a dying clock
  survives as history instead of being rediscovered.

**Applied and verified on the authority**, not merely written:

```
$ sqlite3 -readonly /root/authority.db "select name from sqlite_master where type='table' ..."
camera_clock  credential  entry_event  security_action  security_decision
security_event  security_evidence  security_label  subject

$ pragma table_info(security_evidence)
id event_id entry_id door_id camera_id captured_at captured_at_local osd_offset_s
osd_measured_at path sha256 bytes width height source_host result detail created_at

$ select 'security_evidence', count(1) ... union all select 'camera_clock', count(1) ...
security_evidence|0      camera_clock|7
```

**The clock register is seeded with the day's real measurements**, which is what makes it a register rather than an
empty promise:

| camera | measured | offset | verdict |
|---|---|---|---|
| `cam_front_hallway_main` | 2026-10-27T16:21:25Z | 3084 s | ragged (before NTP was enabled) |
| `cam_front_hallway_main` | 2026-10-27T21:22:01Z | 3601 s | whole_hour (after the owner's sync) |
| `cam_larry_s_exit_main_2` | 2026-10-27T16:21:25Z | 3082 s | ragged |
| `cam_deserted_exit_main` | 2026-10-27T16:52:31Z | 3087 s | ragged (read from a second machine) |
| `reolink … snapshots_clear` | 2026-10-27T16:54:29Z | 4046 s | ragged |
| `reolink … snapshots_clear` | 2026-10-27T21:22:04Z | 3599 s | whole_hour |
| `cam_larry_s_interior_main` | 2026-10-27T16:52:40Z | — | **unreadable** (HTTP 500 on all three channels) |

**What is still missing, and it is the only thing between this and a working record:** nothing yet writes a row. The
capture step — on a door edge or a credential event, fetch one still from each camera covering that door, save it,
hash it, and insert the row — is the next piece of work, and it needs no credential and no setting on any device. The
`result` semantics, the entity choice (snapshot/clear entity, never the substream) and the offset lookup all have a
home now.

### 11.1 The capture step now writes rows — verified 2026-10-27 21:26Z

`scripts/security-capture.py` (deployed on the authority as `/root/security-capture.py`, run by
`/opt/company/.venv/bin/python`) takes a camera entity and three optional keys (`door_id`, `event_id`, `entry_id`),
fetches one still through `GET /api/camera_proxy/<entity>`, stores it under
`/root/security-evidence/YYYY/MM/DD/`, hashes it, looks up that camera's most recent measured offset from
`camera_clock`, and inserts the row. A failure path writes a row too, with `result` set and the verbatim `detail`.

Three real rows, on the first run:

```
camera.cam_front_hallway_main                        ok        168851 bytes  row ev-20261027T212648Z-cam_front_hallway_main
camera.reolink_video_doorbell_poe_snapshots_clear   ok        667863 bytes  row ev-20261027T212650Z-…
camera.cam_larry_s_interior_main                    http_500  HTTP Error 500: Internal Server Error
```

and the table as it now reads:

| camera | door | result | bytes | sha256 (first 12) | osd_offset_s |
|---|---|---|---|---|---|
| `cam_front_hallway_main` | `shop_door` | ok | 168 851 | `5395a78f185d` | 3601 |
| `reolink … snapshots_clear` | `outside_door` | ok | 667 863 | `32ab748a696a` | 3599 |
| `cam_larry_s_interior_main` | `inner_door` | **http_500** | — | — | — |

**The dead camera is in the record as a failure, not as silence** — which is the whole reason the `result` column
exists, and it worked on the first attempt.

**And the row's arithmetic checks out against the picture itself.** The stored hallway frame burns in
`2026-10-27 16:26:48`; the row says `captured_at = 2026-10-27T21:26:48Z` with `osd_offset_s = 3601`, and
`21:26:48Z − 3601 s` is `17:26:47` local, which is `16:26:47` in the camera's standard-time frame of reference —
one second from what the picture says. The file's sha256 on the authority, in the database, and after being pulled to
another machine and re-hashed here are the same value:
`5395a78f185de03374d2a2d4bf1b37f7c2641bcfcf27ce80a33fdf221705989a`.

That is the first end-to-end proof of the whole design: **a person's entry can be answered with a picture, taken at a
time the record can defend, and a camera that failed to deliver says so in the record instead of leaving a hole.**

### 10.3 The disk answers the retention question — and says video *is* being recorded

From `Storage`:

| read | value |
|---|---|
| Disk Manager | `sda`, Cabinet_1, Read/Write, **Health Normal**, **Free 0 GB / Total 1.80 TB** |
| Basic | Disk Full = **Overwrite**, Create Video Files = Time Length **60 min**, Delete Expired Files = **Never** |
| Disk Quota | **quota off**; Remaining Quota 1846.39 GB, Used Capacity of Record 0; red banner "channels with no allocated quotas" |

Three readings of that, in order of what is *known*:

1. **A 1.8 TB disk reporting zero free is a disk full of recordings.** That is the good news: video exists, the
   recorder writes, and the ring buffer is in `Overwrite` mode. It also means the red quota banner is cosmetic —
   quota is simply switched off, and with it off all channels share the whole disk. `Used Capacity of Record 0` is a
   field that only fills when quota is enabled, **not** evidence of an empty disk, and reading it as such would have
   been exactly the kind of number-that-looks-calm defect this folder exists to catch.
2. **There is no day-based retention at all.** "Delete Expired Files: Never" plus "Disk Full: Overwrite" means
   retention is whatever 1.8 TB holds at the current bitrates — a ring buffer, not a policy. So `D19`'s "thirty
   days" is not something this box can be asked for; it is something that would have to be *bought* (disk) or
   *configured* (bitrate, frame rate, or recording only on motion).
3. **The days-held figure still needs one glance**: `Playback` → the calendar, the earliest date that has footage.
   With 1.80 TB and the recorder's own reference bitrate of 4096 Kb/s (≈ 1.84 GB per camera-hour), five channels
   would fill it in roughly eight days — but that is arithmetic on a *reference* field, not a measurement, and it is
   labelled as such until the calendar says otherwise.
