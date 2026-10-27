# W8 — Can this security system STAY working, and how would anyone know if it broke again?

**LOCAL (zabz-tech)** · 2026-10-26 · read-only audit (no edits, no state changes, no restarts, nothing sent)

## STEP 0 — revision check: PASS

```
pwd  -> C:\Users\ezabz\Code
e6b45f6b1c04  phoenix_security.yaml          2026-10-26T14:08:52  14472 B
6ff9a7142d0d  phoenix_intrusion_evidence.yaml 2026-10-26T14:13:15  23651 B
```
Both match the expected hashes, so every finding below is against the current checkouts. `(Get-FileHash … -Algorithm SHA256).Hash.ToLower().Substring(0,12)`.

Live reads used: `/api/states` (1,036 entities), `/api/services` (64 domains), `/api/error_log` (63 lines), and `/api/logbook/<ts>?entity=…` (read-only GET) for the timing proof.

One HA-source read was needed to settle mechanism rather than guess: `raw.githubusercontent.com/home-assistant/core/2025.10.3/homeassistant/helpers/script.py` and `.../components/shell_command/__init__.py`, saved to `_scratch/audit-2026-10-26/`.

---

# THE HEADLINE

**The page is sent after the alarm is over, not when it starts — and on 2026-10-25 that was 2 h 51 min after the trigger.** `phoenix_intrusion_initial_response` calls `script.phoenix_intrusion_loop` as a *blocking* service call, before the evidence + page step. Logbook, verbatim:

```
10/25 23:23:21  input_boolean.phoenix_intrusion_active -> on
10/25 23:23:21  script.phoenix_intrusion_initial_response  started
10/25 23:23:38  script.phoenix_intrusion_loop              started
10/26 02:14:22  script.phoenix_intrusion_loop              off      <- 2 h 50 m 44 s
10/26 02:14:22  script.phoenix_intrusion_evidence_and_page started  <- the page step, 2 h 51 m late
10/26 02:14:27  script.phoenix_intrusion_evidence_and_page off      <- 5 s: aborted on the `for` defect
10/26 02:14:27  script.phoenix_intrusion_initial_response  off
10/26 11:25:25  input_boolean.phoenix_intrusion_active -> off        <- 12 h 02 m latched
```

The loop ended at 02:14:22 not because anything disarmed it but because Home Assistant kills a `repeat: while:` at 10,000 iterations — `script.py:293 REPEAT_WARN_ITERATIONS = 5000`, `script.py:294 REPEAT_TERMINATE_ITERATIONS = 10000`, raised at `script.py:871-883`. That is the same 5,000/10,000 pair already measured today; this is its mechanism, and it is HA's cap, **not** the config's. `config/packages/phoenix_security.yaml:219-248` has no `count:`, so nothing in the file bounds the loop.

Same night, same pattern, shorter: 19:57:45 → 21:01:04 (page 63 min late), 21:38:24 → 21:38:59 (29 s), 16:59:15 → 16:59:21 (6 s). **The delay equals the alarm duration. A real intrusion is never disarmed, so a real intrusion is never paged on time.**

---

# 1. Every other place a command, template or service call can fail silently

### 1.1 CRITICAL — A dead Mac mini siren suppresses the owner page entirely
`config/packages/phoenix_security.yaml:188` calls `rest_command.phoenix_alarm_mac_on` with **no** `continue_on_error`, and the page step is at line 209, *after* it. A 5 s timeout against `http://192.168.50.45:8128/alarm/on` (`config/packages/secretary.yaml:37-45`) raises, the script aborts, and steps 3 (evidence + page) never run. The loudest failure is silent by construction: the one hardware that makes noise is the one whose failure removes the notification.
**Proof:** the call site has no `continue_on_error` (read at 14:08 today); `script.py:479-481` — any other exception sets `script_execution_set("error")` and re-raises, ending the sequence.
**Fix:** add `continue_on_error: true` to that call *and* move the evidence + page block above the siren.

