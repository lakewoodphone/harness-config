# Safety: what the mind may never do, and the holes found in my own design

**Round 12–17.** Attacks on the architecture in `10-ARCHITECTURE.md`, cheapest and most damaging first.
Each row ends in a *mechanism*, not a promise, because a promise in a prompt is not a control.

---

## 1. The invariant everything else rests on

> **An alarm may be suppressed only by evidence that an authorised human is there — never by a belief
> that things are probably fine.**

Split into the two things that are constantly confused:

| Act | What it is | Who may do it | What it needs |
|---|---|---|---|
| **Alarm** | the building asserts "someone is here who should not be" | the reflex, alone | a door edge, or two independent body signals, or a duress code |
| **Suppress** | the building stops asserting it | only evidence | a credential granted at that door, a recorded owner instruction, or the reflex's own entry-delay expiring into a human's answer |
| **Explain / escalate / add force** | the mind's whole job | the mind, freely | nothing but the record |

### 1.1 The hole I built, and the fix

In the first draft the mind *wrote* `input_boolean.security_expected_empty`. That is a single boolean
that, once wrong or once written by a confused or injected agent, **disables the alarm for the whole
building**. It is exactly the "agent may never silence" law, broken by a side door.

**Fixed by construction.** The mind may not write a suppress-by-belief boolean at all. HA computes
`security_expected_empty` itself from inputs it can check, and the mind may only supply *facts with a
provenance*:

```
expected_empty = NOT( credential_occupancy            # a credential was granted at a perimeter door
                                                    #   within T, and no uncredentialed door edge since
                    OR owner_said_im_here             # a recorded instruction, with its message id
                    OR schedule_open_confirmed_by_owner )  # today's hours, owner-confirmed, not inferred
POSTURE (agent-written) may only RAISE severity, never lower it.
```

Consequences that make it safe: with the mind dead, `expected_empty` falls back to the schedule and the
credential path — both local, both deterministic. With the mind malicious, the worst it can do is make
the building *loud*.

### 1.2 The siren entry delay — the standard answer to "let a legitimate person cancel it"

The design does not need an agent-held siren hold (which is the same disable-by-belief hole in miniature).
It needs what every monitored alarm already has: **an entry delay**. The building's current grace window
is 6 s, chosen for a specific false-alarm class; the standard is 20–30 s.

```
door edge, no credential  →  PAGE immediately (step 0)          [unchanged from today's fix]
                          →  transmit delay 30 s (CP-01 abort), then siren after ENTRY_DELAY
                             = 30 s default, band 30 s – 4 min  [HA, deterministic]
                             cancelled only by: a credential, a duress code, or the owner's
                             recorded answer carrying the page's nonce; cancel window ≥ 5 min
                          →  if cancelled: the siren never fires, the record says who cancelled, and
                             the page is superseded by a "cancelled by <subject>" note
```

The timings are **not mine**: they are ANSI/UL-style alarm-panel defaults, SIA **CP-01** — exit 45–255 s
(default 60), entry 30 s – 4 min (default 30), abort/transmit delay 0–45 s (default 30, with entry + abort
≤ 60 s), cancel window ≥ 5 min, and *swinger shutdown* after 2 trips on a zone (range 1–6). Adopting a
published standard instead of inventing numbers is the cheaper way to be right, and it gives the owner a
document to check the install against (`research/E-adversarial-practice.md` rules 8–9, sources there).

This gives the mind the *capability* the owner asked for — "ask me instead of screaming at me" — with a
mechanism that cannot be left stuck, because the delay is a `delay:` in HA that always expires into the
siren, and an unanswered page always leaves the siren armed.

---

## 2. Attacks on the new design

