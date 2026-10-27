# HANDOFF — Lakewood Phone & Tech security system, 2026-10-26

**Read this first. It is written for an agent who has no memory of the session that produced it.**

Owner's instruction when he asked for it: *"write a full handoff document with everything you did, what you
discovered, what needs to be done and what needs to be audited and investigated, I will give it to another agent
to deal with, then give me the path to that doc."*

Three documents sit behind this one, all in `~/code/ha-config`:

| File | What it is |
|---|---|
| `docs/HANDOFF-2026-10-26-security-audit.md` | **this file** — start here |
| `docs/security-audit-2026-10-26.md` | the audit: 84 numbered findings (`S1`…`S84`), append-only, every claim carries its evidence and its corrections |
| `docs/security-system-design-2026-10-26.md` | the design: 20 rounds, the deterministic envelope, the record, the department, the phased build, the acceptance tests |
| `_scratch/audit-2026-10-26/` | eight workstream reports (`W1`-`W8`) and four data rounds (`R1`-`R4`), with raw data and rerunnable scripts |

---

## 1. The state of the system right now (2026-10-26 17:10 local)

**Working and verified:** the siren is off; the alarm is disarmed (flag off); all three door contacts are live and
`off`; `everyone_away` is `off`; the one-second regression check passes (`PHOENIX_EVIDENCE_OK`, rc 0); `ha core
check` is clean; the configuration was deployed byte-identical (sha256 compared both ways) and reloaded.

**Deployed today, and each one is a change to a live alarm — know what you are inheriting:**

1. **The trigger list is cut to the two real doors** (apartment door, shop door). The public-hallway zone, the
   always-open hallway door contact and the redundant control-room zone are **out** of the trigger.
2. **The evidence-and-page script runs at step 0**, before anything that can block. It used to be the last step,
   behind a blocking siren loop.
3. **The retry loop is rewritten** as `repeat: while: (not page_ok) and (attempts < 4)` with a type-checked
   `page_ok`; the old `count: 4` + `stop` version was inverted (see §6).
4. **A siren fail-safe automation** (`automation.phoenix_siren_fail_safe`) posts `rest_command.phoenix_alarm_mac_off`
   three times, three seconds apart, whenever the alarm flag drops, the loop script ends, or HA starts.
5. **`script.phoenix_intrusion_reset` now clears the alarm flag first**, so one press is a full stop.
6. **The two `shell_command`s** were fixed earlier the same day (see §6.1).
7. **The page body carries a reference stamp** (`detail: "… (ref <stamp>)"`) so a second intrusion inside the
   backend's 30-minute duplicate window is not silently suppressed.

**Not built yet — do not assume otherwise:** the presence-based arming model, the credential veto, the four record
tables, the security department, vision, and the heartbeat. The design for all of them is written; none of it is
running.

---

## 2. The owner, and the rules that are his

He is terse and he is right when he is annoyed. These are binding, from him directly:

- **One question per message.** Never a list of questions. (*"one question at a tinme"*)
- **Read the record before you ask him anything about this building.** Journal → config grep → entity history →
  only then him. I wasted his patience twice by asking things the repository already answered.
- **Do not ask him to review a document or a list of options.** If a problem has a solution you can find, finding
  it is the work.
- **Access policy, his words:** *"the only people who have access are me, my parents and my wife, and a master
  guest code for now."* Five subjects. No workers — *"montrose hasn't worked here in months"* — so the entire
  worker/kiosk presence path is obsolete.
- **Entry is by keypad or RFID tag**, both on the shop door (ESPHome keypad) and on the apartment door (Kwikset
  smart lock, programmable from HA).
- **Never send anything outbound without an explicit per-message instruction.** This includes SMS to himself.

---

## 3. The building, as he described it (this corrects most of the old model)

> *"the outside door is always open cuz that hallways is 24 6 pickup and dropoff… it's barred by the apartment door
> on the left and the shop exterior door on the right"* — confirmed by his video `C:\Users\ezabz\Downloads\IMG_1254.MOV`.

```
street
  |
  v
PUBLIC HALLWAY  (open 24/6 — drop-off and pick-up; anyone may walk in)
  |                                    |
  v  LEFT                              v  RIGHT
APARTMENT DOOR                     SHOP DOOR
(Kwikset keypad, z2m)              (ESPHome keypad + RFID, contact sensor)
```

**The two doors are the entire perimeter. Nothing else leads anywhere.** The hallway is not a boundary and a person
standing in it is a customer at a pickup box.

The sensors, mapped:

