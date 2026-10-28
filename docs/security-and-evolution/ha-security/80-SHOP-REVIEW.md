# 80 — The shop review surface: live, then a day you can scroll

*Started 2026-10-28. This is the architecture document for the build the owner asked for: open the page and see the
live situation, then scroll down through a day's captures — then yesterday, then the day before — with clips, and be
able to expand any event into everything known about it.*

## What he asked for, in his words

> *"open that page and see, you know, the current view like you have with the cameras and the alerts or whatever, and
> the most recent captures. And also be able to scroll down and see a gallery of like all the captures for that day
> and then the day before and so on. And then clips of people if there's a point in it to be able to play the clip…
> And be able to expand to see full events of like the door and different things… to be able to like scroll through
> fast and see everything that happened that day. An easy win and some data dump type of way."*

Read as a requirement, that is:

1. **Now** — live cameras, the alert if there is one, and the most recent captures.
2. **Today** — a gallery of every capture, in time order.
3. **Yesterday, and the day before** — the same, without hunting.
4. **A clip** where a person was present long enough to be worth watching.
5. **Expand** any item to the full event: which door, which sensor, who, when it began, how long, every picture.
6. **Fast** — scanning a day must take seconds, not reading.

## What the ground truth says (all measured 2026-10-28)

**Every camera has its own human detector.** Six cameras expose `binary_sensor.cam_*_smart_motion_human_2` alongside a
motion alarm and a vehicle detector. That is far better than only the doorbell's person sensor: "a person was on this
camera at this second" is measurable per camera, which is the primitive an event gallery needs.

**Signal volume is manageable once the noise is removed.** In 24 hours the record held **3,769** `control_room_moving`
rows — a detector that fires constantly and must never reach the screen — against **120** doorbell-person detections,
**74** outside-door contacts, **55** hallway-zone activations and **84** occupied-area rows. The screen is built from
the second group.

**`security-listener.service` already holds a Home Assistant websocket** and writes every one of those rows to
`security_event` on the authority. Ingestion does not need to be invented; it needs a grouping layer on top.

**Clips are possible without any new credential.** The Reolink media source in Home Assistant has **zero browsable
children** — its recordings are not reachable that way, and no camera or NVR credential exists in the company
environment. But `camera.record` works: a test recorded 8 seconds from the hallway camera to `/media/test_clip_….mp4`,
it appeared under *My media*, and `media_source/resolve_media` returned a **playable signed URL**. So clips from now
on require nothing new. Historic footage sits on the NVR's disk and stays out of reach until its credential exists.

**ffmpeg is not installed on the authority** (candidate `7:8.0.1-3ubuntu2`, 32 GB free). Needed only if clips are
assembled outside Home Assistant; `camera.record` already produces a browser-playable MP4.

## The architecture this implies

```
  Home Assistant                       authority (secratary-cloud)                 the screen
  ─────────────                        ────────────────────────────                 ──────────
  camera streams ── camera.record ──▶  /media/…mp4  ─┐
  camera stills  ── camera_proxy ───▶  evidence jpg  ─┼─▶  visit / event rows  ──▶  review page
  person + door + keypad sensors ───▶  security_event ┘        (grouped, with media refs)
  (already streaming to the listener)
```

**Storage:** a `visit` concept in `/root/authority.db` — one row per human event (arrival → actions → departure), with
its pictures and its clip, plus the raw signals that formed it. Grouping rules belong in one place so the same visit
looks the same on every surface.

**The screen:** served by the dashboard the owner already logs into (`ai.abletelsolutions.com`), because it already has
authentication and works on his phone — not a new public URL carrying shop footage.

**Honesty:** an event with no picture, no clip, a dead camera or an `unavailable` sensor must say so on the card. The
failure this estate keeps repeating is a confident blank.

## Round 1 status

- Goal armed, 20 rounds.
- Three research agents dispatched: the Reolink recordings API, Dahua NVR playback (both for the historic-footage
  question), and a phone-first design for the day gallery.
- Ground truth established above: sensors, volume, listener, clip path, tooling.
- Not yet built: the grouping layer, the media capture per event, the UI.

## Round 2 — the grouping layer, and a finding that changes the design

**Built:** `scripts/shop-visits.py` and two tables in the authority database — `shop_visit` (the human event) and
`shop_visit_signal` (the raw rows that formed it, so any visit can be expanded to its evidence).

The rule, deliberately explainable: only signals that can mean a person are considered (a camera's human detector, a
door contact, the doorbell's person/visitor, a keypad credential, an occupied zone); a visit opens at the first such
signal, absorbs everything within **150 seconds**, and closes on a longer gap. Zones are recorded as context but never
open or extend a visit — without that, `business_area_occupied` glued unrelated arrivals together and labelled every
visit with rooms instead of cameras.

**Result over 43 hours: 277 person-capable signals → 53 visits, 45 of them with a person detected.** That is the
compression the day gallery needs: 53 cards to scroll, not 8,092 rows.

One visit, expanded exactly as the UI will read it:

```
17:15:59  keypad entry -> received
17:16:03  business_area_occupied -> on
17:16:03  zone_control_room_occupied -> on
17:16:54  shop door contact -> off        (visit still open)
```

**The finding: the per-camera human detectors have never fired.** All twelve `cam_*_smart_motion_human_2` and
`*_motion_alarm_2` entities have been `off` for **43 hours** — the record holds seven rows for them, every one from a
restart at 22:36 on 26 October. The NVR integration exposes them, but the NVR has no human-detection rules configured
on those channels, so they emit nothing.

That matters because the original design assumed six independent person detectors. In reality there is **one** — the
doorbell's own detector, which fires ~120 times a day. So a visit's "person" flag comes from the doorbell (the view
from outside), and an indoor arrival is known from the **door contact** plus the **keypad**, not from a camera saying
"a human is here".

Two ways to fix that properly, both needing the NVR's credential, which does not exist in this environment: enable
IVS/human rules on the NVR channels, or pull the NVR's own event log. Until then the build is honest about which
signal it has rather than pretending six cameras are watching for people.

## Round 1 (of the review surface): the media layer, and the clock that lies on the picture

**Built:** `scripts/shop-capture.py` plus the `shop_visit_media` table. For every visit it captures a still from the
three cameras that matter — the shop-door threshold (best face view), the outside stairwell, and the drop-off door —
through Home Assistant's `camera_proxy`, hashes it, writes it under `/root/shop-media/<date>/`, and records the result
including failures. Idempotent: a visit that already has a good still is skipped.

**Measured on the first run:** 10 visits → **30 stills, 0 failures, 10.7 MB**. Every file is a real 2560×1440 frame,
verified by opening one. At ~1 MB per visit this is roughly 50 MB a day for the current traffic, so retention is a
design parameter, not an afterthought.

**The finding that the pictures carry their own lie.** The still captured for the 17:15:59 visit has **12:26:50**
burned into the image. The camera's own clock is nearly five hours away from the event time (and ~49 minutes from the
correct local time). Two consequences, both now requirements:

1. **The event time shown in the UI is Home Assistant's trigger time, never the burned-in stamp.** A person reading
   `12:26:50` on a card that says 17:15 would conclude the system is broken.
2. **The offset has to be recorded and shown**, the way the design review demanded: when a camera's clock is more than
   a minute out, the expanded event says so (`Camera clock 49m behind`) and that camera is never merged with another by
   time alone. The same skew is why cross-camera merging cannot be done on timestamps.

This is the second time in this estate that a camera's honest-looking timestamp was wrong; the first cost a whole
morning of confusion about whether NTP was on.