### 1.2 CRITICAL — The page-retry loop and its "fail LOUD" branch are unreachable
`config/packages/phoenix_intrusion_evidence.yaml:344-351`: on a failed retry it does `- stop: "page not confirmed - retrying"`. `stop` is not `break`: `script.py:948-968` raises `_StopScript`, caught at `script.py:470-477` at the **run** level, which ends the whole script. So the first failed retry (attempt 2 of 5) ends everything: attempts 3-5 never happen, the `persistent_notification` "SECURITY PAGE FAILED" (lines 356-380) never fires, the audit logbook line never fires, and the retention command at line 392 never runs.
**Proof:** source above; plus `/api/states` shows **zero** `persistent_notification.*` entities right now, i.e. that notification has never once been created.
**Fix:** remove the `stop`; wrap the retry in `if not page_ok` and let the `repeat` run to completion, or `stop` only on success.

### 1.3 HIGH — Retention is downstream of paging success (this is the 40-day link)
`phoenix_prune_intrusion_evidence` is the **last** step of `phoenix_intrusion_evidence_and_page` (line 392). Anything that aborts that script — the `for` defect (until 14:08 today), a failed retry via 1.2, an undefined `evidence_check` — also skips the prune. The retention code was fine; it was simply never reached.
**Proof:** the defect-notes in that same file, plus 1.2. 48 `intrusion_*.jpg` files, oldest Sep 16, was the symptom.
**Fix:** move the prune into the housekeeping automation (24 h timer) instead of a script that runs once per intrusion.

### 1.4 HIGH — `shell_command` never reports a non-zero exit as an error
`shell_command/__init__.py:128-131`: `if process.returncode != 0: _LOGGER.exception("Error running command: …")`. It **logs and continues**; it does not raise, and it still returns `{stdout, stderr, returncode}`. So `continue_on_error: true` on a shell command protects nothing, and every caller that does not read `returncode` cannot tell success from failure.
**Proof:** source above. `config/packages/phoenix_timeline.yaml:176-187` then writes the logbook line **"Evidence retention pass ran. …"** unconditionally, printing `stdout` — which is empty on failure. The audit trail asserts success for a failed prune.
**Fix:** `condition: template value_template: "{{ phoenix_purge_result.returncode | default(1) == 0 }}"` before the logbook line, and a persistent notification on the else branch.

### 1.5 HIGH — 6 `nohup` shell_commands cannot report failure at all
`config/packages/phoenix_timeline.yaml:41-81`: `phoenix_clip_doorbell_ring`, `phoenix_clip_person_doorbell`, `phoenix_clip_outside_door`, `phoenix_clip_interior_door`, `phoenix_still_waiting_room`, `phoenix_still_control_room_exit`. Every one ends `nohup python3 … >>/dev/null 2>&1 &`. Three consequences, all structural: the shell returns 0 the instant it backgrounds, so `returncode` is always 0; stdout/stderr are discarded, so the Python error is gone; and `phoenix-clip.py` documents `Exit: 0 if every requested camera produced a clip, 1 otherwise` (line 54) — an exit code nobody can read. The only surviving record is `/media/phoenix/capture.log`, which nothing watches and which rotates at 2 MB to `.1` (lines 107-113).
**Fix:** have the wrapper append one line to a file HA can age-probe (newest clip mtime), and add a template sensor that goes `problem` when the newest clip is older than 24 h while triggers are firing.

### 1.6 MEDIUM — `phoenix_timeline_regen` ends in `|| true`
`phoenix_timeline.yaml:85-86`. A generator that fails is indistinguishable from one that ran. It has been on a daily 04:45 trigger since 2026-10-18 with no assertion that it produced a file.
**Fix:** drop `|| true`, read `returncode`, notify on failure.

### 1.7 MEDIUM — `rest_command.secretary_ptt` fails silently by an undefined variable
`config/packages/secretary.yaml:61-64`: the PTT command has no `continue_on_error` and no retry, then a `condition: template` reading `ptt_response.status`. When the transport fails, `response_variable` is never set, the condition raises, and the automation aborts. `mode: single`, `max_exceeded: silent`. Push-to-talk simply does nothing, silently.
**Fix:** `continue_on_error: true` on the call plus `ptt_response.status | default(0) == 200`.

