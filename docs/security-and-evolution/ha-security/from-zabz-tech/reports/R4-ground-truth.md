# R4 — Ground truth: labelled security episodes

**LOCAL (zabz-tech)** · workstream R4 · written 2026-10-26 14:5x local (America/New_York, EDT = UTC−4; all clock times below are local unless marked Z) · read-only throughout: no edits, no service calls, no state changes, no outbound messages.

---

## 0. Step 0, and three corrections to the brief

`pwd` → `C:\Users\ezabz\Code`.

| Measurement | Value | Source (this session) |
|---|---|---|
| HA version | **2025.10.3** | `GET http://192.168.50.34:8123/api/config` → `version` |
| Entity count | **1036** | `GET /api/states` → `$st.Count` |
| Location / TZ | Home / America/New_York | same call |
| Run timestamp | 2026-10-26T18:42:51Z | `Get-Date -AsUTC` |

Three premises in the brief are wrong on this host, and every number below depends on them:

1. **The recorder holds ~30 days, not 1.8.** `r4_retention.py` pulled 24 h windows for 21 days back and counted rows per day for `binary_sensor.video_doorbell_person`: 2026-10-05 → **435 rows**, 2026-10-01 → 234, 2026-09-29 → **182**, 2026-09-26 → **0**, 2026-09-20 → 0, 2026-09-15 → 0. The retention edge is therefore between 27 and 30 days. Anyone who told you 1.8 days measured an entity's density, not the recorder's depth.
2. **24-hour chunking is real and I used it** — 5 daily history calls and 5 daily logbook calls, 2026-10-22 → 2026-10-26 (`r4_collect.py`; per-chunk row counts 3,478 / 12,958 / 153 / 2,640 / 28,039).
3. **The recording window is not continuous and that is the real constraint.** One hole dominates everything: no rows of any kind from **2026-10-23 13:03:09 → 2026-10-24 19:44:43 local (30 h 41 min)**. Recording resumed 7 seconds after a Shabbat automation step failed on the authority (`sms_log` id 4461, `2026-10-24T23:44:36Z`: "Shabbat automation problem (on): step relock_and_restore failed"). Whether HA was *down* or merely *not recording* cannot be determined from HA's own data — I have no shell on that host. Also zero rows for the whole of 2026-10-03 and 2026-10-23 for the busiest entity, so quiet-day ≠ gap and I only call a gap where a full business day has no door activity at all.

**A fourth constraint determines the denominators, and it is the one that would have made this report wrong:** `binary_sensor.phoenix_outside_door_contact` recorded **no transitions at all before 2026-10-21** (per-day counts 0 on 10-05…10-20, 55 on 10-21). Any doorbell→door statistic computed over the full month counts 15 days where the door signal did not exist and reports "no entry" for all of them. I measured that error: month-wide the answer is 11 % (137 of 1,192 clusters); restricted to the days the door sensor records, it is 62 %. **Every truth-table number below is computed on 2026-10-20 20:10 → 2026-10-26 14:43, the window in which all eleven signals are recording.** `r4_window_final.py`.

---

## 1. What the system can actually see

The alarm is not an `alarm_control_panel`. There is **no `alarm_control_panel` entity at all** (`GET /api/states`, zero matches). Intrusion is a template binary sensor plus a script, in `config/packages/phoenix_security.yaml`:

- Armed condition, `phoenix_security.yaml:12-15`: `everyone_away = NOT user_is_here AND NOT worker_is_here AND NOT house_guest_mode_active`.
- Trigger, `:21-36`: any of **three door contacts** going `on`, or `zone_hallway_active` / `zone_control_room_active` going `on`.
- Grace, `:69`: 6-second delay, then re-check, then arm.
- Disarm, `:82-96`: only two paths — a `phoenix.valid_pin` event, or `everyone_away → off`. **There is no third path and no manual disarm.**

The two zones are fused templates in `config/packages/presence_architecture.yaml`:

- `zone_hallway_active` (`:35-48`) = `cam_front_hallway_smart_motion_human_2` OR `cam_waiting_room_smart_motion_human_2` OR `video_doorbell_person` OR outside-door OR control-room-exterior-door.
- `zone_control_room_active` (`:56-65`) = `cam_deserted_exit_smart_motion_human_2` OR `cam_deserted_interior_smart_motion_human_2` OR the two control-room doors.