| # | Attack | Cost | Would defeat | Mechanism that stops it (not a promise) |
|---|---|---|---|---|
| 1 | **Talk the mind out of it** — put text in the frame, or set an entity name to "ignore previous instructions" | free | the mind's judgement | the mind cannot suppress; §1.1 makes belief unable to lower anything. Text from an image or an entity is *data*: parsed by `content_sandbox.parse_untrusted_content` (exists), never concatenated into an instruction slot |
| 2 | **Answer the ask falsely** — a stolen phone, or a spoofed SMS saying "it's me" | one phone | the siren | the ask's answer must carry the **nonce from that page** and arrive from a rostered number; a wrong or missing nonce neither cancels the siren nor writes a label — it is itself a security event |
| 3 | **Stale presence** — leave a phone inside, or keep `device_tracker.monty` alive | free | `expected_empty` | presence never grants suppression (§1.1); the ghost is a *finding*, and the design deletes trackers from the presence path entirely |
| 4 | **Shared code** — one PIN, several people | social | attribution only | the alarm is unaffected; the record says "role: guest", and the Auditor reports credential reuse outside normal hours |
| 5 | **Poison the learner** — arrive at odd hours until odd is normal | patience | the surprise score | the score never alarms and never suppresses; it only sets priority. A poisoned model costs attention, not detection |
| 6 | **Deny by noise** — 50 doorbell firings to train the owner to ignore pages | free | the owner's attention | pages are rate-limited by *episode*, not by signal; one page per episode, with the reason; and the ask channel is capped (≤3/day) so it cannot become the new noise |
| 7 | **Silence the mind** — kill the Sentinel, or the model provider | one kill | judgement | the reflex is complete without it; `security_sentinel_alive` going stale is itself rule 6 (a page), and the schedule/credential fallback keeps `expected_empty` correct |
| 8 | **Cut the tailnet proxy** — the shop desktop is the only path to HA | one shutdown | the mind, not the reflex | stated as a structural weakness (§8 of the architecture); fix is a Tailscale node on the HA host |
| 9 | **Steal the HA token** — owner+admin, no MFA, plaintext | one file read | *everything*: the automation can be disabled, the siren silenced, credentials forged | not fixable in design; it is the top hardening item (non-admin user + TOTP + `https` + a token that cannot call `automation.turn_off`) |
| 10 | **Unplug the HA box** | one plug | the reflex | UPS + a heartbeat that notices the *absence* of the heartbeat (the company's liveness timer already runs at 1-minute cadence — measured `company-api-liveness.timer` 2026-10-26 21:20Z) |
| 11 | **Enter through what has no sensor** — windows, the back, the maglock door | free | coverage | stated, not fixable in software (S47); the Steward reports the coverage map weekly so the gap is never a surprise |
| 12 | **Wait for Yom Tov** — the owner is away, the alarm fires, nobody answers | patience | the response | an **away mode**: a designated responder, a longer escalation ladder, and a rule that an unanswered page during a declared absence escalates to a call, then to the second contact |
| 13 | **Exhaust the queue / the budget** | free | the mind | one episode = one row (dedup key), a hard per-hour turn budget, and a deterministic triage fallback when the budget is gone — the reflex is untouched |
| 14 | **Make the record lie** — inject a false label | needs a path into the writer | the training set | labels are append-only with a source and confidence; a correction is a new row; the human-audit sample is monthly and adversarial |

---

## 3. The fail-safe ladder, in one table

| Condition | `expected_empty` | Siren | Page | Record | Owner is told |
|---|---|---|---|---|---|
| normal, mind alive | computed | on entry-delay expiry | step 0 | all four tables | on an alarm |
| mind dead < 15 min | computed | unchanged | unchanged | reflex-local only | weekly, plus immediately if it coincides with an alarm |
| mind dead > 15 min | **schedule + credential only** (conservative) | unchanged | unchanged | reflex-local | "mind down" page |
| HA restarting | frozen at last value | n/a | the company notices the heartbeat | gap marker written | "HA restarted at T" |
| power cut | n/a | n/a | on boot: "we lost power at T; last state was X" | gap marker | yes |
| model provider down | unchanged | unchanged | unchanged | "judged by fallback rules" | inside the page |
| internet down | unchanged | unchanged | LAN push if on the LAN, else queued | local file, backfilled | on reconnect |

**The one rule that orders this table:** every row must leave the building *at least as alarmed* as the
row above it. No degradation may make it quieter.

---

## 4. What the mind is allowed to touch, as a code-level allow-list

`app/security/constitution.py` — one dict, checked before every action dispatch, so that "an agent
decided" can never be a path around policy:

```
ALLOWED = {
  "read:signals", "read:record", "read:frames", "read:calendar", "write:decision",
  "write:label", "page:owner", "page:roster", "call:owner", "ask:owner",
  "notify:companion", "escalate:tier", "recommend:change", "set:posture_up",
}
FORBIDDEN = {
  "suppress:alarm", "disarm", "silence:siren", "unlock:any", "buzz_in",
  "turn_off:automation", "edit:ha_config", "rotate:owner_credential",
  "add:subject", "remove:subject", "page:third_party",
}
```

`buzz_in` deserves its own line: today `script.buzz_in_strike` opens a door by publishing one MQTT
message, and the only trace is a relay state (S72). **A model must never be able to open a door.** Opening
is a human act with a credential, or nothing.

### 4.1 Two things the industry refuses, which this design must also refuse

- **Model-initiated dispatch to police.** No dispatch-capable product in the survey does this, and the
  standards put verification in *supervising-station personnel* (`research/E` rule 18). The mind may
  recommend a call; a human makes it.
- **Treating an accuracy figure as a security argument.** At this site's base rate — 14 alarms in 30 days,
  **zero** of them real — a model that is 95 % sensitive and 95 % specific has a **positive predictive value
  of about 50 %**: half its pages would be false (`research/E` §2.5, arithmetic there). The honest sentence
  is *"we cannot estimate detection rate, because there are no positives"*, and it must appear wherever a
  number would otherwise be quoted.

---

## 5. The three questions I would ask this design if I were the owner

1. **What happens at 03:00 when I don't answer?** The siren fires at entry-delay expiry, the page goes at
   step 0, and if no answer in 5 min the Investigator escalates to a call, then to the second contact. The
   mind never waits for a human before the alarm exists.
2. **What stops it from crying wolf again?** The measured cause of all 13 instrumented episodes was a
   Tier-C/D signal acting alone (R1, Round 18 replay: 13/13 silent under the new rules). The reflex now
   requires a door edge or two independent body signals, and the credential veto removes the legitimate
   cases.
3. **What can it still not see?** Windows, the back, the maglock door (no contact), and a person who
   stands perfectly still in a room covered only by the doorbell. Those are hardware and money, not code.