### 1.8 The full `rest_command` inventory (5 + 1 built-in)

| name | URL | method | timeout | failure observable? |
|---|---|---|---|---|
| `phoenix_security_page` | `https://ai.abletelsolutions.com/webhook/ha/security-alert` | POST, JSON, `x-ps-api-key` | 15 s | **only in theory** — 1.2 makes retries and the notification unreachable; and by ordering (header) it runs after the alarm |
| `secretary_ptt` | `https://ai.abletelsolutions.com/webhook/ha/push-to-talk` | POST, JSON | 10 s | no — 1.7 |
| `phoenix_alarm_mac_on` | `http://192.168.50.45:8128/alarm/on` | POST | 5 s | **no, and fatal** — 1.1 |
| `phoenix_alarm_mac_off` | `http://192.168.50.45:8128/alarm/off` | POST | 5 s | no — and it is the *only* off switch (`phoenix_intrusion_reset:253`) |
| `reload` | — | — | — | built-in service of the integration |

### 1.9 LOW — `command_line` sensors: there are none
`command_line:` appears **0 times** across `config/**/*.yaml`; `sensor:` in `configuration.yaml` holds only two `platform: filter` entries (lines 390-407). Nothing to fix — but the same silent-failure shape lives in the `template:` sensors: `configuration.yaml:366-388` derives all three door contacts, and each carries `availability:` so a lost zigbee device turns the derived sensor `unavailable` — which the alarm's `to: "on"` trigger can never fire on. **A dead contact is an invisible hole, not an alert.**

---

# 2. What rots: every cooldown, latch, log and counter in the security path

### 2.1 CRITICAL — `input_boolean.phoenix_intrusion_active`
**Set by:** the trigger (`phoenix_security.yaml:76-78`) and the drill (`:263-267`). **Cleared only by** `phoenix_extreme_intrusion_disarm` (`:93-96`), which needs a `phoenix.valid_pin` event or `binary_sensor.phoenix_everyone_away → off`.
**Measured consequence:** latched **12 h 02 m** (10/25 23:23:21 → 10/26 11:25:25). During that window `phoenix_security.yaml:43-45` blocks every new trigger, so the building is not alarmed; the loop had already been aborted at 10,000 iterations, so nothing was sirening; and `phoenix_intrusion_reset` — the only caller of `alarm_mac_off` — ran at **11:25:25**, so the overhead alarm was switched off by a person arriving the next morning. The system spends that whole window reporting "in alarm" while doing nothing at all.
**Fix:** bound it — a `timer` armed with the boolean, and an automation that clears both at expiry.

### 2.2 CRITICAL — `input_boolean.phoenix_intrusion_test_mode`
**Set by:** the drill (`:263-267`). **Cleared by: nothing.** Grep across every YAML finds exactly one `turn_on` and no `turn_off`; the only other reference is a dashboard toggle (`config/lovelace/snapshots_admin.yaml:451,471`). It is a human-only reset.
**Consequence:** left on, the next **real** intrusion is silent — lights off, no siren, no loop, and the page goes out as `intrusion_test`, which the backend refuses to send (`personal-secretary-mvp/app/main.py:8594`: `if not force and event in ("intrusion_test", "test_drill", "test")`). Only evidence is written. This is the single most dangerous latch in the system: a forgotten drill converts the alarm into a camera.
**Fix:** clear it at the end of `phoenix_test_intrusion_sequence` and on every `everyone_away → off`.

### 2.3 Rot table (the rest)

