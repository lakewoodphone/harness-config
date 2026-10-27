# Live findings — measured on the running system, 2026-10-26 ~21:45Z

Read directly from the live host, not from the repo. Files pulled byte-exact from
`/config/packages/` on `192.168.50.34` through the shop desktop, base64, and verified by sha256 against
the host (`phoenix_security.yaml` `48967f3d…`, `phoenix_intrusion_evidence.yaml` `b09342c0…`). They live
in `live/`. **The repo copy in this clone differs from what runs** (`daemon` sha `75d17F2d…`), which is the
both-ways divergence trap, measured again.

---

## L1 — THE ALARM DISARMS ITSELF FOR ANYONE WHO WALKS IN (critical, live)

> **STATUS: FIXED 2026-10-26 22:24Z, and proven durable across a full Home Assistant restart at 22:35.**
> The two ghost automations are off at every start, the keypad handler is on (it had been severed since
> 2025-12-16), and the stale latch is cleared, so `binary_sensor.phoenix_everyone_away` reads **`on`**.
> Evidence: journal `W7259`; deployed hashes `phoenix_core.yaml 179e7dc4…`, `presence_architecture.yaml
> 140970c9…`, `phoenix_access_manager/__init__.py 6431acb0…`. **The text below is the original finding and is
> kept because the mechanism still explains why it happened — do not read it as current state.** What remains
> open is that the *credential* that now disarms is the shop keypad only; the apartment door still reports
> nothing usable (see `30-IDENTITY.md`).

**The chain, each link read in the deployed file and confirmed in the live state machine:**

1. `phoenix_security.LIVE.yaml:95-102` — `Phoenix: Extreme Intrusion Disarm` triggers on
   `binary_sensor.phoenix_everyone_away` going **off**, and its action is to clear
   `input_boolean.phoenix_intrusion_active` and call `script.phoenix_intrusion_reset` (siren off).
2. `phoenix_security.LIVE.yaml:12-15` — `everyone_away` is `NOT user_is_here AND NOT worker_is_here AND
   NOT guest_mode`.
3. `presence_architecture.LIVE.yaml:287-313` — `Phoenix: Passive Arrival (Montrose Phone + Room Occupied)`:
   *"Turns on Worker presence when Montrose phone is home AND Control Room becomes occupied."* Condition:
   `device_tracker.monty == home`.
4. **Measured now:** `device_tracker.monty = home` (last_changed 21:05:33Z, i.e. it has not moved since the
   last HA restart), `automation.phoenix_passive_arrival_montrose_phone_room_occupied` is `on`.
5. **Measured now:** `automation.phoenix_extreme_intrusion_disarm` `last_triggered = 21:06:07.627Z`;
   `input_boolean.phoenix_worker_is_here` turned `on` at `21:06:07.424Z` — **203 ms earlier**, credited by
   `automation.phoenix_v2_worker_auto_arrival_gps` (`last_triggered 21:06:07.422Z`).

**What that means in plain words.** A departed worker's GPS tracker, which has reported `home` for months,
plus any presence credit, turns `worker_is_here` on; that turns `everyone_away` off; that **disarms the
alarm and silences the siren**. An intruder who walks into the control room triggers the same chain: the
alarm disarms itself for him. This is the measured explanation of the prior audit's *"all 13 instrumented
episodes ended by presence credit — never by PIN, never by a human"* (`HANDOFF` §5.1), and it is a
security defect, not a false-alarm nuisance.

**It is live right now.** Re-measured at **21:37:52Z** (authority clock, same call): the room is verifiably
empty (`zone_control_room_occupied = off`, `control_room_hub_control_room_presence = off`, all camera human
detectors `off`, all three door contacts `off`), yet `input_boolean.phoenix_worker_is_here` is still **`on`**
(since `21:06:07.424Z`), `everyone_away` is **`off`** (since `21:06:07.579Z`), and the alarm flag is `off`.
**31 minutes 45 seconds** with the building empty and unarmed, and nothing in the configuration will clear it.

> Correction to this document's first draft: it said "at 21:45Z … 39 minutes". Both were wrong — the
> measurement was taken at ~21:20Z and the elapsed figure was arithmetic on an invented clock. The
> underlying state was and is exactly as described; the timestamps now come from the same call that read
> the states.

**The credential path that should be the only disarm is dead:**
`automation.phoenix_keypad_event_handler = off` (`phoenix_core.LIVE.yaml:40`, `initial_state: false`,
last triggered **2025-12-16**). So `esphome.access_control_keypad_entry` is never validated,
`phoenix.valid_pin` never fires, and the whole PIN-context branch in `presence_architecture.LIVE.yaml:152-257`
is unreachable. The card-reader and keypad entity shadows are `unavailable`
(`automation.access_control_keypad_*`, five of them).

**Minimal remedy, one line, reversible, no config edit:** turn `input_boolean.phoenix_worker_is_here` off.
`everyone_away` then recomputes `on` and the building is armed. It will disarm itself again the next time
the ghost is credited, so the durable fix is to delete the GPS/passive-arrival credit for a worker who no
longer works there — which is a config change to a live alarm and needs the owner's word.

