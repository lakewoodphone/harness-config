# The security system — everything to discuss, in one place

**2026-10-26 late · ZABZ-YOGA.** Prepared after the rebuild went live. We go through this one item at a time,
not top to bottom in one sitting.

> **STATUS 2026-10-27: Q1 IS ANSWERED, AND IT RE-RANKS THIS DOCUMENT.** The alarm is wanted, but the thing he
> actually wants is **the record** — every person who came, a picture or video of them, when they came and when
> they left — and that ranks **above** burglary, which he does not fear in that neighbourhood. So the build order
> in Part 5 is re-ranked below, observation before alarm, and the engineering consequence is written out in
> `55-OBSERVATION-FIRST.md`. **This document was ordered alarm-first; it is no longer.** The next items are Q3 and
> Q9, not D1.
**Where it stands, in five lines.** The alarm arms and disarms on a credential instead of a ghost, and that
survives a restart. The siren fires thirty seconds after the alarm regardless of the cameras and stops itself at
fifteen minutes. A listener, an episode engine and a model verdict run in shadow, recording everything and
paging nobody. Identity works end to end on a real event: a keypad event lands with a name on it. The system
tonight **notices, judges and records** — it does not yet tell you anything.

---

# Part 1 — Questions only you can answer

These are facts, not choices. Every one of them changes what the system should do, and I would rather ask than
assume.

## Q1. What are we actually defending against?

A system built against burglary is not the same as one built against a person you know, or against a robbery
while you are standing there, or against fire. I have been designing against *an unauthorised entry while the
building should be empty*, because that is what the old alarm tried to do. The other threats need different
answers — different sensors, different responses, sometimes different law.

**What I need:** your ranking. Burglary when closed, insider (staff, tenant, family, ex), robbery while open,
package theft, vandalism, fire/flood — which are real for this building and which are noise?

> **ANSWERED 2026-10-27.** Burglary protection is wanted but is not the fear — *"it's a pretty secure
> neighborhood, I'm not so scared of that."* What he wants first is **extreme tracking**: *"I want to know every
> person who came and want a little picture or video of them. I want to know when they came, when they left. And
> very good tracking of everything that ever happened there is more important to me even."*
>
> So the ranking is: **1. a complete, pictured, timestamped record of every person and every entry; 2. the
> intrusion alarm** (keep what was built — a credential disarms, presence never does); **3. the rest**, including
> fire/flood, which nothing in this design currently covers and which is a different product (sensors, not
> cameras). Insider and tenant cases are not ranked as threats but they are unavoidable as *identity*: the record
> cannot answer "who" without them, which is why Q8 and D10/D11 are now load-bearing rather than tidy-up.
>
> The consequence is not a preference, it is an inversion of this document's priority: every stage that makes a
> person appear in the record with a likeness and a correct clock now outranks every stage that tunes the alarm.

## Q2. When it is real — who responds, and how fast?

Tonight an alarm produces a siren and, if we enable paging, a text to you. Then what? Do you drive over? Is there
a neighbour or a staff member closer? Do you want the police called — which in most towns means you calling, not
the system — and would you want the system to *recommend* that in one tap? The answer decides how the escalation
ladder is built.

**What I need:** who, in order, and roughly how many minutes until a human is physically there at 2 in the
morning.

## Q3. Is the apartment occupied at night?

This is the biggest unknown in the design and I have been guessing. If someone sleeps behind the shop door, then
"the building is empty" is never true at night, and the reflex has to distinguish *shop empty* from *building
empty*. If nobody is there, the whole building is one perimeter.

**What I need:** who sleeps there, on which nights, and whether the answer changes with the seasons or Yom Tov.

## Q4. What are the shop's real hours — and which days?

Measured: the hallway is a public 24/6 pickup-and-drop-off corridor. What I do not have is *your* hours: when the
shop is open, which day it closes, and whether Friday is short. The system's sense of "expected empty" is built
on this, and right now it is built on nothing.

**What I need:** open hours, the closed day, and whether the hours are the same every week.

## Q5. Who legitimately enters when nobody is watching?

Cleaner at 6am, a delivery left inside, a staff member opening up, the tenant, a family member. Each one is a
person who will trip a system that does not expect them. The kindest design is to *expect* them: a window, a
credential, a known schedule.

**What I need:** the list, with times.

## Q6. What is actually at risk overnight?

