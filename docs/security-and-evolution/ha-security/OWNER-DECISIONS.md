# Owner decisions — the shop's security rebuild

**2026-10-26 · ZABZ-YOGA.** Everything I can do without you is done. These are the rest, in the order they
unblock work. Each one has what I read, why it is yours, my recommendation, and the single decision needed.

---

## Where the build stands, in six lines

- **Running on the authority, all supervised and self-checking:** `security-listener` (Home Assistant websocket
  → record), `security-sentinel` (events → episodes → rule verdicts), `security-agent` (a model verdict beside
  the rules), `security-health.timer` (every 15 min), nine record tables, a replay corpus of every documented
  episode, a promotion gate, a scorecard, a label tool, a weekly digest, and a 7-case composed self-test that
  currently passes 7/7.
- **All of it is shadow.** Nothing writes a `security_action`, nothing pages, nothing touches a siren or a lock.
- **Nothing has happened at the building** since the record went live: 4 rows, all listener markers, 0 episodes,
  0 decisions. That is honest emptiness, not success.
- **The alarm is still broken exactly as it was:** it disarms for anyone who walks in, and the keypad that would
  fix it has been severed since 2025-12-16.
- **Two proposals are written and unapplied**, with exact diffs and acceptance tests:
  `PROPOSAL-stage1-credential-and-ghost.md` and `PROPOSAL-stage2-cp01.md`.
- **The one thing that is genuinely yours:** I will not touch a live alarm at this hour, or change what a keypad
  press physically does, without your word. That is decision 1, and every other decision below is smaller.

---

## 1. The four reversible calls — the one word that unblocks the building

**What I read.** `automation.phoenix_keypad_event_handler` is **off**, last triggered **2025-12-16**. Everything
downstream is on and has never fired. The presence path standing in for it is fed by a departed worker's GPS:
`phoenix_v2_worker_auto_arrival_gps` fired `21:06:07.422Z`, and `phoenix_extreme_intrusion_disarm` fired
`21:06:07.627Z`. At 22:2xZ `worker_is_here` was still `on` with every presence signal off, so the building
cannot arm.

**Why it is yours.** One of the four makes a keypad press physically **open a door**, and all four change what
disarms your alarm.

**My recommendation.** Apply all four, next time you are at the shop. Measured on the corpus: **without a
credential signal the new rules false-alarm on 10 of 12 legitimate entries; with one, 0 of 12** and they still
catch the synthetic 03:00 intrusion.

**Decision needed:** when — at the shop, or remotely now.

---

## 2. Who gets woken up

**What I read.** Live roster is your number plus two others (`+1848…`), while decision `D240` says your mother
was meant to be on it. In the page code, `ok = all(...)` across recipients, so one refusal marks the whole page
failed.

**Why it is yours.** Your family's sleep and their phone numbers.

**My recommendation.** Three tiers, not a blast: you always; your wife for a level-3 alarm and for away-mode
escalation; your parents only as the away-mode backup and only if they agree to a 3 am call. Per-recipient
results, success if anyone got it.

**Decision needed:** who is on which tier, and whether your parents will take that call.

## 3. The tenant's code

**What I read.** Slot 11 (Tenant) is live and written by `apartment_deadbolt_codes.yaml` (2026-10-25, never
rotated). Decision `D7429` (2026-10-18) states the expected roster as *"zero tenant"*.

**My recommendation.** If the tenant is still there, keep the slot and register them as a subject with their own
hours, so their entry is *expected* rather than tolerated. If not, retire it as a revocation, never a delete.

**Decision needed:** does the tenant still have access?

## 4. Who owns the 03:00 decision when you are away

**What I read.** You are away for Shabbat and Yom Tov and the shop empties; an alarm then reaches a phone you
will not answer, which looks covered and is not.

**My recommendation.** A declared-absence mode entered in one message, adding two rungs: unanswered page at
5 min → call; unanswered at 10 min → the tier-2 contact.

**Decision needed:** who is the away-mode contact, and do they know they are it.

## 5. Vision — the only item that needs money

**What I read.** No vision exists today. `zabz-tech-linux` (i5-11400 iGPU) runs a detector at 14 ms a frame —
about 71 fps against the 25 your cameras produce — so local detection is free at the margin. The blocker is
that `zabz` is not in the `render` group. Coral buys nothing at this camera count. Cloud vision is about
$0.0002 per event.

**My recommendation.** Local Frigate + OpenVINO on `zabz-tech-linux`, after stages 1–5, corroboration only,
never the sole trigger. Buy Frigate+ only if you want the parcel/package class.

**Decision needed:** local-only, and whether you want the packaged-detection subscription.

## 6. The agent token