| entity | what sets it | what clears it | consequence if left wrong |
|---|---|---|---|
| `timer.phoenix_snapshot_entry_cooldown` 30 s | `scripts.yaml:218-223`, top of `snapshot_entry_cameras`, for **every** caller | expiry only — no `cancel` anywhere | a cooldown taken by an unrelated door automation makes the next real caller `stop` at `:217` and write no evidence (this is the 2026-09-16 defect) |
| `timer.phoenix_snapshot_hallway_cooldown` 60 s / `…control_room_cooldown` 15 s | same pattern (`:344`, `:441`) | expiry only | same class |
| `timer.phoenix_snapshot_breaker` 30 min | `scripts.yaml:103-105` after 3 consecutive probe failures | expiry only | 30 min with **no snapshot from any script that uses `snapshot_latest_with_retries`**; only a logbook line on `script.snapshot_latest_with_retries` says so. Intrusion evidence is immune (it bypasses this), the Lovelace tiles are not |
| `counter.phoenix_snapshot_consecutive_failures` | increment/reset `scripts.yaml:91-97`; reset again when the breaker opens | reset on any success | `restore: true`, so a stale 2 survives a restart and the next single failure opens the breaker |
| `timer.phoenix_invalid_pin_window` 5 min + `counter.phoenix_invalid_pin_attempts` | `script.phoenix_access_control_register_invalid_attempt` | `phoenix_invalid_pin_window_reset`, `…lockout_finished` | threshold 5 in 5 min → lockdown |
| `timer.phoenix_access_control_lockout` (2 min, from `input_number.phoenix_access_control_lockout_minutes`) | `access_control.yaml:260-264` when lockdown is on and lockout idle | `phoenix_access_control_lockout_finished` | while active, **every** access event is ignored (`access_control.yaml:251`) and the only trace is `system_log.write` level warning; the door will not buzz and nobody is told |
| `input_boolean.phoenix_access_control_enabled` | human / UI | human | off = access control silently stops responding; no watchdog |
| `input_boolean.phoenix_user_is_here`, `…worker_is_here` | 5 arrival automations (PIN context + room occupied, BLE + room occupied, GPS) | `phoenix_auto_departure_smart_timer` only: occupied off for 5 min (unanimous) or 10 min (safety) | stuck ON = **never arms**, no intrusion detection at all; stuck OFF = alarm while someone is inside. Live right now: `worker_is_here = on` since 14:15:11 |
| `input_boolean.phoenix_house_guest_mode_active` | guest PIN paths (`access_control.yaml:224,294,486,530`) | night reset (`:2356`), empty-shop watchdog (`:2376-2405`), presence-follow (`:1461`) | stuck ON = `phoenix_everyone_away` never true = never arms. The only latch in the system with a real watchdog |
| `input_boolean.phoenix_sim_control_room_presence` | a human, from the dashboard | a human | ON makes `zone_control_room_occupied` true forever → auto-departure can never fire → never arms. **No watchdog.** |
| `input_text.phoenix_access_control_log`, `phoenix_door_activity_log` | ~15 sites | never cleared; `max: 255` hard truncation (`phoenix_helpers.yaml:90-96`) | it is a 255-character display buffer, not a log. Live value: 6 lines then cut. Anyone reading it as the audit trail is reading a window |
| `input_select.phoenix_security_mode` | 7 automations maintain Home/Customer/Away/Armed | same | **the alarm never reads it** — `phoenix_security.yaml` does not reference it once. Two notions of "armed", one of them decoration |
| `timer.phoenix_house_access_timer` 2 h + `input_boolean.phoenix_house_access_pin_enabled` | `house_access_pin_control_timer` | `house_access_pin_timer_finished` turns both off and clears the PIN; `house_access_pin_auto_reset` is the belt | a cancelled timer without the clear leaves a temporary PIN valid indefinitely |
| `timer.phoenix_intrusion_loop_timer` 15 s | **nothing** | **nothing** | dead config; it is on the dashboard (`lovelace/snapshots_admin.yaml:455`), so it *looks* like the loop is bounded. It is not — HA's 10,000 cap is |
| `timer.phoenix_housekeeping_last_purge` 24 h / `…purge_retry` 12 h | `phoenix_timeline.yaml:179-182` | expiry; re-armed unconditionally right after the shell_command | **the overdue alarm can never fire on a failed purge** — `phoenix_housekeeping_prune_overdue` only fires when `last_purge` is `idle`, and it is re-armed whether the purge worked or not (1.4) |
| `timer.hallway_guard_window` 2 min | every buzz (`access_control.yaml:623-626`), extended on people detection (`:1630-1632`) | `security_mode_revert_after_hallway_window` (`:1474`) | while active it suppresses the mode revert; cosmetic, but it is on the dashboard as if it gated something |

