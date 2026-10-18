# The owner channel — design of record, 2026-10-18

Supersedes the *recommendations* in `OWNER-TEXT-AUDIT-2026-10-15.md`; that document's **findings**
remain the evidence base and are cited here by `F<n>`. This document records **decisions**, so the
next session does not re-derive them.

Asked for, verbatim (2026-10-18):

> *"read the past 500 texts back and forth of the maintenance system and assistant to me, and I
> wanted to learn based on that... make it way more robust to texting back and forth system for
> reminders for the cfo, for everything else. And it needs to be learning and adapting overtime.
> So number one, I want to make sure that when the CFO needs information, it works very hard to
> figure it all out by itself first but afterwards if it needs my help, it asks me about it. And
> also other texts I needed to be a unified brain that, like, even if different parts of the
> company text me, there's one part that it relays through. So, like, no one gets confused. But
> who's texting what I'm responding to? And most important is to be constantly learning and
> optimizing itself... every week or two this whole texting back and come forth gets audited and
> evolved."*

---

## 0. What the 500 messages actually say

Corpus: the last 500 distinct real messages (`delivered`/`sent` outbound + `received` inbound,
deduped on `twilio_sid`) between the company and `+18483897895`, 2026-02-18 → 2026-10-16.
Method and raw window: `_owner-text-20261018/corpus.txt`, 500 lines, cited below as `corpus:NNN`.
The taxonomy with counts is `_owner-text-20261018/preferences.md`.

**The channel's history in one line:** 2026-02 → 2026-07 is dominated by machine-generated
*questions with no content* — "What specific metrics or insights do you want to focus on for
Dialpad and Communications?" repeated 40+ times (`corpus:220-296`), each ending
`Reply to this text and I'll get it.` He never answered one. The volume was never the problem;
the questions were.

Six rules he stated, each more than once, in his own words:

| # | rule | his words |
|---|---|---|
| 1 | ONE item. A question, or a notification. Never a list, never a count head. | `corpus:331`, `corpus:486`, `corpus:497` |
| 2 | Exhaust your own records before asking me. | `corpus:500`, `corpus:488`, `corpus:386`, `corpus:176` |
| 3 | If it is still unknown, say everything you found and ask one thing. | `corpus:500` |
| 4 | A unified brain: know what you already sent me and what I already answered. | `corpus:358`, `corpus:464`, `corpus:483` |
| 5 | Answer a text with a text; silence is the worst failure. | `corpus:8`, `corpus:24`, `corpus:35`, `corpus:356` |
| 6 | Read the timestamps. Do not assume it all happened "now". | `corpus:19`, `corpus:55`, `corpus:56` |

And the sentence that is the whole specification for the ask path, `corpus:500`, 2026-10-16:

> *"I don't know. I want you to figure this out and give me more details. Maybe check my emails or
> other places. **Remember, before you give me a charge, you have to exhaust all of the resources
> for exploring it. And then, if you still don't know, give me all the details you found.** This
> doesn't have any details."*

---

## 1. The one structural decision

**Every text to him, and every text we send on his behalf, is composed by one front desk, and the
front desk is `owner_text_relay.py`.**

A door may *ask* for a message; it may not *write* one. The door submits an **item**; the front desk
composes, gates, files the ask, sends, and records the outcome. That is what makes "one part that it
relays through" true rather than aspirational.

Consequences, all already begun on 2026-10-15 (`F7`, and `submit_item`/`compose` at
`owner_text_relay.py:598,628`):

- `compose(item)` is the only producer of a body.
- `submit_item(door, subsystem, item, ref=…)` is the only path to `submit()`.
- The judged body and the posted body are the same object (journal `L3790`).
- A door that writes its own body is a defect, not a variation. The count of such doors is a
  metric (`doors_outside_relay`), and it must reach the heartbeat only, because
  `company-heartbeat.sh` must stay independent of the company API by design (`P3176`).

**CORRECTION (forensics, 2026-10-18).** The primitives exist; **nothing uses them.** Measured call
sites on the live tree: `compose()` has **exactly one** caller
(`scripts/owner_attention.py:959`) and `submit_item()` has **zero**. So the paragraph above
described an intention, not the system. The honest statement of today:

| primitive | state |
|---|---|
| `compose()` | live, one caller — the daily attention item |
| `submit_item()` | live, **no callers** — dead code on the send path |
| `submit()` | live, three door literals: `app`, `textsend`, `family_chat` |
| `fit()` | called by the app door only; **`textsend` and `family_chat` never call it** |

That makes step 2 of the 10-15 audit's own "next" list ("give every door one `compose()`") the
first real task, and it is why a body could be 377 chars on a door that never fitted it. The
`fit()` asymmetry is also half the Audi defect below.

**Doors and their status.** Nine exist (`F7`). Target state:

