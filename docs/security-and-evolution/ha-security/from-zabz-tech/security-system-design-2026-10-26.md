# Security system design — a learning system run by the security department

Working document, 2026-10-26. Append-only per round. Every claim carries its evidence.

Owner's brief, verbatim:

> *"hold on, there are multiple ways to see if someone is in teh room, we have a person sensor, cameras, door
> sensors and more. did you analyze this all to maybe build a smart security system run by the security dept on
> the ai company instead of unmanaged automated one? this way its more accurate and evolves and gets better and
> learns overtime. analyze and audit this all over again how you would create this fully, do this for 20 rounds
> before coming back to me with questions for us to go through."*

So: not another patch on `phoenix_security.yaml`. A design for a system whose *judgement* comes from the AI
company's security department, with Home Assistant as the sensor and actuator layer, and a learning loop that
makes it better every week. Twenty rounds, then questions.

---

## Round 0 — what already exists, measured (the answer to "did you analyse this all")

Yes, and the answer is uncomfortable: **at least eight independent signals can see a person, and the alarm
currently uses one derived boolean built from three of them — two of which are dead.**

| # | Signal | What it can say | Live state, 2026-10-26 | Has it ever worked? |
|---|---|---|---|---|
| 1 | `binary_sensor.video_doorbell_person` (Reolink) | a person is at the front door | **92 firings in 42.68 h** | yes — the only reliable outside signal, and the one that caused all six false alarms |
| 2 | `binary_sensor.cam_*_smart_motion_human_2`, 35 entities (Dahua IVS) | human motion inside, per camera | all `off` | **never fired** — zero events in 42.68 h |
| 3 | `binary_sensor.control_room_hub_control_room_presence` (mmWave LD2410) | someone is in the control room | `off` since 14:31 | yes, but **80 firings at 1.9/h with the shop empty** |
| 4 | three Zigbee door contacts | a door opened | 51 / 48.5 / 47.5 % battery; one **latched `on` for 67 h** on 18–21 Oct | yes, edge-only |
| 5 | BLE beacons (Bermuda + BCP Pro) | the owner's tag is near the control room | **every sensor `unavailable`** | not now |
| 6 | `device_tracker.monty` (phone) | owner's phone is within **100 m** | `home` | yes, but 100 m is most of the block |
| 7 | `media_player.control_room == 'playing'` | the Echo is **busy** | `idle` | counts as "occupied" — a speaker is a presence sensor here |
| 8 | keypad + RFID | **who** crossed, by name | `Owner Access at Interior` at 13:22 | yes, and nothing reads it for the alarm |
| 9 | cameras as images | identity, intent, object | 4 of 4 capture; one is a 640×480 frame, one is an empty NVR channel | images yes, classification no |

The current system's entire threat model is: *"the template over booleans 3, 5 and 7 says everyone is away,
and one of two door zones went from off to on."* Signals 1, 2, 8 and 9 are unused for detection; 2 and 5 are
dead; 7 is an audio player; 6 is a 100-metre guess. That is why four out of four alarms today were false and
why a real one would also have been missed.

**Thesis to be tested over the twenty rounds, not assumed:** a *deterministic safety envelope* stays in Home
Assistant — the parts that must work with no network, no cloud and no model — and *judgement* moves to the
security department, which fuses the signals above, explains itself, and learns from every event the owner
labels by his behaviour. Neither half alone is acceptable: a pure agent is unavailable exactly when the power
or the network is, and a pure YAML automation is what we measured today.

---

## The twenty rounds

Each round answers one question and appends its section here. Rounds may be revised by later rounds; nothing is
deleted, and disagreements are recorded as disagreements.

**Part A — truth (what we actually have)**
- R1 Signal inventory: every presence/entry signal, its latency, its reliability, its failure mode, and how
  often it fires in a normal week.
- R2 Camera truth: what each camera can actually deliver (resolution, night, angle, face), and what
  classification is available locally vs in the cloud.
- R3 Identity truth: keypad, RFID, PIN, phone, beacon — who maps to whom, where the mapping lives, and what
  proves a credential rather than inferring it.
- R4 Ground truth: reconstruct the last 30 episodes from cross-signal evidence — owner, worker, customer,
  passer-by, or unknown — to build the first labelled set.

**Part B — architecture (what to build)**
- R5 The split: what must be deterministic and local, what may be an agent, and the boundary between them.
- R6 The fusion model: how the signals combine into presence confidence and threat confidence, with numbers.
- R7 The security department: its charter, its tools, its latency budget, and what it may decide alone.
- R8 The record: events, decisions, labels, and where the truth lives so the system can learn from it.

**Part C — adversarial**
- R9 Attack the design: spoofing, fail-open paths, collusion between signals, and the cheapest way to defeat it.
- R10 Attack the learning: poisoning, drift, overfitting to one quiet week, and reward hacking.
- R11 Availability: cloud down, HA down, Mac off, disk full, network partition, power cut mid-alarm.
- R12 Economics: how many false pages per week is acceptable, what a miss costs, and the arithmetic behind both.

**Part D — build**
- R13 Phasing with an acceptance test per phase, in the order that removes risk first.
- R14 Migration with no blind window: how to change a live alarm without leaving the shop unwatched.
- R15 Observability: heartbeats, the one-second self-test, drills that prove the siren and the page.
- R16 The charter in writing: what the department decides alone, what waits for the owner, what it may never do.

**Part E — stress**
- R17 Red team the finished design, both directions — and re-run the earlier adversarial rounds against it.
- R18 Scenario replay: run ten historical episodes through the proposed logic and show what it would have done.
- R19 Cost, effort and risk ledger, with the decisions that are the owner's marked as his.
- R20 The consolidated design and the questions, one at a time.

---

## Round 1 — the signal inventory (in progress)

_(fleet dispatched 2026-10-26 ~20:40 UTC; four read-only workstreams: R1 signals, R2 cameras, R3 identity,
R4 ground truth. Each reports with evidence and each appends here.)_

---

## Round 5 — the split: what must stay deterministic, and what may be an agent

This is the load-bearing decision. Get it wrong in either direction and the system is worse than today.

**The pure-automation failure is measured, not argued.** In 42 hours: four alarms, four false; a page that
could only be sent after the alarm ended (2 h 51 m); a siren latched on for 12 h because the only thing that
turns it off is a disarm; a door latched blind for 67 h because the rule is edge-only; and no learning of any
kind — every episode taught it nothing. Nothing supervises it, which is exactly the owner's word:
*unmanaged*.

**The pure-agent failure is equally real.** An agent turn costs seconds to a minute; the cloud can be down; the
model is non-deterministic; and an agent that reads untrusted content — a camera frame, a voicemail — can be
talked out of a decision. An alarm that depends on a network round trip is not an alarm.

**The boundary rule, stated as three laws:**
1. **Anything that must happen while the network is down happens in Home Assistant, deterministically.** The
   local envelope may fire the siren, strobe the lights, post to the companion app and start the page retry with
   no server, no model and no cloud.
2. **The agent may always add force; it may never be the only force.** It can escalate, add a channel, call a
   phone, wake a human, or explain. It cannot be the sole path by which an alarm exists.
3. **The agent may never silence.** Silencing requires a credential, an explicit owner instruction, or the
   envelope's own timeout. A model that decides "this is probably fine" is not allowed to stop a siren.

**The layers, with budgets:**

| Layer | Runs | Latency budget | May decide | Must never |
|---|---|---|---|---|
| **L0 envelope** | HA, local, always | detection → siren ≤ 2 s; → first page ≤ 30 s | fire, page, strobe, time out, self-test | learn, guess, interpret an image |
| **L1 triage** | security department agent, seconds | verdict ≤ 60 s, and its absence must change nothing that L0 did | corroborate, add channels, name the likely person, ask a human, recommend stand-down | silence, delay L0, or block a page |
| **L2 learning** | security department, minutes to daily | overnight | propose threshold and rule changes, replay them against history, promote what passes | edit the envelope without a passing replay and an owner-visible record |

**What the envelope actually is — six rules, auditable, no model:**
1. Any door contact opens while `everyone_away` → local alarm.
2. Any door opens with no credential in the preceding 120 s → local alarm.
3. Presence detected inside (two independent signals) while `everyone_away` and no credential → local alarm.
4. Duress credential → silent alarm (no siren, immediate page with a different payload).
5. Any alarm bounds itself: siren N minutes, then persist the state and page again rather than scream forever.
6. Any paging failure → second channel, and a heartbeat that proves the path alive every N hours.