---

# 3. Can an alarm be regression-tested without a real alarm?

**Yes — the drill is already built, already silent, already page-free, and it is not safe to run unattended for three reasons.**

`script.phoenix_test_intrusion_sequence` (`phoenix_security.yaml:259-268`) turns on `phoenix_intrusion_active` **and** `phoenix_intrusion_test_mode`, then calls `phoenix_intrusion_initial_response`.

- **Does it page anyone?** No. `test_mode` renders `event: intrusion_test` (`:213`) and the backend refuses that event without `force` — verified in source at `personal-secretary-mvp/app/main.py:8594`, not assumed from the comment.
- **Does it make noise?** No. Lights (`:142-160`) and siren/loop (`:184-194`) are both behind `if not test_mode`; test mode instead writes one logbook line. Evidence capture still runs.
- **Does it leave state behind?** **Yes, three ways.** (a) `phoenix_intrusion_active` stays ON — nothing in the script clears it, only the disarm automation does; measured today: drill started 14:16:10, both flags cleared at 14:17:21 by a human, 71 s later. (b) `phoenix_intrusion_test_mode` stays ON and **no YAML anywhere clears it** (2.2). (c) it writes 8 real JPEGs (4 timestamped + 4 `latest` tiles) that count against the 120-file cap.
- **Who turns it off?** A human, by hand. That is the whole answer, and it is why the drill cannot be a test today.

### The smallest automated check that would have caught today's defect, in under a minute

**Check A — 1 second, no state change, catches the exact defect.** Call the verifier directly with a file that certainly exists:

```
action: shell_command.phoenix_verify_evidence_files
data: { files: "/config/configuration.yaml" }
```
Assert the call **returns** (does not raise) and `response.stdout` contains `PHOENIX_EVIDENCE_OK /config/configuration.yaml`. Before 14:08 today this call raised `[Errno 2] No such file or directory: 'for'` immediately — the whole 40-hour outage, caught in one second, with no alarm, no siren and no page.

**Check B — 8 lines, catches the *ordering* defect (the headline).** Template trigger, so no alarm is needed:

```
trigger: state  entity_id: input_boolean.phoenix_intrusion_active  to: 'on'  for: '00:01:00'
condition:
  - condition: state      entity_id: input_boolean.phoenix_intrusion_active  state: 'on'
  - condition: template   value_template: "{{ not is_state('script.phoenix_intrusion_evidence_and_page','on') }}"
action: persistent_notification.create + notify.mobile_app_iphone_15
```
This fires at 23:24 on 10/25, at 19:58, at 21:39 — every time the page lagged. It needs no camera, no siren and no door.

**Check C — once the drill self-cleans (2.2 fix + clear `intrusion_active` at the end), the drill itself becomes the 40-second end-to-end regression test**: one call, assert the two booleans are `off` 60 s later and that 4 new files exist. That is the test worth having.

---

# 4. What monitoring exists over HA itself? (almost none)

### 4.1 CRITICAL — there is no host telemetry whatsoever
The states scan for `sensor.(disk|free|memory|swap|cpu|processor|load|uptime|last_boot|home_assistant|database|recorder|core|supervisor|host)` returns **only** the backup integration's four sensors. No disk free, no memory, no CPU, no HA uptime, no restart counter, no add-on health, no DB size. The 6.8 GB-free arithmetic that justifies every retention bound was measured by hand on 2026-09-15 and is not instrumented.
**Proof:** `/api/states`, 1,036 entities, filtered as above; the only hits are `sensor.backup_backup_manager_state / last_attempted / last_successful / next_scheduled`.
**Fix:** `default_config` already enables the `systemmonitor`-adjacent pieces — add a `platform: systemmonitor` block (disk_use_percent on `/config`, memory_free, processor_use) and one numeric_state alert on disk above 85 percent.

