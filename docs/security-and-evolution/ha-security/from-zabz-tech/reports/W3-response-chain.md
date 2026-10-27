# W3 — What the alarm actually does once it fires, and whether anything can stop it

**LOCAL (zabz-tech)** — read-only. No POST to `/alarm/on`, no edits, no restarts, no state-changing service calls.

## Step 0 — revision check

| file | sha256[0:12] | expected | result |
|---|---|---|---|
| `config/packages/phoenix_security.yaml` | `e6b45f6b1c04` | `e6b45f6b1c04` | MATCH |
| `config/packages/secretary.yaml` | `6ea50d895217` | `6ea50d895217` | MATCH |

`pwd` = `C:\Users\ezabz\Code`. Both files present; `phoenix_security.yaml` mtime `2026-10-26T14:08:52`, 14472 bytes; `secretary.yaml` mtime `2026-09-14T12:08:06`, 2898 bytes.

Read: `phoenix_security.yaml` (all 293 lines), `secretary.yaml` (all 68), `phoenix_intrusion_evidence.yaml` (all 394), `phoenix_helpers.yaml` lines 85–218, `automations/access_control.yaml` around the three `homeassistant.start` triggers, `lovelace/snapshots_admin.yaml` 440–478, `ui-lovelace.yaml` 686–698. Live HA read via `GET /api/states` (1036 entities), `GET /api/services`, `GET /api/logbook/...` with `end_time`. Mac listener probed with **GET only** (`GET /`, `GET /alarm`, plus a raw-socket GET to read the headers).