**Where "more accurate and it learns" actually comes from.** Not from the model being smarter at the moment of
alarm — that is the least reliable place to put intelligence. It comes from L2, which owns the things that
today are hardcoded guesses: which signals are trusted at which hour, which zones are armed when the shop is
open versus closed, who is expected today, what normal looks like for this shop on a Tuesday, and which of
today's four false alarms share a cause that a threshold change would have removed. Every one of those is a
number that should be *fitted to labelled history*, not chosen by whoever wrote the YAML.

**The one thing that makes the agent layer trustworthy:** it must be able to say *why*, in one line, with the
signals and their timestamps — and that line must be in the page the owner reads at 03:00. "Person at the front
door, no credential, control-room presence 4 s later, no phone on the premises" is a decision a human can audit.
"Intrusion detected" is not.

---

---

---

## Round 7 — the security department: what it is, what it may decide, and why it must not default to L4

**There is no security department today.** `company_blueprint.DEPARTMENTS` (line 164) defines fourteen, and
none of them is security: business ops, finance, engineering, research, home life, world index, systems custody,
scheduling, comms/relationships, evolution/reliability, AI platform, devices, creativity, mashgiach. The closest
is `dept_systems_custody`, whose remit is holding systems rather than judging threats. So the owner's phrase —
"run by the security dept on the ai company" — describes something that does not exist yet, and the first build
item is to create it as a first-class department with a mission, KPIs and standing orders, not as a script.

**The autonomy trap, and it is a real one.** `app/services/autonomy.py` line 376: *"Unknown actions default to
L4 (autonomous) — bias towards action."* So a new action invented by a security agent — call the owner's phone,
drop a lock, silence a siren — is **autonomous by default** unless it is explicitly registered in the matrix.
For most of this company that bias is right. For security it is exactly backwards: the department's power must
come from being *registered*, never from being unknown.

**Its three cadences:**
- **On event (seconds) — judge, do not delay.** Receives the event the envelope already acted on, corroborates
  it against every signal, names the likely person, adds channels, and writes the decision row. It cannot
  silence and cannot delay L0.
- **Nightly (minutes) — learn.** Reads the day's labelled events, compares what it predicted against what
  happened, and proposes threshold and rule changes. Every proposal is replayed against stored history before it
  may be promoted, and a promotion is a committed diff with a date and a reason.
- **Weekly — audit and drill.** Runs the one-second regression check, a silent drill, a siren test the owner is
  told about in advance, a sensor-health sweep, and writes one page: what it learned, what it changed, what is
  still blind.

**Its tools, and the line.** It may read every signal, read and write the event/decision/label tables, page, call,
add a channel, and propose config diffs. It may **not** edit HA config directly, disable an automation, or
silence anything. Those require a human or the envelope's own timeout.

**Its KPIs** — the numbers that would let the owner judge it in one line: false pages per week; median
time-to-page; median time-to-human; percentage of entries covered by a credential; sensors blind or unavailable
right now; drills passed; and the number of labelled events in the last 7 days (because a system that stops
recording stops learning).

## Round 8 — the record: what must be written down for any of this to learn

**Today the system forgets in 44 hours.** The HA recorder holds about 1.8 days against a config that promises 30
(measured, S60). `sms_log` keeps every send forever, but only sends. `activity_log` has zero intrusion rows.
`trigger_engine.ha:security_alert` cannot fire (S35). So there is no corpus to learn from, and the evidence for
today's incident expires this week.

**Four tables, one writer, in the authority database:**
- `security_event` — one row per signal edge that could matter, with the entity, the state, the timestamp to
  the second, and the measured latency from the physical event where known. Cheap to write, impossible to
  reconstruct later.
- `security_decision` — one row per alarm: what fired it, which signals were considered and what they said,
  what the envelope did, what the agent concluded, and the one-line explanation that went into the page.
- `security_label` — what actually happened: owner / worker / customer / passer-by / unknown / drill, with the
  evidence that settled it, the confidence, and who labelled it. This is the training set.
- `security_action` — what was done and by whom: siren, page, call, silence, disarm, drill. Who includes the
  agent, a human name, or a credential.

**Retention:** events 90 days, decisions 2 years, labels forever, evidence images 30 days with a nightly export
to the estate's file store. The point is that the label and the decision outlive the image and the logbook.

**The fields that do not exist today and must be added first** — because a learning system cannot start without
them, and every day without them is a day that cannot be learned from: the event id, the credential (or its
absence), the person inferred and how, the siren start and stop, the page attempt and its result per recipient,
the first human action, and the label.

---

## Round 9 — attacking the design (this round assumes the design in R5 and tries to break it)

An honest red team on the proposed system, cheapest attack first. "Envelope" means the L0 local rules.