### 4.2 CRITICAL — 35.7 percent of the estate is unavailable and nothing says a word
370 of 1,036 entities are `unavailable`/`unknown` (sensor 130, automation 49, device_tracker 48, input_text 45, script 19, switch 15, camera 4, lock 1, siren 1). Across the whole config only **4** automations react to `unavailable` — the two ESPHome hubs and the beacon (`system_health_monitoring.yaml:57`, `control_room_hub_health_monitoring.yaml:52`, `presence_beacon.yaml:64,69`). There is no generic availability guard and **zero battery alerts**, while the three perimeter contacts read 51, 48.5 and 47.5 percent.
**Fix:** one template sensor counting `unavailable` over a named security roster + a `numeric_state above 0 for 10 min` alert. Fifteen lines.

### 4.3 HIGH — the only error surface is a ring buffer that dies on restart
`/api/error_log` returned **63 lines**, first line `2026-10-26 14:14:59 … We found a custom integration hacs`. HA restarted at 14:14:59 today, so everything before that is gone. Anything that only appears there — every non-zero shell exit (1.4), every failed `rest_command` — has a lifetime of one restart.
**Fix:** none needed in HA; the journal/logrotate side must own it. In HA, convert the things that matter into entities (see 4.1, 4.2).

### 4.4 HIGH — a genuinely dead camera, caught by nothing
Live, in today's core log:

```
14:16:36.392 WARNING [custom_components.dahua] Dahua snapshot failed … (name=Cam Larry's Interior Main, channel_number=2): ClientResponseError(… 400, 'Bad Request', url='https://192.168.50.170/cgi-bin/snapshot.cgi?channel=2')
14:16:36.410 ERROR [homeassistant.components.script.phoenix_intrusion_evidence_and_page] … Parallel action at step 2: parallel 4: If at step 1: … Dahua snapshot failed for Cam Larry's Interior Main
14:16:39.241/247  same pair again, step 3
```
One of the four evidence cameras has been failing every single capture with HTTP 400, on both the timestamped pass and the `latest` tile pass. The roster guard at `phoenix_intrusion_evidence.yaml:176-185` tests `not in ['unknown','unavailable']` — the entity is `idle`, so the guard passes, the call fails behind `continue_on_error`, no file is written, and the verifier simply reports 3 of 4. **A drill today would have "passed" with a quarter of the evidence missing.** Note also that the documented roster comment ("ONLY the first four exist … `cam_waiting_room_main`, `cam_deserted_exit_main` are absent") is now stale: `/api/states` shows both present and `idle`, plus `cam_larry_s_*` in use and `cam_deserted_exit_main` unused.
**Fix:** assert `snapshot_count == 4` in the evidence script and notify on the difference; then either fix channel 2 or drop it from the roster.

### 4.5 `system_health` — grep result
Every hit is a custom component's own registration (`custom_components/hacs/system_health.py`, `custom_components/keymaster/system_health.py`), which feeds the UI's System Health **page**. Zero references in `configuration.yaml`, `packages/` or `automations/`. It is a page a human must open; it creates no sensor and sends no alert.

### 4.6 The two failures in question: would anything have caught them?

**The 40-day retention failure — no.** The signals that existed: one `ERROR … Error running command … return code: N` line per night in a ring buffer that is wiped on restart (4.3), and a logbook line that actively asserts **"Evidence retention pass ran"** on failure (1.4). The one automation written to catch it, `phoenix_housekeeping_prune_overdue`, is defeated by its own condition (2.3 last row). 40 days, zero notifications.

**The 2-day paging failure — no.** Every channel was dead at once: the persistent notification and the logbook line sat behind the same `stop` that aborted the script (1.2); the `rest_command` warning went to the ring buffer; the audible alarms that did fire were the *siren*, not a "page failed" signal; and the SMS never arriving has no watchdog on either side. `/api/states` shows no `persistent_notification.*` entity exists at all.

### 4.7 LOW — 23 pending updates, nothing surfaces them
`update.*`: 23 `on`, 9 `off`, 4 `unavailable`. On a security box, HA core and Tailscale updates are a known periodic breakage source and there is no "updates pending" reminder.

---

# 5. Every hardcoded value that must be edited when reality changes

