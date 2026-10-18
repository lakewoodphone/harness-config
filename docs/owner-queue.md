# The owner queue

**One table, one order, one dossier per item, and it learns from his answers.** Everything that
needs Eliyahu — a decision only he can make, and anything from his personal texts, calls, voicemails
or email that he would want to know about — lives in `owner_decision_queue` on the authority and
comes out of one command in one order.

Read §1 before changing any rule here. Written 2026-10-18, after he corrected a session that had
started building it on the shop's telephone line; extended the same day with the two requirements
that decided its shape: **it must learn** and **it must arrive fully briefed**.

---

## 1. His words — the law this serves

> *"make sure it's one queue that has everything that I need to know or needs my either one ... any
> email or text that you deem worthy of my attention or something I might want to know should be in
> the owner queue ... once in a while I'm going to ask, hey, let's go through the queue or let's
> knock out the queue and you just tell me things one at a time. A mix of stuff that were emailed or
> texted. They don't specifically need my decision, but I would want to know about and also stuff
> and need my decision from."*

The correction that overrides every earlier assumption:

> *"dial pad calls sms and voicemail do not count. I only want personal ones ... Google voice numbers
> and you do have access to my Google voice numbers because they get forwarded to my email ... The
> dial pad is not relevant to my queue And you can access my goal of voice through my emails."*

And the two that make it usable:

> *"the queue needs to learn over time what to put in it and what to prioritize and so on based on my
> responses to the queue when we go through a session knocking it out together"*

> *"all information about it must be gathered in case I want more info, so only put it in the queue
> after all info is gathered about it fully so I can just quickly knock out the queue with you once
> every other day or so quickly together with you already having all the info I may need about each
> thing"*

## 2. The channel law

| Channel | In the queue? | How it is reached |
|---|---|---|
| **Google Voice** texts, missed calls, voicemails | **YES — the personal channel** | Forwarded mail: `voice-noreply@google.com`, `txt.voice.google.com` |
| **His own inboxes** | **YES — judged, one verdict per message** | `gmail_service` live; all authenticated accounts except `zabzgpt@` |
| **Dialpad** (shop line: calls, SMS, voicemail) | **NO. Never.** Its voicemail-notification *email* is filtered by sender | — |
| App alerts the app never delivered (`owner_message_queue`, status `held`) | Read as items, except ops alerts and duplicates of judged email | read-only merge in the reader |
| Agent approval requests (`agent_questions`) | Read as decisions | read-only merge in the reader |
| Ops alerts (paused sync, stale capture) | No — they are mine to repair | counted, never shown as an item |

Google Voice accounts and where each forwards (from `app/services/gv_email_handler.py`
`GV_ACCOUNT_MAP`):

* `+17325691594` → `eliyahuzabrowsky@gmail.com`  ← the busy one, ~99% of volume
* `+17329943420` → `ezabz68@gmail.com`

**The Voice browser scraper is retired on purpose and is not a fault.**
`google_voice_secretary_health` shows account 0 `retired` (7977 consecutive failures, last ok
2026-07-02) and account 1 `retired` (7315, 2026-07-02), with `last_error` = *"RETIRED BY DECISION, not a
fault."* Nobody may "fix" those counters. Email forwarding is the live path and it works.

## 3. The pipeline

```
Google Voice forwards ─┐
                       ├→ owner-queue-ingest-gv.py ── parse_gv_email → classify → collapse ─┐
his inboxes ───────────┴→ owner-queue-ingest-mail.py ─ judge (model, rubric) → dedupe → digest ─┤
                                                                                                ▼
                                                              owner_decision_queue (ONE table)
                                                                  kind = decision | attention
                                                                                                │
                     owner-queue.py queue / card / knock  ← one score, one arithmetic ──────────┤
                     owner-queue.py answer|resolve|defer → owner_queue_feedback ── learning ────┘
```

Both ingest scripts run under the app venv (`/root/personal-secretary-mvp/.venv/bin/python`) because
they import the app's Gmail client, its GV parser and its model helper. They **chdir to the app
root**: `gmail_service._tokens_dir` defaults to the *relative* path `data/gmail_tokens`, and a run
from `/root` reports every account "not authenticated" while the tokens sit in the checkout —
measured 2026-10-18, and it looks exactly like a credential outage.

## 4. How a message becomes a queue item

### 4.1 Google Voice — rules, not judgement

