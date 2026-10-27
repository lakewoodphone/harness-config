# The security system, redesigned as a system the company runs

**Status:** design in progress, 2026-10-26, ZABZ-YOGA. Nothing here is deployed. Every number carries
where it was read. Prior work it extends: `from-zabz-tech/` (audit S1–S84, 20 design rounds, 12 reports).

---

## 0. The one sentence

**Home Assistant keeps a reflex; the company keeps a mind; the record keeps a memory; and a written
constitution decides which of the three is allowed to touch the building.**

The owner's complaint about the current system is exact: **at least 188** automation blocks, 997 Jinja
expressions, 58 `delay:` steps (`Get-ChildItem ha-config/config -Recurse -Include *.yaml` + regex counts,
2026-10-26; one file failed to parse in the scan, so the counts are floors, not totals) —
and after all that code, in 30 days it produced **15 alarms, 14 real, 0 unauthorised entries, and never
delivered one page** (`from-zabz-tech/HANDOFF` §5.1, §5.2). That is not a system with a bug. It is a
system whose intelligence is in the wrong place: it encodes *judgements* (who is here, is this normal,
who is this person) as constants in YAML, where they can never be right for more than one week.

## 1. The four layers, and the line between them

| Layer | Lives in | Reacts in | Owns | May never |
|---|---|---|---|---|
| **Reflex** | Home Assistant, local, YAML/Scripts, no network | ≤ 2 s to siren, ≤ 30 s to first page attempt | *whether an alarm exists*; siren, strobe, local push, self-timeout, fail-safe | learn, interpret an image, wait for a server, decide a person's identity |
| **Mind** | the company (`company-api` + a new always-on sentinel on the authority) | seconds to minutes | *what it means*: corroborate, identify, explain, escalate, add channels, ask the owner, write the record | be the only path by which an alarm exists; silence a siren; open a door without a credential |
| **Memory** | `/root/authority.db` — four tables, one writer | — | every event, decision, label, action, with evidence and the build sha | be edited to look better in hindsight (append-only) |
| **Constitution** | code, not prompt — `app/security/constitution.py` | — | the allow-list of actions, the fail-safe defaults, the injection rules, the money/attention budgets | be overridable by an agent's own reasoning |

This is the prior design's "three laws" (Round 5) made structural. The new part is **the input path runs
the other way too**: the mind does not only *react* to the reflex, it *writes the reflex's context*.

### 1.1 The keystone: the agent supplies the facts, HA decides from them

HA cannot know that Montrose left in March, that the hallway is a public 24/6 pickup corridor, that the
owner is away for Yom Tov, or that 23:20 on a Saturday is unusual for this shop. So it must not be asked
to. But the fix is **not** "let the agent write an `expected_empty` boolean" — that boolean is the
building's whole alarm, and an agent that can write it can silence the shop (`40-SAFETY.md` §1.1). The
agent supplies **facts with a provenance**; HA computes the boolean from facts it can check itself.

| Input | Written by | What it means | If the company is silent for 15 min |
|---|---|---|---|
| `security_credential_occupancy` | HA, from the credential path | a credential was granted at a perimeter door within `T` and no uncredentialed door edge since | keeps its local value — this is the strongest path and it never needs the company |
| `security_schedule_open` | HA, from a schedule the owner confirmed | the shop is expected open today, per hours he has actually confirmed | falls back to **closed** |
| `security_owner_here` | HA, from a recorded owner instruction (message id kept) | he said he is there | falls back to **off** |
| `security_posture` | company | `closed` / `open` / `delivery` / `guest` / `maintenance` — may only **raise** severity | falls back to `closed` |
| `security_context_reason` | company | one line, shown in the page and on the dashboard | stale value displayed **as stale**, with its age |
| `security_sentinel_alive` | company heartbeat, 60 s | the mind is alive | goes `off` → rule 6 fires a "mind down" page |

```
expected_empty = NOT(credential_occupancy OR schedule_open OR owner_here)
```

So: with the mind dead, the building is armed on the schedule and the credential path — both local, both
deterministic. With the mind malicious, the worst it can do is make the building **loud**.

The six reflex rules then read as they should, and they stay six lines:

1. A door contact opens while `security_expected_empty` is `on` **and** no credential granted in the
   preceding `N` s (N = 120, tunable inside a band by the learner) → alarm.
2. Two independent Tier-C corroborations of a person inside while `expected_empty` is `on` and no
   credential since the last disarm → alarm, higher priority.