**What I read.** `HA_TOKEN` is owner+admin, no MFA, plaintext, plain http, on at least two hosts. And
`ip_ban_enabled: true`, threshold 5, bans with no expiry — five bad-token attempts from the proxy would cut
every cloud-to-HA path at once.

**My recommendation.** A non-admin HA user for agents, TOTP on your own account, HTTPS on the LAN, in a window
with the new token proven before the old one is revoked.

**Decision needed:** the window, and whether TOTP on your own login is acceptable.

## 7. Coverage — what money fixes that code cannot

**What I read.** Contacts on two doors. Nothing on the windows, the back, or the maglock door. Both maglocks are
fail-safe, so cutting power unlocks them. One audible device, no UPS.

**My recommendation, in order:** a contact on the maglock door; a UPS for the HA box and the siren; ground-floor
glass; a second audible device that is not the Mac.

**Decision needed:** which of the four, and roughly when.

## 8. The frozen office box

**What I read.** `secratary` is the rollback anchor and is not dormant: five timers firing, a 23 GB database
written today, `/` at 99 % with 5.3 GB free.

**My recommendation.** Decide what it *is*: a maintained cold standby, or retired with its database copied to
the authority first. "Frozen but still writing" is the current state and it is not one of the two.

**Decision needed:** standby, or retire.

## 9. How much the company may do to the building

**What I read.** `UNSAFE_ACTIONS_ENABLED=false` and `HA_CALL_SERVICE_REQUIRES_APPROVAL=true`, so every HA
service call already needs an approval task. Unknown actions default to `L1_SUGGEST`, not L4. But the company's
action surface still includes `ha_call_service` and a `buzz_in` that opens a door.

**My recommendation.** Adopt the registered list: read everything, page you, ask you, add channels, raise
posture, write the record — and never unlock, buzz, silence, disarm, or call the police. Remove `buzz_in` from
the company's surface, or gate it behind a live owner instruction.

**Decision needed:** accept the list, and does `buzz_in` go entirely.

## 10. The 188 automations

**What I read.** At least 188 automation blocks and 997 Jinja expressions; the security-relevant part is small,
most of it is access control, climate and dashboards. Access control is also the part that has never caused a
false alarm.

**My recommendation.** Leave everything except the intrusion path alone.

**Decision needed:** confirm access control stays as it is.

## 11. What the company costs per day

**What I read.** The estate repeats "five dollars a day". The ledger says **$9.62–$37.78/day over eight days,
mean about $21**; the code default is $10 and `AI_GATEWAY_DAILY_BUDGET_USD` is not set, so nothing enforces
either number. The security lane adds about seven cents.

**My recommendation.** Set the ceiling deliberately — twenty-five — so a limit that is currently exceeded on
five of eight days means something again.

**Decision needed:** the ceiling, and whether it is enforced.

---

## 13. Should the system be allowed to text you at 3 a.m.?

**What I read.** security_action holds **zero rows**: the reflex sounds the siren and the mind records its verdict, but **nothing sends a message**. The mechanism exists and is proven — the company's paging endpoint answers in 170-471 ms, sms_log shows 4,507 sends — but no code path connects a level-3 decision to it. That is deliberate: paging is outbound, and the standing rule is that nothing goes out without your word.

**Why it is yours.** A false page at 3 a.m. costs belief, and belief is the only currency an alarm has. Who gets woken, and on what evidence, is not mine to decide.

**My recommendation.** Enable paging for **level 3 and above only** (a door with no credential while the building is expected empty; two independent body signals; duress), to you alone first, with the picture and the one-line reason, and only after a week in which the shadow record shows no level-3 false alarm. Not to your family until you have seen that week. Also decide the night rule: does level 3 page you at 03:00, or wait for 07:00 unless it is duress? My answer: it pages at 03:00 — a level 3 that waits until morning is not a security system — but that is a decision about your sleep.

**Decision needed:** enable paging at level 3 to you only, or keep it recording-only until more history exists.

---
## What I decided myself (recorded so the reasoning survives)

- **The agent supplies facts; HA computes the alarm.** The mind can never write a suppress-by-belief boolean.
- **AVS-01 levels and CP-01 timings**, adopted from the standards rather than invented.
- **A credential disarms, presence never does.**
- **Record before learner**, and `inconclusive` is never rendered as `passed`.
- **The model may never act** — its output schema has no `action` field.
- **The security department was connected, not created** — it exists on the authority with 32 departments.
- **The replay gate refuses a change that misses a real event**, demonstrated by refusing the tempting
  "treat a missing credential as benign" rule, which drove false alarms to zero while silencing the one real
  intrusion in the corpus.

## What happens the moment you answer decision 1

I apply the four calls, watch one real keypad entry land in `entry_event` with a name on it, re-run the 7-case
self-test, and then the alarm disarms on a credential instead of a ghost. Stage 2's diff is written and can go
in the same window.