Corpus: **624 forwards over 45 days** (538 sms, 66 missed calls, 20 voicemails), 166 over 14 days.
Every rule exists because that text was in front of me. 14-day window: 166 read → **34 queued**,
**73 dropped**, 59 folded into digests.

**DROP**: shortcode senders (17) · daily zmanim/candle-lighting (13) · missed calls with no name, no
voicemail and no text (13) · empty or receipt-only (7) · bulk sender named in the body (6) · vendor
robots (5) · one-time codes (3) · **our own alert texts** (2) · order & parcel lifecycle (2) ·
carrier data notices, toll-free marketing, robocall voicemail, voicemail with no transcript.

**DIGEST**: twelve or more messages from one sender in the window is a relay; they fold into **one row
per sender per ISO week** carrying a count, the speakers and any actual question.

**ATTENTION**: a person asking him something · a named missed call · any voicemail that survives the
robocall test (callback + a real name ⇒ `critical`) · a personal message with a date or a sum.

**DECISION**: only when the message asks him to choose, approve or commit.

Two traps that cost real time and must not come back: `contact_name` vs `name` key mismatch (dropped
every item as nameless), and `not name` dropping real people who are simply not in his address book.
A 4-6 digit *name* is a shortcode; a bare *number* is a person.

### 4.2 Email — a model judges, against a written rubric

Measured 2026-10-18: **814 messages over 14 days across five accounts** (~58/day).
`email_catalog` flags 347 of 812 `needs_owner=1` and a 25-row sample of those was UGG, Uber Cash, AAA
and newsletters — **the flag is not the signal**. A regex cannot answer "would he want to know this",
so the verdict is a model call per batch of 10, and **every verdict is stored with its reason**
(`owner_mail_verdict`). Nothing is dropped without a recorded why.

Three outcomes: `drop` · `attention` · `decision`. The rubric is in
`scripts/owner-queue/owner-queue-ingest-mail.py::SYSTEM_PROMPT`; the parts that matter:

* **Tier is about consequence, not about who sent it.** A link from his wife is `low`; a bill that
  will suspend a service is `critical`.
* **A machine never asks him to choose.** A bill that is due, a negative balance, a delivery that
  needs rescheduling are `attention` with a deadline. Enforced deterministically afterwards
  (`demote_machine_decisions`), because one model wobble on this puts a billing notice in front of
  him as a question — measured twice on the first run.
* **Every decision carries a recommendation**, because he knocks the queue out to *answer*, not to
  research.

Measured on the first 7-day backfill: **205 messages → 100 dropped, 35 rows** after collapse, dedupe
and routine-notice digest.

**Two deterministic guards sit behind the model, and both exist because it was wrong twice:**

| Guard | What it prevents | Measured |
|---|---|---|
| **HTML → text before judging** | Gmail falls back to the raw part, so a Chase notice is 17 KB of `<head>` and scripts. Truncated to 1 500 chars the judge only ever saw the `<head>`: it said "amount unknown" while queueing the row | first run |
| **Fact keys, not message keys** (`key_for`) | Telnyx sent "balance is -$0.01" on four consecutive days → four `critical` rows for one fact. A *person's* conversation keys on the thread; a *machine's* recurring notice keys on the fact (domain + subject with dates/amounts stripped) | 4 rows → 1 |
| **Routine notices digest** (`fold_routine_notices`) | Five banks "informing" him on one day are one thing happening. `money`/`notice` at `medium`/`low` fold into one row per class per day; `critical`/`high` never fold | 5 rows → 1 |
| **`urgent_email` dedupe** | The app writes a held row for every "X emailed about Y". The mail ingest now judges Y itself, so the held row is dropped when the judge holds a verdict on that subject — and if the judge is dead there are no verdicts, the held row shows, and nothing goes missing | 4 rows |

## 5. The one ordering

Every reader uses one function, `_queue_score`, and **every line prints its own arithmetic** so the
order is judgeable rather than asserted:

```
score = tier                      critical 1000 · high 700 · medium 400 · low 150
      + 200 if it blocks other work
      + 100 if it is a filed decision          (agent questions do not get this; they carry ask)
      + min(150, age_hours / 8)                anti-starvation, capped so it cannot jump a band
      + 40  if it arrived in the last 24h
      + 80  if a person is asking him something
      + 60  if it names a deadline, +60 more if that deadline is inside a week
      + min(200, money / 10)                   read from the one-liner, not from the body
      - learned penalty                        what his own answers taught (see §6)
      - 200 if the row named a day that has passed (POSSIBLY MOOT)
```