Cash in the drawer, phones and laptops in for repair, tools, the safe? The number matters because it decides how
much of your attention and money the system should be allowed to spend per false alarm. A shop with four figures
of stock and a shop with forty should not have the same paging policy.

## Q7. Does your insurance require a monitored alarm?

If the policy says "UL-listed central station monitoring" then this system, however good, does not satisfy it and
the trade is: keep a cheap monitored alarm for the certificate and let mine do the thinking. If the policy says
nothing, we are free.

**What I need:** the policy's alarm clause, or a photo of it.

## Q8. Is there anyone whose access must be *revoked*?

The ghost that broke the old alarm was a worker who left months ago and whose phone still said he was home. If
someone has left — staff, tenant, a family member's ex — their code and tag are live right now and I have no way
to know.

**What I need:** anyone who should no longer be able to walk in.

## Q9. Are there constraints I should know about — legal or personal?

Cameras that can see the public hallway, audio recording, the tenant's rights, the fact that customers are filmed.
New Jersey is a one-party state for audio but a business premises with employees has its own rules. Also: is
there anyone in your life whose presence at the shop would be a problem if it were *recorded*?

## Q10. How do you want to be reached at three in the morning?

Text, call, both — and does it depend on what happened? A text with a picture can be read in bed in ten seconds;
a call wakes you properly and works when you are asleep with the phone face down. My default would be text first,
call if unanswered.

---

# Part 2 — Decisions

Each has the evidence I read, why it is yours, my recommendation, and the single choice. Most are small; D1 is
the one that matters most.

## D1. May the system page you at all?

**Read:** `security_action` has 0 rows. The paging endpoint works (170–471 ms) and 4,507 messages are behind it,
but no code connects a level-3 decision to a message. That is the outbound rule doing its job.

**Recommendation:** yes, but narrow — **level 3 and above**, to you alone, carrying the picture and the one-line
reason. Level 0/1 never page; level 2 goes to a digest.

**Decision:** on, or recording-only until there is more history.

## D2. Who gets woken up

**Read:** the live roster is your number plus two others; `D240` says your mother was meant to be on it; the page
code marks the whole send failed if one recipient refuses.

**Recommendation:** three tiers — you always; your wife for level 3 and for away-mode; your parents only as the
away backup and only if they agree to a 3am call. Per-recipient results, success if anyone got it.

**Decision:** who is on which tier.

## D3. The night rule

**Recommendation:** level 3 pages at 03:00. A level 3 that waits for morning is not a security system. Duress
always pages, any hour. Level 2 waits for the morning digest.

**Decision:** accept, or set a quieter rule for weeknights.

## D4. The escalation ladder

**Recommendation:** page → if unanswered in 5 minutes, call → if unanswered in 10, the second person. During a
declared absence the first rung is the call.

**Decision:** accept, or change the intervals.

## D5. Who can cancel, and for how long

**Read:** the disarm already accepts a credential at any time. CP-01 wants a cancel window of at least 5 minutes.

**Recommendation:** a credential, a duress code, or your written word with the page's nonce, for ten minutes
after the page. A cancel is recorded with who did it. A *disarm without a credential* is never accepted.

**Decision:** accept.

## D6. What the agent may do with no one watching

**Recommendation:** read everything, page you, ask you, add channels, raise posture, write the record — and never
unlock, buzz, silence, disarm, or call the police. Remove `buzz_in` from the company's action surface entirely.

**Decision:** accept the list; and does `buzz_in` go.

## D7. Test mode should expire by itself

**Read:** `input_boolean.phoenix_intrusion_test_mode` is cleared by **nothing** in any YAML. A drill left on makes
the next real alarm silent — the worst state the system can be in.

**Recommendation:** auto-clear after 30 minutes, with a warning note in the record when it expires.

**Decision:** accept the 30 minutes or set another.

## D8. Armed modes

**Read:** today there is one mode. `everyone_away` is the whole arming model.

**Recommendation:** three declared states — **shop closed / apartment occupied / nobody here** — because a door
opening when someone is asleep behind it means something different from a door opening in an empty building.

**Decision:** accept three modes (this depends on Q3).

## D9. Expected-entry windows

**Recommendation:** a declared window ("cleaner Tuesday 06:00–07:00") that raises the *evidence* threshold rather
than lowering the alarm: an entry inside a window with no credential is a level 2 note; outside it, level 3.

**Decision:** accept, and give me the windows (Q5).

## D10. The tenant's code

