# Operating model: states, escalation, autonomy, budget, KPIs

**Rounds 18–26.** What the system does at 03:00, and what it does at 14:03 on a Tuesday, expressed so a
builder can code it and the owner can check it.

---

## 1. The building's state machine

One state variable, always known, written to the record on every transition. Everything else (posture,
siren, page) is derived from it plus the reflex.

```
                    ┌──────────── MAINTENANCE (a human declared it; siren disabled, page still works)
                    │
  EMPTY_ARMED ──door edge, no credential──► ENTRY_DELAY ──expires──► ALARMING
       │                                        │
       │                                        └─credential / duress / owner-with-nonce──► OCCUPIED_NORMAL
       ├──credential used──────────────────────► OCCUPIED_NORMAL
       ├──two independent body signals─────────► ALARMING (priority 2: presence without entry)
       └──schedule says open + owner confirmed─► OCCUPIED_NORMAL

  OCCUPIED_NORMAL ──last credential + no presence for T──► EMPTY_ARMED
  OCCUPIED_NORMAL ──door opens with no credential────────► ENTRY_DELAY (visitor)
  ALARMING ──credential / owner-with-nonce / reset───────► RESOLVED ──► EMPTY_ARMED or OCCUPIED_NORMAL
  any state  ──sentinel heartbeat lost > 15 min──────────► DEGRADED (posture frozen at closed)
  any state  ──HA restart────────────────────────────────► DEGRADED until reconciles, then previous
```

**Rules the machine enforces by itself:**
- `ALARMING` is the only state in which the siren sounds, and it always has a maximum duration.
- `ENTRY_DELAY` cannot be extended by the mind; a page already went out.
- `MAINTENANCE` is the only state in which the siren is suppressed, it requires a **human** to declare it,
  and it auto-expires (default 2 h) so a forgotten maintenance mode cannot become a back door.
- Every transition writes a `security_decision` row with the previous state, the trigger, and the reason.

---

## 2. The escalation ladder

Two axes decide what the owner experiences: **how confident** the evidence is, and **what hour** it is.
A system that pages him at 03:00 the way it pages him at 14:00 is a system he turns off.

| Evidence | Waking hours (his own rhythm, learned — not assumed) | Night |
|---|---|---|
| Door edge, no credential, **no other signal** | page (picture + one line); siren after entry delay | page immediately, then **call** after 90 s if unanswered; siren at entry-delay expiry |
| Door edge, no credential, **+ body signal inside** | siren at entry delay, page at step 0, ask-the-owner at the same moment | siren immediately (no ask), page, call at 90 s |
| Credential used, **out of that subject's normal hours** | a note, not a page ("father entered at 23:20") | a page only if it is outside *all* subjects' hours |
| Credential used, normal | silence; a line in the nightly summary | silence |
| Door propped > N minutes, nobody inside | one page, once per episode | a note, not a page |
| Duress credential | **silent** siren, page with a different payload and no callback prompt | same, plus a call to the second contact |
| Sensor dark / battery | the weekly page | never |
| Nothing | nothing | nothing |

**The ask channel** (the mind asking him instead of assuming) is capped at **3 a day**, only during waking
hours, only in the "no other signal" row, and only while a page is already out. An unanswered ask is not a
permission; it is an escalation.

---

## 2a. The vocabulary: AVS-01 levels, adopted instead of invented

The monitoring industry already has a scale for exactly the question this ladder answers — *how much does
anybody actually know about this event?* It is TMA **AVS-01**, and adopting it costs nothing and buys a
shared vocabulary with every installer, insurer and monitoring centre (`research/E-adversarial-practice.md`
rule 10, source there):

| AVS-01 | Meaning | What this system does |
|---|---|---|
| **0** | No call for service — the signal is explained, or known to be benign | record only; morning digest |
| **1** | Verified, but limited or no additional information | record + digest; **never a 03:00 page** |
| **2** | Verified, with audio/video or a named human confirmation | page, waking hours |
| **3** | Verified intrusion — multiple independent signals agree | page + siren at entry-delay expiry, any hour |
| **4** | Duress or life-safety | silent siren, immediate page with a distinct payload, call |