**All six camera human-detection sensors recorded zero transitions in 4.8 days** (`r4_zones.py`: `cam_front_hallway_smart_motion_human_2`, `cam_waiting_room_…`, `cam_larry_s_interior_…`, `cam_deserted_interior_…`, `cam_deserted_exit_…`, `cam_larry_s_exit_…` → `transitions=0` each). The comment at `presence_architecture.yaml:23-34` says these were "verified live" on 2026-09-16 and replaced dead `camera.*` tests; they are dead again. Consequence, measured over the whole window:

> **The entire intrusion-detection surface is three door contacts plus one doorbell person sensor, gated by three presence booleans.** The mmWave sensors are not alarm inputs — `mmwave_on_edges=0` inside every armed window (`r4_zones.py`). Neither are the eight Dahua/Reolink camera alarms.

This is why ten of the eleven episodes in the dense window were triggered by `zone_hallway_active` and one by a door contact directly (`r4_truth.py`, "EPISODE TRIGGER SOURCES"): with the camera half dead, `zone_hallway_active` *is* `video_doorbell_person OR outside door OR control-room exterior door`.

---

## 2. Every intrusion episode in the window I can see

11 in the dense window plus 2 on 2026-10-21, all with full signal coverage; 2 more (2026-10-11, 2026-10-18) exist in the month but predate door-contact recording and are listed separately as under-determined.

Renumbered for this report: **A, B** (2026-10-21) then **E1–E11** (2026-10-22 → 2026-10-26).

### A — 2026-10-21 17:51:46, armed 302 s
- **Trigger:** `video_doorbell_person` on at 17:51:40, off 17:51:45, armed 17:51:46 (+6 s = the grace window expiring).
- **Presence signals:** `everyone_away` on throughout; no door contact, no mmWave, no credential until 17:56:39.
- **Second-by-second:** 17:56:39 doorbell person on → 17:56:47 outside door opens → 17:56:48 control-room mmWave on → 17:56:48 `worker_is_here` on → 17:56:48 `everyone_away` off → 17:56:48 intrusion off.
- **Human there?** 300 s after the trigger, yes — and that person is what ended it.
- **Evidence that settles it:** outside-door contact at +301 s and simultaneous worker credit; the shot was of someone arriving at a closed door, then opening it five minutes later.

### B — 2026-10-21 19:46:48, armed 300 s
- **Trigger:** `video_doorbell_person` 19:46:42 → armed 19:46:48 (+6 s); no door contact anywhere near the trigger.
- **Disarm:** 19:51:48 `worker_is_here` on → `everyone_away` off → intrusion off. The control-room mmWave only fired at 19:51:50, **2 s after** the credit, so the credit came from GPS (`automation.phoenix_v2_worker_auto_arrival_gps`, `last_triggered` 10/24 7:45 PM), not from the room.
- **Human there?** Yes, at 19:51:48 — 5 minutes late.
- **Evidence:** worker boolean + `AWAY off` at the same second, with the mmWave trailing it.

### E1 — 2026-10-22 08:43:59, armed 959 s (16 min)
- **Trigger:** doorbell person on 08:43:53 (Reolink fired twice: 08:43:53 and 08:43:58) → `zone_hallway_active` on → armed 08:43:59. Logbook: "Phoenix: Extreme Intrusion Trigger … triggered by state of binary_sensor.zone_hallway_active".
- **Presence second-by-second:** 08:43:53 person on; 08:43:58 person off/on; 08:43:59 armed; 08:44:04 person off. **Then nothing for 15 minutes** — no door, no mmWave, no doorbell. 08:59:54 person on again; **08:59:56 outside door opens**; 08:59:59 control-room mmWave on → worker credit → disarm, same second.
- **Human there at the trigger?** **No entry.** The door did not open until 957 s later, and the person who opened it was a worker being credited.
- **Evidence:** door contact absent for the entire first cluster; strobe logged **1,855** state changes during the armed window (`r4_ledger.py`).

### E2 — 2026-10-22 23:19:20, armed 6,414 s (1 h 47 min)
- **Trigger:** person 23:19:14 → armed 23:19:20. Doorbell fired again 23:19:25.
- **Presence:** no door contact, no mmWave, nothing at all for 106 minutes. Then 01:06:00 person on → **01:06:14 outside door opens** → 01:06:15 control-room mmWave + worker credit → disarm.
- **Human there at the trigger?** No entry; 23:19 is well after closing.
- **Evidence:** 12,508 strobe changes. Alarm ran 1 h 47 min in an empty shop at night.

