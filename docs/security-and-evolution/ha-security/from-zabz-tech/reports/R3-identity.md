# R3 — Identity: who can prove they may be inside, and what is recorded

**LOCAL (zabz-tech)** — all reads performed on this machine; no edits, no state changes, no restarts, no outbound sends.

## What I read

| Source | Revision / time |
|---|---|
| `ha-config` | `git log -1 --format=%h` → **ae8b622** |
| `personal-secretary-mvp` | `git log -1 --format=%h` → **121e13ee** |
| Session time | 2026-10-26 14:42–14:53 EDT (host clock) |
| Live Home Assistant | `GET /api/config` → `version=2025.10.3`, `time_zone=America/New_York` |

Two file names in the brief do not exist, so I read the real ones:

- `config/packages/phoenix_access_control.yaml` — **does not exist**. The only file by that name is `config/packages/phoenix_access_control_tuning.yaml` (116 lines: hold times, lockout thresholds, `input_boolean.phoenix_access_control_enabled` / `_lockdown` / `_debug`, two `timer:`s). The access-control *logic* is not in a package at all — it is `config/automations/access_control.yaml` (2,405 lines).
- `config/packages/phoenix_door_locks.yaml` — exists and is **empty**: its entire content is `# This file is intentionally emptied to overwrite a corrupted/obsolete remote version.` All lock behaviour lives in `config/scripts.yaml` and `config/packages/phoenix_core.yaml`.
- `custom_components/phoenix_access_manager/` has no `__init__.py`-adjacent logic beyond `__init__.py` (210 lines) + `sensor.py`; there is no `entity.py`, no `switch.py`. It is a service-only integration.
- `secret*` — the tree contains **only** `config/secrets.yaml.example` (3,265 B, 2026-09-14) and `config/esphome/secrets.yaml.example` (974 B). `config/secrets.yaml` is gitignored (`.gitignore`: `config/secrets.yaml`, `config/**/secrets.yaml`). No secret file is committed; one example file leaks real values (see §4.3).

Method: repo files read in full or at the stated offsets; live facts read with `GET /api/states`, `/api/states/<entity>`, `/api/services`, `/api/logbook/<ts>`, `/api/history/period/...` through `_ha-cred-20261018\ha.ps1`. Credential values were never printed — only their **lengths** and, where useful, boolean comparisons computed inside PowerShell.

---

## 1. Every credential path that exists

