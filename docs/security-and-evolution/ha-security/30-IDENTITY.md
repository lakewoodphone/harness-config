# Identity: who is inside, and what actually proves it

**Rounds 27–33.** The current system has never known who is inside. It knows a `device_tracker` and it
believed one for months after the man left, which is the mechanism that disarmed thirteen alarms
(`05-LIVE-FINDINGS.md` L1). This document replaces "presence" with "identity", and says honestly what each
credential proves.

---

## 1. The roster, from the live credential file

The apartment door is a Kwikset 99140-031 on Zigbee2MQTT, and its slots are documented and enforced in
`live/apartment_deadbolt_codes.LIVE.yaml:7-36` — the header table is the authority:

| Slot | Subject | Written by | Notes |
|---|---|---|---|
| 1 | **Eliyahu** (owner, admin) | `phoenix-pin-rotation`, 14-day family rotation | full access |
| 4 | **Mother *and* Father — one shared slot** | `phoenix-pin-rotation` | *"Mother and Father SHARE slot 4 by the owner's explicit instruction (2026-10-25). They are not separate slots and must not be given separate slots."* |
| 5 | **Yocheved** (his wife) | `phoenix-pin-rotation` | full access; decision `D7429`, 2026-10-18: *"yocheved gets her own full access code"*, rotating, delivered via the owner because she has no mobile on file |
| 6 | **master temporary / house access** | `house_access_pin_control_timer` | the shared guest code, rotating |
| 11 | **Tenant** | `apartment_deadbolt_codes.yaml` only | on demand, **never rotated** |

**The owner's own words** (`from-zabz-tech/HANDOFF` §2): *"the only people who have access are me, my
parents and my wife, and a master guest code for now"* — five subjects, and the slots match them exactly.
Two consequences worth stating because both are counter-intuitive:

1. **Mother and father are one identity**, deliberately. Any log that claims to know which of them entered
   is lying. The system must say `parent`, not `mother`.
2. **The tenant is a sixth subject the owner's sentence does not include**, and decision `D7429`'s expected
   final roster says *"zero … tenant"*. Live, slot 11 is written by a file dated 2026-10-25 and is
   documented as intentional. **This is a discrepancy in the record, not a decision I should guess at** —
   it goes on the question list, with the evidence for both readings.

## 2. What each kind of evidence proves

| Evidence | Proves | Proves *not* | Available today |
|---|---|---|---|
| Kwikset slot used (`action_user`) + `action_source_name` (`keypad`/`manual`/`rf`) | a slot's credential opened that door, at that time | which *human* holds the credential | **NO — measured 2026-10-26. The entity exposes only `friendly_name` and `supported_features: 0`, and its entire 24-hour history carries no `action_user`, no `action_source_name`, no `pin_code` (14 rows read). The audit's claim that the lock names people does not reproduce** |
| Shop keypad PIN (`esphome.access_control_keypad_entry`) | a code was typed | anything, **because the handler that validates it is `off`** — `automation.phoenix_keypad_event_handler = off`, last triggered 2025-12-16 (`phoenix_core.LIVE.yaml:40`) | **no** |
| RFID tag | a tag was presented | who carries it | tag counter entities are `unavailable` (R1) |
| A phone's presence (`device_tracker`) | a phone is somewhere in a coordinate approximation of "home" | a person, an intent, or authorisation | yes — and it is **deleted from the security path** |
| Two independent body signals inside | a body is inside | who | partially (mmWave only; camera human terms contribute 0, S57) |
| A camera frame | that *some* adult was there, and what they carried/wore | identity, reliably | no vision today |
| The owner's own statement | identity **and** intent | anything he is wrong about | yes, and it is the strongest label |

**The consequence, stated plainly: this building currently has no working credential signal at all.** The
apartment door's lock does not report which slot was used, and the shop door's keypad handler is disabled.
So identity is not something the rebuild can *read* — it is something it has to **create**, and every route
to creating it is a live change to the alarm chain:

| Route | What it needs | What it costs |
|---|---|---|
| Enable `phoenix_keypad_event_handler` | one HA automation flipped on, then reload | gives the shop door a named credential — and **first** the component must stop logging mistyped PINs in cleartext (`phoenix_access_manager/__init__.py:118`: `_LOGGER.warning(f"Invalid PIN entered: {pin}")`, read 2026-10-26) |
| Subscribe to MQTT on the broker | a client on a host that can reach the shop LAN, and a broker credential | the raw `action_user` from zigbee2mqtt, but it is a second credential store on a broker already shared for the maglock |
| Read the lock's slot table | nothing new — the `users` attribute exists | proves which slots are *enabled*, never which one was *used* |