### E3 — 2026-10-23 11:28:38, armed 0 s
- **Trigger:** person 11:28:32 → armed 11:28:38; **outside door opened at 11:28:38**, worker credited 11:28:39.
- **Human there?** Yes — a worker, and the alarm beat him by one second.
- **Evidence:** door + worker credit in the same two seconds. This is the cleanest demonstration of the timing defect in §6.

### E4 — 2026-10-23 12:27:53, armed 9 s
- **Trigger:** person 12:27:47 → armed 12:27:53; **door 12:28:02**; worker credit 12:28:03.
- Same shape as E3, 9 s later instead of 0.

### E5 — 2026-10-24 22:21:31, armed 222 s — **not a person at all**
- **Trigger:** `phoenix_outside_door_contact` "on", but look at what precedes it: at **22:21:25 every sensor in the security set went `unavailable` and came back in the same second** — outside door `on`, control-room exterior `off`, control-room interior `on`, `zone_hallway` `on`, `zone_control_room_active` `on`, `everyone_away` `unavailable→on`. The same flap repeats at **22:22:39, 22:23:58, 22:25:03** (4 flaps in 3 m 38 s), each re-arming the alarm.
- **What was happening:** `sensor.apartment_door_smart_lock_action_source_name` = `rf`, user `6`, at 22:19:08 and 22:19:14; "Apartment Deadbolt: Set or replace a person's code" and "Clear a person's code" at 22:23:57 — i.e. lock-code administration. `user_is_here` came on 22:25:14 and ended it.
- **Human there?** Yes — the owner, already inside. The alarm was caused by sensor availability, not by an entry.
- **Evidence:** the unavailable/restored pattern in the same second for six independent entities, and the lock-admin logbook rows. `r4_episodes.txt` E5 (lines 646-745).

### E6 — 2026-10-25 16:59:15, armed 5 s
- Person 16:59:09 → armed 16:59:15 → **door 16:59:18** → worker 16:59:21. Worker arriving; the alarm sounded for 5 s.

### E7 — 2026-10-25 19:57:45, armed 3,793 s (63 min)
- **Trigger:** person 19:57:39 → armed 19:57:45. Person again 19:58:04. Then **nothing for 62 minutes**: no door, no mmWave.
- **Disarm:** 21:00:50 person on → 21:00:56 outside door opens → 21:00:58 control-room mmWave + worker credit.
- **Human there at the trigger?** No entry. The worker who ended it arrived an hour later.
- **Evidence:** 7,308 strobe changes over 63 min in a closed shop on a Saturday night.

### E8 — 2026-10-25 21:38:24, armed 28 s
- Person 21:38:18 → armed 21:38:24 → **door 21:38:51** → worker credit 21:38:53. Worker arriving, 27 s late.

### E9 — 2026-10-25 23:23:21, armed **43,323 s (12 h 2 min)** — the worst event in the window
- **Trigger:** five doorbell-person firings inside 52 s (23:23:15, 23:23:23, 23:23:44, 23:23:54, 23:24:07) → armed 23:23:21.
- **Presence:** **zero** door contacts, zero mmWave, zero doorbell firings for the next 12 hours. The next event is 11:25:14 person on → 11:25:24 outside door opens → 11:25:25 worker credit → disarm.
- **Human there at the trigger?** No entry — someone was in front of the camera for ~50 s at 23:23 and left.
- **Evidence:** **20,001** strobe state changes during the armed window (`r4_ledger.py`). Nothing in the recorded signals turned it off; only the morning arrival did.

### E10 — 2026-10-26 14:03:21, armed 7 s — **the one that got fixed today**
- **Trigger:** person 14:03:15 → armed 14:03:21 → **door 14:03:26** → worker credit 14:03:29 → disarm.
- **Then the defect:** the initial-response script had 22 s of snapshot work ahead of the siren step, so at **14:03:43** — 14 s *after* the disarm — it started the strobe loop and the evidence/page script. `script.phoenix_intrusion_loop` started 14:03:43. A manual `script.phoenix_intrusion_reset` ran at **14:05:40** (logbook row, 2 m 19 s after the alarm).
- **Human there?** Yes, the worker — and the person who reset the siren at 14:05:40 was responding to an alarm that was already logically disarmed.
- **Evidence:** logbook, `r4_e10.py` output. This matches the comment at `phoenix_security.yaml:164-182` exactly, which is why the `condition` at `:180-182` exists.