| # | Path | What it proves | Where the secret lives | Who can mint / change | Logged with a name? |
|---|---|---|---|---|---|
| 1 | **Keypad PIN** on 3 physical readers across 2 ESP32 hubs | Knowledge of a code. Nothing about *who* typed it beyond which code it was. | `input_text.phoenix_*_pin` — a helper entity, **plaintext state**, readable via `GET /api/states` by any token, and written into the recorder DB | Owner, via the `phoenix-admin` dashboard (`lovelace/phoenix.yaml:91-125`) or `input_text.set_value`; non-owner writes are reverted by `automation.phoenix_block_unauthorized_helper_changes` (state `on`) | **Yes** for admin/parent/yocheved/house-access; **no** for invalid, drop-off and business |
| 2 | **Per-user PIN** (`phoenix_access_manager` store) | Would prove "this named user, these named relays" | HA `.storage/phoenix_access_manager_data` — plaintext JSON, `Store(...)` with no encryption (`__init__.py:48`); never in git | `script.phoenix_add_user_from_helpers` → `phoenix_access_manager.add_user`; the script hard-requires `context.user_id == lovelace_boss_user_id` (`scripts.yaml:742-754`) | Would log `Valid PIN entered for {name}.` — **but the path is inert today** (below) |
| 3 | **RFID tag** | Possession of a card/fob | `input_text.phoenix_rfid_*_tag` (plaintext state, same exposure as PINs) | Owner dashboard (`lovelace/phoenix.yaml:143-151`) or the capture→assign flow (`automation.phoenix_rfid_capture_next_tag` + `input_button.phoenix_rfid_assign_last_tag`, both `on`) | **Yes** — but only 3 of 6 roles can ever resolve (below) |
| 4 | **Phone / `device_tracker`** | That a handset is in a zone. Not that the person is. | No secret in HA; pairing lives on the phone | Whoever installs the app / pairs the beacon | `Presence` logbook: "Passive arrival: User Bluetooth detected + Control room occupied." No credential name, no door |
| 5 | **BLE beacon** (iBeacon + Bermuda distance triangulation) | A beacon is within N feet. A borrowed beacon is indistinguishable from the owner. | `input_boolean.phoenix_boss_in_control_room_ble` + `input_number.phoenix_boss_*_ft` tunables | Anyone who can place/swipe the beacon; `phoenix_beacon_presence.yaml` is YAML-owned | `Presence` logbook on enter/leave; sets `phoenix_user_is_here` **on** (`phoenix_beacon_presence.yaml:239-249`) |
| 6 | **Dashboard button** (`script.buzz_in_strike`, `buzz_in_maglock`, `buzz_in_interior_maglock`, `buzz_in_apartment_door`) | That an **authenticated HA user** pressed it (or that an automation did) | HA user session | Every HA account that can see the dashboard — `phoenix-admin` is declared `require_admin: false` (`configuration.yaml:229-235`) | Partly: writes "Manual buzz-in at Outside Door (**Unknown user**)" — `input_text.ha_user_id_worker_klein/montrose/bachrach` all read `unknown`, so the label never resolves (`scripts.yaml:919-931`) |
| 7 | **Physical key** | Nothing the system can see | Metal | Owner / locksmith | **No.** Nothing in HA observes a key turn |
| 8 | **Shared/temporary codes** (house access, customer/business, drop-off, generic worker) | Group membership, not identity | Same `input_text` helpers | Owner; house-access also allowed to `lovelace_parent_1_user_id` (`access_control.yaml:1313-1326`) | Logged with a **label, not a person**: "HOUSE ACCESS (TEMP/ALL DOORS)", "Business Access", "Drop-off Access", "Worker Access" |

### 1.1 The per-user PIN path is registered but switched off

`GET /api/services` → `phoenix_access_manager` domain **is** registered with `validate_pin, add_user, delete_user, modify_user, buzz_in`. But:

- `GET /api/states/sensor.phoenix_access_manager_users` → **404**, and no entity in 1,036 states matches `access_manager` — the user-list sensor the integration is supposed to publish does not exist, so **the roster inside the store cannot be read from HA at all**.
- The only caller of `validate_pin` is `automation.phoenix_keypad_event_handler` (`config/packages/phoenix_core.yaml:37-48`) and `GET /api/states/automation.phoenix_keypad_event_handler` → **`state=off`** (`last_changed=2026-10-26T14:15:23`). Its YAML sets `initial_state: false`.
- Consequence: `phoenix.valid_pin` never fires, so `automation.phoenix_extreme_intrusion_disarm` (`phoenix_security.yaml:82-96`) can never be triggered by a PIN — only by `binary_sensor.phoenix_everyone_away` going off.

### 1.2 The RFID role map cannot resolve two of the three worker tags

`access_control.yaml:52-66` builds `rfid_role` from **three** tags only — `owner`, `worker_bachrach`, `wife` — and everything else is `unknown`:

```
{% elif t != '' and t == o %}owner
{% elif t != '' and t == b %}worker_bachrach
{% elif t != '' and t == f %}wife
{% else %}unknown
```

`input_text.phoenix_rfid_worker_klein_tag` and `..._montrose_tag` exist and are assignable (`access_control.yaml:778-791`), but no branch compares them. So a Klein or Montrose tag is evaluated as `unknown`, falls to *Scenario 9*, logs "Unknown RFID tag", increments `counter.phoenix_invalid_pin_attempts`, and can contribute to a lockout. The two branches that grant Klein entry by tag (`access_control.yaml:320-332` and `378-388`, both testing `rfid_role == 'worker_klein'`) are **unreachable**.

### 1.3 A PIN is written to the log in cleartext on a failed attempt — in code

`custom_components/phoenix_access_manager/__init__.py:118`:

```python
_LOGGER.warning(f"Invalid PIN entered: {pin}")
```