Two things this got wrong first, both measured on the live 42-row queue before they were fixed:

* **`meta.money` was NULL on every single pending row**, so the money term had never fired once — a
  returned payment of 2 380.06 ranked below a ten-day-old voicemail about a laptop. The amount is in
  the words; `_money_in()` reads it there, which also fixes every historic row at once.
* **`deadline` matched the word "today"**, so "any way I can get my phone today?" earned a deadline
  bonus. A day is named; a deadline is stated — `due in`, `expires`, `overdue`, `suspended`,
  `deadline`, `final notice`, `by <weekday>`, `in N days`.

Nothing reads a stored score. A score written at insert time goes stale the moment the ingest stops,
and then the order is a claim about urgency that nothing re-measures.

## 6. It learns — from his answers, not from a hint

Owner's requirement, 2026-10-18. The mechanism is boring and auditable; there is no model in the
ranking and no stored score.

1. **Every close writes one feedback row** — `owner_queue_feedback(item_id, action, answer, kind,
   channel, party, class, sender_domain, tier_at, at)`. Written by the same `answer` / `resolve` /
   `defer` / `skip` commands that close the item, so the record cannot drift from the queue it
   describes.
2. **A sender he keeps dismissing sinks.** ≥ 2 dismissals and more dismissals than answers in 120 days
   ⇒ **−40 per dismissal, capped at −120**, printed in the arithmetic as `learned=-80`. It may reorder
   inside a band and can never pull a critical item below a medium one.
3. **The mail judge is given his last dozen answers and dismissals as examples**, so tomorrow's
   judgement is *his* judgement rather than the rubric author's. The block is labelled
   `WHAT HE HAS ALREADY SAID` and lists the item, the sender and his own words.

To watch it learn: `owner-queue.py learning` prints the profile — which senders are demoted, by how
much, and the evidence count behind each.

## 7. Every item arrives briefed

Owner's requirement: *"only put it in the queue after all info is gathered about it fully"*. What a
row carries when it lands, and what `show`/`card` print:

| Part | Where it comes from |
|---|---|
| The one-line title | the judge (email) or the parsed message (Voice) |
| **Why it is in the queue** | the judge's reason, stored with the verdict |
| **What he would do** | the judge's `action` |
| **My recommendation** (decisions) | the judge's `recommendation` |
| The full text | the message body, HTML stripped (email) or the cleaned transcript (Voice) |
| **History with this sender** | closed queue items from the same *identity*, with his own past answer |
| Thread state | how many messages in the conversation, and which is newest |
| Amount, deadline, tier | read from the one-liner at rank time, so they cannot go stale |
| **POSSIBLY MOOT** | added when the row named a relative day that has passed |

A decision without a recommendation is a **defect**, not a nicety: he asked to answer without going
and looking anything up.

Two of these were wrong on the first build and are worth not repeating:

* **History matched on the mail domain**, so a card for his wife's grocery request listed four Telnyx
  and Chase items as "history with this sender" — `gmail.com` is not an identity. For freemail
  domains the **full address** is the identity; for a company the domain is. A false provenance claim
  is worse than no history.
* **The amount was read from the whole message**, so a grocery order scored `money=+200` off the
  prices of the items in it and outranked a suspended phone line. Money comes from the judge's field
  or its one-liner, **never from the body**.

**POSSIBLY MOOT** exists because the queue's second-highest item was *"Yocheved asks you to order four
grocery items for dinner tonight"*, four days after that dinner. Asking him is worse than not asking:
it spends his attention and returns nothing. A row whose text says `tonight`/`today`/`tomorrow` and
which is older than that day is flagged on its own card and demoted by 200.

## 8. The working set — what "let's knock out the queue" actually shows

Measured 2026-10-18: the first 7-day backfill produced **100 pending items**, 37 of them 3-7 days old
and 16 older. A hundred-item list is not knockable, and a queue nobody finishes is the same as no
queue. So:

* **Decisions are always in the working set.** They block work until answered.
* **Attention stays while it is still news, still someone waiting, still expensive, or serious** —
  age ≤ 3 days, or `ask`, or `critical`/`high`, or money ≥ 100. Otherwise it is **counted and named**,
  never deleted: *"32 quieter attention item(s) held back — older than 3 day(s), nobody waiting, no
  money, not serious (--all shows them)"*.
* The absolute bound is 21 days for attention. Decisions are never aged out.

