# Phoenix alarm audit — 2026-10-26

Append-only ledger. Every item carries its evidence. Nothing here is true because it is remembered.

Owner's instruction, 2026-10-26: *"analyze this really well and audit it from all positions with
subagents and orchestration, and adversarial ones both ways, then find all the changes decisions and
optimizations and write them all down as you go along, and then we'll go through them."*

Decisions are marked **DECIDED** (taken by me, with reason), **OWNER** (genuinely his), or **OPEN**.
Status is marked **FIXED+PROVEN** only where a command's output was read back after the change.

---

## Part 0 — what happened, and what is already fixed

### S1 — The evidence-verify step never ran, so no intrusion page has ever been delivered. FATAL.
`shell_command` is executed by Home Assistant via `create_subprocess_exec(*shlex.split(cmd))`: there is no
shell, so the first word must be an executable. `phoenix_verify_evidence_files` began `for f in {{ files }}`,
so exec looked for a binary named `for`.

Correction, same day: the *rule* is narrower than "shell_command has no shell", and I had it wrong at first —
see **S10** for the source. It only applies to a shell_command that **contains Jinja**. This one did, so the
finding stands.

Evidence: 42 identical lines in `/api/error_log` across 6 episodes in the 43 h it retains (10-24 22:25,
10-25 16:59, 21:01, 21:38, 10-26 02:14, 14:03):
`Unexpected error for call_service at pos 5: [Errno 2] No such file or directory: 'for'`.
`continue_on_error: true` does not cover a FileNotFoundError raised inside the service, so the sequence
aborted four steps before the page. `sms_log` on the authority: 4,507 rows from 2025-09-02 to now, zero
intrusion pages.

**FIXED+PROVEN** — wrapped in `bash -c '<loop>'`; `POST /api/services/shell_command/phoenix_verify_evidence_files?return_response`
returns `PHOENIX_EVIDENCE_OK <path>`, returncode 0. Commit `eb57dd8`.

### S2 — Retention had never run. The OUTCOME is real; my first explanation of WHY was wrong, and I withdraw it.
The measurement stands: 48 `intrusion_*.jpg` on the host, oldest dated **Sep 16 — 40 days old** against a
14-day rule, so nothing was being pruned.

**What I first wrote, and it was wrong:** "same defect class — pipes handed to `find` as arguments". That was
an inference from two things failing at once, not a measurement, and it is false. `shell_command` uses a real
shell when the command contains **no Jinja**; the prune command contains none, so it ran under `/bin/sh` the
whole time. Proved both ways:

- Source, `docker exec homeassistant sed -n '45,95p' .../components/shell_command/__init__.py` on
  HA 2025.10.3: `if rendered_args == args:` → `asyncio.create_subprocess_shell(cmd)`; else
  `shlexed_cmd = [prog, *shlex.split(rendered_args)]` → `create_subprocess_exec`.
- Empirical, on the host: four synthetic files dated 2026-08-01, 2026-09-16, 2026-10-01, 2026-10-26, the
  ORIGINAL prune command run under `sh -c` → kept only the 2026-10-26 file. `xargs -r` exists in BusyBox
  (`xargs -r true` → exit 0).

**The real cause is S1.** The prune is step 7 of `phoenix_intrusion_evidence_and_page`; the script aborted at
step 5, so steps 6 and 7 never executed. One defect, two symptoms: no page and no retention.

**Decision:** keep the `bash -c` form for both commands anyway, for a different and honest reason — a
shell_command's execution mode depends on whether it happens to contain Jinja, which is invisible at the call
site and one edit away from flipping. `bash -c` behaves identically under both branches and was proven live
under the templated branch (`PHOENIX_EVIDENCE_OK`, rc 0). Retention was then exercised for the first time:
42 files, 0 older than 14 days.

### S10 — The rule, stated properly, because this is the trap that cost two days.
Home Assistant 2025.10.3, `components/shell_command/__init__.py`:

```python
prog, args = cmd.split(" ", 1)
args_compiled = template.Template(str(args), hass)
...
rendered_args = args_compiled.async_render(variables=service.data, parse_result=False)

if rendered_args == args:
    # No template used. default behavior
    create_process = asyncio.create_subprocess_shell(cmd, ...)      # a real shell
else:
    # Template used. Break into list and use create_subprocess_exec
    # (which uses shell=False) for security
    shlexed_cmd = [prog, *shlex.split(rendered_args)]
    create_process = asyncio.create_subprocess_exec(*shlexed_cmd, ...)   # NO shell
```

So: **a `shell_command` that contains any Jinja runs with no shell; one that contains none runs under a real
shell.** The first word is split off before templating, so `prog` is never templated.

Sweep of the whole configuration (all `shell_command` blocks parsed out of `config/**/*.yaml`, 2026-10-26):
**9 definitions, exactly 1 templated** — `phoenix_verify_evidence_files`, which was the broken one and is now
`bash`. The other 8 (`phoenix_prune_intrusion_evidence`, the six `nohup` timeline/clip commands, and
`phoenix_timeline_regen` with `mkdir`) take the shell branch and were never affected. The defect was unique,
not a class scattered through the config.

Retention was then exercised for the first time and did work: 42 files, **0 older than 14 days**. The 9 files
it would delete were archived first to
`_scratch/phoenix-evidence-archive/intrusion-over-14d-20261026.tar.gz` (verified: 9 entries, 1.4 MB).

### S3 — The siren step did not re-check the alarm, so a disarm could not stop it. FATAL.
14:03:15 person at the door → `zone_hallway_active` on → trigger. 14:03:21 grace expired → armed →
initial response started. 14:03:29 passive arrival credited → disarm → flag off + reset. 14:03:43 the
still-running sequence reached the siren step (22 s of snapshot work) and ran
`rest_command.phoenix_alarm_mac_on` eight seconds AFTER the disarm, with nothing left to turn it off.
Siren from 14:03:43 until a manual reset at 14:05:40.

**FIXED+PROVEN** — `- condition: state input_boolean.phoenix_intrusion_active == on` added after all
evidence capture and before siren/strobe/loop/page. `ha core check` clean before both restarts; deployed
byte-identical (sha256 both ways); pre-edit copies on the host as `*.bak-20261026-140921`. Commit `eb57dd8`.
Proof the block does not break the normal path: test drill at 14:16:10 logged
`Intrusion Evidence | captured 3 image(s) for intrusion_test: ..._doorbell.jpg, ..._front_hallway.jpg,
..._control_room_interior.jpg` — step 7, reached for the first time.

### S4 — The flash/audio loop has a count cap, not a time cap. SEVERE.
`WARNING ... looped 5000 times` at 00:49; `CRITICAL ... terminated because it looped 10000 times` at
02:14:22 — roughly 85 minutes of siren and strobe, ended by HA's hard cap, not by anything that knew
whether anyone was coming. Open.

### S5 — The alarm can be armed by a person merely *seen* at the front door. SEVERE (false-alarm engine).
The trigger list includes `binary_sensor.zone_hallway_active`, which fuses the doorbell's own person
detection. Six triggers in 43 h, all false. Grace window is 6 s; arrival was credited after 14 s.
**OWNER** — two options, recommendation below.

### S6 — One camera contributes no evidence, on every run. MINOR.
`camera.cam_larry_s_interior_main` → Dahua NVR `https://192.168.50.170/cgi-bin/snapshot.cgi?channel=2`
returns **HTTP 400** (measured 14:16:36 during the drill, and at every prior episode). The roster tolerates
it (`continue_on_error: true`), so evidence is 3 of 4 cameras. Open.

### S7 — DECIDED: the repo stays the single source of truth, but the documented deployer cannot be used from this host.
`scripts/deploy.ps1` defaults to `-UseScp`-less SSH plus an scp transfer; the HA SSH add-on has **no sftp/scp
subsystem** (`scp` -> `subsystem request failed on channel 0`, measured 14:09). It also listens on **2222**,
not 22, and only `~/.ssh/ha-mesh-key` is authorised (`zabz-tech-ed25519` -> `Permission denied (publickey)`).
Deployment was therefore done with a byte-exact `base64 -d >` over `ssh -p 2222`, and correctness was proved
by comparing sha256 on both sides rather than by trusting the transfer:
`6cb5eea0...` then `6ff9a714...` on the host matched the local file exactly, both times.
Decided: fix the deployer later rather than leave a second deploy path undocumented; any future hand-deploy
must compare sha256 both ways. Open.

### S8 — DECIDED: two HA core restarts, mid-afternoon, on a live security system.
A `shell_command` body is not reloadable (`/api/services` has no `shell_command.reload`), so the S1/S2 fixes
could only take effect at startup. `ha core check` returned *Command completed successfully* immediately
before each restart; the API answered `{"message":"API running."}` 5 s after the second one returned; template
entities re-resolved at 14:15:47 (`binary_sensor.phoenix_everyone_away = off`). Downtime was seconds, no
automation ran wrongly during it, and the alarm was verified armed-capable afterwards. Recorded because a
restart of the thing that guards the premises is a decision, not a detail.

---

### S9 — the mesh cannot place a child where the code lives, so this audit runs LOCAL. Records the placements, per the honesty rule.
Two children were placed and reported; both were wrong for this task:
- probe `remote-b2486dea` → **LANDED-RIGHT on `ZABZ-YOGA`**, but `git log -1` there is `39f13694`
  dated **2026-09-17** — five weeks behind today's commit `eb57dd8`. Auditing that tree audits an alarm
  that no longer exists.