| door | through the front desk | how |
|---|---|---|
| app `sms_service.send_message` | yes | already |
| `textsend.send()` | yes | already |
| `cfo-ask.py` | **yes — question composed as an item** | this work |
| `owner-ask.py` | yes | wire or retire; it has no cron line today |
| `card-due-watch.py` | yes | this work |
| `scripts/owner_attention.py` | yes (daily item) | already |
| `app/family_chat` owner leg | yes — **two recipients, not a double send** (corrected below) | `attempt` 66/67, 68/69, 71/72 |
| `sms-responder.py` | yes via textsend | already |
| `company-heartbeat.sh` (2 read-only hosts) | **stays outside, deliberately** | `P3176` |

### 1a. CORRECTION — the "doubled family tap" was not a double send, and the real defect is worse

First reading of `relay.db` attempt pairs 66/67, 68/69, 71/72 was "every family message is sent
twice". **That was wrong, and `sms_log` says so.** The two rows of attempt 71/72 are:

| sms_log id | sid | `to_number` | body |
|---|---|---|---|
| 4277 | `SM587ac9…` | `+18482245096` | Shabsi: MOOSE MASTER! |
| 4278 | `SM070166…` | `+18483897895` | Shabsi: MOOSE MASTER! |

One relay to the intended family member, one to the owner. Correct behaviour. A per-minute count of
distinct sids to the owner is 1. He receives each family message **once**.

**The real defect this exposed: `relay.db attempt` has no recipient column.** The door that sends
to a third party and the door that sends to him are indistinguishable in the ledger, so:

- "was this the same message twice, or one message to two people?" cannot be answered from the
  only ledger the channel has;
- the two stuck attempts 74/75 (`too-long`, `pending`, no sid) cannot be shown to be a retry of one
  recipient rather than one message to two people — which decide different fixes;
- the estate's own rule — *"after the send, read the recipient back, not the label"* — is
  impossible to obey for the relay, by construction.

**Decision:** `attempt` gains `to_number`, `submit()`/`submit_item()` require it, and the ledger's
`record_sent()` verifies the sid's real recipient against it where Twilio can tell us. A message
whose recipient is not recorded has not been sent as far as this channel is concerned.

### 1b. The flood is five retry loops, not two thousand messages

The honest numbers, measured 2026-10-18 over 30 days:

| reading | value |
|---|---|
| `sms_log` rows with status `suppressed` | **2,036** |
| **distinct bodies** among them | **61** |
| the top four bodies | 840 + 488 + 290 + 91 = **1,709 rows** |
| outbound distinct sids delivered | 60 |
| inbound from him | 85 |
| inbound with no outbound within 60 minutes | 16 (18.8%) |
| **median minutes from his text to the next outbound** | **0.6** |

So the channel he remembers was broken; the channel that exists today is quiet and usually answers
in under a minute. What remains is structural: four scheduled reminders re-submit the same body on
a tick (1,709 suppressed rows for 4 messages), and nothing counts that as a defect because a
`DEDUPE`/`SUPPRESS` verdict looks like the gate working.

## 2. The pre-ask ladder — "work very hard first"

This is the answer to rule 2/3 and to `corpus:500`. It is **one module**, `preask`, called by the
front desk **before an item may set `opens_ask`**. An ask that arrives at the composer without a
`preask` receipt is refused by the composer, not argued with.

An item carries `preask_receipt`: the ordered list of rungs that ran, what each returned, and the
verdict. The composer prints the receipt into the message only as far as it is *useful to him* —
never as a log — and the refusal is what makes the ladder unavoidable.

**The rungs, in order — cheapest and most authoritative first:**

| # | rung | source | what it can settle |
|---|---|---|---|
| 1 | `records:owner-answer` | `relay.db ask` (answered), `owner_text_turn`, `owner_text_suppression`, `memories` | he already told us |
| 2 | `records:ledger` | `authority.db purchases`, `transactions` (join on `external_transaction_id`), `merchant_aliases` | what the money was |
| 3 | `records:comms` | comms index: his texts, emails, call transcripts (FTS) | merchant emailed us, order confirmed, vendor named |
| 4 | `records:case` | LPT production work orders / case files | which customer a shop purchase was for |
| 5 | `records:docs` | repo docs: payroll, insurance, contracts, tax | the standing fact |
| 6 | `records:memory` | `owner_profile_v2`, `owner_assumptions`, journal decisions | a preference or fact recorded once |

`merchant_resolve.resolve()` already implements rungs 2 and 3 for charges, plus
`records:owner-text`, and is the reference implementation of a rung (`F5`, item 8 of the 10-15 work).
`preask` **routes by ask kind** and reuses it for money; it does not reimplement it.