That is a full wrong PIN in `home-assistant.log` (and in the HA system log buffer / `system_log` ring). It is latent today only because nothing calls `validate_pin` (§1.1). Turning that automation on without fixing line 118 makes every fat-fingered PIN — which is usually a *near miss of the real PIN* — a persisted string.

---

## 2. The identity roster as the system knows it

There is **no roster table**. The roster is the set of helper entities; the person's name lives in the entity's `name:` field and the value is the credential. Two things are code, not data: the RFID role map (§1.2) and the unlock decisions.

Live values, measured `GET /api/states` at 14:45 EDT 2026-10-26. Lengths only, digits-only flag as a type indicator:

| Entity | `name:` | state length | digits only |
|---|---|---|---|
| `input_text.phoenix_admin_pin` | Admin PIN | **4** | yes |
| `input_text.phoenix_parent_pin` | Parent PIN | **4** | yes |
| `input_text.phoenix_yocheved_pin` | Yocheved PIN | **4** | yes |
| `input_text.phoenix_house_access_pin` | Temporary House Access PIN | **4** | yes |
| `input_text.phoenix_family_pin` | Regular Family PIN | 0 (empty) | – |
| `input_text.phoenix_guest_pin` | Guest PIN | 0 | – |
| `input_text.phoenix_tenant_pin` | Tenant PIN | 0 | – |
| `input_text.phoenix_worker_pin` | Generic Worker PIN | 0 | – |
| `input_text.phoenix_drop_off_pin` | Daily Drop-off PIN | 0 | – |
| `input_text.phoenix_customer_pin` | Business Access PIN | 0 | – |
| `input_text.phoenix_worker_klein_pin` | Worker Klein PIN | 0 | – |
| `input_text.phoenix_worker_montrose_pin` | Worker Montrose PIN | 0 | – |
| `input_text.phoenix_worker_bachrach_pin` | Worker Bachrach PIN | 0 | – |
| `input_text.phoenix_yitz_pin` | Yitz (Brother) PIN | 0 | – |
| `input_text.phoenix_rfid_owner_tag` | RFID Tag (Owner) | **7** | yes |
| `input_text.phoenix_rfid_wife_tag` | RFID Tag (Wife) | **7** | yes |
| `input_text.phoenix_rfid_worker_klein_tag` | RFID Tag (Worker Klein) | 0 | – |
| `input_text.phoenix_rfid_worker_montrose_tag` | RFID Tag (Worker Montrose) | 0 | – |
| `input_text.phoenix_rfid_worker_bachrach_tag` | RFID Tag (Worker Bachrach) | 0 | – |
| `input_text.phoenix_rfid_tenant_tag` | RFID Tag (Tenant) | 0 | – |
| `input_text.phoenix_rfid_last_tag_uid` | RFID Last Captured Tag UID | 0 | – |

Four orphaned helpers exist with state literally `unavailable` (registry rows whose YAML is gone — verified by string comparison, not by length): `input_text.phoenix_new_user_pin`, `input_text.phoenix_parent_1_pin`, `input_text.phoenix_parent_2_pin`, `input_text.phoenix_full_family_pin`.

**Names the system knows**, in three separate namespaces that are not joined:

- **PIN/RFID roles** (above): Owner, Parent (generic, and a `lovelace_parent_1_user_id` secret), Yocheved, Yitz, Worker Klein, Worker Montrose, Worker Bachrach, generic Worker, Tenant, Guest, Daily Drop-off, Business/customer, House access.
- **HA `person` entities:** `person.eliyahu_zabrowsky` (`not_home`, source `device_tracker.00_08_22_c8_b2_fb`, also tracking `device_tracker.iphone_15_2`), `person.montrose` (`home`), `person.klein` (`unknown`).
- **HA users:** referenced only as secrets — `lovelace_boss_user_id`, `lovelace_parent_1_user_id`, `lovelace_worker_montrose_user_id`. The three `input_text.ha_user_id_worker_*` that would map user→name are all `unknown`.

The three namespaces never cross-reference: `person.klein` is `unknown` while Klein's PIN and tag are empty and his tag role is unreachable. The **only** place a credential is bound to a human is the string in each `name:` field, and the **only** place a tag is bound to a role is the Jinja block at `access_control.yaml:52-66`.

