# W7 - Red team: how to stop the Phoenix alarm, or make it lie

**Ran on:** `zabz-tech-linux` (Linux, `uname` 6.8.0-111-generic). The repo path
`C:\Users\ezabz\code\ha-config` does **not** exist on this machine; it exists on the
Windows host `zabz-tech` (192.168.50.138), which is reachable over the SSH mesh.
Every file read and every network probe below was executed **on `zabz-tech`** (or,
where stated, from `zabz-tech-linux`), read-only. No `POST /alarm/on`, no
`POST /alarm/off`, no HA service call, no automation/sensor was changed. Token and
PIN values are deliberately withheld; only key names and capabilities are reported.

**Date:** 2026-10-26. **Repo revision:** `eb57dd8` plus untracked audit docs.

## Verdict in one paragraph

The alarm is easy to silence from the network and easy to keep from arming by
accident. The only audible siren is a Python HTTP server on the Mac mini with
**no authentication at all**, bound to every interface, reachable from the office
LAN and the whole Tailscale tailnet, with the macOS firewall off and no request
logging. One unauthenticated `curl` silences it; one held TCP connection can block
the legitimate `alarm/on` call. Separately, an **admin-scoped HA long-lived token**
sits in a 32 KB `.env` on a workstation plus four backup copies, and a second,
different admin token sits on the secretary server. The alarm's master condition
also **fails open**: an `unknown`/`unavailable` presence helper reads as "someone is
here", and an HA restart resets the intrusion flag. The system is good at capturing
evidence; it is not hard to keep the evidence from mattering.

## Ranked findings (impact x ease)

| # | Severity | Finding | Impact | Ease |
|---|----------|---------|--------|------|
| 1 | CRITICAL | Mac siren `:8128` has no auth; LAN + tailnet can silence or DoS it | Silences the only audible alarm | Trivial |
| 2 | CRITICAL | Admin HA token in `personal-secretary-mvp\.env` (+ 4 backups); second admin token on secretary | Full HA control: disarm, unlock, disable automations, read cameras | Medium (file read) |
| 3 | CRITICAL/HIGH | Any HA user can read PINs cleartext from `/api/states`; access-manager services have no admin check | Doors + disarm from a low-privilege account | Low if an account exists |
| 4 | HIGH | `phoenix.valid_pin` is a raw, unsigned event; an admin token can forge it with no PIN | Disarm without a credential | Low |
| 5 | HIGH | GPS alone sets `worker_is_here` on every HA start; a phone left at home disarms | Alarm silently never arms | Trivial (no attacker) |
| 6 | HIGH | `everyone_away` treats `unknown`/`unavailable` as occupied; restart resets `intrusion_active` | Disarm / no-arm on any restart or helper glitch | Low |
| 7 | HIGH | Any dashboard user can one-tap worker/guest presence or the Reset script; guard omits them | Silence the alarm from the UI | One tap |
| 8 | MEDIUM-HIGH | "Unknown presence" cross-check disabled by design; temp PIN rotation automation off | Blind to an intruder when presence is stale; permanent PIN | Already off |
| 9 | MEDIUM | Cloned iBeacon can latch "Boss is here" and disarm | Disarm / never arm | Medium (BLE clone) |
| 10 | MEDIUM | Zigbee jamming or coordinator reboot blinds door sensors with no offline alert | No detection, no page | Medium (jammer) |
| 11 | MEDIUM | Physical button triple-click toggles owner presence and disarms | Silence after entry | Low once inside |
| 12 | MEDIUM | HA restart or manual toggle during an alarm leaves the Mac siren running forever | Stuck siren / alarm fatigue | Operator action |
| 13 | LOW-MEDIUM | `trusted_proxies` includes all Cloudflare + Docker ranges; HA->secretary webhook is a static key | Spoofed source IP; fake pages if key leaks | Low |
| 14 | LOW | ~50 `unavailable` automation entities make a disabled real automation look like orphan noise | Security automation can be off unnoticed | Already true |

---

## 1. CRITICAL - The Mac mini siren can be silenced by one unauthenticated POST

**Attack (one sentence):** any device on the office LAN, or any device on the
Tailscale tailnet, can `POST http://192.168.50.45:8128/alarm/off` (or `/test`, or
`/alarm/on`) with no credential and no trace, and can hold a TCP connection open to
block HA's own `alarm/on` because the server is single-threaded.

**Proof.**
- `secretary.yaml:37-45` - HA calls `http://192.168.50.45:8128/alarm/on|off`
  with no headers, no key, no TLS.
- `/Users/lpt/alpine-mac.py` (read over SSH) - `do_POST` checks only
  `self.path`; there is no auth, no token, no source-IP check, and
  `log_message()` is `pass`. `HTTPServer(('0.0.0.0', 8128), Handler)` binds
  every interface. `do_GET /health` returns `{"ok":true,"alarming":...}` to
  anyone.
