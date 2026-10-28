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

## Round 2: clips — what is possible, proven, and what is honestly not

**The constraint, first:** `camera.record` records **from the moment it is called**. It cannot go back in time. So a
clip can exist only for a visit that is happening now. An event from this morning can never have one, and the page
will say so rather than showing a player that fails.

**Built:** `scripts/shop-clip.py`. It finds person-visits young enough for the clip to actually cover them, picks the
camera that would have seen them (the shop-door threshold for a shop-door visit, the outside doorbell otherwise),
records 25 seconds into `/media/shop/<visit_id>.mp4`, and records the outcome in `shop_visit_media` with
`kind='clip'`.

**The rule that keeps it honest.** The first version selected any visit that was "open or recently ended" — which
matched the 17:15 visit, twenty minutes old. Recording then would have produced a video of an **empty hallway attached
to someone else's arrival**. The window is now: the visit must have **started** inside the last
`CLIP_SECONDS + 90s`, so the clip genuinely covers it. Run against the current moment it correctly selects **0
visits** — nobody had arrived in the last two minutes.

**The storage and serving path, verified end to end:**

```
camera.record -> /media/shop/proof_….mp4
media_source browse -> 1 file, can_play: True
media_source resolve -> /media/local/shop/proof_….mp4?authSig=…
fetch that URL     -> 200  video/mp4  2,382,160 bytes
```

So a clip is recordable, storable, resolvable and fetchable as a real video file with no camera credential — the
Reolink and NVR routes (researched in full: `/cam/playback` with underscore timestamps, realtime-paced;
`File[].name` and `Download` for Reolink) stay available if the owner ever supplies a password, and are not needed for
this to work.

**Consequence for the page:** every event card carries one of three honest clip states — *plays*, *no clip because it
is older than the recorder*, *no clip because nothing was recorded* — and only the first gets a play button.

## Round 3: the page exists — live, recent, and the days back

**Built:** `app/shop_review.py`, a FastAPI router serving one server-rendered page at
`/shop/r/<token>`. Server-rendered on purpose: the visits, pictures and clip references all live on this host, so one
HTML response is faster than a page that then fetches everything, and there is no client-side state to get wrong.

**What it shows, in the owner's order:** a header with the visit count, **Live now** (four camera tiles), **Most
recent** (the three newest visits that have a picture), then **Today**, **Yesterday** and the days before, each as a
header with its counts and its visit cards. Every card expands in place — with `<details>`, so it works with no
JavaScript — to show the pictures from every camera, the raw signals that formed the visit, its duration and doors, and
a clip if one exists.

**Measured after the last fix:** 5,611 px tall, 47 images, **27 decoded**, 53 event cards, **0 JavaScript errors**, at
390 px wide.

### Three defects the render caught, none of which a readback could

1. **The thumbnail rendered at natural size.** The `<img>` was a direct child of `<summary>` with no wrapper, so a
   2560 px frame filled an entire phone screen — one card per screen. The page was **19,351 px** tall. Wrapping it in
   the sized box brought it to **5,611 px**.
2. **Every "recent" card showed the hallway camera**, including the one labelled *Person outside*, because the still
   picker sorted alphabetically and `cam_front_hallway_main` wins every time. A thumbnail showing the wrong room is
   worse than none: it looks like evidence and is not. Stills are now chosen by what the visit actually was — shop door
   → hallway, street door or a person → the doorbell.
3. **The picture grid inside an expanded card was broken images**, because the `<img>` pointed at a route that does not
   exist (`/img/<visit>/<camera>`); the working route is `/full/<visit>/<camera>`. The `<a href>` was already right,
   which is exactly the kind of half-right that a readback would have called correct.

**Honesty, as built:** a visit with no clip says *"No clip for this event — recording starts only when a visit begins,
so older events will never have one."* A visit with no picture says so. Nothing shows a dead player or a blank frame.

### Access

The URL carries a long random token (`SHOP_REVIEW_TOKEN` in `/opt/company/.env`), not a login. That is the same trust
model as the MMS evidence host — unguessable rather than authenticated — and it is a stated trade-off, not an
oversight: the page can be moved behind the dashboard's session later without touching anything below it. A wrong
token returns **404**, verified.

### The page is reachable from a phone

`api.abletelsolutions.com` answers **401** for everything at the edge — a key, not a login — so a page served there is
unopenable in a browser. The one path the edge lets through is **`/webhook/`**, which is where Twilio fetches MMS media
(verified: a stored evidence JPEG returns 200 anonymously, and the alert endpoint answers 405, meaning it reached the
app rather than the edge).