- `remote-416b75cc` → **LANDED-WRONG on `zabz-tech-linux`**: "no `/mnt/c`, no `ha-config` checkout anywhere
  under `/home`, `/mnt`, `/srv`, `/opt`, `/root`" — it stopped rather than audit the wrong tree.

The broker routes remote because local commit pressure reads 91.9 % (`pressure check = local pressure HIGH
— 60389 MiB of 65173 MiB physical committed`), so it will not place children on `zabz-tech`, which is the
only host holding both current checkouts. `scp` and `sftp` are unavailable on both remote targets
(`subsystem request failed on channel 0`), so the canonical files cannot be pushed to the nodes it does
choose.

**Decided:** run the analysis fleet with `subagent_local` on `zabz-tech`, and label every finding **LOCAL**
so nobody mistakes where it ran. Six remote children were interrupted before they could report against a
stale tree.

**This is a finding in its own right:** a fleet told to audit code that is 40 days old on the node it lands
on will produce confident, wrong findings, and nothing in the mesh's own report says so — the probe said
"LANDED-RIGHT" because the path existed. Path existence is not revision correctness.

**And the stale tree carried the answer the whole time.** `ZABZ-YOGA`'s 2026-09-17 commit message in
`ha-config` reads: *"the two traps they exist to prevent: a Dahua camera can report idle and fail every
snapshot, and **Home Assistant will not run shell control-flow keywords in a shell_command**."* The exact
defect fixed today was written down on another machine five weeks ago, in a commit message nobody read.
Knowledge that lives in a commit message on one node is not knowledge the system has.

---

### S33 — Exactly ONE push channel exists on the intrusion path, and three unused ones need no server at all. HIGH.
Live `/api/services` registers 14 `notify` services including `mobile_app_zabz_waze`, `mobile_app_iphone_15`
and `mobile_app_monty`. The intrusion path uses **none** of them — they are called only by
`automations/outside_door_stuck_open.yaml:89,96`, i.e. wired to a door that stays open, not to a break-in.
Everything else on the alarm path is **pull**: `logbook.log` (`phoenix_intrusion_evidence.yaml:374,387`), the
"SECURITY PAGE FAILED" notification (`:363-373`), the dashboard cards, every system-health notification
(`system_health_monitoring.yaml:15,66,114,149` — all `persistent_notification.create`, no `notify.*`), and
`ha-watch`, whose own docstring says *"It does not text the owner: outbound is not this job's to spend."*

So the entire alarm rests on one chain — HA → Cloudflare → tunnel → API → owner-text gate → Twilio — and a
companion-app notification bypasses every link of it. **Cheapest robustness in the whole audit.**

### S34 — There is no heartbeat, and the thing that would have been one does not exist. HIGH.
No automation exercises the paging path on a schedule. `script.phoenix_test_intrusion_sequence` is manual and
sends `intrusion_test`, which the secretary declines to page — it proves reachability, never delivery.
`check-security-absence.py` exists but is in no crontab and no timer on the authority.
`scripts/check_intrusion_payload.py`, **cited as evidence** at `phoenix_intrusion_evidence.yaml:283`,
**does not exist**. `ha-watch` was green every 30 minutes through every failure in this ledger.

### S35 — The backend keeps no record an alert arrived, and the rule meant to act on it is dead code. HIGH.
The handler writes no task, goal, memory or event row; the only durable trace is the `sms_log` audit row inside
`send_message`, so a page that never sent leaves nothing at all. `activity_log` rows matching intrusion: 0.
`trigger_engine.ha:security_alert` (`trigger_engine.py:685-730`) cannot fire: it needs
`ctx["home_assistant"]["doors"]`, and `autopilot.py:6060-6067` passes only `{world_context, tick}`, so `doors`
is always empty and the rule returns `[]`. Even if it fired it would create a goal plan — a pull artefact, not
a page.

### S36 — The duplicate guard plus a fixed body means a second intrusion inside 30 minutes pages nobody. HIGH, two-minute fix.
`sms_service.py:873-901` refuses an identical body to the same number within 30 minutes, and the body is a
fixed string (`phoenix_security.yaml:214` plus `main.py:8599`). Two intrusions twenty minutes apart produce
identical text; the second is suppressed and recorded as a failure. **Fix: put the trigger timestamp in
`detail`** — which also supplies the idempotency key the retry path lacks.

### S37 — The owner's page can be held behind an open owner turn, and one is open right now. HIGH.
Live: `owner_text_turn` id **249**, sent 17:44:57Z, `answered_at` empty — 46 minutes old against a 12-hour
window. The page reaches the gate as `reason="send_message"`, `urgency="normal"` (priority 21) and does not
outrank it; `interrupt` is never passed. The wife's copy is unaffected — S28 from the other side.

### S38 — The gap between the siren and a human, quantified. SEVERE.
First human action anywhere per episode: **39 h 43 m 51 s** (10-24 22:21:49 → the 10-26 14:05:40 manual
reset), then 21 h 06 m, 17 h 05 m, 16 h 27 m, 14 h 42 m, 11 h 51 m. The 14:03 episode was 2 m 19 s — and that
was him hearing it, not being told.

### S39 — The deployed backend is newer than the checkout and differs where it matters. MODERATE (process).
`/opt/company` is at **8f19ab373 (2026-10-25)**; `main.py` `d0338adc` vs `f6955c96`, `owner_text.py`
`cf9cd80` vs `2bbdbca`, `sms_service.py` `6e59347` vs `5297e85`. It already carries a `rate_floor` refusal code
(170 refusals in seven days) and the `owner_text_context={subsystem: security_alert_mms, urgency: urgent}`
that the checkout lacks. Anyone editing this area reads `/opt/company`, never the repo. (Same finding as S32,
reached independently by a second workstream.)

---

### S40 — `phoenix_intrusion_test_mode` is set by the drill and cleared by **nothing in any YAML**. CRITICAL.
One `turn_on`, zero `turn_off` anywhere in `config/`; the only way back is a dashboard toggle
(`snapshots_admin.yaml:451,471`). While it is on, the next **real** intrusion is silent: the lights and the
siren are behind `if not test_mode`, and the page is sent as `event: intrusion_test`, which the backend refuses
without `force`. So a drill run and forgotten converts a real break-in into evidence capture only. This is
worse than S15, which only noted that the drill leaves the flags on.

### S41 — A dead or slow Mac aborts the sequence before the page, because the siren call has no `continue_on_error`. CRITICAL.
`phoenix_security.yaml:188` calls `rest_command.phoenix_alarm_mac_on` — `timeout: 5` to 192.168.50.45:8128 —
with no `continue_on_error`, and the page is at `:209`, after it. Any exception there ends the script, so
"the Mac mini is off" means "nobody is paged". HA's `script.py` re-raises anything that is not a caught service
error, so this is not theoretical.

### S42 — `shell_command` never raises on a non-zero exit, so `continue_on_error` on one protects nothing, and one of them lies in the logbook.
`components/shell_command/__init__.py:128-131` logs the failure and still returns `{stdout, stderr, returncode}`.
Two consequences: (a) `continue_on_error` on a shell command is decorative — the only thing that ever aborts is
an exception from `exec` itself (which is exactly what today's `for` defect was, which is why that one did
abort); (b) `phoenix_timeline.yaml:176-187` writes **"Evidence retention pass ran."** unconditionally, so the
logbook asserts success whatever happened. Six `nohup … >>/dev/null 2>&1 &` commands in the same file can never
report anything at all — the shell returns 0 instantly and the output is discarded.

### S43 — There is no telemetry for the machine the system runs on, and a third of the entities are silently unavailable. CRITICAL.
States scan for disk / memory / CPU / uptime / database / recorder / supervisor / host sensors returns only the
four backup sensors. No disk free, no memory, no CPU, no HA uptime or restart counter, no add-on health. The
6.8 GB-free arithmetic behind every retention bound is a hand measurement, not an instrument. Meanwhile **370 of
1,036 entities are `unavailable` or `unknown` (35.7 %)** and nothing says a word; only four automations react to
`unavailable` at all, all for the two ESP hubs plus the beacon. There is **no battery alert anywhere** while the
three perimeter door contacts read 51 %, 48.5 % and 47.5 %.

### S44 — The dead camera passes the roster guard because it is `idle`, not `unavailable`.
`phoenix_intrusion_evidence.yaml:129` tests `states(...) not in ['unknown', 'unavailable']`; the Dahua camera is
`idle`, so the snapshot call runs, fails behind `continue_on_error`, writes no file, and the verifier honestly
reports 3 of 4. A drill therefore "passes" with a quarter of the evidence missing. The roster comment claiming
two cameras are absent is also stale — both are present and `idle`.

### S45 — The cheapest regression check in this estate: one service call, one second, no siren, no page, no state change.
Call `shell_command.phoenix_verify_evidence_files` with `files: "/config/configuration.yaml"` and assert the
call **returns** with `PHOENIX_EVIDENCE_OK` in stdout and `returncode: 0`. Before 14:08 that call raised
`[Errno 2] No such file or directory: 'for'` in about a second — the entire 40-hour outage, caught with nothing
else running. Second check, which catches the ordering defect without an alarm: trigger on
`intrusion_active` → on for one minute, condition "active still on and `script.phoenix_intrusion_evidence_and_page`
not running" → notify. That fires on 10-25 23:24, 19:58 and 21:39. Both belong in a saved script with a
dashboard button.