| # | Attack | Cost to attacker | What it defeats | Mitigation that fits this estate |
|---|---|---|---|---|
| 1 | **Cover or disable the doorbell** | a hand | the only outside signal that has ever worked (92 firings in 43 h); every approach detection dies | a second, physically separate outside sensor (a £20 PIR at the door, wired to the same mesh) and an availability alarm when the doorbell goes quiet for a day |
| 2 | **Walk through the maglock door** | free | there is no sensor on it at all (S47) | a contact on that door — hardware, but it is the cheapest coverage win in the audit |
| 3 | **Leave a phone inside** | free, accidental | device_tracker.monty = home within a 100 m zone, and passive arrival only needs room-occupied + tracker | shrink the zone to the building; require a credential for passive arrival, not a phone |
| 4 | **Make the Echo play** | free | zone_control_room_occupied counts media_player == playing as a person | remove that term (S52) |
| 5 | **Clone the BLE beacon** | ~£5 | iBeacon advertisements are unauthenticated; if a beacon is ever trusted again it can be replayed from outside | do not treat an unauthenticated radio advertisement as a credential; if beacons return, bind them to a rotating token |
| 6 | **Use a shared or borrowed credential** | social | one PIN opens the shop and the alarm accepts it as "someone legitimate" | per-person PINs and tags, revocation on the day someone leaves, and a page when a credential is used outside its owner's normal hours |
| 7 | **Take the HA token** | one file read | owner+admin, no MFA, plaintext on at least two hosts (W7 #1) — can disable the automation, silence the siren, forge a credential | the non-admin token (C16); this is the single highest-value fix in the whole audit |
| 8 | **Cut the power to HA** | a switch | everything local; no siren, no page, no record | UPS on the HA box and the Mac, and a battery-backed siren that does not depend on either |
| 9 | **Cut the network** | a cable | the page path; the envelope still fires the siren | companion-app push over the LAN, and a page path that does not need the internet |
| 10 | **Fill the disk** | time | snapshots, recorder, and eventually the DB — already 63 % with no telemetry (S43) | the host telemetry item (C29) and retention that runs on its own schedule (C21) |
| 11 | **Feed the agent a picture it misreads** | free | a hooded figure, a mannequin, a printed face; and any text the agent reads from a camera or a voicemail is untrusted input | the agent may only ever *add* force; the envelope decides whether to alarm, and the page carries the signals, not the model's opinion |
| 12 | **Deny by noise** | free | fire the doorbell 50 times to train the owner to ignore pages | rate-limit the page channel, not the alarm; and make the page one line with the reason |

**The pattern:** eight of the twelve need nothing but a body and a minute. That is not a flaw in the design, it
is the nature of a building — but it means the design's honest claim is *"it will notice and tell you"*, never
*"nobody can get in"*. The three that are software-only (5, 6, 7) are the ones to fix first, because they defeat
the system without ever entering the building.

## Round 11 — availability: what happens when a piece is missing

Every row is a real failure this estate has had, or one it is one accident away from.

| Piece missing | Today | What the design requires |
|---|---|---|
| **Cloud / internet** | page dies silently; siren still runs | envelope fires locally; companion-app push over the LAN; a second page path that does not cross the internet |
| **HA core down or restarting** | siren keeps sounding (a latch in another process); loop does not resume; no record | the Mac siren self-stops after N minutes unless refreshed; on start, reconcile every actuator against the flag and silence what should not be sounding |
| **Mac mini off** | **no audible alarm at all**, and (today) the page is aborted too because the call has no continue_on_error (S41) | the page must never depend on the siren call; a second audible device, or a siren that lives on the HA host |
| **Network partition (HA up, server up, path broken)** | page fails, nobody knows | heartbeat every N hours; a page path that reports its own failure through a different channel |
| **Disk full** | snapshots fail quietly, recorder stops, evidence degrades exactly when needed | host telemetry with a page at 80 %; retention on its own schedule; evidence written to the external volume first |
| **Power cut mid-alarm** | everything stops silently; input_boolean comes back off, so the system looks idle | UPS; on start, a "we lost power at T, here is what was happening" page |
| **Sensor dies** | invisible (the 67-hour latch, the half-battery contacts) | the availability guard: any named security entity unavailable for 10 min, or quiet for 24 h when its siblings are busy → page |
| **Backend build drift** | /opt/company is not the repo (S32, S39) | deploy by sha, record the running sha in every decision row, and refuse to learn from a build you cannot name |

---

## Round 10 — attacking the learning loop

A learning security system has a failure mode a static one does not: it can *unlearn* the alarm. Every item
below is a way that happens, with the guard that prevents it.

| # | Failure | How it happens here | Guard |
|---|---|---|---|
| 1 | **Boy who cried wolf** | the owner silences four false alarms; the system learns "arrival at 14:03 on a Sunday is benign"; the fifth time it is a burglar and the pattern is suppressed | a label must come from **evidence**, not from a disarm: a credential, a camera frame, a named person. Disarms are a weak label and must never be able to remove a rule on their own |
| 2 | **Paging fewer times is not the same as being right** | every metric a naive agent optimises is "false pages per week", which is minimised by paging never | pair every such metric with a coverage metric that cannot improve by doing less: entries covered by a credential, drills passed, sensors alive, real events paged within 30 s |
| 3 | **Overfitting one quiet week** | the shop has a weekly rhythm (closed days, Monday arrivals, delivery times); two weeks of history is enough to fit the rhythm and not enough to know the exceptions | replay every proposed change against **all** stored history, and promote only if it improves without a single lost real event |
| 4 | **Drift with no signal** | a camera is replaced at a different resolution, a phone changes, a worker leaves and their tag stays live | the feature set is versioned; a change in any input's shape (resolution, entity id, credential roster) invalidates the model and raises an owner-visible note |
| 5 | **Poisoned by the agent's own mistakes** | the agent labels a real event "customer" because it looked like one, and the label is then trusted | confidence on every label, a human-audited sample monthly, and labels never overwrite each other — a correction is a new row |
| 6 | **Silent promotion** | an "improvement" lands at 03:00 and removes a rule nobody notices | every promotion is a committed diff with a replay report attached, and any change that *reduces* firing power needs the owner's line in the record |
| 7 | **Learning from a build you cannot name** | the running backend is already not the repo (S32) | the running sha is written into every decision row; a decision from an unknown build is not learnable |

**The one-line test for the whole loop:** for any proposed change, the system must be able to show *what it would
have done differently on every past event*, and the list of real events it would have missed must be empty. If it
cannot produce that, it has not learned anything; it has guessed.

## Round 12 — economics: what accuracy is worth paying for, and what it costs to be wrong

**The two costs are not symmetric and both are real.**
- A false alarm costs attention and, more expensively, trust: the measured record is four false alarms in one
  day, and the owner has already started ignoring the channel (he reset one siren by hand and asked for the next
  one to be turned off). A system the owner does not believe is worse than no system, because it also consumes
  the belief he would need for the real one.
- A miss costs whatever is in the shop, plus the insurance argument, plus the fact that a missed event teaches
  the system nothing at all.

**The arithmetic that sets the operating point.** The doorbell alone fires about once every 28 minutes during
business hours (92 firings in 42.68 h, and 47 of them with nobody entering). At even a one-in-a-hundred
false-positive rate that is roughly half a false page a day — still too many. So **no single signal may be
allowed to raise an alarm**. The envelope must require either a door opening, or two independent corroborations
of a person inside, and the credential window removes the legitimate cases. That is not a tuning choice; it is
the only arithmetic that reaches "a few false pages a month".

**What the agent layer costs.** One cheap-tier call per event, and the estate's whole daily budget is five
dollars shared with everything else. Fifty events a day at the cheap tier is affordable; fifty at the frontier
tier is not, and it would also be wrong — the judgement that matters at 03:00 is fusion and honesty, not
eloquence. So: the on-event layer runs on the cheap tier, and only an escalation to the owner uses the smart one.

**What each stage costs in hands-on time** (my estimates, from the change set in the audit):
- the repairs that make today's alarm function at all: about ninety minutes;
- the envelope with credentials and the latch guards: about a day;
- the four record tables plus the writer: about a day;
- the department (blueprint entry, tools, autonomy entries, nightly job): about two days;
- the vision layer, if the hardware allows it at all: days, and it is the only item that needs new hardware.

---

## Round 13 — phasing, with an acceptance test that has to pass before the next phase starts

Ordered so that each phase removes a risk rather than adding a feature. No phase starts until the previous
one's acceptance test has been run and its output recorded.

| Phase | What it builds | Acceptance test (the command and the line) |
|---|---|---|
| **0 — repairs** | the six items that make today's alarm function: retry stop, self-cleaning drill, continue_on_error on the siren call, page before the siren, non-blocking loop, the doorbell term out of the hallway zone | the one-second check returns PHOENIX_EVIDENCE_OK with rc 0; a drill logs captured N image(s) and pages nobody; replaying the six historical episodes produces zero arms |
| **1 — envelope** | credential window, latch guards, bounded siren, page-first, second channel | a synthetic intrusion (a real door contact, no credential) arms within 2 s and pages within 30 s; a credentialed entry arms nothing; a siren left running stops itself at N minutes |
| **2 — record** | the four tables and the writer | every event in a 24 h window has a row; every alarm has a decision row carrying the one-line explanation that went out |
| **3 — department** | blueprint entry, L1 triage, nightly job, its autonomy entries | a week of events is labelled; three threshold proposals are replayed and their missed-event lists are empty |
| **4 — learning** | the promotion pipeline with a replay gate | one proposal is promoted and one is rejected, both with the replay attached; a deliberate bad proposal is refused |
| **5 — vision** | image classification, if R2 says the hardware allows it | person-versus-animal correct on twenty labelled frames, and the classifier is never the sole trigger |
| **6 — hardening** | non-admin token, UPS, second siren, window and maglock sensors | the token reports is_admin: false; pulling the network still pages; pulling power still sounds |

## Round 14 — migration with no blind window

The rule: **the old path keeps working until the new one has proven itself in shadow, and every step is
reversible with one line.**

1. **Shadow first.** New rules run with input_boolean.security_v2_enabled off: they compute, write a decision
   row, and take no action. For N days we compare what v2 *would* have done against what v1 *did*.
2. **Flip one behaviour at a time**, in risk order: labelling → extra channels → credential gating → the new
   envelope as the primary. Never two behaviour flips in one deploy.
3. **Both paths alarm while the flip is in progress.** A v2 rule may only *replace* a v1 rule that it provably
   subsumes on the recorded history; until then they run in parallel and a disagreement is logged, not resolved
   by the newer one.
4. **Rollback is a commit and a boolean.** Every phase is a git commit in ha-config plus a single flag; the
   flag off restores v1 exactly, and that is tested before the phase is enabled.
5. **No deploy to a live alarm without the drill.** After any change: ha core check, the one-second check, the
   silent drill, and a read-back of the logbook line. If any of the three is missing, the change is not done.

**The specific trap in this estate:** the deployed file is not always the repo file (S32, S39), and scp is not
available on either remote target. So every deploy compares sha256 both ways and the running sha is written into
the record; a decision made by an unknown build is discarded rather than learned from.

## Round 15 — observability: the system must be able to say it is alive, and prove it weekly

- **Heartbeat, every 6 hours:** a synthetic event through the real paging path, answered by the backend before
  it sends anything, recorded as a receipt. Two missed heartbeats and the owner hears about it by a *different*
  channel.
- **The one-second check:** the verify command against a known file. This single call would have caught the
  forty-hour outage; it runs daily and on every deploy.
- **The drill, weekly and self-cleaning:** runs the whole response in test mode, asserts the logbook line, and
  clears its own flags. It is the only test that exercises the ordering as well as the components.
- **A receipt per alarm, per recipient:** attempted, accepted, delivered, fetched-the-picture. Today
  "delivered" is unmeasurable and one path (Twilio accepting then failing to fetch) admits nothing.
- **One tile and one weekly line:** last successful page, last drill, sensors blind, anything queued. Silence
  means healthy only if there is a weekly "still alive, here is what I learned" line — otherwise silence is
  indistinguishable from death, which is the failure this whole audit is about.

## Round 16 — the charter, in writing

**The department may, alone:** read every signal; read and write the four record tables; add a notification
channel; call the owner's phone for a suspected intrusion; label an event with a confidence; propose a change;
replay a proposal against history; promote a threshold inside a pre-agreed band.

**The department may not:** silence a siren; disable an automation; edit configuration; widen its own autonomy;
page anyone who is not on the roster; label an event without evidence; learn from a build it cannot name.

**It escalates when:** it cannot reach a verdict within 60 seconds; the signals disagree about whether a person
is inside; a credential is used by the wrong person or outside that person's normal hours; a sensor goes blind;
or a paging attempt fails.

**The owner's reserved powers:** who is on the roster; the arming posture; any spend on hardware; and silencing
a real alarm. Everything else is the department's to run.

**The one sentence that defines it:** *the department's job is not to decide whether to sound the alarm — the
envelope does that — it is to make sure the right person knows, to explain why in one line, and to make next
week's envelope better than this week's.*

**R15, measured 2026-10-26 20:56 UTC — the one-second check, run live as a baseline for this design:**

`
POST /api/services/shell_command/phoenix_verify_evidence_files?return_response
     {"files": "/config/configuration.yaml"}
  -> returncode 0
     stdout  PHOENIX_EVIDENCE_OK /config/configuration.yaml
     elapsed 0.1 s
`

Before 14:08 the same call raised FileNotFoundError: 'for' inside the service in about a second. That is the
entire forty-hour outage, caught by a call that costs a tenth of a second and changes nothing.

---

## Round 2 — camera truth (interim, from R2 on zabz-tech)

**The single most important answer: there is no machine vision on this estate.** HA 2025.10.3, 229 components,
and `image_processing` is not among them; there is no `image.` domain at all across 1,036 entities and 32
domains. No Frigate, no DOODS, no DeepStack, no CodeProject.AI, no TensorFlow, no OpenCV, no Coral. Every
"detection" in this system is inference performed **inside the camera** and surfaced as a switch. Nothing on the
estate classifies a frame.

**And those in-camera detectors are switched off.** All twelve Dahua detection switches read off right now —
switch.cam_deserted_exit_motion_detection_2, …_smart_motion_detection, and the same pair for front hallway,
deserted interior, waiting room and Larry's exit (measured live). That is why 54 inary_sensor.cam_* entities
have produced **zero** state changes in twelve days while the Reolink doorbell fired 99 times: the detectors are
not broken, they are disabled upstream. The fix is a switch, not a purchase — with the caveat that someone turned
them off, and that reason has to be found before they go back on.

**Two corrections to the audit, both from measuring rather than reading the repo:**
- camera.cam_larry_s_exit_main_2 is **not** an empty channel: HTTP 200, 2560×1440, 300,843 B, and the OSD in the
  frame reads "Deserted House Exit". It is the same physical camera as the exit view under a second entry. Only
  cam_larry_s_interior_main is genuinely dead.
- Recorder retention is **~28 days, not 1.8**: read from the database itself on the host,
  states holds 2,335,006 rows across 26 distinct days back to 2026-09-28. Four measurements said otherwise
  because /api/logbook returns at most 24 h from the start and /api/error_log is a ring buffer cleared at
  restart — the API's window is not the database's retention. Round 8's "forgets in 44 hours" is corrected by
  that same fact: the store is deep enough to learn from, provided the labels are written down.

**Design consequences, stated plainly:**
1. A vision layer is **not** available today. It is either an add-on on a machine with a CPU to spare (Frigate on
   the Linux PC), or it is the cameras' own edge inference switched back on. Both are real options; neither is a
   config edit in HA alone.
2. Because no model can be trusted as the sole trigger (R5's second law), the vision layer's job is
   **corroboration**: it raises confidence and it names a person, it never decides alone.
3. The camera-side detectors, if re-enabled, give 54 corroborating signals for free — but their false-positive
   rate is unknown, and the 2026-09-16 note that claimed they were "verified live" was wrong, so nothing about
   them should be assumed.

---

## Round 2 (full) — camera truth: good cameras, no vision, wrong clocks

**What is actually there**, measured from the bytes (JPEG SOF markers, not entity names), fetched through
`/api/camera_proxy`:

| Physical camera | OSD burned into the frame | Stills | Bytes |
|---|---|---|---|
| Reolink doorbell (standalone, 192.168.50.231) | "Reolink Video Doorbell PoE" | 2560×1920 (and a fluent twin at **640×480**) | 605,216 / 48,185 |
| Dahua NVR ch — main room | **"Deserted House Exit"** | 2560×1440 | ~315,000 |
| Dahua NVR ch — repair bench | **"Deserted House inwards"** | 2560×1440 | 298,175 |
| Dahua NVR ch — vestibule | **"Main Entrance"** (monochrome) | 2560×1440 | 149,503 |
| Dahua NVR ch — drop-off door | **"IPC"** | 2560×1440 | 213,689 |

Five physical cameras, eighteen camera entities, four restored ghosts that 404. The entity names do not describe
the views — "Waiting Room" is the drop-off door, "Front Hallway" is the main entrance, "Control Room" is the main
room — so **a role must never be assigned from an entity name**. The pixels are good: a visitor's head in the
doorbell frame is about 310 px tall, well above what face recognition needs.

**There is no machine vision on this estate.** `image_processing` is absent from the 229 components — not the
domain, not any platform — and that is the domain every HA classifier uses. No Frigate, DOODS, DeepStack,
CodeProject.AI, TensorFlow, OpenCV, Coral, EdgeTPU. The HA host itself is a **Raspberry Pi**, so a vision layer
cannot live on it; it needs a separate box. And all 54 in-camera detectors have produced **zero** events in 30
days because their switches are off, while the doorbell's own classifier fired 99 times in 72 hours.

**The two things that must be fixed before any vision layer is worth building:**
1. **The clocks.** One automation run, three tiles, the same courier with the same parcel: doorbell 13:21:03,
   hallway 13:37:21, waiting room 13:37:26 — **16 m 18 s apart**, against a true local time of 14:44. The Reolink
   is ~67 minutes slow, the NVR ~51. Every cross-camera timeline is wrong before any model sees it.
2. **The evidence path.** It uses the 640×480 doorbell entity (307,200 px) while the parcel path uses the same
   camera at 2560×1920 (4,915,200 px) — exactly 16× worse on the one frame that would identify an intruder. Three
   roster tiles 404.

**And one finding that changes what evidence means here:** `dahua/client.py:74-92` retries a failed snapshot on
`channel-1`, then `1`, then `0`, then with **no channel at all** — which returns the first channel's frame.
So a still named for a camera that does not exist can silently be a picture of one that does, with HTTP 200 and no
error. Until that is fixed, **an evidence file name is not evidence of which camera produced it.**

**The honest ceiling, per capability:**
- person vs animal: **yes now**, doorbell only, no GPU (the pet class exists; its sensitivity is set to zero).
- vehicle: **yes now**; the class exists and fires zero because sensitivity is zero.
- direction of travel (in/out): **yes, and no GPU** — the doorbell looks out, Main Entrance looks in, so ordering
  two detections gives the answer. It is blocked purely by the 16-minute clock skew.
- person count, loitering, package vs person: **GPU box**. Package-vs-person matters most, because this is a shop
  that receives parcels — and the measured counter-example is that the doorbell called a courier holding a large
  box a "person".
- face identification: **GPU box + geometry fix + an owner decision** on storing biometrics. The pixels are
  sufficient; the doorbell's sightline is not (it sits at the bottom of a stairwell).

**Design consequence, unchanged and now better evidenced:** vision is corroboration. It raises confidence, it can
name a person, and it is never the sole trigger — because the model that misreads a hooded figure must not be the
reason the siren stays quiet, and because the cheapest failures today were logic and plumbing, not perception.

**Three details from the full R2 report that the summary above does not carry, added because each is a live
trap:**

1. **A dead evidence path that looks alive.** The `latest_doorbell_ring_*` tile family returns HTTP 200 on
   every request and has not been written since **12 October — 14 days stale**. A tile that answers 200 is not
   a tile that was written. Same class as `video_loss` never firing for a camera that has returned HTTP 500
   for 29 days: the sensors that are supposed to report "this path is dead" are themselves dead.
2. **Four of the 25 camera entities are ghosts** — `camera.cam_waiting_room_main_stale_placeholder` and three
   `_sub` siblings, all `restored: true`, all 404. They exist because HA restores deleted config entries.
   A roster built from entity names alone would happily include them.
3. **`_main` for evidence, `_sub_4` for the live wall.** All three Dahua suffixes deliver the identical
   2560×1440 still (the snapshot call hardcodes `subtype=0`), so the only argument is naming: `_main` is not
   a unique_id collision artefact and `_sub_2_2` is the one the repo documents as stream-less. But `_sub_4`
   is the entity with a real subtype-1 RTSP stream behind it, so it belongs on the wall and not in the roster.

---

## Round 3 — identity: what actually proves a person may be inside

**The measured state, before any design.** The credential set is two live RFID tags (owner, wife) and four live
PINs (admin, parent, yocheved, house access). Everything else is empty or off. The per-user system
`phoenix_access_manager` is registered in `/api/services` with `validate_pin / add_user / delete_user /
modify_user / buzz_in`, but its roster sensor is a 404, and its only caller — the keypad event handler automation
— is switched off, so `phoenix.valid_pin` **never fires** and no PIN can currently disarm anything. Two workers'
tags resolve to `unknown` because the role map lists only three people, so both grant branches are dead code. The
"credential log" is a 255-character rolling string holding six entries; every new badge-in destroys the oldest.
And the log that holds the real record — the logbook — has a thirty-hour hole on 23 October.

So the honest summary: **the building has two people it can name and a half-dozen codes it cannot attribute**, and
no durable record of either.

**The model that fixes it — three tables in the authority database**, not in Home Assistant:

- `subject` — a person **or** an explicit role (house access, tenant, generic worker). A shared code is a role
  subject with a name, not an anonymous string; that is what lets the record say "house access code, 14:03"
  rather than "unknown".
- `credential` — `subject_id`, type (pin | tag | phone | beacon), `value_hash`, `issued_at`, `revoked_at`,
  `UNIQUE(type, value_hash)`. Never the plaintext: entity state is readable by any token and persisted for
  thirty days, and `mode: password` masks the field, not the state.
- `entry_event` — append-only: timestamp, subject, credential, door, side (in/out), result (granted / refused /
  unknown), and the raw actor (which device reported it). One row per credential event.

**The design change this forces, and it is an improvement on Round 5.** Rule 2 of the envelope said "any door
opens with no credential in the preceding 120 s". With `entry_event` that becomes far stronger and no longer a
guess:

> *A door opening with no **granted entry_event** within the preceding N seconds is an alarm, regardless of any
> presence flag.*

Why it is better: a timer boolean can only say "something badged recently"; an event row says **who**, at which
door, in which direction, and whether it was granted. It also survives a restart, it is auditable after the
fact, and it makes the disarm path depend on evidence rather than on inferred occupancy. The "credential window"
in C31 is therefore an implementation detail of this rule, not the rule itself.

**What must be true before the gate can be trusted** (each is a defect found today):
1. One live credential maps to one subject, and the role map is data-driven rather than three hardcoded names —
   otherwise Klein's and Montrose's tags stay dead (S70).
2. Revocation is read *at the door* and sweeps every copy: the deadbolt slot, the `input_text` helper, the role
   map. Otherwise revoking a worker leaves a working code in one of three places.
3. The audit survives the recorder purge, which means it lives in `entry_event`, not in a 255-character string
   and not only in the logbook (S67, S68).
4. No plaintext PIN or tag in entity state or in logs. `__init__.py:118` currently logs the wrong PIN in clear
   (S69) and must be deleted before the keypad automation is ever enabled.
5. The two credential-free paths are closed: the HA event bus (any token can forge
   `esphome.access_control_keypad_entry`) and MQTT `zigbee2mqtt/Smart Switch/set` (S72). Neither is the ESPHome
   radio link, which is encrypted on every committed device config.
6. The record knows about doors that open by design when de-energised: both maglocks are fail-safe, so a power cut
   opens them silently (S73). No software model should pretend otherwise; the design should say so and cover it
   with a power-loss event.

**The one decision this round cannot make for the owner, recorded here rather than asked:** whether house access,
the tenant and the generic worker code stay **role** subjects, or each holder gets their own credential. That
single choice determines whether the log can ever say *which* worker came in — and it changes what "covered by a
credential" means in every metric the department will report.


---

## Round 4 — ground truth: what actually happened, and what a learner would have learned

Fifteen intrusion episodes in thirty days, thirteen of them inside a window where every signal records. Labelled
from cross-signal evidence, not from the logbook's opinion:

| Label | Count | What it means |
|---|---|---|
| worker arriving | 7 | the largest class by far; in five of them the alarm armed **0–27 s before the door opened** |
| passer-by, no entry | 3 | a person at the door, no door contact for the whole armed window |
| owner arriving + infrastructure flap | 1 | six sensors went `unavailable` and came back in the same second, four times in 3 m 38 s, each one re-arming |
| unknown | 1 | five doorbell firings in 52 s, someone stood at the door ~50 s and left |
| drill | 1 | test mode, page refused by the backend |
| **unauthorised entry** | **0** | in the whole month |

**That zero is the most important measurement in this document.** A learning system trained on this window
learns one thing: *the alarm is a worker-arrival detector with a six-second handicap*, and the 43,323-second
episode is what that handicap costs. Every design decision after this round has to be judged against it — the
system was never wrong about a burglar, and was wrong fourteen times about the people who work there.

**The mechanism, measured across thirteen episodes.** Trigger→arm is 6 s in twelve of them, because that is the
grace window. Arm→door-opened is 0–27 s in five. The doorbell sees a person 5–15 s before they touch the door, so
the re-check lands precisely in the gap between "someone is visible" and "the door opens". And every real alarm
ended the same way: `everyone_away → off` from presence credit. **Never by PIN. Never by a human pressing
anything.** Thirteen of fifteen ended by the presence system noticing someone entitled to be there.

**The false alarm that was not a person at all.** One episode was a sensor-availability flap: six independent
security entities went `unavailable` and restored within the same second, four times in under four minutes, and
each restoration re-armed the alarm. No door opened. This is a failure class the design did not have: **a
restart or a Zigbee hiccup can sound the alarm**, and nothing distinguished it from an intrusion.

**The numbers the fusion model has to beat.** Over 108 doorbell clusters in the dense window: 62 % are followed
by a door contact within 300 s, 38 % are not; at the honest 30-second horizon, 58 % have no door contact at all.
While the shop was believed empty there were 19 clusters — 12 with a door, 7 without — and those 19 produced 11
alarms because the grace window and the single-shot flag suppressed the rest. So the baseline is *doorbell alone,
62 % precision at five minutes*, and any claim that a new model is better has to be shown against that number.

**The missed signal nobody reads.** The standalone mmWave produced 130 on-intervals totalling 11.5 hours and
overlapped a presence credit **3 times (2 %)**; 45 % of its intervals contained no entry and no credit at all.
The control-room hub mmWave overlaps a credit 48 % of the time. Neither is an alarm input. So the one sensor that
would say "a human is in this room" is not wired to anything, and the presence logic disagrees with it almost
always. It is a missed signal, not a false-alarm source — and "neither" is not proof of a ghost: a person sitting
still produces no door and no credit.

**The taxonomy the department will label with** (each one assignable from signals that exist today):

`OWNER_ARRIVAL` · `WORKER_ARRIVAL` · `TENANT_ARRIVAL` · `CUSTOMER_ENTRY` · `DELIVERY_NO_ENTRY` ·
`PASSER_BY_NO_ENTRY` · `UNKNOWN_PERSON_NO_ENTRY` · `UNAUTHORISED_ENTRY` · `FORCED_ENTRY` ·
`INFRASTRUCTURE_FALSE` · `DRILL` · `SYSTEM_ERROR` · `NO_ANSWER`

Two rules that fall out of the data: **label the outcome, not the sensor** (every label above is a statement
about a person and a door; `zone_hallway_active` collapsed five inputs into one and destroyed the information
needed to learn), and **`NO_ANSWER` is a real label** — per the measurement rule, "no signal" and "a signal that
never resolved" are different sentences and must never be recorded the same way.

**And the fields that must exist before any of this is learnable**, from the episodes themselves: the *leaf*
trigger input; trigger→arm, arm→entry and arm→credit in seconds; the basis on which each presence boolean was
set; `acknowledged_at` and `ack_channel` (today "nobody noticed" and "noticed and ignored" are literally the same
observation); page attempted / status / recipients / error; `script_aborted_at_step`; an availability snapshot at
trigger time (which would have labelled the flap episode automatically); a canonical `door_id` (two sensors report
the same physical door and fire within the same second on 246 edges); a snapshot manifest with both the camera's
OSD time and the file's mtime, because they disagree by 67 minutes; and a `recorder_gap` marker, because a
30-hour hole exists and nothing says so.


---

## Round 6 — the fusion model, built on the measured numbers

**The honest starting point: there are no positives.** Thirty days, fifteen alarms, zero unauthorised entries. A
supervised classifier trained on this data has an empty positive class — its precision is undefined and anything
it "learns" would be a model of workers arriving. So the order is fixed: **rules first, then a model of what
normal looks like, and only then a classifier** once there are labelled positives (or a one-class novelty model,
which is a different and weaker claim).

**Tiering the evidence, from the measurements.** Each signal gets a role, not a weight, because a weight implies
a precision nobody has measured yet:

| Tier | Signals | Role |
|---|---|---|
| **A — a fact** | three door contacts; a granted `entry_event` | one of these decides on its own |
| **B — a veto** | a credential granted within N seconds of the door | removes the alarm, never raises it |
| **C — corroboration** | doorbell person, camera human detectors (if re-enabled), mmWave presence, the Echo playing | raises priority and confidence; never triggers alone |
| **D — noise** | `device_tracker` inside a 100 m zone, BLE beacon advertisements, `media_player` state | may only *support* a Tier A/B decision, never stand alone |

That table alone forbids every false alarm in the thirty-day record: every one of them was a Tier C or D signal
acting on its own, because the zone fused an outside doorbell into an interior trigger (S55).

**The two rules that replace the current logic.**

1. **Entry rule (the alarm).** A door contact opens **and** no Tier-B credential was granted in the preceding
   N seconds → alarm. N is 120 s, chosen from the measured sequence (doorbell 5–15 s before the door, credential
   1–3 s after it) with a factor of safety, and it is a number the department may tune inside a band, not a
   constant chosen by whoever edits the YAML.
2. **Presence rule (the escalation).** Any Tier C signal agrees that a person is inside **while the shop is
   believed empty**, and no Tier-B credential has been granted since the last disarm → alarm with a higher
   priority. One Tier C signal on its own is not enough; the rule needs two, or one plus a door that opened and
   did not close.

**What the model adds, given it cannot yet classify an intruder.** It can learn the *shape of normal*, which is
where the information actually is in this data set:
- **Arrival signature**: for each door, the distribution of `door→credential` latency, per person, per hour.
  A worker who normally badges 2 s after opening and today opens with no badge is a deviation the rule already
  catches; a worker who normally arrives at 08:40 and arrives at 23:20 is a deviation only a model catches.
- **Who is expected**: the department knows the schedule, the roster, and the caller history. "A person at the
  side door at 23:20 on a Saturday" is unusual for this business, and unusual is free information.
- **Base rates per hour**: 92 doorbell firings in 43 hours, concentrated in business hours. A firing at 03:00 is
  a different event from a firing at 14:00, and today they are identical to the alarm.
- **The surprise score**: distance from the learned distribution of legitimate entries, computed from features
  that already exist (time, day, door, credential, sequence, duration, whether the shop is expected open). It
  **never alarms on its own** — it sets the priority of a page and the question the department asks.

**The acceptance numbers, stated in advance so they cannot be fitted afterwards:**
- false alarms at the rule level: **≤ 1 per week** (currently ~3.5 per week, all false);
- every genuine door-without-credential caught: **100 %**, because that is a rule, not a statistical decision;
- time from door to first page: **≤ 30 s**;
- time from page to a human's acknowledgement recorded: measured for the first time ever, and reported weekly.

**One number that must be honest about the data:** with zero positives in thirty days, "detection rate" cannot be
estimated. The system can only claim *coverage* (which doors, which signals, which hours) until a positive
exists. That is a limitation to state in the charter, not to paper over with a confusion matrix built on
fifteen false alarms.

## Round 18 — scenario replay: the fifteen historical episodes through the proposed logic

The same thirteen densely-covered episodes, scored by the Round 6 rules with N = 120 s, door contacts only in
Tier A, and no doorbell term in the zone. This is the test the design has to pass before it is built.

| Episode | What happened | Old rule | New rule (rule 1 + rule 2) | Verdict |
|---|---|---|---|---|
| A | worker, door at +301 s | armed, 5 min of strobe | no door at trigger time → **no alarm**; door open + credential 1 s later → veto | correct, silent |
| B | worker, GPS credit | armed, 5 min | no door → no alarm | correct, silent |
| E1 | passer-by, door 957 s later by a worker | armed 16 min, 1,855 strobes | no door → no alarm | correct, silent |
| E2 | passer-by at 23:19 | armed 1 h 47 min, 12,508 strobes | no door → no alarm | correct, silent |
| E3 | worker, door at +0 s | armed, 0 s | door opens; credential 1 s later → **veto** | correct, silent |
| E4 | worker, door at +9 s | armed 9 s | same | correct, silent |
| E5 | six sensors flapped, no door | armed 222 s | no door; availability snapshot → `INFRASTRUCTURE_FALSE` | correct, silent, and now labelled |
| E6 | worker, door at +3 s | armed 5 s | veto | correct, silent |
| E7 | passer-by, worker 63 min later | armed 63 min, 7,308 strobes | no door → no alarm | correct, silent |
| E8 | worker, door at +27 s | armed 28 s | veto | correct, silent |
| E9 | person at the door 50 s, never entered | armed **12 h**, 20,001 strobes | no door → no alarm | correct, silent |
| E10 | worker, door at +5 s, siren after disarm | armed 7 s, siren 2 min | veto; and the page runs before the siren anyway | correct, silent |
| E11 | drill | 70 s, no page | drill still suppressed | correct |
| **synthetic** | door opens, no credential, nobody expected | — | **rule 1 fires on the door edge**, page within 30 s | the case it exists for |

**Thirteen of thirteen historical episodes produce no alarm, and the one case the system exists for still
fires.** That is what a correct design looks like on this data — and it is worth being blunt about why it is so
easy: every one of the thirteen false alarms came from a sensor that was not a door.

**Two caveats, stated rather than buried:**
1. The replay is a rule trace, not an execution. The real test is the shadow run in Round 14 — the new logic
   computing decisions in parallel for two weeks while the old one still acts.
2. It proves the rules do not fire on *these* episodes. It cannot prove they will not fire on a Tuesday nobody
   has seen yet, which is exactly why the false-alarm budget (≤ 1 per week) is a monitored number rather than a
   claim.


---

## Round 17 — red team the finished design

A second adversarial pass, now that there is something to attack. Each row: the attack, what it defeats, and
whether the design as written survives.

| # | Attack on the NEW design | Defeats | Survives? |
|---|---|---|---|
| 1 | **Tailgate a credential.** One badge, two people through one door. | the veto — a granted event exists, so the door is "explained" | **No, by design.** The veto explains the *door*, not the *people*. That is why rule 2 (presence) exists: a second person inside with no credential still trips Tier C. The honest limit: if the second person stands still and the mmWave is the only witness, it may not. |
| 2 | **Use a shared code.** House access, tenant, generic worker. | attribution — the record says "a role", not a person | **Partly.** The alarm still fires correctly; the *log* cannot say who. This is the owner decision recorded at Round 3. |
| 3 | **Time the forced entry inside the veto window.** Force a door within 120 s of a legitimate badge. | rule 1's veto | **Yes, survives** — the veto is keyed to a *specific door event* and duration, not a global timer, so a second door or a second opening is a new event with no veto. This is why the rule is an event row and not a 120-second boolean (Round 3). |
| 4 | **Cut the network** so the credential cannot be written to `entry_event`. | the veto — every legitimate entry becomes an alarm | **Fail-safe, by design.** The alarm fires; that is the correct direction. The cost is a false alarm during an outage, which is the price of never silently passing an entry. |
| 5 | **Poison the learner** by arriving at odd hours until "odd hours" is normal. | rule 2's surprise score | **Partly.** The score never alarms alone and never vetoes; it only sets priority. A successful poisoning costs attention, not detection. |
| 6 | **Socially engineer the department.** "This is the owner, silence it." | the charter | **No** — the charter forbids the department silencing anything. Silence requires a credential, an owner instruction through a recorded channel, or the envelope's own timeout. |
| 7 | **Replay-overfit.** The design was tuned on thirteen episodes and looks perfect on them. | credibility | **The real risk on this list.** Mitigation is structural: the replay is a rule trace, the shadow run is the test, and the acceptance numbers were written before the build (Round 6). |
| 8 | **A single Tier C signal while someone is still.** | rule 2 | **Yes, misses it.** A person standing still in a room covered only by a doorbell is not detected. Stated as a coverage limit, not hidden: the fix is the mmWave wired in (it currently is not) or a camera-human detector switched on. |
| 9 | **Blind the doorbell** and enter through a door with no contact. | everything | **Yes, defeats it.** This is why the window/glass/maglock coverage gap (S47) is a structural finding, not a nice-to-have. No software design fixes an unsensed opening. |
| 10 | **Wait for the agent to be down.** | the department's judgement | **No effect on the alarm** — the envelope is local and complete. The cost is a slower, dumber explanation, not a missing siren. That is the whole point of Round 5. |

**The three that survive are all structural — shared credentials, no coverage on some openings, and a person who
stands still — and none of them is a software problem.** That is the honest shape of the result: the software
defects are fixable, and what remains needs hardware, policy, or both.

## Round 19 — cost, effort and risk ledger

**Effort** (hands-on, mine, in the order of Round 13's phases):

| Phase | Work | Estimate |
|---|---|---|
| 0 | the six repairs that make the current alarm function | 90 min |
| 1 | envelope: credential veto, latch guards, bounded siren, page-first, second channel | 1 day |
| 2 | the four record tables and the writer | 1 day |
| 3 | the department: blueprint entry, L1 triage, nightly job, autonomy entries | 2 days |
| 4 | the learning pipeline with a replay gate | 1 day |
| 5 | vision, if wanted | 2-4 days, and it is the only phase needing hardware |
| 6 | hardening: non-admin token, UPS, second siren, window/maglock sensors | 1 day plus the hardware lead time |

**Direct cost** of the non-labour items: a Coral or a small GPU box for vision, window/glass contacts, a UPS, and
a second audible device. All of it is a purchase decision, and none of it is needed for Phase 0-4.

**The risk register** — what could go wrong in the build, worst first:

| Risk | Likelihood | Impact | Mitigation already designed |
|---|---|---|---|
| The new envelope is quieter than the old one and a real intrusion is missed during the transition | low | catastrophic | shadow mode for two weeks; the old path keeps acting until the new one matches it on every recorded episode |
| The credential veto is defeated by a shared code | high | moderate | the owner decision at Round 3; the alarm is unaffected, only attribution |
| The department's learning removes a rule it should have kept | medium | high | no change may reduce firing power without a replay showing zero missed events, and the owner sees the record |
| The token swap breaks every agent path at once | high | high | a maintenance window, a second token issued before the first is revoked, and a rollback line in the record |
| The system is tuned to the thirteen episodes and fails on a new pattern | medium | high | acceptance numbers fixed in advance; weekly false-alarm and miss reporting |
| Nothing proves the page arrives, as today | certain if we skip it | catastrophic | the heartbeat, the receipt row, and one real page the owner agrees to beforehand |

## Round 20 — the consolidated design, and the questions

**In one paragraph.** Home Assistant keeps a small, deterministic envelope — six rules, no model, no network —
that fires on a door opening without a granted credential, on presence inside while the shop is empty, and on a
duress code, with a bounded siren and two independent ways to reach a human. Every credential use, every alarm,
every decision and every label is written to four tables in the authority database, so the machine has a past.
The security department — which does not exist yet — then does the three things a static automation cannot: it
explains every event in one line using all nine signals, it adds force and channels rather than deciding whether
to alarm, and it learns the shape of normal for this shop and tunes the context numbers inside bands, with a
replay gate that refuses any change that would have missed a real event. Vision is corroboration and arrives
last, because the failures that cost the owner two days were logic and plumbing, not perception. And the whole
thing is judged by four numbers that are reported weekly: false alarms, time to page, time to a human's
acknowledgement, and the count of sensors that are blind.

**What it costs to be wrong in either direction, one line each:** a false alarm costs belief, and belief is the
only currency an alarm has; a missed alarm costs the shop. The design is tuned so that the first is at most
weekly and the second is a rule rather than a probability.

**The questions, in the order they will be asked — one per message, and not before this round is closed:**

1. **The credential veto and shared codes** — do house access, the tenant and the generic worker stay *roles*, or
   does every holder get their own credential? It decides whether the log can ever say *which* person entered.
2. **The mother on the intrusion page** — `D240` says she was meant to be; the live configuration says she is not.
3. **The agent token** — a non-admin HA user and TOTP on the owner account, in one maintenance window.
4. **Vision** — after the envelope and the record, on the Linux PC with an accelerator, or not at all.
5. **Hardware coverage** — windows, glass-break, the `maglock` contact, a UPS, a second siren. The one place
   where money changes the answer.


---

## Round 3 addendum — the subject model, DECIDED by the owner (2026-10-26)

Owner's words: *"the only people who have access are me, my parents and my wife, and a master guest code for
now."*

So the `subject` table has exactly **five rows**, and this replaces the fourteen PIN helpers and six tag helpers
that exist today:

| subject | kind | credentials | note |
|---|---|---|---|
| Eliyahu | person | his own PIN **and** his own tag | already live (4-digit PIN, 7-digit tag) |
| Mother | person | her own PIN and/or tag | currently no credential exists for her at all |
| Father | person | his own PIN and/or tag | currently no credential exists for him |
| Wife | person | her own PIN **and** her own tag | already live (4-digit PIN, 7-digit tag) |
| Guest | **role** | one master code | explicitly shared, must rotate and must expire; today `house_access_pin_auto_reset` is **off**, so a "master guest code" would never change |

**Consequences, each a concrete change rather than an opinion:**
- `worker_klein`, `worker_montrose`, `worker_bachrach`, `tenant`, `customer`, `drop_off`, `family`, `guest_pin`,
  `yitz`, `parent_2`, `full_family` — every one of those helpers becomes **retired**, not merely empty. Eleven
  PIN helpers and four tag helpers stop existing, and the two dead `worker_klein` grant branches in
  `access_control.yaml:320-332,378-388` are deleted rather than left unreachable.
- The RFID role map (`access_control.yaml:52-66`) is rewritten against five rows instead of three names, which is
  what makes mother's and father's tags resolvable at all.
- The guest code is a **role** with a revocation date, and its rotation automation is switched back on — that is
  the only thing that makes "master guest code" safe to share.
- The alarm's veto (Round 6, rule 1) can now name every legitimate entrant exactly, which is the whole point of
  the owner's answer: *the record can say which of four people opened the door, or that it was the guest code.*

**The conflict this creates, and it is measured, not hypothetical.** Seven of the thirteen instrumented episodes
were a **worker arriving** while the shop was believed empty — and in every one of them the door opened with no
credential event: E3 at 11:28:38, E4 at 12:28:02, E6 at 16:59:18, E8 at 21:38:51, E10 at 14:03:26. If workers
have no credential under this policy, then rule 1 fires on every one of those arrivals — correctly by the letter
of the rule, and wrongly in fact.

So one question has to be settled before the veto can be built, and it is the owner's.

---

## Round 3 addendum II — the ghost worker (owner, 2026-10-26: *"montrose hasn't worked here in months"*)

That single sentence explains thirteen alarms. The presence path
`presence_architecture.yaml:287-313` credits `phoenix_worker_is_here` when
**`zone_control_room_occupied` goes on AND `device_tracker.monty` is `home`**. That tracker still reports `home`,
so every time the room sensor moves, the system marks *a person who left months ago* as being at work — and
`everyone_away` goes false, which is the disarm condition.

`GET /api/states/device_tracker.monty` → `home` right now. `input_boolean.phoenix_worker_is_here` was `on` at
14:15 today for the same reason, which is why the alarm has been unable to arm since. **The thing that disarmed
your alarm today was a ghost.**

**Consequences, decided (not asked):**
1. **No workers.** The entire worker presence path is retired: `phoenix_passive_arrival_bluetooth_worker`,
   `automation.phoenix_v2_worker_auto_arrival_gps`, `phoenix_worker_is_here`, the Bachrach/Klein/Montrose PIN and
   tag helpers, and the `device_tracker.monty` condition. Seven of thirteen episodes were labelled "worker
   arriving" by this path and **none of them was a worker** — they were somebody opening a door with no
   credential, plus a ghost credit arriving seconds later.
2. So `everyone_away` collapses to: **NOT `user_is_here` AND NOT `guest_mode`** — two inputs instead of three,
   and the one that caused every false alarm is gone.
3. The seven "worker arriving" episodes are re-opened as **UNKNOWN_PERSON / unbadged door**, not
   WORKER_ARRIVAL. That is the honest label, and it changes the replay: the new rule *would* fire on those doors,
   because nobody badged at them.

**What that leaves, and it is the next question:** in five of those episodes a door opened with no credential
event within any plausible window, and the arrival was credited by occupancy seconds later. Either the door is
simply unlocked at those times, or somebody opened it with a key the system cannot see. Under the current veto,
a door opened with a key during a quiet five minutes is an alarm — which is a false alarm on the owner himself.

---

## Round 6 correction — the perimeter is not a door. The owner's setup, and what it does to the rules.

Owner, 2026-10-26: *"the outside door is always open cuz that hallways is 24 6 pickup and dropoff."*

That is a fact about the building, and it invalidates the trigger model rather than tuning it. Measured
consequences, from R1's 28.76-day inventory:

| Signal | Measured | What it means under the real setup |
|---|---|---|
| outside door reed | **113 edges, 83 % duty, three open stretches of 168.6 h / 142.9 h / 167.9 h** | the door is *supposed* to be open — this is a public hallway, not a perimeter. I logged the 168-hour stretch as "a latched door blind for 67 hours"; R1 logged it as "one stuck magnet blinded a zone for three weeks". **We were both wrong the same way: a signal that never changes was telling us the setup.** |
| outside door opens | 118 in the window, **12 credentialed** | 106 "unbadged entries" that were never entries — people using a pickup counter |
| interior maglock door | **open 57 % of the time, longest single episode 82.9 h** | the shop door stands open most of the day, so its edge carries almost no information, and it pins `zone_control_room_active` on, which deafens every "not already active" condition |
| `zone_hallway_active` | 102 edges, fed by the doorbell (outside) plus two door contacts | a zone that describes a **public space**. It should never have been an intrusion trigger, and it produced 13 of 13 alarms |
| credential → door opens | **median 1.4 s** prior (n=73) | the badge happens *before* the door, so a rule that waits for a credential after a door opens waits for something that has already happened |
| doorbell person → door opens | median **8.0 s** prior | the camera sees a person ~8 s before the door moves — the leading indicator, not the event |

**So rule 1 of the envelope is withdrawn in its door-edge form.** With a public hallway and a shop door that
stands open, there is no door edge that means "an entry". The corrected rule is presence-based:

> **Rule 1 (corrected).** A person is detected **inside the shop** while the shop is expected closed, and no
> credential has been granted since the last time it was known empty → alarm.

Where "inside" is R1's fusion, which is the only part of this that survives contact with the data:

```
INSIDE = hub mmWave OR BLE mmWave OR any door opened in the last 600 s OR credential in the last 600 s
EMPTY  = INSIDE false, continuously, for 600 s
ARM    = EMPTY and no door and no credential for 1800 s
```

**Why that fusion and not a door:** the two mmWave sensors are genuinely independent radios (ESPHome LD2410 and
a BLE HLK-LD2410) and they agree — hub 97.6 occupied hours, BLE 77.3, union 98.7, intersection 76.2, Jaccard
**77.3 %**, and 78.1 % of the hub's occupied hours are also BLE-occupied. Two radios agreeing is what makes a
*level* trustworthy; one at 11–14 % duty is not. Night phantoms between 02:00 and 06:00: 9 hub, 14 BLE, **0 door
contacts** — about one false "inside" every two to three nights, median 63.6 s, absorbed by the 600 s hold.

**The arithmetic that justifies replacing the incumbent:** `phoenix_everyone_away` declares the shop empty
**9.77 times a day** (281 in 28.76 days, median 11.3 min, 43.2 % duty) and that produced 15 arming episodes. The
proposed latch, simulated on the same series, declares empty **0.63 times a day** with **zero** re-occupations
within five minutes — **15.5× fewer opportunities to arm wrongly**, for the same coverage.

**What it costs, stated rather than hidden:** the only interior body sensor is one LD2410 in the control room;
the waiting room and the shop floor have no occupancy sensor at all. So "inside but outside the control room" is
covered only by the door/credential latch — up to ten minutes of undetected presence after the last door event.
That is the gap to close with hardware, not software.

**And the number that decides the remaining tuning:** 286 door-open edges, only 87 (30 %) with a credential in the
prior 300 s. Under the corrected rule the alarm population is the opens with no credential **and** no radar in
the prior 600 s — **24 in 28.76 days, 13 of them outside 09:00-20:00, so 0.45 a day**. Removing that last
half-a-page-a-day means staff and family badge *in* as well as out — which is a policy choice, not an
engineering one.


---

## Round 6 correction II — the actual geometry, from the owner's video (IMG_1254.MOV, 42 s, 1920×1080)

Frames extracted at two-second intervals and read directly (ffmpeg → 21 stills). What they show, in order:

- **The public hallway**, with a white door carrying the shop's own signage — *"PLEASE DO NOT BLOCK OR PARK IN
  DRIVEWAY"* and *"PHONETECH · Your All-in-One Tech Center · 24/6 Drop-Off & Pick-Up Box · 732.655.2355"* — a
  lever handle and an electronic keypad deadbolt. This is the **shop exterior door, seen from the hallway**.
- **A second door on the other side** with a **mechanical push-button lock** (the classic Simplex/Kaba style, no
  battery, no radio) and a knob: this is the **apartment door on the left**.
- **Inside the shop**: a door frame with a white contact sensor and its magnet, a "LIABILITY" waiver taped to the
  door, and the bench with a meter and a cylindrical device on it.

So the owner's sentence is the correct model: *the hallway is barred by the apartment door on the left and the
shop exterior door on the right.* The street door stands open, the public walks into the hallway, and the only
two things that lead anywhere are those two doors.

**This corrects the perimeter a second time, and the second correction is the one that matters for the rules.**

| Perimeter | Sensor | Credential? | Consequence for the envelope |
|---|---|---|---|
| **Shop exterior door** (right) | contact on the frame, verified in the video | yes — electronic keypad, plus a tag | the credential veto applies here exactly as designed: sealed door + badge before it opens |
| **Apartment door** (left) | contact (`external_control_room_door_sensor`) | **appears to be a mechanical push-button lock — no electronic event at all** | the veto *cannot* apply here. The rule for this door can only be "opened while expected empty", with the false-alarm cost carried by the emptiness model, not by a credential |
| the hallway itself | doorbell person, doorbell motion | none | a public space. A person in the hallway is normal; only a door opening is evidence |

**So the design has two perimeters with two different rules, not one rule with two doors:**

1. **Shop door:** opens with no credential in the preceding N seconds while the shop is expected empty → alarm.
   This is the rule the owner's keypad/RFID answer supports, and it is the only door where a credential exists.
2. **Apartment door:** opens while the apartment is expected empty → alarm. No credential can be waited for,
   because there is none to wait for. Here the anti-false-alarm work is entirely in the emptiness model (the
   two-radar latch from R1) plus the door's own `on` duration — one measured 17.6-hour latch on this door.

**And one more thing the video settles:** the sensors are visibly mounted on the door frames, so the two contacts
are physically correct; what was wrong was never the sensors, it was reading a public hallway as an interior.

**Open, and it is a factual question rather than a design one:** whether the apartment door really has only a
mechanical lock. If it does, no credential event will ever exist for that side and the design must not pretend
otherwise; if there is a keypad behind the plate, the same veto applies to both doors and the design simplifies.


**Correction to the geometry section, from the code rather than from the video.** The apartment door **does** have
a keypad, and it is programmable from Home Assistant — I asked a question the repository had already answered.

`scripts.yaml:772-792`: `ui_set_kwikset_pin` publishes `{"pin_code":{"user":<slot 1-30>,"pin_code":"<pin>"}}` to
`zigbee2mqtt/Apartment_Door_Smart_Lock/set`. `access_control.yaml:2160-2169` mirrors the admin PIN into slot 1 and
the generic worker PIN into slot 2 whenever those helpers change. And the lock reports `action_source_name`
(`keypad` / `manual` / `rf`) plus `action_user`, so a keypad entry on that door arrives as a **named event**:
`Apartment Deadbolt unlocked by Boss`.

**So both perimeters have credentials, and the veto is a single rule after all:**

> **A door opens with no granted credential in the preceding N seconds while its zone is expected empty → alarm.**

Two credential sources feed it, and they are different mechanisms that must both be wired to the same table:
- **shop door** — ESPHome keypad/RFID event → compared against the `input_text` PIN helpers;
- **apartment door** — Kwikset keypad via zigbee2mqtt → `action_user` slot + `action_source_name`.

**Four defects in that second path, all fixable and all found while reading it:**
1. The slot→name map is hardcoded to three names (`access_control.yaml:2179`: 1 Boss, 2 Worker, 3 Guest, else
   `User {{ user_id }}`). Under the owner's five-subject policy the map must be data, not code, and slot 7 must
   stop being "User 7".
2. Only two slots are ever populated by automation (admin → 1, worker → 2). Five subjects need five slots and an
   issuer, a revocation date and an audit per slot.
3. `sensor.0x002446fffd0a4705_pin_code` publishes **the last PIN used, in plaintext**, as an entity state that the
   recorder keeps for 28 days. Any token can read it; it should never be a state.
4. There is no recording of a *failed* keypad attempt on the lock — the invalid-attempt counter is wired to the
   ESPHome keypad path only, so the apartment keypad can be guessed at without the lockout ever engaging.