### E11 — 2026-10-26 14:16:10, armed 70 s — **DRILL**
- `input_boolean.phoenix_intrusion_test_mode` on at 14:16:10 (the only test-mode edge in 30 days), `script.phoenix_test_intrusion_sequence` fired, `intrusion_active` on at the same second, reset at 14:17:21.
- **Evidence:** test-mode boolean, script `last_triggered`, and the page payload carried `event: intrusion_test` (the backend deliberately does not page those).
- During this drill the evidence/page script **raised and aborted**: `2026-10-26 14:16:36.410 ERROR … [phoenix_intrusion_evidence_and_page] … Error for call_service at pos 1: Dahua snapshot failed for Cam Larry's Interior Main` (HA `/api/error_log`, 23,028 bytes, starts 14:14:59 today). `continue_on_error: true` at `phoenix_intrusion_evidence.yaml:145-185` did **not** contain it.

### Under-determined, outside door-contact coverage
- **2026-10-11 01:20:03 → 07:07:32 (20,849 s, 5.8 h)** — 6th longest episode of the month; door contact data does not exist for that date, so "was there an entry" is unanswerable.
- **2026-10-18 18:34:18 → 18:36:33 (135 s)** — ended by neither credit nor door (script), same coverage problem.

**Month total: 15 episodes, 2026-10-11 → 2026-10-26, 1 drill and 14 real, 21.2 h armed in total, median 223 s, maximum 43,323 s** (`r4_month_count.py`). If your "six alarm episodes" means the last 48 hours, that set is exactly **E5, E6, E7, E8, E9, E10** — with E11 the drill.

---

## 3. Labels

| EP | Label | Confidence | How I decided |
|---|---|---|---|
| A | worker arriving | high | door at +301 s, worker credit same second |
| B | worker arriving | high | worker credit + `AWAY off` same second; mmWave 2 s later, so GPS not room |
| E1 | passer-by with no entry | medium | no door contact for 957 s; no entry ever during the cluster; the later entrant was a credited worker |
| E2 | passer-by with no entry | medium | same shape at 23:19; 106 min with zero door activity |
| E3 | worker arriving | high | door + worker credit within 2 s of arm |
| E4 | worker arriving | high | door +9 s, credit +10 s |
| E5 | owner arriving / infrastructure fault | medium-high | six entities flap `unavailable` in the same second, four times; concurrent lock-code admin; owner credited 3 m 49 s in. **Label the fault, not the person** |
| E6 | worker arriving | high | door +3 s, credit +6 s |
| E7 | passer-by with no entry | medium | no door for 3,781 s; the arrival that ended it was 63 min later |
| E8 | worker arriving | high | door +27 s, credit +29 s |
| E9 | **unknown** | low | five firings in 52 s with no door contact — a person stood at the door ~50 s and did not enter; could be a passer-by, a customer who found it locked, or someone testing the door. No camera label exists to separate these |
| E10 | worker arriving | high | door +5 s, credit +8 s, then siren after disarm |
| E11 | drill | high | test-mode boolean, test script, `intrusion_test` page event |
| 10-11, 10-18 | unknown | — | outside door-contact coverage |

**No episode among the 13 fully-covered ones is evidence of an unauthorised entry.** Every alarm either beat a legitimate entrant by 0–27 s, or fired on a person who never opened the door, or fired on sensor availability; the two episodes outside door-contact coverage (10-11, 10-18) are unknown, not exonerated. That is the ground truth this system most needs: **15 alarms in 30 days, 0 intrusions, and 13 of the 15 ended by the presence system noticing someone who was entitled to be there** (the other two ended by a script — one of them the drill).

Tally of endings, month-wide (`r4_month_table.py`): 13 × `everyone_away → off`, 2 × script, 0 × `phoenix.valid_pin`, 0 × manual disarm.

---

## 4. Cross-signal truth table: `video_doorbell_person` → door contact

Window 2026-10-20 20:10 → 2026-10-26 14:43 local (all 11 signals recording). Doorbell firings clustered with a 60 s gap so one approach counts once. `r4_window_final.py`.