## L2 — the arming condition and the disarming condition are the same broken signal

`everyone_away` is a motion-gap detector: it goes false **0.13 s** after a radar sees someone and declares
the shop empty **9.77 times a day** (R1 §4). It is used both to arm *and* to disarm. That is why the system
oscillates: one sensor, two opposite meanings. The redesign's whole point (`10-ARCHITECTURE.md` §1.1) is
that arming must come from **schedule + credential occupancy**, and disarming must come from **a credential**
— never from presence.

## L3 — duplicate and orphaned automations

Live registry carries `phoenix_v2_auto_departure` **and** `phoenix_v2_auto_departure_2`;
`access_control_keypad_event_handler`, `…_2`, `…_validator`, `…_validator_2`, `…_entry_trigger`,
`…_process_keypad_entry`, `keypad_pin_entry_to_phoenix_validator` all `unavailable`. Seven dead entity
shadows for keypad handling. This is the "less dead code" problem visible in one command.

## L4 — the day's real numbers, from the running system

| Read | Value |
|---|---|
| `GET /api/` from the authority | **200 in 54 ms** over the tailnet |
| `GET /api/states` | **200, 1,037 entities, 66 ms** |
| entities `unavailable`/`unknown` | **370 of 1,037 (35.7 %)** |
| cameras | 25 camera entities in HA — but **5 physical cameras**: 4 Dahua channels + the Reolink doorbell. The rest are substreams, a stale placeholder, and a channel-fallback duplicate (`cam_larry_s_exit_main_2`). Channels 2/3/4 have no lens (`research/B` §4, `R2-cameras.md:145-158`) |
| locks | `lock.0x002446fffd0a4705` = locked; `lock.boltchecked_apartmentdoor` = **unavailable** |
| page endpoint, `POST /webhook/ha/security-alert` with a skipped test event | **200 in 170–471 ms** |

The last row matters: the company's paging endpoint is fast enough. The reason no page has ever been
delivered is not latency — it is that the reflex never reached the step (`HANDOFF` §5.2) and, since today's
fix, that the alarm disarms before it matters.

## L5 — "no page has ever been delivered", verified from the receiving end

The prior session inferred it from HA's log and from three webhook POSTs. This is the other end, read
directly on the authority:

```
sqlite3 -readonly /root/authority.db \
  "SELECT COUNT(*) AS all_sms,
          SUM(CASE WHEN body LIKE '%LPT-SECURITY%' THEN 1 ELSE 0 END) AS security_pages,
          MIN(created_at), MAX(created_at) FROM sms_log;"
→ 4507 | 0 | 2025-09-02T06:19:25+00:00 | 2026-10-26T17:44:57+00:00
```

**4,507 messages sent since 2025-09-02, and not one of them is an intrusion page.** The page body begins
`⚠️ LPT-SECURITY` (`app/main.py:8583`), so the filter is exact. Two independent ends now agree: HA never
invoked the page, and the company never sent one.

> A caveat that must travel with this number: `sms_log` records the company's own send attempts. It does
> not prove *delivery* to a handset — no page has ever been attempted, so there is nothing to have been
> delivered. The first real page must be a test he has agreed to in advance, and it must be verified by the
> recipient answering.

## L6 — the company's event pipeline is dead, and it reports success (high, live)

**Read**: `SELECT COUNT(*) FROM events` on `/root/authority.db` → **0**. `routing_log` → **0**. So the
`POST /events` path — the one designed for exactly this, an external event waking the company in about a
second — has never carried a single event.

**The mechanism** (lane C, verified against the source): `app/autopilot.py:9322` calls
`enqueue_job(..., task_type=...)` while `app/database.py:9638` accepts `job_type`. The `TypeError` is raised
inside `_dispatch_routed_event`, **swallowed**, and the event is marked **processed** at `autopilot.py:9254`.
That is the same shape as the estate's most expensive recurring failure: a failure that looks like a
success, because the thing that would have told you never ran.

**What actually works today**, measured over 24 h: the `ha-watch` 30-minute cron → wake flag → `dsh` on the
desktop, **p50 37.3 min, p90 308 min** end to end; `job_queue` pickup **p50 1 h 45 m, p90 3 h 34 m**
(n = 347).

**Why it matters for this design and not just for tidiness:** the whole "real-time security by agents" claim
rests on an event reaching an agent in seconds. Today the fastest honest number is tens of minutes, and the
component that would have made it seconds has been dead since it was written — silently. A security system
built on this path without fixing it would page nobody and record a success.

**One more live constraint, same area:** `UNSAFE_ACTIONS_ENABLED=false` +
`HA_CALL_SERVICE_REQUIRES_APPROVAL=true` on the authority mean every Home Assistant service call becomes an
owner-approval task. **The company can read the alarm; it cannot fire the siren.** That is the correct
default, and the design must respect it rather than route around it.