Until one of those lands, the record's `entry_event` table will only ever hold rows the sentinel synthesises
from a name if an event happens to carry one — and "unknown holder" is the honest answer for every entry.

**The three rules that follow, and that the redesign enforces in code:**

1. **Presence never grants identity.** A body inside is not a person, and never becomes "the owner" by
   inference. This is the ghost's lesson, made structural.
2. **A credential proves a token, not a human.** Slot 4 is two people; slot 6 is however many guests; slot
   11 is a tenant whose name the system does not have. The record stores the *slot*, the *source*, and the
   *resolved subject with a confidence*, and "unknown holder of slot 6" is a legal answer.
3. **Only a credential may disarm.** The current system disarms on presence (`phoenix_security.LIVE.yaml`
   `:95-102` + `presence_architecture.LIVE.yaml:287-313`). That is the defect, and it is also why
   "who disarmed it" has never been answerable.

## 3. The registry, as data

```
subject(id, display_name, role, rank, credentials[], expected_hours[], page_targets[], active)
credential(slot, system, kind, value_hash, subject_id, issued_at, rotated_at, revoked_at, revoked_why)
entry_event(id, at, door_id, system, slot, source, subject_id, confidence, raw_hash)
```

- **Never store a PIN.** `value_hash` only. The lock itself never returns a PIN —
  `apartment_deadbolt_codes.LIVE.yaml:34-36` says so explicitly: *"Locks never return an existing PIN; we
  only read the slot's enabled/available status."* The registry must inherit that discipline.
- **`door_id` is canonical, and today it is not.** The same physical door produces two entities that fire
  within the same second on 246 edges (R4). Any identity log keyed on the entity id would split one person
  into two people.
- **Every rotation writes an `entry_event`.** The family rotates every 14 days; if a rotation is invisible
  to the record, the system loses the ability to attribute the *next* entry. A rotation is the one moment a
  credential's identity is knowable for certain — that is exactly when to record it.

## 4. The plaintext PIN leak, which is a live defect and not a design choice

`sensor.0x002446fffd0a4705_pin_code` publishes **the last PIN used, in plaintext**, retained ~28 days by the
recorder (prior audit, S-new #12 in `from-zabz-tech/HANDOFF` §8.12). With a 14-day rotation this is a
window in which the current code sits in a readable history. It is the credential equivalent of a
world-readable `.env.bak` — the estate has paid for that mistake four times (pain `P344`, `P2938`, `P13b`).

**Fix, in order:** (a) exclude that entity from the recorder; (b) stop publishing it at all if the
integration allows a template override; (c) purge the existing history; (d) rotate every affected code,
because a redacted history is still a history of a live credential.

## 5. What identity buys the building

Not attribution for its own sake — three concrete capabilities no automation has today:

1. **The credential veto** (`10-ARCHITECTURE.md` §1) needs to know that *a credential was used at that
   door*, which requires the credential event to exist as data. Today it does not: keypad events are HA
   events, which are not recorded anywhere (R1 #8).
2. **Out-of-hours, by person.** "Father entered at 23:20" is a note; "slot 6 entered at 23:20" is a page,
   because slot 6 is a shared guest code. The rule is per-subject, which requires subjects.
3. **The learner's strongest feature.** Arrival signature per subject per hour is the feature that turns
   14/14 false into "a person at the shop door at 23:20 who is not the owner". Without identity there is
   only one feature — time of day — and that is what the current system already mis-uses.

## 6. Open, and not mine to decide

- **Is the tenant supposed to have a code?** Live says yes (slot 11, written 2026-10-25); `D7429` says the
  expected roster is *"zero … tenant"* (2026-10-18). Evidence for both is in the record; the answer changes
  who the alarm is allowed to ignore.
- **Who receives a page?** Live roster is `OWNER_PHONE_NUMBER=+17325691594` plus
  `HA_SECURITY_EXTRA_RECIPIENTS=+18482245096,+18483897895` (`docs/STATE-2026-09-17`, prior session), while
  decision `D240` says his mother was meant to be on it and the prior audit (S29) says she is not.
- **Does Yocheved want her own pages**, or is being on the roster enough?