### S46 — Two measurements disagree about 14:03:29 and I am recording it rather than smoothing it.
W8 reports that the flag going off at 14:03:29 is unattributable — no disarm trigger and no reset run in the
logbook. My own read of `/api/logbook/2026-10-26T18:03:00Z` shows, at that exact second,
`Phoenix: Extreme Intrusion Disarm | triggered by state of binary_sensor.phoenix_everyone_away`,
`Intrusion System Active`, and `Phoenix: Intrusion Reset | started` (three lines). One of the two readings is
wrong. Mine is quoted with its timestamps; W8's window may have started after those lines. Unresolved, and it
matters only for the attribution, not for the defect.

---

### S47 — The perimeter is three door magnets. No window, no glass, no shop side, no back, and the `maglock` door has nothing. CRITICAL.
`GET /api/states` with `device_class: door` returns exactly six entities: three contacts and their three
template twins. `window|opening|garage_door|smoke|gas|moisture`: zero window sensors. The tamper class is three
entities, all off. `maglock` is unlocked **by name** in `access_control.yaml:499-506`, so the access model
treats it as a real door, and no sensor covers it. Whether it is a separate door or a second lock on the front
door is unresolved and changes the size of the gap — it needs eyes on the doorway.

### S48 — The three contacts the whole system rests on are at half battery, due around 2026-12-09, and nothing watches them. HIGH.
`51 %`, `48.5 %`, `47.5 %`, every `*_battery_low` flag `off`. No automation anywhere reacts to a sensor going
`unavailable` or `unknown` — the ESPHome health automations watch the **hubs**, not the sensors that carry the
alarm. Arithmetic from W5: about 50 % lost in the 41 days since the 2026-09-15 replacement, so ~85 days of life,
so they are due on or about **2026-12-09**. A battery warning belongs in place before then, not after.

### S49 — A latched contact is a blind door, and this has already happened for days. CRITICAL.
The trigger fires on the edge `to: "on"` only (`phoenix_security.yaml:24-36`), so a contact stuck `on` can never
fire it — and it also pins `zone_*_active` on, killing the zone half of the same trigger.
- **Measured history:** `/api/history/period/2026-10-19…filter=phoenix_outside_door_contact` returns **one point
  for a full business day** (`10/18 20:00 on`), while the interior door logged 13 normal transitions in the same
  window. Followed out: `on` until **10/21 15:02:03** — the front door was latched `on` for at least **67 hours**,
  during which the main entrance could not alarm and read as a door standing open. Zero trigger runs in that
  window; `phoenix_intrusion_reset` ran 51 times.
- **Right now:** `phoenix_control_room_interior_door_contact` is `on` since 14:16:25, so that door and
  `zone_control_room_active` are edge-dead at this moment.

### S50 — The intrusion doorbell photo is 640×480 while the same camera is photographed at 2560×1920 every day. CRITICAL, one line.
`latest_intrusion_doorbell.jpg` = 55,143 B, **640×480**. `latest_person_doorbell.jpg` = 542,147 B,
**2560×1920** — same camera, the routine parcel path. Sixteen times fewer pixels on the one frame that would
identify an intruder. `scripts.yaml:241-244` already records that `camera.video_doorbell_fluent` is not the
right entity and `:248` points at `camera.reolink_video_doorbell_poe_clear`; the intrusion roster at
`phoenix_intrusion_evidence.yaml:126` was simply never updated.

### S51 — CORRECTED in part: only ONE roster camera is dead, and the "empty channels" claim is stale.
R2 measured the cameras directly and found the repo's channel table is stale:
- `camera.cam_larry_s_exit_main_2` is **alive**: HTTP 200, 2560×1440, 300,843 B, and its burned-in OSD reads
  **"Deserted House Exit"** — the same physical camera as `cam_deserted_exit_*` under a second config entry. It
  must not be deleted as though it were an empty channel.
- `camera.cam_larry_s_interior_main` is the one that is dead (HTTP 400 on the roster's own call, HTTP 500 on a
  direct fetch), and its evidence tile is the only 404 of ten probes.

What stands: that roster slot is a guaranteed failure on every intrusion, the waiting-room and exit views are not
in the roster, and a real event produces three stills where the hardware can produce five.

### S52 — Owner and intruder are still indistinguishable, and the fix is one condition using data that already exists. CRITICAL.
The trigger's whole condition set is `everyone_away == on` and `intrusion_active == off` — the discriminator is
"is the room empty", not "did someone badge". Measured: `everyone_away` rose 12 times in 24 h, the alarm fired
four times, all four from `zone_hallway_active`, and three were disarmed within 38 s by occupancy. Four false
alarms out of four.

The data to fix it is already flowing. `input_text.phoenix_access_control_log` currently reads
`Oct 26, 1:22 PM - Owner Access at Interior / … 11:28 AM - Owner Access at Maglock`, written by
`access_control.yaml:160-169` from an `esphome.access_control_keypad_entry` event carrying `code`, `door_name`
and a resolved role; RFID tags exist too. **Mechanism:** one `input_boolean.phoenix_credential_valid`, one
120-second timer started when the role resolves, and one added condition on the trigger —
`condition: state, entity_id: input_boolean.phoenix_credential_valid, state: "off"`. That changes the rule from
*"a door opened while nobody is marked present"* to *"a door opened and nobody badged"*, which is the rule the
owner actually wrote down, and it removes the false-alarm class without widening any window.

### S53 — A measurement rule worth keeping: `/api/logbook/<start>` and `/api/history/period/<start>` return at most 24 hours from the start.
Not "to now". W5's first seven-day logbook call returned 2,872 entries ending exactly 24 h after the start
timestamp. Any count taken from an unbounded call is a one-day count dressed as a period.

### S54 — My own recommendation changes: the credential gate beats "door contacts only".
In my earlier note to the owner I recommended dropping the doorbell zone and arming on the three door contacts.
S52 is better and I withdraw mine: a contact-only trigger still fires on every person who walks up to the door
(through `zone_hallway_active`) unless that entity is also removed, and it leaves the "is the room empty"
inference as the only discriminator. Gating on a **credential window** attacks the actual rule, needs no new
hardware, and lets the perimeter approach sensor stay — in the snapshot trigger, where it belongs.

---

### S55 — The root cause of every false arm: `zone_hallway_active` is fed by an outside sensor. CRITICAL, one deleted line.
W2 replayed the trigger list, both conditions and the 6 s re-check against 40,325 logbook entries and
reproduced **all six arms to the exact second**. Attribution: every one of the six came from
`binary_sensor.zone_hallway_active`; not one came from a door contact or from `zone_control_room_active`.

And the zone is built on an entity the same file calls perimeter:

```yaml
presence_architecture.yaml:16   # ZONE 1: OUTSIDE (Perimeter)
   is_state('binary_sensor.video_doorbell_person', 'on') or ...
presence_architecture.yaml:42   # ZONE 2: FRONT HALLWAY (Transitional)
   is_state('binary_sensor.video_doorbell_person', 'on') or ...
```

Of 61 zone edges, **40 came from the doorbell person sensor**, 12 from the outside door, 5 from the exterior
door, 4 from the interior door. That sensor fired **92 times in 42.68 h**, and **47 of those had no entry within
300 s** — people who walked past.

The incident, second by second: `14:03:00` worker→off; `14:03:15` doorbell person → zone_hallway → trigger;
`14:03:21` armed; **`14:03:26` the door actually opens, eleven seconds after the alarm decided**; `14:03:29`
presence credited → disarm; `14:03:43` siren. The person was still outside when it armed.

**Delete the `video_doorbell_person` term from `zone_hallway_active` and the 14:03 incident cannot happen**:
the first trigger becomes the door contact at 14:03:26, and the existing 6 s re-check lands at 14:03:32 — after
the 14:03:29 disarm — so the grace window aborts it with no other change.

### S56 — Do not widen the grace window. I withdraw that recommendation.
Measured detection→occupancy latency: **min 1 s, p50 66 s, p90 275 s, max 298 s**. Catching the median false arm
would cost **66 s of real siren delay on every genuine intrusion**; p90 would cost four and a half minutes. The
earlier suggestion of 6 s → 20 s is withdrawn on that arithmetic. If it moves at all: 6 s → 12 s.

### S57 — The camera half of both zones has never fired. CRITICAL (contradicts a recorded claim).
All **35** `binary_sensor.cam_*_2` entities produced **zero** logbook entries across 42.68 h, and the recorder
excludes only two unrelated entities, so this is real and not a filter. The 2026-09-16 comment asserting those
entities were "verified live" is **false in the record**. Both zones are door-contact detectors wearing a motion
sensor's name.

### S58 — "Not already active" is a deafness that lasted twelve hours.
28 of 148 trigger edges were discarded by that one condition during the 10-25 latch. The building was not
armed, nothing was siring, and every subsequent trigger was thrown away silently.

### S59 — `everyone_away` reads `unavailable`, and `mode: single` drops simultaneous triggers.
`unavailable` is not `on`, so both the arming condition and the 6 s re-check fail — 12 episodes in the window.
Separately, at `22:21:25` seventy entities changed in one second and `mode: single` dropped **3 of 4**
simultaneous triggers.

### S60 — CORRECTED: the recorder keeps ~28 days, not 1.8. Three workstreams and I were all wrong, the same way.
The original claim here — "the recorder holds 1.8 days, so the evidence expires within days" — is **false**, and I
told the owner it in a message. Read from the database itself on the host, not through the API:

```
sqlite3 file:/config/home-assistant_v2.db (read-only)
  states: rows=2,335,006  oldest=2026-09-28T00:26:03Z  newest=2026-10-26T18:47:15Z
  distinct days in states: 26
```