### 2.1 A committed example file contains real-format tag UIDs with names

`config/secrets.yaml.example` — **tracked** (`git ls-files` confirms), last touched in commit `08ec945` (2026-09-07):
lines 12-17 assign six 6–8 digit tag numbers to named holders (owner "Boss tag", "Mattis Klein tag", "Montrose tag", bachrach, family, tenant), three of them annotated `verified 2025-12-28`.

I compared those six against the live helpers without printing either side: **none match**, at any length and after leading-zero normalisation (`rfid_owner_tag` example length 8 vs live length 7; the other five have no live value at all). So the committed numbers are historical, not current — but they are real card numbers with real names attached, in git, and anyone who clones this repo learns which numbers were issued to whom. Card numbers are not secret-key material, but they are the lookup key a cloning attack needs.

---

## 3. What the system records when someone enters

### 3.1 The trigger

Two custom events, fired **by the ESP32**, not by HA (`security-hub.yaml:165-171` and `185-191`; `interior-door-hub-wifi.yaml:93-100` and `110-117`):

```
event: esphome.access_control_keypad_entry   data: {door_name, code}           (+ side: A|B on the interior hub)
event: esphome.access_control_rfid_entry     data: {door_name, tag_uid}        (+ side: A|B on the interior hub)
```

`door_name` is one of `strike` (outside door), `maglock` (control-room exterior), `interior`. `code` is the digits collected up to `#` with a 10 s timeout (`key_collector`, `allowed_keys: "0123456789"`). `automation.phoenix_access_control_master_unified` triggers on the event type **only** — `access_control.yaml:15-19` has no device, node or source filter.

### 3.2 What is written

| Sink | Exact content | Survival |
|---|---|---|
| `input_text.phoenix_access_control_log` | one line prepended, `"%b %d, %-I:%M %p - <Who> Access at <Door>\n" + previous`, then **`[:255]`** (`access_control.yaml:160-164`; the literal `[:255]` appears on **13** lines of that file, measured with `Select-String -Pattern '\[:255\]'`) | **255 characters total.** Not a log — a rolling display. Measured length now: **255**, six lines, oldest clipped mid-phrase |
| `logbook.log`, `name: Access Control`, `entity_id: input_text.phoenix_access_control_log` | one row per event: `when`, `name`, `message` | recorder `purge_keep_days: 30` (`configuration.yaml:177`) |
| `system_log.write` | warnings for disabled, lockdown/lockout, unknown RFID, failed PIN, restricted-door denials | `home-assistant.log`, rotates |
| `notify.mobile_app_zabz_waze` | Klein denied, lockout engaged, unauthorized helper edit | phone |
| presence booleans | `phoenix_user_is_here` (owner), `phoenix_worker_is_here` (workers), `phoenix_house_guest_mode_active` (yocheved/parent/yitz/house access) | state history, 30 days |
| camera files | `script.snapshot_entry_cameras` / `snapshot_control_room_cameras` → `/media/phoenix/...` | pruned by `shell_command.purge_old_snapshots` (history 25 d / 750 MiB, clips 4 d / 5,600 MiB) |
| deadbolt | `log_message` from the z2m payload → `phoenix_access_control_log` **and** `phoenix_door_activity_log`, user slot → "Boss"/"Worker"/"Guest"/"User N" (`access_control.yaml:2176-2191`) | as above |

Not recorded anywhere: the credential value (masked in debug only, `entered_code_masked`/`rfid_tag_uid_masked`), which *side* of the interior door, which physical reader, the HA user who did it (for credential events), and — on the drop-off and invalid paths — any name at all.

### 3.3 `input_text.phoenix_access_control_log`, as it reads right now

`GET /api/states/input_text.phoenix_access_control_log`, read 2026-10-26 14:47 EDT, `last_changed=2026-10-26T14:15:11`, length **255**:

```
Oct 26, 1:22 PM - Owner Access at Interior
Oct 26, 12:03 PM - Owner Access at Interior
Oct 26, 11:29 AM - Owner Access at Interior
Oct 26, 11:28 AM - Owner Access at Maglock
Oct 25, 12:04 PM - Yocheved Access at Interior
Oct 24, 10:25 PM - Owner Access at
```