**Read:** slot 11 is live and never rotated; `D7429` says the expected roster has no tenant.

**Recommendation:** if the tenant is still there, keep the slot and register them as a subject with hours. If not,
revoke it as a new row, never a delete.

**Decision:** does the tenant still have access.

## D11. Per-person credentials, or shared

**Read:** your parents share slot 4 by your explicit instruction, so "parent" is one identity by design. The shop
keypad's user list names individuals. The RFID layer is dead.

**Recommendation:** keep the shared parent slot as-is, give every other person their own credential, and retire
RFID rather than restore it — a tag has no revocation story and the readers are already dark.

**Decision:** confirm, and say whether any *shared* code may stay.

## D12. A duress code

**Read:** none exists. The design has a place for one — a silent alarm with a different payload.

**Recommendation:** yes, one, known only to you, used at the shop keypad; it arms the same alert without a siren.

**Decision:** yes or no.

## D13. What the siren does after fifteen minutes

**Read:** it now clears the flag and logs it. After that, silence.

**Recommendation:** after the cap, a strobe-only mode for another fifteen and a second page, rather than nothing —
an intruder should not learn that the noise has a timer.

**Decision:** accept, or leave it silent after the cap.

## D14. Drills

**Recommendation:** one silent drill a month, run by the system, recorded; one *audible* drill a quarter that you
know about in advance. Never an audible one without your word.

**Decision:** accept the cadence.

## D15. A weekly digest

**Recommendation:** one short message a week, only when something changed, at most one item needing you, silence
when the week was clean — and a hard rule that it says "nothing was recorded" rather than "all quiet" when the
record is empty.

**Decision:** yes, no, or only when broken.

## D16. What the AI is allowed to cost

**Read:** the estate repeats "five dollars a day"; the ledger says nine-sixty-two to thirty-seven-seventy-eight
over eight days, mean about twenty-one; the code default is ten and nothing enforces it. The security lane adds
about seven cents.

**Recommendation:** set the ceiling at twenty-five and actually enforce it, so a limit means something again.

**Decision:** the number, and whether it is enforced.

## D17. Coverage — the money

**Recommendation, in order:** a contact on the maglock door (cheapest real gap); a UPS for the HA box and the
siren; ground-floor glass; a second audible device that is not the Mac.

**Decision:** which, and when.

## D18. Cameras: clocks and detectors

**Read:** two cameras are sixteen minutes apart in time, so any cross-camera timeline is wrong; the Dahua
detectors are all switched off and have produced no events in thirty days; one channel is dead.

**Recommendation:** fix NTP first (free, and everything else depends on it), then decide detectors-vs-Frigate
rather than turning the Dahua switches on blindly.

**Decision:** approve the clock fix; decide whether to replace the dead camera.

## D19. How long do we keep the evidence

**Read:** evidence images are pruned at fourteen days; the record's decisions are meant to outlive them.

**Recommendation:** fourteen days on the HA box, thirty in the estate's store, labels and decisions forever.

**Decision:** accept, or lengthen (costs disk).

## D20. The frozen office box

**Read:** `secratary` is the rollback anchor and is not dormant — five timers firing, a 23 GB database written
today, `/` at 99 per cent with 5.3 GB free.

**Recommendation:** choose: a maintained cold standby, or retired with its database copied to the authority
first. "Frozen but still writing" is not one of the two and is the state it is in.

**Decision:** standby, or retire.

## D21. The HA token window

**Read:** the token is owner+admin, no MFA, plaintext, plain http, on two hosts; and `ip_ban` with a threshold of
five means five bad attempts from the proxy cut every cloud-to-HA path at once.

**Recommendation:** a non-admin user for agents, TOTP on your own account, HTTPS on the LAN, in a window with the
new token proven before the old one is revoked.

**Decision:** the window, and whether TOTP on your own login is acceptable.

## D22. Where the listener finally lives

**Read:** `zabz-tech-linux` reaches HA in 38 ms and is on the tailnet; it has no token and no `websockets`
package. The authority runs the listener today only because it already holds the token.

**Recommendation:** move it, and give it a **dedicated read-only HA user** rather than a copy of your admin token.

**Decision:** approve a third, narrow credential for that box.

---

# Part 3 — Things I want to be sure you understand

Not choices — these are the trade-offs I have already made on your behalf, and you should be able to overrule any
of them.

## C1. Why the alarm logic stays in Home Assistant and the intelligence does not