| Entity | Physically | Notes |
|---|---|---|
| `binary_sensor.phoenix_outside_door_contact` (`0x286d97000115ca7a`) | **the hallway door** | stands open; 83 % duty, three open stretches of 168/143/168 h. **Not a perimeter.** Removed from the trigger. |
| `binary_sensor.phoenix_control_room_exterior_door_contact` | **the apartment door** | 99 edges / 28 d; one 17.6 h latch (propped) |
| `binary_sensor.phoenix_control_room_interior_door_contact` | **the shop door** (maglock) | open **57 %** of the time, longest single 82.9 h — a propped door, so its edge is weak evidence |
| `binary_sensor.zone_hallway_active` | a fused zone over the doorbell + hallway door | describes a **public space**. Produced **13 of 13** false alarms. Removed from the trigger. |
| `lock.0x002446fffd0a4705` | the Kwikset keypad lock on the apartment door | reports `action_source_name` (`keypad`/`manual`/`rf`), `action_user` (slot), and `sensor…_pin_code` (last PIN **in plaintext**) |

---

## 4. Access and tooling — what actually works from `zabz-tech`

```
# Home Assistant REST (token lives in personal-secretary-mvp/.env, key HA_TOKEN)
. "C:\Users\ezabz\code\_ha-cred-20261018\ha.ps1" -Path /api/states          # helper: GET with bearer token

# Home Assistant shell (the ONLY route to the host filesystem; the SSH add-on is on 2222, not 22)
ssh -p 2222 -i ~/.ssh/ha-mesh-key -o IdentitiesOnly=yes -o StrictHostKeyChecking=no root@192.168.50.34

# The authority (company DB, company-api.service)
ssh secratary-cloud "sqlite3 -readonly /root/authority.db '<SELECT ...>'"

# The Mac mini overhead siren (unauthenticated by design, bind 0.0.0.0 — see §7)
POST http://192.168.50.45:8128/alarm/off      # {"ok":true,"alarm":"off"}
GET  http://192.168.50.45:8128/health         # {"ok":true,"alarming":false,...}

# Deploy a config file byte-exactly (scp/sftp are NOT available on the HA host)
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($localPath))
$b64 | ssh -p 2222 -i ~/.ssh/ha-mesh-key … root@192.168.50.34 "base64 -d > /config/packages/<file>"
# then: sha256sum on both sides, `ha core check`, and either `ha core restart` or `automation/reload`
```

**Deploy discipline that is not optional here:** the repo and the live host are different machines; compare sha256
both ways every time; `ha core check` before any restart; `SCRIPT` domain changes need a restart or
`script/reload`, `automation` changes need `automation/reload`. Pre-edit copies are on the host as
`/config/packages/*.bak-20261026-140921` and `*.bak2-20261026`.

---

## 5. What was discovered (the short version; every item has an `S` number in the audit)

### 5.1 The alarms were never about burglars
Thirty days, **15 intrusion episodes, 14 real, and ZERO unauthorised entries.** Seven were a "worker arriving"
credit from a **ghost** — `device_tracker.monty` still reports `home` for a man who left months ago, and passive
arrival credits `worker_is_here` whenever the control-room radar moves while that tracker is home. That ghost is
why the alarm kept disarming itself and why it could not arm today. **All 13 instrumented episodes ended by
presence credit — never by PIN, never by a human.**

### 5.2 No page has ever been delivered
- The HA error log held **42 identical failures** over 6 episodes: `FileNotFoundError: 'for'` — a `shell_command`
  with Jinja is run by `create_subprocess_exec`, no shell, so `for f in …` tried to exec a binary named `for`.
  `continue_on_error` does not catch it, so the sequence aborted **before** the page step.
- The receiving end confirms it independently: `company-api`'s journal (12 days) has **three** POSTs to
  `/webhook/ha/security-alert`, all today, all mine.
- `sms_log`: 4,507 rows since 2025-09-02, **zero** intrusion pages, ever.

### 5.3 The page was sequenced BEHIND the alarm
`initial_response` called the loop as a **blocking** service and paged in the step after it, so the page could not
be *attempted* until the alarm ended. Measured: loop started 23:23:38, HA's 10,000-iteration cap killed it at
02:14:22, and the page step started **in that same second** — 2 h 51 m after the intrusion. Now fixed (page is step 0).

### 5.4 The siren is a latch with no timeout, and it ran for twelve hours
`POST /alarm/on` starts a `while` loop in a Python listener on the Mac mini; only `/alarm/off` clears it. Between
23:23:38 and 11:25:25 nothing asked it to stop — **12 h 01 m**, nine of those with the strobe already dead.