The last line is cut mid-phrase by the `[:255]` cap. That is the whole visible history of the shop door: **six entries over three days**, and the seventh is destroyed every time anyone badges in.

### 3.4 The 30-day record has a hole in it

- `GET /api/logbook/2026-10-25T14:44` → **32,095** entries for that 24 h window. `GET /api/logbook/2026-10-22T14:44` → 16,544. `GET /api/logbook/2026-10-24T14:44` → 8,533.
- `GET /api/logbook/2026-10-23T14:44` → **0** entries for the whole 24 h window.
- `GET /api/history/period/2026-10-23T15:00?filter_entity_id=input_boolean.phoenix_worker_is_here` → rows to `2026-10-23 13:02`, then the next row is `2026-10-24 19:44`.

So roughly **30 hours between 2026-10-23 13:02 and 2026-10-24 19:44 have no recorder rows and no logbook entries**. Whatever the cause (host down, recorder failure, purge), the audit trail the alarm would be judged by does not cover that window. Not investigated further here — it is a different workstream's question, but it changes what "30 days of history" means.

Credential events are rare enough that I can quote the whole set from the logbook, filtered on `Access at|DENIED|Invalid credential|Unknown RFID|HOUSE ACCESS|Business Access|Drop-off|UNAUTHORIZED`, 7-day window:

```
10/20/2026 10:34:53 AM | Access Control | Owner access at Maglock
10/20/2026 11:00:51 AM | Access Control | Owner access at Interior
10/20/2026 11:00:51 AM | Access Control | Invalid credential attempt (PIN) at Interior keypad
```

Everything else in the logbook is the Apartment deadbolt republishing `state changed to locked` every ~8 minutes (`automation.deadbolt_pin_sync_and_activity_logger`, 3,777 rows in a 24 h window) and snapshot scripts.

Note the last two rows: **at the same second** the logbook holds both `Owner access at Interior` and `Invalid credential attempt (PIN) at Interior keypad`. One badge-in, one entry, two contradictory verdicts. I did not establish the mechanism — a `choose` in HA runs only the first matching branch, so a single event cannot produce both, which means two event executions shared that second. That is a hypothesis, not a finding; what is measured is that the record at 11:00:51 on 2026-10-20 says both things at once, and that an "invalid attempt" is one of the three inputs to the lockout counter (`script.phoenix_access_control_register_invalid_attempt`).

---

## 4. The gaps

### 4.1 Entry routes with no credential at all

- **Windows.** Zero window contacts exist: of 1,036 entities, the seven matching `window` are all *time* windows (`timer.phoenix_invalid_pin_window`, `input_number.phoenix_invalid_credential_window_minutes`, …). Only three door contacts exist: `phoenix_outside_door_contact`, `phoenix_control_room_exterior_door_contact`, `phoenix_control_room_interior_door_contact`. A window is invisible to this system.
- **Power.** Both maglocks are **fail-safe**: locked = energised (`switch.smart_switch_l2` / `_l4` state `on` = locked, proven by the startup assertion "asserted door relays to locked defaults (strike OFF, maglocks ON)", `access_control.yaml:2213-2234`). Cutting power to the control-room doors unlocks them, with no credential and no event. `personal-secretary-mvp/app/services/home_assistant.py` documents that the interior maglock is on *separate* power precisely so that cutting the Shelly plug does not release it — i.e. someone already thought about this for the HA power-down path, not for an intruder.
- **Physical key.** `lock.0x002446fffd0a4705` (Kwikset) has a keyway. Key use produces no HA event.
- **The deadbolt's own keypad.** Its slots are programmed by MQTT (`script.lock_set_code`, `script.ui_set_kwikset_pin`), and slot→name is hardcoded in the automation as 1=Boss, 2=Worker, 3=Guest, `else` → `User {{ user_id }}` (`access_control.yaml:2179`). Any slot beyond 3 — a tenant, an airbnb guest — logs as "User 4", which is a number, not a person.
- **The shop side of the interior door.** The interior maglock has keypads on both sides which both emit `door_name: "interior"` with only a `side: A|B` field, and `side` is **never read** by any automation. So a person inside the house can open the door to the shop, and the record cannot say from which side.
- **The relay itself.** `script.buzz_in_strike` reaches the door by publishing to MQTT directly (`scripts.yaml:948-951`), bypassing all credential logic — see §5.