Twenty-six days, against `configuration.yaml:177 purge_keep_days: 30`. The retention is working as configured.

Why four independent measurements said otherwise: W2 and W5 built their windows from `/api/logbook/<start>`,
which returns **at most 24 hours from the start**, and W8 read `/api/error_log`, which is a ring buffer cleared
at restart. R2 was the one who caught it, by sampling isolated days instead of trusting a single window. **The
API's window is not the database's retention**, and a query that returns 42 hours of a 26-day store looks exactly
like a store that holds 42 hours.

What survives of the finding: the logbook *API* is awkward and silently truncates on a full-range call, and the
error log is genuinely short-lived (62 lines since the last restart). What does not survive: "the evidence for
this incident disappears within days". It has about a month, which is enough to learn from — provided the
labelled record is written down before then.
### S61 — What the arming posture should be, now that all eight workstreams are in.
Three candidates were on the table. The measured answer:
1. **Delete `video_doorbell_person` from `zone_hallway_active`** (S55). One line, provably prevents the incident,
   needs no new data, and leaves the grace window alone.
2. **Gate the trigger on a credential window** (S52). One boolean, one 120 s timer, one added condition. Changes
   the rule from "a door opened while the room looks empty" to "a door opened and nobody badged", which is the
   rule the owner actually wrote. This is the principled fix and it should follow (1).
3. **Widen the grace window** — withdrawn (S56).
"Arm on door contacts only" is subsumed by (1) plus (2); it was my earlier suggestion and it is the weaker one,
because it still leaves inferred occupancy as the only discriminator.

---

## Part 1 — fleet findings

_(appended as each workstream reports; each item states its evidence and the workstream that found it)_

Workstreams re-dispatched **LOCAL on `zabz-tech`** 2026-10-26 18:35 UTC, all read-only, each verifying the
sha256 of the file it read against the ledger (`phoenix_security.yaml` `E6B45F6B1C04`,
`phoenix_intrusion_evidence.yaml` `6FF9A7142D0D`):
W1 adversarial review of today's three fixes · W2 trigger/arming · W3 response chain and failsafe ·
W4 paging path · W5 detection coverage · W6 observability · W7 red team · W8 same-defect sweep.

---

### S20 — The receiving end proves it too: the paging endpoint was never called, in the whole retained journal.
`company-api.service` on `secratary-cloud` is the process that serves `/webhook/ha/security-alert`
(`/opt/company/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002`, pid 3852236,
cgroup `/system.slice/company-api.service`). Its journal runs back to **Oct 14 06:26** — twelve days — and
contains exactly **three** lines mentioning `security-alert`:

```
Oct 26 18:16:04 ... "POST /webhook/ha/security-alert HTTP/1.1" 200 OK      <- my deliberate test event
Oct 26 18:16:40 ... "POST /webhook/ha/security-alert HTTP/1.1" 200 OK      <- my 14:16:40 test drill
Oct 20 06:47:54 ... (an unrelated task title containing the word)
```

**Zero intrusion pages arrived in twelve days.** That is the same fact as S1 measured from the other end, by
an independent instrument, and it also rules out "the page was sent but rejected": nothing arrived to reject.

How I nearly got this wrong, because it matters: my first attempt was
`journalctl -u secretary-api | grep -c security-alert` → **0**, with the unit reporting `inactive` and
`no such unit`. A zero from a unit that does not exist is not a negative, it is a refusal. The real unit was
found from the listening socket (`ss -ltnp` → pid 3852236 → `/proc/3852236/cgroup`). The rule "a refusal is
not a negative" earned itself again.

---

### S27 — CORRECTION to two children and to me: the alarm flag does NOT restore ON across a restart, because `initial:` is set. SEVERE (but not the way it was reported).
W1 and W3 both wrote that a restart mid-alarm leaves `input_boolean.phoenix_intrusion_active` restored to
**on**, keeping the house unarmed. That is **wrong**, and the source says so plainly — HA 2025.10.3
`components/input_boolean/__init__.py:193-201`:

```python
async def async_added_to_hass(self) -> None:
    # Don't restore if we got an initial value.
    await super().async_added_to_hass()
    if self._config.get(CONF_INITIAL) is not None:
        return
    state = await self.async_get_last_state()
    self._attr_is_on = state is not None and state.state == STATE_ON
```

`phoenix_intrusion_active` is declared with **`initial: false`** (`phoenix_helpers.yaml:99-102`), so the
`return` fires, nothing is restored, and it comes up **off** after every restart. Same for
`phoenix_intrusion_test_mode` (`:104-107`).

What that means after a restart in the middle of an alarm: the strobe stops (the loop does not resume, and its
condition would now be false anyway), the flag is clean and the house is armed-capable again — but the Mac
siren, which is a latch in a different process, **keeps sounding** because nothing on `homeassistant.start`
posts `mac_off`. So S14's hole is real but narrower and specific: the stuck thing is the audio, not the flag.

**The general rule worth keeping:** in this estate an `input_boolean` with `initial:` never restores, and one
without it always does. Neither behaviour is visible at the point of use.

---

### S28 — The page can reach the wife and be refused for the owner, and HA calls that a total failure. CRITICAL.
`send_security_alert_mms` passes `bypass_owner_kill_switch=True`, which bypasses **only** the kill-switch file.
It does not pass `interrupt=True`, so the owner's copy still goes through the owner-text gate with
`reason="send_message"`, `urgency="normal"` and can be refused — `awaiting_reply` (12 h window, 45 min grace)
or the 20/day owner quota. The wife's number is not owner-recognised, so her copy skips all of it.

Measured scale of that gate: **827 `turn_awaiting_reply` and 911 `too_long` suppressions of owner SMS since
2026-10-01**. And `ok = all(results[r].ok)` (`sms_service.py:2126+`), so one refused recipient makes the whole
page "failed" — which, combined with the retry loop, is what produces the retry storm on a page the wife
already received.

Live-build delta worth knowing: `/opt/company` already passes `owner_text_context` urgency `urgent` +
subsystem `security_alert_mms` **for the relay**, but the gate call itself is still hard-coded
`normal`/`send_message`. So the wire is half-run in production. Found and cross-checked by W4.

### S29 — The roster is two phones, and the mother is not on it. OWNER.
`HA_SECURITY_EXTRA_RECIPIENTS` holds two entries; the second duplicates the owner target and is dropped only
by exact string equality. Effective roster: owner personal `…7895` and wife `…5096`. The mother (`…5878`) is
absent although decision `D240` recorded that she was meant to be paged. That is a family call, not a config
accident — it goes to the owner queue, not to a commit.

### S30 — No intrusion picture has ever been stored on the backend, and the media sentence is what can duplicate a page.
`/opt/company/data/security_media` **does not exist**, so every page to date would have been text-only no matter
what HA sent. Separately: the dedup added at `sms_service.py:1271` refuses an identical body for 30 minutes, so
HA's 12 s retries cannot storm — but the media-error sentence varies per attempt, so two *different* bodies
both send. Max today is 2 pages per recipient because of the `stop` bug (S22); fixing the loop alone would make
it 5.

The picture path itself works at both hops, measured from the authority by W4:
`http://…/local/snapshots/latest_intrusion_control_room_interior.jpg` → 200 `image/jpeg`, 298,175 bytes;
the public rehost route `/webhook/ha/security-media/<token>.jpg` → 404 for an unknown token (route live, not
Access-gated). Token is `token_urlsafe(32)`, 7-day expiry, traversal-proof, `no-store`. A 7-day public window
on an interior photo of the house is longer than it needs to be; hours would do.

### S31 — The HTTP timeout is a third of the work it asks for, and HA reaches the backend by tailnet name.
`rest_command.phoenix_security_page` has `timeout: 15`, while the handler can spend ~12 s on media + ~5 s
verifying the public URL + up to 3 Twilio attempts × 2 recipients. So a successful page can time out as
"failed" and be retried. `HA_URL` is `http://zabz-tech.tail93e6e6.ts.net:8123` (answers 200 in 58 ms, and is
not this machine — `127.0.0.1:8123` is closed here). When the secretary is unreachable the delay is bounded at
about 27 s by accident (12 s delay + 15 s timeout), and every later attempt plus the alarm is lost.

### S32 — The backend that runs is not the checkout we audited. MODERATE (process).
`company-api.service` runs `WorkingDirectory=/opt/company` with its own `.env`, and its `main.py` is
**804,096 bytes** against the checkout's **771,454** (`sha d0338adc7574` vs `f6955c96b0a4`). W4 re-verified
every load-bearing construct by grep in the live build and recorded live line numbers, so the findings here
hold — but "the repo is the system" is false for the secretary, and any claim about its behaviour has to be
checked against `/opt/company`, not `C:\Users\ezabz\code\personal-secretary-mvp`.

---

### S21 — MY OWN FIX SILENCES THE PAGE. FATAL — a regression I introduced today, found by the adversarial pass.
The `condition` I added at `phoenix_security.yaml:180-182` aborts the whole sequence, and the page call sits
**below** it at `:209`. So on exactly the case it was written for — an arrival credited after the alarm armed
— the new behaviour is: no siren **and no page**. The owner is told nothing.