Anything that must happen while the internet is down happens locally and deterministically: the door, the siren,
the timeout, the page attempt. The agent adds *force* — explanation, escalation, channels, questions — and may
never be the only reason an alarm exists. An agent turn takes seconds; an alarm cannot depend on a network round
trip. This is why a model outage degrades the explanation, not the alarm.

## C2. Why the agent can never silence, unlock or call the police

Its output has no `action` field at all — it returns a verdict and a level, and code decides what runs. A model
that could return "siren off" is a model that can be talked into it, and I have already proven one injection
attempt succeeded at nothing. Silencing needs a credential, your recorded word, or the envelope's own timeout.

## C3. "Unknown holder" is a correct answer, and it will be common

The apartment door reports no identity at all, and shared codes attribute a role, not a person. When the system
says "unknown", it is telling you the truth about what it knows. I will not let it guess.

## C4. An empty record is not a quiet week

If the record stops filling, the honest reading is that nothing is writing — not that nothing happened. Every
digest and every reply from the record-reader carries the last event time for exactly this reason. This estate has
been burned by numbers that looked calm because their source had stopped.

## C5. The false-alarm arithmetic, measured

On the historical corpus, the rebuilt rules without a credential signal false-alarm on **ten of twelve** benign
episodes. With one, **zero of twelve**, and the synthetic three-in-the-morning intrusion is still caught. That is
why the keypad mattered more than it looked.

## C6. What this system still cannot see

A person who stands perfectly still in a room covered only by the doorbell; windows, the back, and the maglock
door (no contact); a door propped open all day; a camera that fails silently. Those are hardware and money, not
code.

## C7. The page is the whole gap between "notices" and "tells you"

Everything else can be perfect and, with `security_action` empty, you would still find out from the siren or from
the damage.

## C8. What I got wrong tonight, so you can calibrate me

Three live mistakes, all mine, all recorded: a delay whose arithmetic I asserted without computing it; a
"non-blocking" change that removed evidence capture entirely for four minutes before I reverted it; and a privacy
redaction that silently destroyed every identity until I fired a real event and saw an empty subject. Each is in
the journal with what it taught. Assume the rest of my work has errors of the same shape and check the ones that
matter.

---

# Part 4 — Mine to finish, no input needed

- **The entry delay end to end.** The thirty-second timer is live and structurally sound but has never fired for
  real. Its first real alarm is its first real test.
- **The evidence chain.** It still blocks the script for twenty to forty seconds. Harmless now that the siren is
  decoupled, but the fix is written down in `OPEN-THREAD-nonblocking-evidence.md` with the safe procedure.
- **Camera failures generally.** I removed the dead camera; the class is still open — any camera that starts
  failing can abort the chain.
- **Episode grouping.** One door per episode today. A person who opens two doors should be one episode.

---

# Part 5 — The order I would take them in (re-ranked 2026-10-27 after Q1)

The old order put paging second and hardware seventh, because the product was assumed to be an alarm. It is not.
The product is the record, so the parts that decide whether a person can be seen at all, at the right time, and
for how long, move to the front, and the alarm work keeps its place behind them.

1. **Q3, Q9, D8** — does anyone sleep behind the shop door; what may lawfully and decently be recorded (hallway
   cameras, audio, the tenant, customers); and therefore how many armed states exist. These three decide camera
   placement, retention and privacy, and none of them is mine to assume.
2. **Q4, Q5, D9** — the shop's hours, the people who are *expected*, and the declared windows. This is the
   vocabulary that lets the record say "expected" or "unexpected", and turns an anonymous edge into a named row.
3. **D17, D18, D19** — hardware, clocks and retention. Promoted from last-but-one to third: a camera that is not
   looking at the door, a clock sixteen minutes wrong and a fourteen-day prune are now defects in the product
   rather than gaps in a backup.
4. **D10, D11, D12** — the credential layer: what the record can honestly say about *who*, and what "unknown"
   will be rendered as.
5. **D1, D2, D3, D4, D5** — paging, escalation and cancellation. Wanted, but second: the record already earns its
   keep on a night nothing is paged.
6. **D7, D13, D14, D15** — the operating rules: test mode, the siren tail, drills, the weekly digest.
7. **D16, D21, D22, D20** — money, tokens, where the listener lives, the frozen box.
8. **D6** — the agent's allow-list and `buzz_in`, once the shape above is settled.