### 4.2 Credentials that are shared or unowned

- **`phoenix_house_access_pin`** — one 4-digit code shared with whoever needs it. `house_access_pin_auto_reset` is written to rotate it every 14th day of the year at 03:15 and push the new code to the owner's phone (`access_control.yaml:1371-1392`) — but **that automation is `off`** (`GET /api/states/automation.house_access_pin_auto_reset` → `off`, `last_changed` 2026-10-26T14:15:23). So the code holds a live 4-digit value and does not rotate. Its enable flag is also **off**, so it opens nothing today; the two facts are independent, and turning the flag on would expose a code that never changes.
- **`phoenix_customer_pin` (Business Access)** — shared, enable flag **off** (`input_boolean.phoenix_customer_pin_enabled`), and the value itself is empty. Two independent reasons it cannot work.
- **`phoenix_drop_off_pin`** — empty, and enable flag **off**. The 2026-10-18 comment records that this code previously opened the strike *without* setting presence, so a valid drop-off triggered the intrusion sequence and paged the family.
- **`phoenix_worker_pin` (generic)** — one code for all workers, and it is handled by the same branch as Montrose and Bachrach (`access_control.yaml:409-467`), which logs `worker_identity` — a Jinja expression that returns "Worker" for the generic code. So a generic worker entry is indistinguishable from "a worker".
- **`phoenix_admin_pin`** — 4 digits, and it is *also* the apartment deadbolt's slot 1, pushed over MQTT in a plaintext payload (`access_control.yaml:2129-2170` → `script.ui_set_kwikset_pin`). One secret, two doors, two trust domains, one of them a Zigbee radio link.
- **`phoenix_parent_pin`** — one code for both parents; `lovelace_parent_1_user_id` exists as a separate principal but there is no parent-2.
- **The owner's presence can be forged by a beacon.** `phoenix_beacon_presence.yaml:239-249` sets `phoenix_user_is_here` **on** from BLE distance alone, with no credential. The alarm treats that as "the owner is here".
- **`input_boolean.phoenix_customer_pin_enabled` defaults to `initial: false`** with a comment recording that the repo once said `true` while the host said `false` — i.e. this posture has already drifted once between repo and host.

### 4.3 Loose ends that make the above harder to reason about

- **49 of 124 `automation.*` entities are `unavailable`** (`GET /api/states`, filtered `entity_id -like 'automation.*'`, counted 14:52 EDT). They are registry rows from deleted YAML — `access_control_keypad_event_handler`, `access_control_keypad_event_handler_2`, `phoenix_access_control_master_controller`, `phoenix_v2_keypad_access_control`, `access_control_process_keypad_entry`, and 44 more. Anyone auditing "what handles a keypad entry" by entity list will find six candidates that no longer exist.
- `automation.phoenix_keypad_event_handler` (the per-user validator) is the one that *must* be on to unify identity, and it is the one that is off, while its dead predecessor sits next to it as `unavailable`.
- **`binary_sensor.phoenix_everyone_away` is `on` while `input_select.phoenix_security_mode` is `Home`** (both read 14:56 EDT). The state that disarms the alarm and the state that describes the building disagree, and nothing reconciles them.

---

## 5. Could a credential event be forged from the network?

### 5.1 How the event is delivered

The ESP32 fires `homeassistant.event` over the ESPHome **native API**; HA's ESPHome integration puts `esphome.access_control_keypad_entry` on its own event bus; the master automation matches on `event_type` alone.

### 5.2 Is the ESPHome API encrypted? Yes, on every committed device config