- From `zabz-tech` (Windows): `Test-NetConnection 192.168.50.45 -Port 8128`
  = **True**; `GET /alarm` = **404**, `GET /` = **404** (the listener answers).
- From `zabz-tech-linux`: `curl http://192.168.50.45:8128/alarm` = **404**;
  `curl http://100.126.146.121:8128/health` = **`{"ok": true, "alarming":
  false, "host": "LakewooechsMini"}`** - so the tailnet path is real, not
  theoretical.
- The Mac has two LAN addresses (`192.168.50.45` en0, `192.168.50.73` en1)
  plus Tailscale (`100.126.146.121`); `socketfilterfw --getglobalstate` =
  **"Firewall is disabled"**; `launchctl` shows `com.abletel.alpine-alarm`
  loaded, so it survives reboot.
- `python http.server` is single-threaded by default. One idle TCP connection
  to `:8128` blocks `accept()` for every later request; HA's `rest_command`
  has a **5 s** timeout (`secretary.yaml:40,44`), so the legitimate siren call
  fails while the attacker holds the socket.
- A web page can also drive this: the responses send
  `Access-Control-Allow-Origin: *`, and a `text/plain` POST is a simple
  request that a browser will send cross-origin without a preflight. Any
  browser on the LAN that visits a malicious page can keep posting
  `alarm/off` while an alarm is sounding.

**What it buys.** The only audible alarm. The strobe/lights still run, and the
SMS page still goes out, but the thing that makes an intruder leave and the
neighbours look is silent. It also allows the reverse: `POST /alarm/on` or
`/test` at 3 a.m. to manufacture alarm fatigue, so the owner learns to ignore
the siren. No attribution is possible because the handler logs nothing.

**Cheapest mitigation.** Bind the listener to `127.0.0.1` and put a tiny
authenticated proxy in front of it, or require a random path segment / HMAC
header known only to HA; allow only the HA host's source IP; switch to
`ThreadingHTTPServer`; log the client IP and every state change. Block 8128
from the tailnet and from guest Wi-Fi at the switch/firewall.

---

## 2. CRITICAL - The HA admin token is in a 32 KB `.env`, with four backup copies