| value | where | what breaks when it goes stale |
|---|---|---|
| `0x286d97000115ca7a` outside-door contact | `configuration.yaml:370-372` (the template **the alarm depends on**), `outside_door_stuck_open.yaml:39,48,51,52`, `climate_health.yaml:158,168`, `zigbee2mqtt/configuration.yaml:48` | re-pairing the sensor yields a new IEEE. `is_state()` on the old id is `False` forever and `availability:` only helps if HA knows the entity vanished. A zone of the perimeter alarm goes quiet and **nothing reports it** — this is the worst single literal in the config |
| `0x002446fffd0a4705` apartment deadbolt | 9 sites: `access_control.yaml:195,248,319,364,455,510,554,1943`, `scripts.yaml:1309-1327`, `lovelace/phoenix.yaml:83`, `ui-lovelace.yaml:290` | lock replaced or re-paired → every PIN/unlock path silently no-ops on a non-existent target |
| `camera.cam_*_smart_motion_human_2` (the `_2` is load-bearing) | `presence_architecture.yaml:40-41,61-62` | the Dahua integration re-creates entities without the suffix → `zone_hallway_active` loses its camera half and the alarm degrades to door contacts only. The file's own comment records this exact failure once already |
| camera roster (4 entity ids) | `phoenix_intrusion_evidence.yaml:126-133` | one is broken right now (4.4); the rest are fine but the comment beside them is stale |
| NVR channel table ch1/5/6/7/8 | `timeline_tools/phoenix-clip.py:95-102` | a camera moved to another channel produces clips named after the wrong camera — the documented 2026-09-15 defect, invisible because of `nohup` (1.5) |
| `192.168.50.170` (NVR) | `phoenix-clip.py:81` | every clip and every NVR still dies silently |
| `192.168.50.45:8128` (Mac mini alarm) | `secretary.yaml:38,43` | siren dies **and, today, the page dies with it** (1.1). DHCP change is enough |
| `192.168.50.34:8123` (`!secret phoenix_external_base_url`) | `scripts.yaml:225-230` | only builds URLs inside log messages — cosmetic, and worth knowing it is not load-bearing |
| `ai.abletelsolutions.com` (2 rest_commands) | `secretary.yaml:20`, `phoenix_security.yaml:286` | host or tunnel change → paging and push-to-talk both dead; paging should retry and notify (1.2) but does not |
| `notify.mobile_app_iphone_15`, `notify.mobile_app_zabz_waze` | `outside_door_stuck_open.yaml:89,96` | renaming the phone in the companion app renames the service; the push is `continue_on_error`, so the stuck-door alert just stops arriving |
| `person.montrose`, `person.bachrach`, `device_tracker.monty`, `device_tracker.zabz_ble_tracker` | `access_control.yaml:1134,1141`, `presence_architecture.yaml:272,297` | passive/GPS arrival stops firing → the only way to disarm is a PIN, and auto-departure will arm with somebody inside |
| timeouts and durations (30 s entry cooldown, 60 s hallway, 15 s control room, 30 min breaker, 2 min lockout, 5 min invalid-PIN window, 5/10 min auto-departure, 24 h/12 h housekeeping, 14-day/120-file evidence bound) | spread across `configuration.yaml`, `scripts.yaml`, `phoenix_snapshot_cameras.yaml`, `phoenix_helpers.yaml`, `phoenix_intrusion_evidence.yaml:89-90`, `presence_architecture.yaml:99,105` | each is a quiet behaviour change with no single place to look; the auto-departure pair is the one that decides when the building arms |
| phone numbers | **not in HA** — the alert roster lives in the secretary backend (`app/main.py:8538`) | not verifiable from this checkout; out of scope, flagged |

---

# 6. Ranked shortlist: most reliability for the least work

Effort is the edit and the reload, not the thinking.