| Device config | API encryption | Key reference | API password |
|---|---|---|---|
| `config/esphome/security-hub.yaml:61-69` | **on** — `api: encryption: key: !secret security_hub_api_encryption_key` | `secrets.yaml` (host only) | none; `reboot_timeout: 0s` |
| `config/esphome/interior-door-hub-wifi.yaml:42-44` | **on** — `keypad_board_api_encryption_key` | `secrets.yaml` | none |
| `config/esphome/interior-door-hub-wt32-eth01.yaml:90-92` | **on** — `keypad_board_api_encryption_key` | `secrets.yaml` | none |
| `config/esphome/phoenix-presence-hub.yaml:59-61` | **on** — `phoenix_presence_hub_api_encryption_key` | `secrets.yaml` | none |

Note the trap at `security-hub.yaml:64-66`: a *commented-out* "Encryption disabled for now" block sits directly under the live key. The sibling `config/esphome/archive/security-hub.yaml:30` has a bare `api:` with **no** encryption — an older build that would connect unencrypted.

Caveat I cannot close from here: this is the **committed** YAML, not proof of the **flashed** firmware. I have no way to read the running build's config from this machine, and the evidence that the encryption was once off is the comment left in the file. Both hubs are alive (`binary_sensor.security_hub_security_hub_status = on`, uptime 254,951 s; `binary_sensor.interior_door_hub_interior_door_hub_status = on`, uptime 254,952 s), which is consistent with either state.

### 5.3 What an attacker on the LAN can and cannot do

**Cannot** — without one of the credentials below:
- Inject a keypad/RFID event *through the ESPHome API*. The API is encrypted with a 32-byte pre-shared Noise key, there is no API password to guess, and the key is not in git (`config/secrets.yaml` is gitignored; only `secrets.yaml.example` is tracked, and its encryption-key fields are empty strings).
- Quietly open a door by replaying a captured tag at the reader unless the tag is a cloneable type — the reader compares UIDs, not cryptographic challenge/response (`on_tag` → `tag_uid`, no sector auth).

**Can**, with things that already exist on this LAN or in this estate:
1. **Fire the event over HA's own API.** Any principal holding an HA long-lived token can `POST /api/events/esphome.access_control_keypad_entry` with a body of `{"code": "...", "door_name": "strike"}`. The master automation does not check who fired the event. The result is a log line "Owner Access at Strike", `phoenix_user_is_here` on, and the strike released — with nobody at the door. `HA_TOKEN` and `HA_URL` are keys in `personal-secretary-mvp/.env` (324 keys; names inspected, no values printed), i.e. at least two machines hold a token that can do this, and `HA_URL` is **plain `http://`**, not https, so the token crosses the office LAN in the clear.
2. **Open the door over MQTT, with no event at all.** `script.buzz_in_strike` drives the relay by publishing `{"state_l1":"ON"}` to `zigbee2mqtt/Smart Switch/set` (`scripts.yaml:948-951`); `buzz_in_interior_maglock` and the secretary's `_MAGLOCK_MQTT_TOPIC` use the same topic. Zigbee2MQTT authenticates to `mqtt://core-mosquitto:1883` as user `addons` with a password from `!secret.yaml` (`config/zigbee2mqtt/configuration.yaml:4-9`) — **one** shared broker user for the whole integration. Anyone holding it opens the outside door. What lands in the record is `switch.smart_switch_l1` changing to `Unlocked` in `phoenix_door_activity_log` — a relay state, no person, and `input_text.phoenix_access_control_log` is untouched.
3. **Read every PIN and tag.** `mode: password` on an `input_text` masks the *dashboard field*, not the state. `GET /api/states` returns `phoenix_admin_pin` in cleartext to any token, and the recorder keeps 30 days of those states. A reader is a credential thief.
4. **Buy the credential instead of breaking it.** The encryption key is shared by all four ESP32s and by the ESPHome build directory; a rogue node flashed with `security_hub_api_encryption_key` speaks the protocol perfectly and can fire any event with any `door_name`.
5. **Impersonate the beacon** for presence (§4.2) — no cryptography at all.