Worse, the disarm it relies on has non-credential triggers. `Phoenix: Extreme Intrusion Disarm` (`:82-96`)
fires on any `phoenix.valid_pin` **and** on `binary_sensor.phoenix_everyone_away → off`, and one writer of
those booleans needs nothing but a phone: `presence_architecture.yaml:287-313`
(`phoenix_passive_arrival_bluetooth_worker`) turns `worker_is_here` on when
`zone_control_room_occupied → on` **and** `device_tracker.monty == home`. A phone left charging, a stale
tracker, or a phone that arrives with the intruder is the discriminator between "a worker came in" and
"somebody is in the control room". Inside the 6 s grace plus the ~20 s of snapshot work, that credits an
intrusion as an arrival and now suppresses siren, loop and page together.

**Fix:** the page must not be gated by the disarm at all. Move the page step above the condition, or keep one
`condition` around the noisy half only (siren, strobe, loop) and let the page run unconditionally. A page on a
false alarm costs one SMS; a real intrusion that pages nobody costs the business. The false-alarm rate is then
a trigger problem (S5/W2), which is where it belongs.

### S22 — The retry loop runs backwards, and my fix is what let it run for the first time. FATAL.
`phoenix_intrusion_evidence.yaml:329-351` is `repeat: count: 4` whose body ends in
`if: not confirmed → stop: "page not confirmed - retrying"`. Verified in HA 2025.10.3 `helpers/script.py`:
`_StopScript` is caught at line 470 as `script_execution_set("finished")` and, because the repeat body is a
sub-script (`top_level=False`), re-raised at 473 to end the parent. So `stop` ends the **entire script** and
records it as **finished**, not failed. Consequences, both live now that the sequence reaches this step:

- **Failure is silent, again.** `stop` fires precisely when the page is unconfirmed, so at most 2 attempts
  happen (not 5) and everything after the loop is skipped: the fail-loud `persistent_notification` (`:356-380`),
  the audit `logbook.log` (`:387-391`) and the prune (`:392`) are unreachable, and the run reports success.
- **Success is duplicated.** If a retry succeeds the `if` is false, there is no `break`, and iterations 2-4
  send the same page again: up to **5 SMS+MMS to every roster recipient per intrusion**, and the script is
  `mode: queued, max: 5`, so five queued intrusions could send twenty-five.

**Fix:** `repeat: while:` on `(not confirmed) and (attempts < 4)` and delete the `stop` — a false `while`
ends the loop without aborting the sequence. Drafted in full in `W1-adversarial-fixes.md` §1.

### S23 — The siren can still stick in a ~5 s window after the fix. SEVERE.
`rest_command.phoenix_alarm_mac_on` (`:188`, `timeout: 5`) runs after the condition passes. A disarm landing
during that HTTP call means `intrusion_reset` has already posted `mac_off`, the alarm then posts `mac_on`, and
the loop's `while` is false on its first evaluation — so it exits without ever switching the audio off. Same
defect as 14:03:43, narrowed from 22 s to about 5 s. **Fix:** re-check the flag after `mac_on` and post
`mac_off`; make `mac_off` the loop's exit step; and keep the delayed fail-safe automation from S19.

### S24 — "Page delivered" is judged on the wrong field, and a non-JSON reply kills the fail-loud path. SEVERE.
The success predicate (`:322-327`) tests only `status < 400` and `content.ok`. The backend's own contract
(`personal-secretary-mvp/app/main.py:8547-8564`) says `ok` means *the SMS was sent, not that the picture was
attached*, and returns `media_ok` separately — so a text-only page counts as success, with no retry and no
notification, which is the exact defect this file was written to end.

Second half, verified in `components/rest_command/__init__.py` lines 208-213: `_content = await response.json()`
only for `application/json`, otherwise `await response.text()`. Any non-JSON 2xx (a CDN interstitial, a
Cloudflare Access page, a WAF challenge) leaves `content` a **string**, and
`(page_result.get('content') | default({}, true)).get('ok')` then raises `'str' object has no attribute 'get'`
inside an `if` condition — uncaught, so the fail-loud notification never runs either. **Fix:** require
`content is mapping` before `.get`, and warn visibly when `media_ok` is false.

### S25 — Cheap correctness items on the two commands (all verified, all small).
- `bash` is a PATH dependency; if it were ever missing the failure would be byte-for-byte the one just fixed
  (`FileNotFoundError: 'bash'` inside the service). `sh` is guaranteed (BusyBox) and nothing here needs bash:
  use `sh -c`. *(bash is present in the published HA docker-base, and the fixed command has run successfully
  four times today, so this is about not depending on it, not about a live break.)*
- `-mtime +14` deletes **15+** days old, not 14 (`find` truncates the day count). Comment at `:63` says 14.
  Use `+13` or fix the comment.
- `-mtime +0` excludes anything under 24 h, so "keep the newest 120" is really "keep the newest 120 that are
  at least a day old" — a burst cannot be capped. Use `-mmin +60` for the count rule.
- The prune has exactly **one** caller (`:392`), so if the page step aborts, nothing is pruned — indefinitely.
  It belongs in a daily automation of its own.
- `files` is re-parsed by bash after `shlex` strips the quotes, so it is shell code. No live injection path
  today (roster + `now().strftime`), but the service is callable: `bash -c 'for f in "$@"; ...' _ {{ files }}`.

### S26 — The lights still black the house out after a disarm. MINOR.
The lights block (`:142-160`) turns both switches off, waits 1 s, then on — and it sits **above** the new
condition, contradicting the comment at `:176-179` that "everything above it is evidence capture". At 03:00 a
disarmed alarm still kills the property's lights for a second. Move the condition above the lights block.

---

### S11 — THE OWNER PAGE IS SEQUENCED BEHIND THE SIREN LOOP, so it can only be sent after the alarm has stopped. FATAL — and this is the biggest one.
`phoenix_intrusion_initial_response` calls the loop as a **blocking** service step
(`phoenix_security.yaml:189  - service: script.phoenix_intrusion_loop`) and only afterwards calls
`phoenix_intrusion_evidence_and_page` (`:209`). A script called as `service:` returns only when it finishes,
and this one repeats `while input_boolean.phoenix_intrusion_active == on`. Therefore **the page cannot be
attempted until the alarm ends** — by disarm, or by HA's 10,000-iteration cap.

Measured on the runaway episode (logbook + history):
- `input_boolean.phoenix_intrusion_active` on **23:23:21**, off **11:25:25** (12 h 02 m), so no disarm.
- loop started **23:23:38**, `CRITICAL ... terminated because it looped 10000 times` at **02:14:22**.
- `Phoenix: Intrusion Evidence And Page | started` at **02:14:22** — the same second. The page was
  attempted **2 h 51 m 01 s after the intrusion**, and only because the loop had just been killed.
- 14:03 counter-example: the loop's condition was already false, it exited at once, and the page started in
  the same second. The ordering, not the backend, is what delays the page.

**Consequence:** repairing S1 alone would not have paged anyone at 23:23. It would have paged at 02:14.
My earlier sentence to the owner — "the page will now go out" — is true only in the case where the alarm
ends immediately. **I withdraw the implication that the paging path was fixed end to end.**

**Fix (one line, either form):** call it non-blocking (`service: script.turn_on` with `entity_id:
script.phoenix_intrusion_loop`) so the sequence continues to the page while the strobe runs, or move the page
step above the siren step. Found by W3; confirmed here by reading `:184-214` and the logbook timestamps.

### S12 — The overhead siren is a latch with no timeout, behind an unauthenticated HTTP endpoint, and it ran for 12 hours. CRITICAL.
`/Users/lpt/alpine-mac.py` on the Mac mini (136 lines, launchd `com.abletel.alpine-alarm`, pid 973, uptime
**7 d 22 h**, listening on `*:8128`):
- `POST /alarm/on` → `start_siren()`: sets `State.alarming = True`, starts `_siren_loop()`, which is
  `while not State.stop_event.is_set(): subprocess.run(['afplay', SIREN_WAV])`. **No timeout anywhere.**
- `POST /alarm/off` is the only thing that clears it. `do_POST` checks `self.path` and nothing else —
  **no authentication**, and `Access-Control-Allow-Origin: *`.
- `GET /health` returns `{"ok": true, "alarming": false, ...}` right now. (W3 reported "no state route";
  that is wrong — `/health` is the state route, and it was read.)

Why 12 hours: HA called `/alarm/on` at ~23:23:38 (the sequence posts it immediately before the loop); the
retained HA log contains **zero** `rest_command` failures, so the POST was accepted; nothing called
`/alarm/off` until the 11:25:25 disarm (`Extreme Intrusion Disarm` → `Intrusion Reset` → `mac_off`, confirmed
in the logbook); the listener's process did not restart in between (7 d 22 h uptime). Corroboration: the
Mac's output volume is **100**, and `_crank_volume()` is only reachable from `start_siren()`/`play_test()`.

**Honest limit:** the listener proves the latch was ON and the `afplay` loop was running; it does **not**
prove anyone heard it — that depends on the amplifier being powered. Nobody can answer that but the owner.

### S13 — "Flash & Audio" has had no audio since the Alexas were removed; the 15 s timer it used is orphaned.
Loop body is 4 steps: `homeassistant.turn_off` (2 lights) → delay 200-800 ms → `turn_on` → delay
(`phoenix_security.yaml:228-244`). Steps 246-248 are a bare comment, "B. Periodic Audio Overlay (Every ~15s)",
with nothing under it. `timer.phoenix_intrusion_loop_timer` (15 s, `phoenix_helpers.yaml:216`) is started by
nothing and triggers on nothing. W3 traced it to git: introduced `de6116a`, removed `8102b74`. The alias name
is a lie and the audit trail reads as if audio existed.