3. A duress credential → **silent** alarm: no siren, immediate page with a different payload.
4. Any alarm bounds itself: siren ≤ N minutes, then persist state and page again rather than scream.
5. Any page attempt failure → second channel, and a heartbeat that proves the path alive every 6 h.
6. `security_sentinel_alive` goes `off` → a "the mind is down" page, and posture freezes at `closed`.

**Why this is the right seam.** The reflex never needs a database, a model, or the internet, so an
outage cannot remove the alarm (Round 11's table). The mind never needs to be trusted with the alarm's
*existence*, so a model that is slow, wrong, or jailbroken cannot silence the building — it can only
change *what the building expects*, and it must write down why, in a row that carries its build sha.

## 2. The company side: five agents, one queue, one record

Today the company is a tick with 18 departments and no security department; the closest is
`dept_systems_custody`, whose remit is holding systems, not judging threats (design doc Round 7). **Measured
2026-10-26:** `AUTOPILOT_INTERVAL_SEC=900` in `/opt/company/.env` — so the base cadence is **15 minutes, not
hourly**, and `SCHEDULE_MODE=cheap-first`. There is also **no wake unit on the authority at all**
(`systemctl list-units --all | grep -i wake` → nothing), so nothing currently wakes the company on an event.
The new security work is therefore **not** a department that runs on the tick — a 15-minute tick cannot do
03:00. It is a small always-on runtime with four roles, each with a different clock:

| Agent | Clock | Job | Model tier | Budget |
|---|---|---|---|---|
| **Sentinel** | always on, per event | owns the context facts; triages every candidate incident in ≤ 60 s; decides *escalation*, writes the decision row | cheap | ~$0.01/day |
| **Investigator** | on escalation | pulls every signal, the frames, the last 30 days of similar episodes, the roster; names the likely subject; drafts the page text and the one-line reason | smart | ~$0.01/day |
| **Watchman** | nightly | labels the day, compares prediction to outcome, fits the context numbers, proposes rule changes **with a replay attached** | smart | ~$0.02/night |
| **Auditor** | weekly | drills, sensor health, clock skew, disk, token age, the four KPIs, one page to the owner | smart | ~$0.01/week |
| **Steward** | hourly | batteries, unavailable entities, camera liveness, evidence retention actually running, HA recorder integrity | cheap | ~$0.02/day |

The measured reason these budgets are trivial: a triage turn is ~2 k tokens in, ~200 out; at
`deepseek-v4-flash` pricing ($0.14/$0.28 per M tokens, `AGENTS.md` model table) that is **$0.0004**.
Fifty events a day is **two cents**. Cost is not the constraint on this design — reliability, latency and
the owner's attention are. That is the opposite of the usual assumption and it should shape the build:
spend the money on *more evidence per event*, not less.

**The queue.** Every candidate incident becomes one row in a durable queue with a dedup key
(`episode_id`), so a burst of 50 state changes is one incident, not 50 agent turns. The Sentinel is a
consumer, not a poller. What already exists in the company and is reusable: `event_queue.py`,
`event_router.py`, `trigger_engine.py`, `ceo_wake.py`, `agent_worker.py`.

**Where it runs — measured, not assumed** (`research/A-transport-runtime.md`):
- **Transport: the HA WebSocket API**, one long-lived client, `subscribe_events` for `state_changed` narrowed
  by `subscribe_trigger` per security entity. Not webhooks: HA answers **200 OK for an unregistered webhook
  id and 200 OK when the handler raises** (`webhook/__init__.py:148`, `:196-199`, `requires_auth = False` at
  `:216`), so a 200 proves only that a socket opened — a success signal uncorrelated with delivery cannot
  carry an alarm. Measured socket cost: ping p50 **16.7 ms**, delivery drift p50 **9 ms** / max 26 ms,
  reconnect **105 ms**.
- **The listener runs on `zabz-tech-linux`**, as a systemd unit with `Restart=always` and a `MemoryMax`. It
  is the only always-on host that reaches HA **directly on the LAN (40 ms)** *and* sits on the tailnet. The
  authority cannot reach `192.168.50.34` at all; the only bridge today is a TCP forward owned by `tailscaled`
  on the owner's Windows desktop, which would make his workstation a single point of failure for judgement.
- **HA events must enter the queue at priority 0 or 1.** The queue drains on a wake signal, and
  `AUTOPILOT_INTERVAL_SEC=900` — a priority-2 event waits **up to 15 minutes** (`autopilot.py:7119-7127`).
- The authority stays the **sole writer** of the record; the listener ships events to it.

## 3. What the mind actually adds, in the owner's terms

He asked for a system that is *not stupid automated code*. Five capabilities are the difference, and each
is something no YAML will ever have:

1. **It knows what it expects.** Shop hours, the calendar, who is scheduled, that the hallway is public,
   that a courier at 11:00 is normal and a person at the shop door at 23:20 is not. Today `everyone_away`
   is a motion-gap detector that declares the shop empty **9.77 times a day** (R1 §4). The expected-state
   model is the single largest precision lever in the whole design, and it is pure agent work.
2. **It asks instead of assuming.** When the reflex is about to fire and the mind is not sure, the mind
   can *ask the owner first* with a 30-second window: "Shop door opened, no badge — you?" with the frame.
   One tap = a label, a silent stand-down, and a rule learned. No automation can do this; it is the
   literal definition of judgement. **Guard:** the ask can only *delay the siren*, never the page — the
   evidence and the notification go out regardless, so an unanswered ask still escalates.
3. **It explains in one line.** "Shop door opened 23:20:14, no credential in 120 s, hallway public and
   empty, no phone inside, frame shows one adult at the door" is auditable. "Intrusion detected" is not.
   Every page and every dashboard line carries that sentence.
4. **It maintains itself.** 370 of 1037 entities are `unavailable`/`unknown` right now
   (`/api/states`, read 2026-10-26 21:2xZ through the company client) — a third of the system is dark and
   nothing says so. Batteries at half with a December date, a camera dead for 29 days, two cameras 16
   minutes apart in time, a 30-hour recorder hole: the Steward's job is to find these *before* they
   matter, and the Auditor's job is to prove weekly that it did.
5. **It learns with a gate.** Every episode gets labelled from evidence, every proposal is replayed
   against all stored history, and a change that would have missed a real event is refused. The estate's
   own history says why this matters: `evolution_verification` "passed" 103 of 103 changes because the
   only metric was an error count (`HANDOFF-TO-NEXT-AGENT.md` §4.4).

## 4. Identity: the thing the current system cannot do at all

The system has never known *who* is inside. It has a `device_tracker` that still reports `home` for a man
who left months ago, and that single stale fact disarmed thirteen alarms (`design` Round 3 addendum II).
The owner's roster is five subjects, stated by him: himself, his mother, his father, his wife, and one
master guest code (`HANDOFF` §2).

The resolution ladder, strongest first — and the only ordering that is honest about what each step
proves:

| Step | Proves | Available today |
|---|---|---|
| 1. A **credential** at the door (Kwikset slot / shop keypad / RFID) | *a subject used a credential* | yes — `lock…action_user` + slot names, `esphome.access_control_keypad_entry` |
| 2. **Two independent presence signals** inside | *a body is inside* | partially — hub mmWave + BLE mmWave; the camera human terms contribute 0 (S57) |
| 3. **Visual corroboration** (optional, later) | *one adult, carrying, wearing what the owner wears* | no — no vision at all today (S8-§5.8) |
| 4. **The owner's own word** (asked, or volunteered) | *identity, and intent* | yes — and it is the strongest label the system can get |

**The rule that comes out of the ghost:** presence is never proved by a tracker, and identity is never
inferred from presence. A credential is a *token*, not a person — a shared code attributes a role, not a
name, and the record must say which. That is an owner decision, already flagged (Round 3, Q1).

## 5. The conversation channel (what "dependent on you" actually means)

Two directions, both through channels that already exist (SMS via the company, push via the companion app):

- **Owner → system.** "Who's at the shop?" → a picture and one line. "Was that you at 2pm?" → a label.
  "Arm it, I'm leaving." → posture. This turns the security system into something he *uses*, which is the
  only way it stays true: a system he never talks to cannot be verified by him.
- **System → owner.** Not just alarms: "the shop door has been open 40 minutes and nobody is inside"
  (the propped-door case, 57 % duty measured); "the doorbell camera has been dark 6 hours"; "the battery
  on the shop door contact dies around 2026-12-09"; and the weekly one-pager.

**Hard limit, unchanged from the estate's own rule:** nothing outbound to a *third party* without his
per-message yes. A page to *him* is not a third party — but the roster matters, and today the roster is
two phones plus a duplicate of the owner while `D240` says his mother was meant to be on it (S29).

## 6. What is deterministic, what is learned, and what is never learned

| Class | Examples | Rule |
|---|---|---|
| **Deterministic forever** | door + no credential → alarm; duress → silent alarm; siren timeout; heartbeat | may be *parameterised* (N, minutes) inside a band, never removed |
| **Learned, inside bands** | `N` (60–180 s), siren minutes (3–15), per-hour base rates, arrival signatures, which Tier-C pairs corroborate | every change replayed; a change that removes firing power needs the owner's line |
| **Learned, free** | expected occupancy, the weekly rhythm, "this is the courier", explanation quality, which maintenance is urgent | no gate beyond the record |
| **Never learned** | that a disarm means benign; that a page without an answer was false; that a quiet week is a safe week | labels come from evidence, never from silence or from a human's fatigue |

## 7. Failure ladder — what happens when a piece is missing

| Missing | Reflex | Mind | What the owner sees |
|---|---|---|---|
| internet / cloud | fires | degraded to nothing | companion-app push over the LAN if on it; otherwise the siren and the record |
| the authority (company down) | fires; posture freezes at `closed` | — | "mind down" page from the reflex's own watchdog |
| HA down / restarting | nothing local | Sentinel sees the heartbeat drop | "HA down" page within 2 min (a second watcher) |
| the Sentinel dead, company alive | fires | Sentinel absent | heartbeat timer in the company raises it; Auditor's weekly page names it |
| model provider down | fires | Sentinel falls back to a deterministic triage (rules + roster + last 30 days), and says so in the record | a page that says "judged by fallback rules" |
| the shop desktop (tailnet proxy) off | fires | cannot reach HA | **this is a single point of failure to be removed** — see §8 |
| power cut | nothing | — | on restart: a "we lost power at T, here is what was happening" page |

## 8. Known structural weaknesses of *this* design (stated before an attacker finds them)

1. **The tailnet path to HA runs through the shop desktop.** `settings.ha_url =
   http://zabz-tech.tail93e6e6.ts.net:8123` — a proxy on a Windows PC. If that PC is off, the mind is
   blind while the reflex still works. Fix: a subnet router or a Tailscale node *on the HA host*
   (HAOS supports the Tailscale add-on), so the path has no desktop in it.
2. **The HA token is owner+admin, no MFA, plaintext, plain http** (S8 §8.8). Any agent path that reads it
   can disable the alarm. Highest-value single fix in the audit, and it is a maintenance window.
3. **370 of 1037 entities are unavailable.** A third of the sensor surface is dark; the design must
   distinguish "no evidence" from "no event" (S43, S57).
4. **No coverage on some openings** (S47): windows, glass, the back, and the maglock door has no contact
   at all. No software fixes a door with no sensor.
5. **Both maglocks are fail-safe** (S73): cutting power unlocks them silently.
6. **The cameras disagree about the time by 16 minutes** (S17/S65), so any cross-camera reasoning — and
   any learned arrival signature — is wrong until the clocks are fixed.

## 9. Build order (unchanged where the prior design is right)

Phase 0 repairs are done (2026-10-26, 8 items, `HANDOFF` §6). Then:

| Phase | What | Acceptance test |
|---|---|---|
| **A — the seam** | the four context inputs + heartbeat + posture in HA; the Sentinel reading events and writing only those | with the Sentinel killed, HA alarms conservatively within 15 min and pages "mind down"; with it alive, `expected_empty` follows the shop's real day |
| **B — the record** | four tables + the writer + the dedup key | every event in 24 h has one row; every alarm has a decision row with its one-line reason and the build sha |
| **C — the mind** | Sentinel + Investigator on a real queue; the ask-the-owner window | a synthetic door-with-no-credential produces one page ≤ 30 s with a picture and a correct sentence; a credentialed entry produces none |
| **D — identity** | the subject registry, credential→subject resolution, the ghost audit | the five subjects resolve; a stale tracker cannot grant presence (test: a tracker left `home` changes nothing) |
| **E — learning** | Watchman nightly, the replay gate, one promotion and one refusal, both recorded | a proposal that would have missed a real episode is refused with the episode named |
| **F — eyes** | vision as corroboration only (hardware decision) | person-vs-not correct on 20 labelled frames; never the sole trigger |

## 10. Open questions this design cannot answer without the owner

Collected as they arise; the final document is `OWNER-DECISIONS.md`. For now: vision hardware, the
mother on the page roster, whether shared codes stay roles, the non-admin token window, and what the
frozen `secratary` box becomes.
