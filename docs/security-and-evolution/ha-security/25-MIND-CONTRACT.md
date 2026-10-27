# The mind's contract: what the agent is given, what it must return, and when it is not allowed to think

**Rounds 41–46.** `10-ARCHITECTURE.md` names four roles; this is the interface a builder can implement and a
reviewer can attack. It exists because "the AI decides" is not a design — an event bundle, an output schema
and a refusal path are.

---

## 1. The event bundle — everything the Sentinel may see, and nothing else

One object per **episode** (deduplicated, not per state change):

```json
{
  "episode_id": "ep_20261026_2301_a41",
  "opened_at": "2026-10-26T23:01:12Z",
  "leaf_trigger": {"entity": "binary_sensor.phoenix_control_room_interior_door_contact",
                   "from": "off", "to": "on", "seq": 918273, "recorder_gap": 0},
  "door_id": "shop_door",
  "signals": [ {"entity": "...", "state": "on", "at": "...", "role": "A|B|C|D"} ],   // role per Round 6 tiers
  "credential": {"used_within_s": null, "system": null, "slot": null, "subject": null, "confidence": 0.0},
  "expected": {"expected_empty": true, "reason": "shop hours end 17:00; no credential since 17:04",
               "source": "schedule+credential", "confirmed_by_owner": true},
  "posture": "closed",
  "subject_hypotheses": [ {"subject": "unknown", "basis": "none", "confidence": 0.0} ],
  "history": {"similar_episodes_30d": 4, "of_which_labelled_benign": 4, "last_label": "courier"},
  "frames": [ {"camera": "camera.cam_front_hallway_main", "sha256": "…", "at": "…", "osd_time": "…",
               "mtime": "…", "skew_s": 962} ],
  "build_sha": "…",
  "delivery": {"page_attempted": true, "page_result": "sent", "siren_state": "pending_entry_delay"}
}
```

**Three deliberate absences**, each for a reason that cost something to learn:
- **No phone presence.** `device_tracker` is Tier D and is the ghost that disarmed thirteen alarms. It is
  not in the bundle at all, so no model can be persuaded by it.
- **No raw free-text from the world.** Entity names, notification strings and frame text arrive with a
  provenance tag and are never concatenated into an instruction slot (`research/E` rule 4).
- **No images unless asked for.** Frames are referenced by hash; the Investigator fetches the bytes when the
  episode warrants it. This keeps the Sentinel cheap and keeps the vision cost bounded.

## 2. The output — a verdict and a level, never an action

```json
{
  "verdict": "ALARM | NO_ALARM | ESCALATE",
  "avs_level": 0,
  "confidence": 0.0,
  "reason_one_line": "Shop door opened 23:01:12, no credential in 120 s, shop closed since 17:00, no body signal inside",
  "subject": {"id": "unknown", "basis": "no credential", "confidence": 0.0},
  "recommend": {"channels": ["page_owner"], "call_after_s": 90, "ask_owner": false},
  "considered": [ {"signal": "…", "value": "…", "weight": "supports|contradicts|silent"} ],
  "label_proposal": {"label": "unknown", "evidence": "none", "confidence": 0.0},
  "escalate_to_investigator": true
}
```

**The word "action" does not appear, on purpose.** The agent returns a *verdict* and a *recommendation*; the
code decides what runs, and `constitution.py` refuses anything on the forbidden list (`40-SAFETY.md` §4). A
model that could return `{"action": "siren_off"}` would be a model that can be talked into it.

**`considered` is mandatory.** A verdict without its evidence is not auditable, and the record must be able
to answer *"what did it know"* six months later.

## 3. When the mind is not allowed to think

These bypass the model entirely, and the code enforces it:

| Condition | What happens | Why |
|---|---|---|
| Duress credential | silent siren, page with the duress payload | a duress code means someone is being coerced; a model's opinion is irrelevant |
| Two signals classified Tier A disagree (a door open and closed within 1 s on one contact) | `NO_ALARM` + an infrastructure note | that is a reed switch flapping, not a person |
| The bundle is incomplete (`recorder_gap=1`, or the frame fetch failed) | `ESCALATE` with the gap named | silence must never be read as evidence |
| The model is unavailable, over budget, or > 60 s late | **deterministic triage**: rules + roster + last 30 days. The record says `judged_by: fallback` | the alarm is not allowed to depend on a provider |
| `avs_level` claimed higher than the evidence supports (e.g. 4 with no duress credential) | clamped down by code, and the clamp is logged | a model can inflate; the scale cannot |

## 4. The fallback triage, written out — because it is what runs when the model does not

It is thirty lines, not a model, and it must be good enough that a provider outage is a degradation rather
than an outage:

1. Door edge with no credential in 120 s and `expected_empty` → **level 3, page, siren at entry-delay expiry**.
2. Two Tier-C body signals with `expected_empty` → **level 3**.
3. Credential used → **level 0**, record only.
4. Anything with `recorder_gap` → **level 2**, page, and say the record has a hole.
5. Otherwise → **level 1**, digest.

## 5. What is logged for every turn (the only way to tell "wrong" from "injected")

`episode_id`, model id and version, prompt hash, the full bundle hash, every tool call with its result,
every frame hash shown to the model, token counts, latency, verdict, level, and the clamp (if any). Without
this, a bad call and a poisoned call look identical in the record — and `research/E` rule 14 is explicit
that this is the only way to distinguish them.

## 6. How the mind is judged — the golden set, before any live use

The fifteen historical episodes (`from-zabz-tech/reports/R4-ground-truth.md`) plus one synthetic positive,
run as a fixed test:

| Expected | Count | Pass condition |
|---|---|---|
| `NO_ALARM` on the 13 instrumented benign episodes | 13 | 13/13, and the reason names the actual benign cause |
| `NO_ALARM` on the drill | 1 | 1/1, labelled `drill` |
| `ALARM` (level 3) on the synthetic door-with-no-credential | 1 | page-worthy, reason correct, subject `unknown` |

**A prompt change that moves any of those is a regression until proven otherwise**, and the same replay gate
applies as to a rule change (`research/D`). Note the honest limit: this set has **zero real positives**, so
it measures *specificity only*. It cannot measure whether the mind would catch a burglar — that claim stays
unsupported until a real event exists, and the design must keep saying so.

## 7. The Investigator: the same contract, one tier deeper

It receives the same bundle plus: the frames themselves, the last 30 days of similar episodes with labels,
the subject registry, the shop schedule, and the owner's own words about the building. It returns the same
schema plus a **drafted page body** (subject to the owner-voice rules) and a **`why` paragraph** for the
record — never sent to him except as one line.

Its rule, which the Sentinel does not need: **it may ask him a question.** "Shop door, no badge, this you?"
with a picture, carrying a nonce. That is the only place in the system where a model's words reach a human
in real time, and it is why the answer must be authenticated (`40-SAFETY.md` §2, attack 2).