### S14 — There is no fail-safe of any kind. SEVERE.
No timeout, no stand-down, no second path. `phoenix_alarm_mac_off` has exactly **one** caller in the whole
configuration (`phoenix_intrusion_reset:253`), and that script is reached only by the disarm automation or a
dashboard button. Nothing on `homeassistant.start` touches the siren or the flag, so after a restart
mid-alarm the siren keeps sounding and the loop does not resume.
*(Corrected by S27: the flag does **not** restore ON — `initial: false` means it comes up off. Read S27 for
the source; the stuck thing after a restart is the audio, not the flag.)*

### S15 — The test button leaves the alarm disarmed. SEVERE footgun.
`phoenix_test_intrusion_sequence` (`:259-268`) turns on `phoenix_intrusion_active` **and**
`phoenix_intrusion_test_mode`, then runs the response. Nothing turns either off. While the flag is on, the
trigger automation's `state: "off"` condition blocks every real intrusion — silently. Measured today: the
14:16:10 drill left both on, and a human (me) cleared them at 14:17:21, 71 s later. A drill run and forgotten
is an unarmed building.

### S16 — Neither dashboard button is a full stop.
`snapshots_admin.yaml:449` puts the raw `input_boolean.phoenix_intrusion_active` toggle directly above the
`script.phoenix_intrusion_reset` button (`:461`). Turning the flag off stops the strobe within one iteration
and leaves the siren latched on forever (nothing else calls `mac_off`). Pressing Reset silences the siren and
restores the lights but **does not clear the flag**, so the strobe continues and the house stays unarmed.
Both behaviours are readable straight off `phoenix_intrusion_reset:249-258`, which never touches the flag.

### S17 — Two camera clocks, both wrong, sixteen minutes apart. MODERATE (evidence integrity).
Burned-in OSD read against a known capture time, both from the 14:16:35 drill:
- doorbell (`intrusion_20261026_141635_453744_doorbell.jpg`, Reolink): OSD `26/10/2026 13:21:04` at a
  14:28:41 capture → **67 m 37 s behind**; the 14:03:33 frame read `12:55:41`, i.e. 67 m 52 s behind.
- front hallway (`..._front_hallway.jpg`, Dahua): OSD `2026-10-26 13:25:11` at a 14:16:35 capture →
  **51 m 24 s behind**; the control-room frame read `13:12:22` at ~14:03:41 → 51 m 19 s.

So the two camera systems disagree with the wall clock by different amounts. Any frame offered as evidence —
insurance, police, a customer dispute — carries a timestamp that is wrong by an hour, and frames from the two
systems cannot be aligned to each other without knowing both offsets.

### S18 — Correction to my own claim about the drill. MODERATE (integrity).
I said the 14:16:10 drill proved the new disarm guard works. It did not. Both the lights and the
siren/loop/page branch sit inside `if not test_mode`, and test mode was on, so the drill never executed the
branch the guard protects — it produced no `script.phoenix_intrusion_loop` logbook entry at all. What the
drill proved is narrower and still worth having: evidence capture runs, the verify shell_command works, and
the sequence reaches step 7. The guard itself remains verified by reading, not by execution.

### S19 — The guard narrows the race; it does not close it. SEVERE.
The condition at `:180-182` and the `rest_command.phoenix_alarm_mac_on` at `:188` are separate steps, so a
disarm landing in the milliseconds between them still leaves the siren on with no caller to stop it, because
the disarm path never re-sends `mac_off` afterwards. The durable fix is a second path that turns the siren off
whenever the alarm is not on — an automation on `input_boolean.phoenix_intrusion_active` → off (and on
`homeassistant.start`) that posts `mac_off`, delayed a few seconds so a late `mac_on` lands first. W3 drafted
it (`W3-response-chain.md` §2 F2). Not applied — behaviour change, owner's review.

---

### Owner decisions — asked one at a time, never as a list
Owner, 2026-10-26, after this audit arrived with four questions in one message: **"one question at a tinme"**.
The rule is his and it is binding: one decision per message, with a recommendation attached and the question
last. The four that exist are recorded below in the order they will be asked; each is only asked when the one
before it is settled.

1. **Credential gate** — arm the alarm on "a door opened and nobody badged" instead of "a door opened while the
   room looks empty" (S52, C31). *Asked first: it changes what counts as an intrusion, it subsumes the arming
   posture question, and everything in Stage 3 waits on it.*