**Attack (one sentence):** anyone who can read
`C:\Users\ezabz\code\personal-secretary-mvp\.env` (or one of its four
`.bak-*` siblings, or the secretary server's `.env`) gets an admin bearer token
for `http://homeassistant.local:8123`, which is reachable from the LAN, and can
then disarm the alarm, unlock doors, disable automations, read cameras and fire
arbitrary events.

**Proof.**
- `_ha-cred-20261018\ha.ps1` is four lines of PowerShell that read
  `HA_URL` and `HA_TOKEN` from that exact `.env` and send
  `Authorization: Bearer <token>`. So **yes, this is the same token the audit
  tooling uses** - by construction, not by coincidence.
- The token is a 183-character JWT (value withheld). `GET /api/config` with it
  returns **HTTP 200, version 2025.10.3**; in HA that endpoint is admin-only.
  The existing ledger already calls it "admin long-lived token"
  (`docs/AUDIT-2026-09-11-live-systems.md:7`).
- The directory has **five** files with a real 183-character `HA_TOKEN=`
  line: `.env`, `.env.bak-demote-2026-09-04-142658`,
  `.env.bak-keys2-2026-09-04-143023`,
  `.env.bak-striperoll-20260915`, `.env.bak-twilirot-20260915`.
  `.env.example` has the key but an empty value and is the only one tracked by
  git (verified with `git ls-files`). The four backups are untracked and are
  not covered by any rotation.
- The `.env` is **32,504 bytes** and also contains Twilio, Stripe, PayPal,
  Cloudflare, Hetzner, Mosyle, NanoMDM, Dialpad and multiple model-provider
  keys. One file read is a total business compromise, not just an alarm
  compromise.
- The secretary server `secratary` (192.168.50.77) has
  `/home/zabz/personal-secretary-mvp/.env` mode `600` with **a different**
  183-character JWT. That token also returns `/api/config` **HTTP 200** -
  i.e. there are at least **two live admin tokens**, and rotating one does not
  revoke the other.
- The HA URL is `http://homeassistant.local:8123`; TCP 8123 is reachable from
  `zabz-tech-linux` (verified with a bare TCP connect). The public name
  `ha.abletelsolutions.com` is behind Cloudflare Access (302 to
  `dawn-cell-26a7.cloudflareaccess.com`), so the token does **not** need the
  public host: LAN or tailnet is enough.

**What it buys.** Everything HA can do: `input_boolean.turn_off
phoenix_intrusion_active`, `automation.turn_off phoenix_extreme_intrusion_*`,
`script.phoenix_intrusion_reset` (Mac off), `lock.unlock`, `camera.snapshot`,
reading every state (including PINs, see #3), firing `phoenix.valid_pin` (#4),
and writing the `.storage` auth/registry through the websocket API. It is
"become the owner" with one header.

**Cheapest mitigation.** Rotate **both** tokens now and revoke the old ones;
delete the four `.bak-*` files; move secrets to an OS credential store or a
vault with an ACL, not a 32 KB flat file in a repo directory; give each
consumer its own scoped token (HA long-lived tokens are full-user, so put the
secretary behind a narrow proxy or use a dedicated non-admin HA user plus an
allowlisted set of services); restrict `homeassistant.local:8123` to the
machines that need it; add a startup check that the token still works and
alert on a new token being used.

---

## 3. CRITICAL/HIGH - Any HA user can read every PIN in cleartext, and the access-manager services do not check who is calling

**Attack (one sentence):** a low-privilege HA account - the kind a worker or
guest would have - can `GET /api/states/input_text.phoenix_admin_pin` and read
the owner's PIN in cleartext, or call `phoenix_access_manager.add_user` to
create its own PIN and `buzz_in` to unlock any lock, because the custom
integration never looks at the caller.

**Proof.**
- Live `GET /api/states/input_text.phoenix_admin_pin` returns a **4-character
  cleartext value**, not asterisks (value withheld). `mode: password`
  (`phoenix_helpers.yaml:5-7`) masks the *UI*, not the state machine. Every
  `input_text.*_pin` is exposed the same way.
- `config/custom_components/phoenix_access_manager/__init__.py:71-126`
  compares the supplied PIN, fires `phoenix.valid_pin` (which disarms, see
  #4 / `phoenix_security.yaml:84-100`) and calls
  `script.phoenix_relay_unlock_sequence` for every lock in the user record.
  `:128-195` registers `add_user`, `delete_user`, `modify_user` and `buzz_in`
  with **no `context.user_id` check, no admin check, no allowlist**. Any
  authenticated caller who can call services can add a user with
  `one_time=false` and any `locks` list, or unlock a named lock directly.
- The integration is live: `/api/services` lists all five
  `phoenix_access_manager` services.
- A non-owner account exists in practice: `person.montrose` carries a
  `user_id` attribute (`2269e9ed...`), i.e. the person is linked to an HA
  user. New HA users are non-admin by default. The worker-user helpers
  `input_text.ha_user_id_worker_*` are currently `unknown`, but the person
  link is enough to show the account model is in use.
- All dashboards are `require_admin: false` (`configuration.yaml:228-263`),
  including `phoenix-admin` and `snapshots-admin`, so a non-admin user can
  see the PIN fields (masked in the browser) and the presence toggles.

**What it buys.** A worker/guest/cleaner with an HA login can read the owner's
PIN, add a permanent backdoor PIN, unlock every door, and disarm. Even
without reading the PIN, `add_user` + `validate_pin` is a two-call backdoor.
This is the highest-leverage *insider* path because it needs no exploit, only
the account the system already hands out.

**Cheapest mitigation.** Never store PINs in `input_text` (the state machine
is readable by every user); move them into the integration's `Store` and expose
only a masked sensor. Add `context.user_id == owner` (or an admin check) to
`add_user`/`modify_user`/`delete_user`/`buzz_in`, and audit every call. Give
non-admin users no access to the Phoenix dashboards/entities. Rotate all PINs.

---

## 4. HIGH - `phoenix.valid_pin` is an unsigned bus event; a token can forge a disarm with no PIN

**Attack (one sentence):** with any HA token (the admin token in #2, or any
integration that can write the bus), `POST /api/events/phoenix.valid_pin` with
`{"name":"Eliyahu"}` makes the disarm automation run - no valid PIN, keypad or
RFID is involved.

**Proof.**
- `phoenix_security.yaml:84-100` triggers on `event_type: phoenix.valid_pin`
  with **no `event_data` condition** and no check that the event came from the
  access manager. It turns off `phoenix_intrusion_active` and calls
  `script.phoenix_intrusion_reset` (Mac `/alarm/off`).
- The only intended emitter is
  `phoenix_access_manager/__init__.py:88`, which fires after a PIN match. But
  the HA event bus is writable through the REST API
  (`POST /api/events/<event_type>`) and through any automation/script. The
  event payload (`name`, `pin_name`, `locks`) is data, not a proof.
- The same event also drives the presence-context automations
  (`presence_architecture.yaml:153-257`), so a forged event can set
  `phoenix_presence_context_*` and help a subsequent occupancy claim.

**What it buys.** A one-request disarm that leaves the log looking like a
normal "valid PIN" entry unless someone reads the context/user_id. It can be
fired while the siren is already running, and it calls the reset path.

**Cheapest mitigation.** Do not use a raw bus event as a security signal. Have
the access manager call a script/service directly with a per-install HMAC or a
random `source` secret that the automation verifies; add a condition that
`trigger.event.context.user_id` is the access manager's service context (or
`origin == LOCAL`); log the firing context and alert on any `phoenix.valid_pin`
not immediately preceded by a `validate_pin` service call.

---

## 5. HIGH - GPS alone credits a worker as present on every HA start; a phone left at home silently disarms

**Attack (one sentence):** leave a worker's phone (or any phone feeding
`person.montrose` / `device_tracker.monty`) at the office, or let its GPS drift
to "home"; on the next HA start the automation turns on
`input_boolean.phoenix_worker_is_here` with no room-occupancy check, so
`binary_sensor.phoenix_everyone_away` is false and the alarm can never arm.

**Proof.**
- `access_control.yaml:1129-1148` - `phoenix_worker_auto_arrival` triggers on
  `person.montrose -> home` **and on `homeassistant start`**, condition is only
  `person.montrose` or `person.bachrach` is home, action is
  `input_boolean.turn_on phoenix_worker_is_here`. There is no
  `zone_control_room_occupied` check, unlike the passive-arrival automations.
- Live, at 14:15 on 2026-10-26: `person.montrose = home` and
  `input_boolean.phoenix_worker_is_here = on` at **14:15:11**, 36 s before
  `binary_sensor.phoenix_everyone_away` resolved to **off** at 14:15:47 -
  i.e. the HA restart immediately disarmed the house. `device_tracker.monty =
  home`, `source=device_tracker.monty`, GPS accuracy 16 m.
- `phoenix_security.yaml:10-15` is the master condition:
  `user_is_here off AND worker_is_here off AND house_guest_mode active off`.
  Only those booleans matter; the room sensor is not consulted.
- The same pattern exists for guest mode: any guest/parent/Yitz/Yocheved PIN
  turns `phoenix_house_guest_mode_active` on (`access_control.yaml:224-225,
  294-295, 486-487, 530-531`), which disables the alarm for the whole visit.

**What it buys.** The alarm is silently "off" without anyone touching it. If
the phone is genuinely at home and the worker is not, the system cannot tell
the difference. If the phone is left on the premises deliberately, it is a
free, persistent disarm. The owner sees "Workers Are Here" and may believe it.

**Cheapest mitigation.** Require room occupancy (or a PIN/RFID) within a short
window before crediting GPS presence; expire GPS-only presence after N
minutes and alert when presence is GPS-only while the alarm is disarmed; do
not run the start-up credit until the tracker has a fresh fix and the room
sensor has reported; make the guest flag a perimeter-only bypass, not a full
alarm bypass.

---

## 6. HIGH - `everyone_away` fails open on `unknown`/`unavailable`, and a restart resets the intrusion flag

**Attack (one sentence):** make any of the three presence helpers
`unknown`/`unavailable` - most simply by restarting HA or deleting/reloading a
helper - and `binary_sensor.phoenix_everyone_away` evaluates to `off` (because
Jinja `is_state(..., 'off')` is false for any other state), which both prevents
arming and triggers the disarm automation on the transition; a restart during
an alarm also resets `input_boolean.phoenix_intrusion_active` to `false`.

**Proof.**
- `phoenix_security.yaml:10-15` uses `is_state('input_boolean...', 'off')` for
  all three. `unknown`/`unavailable` therefore makes the whole expression
  false => the template binary_sensor is `off` => "everyone is away" is
  false => "someone is here".
- `phoenix_security.yaml:84-100` triggers the disarm on
  `binary_sensor.phoenix_everyone_away` `to: "off"`. So a boolean becoming
  unavailable is a disarm event.
- `phoenix_helpers.yaml:99-102` - `phoenix_intrusion_active` has
  `initial: false`; it does not restore. An HA restart during an alarm sets it
  false.
- The 14:15 restart is the measured example: after it,
  `binary_sensor.phoenix_everyone_away = off` and the ledger records the same
  (`docs/security-audit-2026-10-26.md:83`).
- `grep phoenix_intrusion_reset` finds only the disarm automation
  (`phoenix_security.yaml:96`) and the dashboard; there is no
  `homeassistant start` reconciliation, so a restart does not call the Mac
  `/alarm/off` either (see #12).

**What it buys.** A crash, a reload, a helper deletion or a Zigbee/HA glitch
turns the alarm off, or keeps it from arming, without an attacker. If the
restart happens during an alarm, the siren can outlive the flag (#12). This is
the "single point failure that is not an attack but has the same effect"
category the brief asks for.

**Cheapest mitigation.** Use explicit state tests that fail closed for
arming: `is_state(x,'off') or is_state(x,'unknown') or
is_state(x,'unavailable')` should be treated as **away** for the purpose of
arming, with an alert that a presence helper is unavailable; give
`phoenix_intrusion_active` `initial: true` or restore it, and call
`script.phoenix_intrusion_reset` on `homeassistant start` (idempotent); page
on any presence helper leaving `on`/`off`.

---

## 7. HIGH - Any dashboard user can one-tap the alarm off; the helper guard protects only one of the four booleans

**Attack (one sentence):** a guest/worker with an HA login opens the
`require_admin: false` Phoenix dashboard and toggles
`input_boolean.phoenix_worker_is_here` or
`phoenix_house_guest_mode_active` (neither is protected), or presses
`script.phoenix_intrusion_reset` on the Snapshots dashboard, which calls the
Mac `/alarm/off` directly; toggling `input_boolean.phoenix_intrusion_active`
off stops the strobe loop but leaves the Mac siren running.

**Proof.**
- `access_control.yaml:1269-1370` is the "Block Unauthorized Helper Changes"
  guard. Its trigger list includes `input_boolean.phoenix_user_is_here`
  (`:1281`) but **not** `phoenix_worker_is_here`, **not**
  `phoenix_house_guest_mode_active`, **not** `phoenix_intrusion_active`, **not**
  `phoenix_intrusion_test_mode`, **not** `phoenix_boss_in_control_room_ble`.
  So those can be changed by any caller; the guard never sees them.
- Even for `user_is_here`, the guard's `is_authorized` (`:1319-1326`) returns
  `true` when `context.user_id` is empty - i.e. any automation/script/webhook
  change is allowed. The revert logic only catches a user-context edit by a
  non-owner.
- `lovelace/phoenix.yaml:55-59` exposes `phoenix_user_is_here`,
  `phoenix_worker_is_here` and `phoenix_house_guest_mode_active` as toggles.
- `lovelace/snapshots_admin.yaml:449-461` exposes
  `input_boolean.phoenix_intrusion_active`, `phoenix_intrusion_test_mode` and
  `script.phoenix_intrusion_reset`; the script is the direct Mac-off path.
- `configuration.yaml:228-263` sets `require_admin: false` on all five YAML
  dashboards.
- `input_text.phoenix_admin_pin` is also on the dashboard (masked in the UI,
  cleartext in the API, #3).

**What it buys.** One tap disarms, or one tap silences the siren, from a
non-owner account. It is the same effect as #1 but requires only a login, not
network access to the Mac. It also makes the alarm's state ambiguous: a
worker can turn "Workers Are Here" on to stop it arming and nobody can tell
whether that was a real arrival.

**Cheapest mitigation.** Add all security booleans to the guard; require an
owner/admin HA user for those entities and for `script.phoenix_intrusion_reset`
(use an admin-only dashboard or a custom card that checks the user); remove the
intrusion/test/reset controls from `snapshots-admin`; make the "Intrusion
Active" toggle call the reset script instead of just flipping the flag; log
every change with the user.

---

## 8. MEDIUM-HIGH - The "someone is inside with no presence" cross-check is disabled by design, and the temp PIN no longer rotates

**Attack (one sentence):** if presence is stale (#5/#6), an intruder can move
through the control room without the one automation designed to notice
"occupied room, nobody marked here", because it is `initial_state: false` and
has been off since 11 August; and the 4-digit all-doors house PIN no longer
rotates, because its rotation automation is off despite having run on 21
October.

**Proof.**
- `access_control.yaml:1183-1217` - `phoenix_unknown_presence_alert` has
  `initial_state: false` (`:1186`) in the repo. Live
  `automation.phoenix_v2_unknown_presence_alert_2 = off`,
  `last_triggered = 2026-08-11 00:17`.
- `access_control.yaml:1371-1392` - `house_access_pin_auto_reset` rotates
  `input_text.phoenix_house_access_pin` to `range(1000,10000)|random` every
  14th day-of-year and SMSes the owner. Live state is **`off`**,
  `last_triggered = 2026-10-21 03:15` (day 294 is a 14-day boundary). The next
  boundary (day 308, 2026-11-04) will not run, so the current 4-digit
  all-doors PIN is permanent until someone notices.
- The PIN is only 4 digits (`range(1000,10000)`), and the keypad has no
  per-code rate limit beyond the shared invalid-PIN counter/lockout; a
  4-digit space is 9,000.

**What it buys.** The second detection layer is gone, so a stale-presence
intruder is invisible to HA's own cross-check. The permanent 4-digit PIN is a
standing credential for every door; anyone who ever had it (cleaner, guest,
former worker) keeps it.

**Cheapest mitigation.** Turn both automations on and add a startup assertion
that they are `on` (a template binary_sensor that alerts if any security
automation is off/unavailable). Do not use a 4-digit PIN for all doors; use
6-8 digits or per-person codes, and rotate on a schedule that is independent
of a manually-disabled automation.

---

## 9. MEDIUM - A cloned iBeacon can latch "Boss is here" and disarm

**Attack (one sentence):** the boss BLE beacon (`bcpro_207463`) is treated as
proof of presence; an attacker who captures its iBeacon advertisement from
outside can replay it with a cheap ESP32 near the control-room hub, turning on
`input_boolean.phoenix_boss_in_control_room_ble` and then
`phoenix_user_is_here`, which disarms the alarm and keeps it from arming.

**Proof.**
- `phoenix_beacon_presence.yaml:213-249` - the enter automation triggers when
  the beacon is within 14-16 ft of the control-room hub for 8 s, then turns on
  `phoenix_boss_in_control_room_ble` and `phoenix_user_is_here`.
- `phoenix_beacon_presence.yaml:251-274` keeps `user_is_here` synced on while
  the BLE latch is on; `:276-299` only clears it after 2 minutes of the leave
  condition.
- `presence_architecture.yaml:69-84` uses the same boolean in
  `zone_control_room_occupied` (source: BLE Beacon).
- `phoenix_security.yaml:10-15` uses `phoenix_user_is_here` as one of the
  three master conditions.
- iBeacon advertisements are static and unauthenticated by design; a clone
  does not need the owner's phone, only the UUID/major/minor (and, for
  Bermuda, the MAC can be spoofed on the ESP32). This is a design property,
  not a measured packet capture; I did not capture the beacon.

**What it buys.** A persistent "someone is home" with no phone and no PIN,
from outside the house, for as long as the clone is powered near the hub. It
also disarms a live alarm.

**Cheapest mitigation.** Treat BLE as a hint only (the `presence_beacon.yaml`
"confirm required" pattern is the right one): require room occupancy or a
PIN/RFID before setting `user_is_here`; use a beacon with rotating
resolvable private addresses / IRK; alert when the beacon is present but the
owner's phone is not; put the hub's BLE scanner where a street-level replay
cannot reach.

---

## 10. MEDIUM - Zigbee jamming or a coordinator reboot blinds the door sensors, with no offline alert

**Attack (one sentence):** jam 2.4 GHz or reboot the Zigbee coordinator; the
door contacts go `unavailable`, the template `binary_sensor.phoenix_*_contact`
becomes `unavailable` (not `on`), `zone_hallway_active` stays false, no
trigger fires, and nothing pages - so the intruder opens the door in the blind
spot.

**Proof.**
- `configuration.yaml:366-388` - the three door templates have
  `availability` set to "source not in unknown/unavailable", so a dropped
  sensor yields `unavailable`, never `on`.
- `presence_architecture.yaml:35-48` - `zone_hallway_active` ORs
  `is_state(door,'on')`; an unavailable sensor contributes false.
- `phoenix_security.yaml:20-35` - the trigger list only fires on `to: "on"`;
  an unavailable sensor cannot produce that transition.
- The only offline alerts are for the presence hub
  (`config/automations/control_room_hub_health_monitoring.yaml:46-74`) and the
  security hub (`system_health_monitoring.yaml:51+`); grep found no alert on
  any door contact going unavailable.
- `phoenix_unknown_presence_alert` is off (#8), so the cross-check that might
  notice an occupied room is also gone.

**What it buys.** The alarm is blind while the radio is jammed or the
coordinator is down, with no indication. A 2.4 GHz jammer is cheap and also
takes out Wi-Fi/BLE, which may take out the keypad and the beacon at the same
time. The system has no heartbeat on the sensors it depends on.

**Cheapest mitigation.** Alert on any door contact `unavailable` for > 2 min
(and on the coordinator's own availability); add a supervised/heartbeat
sensor; keep a second detection path (camera person detection) and trigger on
"door open with sensor offline"; battery/health alerts for every sensor.

---

## 11. MEDIUM - The physical control-room button triple-click disarms without a PIN

**Attack (one sentence):** anyone already inside - a guest, a worker, or an
intruder who got in while the alarm was disarmed - triple-clicks the
control-room button, which toggles `input_boolean.phoenix_user_is_here` and
therefore disarms and calls the Mac `/alarm/off`.

**Proof.**
- `access_control.yaml:1018-1067` - `phoenix_manual_button_handler` maps
  `esphome.control_room_button_toggle_boss` (3 taps) to
  `input_boolean.toggle phoenix_user_is_here`; 2 taps toggles workers; 1 tap
  buzzes the control-room door; long press buzzes the outside door.
- `phoenix_security.yaml:84-100` - `everyone_away` going off runs the disarm
  and `script.phoenix_intrusion_reset`, which calls
  `rest_command.phoenix_alarm_mac_off`.
- No PIN, no confirmation, no user context is required for the button event.

**What it buys.** A silent, physical disarm after entry, and a door-buzz
button for the control room. It is a deliberate convenience feature, but it
is also an unauthenticated "off" switch inside the protected area.

**Cheapest mitigation.** Require the owner PIN (or a long press + PIN) for the
boss toggle; make the button emit a "request" that needs a second factor;
log the event with the ESPHome device and the resulting boolean change; keep
the button out of reach from the entry path.

---

## 12. MEDIUM - A restart or a manual toggle during an alarm leaves the Mac siren running forever

**Attack (one sentence):** restart HA while the siren is sounding (or flip the
visible "Intrusion Active" toggle instead of running Reset); the script loop
dies, `phoenix_intrusion_active` resets to `false`, and the Mac keeps looping
`afplay` because nothing calls `/alarm/off` on start or on that transition.

**Proof.**
- `phoenix_security.yaml:215-248` - the flash/audio loop's `while` condition
  is `input_boolean.phoenix_intrusion_active == on`; the loop is a script
  running in HA, so an HA restart kills it.
- `phoenix_helpers.yaml:99-102` - `phoenix_intrusion_active` is
  `initial: false`; after a restart it is off.
- `phoenix_security.yaml:249-258` - `phoenix_intrusion_reset` is the only
  thing that calls `rest_command.phoenix_alarm_mac_off`; it is called by the
  disarm automation (`:96`) and exposed on a dashboard, but **not** on
  `homeassistant start`.
- The ledger's S3/S4 already measured the same class: the siren outlived the
  disarm at 14:03 on 2026-10-26, and the loop hit HA's 10,000-iteration cap at
  02:14. The new `intrusion_active` re-check before the siren fixes the first
  half; it does not fix the restart/manual-toggle half.
- `lovelace/snapshots_admin.yaml:449-461` exposes the raw
  `input_boolean.phoenix_intrusion_active` toggle next to the Reset script, so
  the unsafe action is one tap away from the safe one.

**What it buys.** A siren that cannot be stopped from HA, or that stops the
strobe but not the audio, plus alarm fatigue and neighbours' complaints. It
also makes the log look "reset" while the speakers are still screaming.

**Cheapest mitigation.** On `homeassistant start`, always POST
`/alarm/off` (idempotent) and reconcile; make the loop's exit path call
`/alarm/off`; make the dashboard toggle call the reset script (or make it
read-only); add a Mac-side watchdog that stops the siren after N minutes
without a heartbeat from HA.

---

## 13. LOW-MEDIUM - Cloudflare protects HA, but `trusted_proxies` and the static webhook key widen the trust boundary

**Attack (one sentence):** HA itself is behind Cloudflare Access (good), but
`use_x_forwarded_for: true` with every Cloudflare range **plus** Docker
`172.30.32.0/23`/`172.30.33.0/24` in `trusted_proxies` lets any container in
those ranges spoof its source IP and defeat `ip_ban` attribution; and the
HA->secretary webhook is authenticated by a static `x-ps-api-key` with no
timestamp/nonce, so a leaked key lets an attacker send fake "intrusion" pages
and MMS.

**Proof.**
- `curl -I https://ha.abletelsolutions.com/` returns **302** to
  `https://dawn-cell-26a7.cloudflareaccess.com/...` - the public HA host is
  not directly reachable without a CF identity. Good.
- `configuration.yaml:14-45` - `use_x_forwarded_for: true`,
  `ip_ban_enabled: true`, `login_attempts_threshold: 5`, and a
  `trusted_proxies` list that includes all Cloudflare ranges and the Docker
  networks. Any add-on/container on those Docker networks can set
  `X-Forwarded-For` to anything; the `ip_ban` then bans the spoofed address
  and the log records it.
- `secretary.yaml:284-292` and `phoenix_intrusion_evidence.yaml` POST to
  `https://ai.abletelsolutions.com/webhook/ha/security-alert` with a static
  `x-ps-api-key`. `app/main.py:452-479` `_authenticate_webhook` compares the
  key with `hmac.compare_digest` but there is no timestamp, nonce or body
  signature; a replay is accepted forever.
- `ai.abletelsolutions.com/` is 307 to `/api/auth/signin` (good), but
  `/webhook/*` is explicitly public in the middleware (`main.py:378-404`).
- The secretary's `/ha/call_service` can call **any** HA service with the
  admin token; it is approval-gated by default (verified:
  `UNSAFE_ACTIONS_ENABLED=false`, `HA_CALL_SERVICE_REQUIRES_APPROVAL=true`),
  but the approval queue and the `DASHBOARD_API_KEY` live in the same `.env`
  as `HA_TOKEN`. I did not find an unauthenticated public path to that
  endpoint; the risk is key compromise, not a bypass I measured.

**What it buys.** Spoofed source addresses in HA's ban list/logs; a leaked
webhook key buys false intrusion pages (alarm fatigue, spoofed evidence), not
a disarm. A leaked dashboard key could approve the agent's HA service call,
which is full control.

**Cheapest mitigation.** Replace the broad `trusted_proxies` list with the
actual Cloudflare Tunnel egress only (or terminate the tunnel on a local
proxy and trust only that proxy); add an HMAC timestamp + nonce to the
HA->secretary webhook; use separate keys per webhook and rotate them; require
owner approval out-of-band for `ha_call_service` (not just a DB task the same
dashboard can approve).

---

## 14. LOW - Orphan automations make a disabled security automation look like noise

**Attack (one sentence):** about 50 automation entities are `unavailable`
(removed/renamed YAML, stale registry), so an operator scanning the list cannot
tell a real automation that has been turned off (`house_access_pin_auto_reset`,
`phoenix_v2_unknown_presence_alert_2`) from dead registry entries - which is
how a security automation stays off unnoticed.

**Proof.**
- Live `/api/states` filtered to `automation.*` shows dozens of
  `unavailable` entities (`automation.access_control_keypad_event_handler`,
  `automation.presence_automatic_worker_arrival`,
  `automation.phoenix_v2_control_room_button_handler_2`, ...), alongside
  `off` entities that are real (`automation.presence_smart_toggle_exclusivity`,
  `automation.house_access_pin_auto_reset`,
  `automation.phoenix_v2_unknown_presence_alert_2`,
  `automation.phoenix_keypad_event_handler`).
- `house_access_pin_auto_reset` still shows `last_triggered = 2026-10-21`, so
  it worked and was then disabled; `phoenix_v2_unknown_presence_alert_2` last
  triggered 2026-08-11.
- The repo YAML also has an explicit `initial_state: false` on
  `phoenix_unknown_presence_alert` (`access_control.yaml:1186`), so this is
  not only a UI accident.

**What it buys.** A slow, silent loss of a security layer; the next person to
read the automation list cannot tell what is real. This is the "masked
automation" failure in the brief.

**Cheapest mitigation.** Clean the entity registry of removed automations;
add a template binary_sensor "Security automations healthy" that alerts if any
of a named allowlist is not `on`; alert on `last_triggered` being older than
its expected cadence; keep a short, explicit list of security automations in
one dashboard.

---

## What holds (worth keeping)

- HA's public host is behind Cloudflare Access (302 to
  `dawn-cell-26a7.cloudflareaccess.com`), and the secretary UI root redirects
  to NextAuth sign-in (307).
- HA auth is on; `ip_ban_enabled: true`, `login_attempts_threshold: 5`.
- The ESPHome API is encrypted (`config/esphome/phoenix-presence-hub.yaml:59`
  and the other devices), so a passive LAN sniffer does not get the keypad
  PINs in the clear.
- The 6 s arrival grace and the post-evidence `intrusion_active` re-check
  (`phoenix_security.yaml:180-182`) are real fixes; the test-mode flag is now
  consumed (`:119-120`), and evidence capture runs before the siren.
- `phoenix_access_manager` masks PINs in its sensor attributes (but not in
  `input_text` state, #3).

## What I could not verify

1. **Guest Wi-Fi -> Mac `:8128`.** I did not have a guest SSID/VLAN or client
   isolation data. Office LAN and tailnet are proven; guest is unknown.
2. **Tailscale ACLs.** I proved reachability from one tailnet node
   (`zabz-tech-linux`); I did not read the tailnet policy. Default
   same-user ACL would allow all ~12 devices.
3. **The cloud secretary (`secratary-cloud`, 100.73.176.126).** SSH was
   `Permission denied (publickey)`; I could not check whether its `.env`
   holds a third admin token. It is the public-facing instance, so this is
   the most important unverified copy.
4. **Whether a non-admin HA user can call services.** I verified the code has
   no check and that `person.montrose` is linked to a user; I did not create a
   non-admin token or call a state-changing service (non-destructive rule).
   HA's core permission model for service calls is the only remaining gate.
5. **Whether `POST /api/events` is allowed for non-admin tokens.** I verified
   the admin token can read/write the API surface and that the event is
   unsigned; I did not fire a test event.
6. **BLE clone feasibility.** I did not capture the beacon's advertisement,
   UUID/major/minor or IRK; the "iBeacon is static" claim is a design fact,
   not a measurement of this specific beacon.
7. **Whether `worker_is_here = on` at 14:15 was legitimate.** Montrose may
   genuinely have been on site. The finding is the *mechanism* (GPS alone,
   on HA start), not the current occupancy.
8. **End-to-end siren test.** I did not POST `/alarm/on` (forbidden); the
   Mac `/health` says `alarming: false`, and the code path is read, not run.
9. **Camera read and door unlock via the token.** I did not exercise them;
   the capability is inferred from admin scope and the service list.
10. **The secretary's approval path and `DASHBOARD_API_KEY` exposure.** I read
    the gate (`_ha_requires_approval`, `UNSAFE_ACTIONS_ENABLED=false`,
    `HA_CALL_SERVICE_REQUIRES_APPROVAL=true`) but did not test the approval
    UI or whether the key is in the Next.js bundle.
11. **Whether the Mac listener is reachable from the HA container's network
   namespace** (it is on the LAN, and HA calls it, so yes by design; I did not
   exec into the HA container).
```