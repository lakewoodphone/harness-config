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