**No level, no page.** Every page carries its level and the evidence that justifies it — which is the same
requirement as the one-line reason, expressed in a number a human can sort by. The measured support:
**85–99 % of alarm signals need no intervention at all**, and each repetition of an ignored reminder drops
acceptance by about **30 %** (sources in `research/E` §2 and §3). A scale that keeps Level 0/1 out of his
phone is the difference between an alarm he reads and an alarm he mutes.

Two consequences that are easy to miss:
- **A level change is itself a reason to page.** Level 1 → 3 while he is asleep is a page even though the
  first notification was not.
- **Rate-limit by event identity, not by notification.** One door, one track, one page per window —
  repeated identical pages are the documented mechanism of desensitisation.

---

## 3. Autonomy: what each action costs in trust

The estate's ladder is L0 (shadow) → L4 (autonomous). **The design doc's Round 7 claim that unknown actions
default to L4 is stale**: the deployed build sets `UNCLASSIFIED_ACTION_LEVEL = L1_SUGGEST`
(`/opt/company/app/services/autonomy.py:302`, and line 618 records *"This branch used to return
L4_AUTONOMOUS"*). Verified on the authority 2026-10-26. So an unregistered security action cannot execute
autonomously today — which is the correct default for this desk, and the opposite of what the prior document
says. Every security action is still registered explicitly, because the registration is what grants the
power, not the model's confidence:

**And a constraint that binds the whole mind layer:** `UNSAFE_ACTIONS_ENABLED=false` and
`HA_CALL_SERVICE_REQUIRES_APPROVAL=true` are set on the authority (read 2026-10-26), so **every Home
Assistant service call becomes an owner-approval task**. The company can *read* the alarm and cannot *fire
the siren*. That is not a bug to flip — it is the right default — but the design must not pretend the mind
can actuate: pages, calls, asks and record writes go through the company's own services; anything that
touches HA hardware needs a dedicated, registered, narrowly-scoped path (stage 4), never the general
`ha_call_service`.

| Action | Level | Why |
|---|---|---|
| read signals / frames / record | L4 | reading harms nothing |
| write a decision row | L4 | the record is append-only and this is its purpose |
| page the owner | **L3** | a page costs attention; the reflex may also page, and the reflex is not bound by this table |
| page the roster (wife, parents) | **L2** | it spends other people's attention, and the roster is partly the owner's decision |
| ask the owner a question | **L3**, capped 3/day | the whole "dependent on him" feature, but bounded |
| call the owner's phone | **L2** | louder than a page; escalation only |
| set posture (raise) | L3 | can only make the building louder |
| set posture (lower) | **L1** — proposal to the owner | this is the one that could silence, so it is never autonomous |
| declare MAINTENANCE | **forbidden** | a human-only act |
| anything on a lock, strike, maglock, buzz-in | **forbidden** | a model must never open a door (`40-SAFETY.md` §4) |
| silence a siren / disarm | **forbidden** | ditto |
| propose a rule/threshold change | L4 to propose, **human to promote** if it reduces firing power | `30-LEARNING.md` |

---

## 4. Budget, and the arithmetic that makes it a non-issue

Measured inputs. **The "$5/day" figure this estate repeats is folklore** — the ledger says otherwise:
`model_usage` over eight days is **$9.62–$37.78/day** (mean ≈ $21), the code's own default is
`DEFAULT_DAILY_LIMIT = 10.0` (`app/services/llm_budget.py:35`), and `AI_GATEWAY_DAILY_BUDGET_USD` is **not
set** in `/opt/company/.env`, so the default applies (`research/B-vision-stack.md` §1, raw query there).

Two more corrections that change the arithmetic: **Google is excluded at the provider level**
(`AI_GATEWAY_EXCLUDE_PROVIDERS=google`), so every Gemini id — including the cheap vision ones in the price
table — is **uncallable**; and the callable vision model is `gpt-4o-mini`, whose per-frame cost at
2560×1920 measures **$0.000205** because the API resizes to 1024×768 (a 640×480 frame bills the same).

| Work | Volume/day (measured or bounded) | Cost/day |
|---|---|---|
| Sentinel triage per episode | ~33 events/day measured (person firings 69/day; the gate is stricter) | **$0.01** |
| Investigator escalations | ≤ 3 | **$0.01** |
| Vision corroboration, cloud VLM | ≤ 20 frames on detector-gated events only | **$0.004** |
| Watchman nightly + Steward hourly + Auditor weekly | 1 + 24 + 1 | **$0.04** |
| **Total** | | **≈ $0.07/day — about 0.7 % of the $10 default limit, 0.3 % of actual spend** |

That is the important conclusion, and it inverts the instinct: **cost is not the constraint, so the design
should buy more evidence per event, not less.** The one genuine budget risk is a lane that inspects **every
frame**: always-on cloud inspection of five cameras at 5 fps costs **$247.86/day**. The detector must be
local and the VLM must only look at what the detector already flagged — a decision worth 43,573 frames/day
of headroom.

---

## 5. The four KPIs, and why each is paired

Every one of these can be gamed alone, so each is reported with its pair:

| KPI | Definition | Paired with |
|---|---|---|
| **False pages / week** | pages whose label is not `owner`/`worker`/`customer`/`passer-by` with evidence | **Coverage**: % of door edges with a credential, and % of episodes paged within 30 s |
| **Time to first page** | physical edge → successful send, median and p95 | **Delivery**: per-recipient receipt rows, not "ok: true" |
| **Time to a human's answer** | page → first recorded human action | **Answer rate**, because a 3-minute median over 10 % answers is a lie |
| **Blind sensors** | named security entities `unavailable`/`unknown`/silent | **Drills passed**, because blind-and-quiet looks like healthy |

A week with **zero** of everything is a failure, not a good week: it means either nothing happened or the
system stopped recording — and the Auditor must distinguish those two in one sentence.

---

## 6. The away case — the one this building will actually face

He is away for Shabbat and Yom Tov, and the shop empties. An alarm then goes to a phone in a place where
he will not answer it, which is worse than no alarm because it *looks* covered.

So the system needs **declared absence**, entered once (conversationally: "I'm away Tuesday–Thursday"):

- the schedule's "open" is overridden to closed for the whole window (so no false alarms from openings
  that will not happen);