Structural proof by parsing the YAML (custom loader for HA's `!secret` tag; first two attempts exited 1 on that tag and on my own wrong loader — fixed by `yaml.load(..., Loader=L)`):

```
repeat keys: ['while', 'sequence']
while: [{"condition":"state","entity_id":"input_boolean.phoenix_intrusion_active","state":"on"}]
sequence steps: 4
  step 1  homeassistant.turn_off      (deserted_house_lights, control_room_strip_lights)
  step 2  delay {'milliseconds': '{{ range(200, 800)|random }}'}
  step 3  homeassistant.turn_on       (same two)
  step 4  delay {'milliseconds': '{{ range(200, 800)|random }}'}
initial_response: 6 top-level steps
reset:  rest_command.phoenix_alarm_mac_off ; homeassistant.turn_on (lights)
test:   input_boolean.turn_on [intrusion_active, intrusion_test_mode] ; script.phoenix_intrusion_initial_response
```

---

## 1. The response timeline, with measured durations

**Episode A — 2026-10-25 23:23 → 10-26 11:25** (all rows from `GET /api/logbook/2026-10-25T23:15:00?end_time=2026-10-26T02:30:00` and `…/2026-10-26T02:14:30?end_time=2026-10-26T14:00:00`, local time):

| time | event | delta |
|---|---|---|
| 23:23:21 | `input_boolean.phoenix_intrusion_active` → **on**; `script.phoenix_intrusion_initial_response` started | t0 |
| 23:23:38 | `script.phoenix_intrusion_loop` **started** (one step after `rest_command.phoenix_alarm_mac_on`) | **+17 s** |
| 00:49:00 | HA `WARNING … looped 5000 times` (given fact) | +5,122 s ≈ 1 h 25 m 22 s |
| 02:14:22 | HA `CRITICAL … terminated because it looped 10000 times`; `script.phoenix_intrusion_loop` → **off**; `script.phoenix_intrusion_evidence_and_page` **started** in the same second | **+2 h 51 m 01 s** |
| 02:14:27 | `phoenix_intrusion_evidence_and_page` finished (5 s → page accepted on attempt 1, no retries) | +2 h 51 m 06 s |
| 02:14:27 | `phoenix_intrusion_initial_response` finished | — |
| 11:25:25 | `phoenix_intrusion_active` → **off**, `script.phoenix_intrusion_reset` started (`phoenix_alarm_mac_off`) | **+12 h 01 m 47 s** |

Measured per-iteration cost: 5,122 s ÷ 5,000 = **1.0244 s**. YAML prediction: two uniform 200–800 ms delays = 1,000 ms mean, times 10,000 = 10,000 s; measured 10,244 s → **24.4 ms of service-call overhead per iteration**. The model and the log agree, which is what confirms the 4-step strobe-only body is exactly what ran.

**Episode B — 2026-10-26 14:03** (`GET /api/logbook/2026-10-26T14:00:00?end_time=2026-10-26T14:20:00`):

| time | event | delta |
|---|---|---|
| 14:03:00 | `phoenix_worker_is_here` → off, `phoenix_everyone_away` → on (arming) | — |
| 14:03:15 | `binary_sensor.zone_hallway_active` → on (trigger) | t0 |
| 14:03:21 | `phoenix_intrusion_active` → on; `initial_response` started | **+6 s** (the grace `delay: "00:00:06"`) |
| 14:03:29 | `zone_control_room_occupied` → on, `worker_is_here` → on, `everyone_away` → off ⇒ disarm: flag → **off** + `reset` started (`mac_off`) | +8 s |
| 14:03:41 | `switch.deserted_house_lights` → off (step 3: lights-off) | +20 s ⇒ snapshot block ≈ 20 s |
| 14:03:43 | `rest_command.phoenix_alarm_mac_on` reached — **14 s after the disarm**; `script.phoenix_intrusion_loop` started and exited in the same second (its `while` was false) | **+22 s** |
| 14:03:43 | `script.phoenix_intrusion_evidence_and_page` started | +22 s |
| 14:03:50 | `initial_response` finished | +29 s |
| 14:05:40 | manual `script.phoenix_intrusion_reset` (`mac_off`) | siren ran **1 m 57 s** |

**The brief's "8 s" does not reproduce as stated; the two numbers that do are 8 s and 14 s.** Disarm fires 8 s after the flag went on (14:03:21 → 14:03:29), and the siren is switched on **14 s after the disarm** (14:03:29 → 14:03:43). The 22 s figure is flag-on → siren (14:03:21 → 14:03:43), which is the snapshot block (20 s measured) plus the 1 s lights delay plus dispatch. Episode A's snapshot block was 16 s (loop at +17 s), so the block is **16–20 s, not a fixed 22 s**.

---

## 2. Every way the siren is left sounding with no automatic stop

**F1 — CRITICAL — a real alarm ran the Mac siren for 12 h 01 m 47 s after the loop had already died.**
Claim: the siren is started once, by `rest_command.phoenix_alarm_mac_on` (`phoenix_security.yaml:188`), and the only thing in the entire configuration that ever calls `phoenix_alarm_mac_off` is `script.phoenix_intrusion_reset:253`.
Proof: `grep` for `phoenix_alarm_mac_off` over `config/` returns exactly two hits — the definition (`secretary.yaml:42`) and the call (`phoenix_security.yaml:253`). The live service list confirms both are loaded (`GET /api/services` → `rest_command: phoenix_security_page, secretary_ptt, phoenix_alarm_mac_on, phoenix_alarm_mac_off, reload`). The logbook shows the loop terminating at 02:14:22 and the next `script.phoenix_intrusion_reset` run at **11:25:25** — no `mac_off` request for 12 h 01 m 47 s, and 9 h 11 m 03 s of that with the loop already dead (no strobe, nothing pending, siren unreferenced).
Fix: the flag-off/loop-stop/HA-start fail-safe in F2.

**F2 — CRITICAL — the 10,000-iteration cap stops the strobe and leaves the audio untouched.**
Claim: at the cap HA aborts `phoenix_intrusion_loop`; the loop's body never references the Mac, the flag, or a timer, so nothing is stopped except the two light switches.
Proof: parsed body = 4 steps, all `homeassistant.turn_off` / `delay` / `homeassistant.turn_on` / `delay` (dump above). `repeat` has exactly two keys (`while`, `sequence`) — no `for`, no `count`, no `continue_on_error`. Terminating `while` at 10,000 is HA's runtime cap, not YAML. Measured effect: loop → off at 02:14:22, `phoenix_intrusion_active` unchanged.
Fix: one automation covers F1/F2/F5/F6 —

```yaml
- alias: "Phoenix: Siren fail-safe (flag off / loop stop / HA start)"
  id: phoenix_siren_failsafe
  mode: restart
  trigger:
    - platform: state
      entity_id: input_boolean.phoenix_intrusion_active
      to: "off"
    - platform: state
      entity_id: script.phoenix_intrusion_loop
      to: "off"
    - platform: homeassistant
      event: start
  action:
    - delay: "00:00:03"   # let a same-second alarm_mac_on land first (F5)
    - repeat:
        count: 3
        sequence:
          - service: rest_command.phoenix_alarm_mac_off
          - delay: "00:00:10"
```

The 3 s delay is deliberate: it catches an `alarm_mac_on` that lands *after* a disarm (the exact 14:03 ordering) instead of racing it.

**F3 — CRITICAL — one tap on "Intrusion Active" in the dashboard silences the strobe and leaves the siren screaming forever.**
Claim: the dashboard exposes the raw boolean as a live toggle, and turning it off does **not** call the reset script — the loop's `while` goes false within ~1 s, the siren keeps its last command.
Proof: `lovelace/snapshots_admin.yaml:445-464` is an `entities` card listing `input_boolean.phoenix_intrusion_active` (line 449) directly above `script.phoenix_intrusion_reset` (line 461). The boolean has exactly one `turn_off` anywhere in the config — `phoenix_security.yaml:95`, inside the disarm automation, which then calls reset. Measured exit cost when the flag drops first: at 14:03:43 the loop started and stopped inside the same second.
Fix: F2 (the flag-off trigger makes the boolean toggle safe), plus remove the boolean from the card and keep only a purpose-built "SILENCE" script.

**F4 — HIGH — the dashboard "Reset" button is half a reset: siren off, strobe forever, house still unarmed.**
Claim: `script.phoenix_intrusion_reset` does exactly two things — `mac_off`, then lights **on** — and never clears `phoenix_intrusion_active`. Pressed alone, the loop keeps strobing indefinitely and the trigger automation stays blocked by its `state: "off"` condition.
Proof: parsed reset = `[rest_command.phoenix_alarm_mac_off, homeassistant.turn_on(lights)]`; the flag is cleared only by the caller, at `phoenix_security.yaml:93-95`, *before* reset is invoked. Missed reference in the loop's `while` (`:222`): no exit on any other condition.
Fix: add `input_boolean.turn_off` for the flag as step 0 of `phoenix_intrusion_reset`, so both controls are complete, and make the loop's exit stop the audio (F2).

**F5 — HIGH — a residual disarm-vs-siren race survives today's fix, and it is the 14:03 bug in miniature.**
Claim: the new `condition: state … phoenix_intrusion_active == "on"` (`:180-182`) is evaluated ~2 steps before `rest_command.phoenix_alarm_mac_on` (`:188`). A disarm landing in that window (template render + `if` + service dispatch, milliseconds) still posts `mac_on` after the reset's `mac_off` has already run, and nothing re-sends `mac_off`.
Proof: step 4 is the condition, step 5 is the `if/then` whose first `then` action is `rest_command.phoenix_alarm_mac_on`. The fix narrowed a 22 s exposure to a millisecond one; it did not remove the class, because the disarm path never repeats its `mac_off`.
Fix: the 3 s delayed re-send in F2, which closes the window by construction.

**F6 — CRITICAL — the fix was then "verified" only in the one mode that cannot exercise it.**
Claim: a test-mode drill suppresses exactly the two steps the fix protects (the `mac_on` and the loop), so a drill passing proves nothing about F5.
Proof: `initial_response:184-194` gates both the siren and the loop behind `if not test_mode`. Measured drill: at 14:16:10 `script.phoenix_test_intrusion_sequence` started, `test_mode` and `active` both → on, `initial_response` ran 14:16:10→14:16:40, `evidence_and_page` 14:16:35→14:16:40 — and **no** `script.phoenix_intrusion_loop` entry at all, i.e. the siren step never executed. That was 23 s after the 14:15:47 config-load markers (`automation.snapshot_*_ha_start` → `unavailable`, all `zone_*` binaries recomputed in the same second), i.e. the drill ran the new code and still proved nothing about the siren race.
Fix: prove F5 with a probe that does not need a real intrusion — see F12's `/alarm` state endpoint, or a drill that stubs `rest_command.phoenix_alarm_mac_on` to a logbook write.

**F7 — HIGH — if `alarm_mac_on` fails or times out, the script aborts before the loop and before the page.**
Claim: `phoenix_security_page`/evidence is step **6**, after the siren step 5; `rest_command.phoenix_alarm_mac_on` has `timeout: 5` and **no** `continue_on_error`, so a 5 s stall or a transport error aborts `initial_response` entirely — no strobe, no page, and the Mac may still be sounding (the POST can arrive and the response be lost).
Proof: `secretary.yaml:37-40` (no `continue_on_error` key, `timeout: 5`); `phoenix_security.yaml:188` (`service:` with no `continue_on_error`); the page call is `:209`, six steps later.
Fix: add `continue_on_error: true` to the `mac_on` call **and** move `phoenix_intrusion_evidence_and_page` before the siren step (see F8).

**F8 — CRITICAL — the owner page is blocked behind the siren loop, so on a real intrusion the SMS arrived 2 h 51 m late.**
Claim: a script called as `service: script.x` is awaited by the caller, so `phoenix_intrusion_evidence_and_page` (step 6) cannot run until `phoenix_intrusion_loop` (step 5) returns — and the loop only returns when the flag drops or the cap hits.
Proof: measured, not inferred. Loop started 23:23:38; `evidence_and_page` **started at 02:14:22**, the same second the CRITICAL termination was logged, and finished 02:14:27. 2 h 51 m 01 s between the trigger and the first page attempt. In the 14:03 episode, where the loop exited immediately, the page followed within the same second.
Fix: call the loop non-blocking — `- service: script.turn_on` with `target: entity_id: script.phoenix_intrusion_loop` — or swap steps 5 and 6. The loop is a parallel annoyance, not a prerequisite for the page.

**F9 — CRITICAL — the Mac listener has no authentication, no state, no timeout, and wildcard CORS.**
Proved live, GET only: `GET /` → `404`, `GET /alarm` → `404`, body `{"ok": false, "error": "not found"}`, headers `Server: BaseHTTP/0.6 Python/3.9.6`, `Access-Control-Allow-Origin: *`, `Content-Type: application/json`, **no `WWW-Authenticate`**. See §6.

**F10 — HIGH — a stale `test_mode` turns the whole alarm silent, and nothing clears it but a human.**
Claim: `phoenix_test_intrusion_sequence` sets both booleans on and never turns either off; `test_mode` is read by `initial_response` at `:120` and suppresses lights, siren, audio and (via `event: intrusion_test`) the page.
Proof: parsed test sequence = 2 steps, both `turn_on`; measured 14:16:10 both booleans on, and at **14:17:21** a human had to turn both off and run `reset` — 71 s of a system that would have stayed silent, with a flag that also blocked every real trigger. `grep` finds no other writer of `phoenix_intrusion_test_mode`.
Fix: append two `input_boolean.turn_off` steps plus `script.phoenix_intrusion_reset` to the test script; add an automation that fires when `phoenix_intrusion_test_mode` has been on for 30 min → persistent notification + turn it off.

**F11 — MEDIUM — `mode: single` turns the long alarm into a long blind spot.**
Claim: while `initial_response` is inside the loop (up to 2 h 50 m), a second intrusion cannot start a response; combined with the flag still being on, the trigger automation's `state: "off"` condition blocks it anyway.
Proof: `:104` `mode: single`; `:43-45` trigger condition; measured `initial_response` running 23:23:21→02:14:27.
Fix: F8 makes the loop non-blocking, which shrinks this to the page-retry window (~60 s worst case).

**F12 — MEDIUM — HA cannot see the siren, so no code can verify it stopped.**
Claim: the listener exposes no readable state; every "the alarm is off" claim in the logs is a claim about a POST, not about audio.
Proof: `GET /alarm` → 404 with the JSON error body; no status route found; `rest_command` calls are not logged in the logbook, so the 12 h window in F1 is proved by *absence of a reset run*, not by an audio observation.
Fix: add `GET /alarm` returning `{"alarming": true|false}` on the Mac side, and assert it in the fail-safe automation.

---

## 3. The `repeat while` + 10,000 cap in detail

- Elapsed time of the cap, measured: **2 h 50 m 44 s** (10,244 s from loop start 23:23:38 to 02:14:22), at **1.0244 s/iteration**. Arithmetic from the YAML: mean 1,000 ms of `delay` per iteration, 10,000 iterations = 10,000 s; the 244 s excess is 24.4 ms/iteration of two service calls. The 5,000-iteration warning landed at 00:49:00, exactly 5,122 s after the loop started, which is the same rate to four significant figures — the two measurements corroborate each other.
- **Does the Mac audio stop at the cap? No.** The loop never touches the Mac (`mac_on` is `:188`, outside the loop; `mac_off` only in reset `:253`). Measured: no `mac_off` for the following 9 h 11 m 03 s.
- **Does "the probe" stop? There is no probe in the committed loop, and no probe ever runs.** The only state the loop reads is `phoenix_intrusion_active` in its `while`, and that read stops happening the moment the loop is aborted. What the loop used to have — a 15 s gate on `timer.phoenix_intrusion_loop_timer` that re-fired audio every cycle — was **deleted with the Alexas**: `git log -S "Periodic Audio Overlay"` → `de6116a` introduced it, `8102b74` ("Remove all Alexa announcements") removed it, leaving the orphan comment at `phoenix_security.yaml:246-248` and the orphan helper `timer.phoenix_intrusion_loop_timer` (`phoenix_helpers.yaml:216-218`, `duration: "00:00:15"`) which nothing starts and nothing triggers on (only Lovelace displays it, `snapshots_admin.yaml:455`). So the loop is strobe-only, the timer is dead furniture, and the "Audio" in the script's alias is a lie.
- **State left behind:** `phoenix_intrusion_active` stays **on** — measured: no state change between 23:23:21 and 11:25:25 (live `last_changed` for that entity was 14:17:21, i.e. after the 14:03 disarm and the later manual clear). Consequences: the trigger automation is blocked by `:43-45` (house unarmed for 12 h 02 m 04 s), and the strobe's last act was `turn_on`, so the lights are left **on**.
- The cap terminates only the loop: `evidence_and_page` started in the same second, so `initial_response` continued (`stop:`/abort semantics apply to the aborting script only).

---

## 4. What stops the alarm if nobody is present and no phone can be reached

**Nothing. There is no timeout, no stand-down, no second path.** Proved by exhaustion of every reference to the two objects that matter:

- `phoenix_alarm_mac_off` is called from exactly one place, `script.phoenix_intrusion_reset` (`:253`).
- `script.phoenix_intrusion_reset` is called from exactly two places: the disarm automation (`:96`) and the dashboard script button (`snapshots_admin.yaml:461`).
- The disarm automation's only triggers are `event_type: phoenix.valid_pin` (needs a human at a keypad) and `binary_sensor.phoenix_everyone_away` → `off` (needs `phoenix_user_is_here` / `phoenix_worker_is_here` / `phoenix_house_guest_mode_active` to change, and those are `input_boolean`s driven by presence automations, i.e. by a phone or a work-order flag).
- No `timer` consumes `timer.phoenix_intrusion_loop_timer`. No automation has a `for:` on the flag. No `max_duration`. The only automatic terminator in the whole chain is HA's 10,000-iteration cap, and per §3 it stops the lights, not the audio.

So with the building empty, phones off or unreachable, and HA healthy: the siren sounds until the Mac mini is powered down, a human arrives, or HA regains a presence signal. The only "second path" that exists is accidental and useless here: `Phoenix V2: Worker Auto-Arrival (GPS)` (`automations/access_control.yaml:1130-1148`) turns `worker_is_here` on when `person.montrose` or `person.bachrach` is `home`, which would disarm — but it needs a phone on the network to report `home`.

---

## 5. Is `phoenix_test_intrusion_sequence` genuinely silent?

**Audibly yes; harmless no.**

Silence, proved structurally. The script's 2 steps turn on `phoenix_intrusion_active` and `phoenix_intrusion_test_mode`, then call `initial_response`. Inside `initial_response`, `test_mode` is resolved once (`:119-120`) and:
- `:142-160` — lights off/on and the 1 s delay are inside `if: not test_mode` ⇒ **no light change at all**;
- `:184-194` — `rest_command.phoenix_alarm_mac_on` and `script.phoenix_intrusion_loop` are inside the same `if: not test_mode`, and the `else` branch is a single `logbook.log` ⇒ **no siren, no Mac audio, no strobe, no loop, no cap, no fail-safe needed**;
- `:209-214` — the page is sent with `event: intrusion_test`, which the secretary backend skips per the in-repo contract (`:117-118`, and the header comment at `evidence.yaml` — a backend claim, see unverified).

Measured confirmation: 14:16:10→14:16:40, `initial_response` ran to completion and **no `script.phoenix_intrusion_loop` logbook entry exists for that window**, which is the observable signature of the suppressed branch.

What it still does that touches the real system, all from the YAML:
1. **Leaves two real booleans on and never clears them** (F10). Measured: a human cleared them at 14:17:21.
2. **Blocks every real trigger while the flag is on** (`:43-45`).
3. **Runs `script.snapshot_entry_cameras` and `script.snapshot_control_room_cameras`** (`:125-138`) — real snapshots, and these are the cooldown-gated shared scripts whose timer `timer.phoenix_snapshot_entry_cooldown` a door automation can consume first: the documented way to lose the *next real* intrusion's door/hallway evidence (`evidence.yaml:10-16`).
4. **Eight real `camera.snapshot` calls and a disk write** through `phoenix_intrusion_evidence_and_page` (4 evidence + 4 `latest_intrusion_*.jpg` tiles), so a drill **overwrites the "latest intrusion" images** with empty rooms.
5. **Sends a real authenticated HTTPS POST** to `https://ai.abletelsolutions.com/webhook/ha/security-alert` with `x-ps-api-key` — a live request to production, silent only because the backend honours the event name.
6. **Runs `shell_command.phoenix_prune_intrusion_evidence`** (`evidence.yaml:392`), i.e. real `rm -f` deletions against `/config/www/snapshots`.
7. Logs to `input_text.phoenix_door_activity_log` on page failure.

"Silent" is a property of the backend's `intrusion_test` handling, not of the HA config: **change that contract and a drill pages the family.**

---

## 6. The Mac mini listener at 192.168.50.45:8128

Read-only probe from `zabz-tech` (office LAN), GET only:

| request | status | headers / body |
|---|---|---|
| `GET /` | **404** | `Server: BaseHTTP/0.6 Python/3.9.6`, `Content-Type: application/json`, `Access-Control-Allow-Origin: *`, `Content-Length: 35`; body `{"ok": false, "error": "not found"}` |
| `GET /alarm` | **404** | same |

- **Reachable** from this host; the listener is a Python `http.server`-style handler (`BaseHTTP/0.6 Python/3.9.6`, Python 3.9.6 = macOS system python), port 8128, HTTP/1.0, `Connection: close`.
- **No authentication** of any kind: no `WWW-Authenticate`, no 401, no cookie, no token, no query key in the HA side either — `secretary.yaml:37-45` posts to a bare URL with no `headers:` block.
- **No readable state.** `/alarm` is not a status route, so nothing (including HA) can ask whether the siren is sounding. That is why F1's 12 h window is provable only as "no off-request was sent".
- **What a LAN attacker could do:** `POST /alarm/on` — sound a full-volume siren through the overhead speakers, indefinitely, with no HA involvement and therefore nothing that would ever stop it; repeat it to keep the shop screaming. `POST /alarm/off` — silence a real intrusion alarm, defeating the alarm at the moment it matters. Both need no credentials.
- **Browser exposure:** `Access-Control-Allow-Origin: *` plus a form-encodable `POST` means it is also a **CSRF target**: any web page opened in a browser on the office LAN can fire it cross-origin (the CORS header merely lets the page *read* the reply; a simple POST needs no preflight). Combined with F9, one malicious ad on a shop PC is an alarm-silencer or an alarm-starter.
- **Fix:** require a shared secret — add `headers: {x-alarm-token: !secret alarm_token}` to both `rest_command`s and validate it on the Mac, reject with 401 otherwise; bind the listener to the LAN interface only; drop the wildcard CORS; add `GET /alarm` returning the boolean state (F12); and give the Mac a maximum autonomous run time (e.g. stop after 10 min unless `/alarm/on` is refreshed), so a lost HA cannot leave it screaming — that is the only fail-safe that survives HA being dead.

---

## 7. HA restart or power loss mid-alarm

**The siren keeps sounding; the loop does not resume; nothing resets either one.**

- **Siren:** it lives on the Mac, started by one POST, played by a launchd-persistent `python3 + afplay` process (commit `8e21f40`). HA dying does not touch it, and there is no maximum run time on the Mac side (no state endpoint, no timeout visible — §6).
- **Loop:** HA does not resume scripts after a restart, and nothing re-invokes `phoenix_intrusion_loop` on boot. Its `mode: single` is irrelevant after a restart because the script is not running.
- **Flag:** `input_boolean.phoenix_intrusion_active` is restore-backed, so it comes back **on** (the repo's own note at `phoenix_helpers.yaml:113` states that `initial:` applies only when the entity is created, which is what makes the restore the live behaviour). With the flag on, the trigger automation is blocked by `:43-45` — **the house is unarmed after a restart that interrupted an alarm**, and the alarm cannot even re-fire.
- **No startup reset exists.** `grep` for `platform: homeassistant` / `event: start` finds 14 matches in 5 files: the three in `automations/access_control.yaml` (LED mode refresh at 823, `Worker Auto-Arrival (GPS)` at 1137, `phoenix_assert_door_relays_locked_on_start` at 2205 — **relays only**), two in `keymaster`, one in `phoenix_timeline.yaml:173`, one in `climate_schedule.yaml:585`. None references `phoenix_alarm_mac_off`, `phoenix_intrusion_active`, or the loop. The global grep already proves this positively: `phoenix_alarm_mac_off` appears in two places only, and neither is a start trigger.
- **Only accidental disarm on boot:** `Worker Auto-Arrival (GPS)` runs on `event: start` and can set `worker_is_here` on if `person.montrose`/`person.bachrach` is `home`, which flips `everyone_away` off and thus fires the disarm — i.e. a restart disarms *only if a worker's phone is at home*, which is exactly the situation that cannot help an empty building.
- **Lights** are left in whatever state the loop's last step produced (`turn_on`), and nothing on boot normalises them until a reset runs.
- **Observed, not assumed:** the 14:15:47 markers (`automation.snapshot_hallway_loop_start_ha_start` and `automation.snapshot_control_room_loop_start_ha_start` → `unavailable`, all `zone_*` binaries recomputed in the same second) are consistent with a config load, but I could not distinguish a reload from a restart from the API, so I do not claim a restart was observed — §7 is proved from the config, not from that event.
- **Fix:** the `homeassistant.start` branch of the F2 automation — POST `alarm_mac_off` unconditionally on boot. It is safe: a genuine intrusion re-arms in 6 s of grace plus a 16–20 s snapshot block, so silencing on boot can never mute a live event, and it converts an unbounded siren into one that ends at the next reboot. Add the Mac-side maximum-run-time as the second, HA-independent layer.

---

## What I could not verify

- **Whether the Mac actually emitted audio for 12 h 01 m 47 s** (or 1 m 57 s at 14:03). I proved no `alarm/off` was requested in that window and that the listener is reachable and unauthenticated, but the device exposes no state (`GET /alarm` → 404), and `rest_command` calls leave no logbook entry. F1 is a claim about requests, not about sound.
- **Whether the 14:03:43 POST and the 02:14:22 page actually reached their targets.** The page ran 5 s and needed no retry, which is consistent with `ok: true` on attempt 1; HA logs do not carry the response body, and I did not read `sms_log` (out of scope for W3).
- **The secretary backend's `intrusion_test` skip.** §5's silence depends on the backend honouring `event: intrusion_test`; that is a claim in the HA comments (`phoenix_security.yaml:117-118`), and I did not read `personal-secretary-mvp` in this session. Change that contract and a drill pages the family.
- **Whether the listener binds to `0.0.0.0`, and whether it is reachable over Tailscale or from the home network.** I proved reachability and no auth from `zabz-tech` on the office LAN only. I deliberately did **not** send any request to `/alarm/on` or `/alarm/off` by any method, including GET, because a sloppy handler could treat a GET as a trigger.
- **Whether today's `condition` fix is deployed on the live HA.** The file at `e6b45f6b1c04` contains it and the drill at 14:16:10 ran after the 14:15:47 config-load markers, but I could not read the live script source, and the drill bypasses the fixed branch (F6). Deployment of the fix is therefore **unproven**.
- **The 10,000-iteration cap itself as an HA constant.** I used the given CRITICAL log line and the arithmetic that corroborates it; I did not read HA's source for the constant.
- **Why the snapshot block took 20 s at 14:03 and 16 s at 23:23** — I measured both, and did not investigate the camera timing.