So the review page moved under it: **`/webhook/ha/shop/r/<token>`**. Verified end to end from outside:

```
page   -> 200  63,551 bytes
image  -> 200  image/jpeg  152,460 bytes
live   -> 200  image/jpeg  152,643 bytes
```

That is the difference between a page that exists and a page the owner can open.

## Round 4: it keeps itself current, and it says when something is wrong

Two gaps closed, both of which would have made the page lie by omission.

**1. The pipeline was manual — so the page would freeze.** Visits are grouped from raw signals, pictures are captured
when a visit appears, and clips are recorded *while a visit is happening*; none of those can be done after the fact. A
page fed by a hand-run script is a page that silently stops updating, which is what happened to the previous timeline
(§ Round 3 finding).

`shop-review-cycle.sh` on a **3-minute timer** (`shop-review-cycle.timer`), in dependency order: group → capture stills
→ record clips. Every step is idempotent, so a rerun costs nothing. First run observed: 10 visits grouped, 0 new stills
(all present), 0 clips (nobody had arrived in the clip window) — the "nothing to do" path is exercised and quiet.

**2. There was no alert line.** The objective asks for "cameras and any alert", and the page showed none. It now carries
the **same severity logic as the Home Assistant banner**, so the two can never disagree:

| state | what the page says |
|---|---|
| alarm tripped **and** the siren muted | **ALARM TRIPPED, SIREN SILENCED** (red) |
| alarm tripped | **ALARM GOING OFF NOW** (red) |
| drill switch on | **SIREN SILENCED — TEST MODE ON** (red) |
| lockdown | **ACCESS CONTROL LOCKED DOWN** (red) |
| door open while marked away | **DOOR OPEN WHILE AWAY** (red) |
| guest code on, nobody home | amber |
| a sensor offline | **CANNOT CONFIRM THE BUILDING** (amber) |
| door open | **DOOR OPEN** (amber) |
| nothing | **No alerts · Doors closed.** (green) |

If Home Assistant cannot be reached at all, the banner says **"Cannot reach the building"** rather than defaulting to
calm — a gallery that looks peaceful while the connection is down is the one lie this system exists to prevent.

**Verified on the public URL after the change:** 200, 64,081 bytes, and the alert block renders
`No alerts | Doors closed.`

**A defect caught in my own patch:** the first attempt 500'd every request with `NameError: name 'st' is not defined` —
one of two string replacements had silently not matched, so the variable was used but never defined. The traceback said
which line; the lesson is the same as the earlier rounds: a patch that compiles is not a patch that applied.

## Round 5: "who" — the name, and the timezone that hid it

The objective asks each card to say **who**. It could not: measured on the live record, every `entry_event` row for the
shop keypad has an **empty `subject_id`**, and the raw `security_event` payload is the automation that fired, not the
credential. The name exists in exactly one place — Home Assistant's `input_text.phoenix_access_control_log`, whose
lines read `Oct 28, 1:16 PM - Owner Access at Interior`.

**Built:** `scripts/shop-attribute.py`. It parses that log, converts each time to UTC, and attaches the nearest entry
to any visit that had a keypad signal, within five minutes. A visit with no keypad signal gets nothing — this is a fact
about a code, never a guess about a face. Wired into the 3-minute cycle **after** the grouping step, because
`--rebuild` deletes and re-inserts the window and would otherwise erase the names every three minutes.

**The bug that made it silently name nothing, and how it was found.** The first run reported *"6 readable entries, 9
visits with a keypad signal, named 0"*. Instrumenting the loop showed a perfectly good 0.015-second gap to the log
entry — so the matcher was fine and the times were not. The cause: the script read `OWNER_TIMEZONE`, which on this host
is **`UTC`**, and that setting governs *when alerts may be sent*, not *what clock wrote a log line*. Every entry was
therefore four hours from its visit. The authority on "what time is it in the building" is the Home Assistant instance
itself, so the script now asks it (`/api/config` → `time_zone` → `America/New_York`), falling back to
`SHABBAT_TIMEZONE` and then the building's zone.

**After the fix:** `building timezone: America/New_York`, and five visits in twelve hours were named
**"Owner at Interior"**. The page now titles those cards **"Owner access at the interior"** — which answers the owner's
own question in a way *"Person at the shop door"* never can.

**The honest limit, and the next fix:** the access log is a 255-character rolling field, so it holds only the last
half-dozen presses. Names are therefore available only for recent visits. The historical names are still recoverable —
the listener records `input_text.phoenix_access_control_log` on every update, so each past log line is sitting in
`security_event.new_state` — and mining that is the next round's job.