1. **Delete the `stop` in the page-retry loop** (`phoenix_intrusion_evidence.yaml:351`). Unblocks retries 3-5, the "PAGE FAILED" notification, the audit line and the prune. **5 min.** Highest ratio in the list.
2. **Make the drill self-cleaning**: at the end of `phoenix_test_intrusion_sequence`, turn off `phoenix_intrusion_test_mode` and `phoenix_intrusion_active`. Removes the "silent real alarm" latch and turns the drill into a usable regression test. **5 min.**
3. **`continue_on_error: true` on `rest_command.phoenix_alarm_mac_on`** (`phoenix_security.yaml:188`). A dead speaker can no longer suppress the page. **2 min.**
4. **Reorder `phoenix_intrusion_initial_response`**: evidence + page first, siren second, and start the loop with `script.turn_on` instead of a blocking `script.` call. Kills the 2 h 51 min page lag and the "someone is inside, then the siren starts" inversion. **15 min.**
5. **Check A as a saved script + dashboard button** (the one-second verifier assertion above): would have caught the 40-hour outage on day one. **10 min.**
6. **Check B sentinel** (the template trigger above): `intrusion_active` on for 60 s with no page started → notification + push. Catches the ordering defect and any future repeat of it, without an alarm. **15 min.**
7. **Read `returncode` in the housekeeping automation** and notify on non-zero; assert oldest `intrusion_*.jpg` is younger than 15 days. Turns "retention ran" from a claim into a measurement. **15 min.**
8. **Availability guard over a named security roster** (3 cameras, 3 contacts, 2 hubs, 1 lock) + battery below 25 percent on the three perimeter contacts. **20 min.**
9. **Bound `phoenix_intrusion_active`** with a timer so a real alarm cannot latch for 12 hours and silently disarm the building. **10 min.**
10. **Move the evidence prune into the 24 h housekeeping** instead of the intrusion script, so paging success is no longer a precondition for retention. **10 min.**
11. **Fix or drop `cam_larry_s_interior_main`** (HTTP 400 on channel 2) and assert `snapshot_count == 4`. **10 min** plus whatever the NVR needs.
12. **Delete `timer.phoenix_intrusion_loop_timer`** from the dashboard, or use it — right now it advertises a bound that does not exist. **3 min.**

Items 1-4 are one sitting (about 30 minutes) and remove the three defects that produced today's incident.

---

# What I could not verify

- **The Mac mini alarm at `192.168.50.45:8128` is untested.** Reaching it means POSTing to `/alarm/on`, which would sound the siren — forbidden under read-only. So "the siren is reachable" and "the siren really ran for 12 h on 10/25" are both unproven; what is proven is that `alarm_mac_off` is only reachable via `phoenix_intrusion_reset`, which last ran at 11:25:25.
- **What turned `phoenix_intrusion_active` off at 14:03:29 today.** The logbook shows the boolean changing but no `phoenix_extreme_intrusion_disarm` trigger and no `phoenix_intrusion_reset` run at that time, while the file's own comment says a human reset the siren at 14:05:40 (also absent from the script log). Somebody touched it outside the automations — most likely a dashboard toggle or a direct service call. I cannot attribute it, and I did not touch state to find out.
- **Whether HA's 10,000-iteration abort leaves the siren sounding.** The loop's abort raises `_AbortScript`; `alarm_mac_off` is only called by the reset script, so by code it should keep sounding — but that depends on the Mac listener's own behaviour, which I could not probe.
- **Add-on health, supervisor state, disk free, DB size, and the actual prune exit codes on the host.** No REST surface for these and no shell on the HA box; the `/api/states` scan proves no such sensor exists, which is the finding, but the live numbers are unknown.
- **The secretary backend's roster, retry and `paged:false` behaviour beyond line 8594** of `app/main.py` (a recursive grep of that repo exceeded 120 s and was killed after the relevant line was found). So "a drill pages nobody" rests on that one line plus the HA-side event rename; the full webhook handler was not read end to end.
- **Whether `prune_evidence.sh` covers the top-level `intrusion_*.jpg` files at all** — the 40-day accumulation is consistent with the script aborting, but the script itself lives on the HA host and was not read here.
- **Any of this surviving a restart.** Every timing proof above is from the logbook, which the recorder keeps 30 days (`purge_keep_days: 30`); `/api/error_log` was already down to 63 lines when I read it.