- the escalation ladder gains a rung: unanswered page 5 min → **call** → unanswered 10 min → **second
  contact** (a named human, not the roster in a group text);
- the Steward's checks tighten (heartbeat every 15 min, door propped → page);
- and the weekly page states, plainly, *"you were away, here is what happened"*.

The roster question (who the second contact is, and whether his mother is on the page) is his, and it is
already open as S29.

---

## 7. What "the company manages it" means on an ordinary day

So that this is a system he can feel, not a claim:

- **07:00** — the Steward's morning line: building empty, all doors closed, 2 cameras healthy, 1 sensor at
  41 % battery, the shop door contact has been open 3 times since midnight (normal for this door).
- **12:31** — the shop opens on schedule; posture flips; nothing pages.
- **14:03** — a person at the doorbell, no door edge: **a note in the record, no page** (this is today's
  alarm, silenced by design — it was a Tier-C signal acting alone).
- **18:20** — the shop door opens with no badge: page with the frame and the one-line reason. He answers
  "that's me, forgot my tag" with the nonce: siren suppressed, label written, and the Watchman gets a fact
  it can use ("the owner forgets his tag on Tuesdays").
- **23:10** — the nightly summary: 3 credential entries, 1 episode, 0 false pages, 1 ask unanswered.
- **Weekly** — one page: what it learned, what it changed, what is blind, what it wants to buy.

If any of those five does not happen, the system is not done, regardless of what the tables say.