2. **The mother on the intrusion page** — `D240` says she was meant to be; the live `.env` says she is not (S29).
3. **A non-admin HA token for the agents and TOTP on the owner account** (W7#1, C16).
4. **Windows and glass-break sensors** — a spend, so it is sized by the owner (S47, C34).

---

## Part 2 — the change set, in the order that makes the alarm work

Each item: what it fixes, effort, risk, and whose call. Effort is my estimate of hands-on time, not elapsed.
**Nothing here is applied yet** — this is the list to go through.

### Stage 1 — make a page possible at all (must ship together, ~45 min)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C1 | Move the page **above** the disarm `condition` and above the siren step; gate only siren/strobe/loop on the flag | S11, S21 | 10 min | low |
| C2 | Call the loop non-blocking (`service: script.turn_on`, `entity_id: script.phoenix_intrusion_loop`) so the sequence continues while the strobe runs | S11 | 5 min | low |
| C3 | Rewrite the retry as `repeat: while: (not page_ok) and (attempts < 5)`, delete the `stop`, so failures reach the fail-loud block | S22 | 20 min | low-med |
| C4 | Require `content is mapping` before `.get('ok')`; treat `media_ok: false` as a visible warning, not success | S24 | 10 min | low |
| C5 | `rest_command.phoenix_security_page` `timeout: 15` → `45` | S31 | 2 min | low |
| C22 | Add `notify.mobile_app_zabz_waze` and `notify.mobile_app_iphone_15` to the initial response, `continue_on_error: true`, critical priority, tag `phoenix_intrusion` — a push that needs no server, tunnel, Twilio or owner-text gate | S33 | 10 min | low |
| C23 | Put the trigger timestamp (and the existing `stamp`) into `detail` so a second intrusion inside 30 min is not swallowed by the body dedup, and so the retry has an idempotency key | S36 | 5 min | low |
| C24 | Page first, pictures second: send the page with `snapshots: []` before the evidence work, then attach pictures in a second message | S11, W6#F1 | 15 min | low |
| C25 | `continue_on_error: true` on `rest_command.phoenix_alarm_mac_on`, so a Mac that is off cannot abort the sequence before the page | S41 | 2 min | low |
| C26 | Make the drill self-cleaning: append `test_mode` off and `intrusion_active` off at the end of `phoenix_test_intrusion_sequence` | S40, S15 | 5 min | low |

Why together: C1 alone silences the page (that is S21); C3 alone raises duplicate sends (that is S22);
C22 is the only change here that keeps working when the server, the tunnel or the gate is down; C25 and C26
are two minutes each and each removes a way for the alarm to be silent or stuck.

### Stage 2 — make the siren stoppable (~1 h 40)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C6 | New automation: on `input_boolean.phoenix_intrusion_active` → off, on `script.phoenix_intrusion_loop` → off, and on `homeassistant.start` → wait 3 s → `rest_command.phoenix_alarm_mac_off` three times, 10 s apart | S19, S23, S14, S8 | 20 min | low |
| C7 | Mac listener: shared-secret header, bind to the LAN address only (drops 11 tailnet devices), **self-stop after N minutes unless refreshed**, keep `GET /health` | S12, W7#5, W7#8 | 40 min | medium — it is the only audible path, so test with `/test` |
| C8 | One SILENCE control that does all three (flag off, `mac_off`, lights on); remove the raw `input_boolean` toggle from the dashboard card | S16 | 20 min | low |
| C9 | Test button: clear both booleans automatically after N minutes | S15 | 20 min | low |

### Stage 3 — stop the false alarms (~1 h, one of these is his call)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C10 | Delete the `video_doorbell_person` term from `presence_architecture.yaml:42` (`zone_hallway_active`), so the hallway zone only follows doors. Measured: this alone aborts the 14:03 incident inside the existing grace window | S55, S5, W2 | 5 min | low |
| C31 | Add the credential gate: one `input_boolean.phoenix_credential_valid` set by the keypad/RFID role resolution, a 120 s timer, and one added condition on the trigger — `state: "off"`. Changes the rule from "door opened while the room looks empty" to "door opened and nobody badged" | S52, S61 | 40 min | medium (needs every legitimate entry path enumerated) |
| C11 | Remove `media_player.control_room == 'playing'` from `zone_control_room_occupied`; require the mmWave sensor for passive arrival; shrink the shop's `zone.home` radius | W7#4 | 30 min | medium (changes who is credited) |
| C32 | Roster: point the doorbell slot at `camera.reolink_video_doorbell_poe_clear` (2560×1920, not 640×480), drop the empty NVR channel 2, and add channels 1 and 5 | S50, S51 | 15 min | low |
| C33 | Latch detector: page when a door contact has not changed for 24 h while its siblings have, and when `phoenix_intrusion_active` has been on for 30 min with `everyone_away` on (page without clearing) | S49, S58 | 30 min | low |
| C34 | Hardware, **OWNER spends money**: window/glass-break sensors on the shop side and front glazing, and a contact on the `maglock` door | S47 | hardware | — |

### Stage 4 — know when it is broken (~1 h 20)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C12 | Dead-contact watcher: any of the three door contacts `unavailable` for 10 min → page | W7#7 | 20 min | low |
| C13 | Heartbeat every 30 min: trigger automation is `on`, `everyone_away` has changed in 24 h, the mini answers — else page | W7#6 | 30 min | low |
| C14 | Arm-state watchdog: flag on > 10 min while `everyone_away` is on → page; `everyone_away` off > 4 h with no credential event → page | S12, S14, W7#9 | 20 min | low |
| C15 | Camera clocks to NTP; re-measure all four offsets and record them | S17 | 30 min | low |
| C27 | Save the one-second regression check as a script with a dashboard button: call `shell_command.phoenix_verify_evidence_files` on a known file and assert it returns `PHOENIX_EVIDENCE_OK` | S45 | 10 min | low |
| C28 | Ordering sentinel: `intrusion_active` on for 60 s with `evidence_and_page` not running → notify | S45, S11 | 15 min | low |
| C29 | Host telemetry and an availability guard: disk free / HA uptime / restart counter, plus page on any of a named security roster going `unavailable` or any perimeter battery below 25 % | S43, S44 | 30 min | low |
| C30 | Bound `phoenix_intrusion_active` with a timer so a stuck flag cannot keep the building unarmed for hours | S12, S40 | 10 min | low |

### Stage 5 — credentials and the paging gate (~2 h, his approval on C16)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C16 | **OWNER**: create a non-admin HA user for agents, issue a token for it, enable TOTP on the owner account, move HA to https. The current token is owner+admin, no MFA, in plaintext `.env` on at least two hosts | W7#1 | 45 min | medium — every agent path uses that token; must be swapped, not revoked blind |
| C17 | Unregister `add_user` / `delete_user` / `modify_user` from `phoenix_access_manager`; add the counter + lockout to `validate_pin` | W7#2 | 30 min | medium |
| C18 | Add `house_guest_mode_active`, `intrusion_active`, `intrusion_test_mode` to the tamper guard, and stop it failing open when `caller_user_id` is empty | W7#3 | 30 min | medium — automations that write those booleans must be enumerated first |

### Stage 6 — the page itself (~40 min)
| # | change | fixes | effort | risk |
|---|---|---|---|---|
| C19 | **OWNER**: roster — remove the duplicated owner entry, normalise numbers before the dedupe, and decide whether the mother is on the page | S29, W4#1 | 10 min | low |
| C20 | In the live build (`/opt/company`), finish the wire: pass the security context into `owner_text.gate`, use `reason="security_intrusion"`, pass `interrupt=True`, exempt from the daily quota | S28, W4#5 | 30 min | medium — it touches the owner-send path |
| C21 | Retention hygiene: `-mmin +60` for the count cap, `sh -c` instead of `bash -c`, `"$@"` for the file list, and move the prune to its own daily automation so it cannot be blocked by a dead page | S25 | 15 min | low |

### Owner decisions
Removed from here — the list was wrong twice over (it offered a choice the measurements have since settled, and
it was a list, which the owner does not want). The four live decisions, their recommended answers, and the
order they will be asked are in **"Owner decisions — asked one at a time"** above. One message, one question.

Everything not on that list is mine to execute without asking.

### What I would do tonight, in one pass, and what I would leave
Tonight: Stage 1, Stage 2 (C6, C8, C9), C5, C21, C12. That is about ninety minutes and it turns the
alarm from "cannot page, cannot be silenced" into "pages within seconds, always silenceable, and tells you
when it is blind". Stage 3 waits for the credential-gate decision. Stage 5 is a maintenance window of its own,
because swapping the token breaks every agent path at once.

---

### S62 — The Dahua snapshot call can return a DIFFERENT camera's picture and report HTTP 200. SEVERE (evidence that can lie).
config/custom_components/dahua/client.py:74-92 builds `channel_candidates = [channel_number]`, then appends
`channel_number - 1`, then `1`, then `0`, and finally tries `/cgi-bin/snapshot.cgi` **with no channel at
all** — which on an NVR returns the first channel's frame. So a still written under the name of a camera that
does not exist can silently be a picture of a camera that does, with no error anywhere.

That is a different and worse fault than "a dead camera": it means an evidence file can be mislabelled and nothing
in the pipeline would know. R2 could not settle whether `cam_larry_s_exit_main_2` is a genuine second config
entry on channel 1 or this fallback substituting channel 1's frame — both produce exactly what was measured, and
`.storage/core/config_entries` is not in the repository. The difference is "a redundant view" versus "evidence
that lies", and the code path makes the second possible for **any** future empty channel.

### S63 — The camera's own "video loss" sensor never fired, for a camera that has been returning HTTP 500 for 29 days.
`binary_sensor.cam_larry_s_interior_*_video_loss` has been `off` for 29 days while that camera produced no
image at all. So the one sensor whose job is "is this camera alive" is itself dead. There is no working
camera-health signal anywhere in the installation.

### S64 — All 54 Dahua detectors have produced ZERO events in 30 days, and the control proves it is not a filter.
30 consecutive 24-hour chunks, 54 live detectors, `minimal_response`: **ON points = 0 in every chunk**, 0 of 30
chunks containing any ON. The control, same query, same recorder, same window: `video_doorbell_person` fired
**99 times in 72 hours**. The recorder captures camera events perfectly well; these detectors simply never fire.

**Mechanism, and it is a switch:** `switch.cam_*_motion_detection_2` = `off` and
`switch.cam_*_smart_motion_detection` = `off` on all six groups, while `switch.cam_*_event_notifications` =
`on`. The inference is disabled at the camera, not broken. Turning it on is a switch — at the cost of 24/7
pixel-change events on a Raspberry Pi recorder.

### S65 — The camera clocks are wrong by different amounts, confirmed with a matched pair.
R2 found three tiles written by one automation run, showing the **same courier with the same parcel**: doorbell
OSD `13:21:03`, hallway `13:37:21`, waiting room `13:37:26` — **16 m 18 s apart**, against a real local time
of 14:44. That is the Reolink about **67 minutes slow** and the Dahua NVR about **51 minutes slow**, independently
confirming S17's measurement with a much stronger control. Any cross-camera timeline is wrong by 16 minutes before
any vision layer exists to use it.

### S66 — Direction of travel is achievable without a GPU, once the clocks agree.
The doorbell looks **out** and the "Main Entrance" camera looks **in** at the same doorway, so ordering two
detections gives in versus out. It is a two-sensor ordering problem, not a vision problem — and it is impossible
today purely because the two clocks disagree by 16 minutes (S65). Cheapest capability upgrade in the audit.

---

### S67 — The credential log is not a log: 255 characters, and every new entry destroys the seventh. HIGH.
`input_text.phoenix_access_control_log` is a single rolling string; `[:255]` appears on 13 lines of
`automations/access_control.yaml`. As it reads right now it holds **six entries spanning 24-26 October**. There
is no durable record of who entered beyond the logbook — and the logbook has a hole (S68).

### S68 — The 30-day history has a ~30-hour hole on 23 October. HIGH (contradicts "30 days of audit trail").
`GET /api/logbook/2026-10-23T14:44` returns **0 entries**, while the windows starting the 22nd, 24th and 25th
return 16,544 / 8,533 / 32,095. `/api/history/period` for `input_boolean.phoenix_worker_is_here` jumps from
2026-10-23 13:02 straight to 2026-10-24 19:44. Cause not established. Whatever the cause, the audit trail is not
continuous, and a system that learns from history must be able to detect its own holes.

### S69 — The per-user PIN system is registered, inert, and logs a full wrong PIN in cleartext. CRITICAL if enabled.
`phoenix_access_manager` exposes `validate_pin / add_user / delete_user / modify_user / buzz_in` (confirmed in
`/api/services`), but `sensor.phoenix_access_manager_users` is **404** and no entity matches `access_manager` —
the roster cannot be read from HA at all. Its only caller, `automation.phoenix_keypad_event_handler`, is **off**
(`initial_state: false`). So `phoenix.valid_pin` never fires, which means the "Extreme Intrusion Disarm"
automation cannot be triggered by a PIN today.

And `custom_components/phoenix_access_manager/__init__.py:118` does
`_LOGGER.warning(f"Invalid PIN entered: {pin}")` — **the wrong PIN in clear text**, in a retained log. That line
must be deleted before anyone turns the automation on.

### S70 — Two workers' RFID tags resolve to unknown, and both grant branches are dead code.
`access_control.yaml:52-66` compares only owner / worker_bachrach / wife. Klein's and Montrose's tags fall through
to "Unknown RFID tag" and an invalid-attempt counter, even though their tag helpers exist and are assignable. Two
live tags (owner, wife) and four live PINs (admin, parent, yocheved, house access) are the whole credential set;
every other helper is empty.

### S71 — Historical tag UIDs sit in a tracked file, attributed to names.
`config/secrets.yaml.example` is **tracked** (commit `08ec945`, 2026-09-07) and lines 12-17 hold six real-format
tag UIDs labelled Boss / Klein / Montrose / Bachrach / family / tenant, three marked "verified 2025-12-28". None
match the live helpers (compared without printing either side). Historical credentials — still name-attributed,
still in the repository.

### S72 — Two paths reach the doors with no credential at all, and neither is the ESPHome link.
The ESPHome native API **is encrypted on every committed device config** (`security-hub.yaml:61-63`,
`interior-door-hub-wifi.yaml:42-44`, `-wt32-eth01.yaml:90-92`; no `api: password:` anywhere), so a LAN attacker
cannot inject a keypad event without the Noise key. The caveat cannot be closed from here: that is the committed
YAML, not the flashed firmware, and `security-hub.yaml:64-66` still carries a commented-out "Encryption disabled
for now" block.

The real holes are elsewhere:
- **HA's event bus.** Any HA token can `POST /api/events/esphome.access_control_keypad_entry` with
  `{"code": "...", "door_name": "strike"}`; the master automation filters on event_type only
  (`access_control.yaml:15-19`). `HA_TOKEN` is in `personal-secretary-mvp/.env` and `HA_URL` is plain http, so
  that token crosses the office LAN in clear.
- **MQTT.** `script.buzz_in_strike` opens the outside door by publishing `{"state_l1":"ON"}` to
  `zigbee2mqtt/Smart Switch/set` (`scripts.yaml:948-951`), and z2m uses one shared broker user `addons`. Anyone
  with it opens the door and the only trace is "Smart Switch Unlocked" in the activity log — a relay state, with
  no person attached to it.

### S73 — Both maglocks are fail-safe: cutting the power unlocks the doors, and nothing records it.
Proven by the start-up assertion automation. A power cut therefore opens the building silently and leaves no
event. That is a physical fact, not a bug, and it belongs in the threat model: no alarm can cover a door that is
unlocked by design when de-energised.

### S74 — The house access PIN never rotates, although the automation to rotate it exists.
`automation.house_access_pin_auto_reset` is **off**, so the code does not change. Three PIN-enable flags
(`customer_pin_enabled`, `house_access_pin_enabled`, `drop_off_pin_enabled`) are all off, so the exposure is
latent rather than live today.


---

### S75 — An unattributed POST to the security-alert webhook, and the handler records no caller.
`journalctl -u company-api` shows `POST /webhook/ha/security-alert 200 OK` at **18:43:45Z** with no matching
alarm: `script.phoenix_intrusion_evidence_and_page` last ran at 14:16:35 (the drill), the flag was off, and the
logbook in that minute shows only presence churn (`Presence Warning Timer`, `Workers Are Here`,
`Phoenix Everyone Away` at 14:43:40). No app-level log line, no `sms_log` row — which is exactly what a POST
carrying a **test-type event** produces, because the handler returns `{ok:true, paged:false}` before it logs
anything or sends anything.

So: something holding that API key invoked the paging path, and **nothing records who, or what event it carried**.
That is the same hole as S35 from a different direction, and it is the reason the heartbeat design in R15 must
write a receipt row — a 200 with no record is indistinguishable from a real page that failed.

### S76 — The 30-hour recording hole, with its boundaries and its neighbour.
No recorder rows and no logbook entries of any kind between **2026-10-23 13:03:09 and 2026-10-24 19:44:43**
local — 30 h 41 min. Recording resumed **7 seconds after** `sms_log` id 4461: *"Shabbat automation problem…
relock_and_restore failed"*. Whether HA was down or merely not recording cannot be determined from HA data (no
shell on that host in the audit's scope). A learning system must emit a `recorder_gap` marker rather than
silently averaging across a hole.

### S77 — The door contacts show zero transitions before 21 October. Two readings, and I prefer mine.
R4 measured `binary_sensor.phoenix_outside_door_contact` with **0 transitions on 10-05…10-20** and 55 on 10-21,
and read it as "the contacts only start recording on 10-21". That is one explanation. The other — and the one
the history supports — is S49: the contact was **latched `on`** from 18 Oct 20:00 until 21 Oct 15:02, so a
stuck contact produces exactly zero transitions for those days. The history query shows one point at
`10/18 20:00 on` and the next state change at 10/21 15:02:03.

Either way the operational conclusion is identical and it matters more than the attribution: **a ratio computed
across that boundary is meaningless.** R4's own numbers show it — 11 % month-wide versus 62 % on days the
contacts actually recorded. All of R4's statistics were therefore restricted to 2026-10-20 20:10 → 10-26 14:43,
where all eleven signals record.

### S78 — The mmWave presence sensors are not presence signals.
`binary_sensor.control_room_hub_control_room_presence` covered 115 intervals in the dense window: 48 % overlap a
presence credit, **19 % contain an entry and no credit at all**. The other occupancy sensor: 130 intervals,
11.5 hours on, only **3 (2 %)** overlap a presence credit, 55 % contain an entry, **45 % neither**. It reports
movement, not people — which is consistent with the 80 firings at 1.9/hour it produced with the shop empty
(W7). Any fusion model that treats it as evidence of a person is fitting noise.

### S79 — The mechanism, measured across 13 episodes: the grace window expires exactly as the entitled human arrives.
Trigger→arm is 6 s in 12 of 13 episodes. **Arm→door-opened is 0 to 27 s in five of them**, and the doorbell sees
the person 5 to 15 seconds before they touch the door. So the 6-second re-check lands in the gap between "a
person is visible" and "the door actually opens", and every real alarm then ended the same way: by
`everyone_away → off` from presence credit. **Never by PIN, and never by a human.** That is why adding a
credential gate (S52) and removing the doorbell term from the zone (S55) are the two correct fixes, and why
widening the window is wrong (S56).

### S80 — Ground truth over 30 days: fifteen episodes, fourteen real, and ZERO unauthorised entries.
R4 labelled thirteen episodes in the dense window: **7 worker arriving, 1 owner arriving plus a sensor flap,
3 passers-by with no entry, 1 unknown, 1 drill.** In thirty days, not one episode was an actual intrusion.
Armed time totalled 21.2 hours, median episode 223 seconds, worst case **43,323 seconds** (12 h) with 20,001
strobe state changes overnight in a closed shop.

That is the single most useful sentence in the whole audit for designing the replacement: **the alarm has never
once been right about a burglar, and has been wrong fourteen times about the people who work there.**

### S81 — The truth table the fusion model has to beat.
On the days all signals record (2026-10-20 20:10 → 10-26 14:43, 108 doorbell clusters):
- doorbell cluster followed by a door contact within **300 s: 67 (62 %)**, without: 41 (38 %);
- within **30 s: 45 (42 %)** versus 63 (58 %);
- while `everyone_away` was on: **19 clusters, 12 with a door within 300 s, 7 without.**

So even the "tight" doorbell→door pairing is wrong about one cluster in three, and the honest baseline a new
model must beat is: *doorbell alone, 62 % precision at a five-minute window.*

### S82 — The fields a learning system must log from now, or it will have nothing to learn from.
From R4, in its words: the **leaf trigger input** (not the fused zone — the zone name hid the real cause for
weeks); `trigger_to_arm_s`, `arm_to_entry_s`, `arm_to_credit_s`; **`presence_basis`** on each presence boolean
(which signal credited it); **`acknowledged_at` and `ack_channel`** — because nothing records a human response
today, so "nobody noticed" and "noticed and ignored" are literally the same observation; `page_attempted` and
`page_http_status`; `script_aborted_at_step`; and a **`recorder_gap` marker**.


---

### S49 — CORRECTED BY THE OWNER: it was not a latch. The outside door is supposed to stand open.
Owner, 2026-10-26: *"the outside door is always open cuz that hallways is 24 6 pickup and dropoff."*

So the 67-hour "latched contact" I recorded here, and the 22.7-day open stretch R1 independently measured and
called "one stuck magnet blinded a zone for three weeks", are **both the building working as designed**. The
outside door is a public hallway entrance that stands open through the day. A contact that never changes was not
broken; it was describing the setup.

What survives: the trigger was edge-only, so a public hallway produced a zone that armed a building alarm
thirteen times. What does not survive: "the main entrance was blind for 67 hours" — the entrance was never a
secured boundary to begin with.

---

### S83 — The apartment door's keypad is real, programmable from HA, and its credential map is a hardcoded three-name list.
I asked the owner whether that door had a keypad. It does, and the code for it was already in this audit. The
path, read now in full:

- `scripts.yaml:772-792` — `script.ui_set_kwikset_pin`, which publishes
  `{"pin_code": {"user": <slot 1-30>, "pin_code": "<pin>"}}` to `zigbee2mqtt/Apartment_Door_Smart_Lock/set`.
  `script.lock_set_code` and `script.lock_clear_code` do the same for set and clear.
- `access_control.yaml:2160-2169` — an automation mirrors `input_text.phoenix_admin_pin` into **slot 1** and
  `input_text.phoenix_worker_pin` into **slot 2** whenever those helpers change. It is the only automatic sync,
  so with five subjects there are three slots no automation will ever populate.
- `access_control.yaml:2179` — the slot→name map is **hardcoded**: `1 = Boss`, `2 = Worker`, `3 = Guest`,
  anything else `User {{ user_id }}`. So slot 7 enters the record as "User 7".
- The lock reports `action_source_name` (`keypad` / `manual` / `rf`), `action_user` (the slot), and
  `sensor.0x002446fffd0a4705_pin_code` — **the last PIN used, in plaintext, as an entity state retained 28 days**.

So the apartment door has a genuine, named credential path. My assumption that it was mechanical was wrong, and
the answer was in the repository before I asked.

### S84 — A process failure worth more than the finding.
The owner's question — *"did you read all available info before you started working?"* — has an honest answer:
**no.** I had read `ui_set_kwikset_pin` and written the slot→name mapping into R3's section of this ledger hours
earlier, then two messages later asked him whether the apartment door had a keypad, because I formed the question
from a video frame instead of from the record I was holding.

The standing rule is explicit and I broke it: *ask him a question only after reading what the record already
answers.* Concretely, before any question about this building, in this order: `journal.py search` for the room or
the device; `grep` the config for the entity or the script; the entity's own history; and only then him.