### 5.5 A retry loop that ran backwards
`repeat: count: 4` ending in `stop: "page not confirmed - retrying"`. In HA `stop` ends the **whole script** and is
recorded as *finished*, so on failure the fail-loud notification and the prune were unreachable code, and on
success there was no break so it **re-sent the page up to five times per recipient**.

### 5.6 Two camera clocks, both wrong, sixteen minutes apart
A matched pair (same courier, same parcel, one automation run): doorbell `13:21:03`, hallway `13:37:21`. The
Reolink is ~67 min slow, the Dahua NVR ~51. **Every cross-camera timeline is wrong by 16 minutes.**

### 5.7 The evidence path can mislabel itself
`custom_components/dahua/client.py:74-92` retries a failed snapshot on `channel-1`, then `1`, then `0`, then with
**no channel at all** — which returns the first channel's frame with **HTTP 200**. A still named for a camera that
does not exist can be a picture of one that does.

### 5.8 There is no machine vision and no vision hardware
No `image_processing` domain, no Frigate/DOODS/TensorFlow/OpenCV/Coral. HA runs on a **Raspberry Pi**. All 48
Dahua detectors have produced **zero** events in 30 days because both detection switches are `off` on all six
cameras — a switch, not a broken thing. The Reolink doorbell's own person AI works (99 firings/72 h).

### 5.9 The credential layer
`input_text.phoenix_access_control_log` is a **255-character string** — six entries, the seventh destroyed on every
badge. The per-user PIN system is registered but **switched off**, so `phoenix.valid_pin` never fires; and
`phoenix_access_manager/__init__.py:118` logs the **wrong PIN in cleartext**. The RFID role map compares only three
names, so Klein's and Montrose's tags can never resolve. The apartment door's Kwikset keypad **does** work and
**does** name people (`ui_set_kwikset_pin`, slot 1 = Boss, 2 = Worker, 3 = Guest, else "User N").

### 5.10 Two ways to open doors with no credential at all
- Any HA token can `POST /api/events/esphome.access_control_keypad_entry` — the automation filters on event type
  only. `HA_URL` is **plain http**, and the token is **owner+admin with no MFA** on at least two hosts.
- `script.buzz_in_strike` opens the outside door by publishing to `zigbee2mqtt/Smart Switch/set` with one shared
  broker user; the only trace is a relay state.
- Physically: **both maglocks are fail-safe**, so cutting power unlocks them silently.

### 5.11 The recorder keeps ~28 days (not 1.8)
Read from `/config/home-assistant_v2.db` on the host: 2,335,006 rows, 26 distinct days, oldest 2026-09-28.
Four earlier measurements said 1.8 days because `/api/logbook/<start>` returns at most **24 hours from the start**
and `/api/error_log` is a ring buffer wiped at restart. **The API's window is not the database's retention.**

---

## 6. What was fixed today, and how it was proved

| # | Fix | Proof |
|---|---|---|
| 1 | `phoenix_verify_evidence_files` → `bash -c '…'` | `POST /api/services/shell_command/phoenix_verify_evidence_files?return_response` → `PHOENIX_EVIDENCE_OK`, rc 0, 0.1 s |
| 2 | `phoenix_prune_intrusion_evidence` → `bash -c`, no `xargs` | after one drill: 42 files, 0 older than 14 days (was 48 files, oldest 40 days). The 9 doomed files were archived first to `_scratch/phoenix-evidence-archive/` |
| 3 | Disarm guard before siren | `ha core check` clean; test drill logged `captured 3 image(s)` — step 7 reached for the first time |
| 4 | Page moved to step 0 | deployed + reloaded; `automation.phoenix_extreme_intrusion_trigger` reloaded clean at 17:06:09 |
| 5 | Retry loop rewritten | YAML validates; `ha core check` clean |
| 6 | Siren fail-safe automation | `automation.phoenix_siren_fail_safe = on`; it fired on the 17:05 HA start |
| 7 | Reset clears the flag | used at 17:05:22 to stop the second alarm; flag went `off` and the loop stopped |
| 8 | Trigger list cut to two doors | deployed, sha256 matched, `automation.reload` OK |

**Today's two alarms:** 14:03:15 (a person at the doorbell; siren at 14:03:43, off at 14:05:40 by hand) and
16:55:36 (public hallway; ran 9 m 46 s until reset). Both fired from `zone_hallway_active`. **Neither had a page.**

---