**The verdict is three-valued and recorded:** `answered` (do not ask — act), `partial` (ask, but the
body carries the evidence found), `unknown` (ask, and the body says which rungs ran and returned
nothing). Only `partial` and `unknown` may open an ask. Every receipt is written to `relay.db`
table `preask` so the weekly audit can count **asks that were answerable from our own records** —
the single most damning metric on this channel (`corpus:488` "you should be able to see research
your questions before asking me for no reason").

**The body shape when it does ask** — one message, ≤ 320 chars, in this order and no other:

```
<merchant or subject> <amount/date>: <the one thing only he can answer>
<what we already found, in one clause, only if it is evidence not a log>
```

Never: a count head, a list, `full: <path>`, `Reply to this text and I'll get it.`, a truncation
marker, or a question mark on a notification.

## 3. One ask ledger

`relay.db ask` is authoritative. `quote`:

- Every asker files with `relay.record_ask(ref, subsystem, topic, body, ttl_hours=…)`.
- Every inbound path closes with `relay.answer_ask(ref, answer, answered_by=<number>)`.
- `textctx.recent_asks()` reads the relay first and the other stores only as a fallback, and the
  fallback is **counted** so its retirement is measurable.
- `/root/.cfo-asks/asks.db` and `/root/.owner-ask/asks.db` become projections, not authorities.
  `owner-ask.py` has never run (`F3`) — decide: wire it or delete it. **Decision: retire it.** A
  store with zero rows and no cron line is a trap for the next reader, and the CFO asker already
  covers its only caller.

**The suppression key is the charge, not the merchant.** `cfo-ask.py:484` keys `asked_keys` on the
merchant, so one answered charge at a shop suppresses every future charge there. The key becomes
`(account_id, external_transaction_id)` with the merchant as a weak fallback. (`F5` residual.)

## 4. Reply binding — "who is texting what I'm responding to"

The failure he named is real and dated: `corpus:192`, 2026-04-20 — *"you linked that replied to the
pending question it was a totally random piece of information"* — and its twin `corpus:357-358`,
where the system asked *"Which item was this for?"* about its own text thread.

**The mechanism, measured** (`textdecide.py:1494-1554`): binding tries an explicit ref, then a
content match at strength ≥ 2, and then — this is the defect — falls through to
`asks[0], strength 0, match="inferred"`: **any non-complaint statement is filed as the answer to
the newest open ask.** The only guard is a "complaint about us" check. An "ok" or a "call me later"
closes a question it never addressed.

**And the relay's asks cannot even be closed by a reply.** They are named `attempt-29`,
`attempt-63`, `attempt-70` (`relay.py:1010-1016`, `ask_ref = "attempt-%d"`), while the reply
extractor looks for `CFO [ask-N]` or `[qN]` (`textctx.py:1112`) — a token he has never seen and no
regex matches. So three asks have been open since 2026-10-14/17, absorbing whatever he says next
until TTL.

Decisions:

1. **A reply resolves in this order:** (a) an explicit `ref` in the body (`CFO [ask-…]`);
   (b) a normalised match against the ask's own body; (c) the newest open ask **whose topic
   overlaps the reply**, within its TTL. Time alone never binds a reply to an ask — step (c) is
   removed as a fallback and `inferred` may no longer be the resolution, only a hypothesis.
2. **Ambiguity is surfaced, not guessed.** If two or more asks are open and none matches by (a) or
   (b), the reply is filed as `unbound` and he is asked which one — one message, numbered, only
   the two or three candidates, never the whole open set.
3. **A bound reply is confirmed in one line that names the thing**, so a wrong binding is visible
   to him in the same breath: *"Filed the Home Depot 299.29 as shop supplies."* Never
   *"Got it"*.
4. **Every ask carries a ref a human can say.** The composer prints a short ref for any ask that
   will need an answer, and `record_ask` refuses a ref that `textctx`'s extractor cannot parse.
5. **Identity is a table, not a cell — and a separate channel is not an identity question at all.**
   The owner is every number he has ever used, as a *verified* allow-list rather than
   `OWNER_ALT_PHONE_NUMBERS` as it stands: that env var lists `+18482245096`, a **family member**,
   making his texts count as the owner's (`twilio_client.py:373-395`). Correcting the number alone
   would be fixing the symptom — the channel rule in §5 means family traffic is never judged by the
   owner's limits in the first place, whoever is on the list.

## 5. The composer's voice

**First, a rule from the owner that outranks the rest (2026-10-18):**

> *"the family chat system is not part of the regular rate limits and is a completely separate
> thing."*

Family Chat is a chat between relatives. It is **not** the owner's attention channel and none of the
rules in this section are about it. The 320-char ceiling, the 20-minute floor, the one-at-a-time
turn and quiet hours are rules about how much of *his attention the company may spend*; a
relative's message is not the company spending it. So, decided and now live in the relay:

| rule | owner channel | family chat |
|---|---|---|
| length ceiling | 320 (his reading) | 1600 (transport only) |
| rate floor (20 min) | applies | **does not apply**, in either direction |
| one-at-a-time turn | applies | **does not apply** |
| quiet hours | applies | **does not apply** |
| dedupe | applies | a relay of a relative's words is exempt (`dedupe_disabled`), because two relatives writing "Mazal tov!" are two events |

Watch: `owner_text_relay.ceiling_for(to, subsystem, door)` and the `separate` term in the FLOOR
branch. Pinned by tests 7–9 of `mirror/test-relay-recipient.py`, including the one that matters:
the *same* text from the `app` door is FLOOR-held while the family message is not.
`/root/bin/owner_text_relay.py` `d4ffe3aad4d0`.

The remaining half is app-side and is ledger 526: `_owner_leg()` calls `owner_text.gate` at
`twilio_client.py:677` for **every** recipient, which is how `sms_log` 4280 came to say *"we texted
**him** 9 minute(s) ago"* about a message to a family member. `OWNER_ALT_PHONE_NUMBERS` containing
`+18482245096` is the symptom, not the disease; deleting that number fixes one person, and the
channel rule fixes all of them.

Rules the composer enforces mechanically on the owner channel, each traceable to a message he sent:

1. One item. A body containing a count head (`N items`, `N urgent`) or a newline-separated list of
   more than three lines is refused at compose time, not truncated.
2. ≤ 320 chars **by construction**: the item is rendered to fit; if it cannot fit, the composer
   drops the evidence clause before the ask, and the ask before the subject. A SEND verdict
   therefore always fits.
3. No truncation marker, ever. A message that must be shortened is shortened at a sentence
   boundary and the loss is logged to `fit.log` — he is never told to ask for the rest of his own
   message (`F2`).
4. No boilerplate close. `Reply to this text and I'll get it.` is refused by the composer.
5. The question mark is *load-bearing*: `textsend` opens his one-at-a-time turn only on
   `[?？]` (`F5`). The composer guarantees a question body ends in one, which is what makes the
   one-at-a-time rule apply to CFO asks at all.
6. A question is only sent if an ask was filed, and the ask's `ref` is attached to the attempt —
   so a reply has something to bind to.
7. Silence is a measured defect, not a default: every inbound must be answered or explicitly
   filed within 60 minutes, and the count of misses is metric 8 of the weekly audit.

## 6. The learning loop

Two speeds.

**Fast (every message).** `standing_rule_mutes()` already reads
`/root/.owner-text/standing-rules.json` on every submit. It gains a *preferences* tier: a `stop`
instruction from him takes effect on the next message, not on the next deploy, and a preference
with two or more observations is applied without a session.

**Slow (weekly, inside the autonomous wake system).** `scripts/text-channel/owner-text-audit.py`
computes eight metrics over the last 14 days and **files a wake flag only when a threshold is
breached** — nothing on a timer may raise a flag merely because time passed. The flag's prompt
carries the metric table, the breached thresholds, and three evidenced defects, and instructs the
woken session to **fix the worst one at the door or composer that owns it, prove it, record it, and
leave a note for next week.** A weekly audit that only writes a report is the failure mode this
whole document exists to prevent.

Metrics, and why each exists:

| # | metric | threshold | what it catches |
|---|---|---|---|
| 1 | refusal_rate | > 0.5 | a gate refusing most of what doors produce |
| 2 | max_repeat | > 1 | the same body to him twice |
| 3 | double_sends | > 0 | two sids, one event (live tonight) |
| 4 | silent_outcomes | > 0 | SEND verdict, no delivery, nobody told |
| 5 | unanswered_backlog | > 0 | questions he never answered |
| 6 | answer_latency | median, trend | how long he waits |
| 7 | internal_asks | > 2 | asked what we could have answered |
| 8 | truncation | > 0 | a half-message reaching him |

## 7. What this document does NOT decide

- The provider pool on the reply path is one model (`F6`, `docs/mesh/177`) — a different
  workstream, and two sessions must not fix one outage.
- `P4254` — something restores files in `/root/bin`. **Any change made there must be hashed before
  and after, and re-checked the next day**, or it is not a change.
- Whether `company-heartbeat.sh` records its sends (`P3172`, owner queue).

## 8. The durability decision

`/root/bin` is not a git repository (`§5` of the 10-15 audit; `AGENTS.md` §6.1). The front desk —
66 KB that every text to him passes through — existed in exactly one place with no review and no
history. **Decision: the live owner-text stack is mirrored into `scripts/text-channel/mirror/`
with a deploy script and a hash manifest, and the mirror is verified before every change, because
`P4254` may revert a live file under us.** The existing `scripts/text-channel/README.md` describes
`/home/zabz/bin` on the now-retired office box and is corrected in the same commit.