Net: the ESPHome link is genuinely encrypted and is **not** the weak point. The weak points are the two *other* paths to the same actuators (HA's event bus and the MQTT relay topic) and the fact that credentials are readable state.

---

## 6. Recommendation — the smallest identity model that lets the alarm tell badged from not-badged

The alarm today asks a boolean question (`phoenix_everyone_away`), and every input to it is a one-bit claim: a beacon was near, a door contact moved, a code was typed. That is why it fires on legitimate entrants and stays quiet for a MQTT-driven door. The minimum that fixes it is **one record per credential use, carrying a subject id**, plus **one place that says which subject a credential belongs to**.

**The model — three columns and a rule**

1. **`subject`** — `id`, `kind` (`person` | `role`), `name`, `active`. People are people. Every shared code is a *role* subject (`house_guest`, `business`, `drop_off`, `worker_generic`), never a person — that is what makes "shared" explicit instead of a bug.
2. **`credential`** — `id`, `subject_id`, `type` (`pin` | `tag` | `app` | `key`), `value_hash`, `issued_at`, `issued_by`, `revoked_at`. `UNIQUE(type, value_hash)` is the uniqueness guarantee: one live code, one subject, enforced by the store instead of by a Jinja `elif` chain.
3. **`entry_event`** — append-only: `at`, `subject_id` (nullable), `credential_id`, `door`, `side`, `result` (`granted` | `denied` | `unlocked_without_credential`), `raw_actor` (HA user id or automation id that caused the actuation). Written to `/root/authority.db` on `secratary-cloud`, not to a 255-character `input_text`.

**What must be true for it to be trustworthy**

- **Uniqueness.** No two live credentials share a value, and every credential has exactly one subject. Today `phoenix_admin_pin` is also deadbolt slot 1 and the generic worker code equals nothing but is treated as Montrose/Bachrach — both become impossible.
- **Revocation that is read at the door.** `revoked_at` is consulted on every event, and a revoke *sweeps*: clears the `input_text`, clears the deadbolt slot, drops the tag from the role map. Today revocation is a manual note (the `weinberg-access-revocation-20261018.md` comment at `presence_architecture.yaml:212-213`) and the code path for a revoked Klein tag cannot match at all (§1.2).
- **Audit that survives the thing it audits.** Every mint, change, revoke and use writes `issued_by` / `raw_actor` + timestamp + before/after to the authority, outside the recorder's 30-day purge and outside the 255-char display. Today the only durable trace is a logbook string, and the last week contains a 30-hour hole (§3.4).
- **No plaintext secrets in entity state.** A PIN and a tag are readable by every token and persisted for 30 days (§5.3.3). Hash them and compare on entry; keep the plaintext only where the deadbolt genuinely needs it, and re-program it from the store rather than from a helper entity.
- **The alarm consumes the record, not the boolean.** "Everyone away" becomes "no `entry_event` with `result=granted` and a `person` subject still present". A door contact opening with **no** granted event in the preceding N seconds is an alert *regardless* of every boolean — that single rule covers the window, the key, the power cut and the MQTT publish, which today produce either a false "Occupied" or nothing at all.

**Smallest first step, in the order I would do it** (each is independently useful, none requires the others):

1. Make `rfid_role` data-driven so all five tag roles resolve (§1.2), and bind each PIN helper to exactly one subject name. This alone converts "Owner Access" from a string into a name and makes Klein's tag work.
2. Delete line 118 of `phoenix_access_manager/__init__.py` *before* the validator automation is ever turned on.
3. Write one `entry_event` row per credential event through the existing authenticated webhook pattern (`rest_command.phoenix_security_page` already POSTs to `https://ai.abletelsolutions.com/webhook/ha/security-alert` with `x-ps-api-key`, `phoenix_security.yaml:284-292`) — no new transport needed, and it survives the 255-char cap and the recorder purge.
4. Make the two actuator paths that skip identity (`POST /api/events/...` and `zigbee2mqtt/Smart Switch/set`) write the same row with `subject_id = null, result = unlocked_without_credential`. That is the sentence the owner actually needs: *the door opened and nobody proved anything.*

One decision is not mine and I am not hiding it behind this document: whether the generic worker code, the house-access code and the tenant should remain **role** subjects at all, or whether each holder gets their own credential. That is a business posture — it changes what the log can ever say about a worker — and it is the owner's to set.