- Raw `video_doorbell_person` on-edges: **1981** in 30 days; **167** in the 4.8-day dense window.
- Clusters: **108** in the coverage window.

| Window after the first firing | With a door contact | Without |
|---|---|---|
| **+0 s … +300 s** (the brief's question) | **67 (62 %)** | **41 (38 %)** |
| +0 s … +120 s | 58 (54 %) | 50 (46 %) |
| +0 s … +60 s | 53 (49 %) | 55 (51 %) |
| **+0 s … +30 s** ("walked straight in") | **45 (42 %)** | **63 (58 %)** |
| −60 s … +300 s | 81 (75 %) | 27 (25 %) |

Read it this way: **at 300 s, 62 % of doorbell person events are followed by a door opening and 38 % are not** — but the 300 s window is generous enough to catch a *different* person, and at the honest 30 s horizon **58 % of person detections have no door contact at all**. Those 58 % are the false-alarm engine: they are what `zone_hallway_active` turns into an intrusion trigger whenever the shop is empty.

The operational version — clusters that occurred while `everyone_away` was on, i.e. exactly the ones that can arm the alarm:

| | Count |
|---|---|
| Doorbell clusters while the shop was believed empty | **19** (4.8-day window, `r4_engine.py`) |
| … that had a door contact within +300 s | **12** |
| … that had none | **7** — 10-22 08:43:53 (E1), 10-22 23:19:14 (E2), 10-25 19:57:39 (E7), 10-25 20:42:36, 20:50:34, 20:53:18, 10-25 23:23:15 (E9) |

19 candidate triggers produced 11 alarms because the 6 s grace and the `intrusion_active` single-shot suppressed the rest.

---

## 5. mmWave: when it fires, is a human actually there?

Two distinct mmWave devices, both measured (`r4_window_final.py`, same coverage window):

| Device | On-intervals | Total on-time | Overlaps a presence credit | Contains an entry event (door/lock/doorbell, −60 s) | Neither |
|---|---|---|---|---|---|
| `binary_sensor.presence_sensor_occupancy` ("Presence sensor Occupancy", the standalone mmWave) | **130** | 11.5 h | **3 (2 %)** | 72 (55 %) | **58 (45 %)** |
| `binary_sensor.control_room_hub_control_room_presence` (ESPHome control-room hub) | **115** | 12.7 h | **55 (48 %)** | 68 (59 %) | **22 (19 %)** |

Two different answers, and the difference is the finding:

- The **standalone mmWave** fires 130 times for 11.5 h and coincides with a presence credit **3 times out of 130 (2 %)**. Whatever it is detecting, the presence system almost never agrees with it.
- The **control-room hub mmWave** agrees with a credit 48 % of the time.

Neither is an alarm input (`mmwave_on_edges=0` in every armed window), so this is not currently a false-alarm source — it is a **missed signal**: a sensor that says "a human is in the control room" 130 times in six days, which the intrusion logic does not read at all, and which the presence logic credits 2 % of the time. If a person were in that room while the shop was armed, the only thing that would notice is this sensor — and it is not wired to anything.

Caveat I will not paper over: "neither" is not proof of a false positive. A person sitting still for 20 minutes produces no door and no credit; 45 % of the standalone's intervals look much more like *ignored humans* than like ghosts.

---

## 6. False-alarm ledger

Trigger = the logbook's own "Extreme Intrusion Trigger" row. Arm = `input_boolean.phoenix_intrusion_active → on`. Strobe = state changes of `switch.deserted_house_lights` while armed. `r4_ledger.py` / `r4_final.py`.

| EP | Trigger | Arm | Trigger→arm | Arm→door opened | Arm→human credited | Disarm | Armed | Strobe changes | Paged? |
|---|---|---|---|---|---|---|---|---|---|
| A | 10-21 17:51:40 | 17:51:46 | 6 s | +301 s | +301 s | 17:56:48 | 302 s | n/m | **no** |
| B | 10-21 19:46:42 | 19:46:48 | 6 s | none | +300 s | 19:51:48 | 300 s | n/m | **no** |
| E1 | 10-22 08:43:53 | 08:43:59 | 6 s | +957 s | +960 s | 08:59:59 | 959 s | 1,855 | **no** |
| E2 | 10-22 23:19:14 | 23:19:20 | 6 s | +6,394 s | +6,395 s | 01:06:15 | 6,414 s | 12,508 | **no** |
| E3 | 10-23 11:28:32 | 11:28:38 | 6 s | +0 s | +1 s | 11:28:39 | 0 s | 0 | **no** |
| E4 | 10-23 12:27:47 | 12:27:53 | 6 s | +9 s | +10 s | 12:28:03 | 9 s | 0 | **no** |
| E5 | 10-24 22:21:25 | 22:21:31 | 6 s | n/a (flap) | +223 s | 22:25:14 | 222 s | 192 | **no** |
| E6 | 10-25 16:59:09 | 16:59:15 | 6 s | +3 s | +6 s | 16:59:21 | 5 s | 0 | **no** |
| E7 | 10-25 19:57:39 | 19:57:45 | 6 s | +3,781 s | +3,783 s | 21:00:58 | 3,793 s | 7,308 | **no** |
| E8 | 10-25 21:38:18 | 21:38:24 | 6 s | +27 s | +29 s | 21:38:53 | 28 s | 18 | **no** |
| E9 | 10-25 23:23:15 | 23:23:21 | 6 s | +43,323 s | +43,324 s | 11:25:25 | 43,323 s | 20,001 | **no** |
| E10 | 10-26 14:03:15 | 14:03:21 | 6 s | +5 s | +8 s | 14:03:29 | 7 s | 0 | **no** |
| E11 | drill | 14:16:10 | 0 s | +15 s | — | 14:17:21 | 70 s | 1 | drill (2 POSTs) |

Totals: **15.23 h armed across the 11 dense-window episodes**; **41,884 of the window's 41,980 strobe changes** happened while an alarm was armed.

**Trigger→arm is 6 s in 12 of 13 episodes.** That is not a coincidence, it is `phoenix_security.yaml:69`. And **arm→door-opened is 0–27 s in five of them.** The system reliably arms *before* the entitled human reaches the door, because the doorbell camera sees them walking up 5–15 s before they touch it, and the grace window is measured from that first sighting rather than from the door.

**Did any human notice?** No, and here is the proof rather than the impression:

- **Zero pages were sent for any real alarm.** The authority's `sms_log` holds 4,507 rows from 2025-09-02T06:19:25Z to 2026-10-26T17:44:57Z; **a `WHERE body LIKE '%intrusion%' OR template_id LIKE '%secur%'` query returns zero rows across the whole 14 months.** Mock outbound is off (`MOCK_OUTBOUND_COMMS` absent from `/opt/company/.env`; `is_mock_outbound_enabled()` requires the literal `"True"`; `/opt/company/data/tester_logs/` does not exist), and `send_message` writes `sms_log` (`/opt/company/app/database.py:8176`), so the absence is real.
- **The webhook was called 3 times in 6 days, all today, none for a real alarm:** `POST /webhook/ha/security-alert 200 OK` at 18:16:04Z, 18:16:40Z and 18:43:45Z (`journalctl -u company-api`, 483,751 lines since 10-21). The first two bracket the 14:16 drill. The 14:43:45 one (14:43:45 local) has **no corresponding alarm, no logbook row and no armed state** — I cannot attribute it; it is not mine and I did not make it.
- **Why no page:** the page is the last step of `phoenix_intrusion_evidence_and_page` (`phoenix_intrusion_evidence.yaml:311-317`), behind two `parallel:` snapshot blocks and a verify step. When a Dahua camera returns 400 the script aborts before it (`error_log`, 14:16:36). For E10 the script started at 14:03:43 and no POST followed.
- **Nobody ever disarmed an alarm manually.** All 14 real episodes ended by `everyone_away → off` (13) or a script (1) — never by `phoenix.valid_pin`, never by a reset someone pressed because they heard it.
- The only human response in the whole window is **E10 at 14:05:40**, a `script.phoenix_intrusion_reset` 2 m 19 s after the trigger, on an alarm that had already disarmed itself.

So the 12-hour E9 alarm strobed a closed shop from 23:23 Saturday until 11:25 Sunday, and the first thing that acknowledged it was a worker walking in twelve hours later.

**One thing I can prove and one I cannot:** the strobe is proven (20,001 switch transitions). **Whether audio was audible is not** — `rest_command.phoenix_alarm_mac_on` (`phoenix_security.yaml:188`) has no `response_variable`, no target-state entity and no readback, and `siren.video_doorbell_siren` stayed `unknown` throughout. `script.phoenix_intrusion_loop` (`:215-247`) is titled "Flash & Audio" but its body contains only lighting steps and a comment; **there is no audio step in the loop**.

---

## 7. What this window cannot tell you, and the fields that are missing

Cannot be determined from anything I am allowed to read:

1. **Whether HA was down or merely not recording** from 10-23 13:03 to 10-24 19:44. Needs the HA host journal; I have no shell there.
2. **The 2026-09-15/16 episodes** the config comments describe (`phoenix_security.yaml:50-65`) — outside the ~30-day retention edge (zero rows 09-26, 09-15, 09-20). Those three-alarms-in-80-minutes claims are unverifiable from HA today.
3. **Whether the alarm was audible.** No state, no readback, no response body (§6).
4. **Identity of any person.** The camera captures a clear face when someone is there — `now_latest_person_doorbell.jpg` (Last-Modified 18:28:41Z) shows a woman in a black coat holding a cardboard parcel on the doorstep — but nothing in HA records that a person was seen, how many, or carrying anything. The still is evidence; the label does not exist.
5. **Whether the E9 person tried the handle.** There is no door-handle, forced-entry or lock-attempt sensor on the outside door, and the outside strike's audit trail is not in any table I read.
6. **What the 14:43:45Z webhook POST was.**

Fields that are missing today, and are the first things a learning system should log — named as they would be recorded per event:

| Field | Why it is missing and why it matters |
|---|---|
| `trigger_input` | `zone_hallway_active` is a 5-way OR; the logbook string names only the fused sensor. Ten of thirteen episodes were really `video_doorbell_person`, and the record cannot say so. Log the **leaf** entity, not the zone. |
| `trigger_to_arm_s`, `arm_to_entry_s`, `arm_to_credit_s` | All computable today only by joining three entities across two APIs. These three numbers are the entire false-alarm taxonomy (§6), and they are the ones a learner needs. |
| `presence_basis` on `user_is_here` / `worker_is_here` | A bare boolean with no provenance. I had to reconstruct `PIN+occupancy`, `Montrose phone+occupancy`, `GPS`, `BLE` from logbook prose. Log the automation id and its inputs at the moment of the write. |
| `disarm_reason`, `disarmed_by` | `input_boolean` keeps only state and `last_changed`; the reason lives in an English logbook sentence. Not queryable, not countable. |
| `acknowledged_at`, `acknowledged_by`, `ack_channel` | **Nothing anywhere records a human response.** "Nobody noticed" and "noticed and ignored" are currently the same observation — and per the measurement rule those must never be the same sentence. |
| `page_attempted`, `page_http_status`, `page_recipients`, `page_ok`, `page_error` | HA logs nothing when `rest_command` fails or when the script aborts before it. The only proof a page happened is the authority's access log — a different machine, a different clock. |
| `script_aborted_at_step`, `script_error` | The 14:16 Dahua failure aborted the sequence silently from HA's point of view. Log the aborting step and the exception text onto the episode. |
| `entity_availability_snapshot` | E5 was an availability flap; nothing records that six sensors were `unavailable` 0.4 s earlier. A single boolean `any_input_unavailable` at trigger time would have labelled E5 automatically. |
| `door_id` (canonical), `open_duration_s` | Two sensors report the same physical door (`binary_sensor.0x286d97000115ca7a_contact` and `binary_sensor.phoenix_outside_door_contact` fire within the same second on 246 edges, always paired). There is no canonical door identity, so "how many doors opened" is ambiguous. |
| `snapshot_manifest[]` = `{camera_id, capture_ts_monotonic, file, sha256, osd_ts}` | `now_latest_person_doorbell.jpg` carries an on-screen clock of **13:21:03** while its file `Last-Modified` is **14:28:41** — a 67-minute disagreement between the camera's OSD and the file time. Evidence that cannot be time-correlated is not evidence. |
| `person_detected[]` = `{count, bbox, face_id?, parcel?, confidence}` | The Reolink AI already emits person/vehicle/pet/visitor booleans; nothing persists what was seen or how many. |
| `episode_id` | No correlation id spans HA → backend → SMS. I had to join on timestamps to prove no page was sent, and that join is not repeatable at scale. |
| `recorder_gap` markers | A 30 h 41 min hole exists and no row in any table says so. |
| `test_mode` on the event | Present as a boolean, absent from the alarm record itself, so a drill and a real alarm are indistinguishable once the boolean is reset. |

---

## 8. Proposed label taxonomy

The minimum set worth recording per event. Every label below is one I could *actually assign* from signals that exist today or from the fifteen fields above; nothing here needs new hardware.

| Label | Definition | Reason it earns a slot |
|---|---|---|
| `OWNER_ARRIVAL` | Entrant is the owner by credential, BLE or PIN | Owner arrivals are the highest-frequency legitimate entrant after workers and must never look like an intruder |
| `WORKER_ARRIVAL` | Entrant is a named worker by PIN, RFID, phone or GPS | **7 of the 13 densely-covered episodes** (A, B, E3, E4, E6, E8, E10) — the single largest class, and the one whose timing needs tuning |
| `TENANT_ARRIVAL` | Apartment deadbolt used by tenant slot | Separate door, separate lock, no contact sensor — a class the alarm structurally cannot see |
| `CUSTOMER_ENTRY` | Uncredentialed person admitted (buzz-in, held door, propped door) | The legitimate-but-uncredentialed case; distinct from intrusion because someone inside chose to admit them |
| `DELIVERY_NO_ENTRY` | Person at door with a parcel, no entry | The `now_latest_person_doorbell.jpg` case — occurs constantly and must not consume alarm attention |
| `PASSER_BY_NO_ENTRY` | Person detected, no door contact within the horizon | **7 of 19** while-empty clusters; the other half of the false-alarm engine |
| `UNKNOWN_PERSON_NO_ENTRY` | As above but the person lingered or approached repeatedly | E9's five firings in 52 s — behaviourally different from a passer-by, and the only one worth a second look |
| `UNAUTHORISED_ENTRY` | Entry with no credential and no credit | The true positive. **Zero occurrences in 15 episodes** — which is itself the most important measurement in this document |
| `FORCED_ENTRY` | Entry with tamper, handle or break signal | Cheap to add, changes the response from "check the camera" to "call police" |
| `INFRASTRUCTURE_FALSE` | Trigger caused by availability, restart or sensor flap | E5. Today it is indistinguishable from an intruder; it should auto-close without paging |
| `DRILL` | Operator-initiated test | E11. Must be excluded from every learned prior |
| `SYSTEM_ERROR` | Alarm path failed (script abort, page failure, dead sensor) | The 14:16 Dahua abort and the dead camera-human sensors belong here, not in a log nobody reads |
| `NO_ANSWER` | Event where a required signal was absent | Per the measurement rule: "no answer" and "an answer that never closed" are different sentences and must never be the same one |

Two design notes that fall out of the data:

- **Label the outcome, not the sensor.** Every label above is a statement about a person and a door, not about which boolean fired. `zone_hallway_active` collapsed five inputs into one and destroyed the information needed to learn.
- **`UNAUTHORISED_ENTRY = 0` is the headline.** A learning system trained on this window would learn one thing worth knowing: the alarm is currently a worker-arrival detector with a 6-second handicap, and the 43,323-second episode is what that costs.

---

## 9. Reproducibility

Everything above is regenerable from these files in `C:\Users\ezabz\Code\ha-config\_scratch\audit-2026-10-26\`:

`r4_collect.py` (5×24 h history + logbook) · `r4_month.py` (30-day, 11 signals) · `r4_retention.py` (per-day depth) · `r4_coverage.py` · `r4_episodes.py` / `r4_episodes.txt` · `r4_ladder.py` · `r4_truth.py` · `r4_final.py` · `r4_ledger.py` · `r4_zones.py` · `r4_engine.py` · `r4_window_final.py` · `r4_month_count.py` · `r4_month_table.py` · `r4_e10.py` · raw: `r4_rows.json` (46,993 rows), `r4_month.json` (12,864), `r4_logbook.json` (62,136). Stills: `now_latest_intrusion_doorbell.jpg`, `now_latest_person_doorbell.jpg`.

Token was read from `personal-secretary-mvp/.env` (`HA_TOKEN`, 183 chars) and never printed. Authority reads were `ssh secratary-cloud 'sqlite3 -readonly /root/authority.db …'` and `sudo -n journalctl -u company-api` — read-only.