## 7. What still needs to be built (design is written; nothing is running)

Order matters. Each has an acceptance test that must pass before the next.

**Phase 1 — the presence-based arm gate.** Replace the arming model entirely. Today `everyone_away` is a
motion-gap detector (it goes false 0.13 s after a radar sees someone) and declares the shop empty **9.77 times a
day**, which is what produced 15 armed episodes.
```
INSIDE = hub mmWave OR BLE mmWave OR any door in 600 s OR credential in 600 s
EMPTY  = INSIDE false continuously for 600 s
ARM    = EMPTY and no door and no credential for 1800 s
```
Simulated on the same 28 days: **0.63 empty declarations/day, zero re-occupations inside 5 minutes** — 15.5× fewer
opportunities to arm wrongly. *Acceptance:* a synthetic door opening with no credential arms and pages inside 30 s;
a credentialed entry arms nothing; a hallway pedestrian arms nothing.

**Phase 2 — the credential veto.** `entry_event` written on every credential use (shop keypad + apartment Kwikset),
and the rule: a door opens with no granted `entry_event` in the preceding N seconds while the zone is expected
empty → alarm. *Acceptance:* the 13 historical episodes stay silent; an unbadged door fires.

**Phase 3 — the record.** Four tables in `/root/authority.db`: `security_event`, `security_decision`,
`security_label`, `security_action`. *Acceptance:* every event in 24 h has a row; every alarm has a decision row
carrying the one-line explanation that went into the page.

**Phase 4 — the department.** `dept_security` in `company_blueprint.DEPARTMENTS` (there are 14; **none is
security**). On-event triage · nightly learning · weekly audit. **Watch the autonomy trap:** `autonomy.py:376`
defaults unknown actions to **L4 autonomous** — for security every action must be explicitly registered.

**Phase 5 — observability.** A 6-hourly heartbeat that writes a receipt row; the one-second check as a button; a
self-cleaning drill; a per-recipient page receipt; `recorder_gap` markers.