## 9. Lifecycle, and why a dismissal sticks

`pending → seen (seen_at) → answered | resolved | dismissed | deferred | superseded`

### 9.1 The queue closes its own loops

Measured 2026-10-18, and it was the worst remaining behaviour: Telnyx's "balance is −$0.01, services
will be suspended" sat at `critical` and at the **top of the queue for two days after Telnyx wrote
"account re-enabled after payment"**. Both facts were in the mailbox; nothing connected them, so the
queue answered yesterday's question with total confidence. That is worse than a missing item.

`reconcile()` in the mail ingest closes it, and the rule is deliberately narrow:

* the resolution must come from the **same sender identity** (full address for freemail, domain for a
  company) — never from a look-alike;
* it must be **newer** than the row it closes;
* the old row must actually **read like an alarm** (suspend, overdrawn, negative, failed, past due,
  expiring, low balance, insufficient, quota, action required, payment due);
* it only ever closes **`attention`**. A decision he has not answered stays his even if the situation
  moved — the card says POSSIBLY MOOT instead, and he decides.
* every close writes what closed it into `resolution`, e.g.
  `auto-closed: portal@telnyx.com said "Telnyx account re-enabled after payment" (2026-10-13)`,
  so the action is auditable and reversible.

On the 14-day corpus it proposed **exactly one** close and made no false ones. `--explain` prints the
proposals and writes nothing.

* `dedupe_key` is **UNIQUE** (partial index where not null). Keyed on the message id for Voice, the
  thread for a person's email, the *fact* for a machine's email.
* Re-running an ingest **refreshes** a pending row and **never resurrects** a dismissed or answered
  one (`left_closed` in the run report). That is the dismissal memory the app's own attention tables
  never had — they re-appended every fingerprint on every run.
* `defer`/snooze keeps the row pending and stops it ranking until the day he named.

## 10. Commands

```bash
# the queue — one order, both kinds, the working set
python3 ~/bin/owner-queue.py queue --limit 20
python3 ~/bin/owner-queue.py queue --all --limit 200      # everything, including held back
python3 ~/bin/owner-queue.py queue --kind decision
python3 ~/bin/owner-queue.py queue --json

# "let's go through the queue" — the answer to that sentence
python3 ~/bin/owner-queue.py card          # THE NEXT ONE, in full, with its dossier
python3 ~/bin/owner-queue.py show 591      # a specific item in full (marks it seen)
python3 ~/bin/owner-queue.py answer 591 --answer "yes, at list price"
python3 ~/bin/owner-queue.py resolve 591 --dismissed "not mine"
python3 ~/bin/owner-queue.py defer 591 --until 2026-10-25 --note "after the yom tov"

# a terminal walk, one item at a time (interactive)
python3 ~/bin/owner-queue.py knock --limit 25

# pull both channels, or one
python3 ~/bin/owner-queue.py ingest all --days 3
python3 ~/bin/owner-queue.py ingest mail --days 7 --explain
python3 ~/bin/owner-queue.py ingest gv --days 3 --explain --only-dropped

# is it being fed, and what has it learned
python3 ~/bin/owner-queue.py health
python3 ~/bin/owner-queue.py health --json
python3 ~/bin/owner-queue.py learning
```

`knock` verbs: `a <answer>`, `d [why]` dismiss, `s 3d` snooze, `n` skip, `q` quit — and **a bare
sentence is taken as the answer**, because he should not have to learn a syntax to reply.

## 11. The knock-through protocol (what a session does)

He says *"let's knock out the queue"*. The correct behaviour, and it is not negotiable:

1. `owner-queue.py card` — **one** item, in full, with its arithmetic. Never a list of everything.
2. Read it to him the way a chief of staff would: what happened, who it is from, why it is here, and
   for a decision **my recommendation in one line**. If he needs a number to decide, the number is in
   the row; if it is not, gather it before asking.
3. Wait. His answer is the next line. A bare sentence is the answer.
4. Record it: `answer <id> --answer "<his words>"`, or `resolve <id> --dismissed "<why>"`, or
   `defer`. **His words verbatim** — they are the training data (§6) and the journal copy.
5. Then `card` again. Stop when he says stop, when the queue is empty, or after ~25 items.

Never batch five questions into one message. Never ask him something the row already answers. Never
end a session without recording what he said.

## 12. Is it alive?

Three readings, and each answers a different question:

```bash
# 1. is the timer scheduled, and did the last run pass
ssh secratary-cloud 'systemctl list-timers lpt-owner-queue.timer --no-pager'
ssh secratary-cloud 'systemctl status lpt-owner-queue.service --no-pager | head -12'

# 2. one command that reads every source's own freshness and fails if one went quiet
ssh secratary-cloud 'python3 /root/bin/owner-queue.py health'

# 3. is GV still forwarding at all — the SOURCE, not the reader
ssh secratary-cloud 'cd /root/personal-secretary-mvp && ./.venv/bin/python -c "
import sys; sys.path.insert(0,\".\")
from app.services import gmail_service; from app.config import settings
print(len(gmail_service.search_messages(settings, account=\"eliyahuzabrowsky@gmail.com\",
      query=\"from:txt.voice.google.com OR from:voice-noreply@google.com newer_than:7d\", max_results=500)))"'
```

A queue that has stopped filling and a queue with nothing to say look identical from inside the table.
`health` is what tells them apart: it compares each source's newest arrival against a limit derived
from its own 14-day rate (`max(48h, 6 × average gap)`), and exits non-zero when one is stale. The
timer runs it after every ingest, so a silent channel shows up in `systemctl --failed`.

Expected: ~80 GV forwards and ~200 messages a week across the five inboxes.

### 12.1 The phone digest reads this queue

`personal-secretary-mvp/scripts/owner_attention.py` (daily, `lpt-owner-attention.timer`) used to read
`owner-queue.py list --json` — decisions only by design — so every text, call, voicemail and email item
was invisible on the phone. It now reads `queue --json` (the one ordered working set) and maps both
field shapes.

Three things had to move with it, and each was found by running it rather than reading it:

* **non-numeric ids.** The one queue also carries held app rows (`m2631`) and agent questions, so
  `int(id)` raised and the whole digest died. The sort parses the id when it is numeric and uses 0
  otherwise.
* **the tail question.** The relay opens a reply turn only when the body ends in a question mark, so
  every item got " Yes?" appended. That is right for a decision and nonsense for news — the first dry
  run would have texted *"Chase: overdraft or declined transaction on account ...9730 Yes?"*. News now
  gets **" Want details?"**, decision keeps " Yes?".
* **`kind` never reached the composer**, so everything looked like a decision. It is passed through now.

The patch is `scripts/owner-queue/patch-attention-digest.py` — literal replacements plus an asserted
end state, safe to re-run. Verify with `python3 scripts/owner_attention.py send --dry-run` (it prints
the exact body and sends nothing).

## 13. Known limits — stated, not hidden

1. **Two rows for one ongoing problem** can still happen when a bank changes its wording ("overdrawn"
   vs "overdraft or declined"), because the fact key strips amounts and dates but not vocabulary.
   §9.1 closes the row once a *resolution* arrives from the same sender, which is the case that
   actually matters.
3. **The daily phone digest now reads this queue** (§12.1). It is the same one ranking, but it still
   composes its own one-line message and its own ordering ACROSS sources (obligations, waiting comms,
   email, the queue), so it is a delivery surface with a second sort, not a second queue. If it is
   ever made identical, it is by moving `pick_item`/`sms_body` behind this tool.
4. **Name resolution** for bare numbers depends on the comms index (`people` / `person_alias`). A stale
   index shows a known caller as a number.
5. **GV recall is capped by the mailbox window we ask for.** A forward older than that window is gone.
6. **The judge is a model, so it is not deterministic.** The cache means a message is judged once;
   `--rejudge` is for when the rubric changes, and it will move verdicts around.
7. **§9.1 only sees resolutions that ARRIVE as mail.** A premise that moved without a message (he paid
   the bill himself, a case was settled on the phone) is still invisible to the queue; `POSSIBLY MOOT`
   and `owner_premise_check` are the only cover.

## 14. Changelog

* **2026-10-18** — built: GV ingest, rules, ordering, `queue`/`show`/`knock`/`ingest`, the timer.
* **2026-10-18 (later)** — the email channel (judge + rubric + verdict cache), HTML stripping, fact
  keys, routine-notice digests, `urgent_email` dedupe, ordering v2 (derived money and deadline,
  decision weight, band-safe anti-starvation), the working set, `card`, `health`, `learning`,
  `owner_queue_feedback`, the recommendations-in-decisions rule, and the dossier.
* **2026-10-18 (last)** — the queue closes its own loops (§9.1): a later message from the same sender
  that says the problem is fixed resolves the alarm it refers to, with the reason recorded.