**Phase 6 — hardware (owner's money):** window/glass-break sensors, a contact on the back/shop-side doors, a UPS,
a second audible device, and — if he wants vision — Frigate on `zabz-tech-linux` (i5-11400, 105 GB free, iGPU with
HEVC), **not** on the frozen `secratary` box (99 % disk, 2013 Haswell, no Docker, and it is the rollback anchor).

---

## 8. What needs auditing or investigating (open, with what would settle each)

1. **Does a page actually arrive end to end?** Nothing has ever proved it. The only way is one real page the owner
   agrees to beforehand — then read the `To` header and the `sms_log` row back.
2. **The unexplained POST.** `company-api` logged `POST /webhook/ha/security-alert 200 OK` at **18:43:45Z** with no
   alarm and no logbook row (no app log, no `sms_log` row — the signature of a test-type event). Something holds
   that API key and used it. Needs attribution.
3. **Is `cam_larry_s_exit_main_2` a real second config entry on channel 1, or the client's channel-fallback
   substituting channel 1's frame?** Both produce what was measured. Settle it in the Dahua config entry, because
   the difference is "a redundant view" versus "evidence that lies".
4. **The 30-hour recorder hole** (2026-10-23 13:03 → 10-24 19:44). Recording resumed 7 s after an SMS about a
   failed Shabbat automation. Whether HA was down or merely not recording is unknown — needs the host journal.
5. **The shop's own hours.** The hallway is 24/6. Whether the shop is the same six days is unresolved, and it
   changes what "expected empty" means.
6. **Is the shop door being propped open 57 % of the time normal?** If it is, its edge cannot be the trigger and the
   design must lean entirely on presence + credential.
7. **Who opens the shop door without badging?** R1 measured 24 opens in 28 days with no credential *and* no radar
   within 600 s — 13 of them outside 09:00–20:00, so **0.45 alarm per day**. Badging *in* as well as out would take
   that to near zero. This is a policy question for the owner.
8. **`HA_TOKEN` is owner+admin, no MFA, in plaintext, plain-http, on at least two hosts** (`zabz-tech`,
   `secratary-cloud`). Replacing it is a maintenance window of its own because every agent path uses it.
9. **The mother is not on the page roster** although decision `D240` says she was meant to be; the roster is two
   phones (owner, wife) plus a duplicate of the owner. Owner's call.
10. **The owner's half of the page is gated** by `owner_text` (`awaiting_reply` 12 h window, 20/day quota) while the
    wife's copy is not — and `ok = all(...)` makes one refusal a total failure.
11. **The frozen `secratary` box is not dormant.** Five systemd timers are firing (`estate-monitor` every 10 min,
    `fa-index`, `sms-status-reconcile`, `trunk-check`, `tmp-reaper`), its `secretary.db` is 23 GB and was written
    today at 15:21, and `/` is at **99 % with 5.3 GB free**. It is one bad night from dying, and it is the rollback
    anchor. Owner's decision what it becomes.
12. **`sensor.0x002446fffd0a4705_pin_code` publishes the last PIN used, in plaintext**, retained 28 days. That is a
    live leak, not a design question.

---

## 9. Traps that will waste your time

- **`/api/logbook/<start>` returns at most 24 h from the start, and a full-range call silently truncates** (357 of
  40,325 entries, exit 0). Chunk into ≤24 h windows.
- **A refusal is not a negative.** `journalctl -u secretary-api` returns 0 because the unit does not exist; the real
  one is `company-api.service`. `find` on this host is BusyBox: no `-printf`. `sqlite3` needs the container.
- **A signal that never changes is telling you the setup.** The hallway door contact was "stuck open" for 22.7 days
  — it is supposed to stand open. Both a workstream and I logged it as a fault.
- **`input_boolean` with `initial:` never restores**; without it, always restores. Neither is visible at the use site.
- **`stop` in a script ends the whole script**, not the loop. **`condition` aborts the sequence.** Both were load-bearing
  bugs here.
- **`shell_command` runs with a real shell when the command has no Jinja and WITHOUT one when it does.** Sweep: 9
  definitions in the config, exactly one templated.
- **The recorder excludes two mmWave channels by config** — their history is *unknown*, not zero.
- **Two of the three door contacts are named confusingly**: `outside_door_contact` is the hallway door,
  `control_room_exterior` is the apartment door, `control_room_interior` is the shop door.
- **Restarting HA flaps entity availability and can ARM the alarm** (one historical episode was six sensors going
  `unavailable`/restored four times in 3 m 38 s, each one re-arming). If you restart, watch the flag.
- **`last_triggered` resets on every restart** — never use it as a long-run record. There were 8 restarts in 28 days.

---

## 10. My own errors, so you do not inherit them

1. **I claimed two defects shared a cause without reading the code that decides.** The verify command was broken;
   the prune was not — `shell_command` branches on Jinja. Ledger `S2`/`S10`.
2. **I told the owner the recorder held 1.8 days and that the evidence would expire within days.** It holds 28.
   Four measurements were wrong the same way. Ledger `S60`.
3. **I read a "67-hour latched door" as a fault.** It was the building working as designed. Ledger `S49`.
4. **I asked whether the apartment door had a keypad** when `scripts.yaml:772` and `access_control.yaml:2179` were
   already in the audit I had written hours earlier. Ledger `S84`.
5. **I claimed the drill proved the disarm guard.** Test mode bypasses exactly that branch. Ledger `S18`.

The pattern in all five: **I asserted a mechanism from a symptom.** Print the raw value next to the predicate; read
the code that decides before naming a cause; and read the estate's own record before asking the owner.

---

## 11. The owner's open questions, in the order they will be asked

1. **Vision** — Frigate on `zabz-tech-linux` after the envelope and the record, or not at all.
2. **Hardware coverage** — windows, glass-break, the back doors, a UPS, a second siren.
3. **The agent token** — a non-admin HA user and TOTP, in a maintenance window.
4. **The mother on the intrusion page.**
5. **Opening hours and the propped shop door** (§8.5, §8.6) — needed before the arm gate can be finished.

Ask **one** at a time, with a recommendation, question last.

---

## 12. Where the raw evidence is

`~/code/ha-config/_scratch/audit-2026-10-26/`:

- `W1-adversarial-fixes.md` · `W2-triggers.md` · `W3-response-chain.md` · `W4-paging.md` · `W5-detection.md` ·
  `W6-observability.md` · `W7-redteam.md` · `W8-maintenance.md`
- `R1-signals.md` (+ `raw/history2.tsv`, 641,790 rows) · `R2-cameras.md` · `R3-identity.md` · `R4-ground-truth.md`
  (+ `r4_*.json`, 46,993 + 62,136 rows, and the rerunnable scripts)
- `states-live.json` (1,036 entities at 14:26), `logbook-24h.json`, saved stills
- `phoenix-evidence-archive/intrusion-over-14d-20261026.tar.gz` — the 9 old evidence files retention would have
  deleted, preserved before it ran

Everything in this handoff is reproducible from those files and from the commands in §4.
