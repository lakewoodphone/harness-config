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
| **His wife's mailbox** (`chevedy@gmail.com`) — mail addressed to her rather than to him | **NO** (owner, 2026-10-18: *"that was to my wife's email address, and that was to her, not to me"*) | `To:`/`Cc:` must carry one of his four addresses; her writing **to** him is still his |
| **Cold solicitation** — funding pitches, sponsorships, agency/SEO/service outreach from a stranger | **NO** (owner, 2026-10-18, twice: *"i don't need you to bring monthly sponsorships to my attention at all"*, *"exactly the kind of email I never want to see"*) | dropped with the reason `cold solicitation (<category>)`, kept in the mail store |
| App alerts the app never delivered (`owner_message_queue`, status `held`) | Read as items, except ops alerts and duplicates of judged email | read-only merge in the reader |
| Agent approval requests (`agent_questions`) | Read as decisions | read-only merge in the reader |
| Ops alerts (paused sync, stale capture) | No — they are mine to repair | counted, never shown as an item |

Both NO rows are enforced in code, not by intention (2026-10-19, `owner-queue-ingest-mail.py`):
the raw `To:`/`Cc:` are read **before** the verdict cache and the model, so a wrong cached verdict
cannot survive; her-address-only mail is refused as `not_owner`, and cold solicitation is dropped as
`cold solicitation (<category>)` while the message itself is kept. Measured on the authority's
01:25:43Z run: fetched 178, queued 13, dropped 152 — of which **38 were not-the-owner** — 0 errors.
The reasons are stored in `owner_queue_ingest_run` as a breakdown of `dropped`, so
`fetched = dropped + queued + folded` still holds and the refusals are countable rather than
invisible. Mail addressed to **both** him and her still qualifies as his, deliberately: erring toward
showing him is the cheaper mistake of the two.

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

**DROP**: shortcode senders (17) · daily zmanim/candle-lighting (13) · empty or receipt-only (7) ·
vendor robots (5) · one-time codes (3) · **our own alert texts** (2) · order & parcel lifecycle (2) ·
carrier data notices, toll-free marketing, robocall voicemail, voicemail with no transcript.

**Two rules were wrong, and were corrected 2026-10-18 after reading what they discarded:**

* **A community announcement is not marketing.** *"Igud Talmidei Fallsburg: Nichum Aveilim Hours"*
  and a *Baruch Dayan HaEmes* levaya notice were dropped as `bulk sender in body`, because the
  community-announcement test ran *after* the bulk-sender test. Those are the notices a person acts
  on in this community. The announcement check now runs first, and folds them into one row a week
  per sender.
* **An unknown missed call is not nothing.** Seven in seven days were dropped as "nothing to act
  on" — a judgement that is mine, not his, and he runs a shop. They now fold into **ONE row a
  week** that names every number: *"6 missed calls this week from numbers not in your contacts:
  (201) 566-7852 | (310) 270-6991 | …"*. He rings back the ones he recognises. Nothing dropped,
  nothing flooded.

**DIGEST**: twelve or more messages from one sender in the window is a relay; they fold into **one row
per sender per ISO week** carrying a count, the speakers and any actual question.

**ATTENTION**: a person asking him something · a named missed call · any voicemail that survives the
robocall test (callback + a real name ⇒ `critical`) · a personal message with a date or a sum.

**DECISION**: only when the message asks him to choose, approve or commit.

Two traps that cost real time and must not come back: `contact_name` vs `name` key mismatch (dropped
every item as nameless), and `not name` dropping real people who are simply not in his address book.
A 4-6 digit *name* is a shortcode; a bare *number* is a person.

### 4.2 Email — a model judges, against a written rubric

**Which mail it may see, and the correction that mattered most.** The query was
`in:inbox newer_than:Nd`. Measured 2026-10-18 over one week: **223 messages in the inbox, 385
outside it and never judged** — 99 on his personal account, 178 on the shop account. Gmail filters
auto-archive receipts, invoices and notifications before he ever sees them, so a bill could live
entirely in a label and the queue would never have read it. A folder boundary is not a judgement
about relevance, and judging relevance is the queue's whole job. The window is now
**`newer_than:Nd -in:spam -in:trash`**; on the first widened run a supplier's return-instructions
request arrived that the queue had never seen. Spam and trash stay out on purpose.

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
        (a DIGEST gets a quarter of that: a folded summary is not a bill)
      ± learned adjustment                     signed, what his own answers taught (see §6)
      - 200 if the row named a day that has passed (POSSIBLY MOOT)
```

Three things this got wrong first, each measured on the live queue before it was fixed:

* **`meta.money` was NULL on every single pending row**, so the money term had never fired once — a
  returned payment of 2 380.06 ranked below a ten-day-old voicemail about a laptop. The amount is in
  the words; `_money_in()` reads it there, which also fixes every historic row at once.
* **`deadline` matched the word "today"**, so "any way I can get my phone today?" earned a deadline
  bonus. A day is named; a deadline is stated — `due in`, `expires`, `overdue`, `suspended`,
  `deadline`, `final notice`, `by <weekday>`, `in N days`.
* **A digest was scoring as if it were a bill.** *"5 notices: Amex snapshot 1,965.08 · $53 PayPal
  charge"* earned `money=+196` off the largest number in its own summary and outranked a person
  waiting for an answer. Nothing is owed on a summary; the amounts in it are the subject matter. A
  folded row now carries a quarter of the money weight and says `(digest, quarter weight)` in its own
  arithmetic.

Nothing reads a stored score. A score written at insert time goes stale the moment the ingest stops,
and then the order is a claim about urgency that nothing re-measures.

## 6. It learns — from his answers, and it says what it learned from

Owner's requirement, 2026-10-18: *"the queue needs to learn over time what to put in it and what to
prioritize ... based on my responses to the queue"*. Boring and auditable: no model in the ranking,
no stored score, and **every adjustment prints its own evidence count**.

1. **Every close writes one feedback row** — `answer` / `resolve` / `defer` / `skip` all write it, so
   the record cannot drift from the queue it describes.
2. **The profile is read along four dimensions**: `party` (who), `domain` (which company), `class`
   (`notice`/`money`/`person`) and `channel` (`email`/`sms`). Each is a way of saying *"this kind of
   thing"*, and his instruction had two halves — what to put in it, and what to prioritise.
3. **It is SIGNED.** A kind he dismisses **sinks**; a kind he always acts on **rises**. A queue that
   can only punish eventually shows him only the least offensive mail.
4. **Per-dimension floors and caps** — the wider the bucket, the more evidence it needs and the less
   it may move: a sender needs 3 closes and may move ±160/90; a class needs 8 and may move ±80/50; a
   whole channel needs 10 and may move ±60/40. **Measured 2026-10-18** by running the profile over a
   simulated session: four dismissed emails produced `channel email −96`, which would have demoted
   every email for 120 days, including a suspended phone line. A broad bucket cannot carry a narrow
   conclusion.
5. **Only his verbs count.** `answered` 1.0 · `dismissed` 1.0 · `skipped` 0.5 · `deferred` 0.3.
   `resolved` contributes **nothing**: of 559 closed rows on the record, **442 were `resolved`** and
   the sample showed them closed by *me* under the standing autonomy rule and by the queue's own
   loop-closing. Counting those as "he acted on it" would have taught the queue that everything it
   auto-closes is something he loves.
6. **Retired surfaces are excluded.** Of the 111 answered/dismissed rows, almost all are
   `owner_message_queue #NNNN` — the app's held-alert table, which the mail judge has made redundant
   (that is why the reader drops held rows the judge already judged). Teaching "email sinks" from a
   dead surface would demote the live channel on false evidence. `learning` prints the split:
   *"evidence: N from a channel that still writes; M from retired surfaces (excluded)"*.
7. **The judge is told both shapes.** It gets his last dozen answers verbatim (`WHAT HE HAS ALREADY
   SAID`) **and** the aggregate profile (`WHAT HIS OWN ANSWERS HAVE TAUGHT ABOUT WHO AND WHAT`), with
   the evidence count beside each line. Examples alone make a judge overfit to the last twelve items.

**The loop had never run at all.** Measured 2026-10-18: `owner_queue_feedback` held **2 rows**
against **553 closed queue rows**, because `learning` opened the database **read-only** and the writer
caught its own error and reported "0 learned" — which is indistinguishable from "there is nothing to
learn from". `learning --backfill` now copies every close already on the record, idempotently, and
recovers the channel and party from the `source` string, since the old writer stored neither.

To watch it learn: `owner-queue.py learning` — what rises, what sinks, the count behind each, and how
much of its evidence is still live. `learning --backfill` first, once.

## 7. Every item arrives briefed

Owner's requirement: *"only put it in the queue after all info is gathered about it fully"*. What a
row carries when it lands, and what `show`/`card` print:

| Part | Where it comes from |
|---|---|
| The one-line title | the judge (email) or the parsed message (Voice) |
| **Why it is in the queue** | the judge's reason, stored with the verdict |
| **What he would do** | the judge's `action` |
| **My recommendation** (decisions) | the judge's `recommendation`, or one derived from the evidence row |
| The full text | the message body, HTML stripped (email) or the cleaned transcript (Voice) |
| **What the record behind this says** | joined live from `Evidence: <table> row <id>` — balance, due date, what has already been paid, where the figure came from |
| **History with this sender** | closed queue items from the same *identity*, with his own past answer |
| **Also in this item / probably the same matter** | rows folded in by proof, and rows to close in the same breath |
| Thread state | how many messages in the conversation, and which is newest |
| Amount, deadline, tier | read from the one-liner at rank time, so they cannot go stale |
| **POSSIBLY MOOT** | added when the row named a relative day that has passed |

A decision without a recommendation is a **defect**, not a nicety: he asked to answer without going
and looking anything up.

### 7.1 The gate: an unbriefed question does not go on his desk

**Measured 2026-10-18 on the row at the TOP of his queue** (#698, `critical`, a decision):

| What the card said | What the database held |
|---|---|
| *"Obligation OVERDUE: Landlord utilities — unpaid household balance — decide: pay it or dispute it?"* | balance **269.71** (electric 214.18, gas 55.53) |
| options: `1) Investigate it and bring me a recommendation 2) Leave it for now 3) Not actionable` | four bills, arriving 2026-09-22, 2026-10-06 and 2026-10-11, **none of them paid** |
| my recommendation: *option 1*, i.e. the item asking itself to do its own work | the ledger path, and the screenshots the figure came from |

The sweep filed a question it already had the answer to, and the card asked him to decide with less
information than the table held. Three repairs, all at READ time so they fix every historic row:

1. **Enrich.** A row whose context cites `Evidence: <table> row <id>` is joined to that row and the
   fields that answer *how much, to whom, when, what happens if I do nothing* are printed on the
   card. sha256 receipts are stripped; a path a person can open is kept.
2. **Replace a template recommendation.** `Investigate it and bring me a recommendation` is not a
   recommendation. When the evidence carries a balance and a due date, the recommendation writes
   itself: *"Pay 269.71 — nothing has been paid against it, 26 days past due; the balance is already
   established in the record."* The template options are replaced with it.
3. **Gate.** A **queue-surface decision** with no recommendation, or with no amount/date/named party,
   is **held out of the working set and counted** — *"5 decision(s) held back while I gather the
   facts — you should not have to decide something I have not briefed"*. Never presented, never
   deleted. Agent approval requests are exempt: they are the agent's to brief, and hiding a live
   approval behind a rule this tool cannot satisfy would be worse than showing it thin.

Three of these were wrong on the first build and are worth not repeating:

* **History matched on the mail domain**, so a card for his wife's grocery request listed four Telnyx
  and Chase items as "history with this sender" — `gmail.com` is not an identity. For freemail
  domains the **full address** is the identity; for a company the domain is. A false provenance claim
  is worse than no history.
* **The amount was read from the whole message**, so a grocery order scored `money=+200` off the
  prices of the items in it and outranked a suspended phone line. Money comes from the judge's field
  or its one-liner, **never from the body**.
* **A person's text was filed as a formal decision.** `Text from Genack: Can I purchase a Kyocera
  today?` arrived as `kind=decision` with no recommendation, and the gate then held it back for a
  recommendation nobody could give. A message from a person is a message with a reply owed — it
  already carries `ask=+80` — so a text-derived decision with no recommendation is **demoted to
  attention at read time**, and says so.

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
* **A decision that has not been briefed is held back too** (§7.1), and counted by name.

## 8.1 One fact, one row — collapsed at READ time

**Measured 2026-10-18 on the live 74-row queue**, and it is the defect he would feel first, because he
knocks this out once every other day and cannot answer the same thing three times:

| One fact | The rows it occupied |
|---|---|
| Techloq filter auto-renews 36.99 | #680 (its own row), #647 (inside a money digest), #688 (inside a notice digest) |
| the LPT referral list | #687, #642, #643 |
| NJ tax payment confirmation | #626, #675 — two digests carrying the same member |
| the 300DDR recovered drive | #693 (the mail), #646 (the agent's question about it) |

Never fixed by de-duplicating at INSERT time, for the same reason nothing reads a stored score: the
digests are written per (class, day), the same message gets judged into two classes on one day, and a
row written yesterday is still the same fact as today's. Collapsing at read time repairs every
historic row at once and cannot go stale. Three rules, in order of how much they guess:

* **A. Same message — proven.** Two rows carrying the same `(account, thread_id)` are the same
  message. #643/#687 were one email judged twice into two classes (`person` and `notice`), so
  `key_for` gave it a thread key *and* a fact key and both landed. The better-ranked row keeps it and
  carries the other's words.
* **B. A decision absorbs attention about the same matter** — either the same shop reference
  (`300DDR`, `case 4485`) or the same party names plus two shared subject words. He does not need to
  read the notice and then answer the question about the notice.
* **C. A digest loses every member a real row already owns**, and a digest of one becomes that one. A
  digest that keeps nothing disappears, because every member is present elsewhere.

**Probable-but-unproven siblings are never merged.** A wrong merge hides an item, which is the one
failure this queue cannot afford. They are *shown* on the card — `PROBABLY THE SAME MATTER — answering
both in one go is: add --with 631` — and `answer`/`resolve` accept `--with` so one sentence closes the
cluster, recording on each row that it was answered together.

A first attempt at this was **wrong and was thrown away**: matching on `party` + `channel` made every
pair of missed calls share the tokens `{call, missed}`, so *"Missed call from Parsons"* and *"Missed
call from Mogo"* were proposed as one fact. A token that every row of a class carries identifies
nothing; the entity tokens come from the party alone.

**But the party IS the thread — added 2026-10-19, on the owner's words *"You shouldn't have given me
the info about the missed calls without the text."*** Two rows from the **same party inside 24 hours**
are one matter whatever the channel: Genack sent two texts (`#817`, `#818`), a missed call (`#819`) and
a voicemail (`#828`) inside three and a half hours, and the card showed him the voicemail and the
missed call while the two rows carrying the actual request sat unseen — because a voicemail and a text
from one person share no words. `_party_key()` normalises `Genack.` == `Genack` == `genack` and matches
two numbers on their last ten digits; `SIBLING_PARTY_HOURS = 24.0`; `_hours_apart()` reads the event
stamp. Still advisory — it proposes `--with`, never merges, so a wrong proposal cannot hide an item. The
card also prints a **text** sibling whole rather than cutting its title at 88 characters, because the
words are what he acts on.

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

### 12.0 Freshness is not completeness, and the difference is a whole mailbox

Both ingests write their own arithmetic to **`owner_queue_ingest_run`** — `fetched`, `queued`,
`dropped`, `new`, `refreshed`, `errors` — and `health` prints a row per source:

```
gv read everything         26       0.0h       48h  OK (10 folded)
mail read everything      180       0.0h       48h  OK (22 folded)
```

`fetched − dropped − written` is the **fold** — twelve texts in one family chat becoming one row is
the design, not a loss — and it is reported, never failed on. What fails the check is a run that
reported errors, a run older than 48h, or arithmetic that comes out **negative**, which is a bug and
must not be silently clamped. Without this line, "18 rows arrived" is compatible with "62 items were
never read", which is exactly what the `in:inbox` window was doing (§4.2).

Expected: ~80 GV forwards and ~350 messages a week across the four judged accounts (the widened
window sees roughly twice what the inbox-only query did).

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
   §8.1 collapses what it can prove, and *shows* what it can only suspect; §9.1 closes the row once a
   *resolution* arrives from the same sender, which is the case that actually matters.
2. **The learning has no live evidence yet.** `learning` says so in as many words: of 111 answered or
   dismissed rows, **0 come from a channel that still writes this queue** — they are all
   `owner_message_queue` held alerts from a surface the mail judge replaced. The mechanism is proven
   (a simulated session moves a sender −96 and another +48, and a broad channel is correctly held
   below its floor), but the first real teaching is the first knock-through after 2026-10-18.
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
8. **The widened mail window costs more model calls** — roughly twice the messages, so roughly twice
   the batches. The verdict cache means each message is paid for once, and the per-run cap
   (`MAX_JUDGE_PER_RUN`) leaves the rest for the next run rather than dropping them.
9. **A digest of one loses its count.** "1 notice (2026-10-14): X" becomes "X", which is correct but
   loses the fact that three others were folded away beside it. The folded members are still on the row.

## 14. Changelog

* **2026-10-18** — built: GV ingest, rules, ordering, `queue`/`show`/`knock`/`ingest`, the timer.
* **2026-10-18 (later)** — the email channel (judge + rubric + verdict cache), HTML stripping, fact
  keys, routine-notice digests, `urgent_email` dedupe, ordering v2 (derived money and deadline,
  decision weight, band-safe anti-starvation), the working set, `card`, `health`, `learning`,
  `owner_queue_feedback`, the recommendations-in-decisions rule, and the dossier.
* **2026-10-18 (last)** — the queue closes its own loops (§9.1): a later message from the same sender
  that says the problem is fixed resolves the alarm it refers to, with the reason recorded.
* **2026-10-18 (audit round, this version)** — five defects found by measuring the live queue, not by
  reading the code:
  * **§8.1 one fact one row** — collapse by message identity, decision absorbs notice, digest loses
    what a real row owns, siblings shown and closed with `--with`.
  * **§7.1 the dossier and the gate** — evidence rows joined live, template recommendations replaced,
    unbriefed decisions held back and counted, person-texts demoted to attention.
  * **§6 learning** — four dimensions, signed, per-dimension floors and caps, his verbs only, retired
    surfaces excluded, `learning --backfill` (the loop had written 2 rows against 553 closes because
    the connection was read-only).
  * **§4.2 the whole mailbox** — `-in:spam -in:trash` instead of `in:inbox`; 385 messages a week were
    invisible.
  * **§4.1 two GV rules corrected** — community announcements are not marketing; unknown missed calls
    fold into one weekly row instead of being dropped.
  * **§5 digest money weight**, **§12.0 run arithmetic in `health`**.
* **2026-10-19 (the rows that were invisible)** — measured on the live queue: 79 pending, and
  **eight of them reachable only with `--all`**, held by probes that had answered a neighbouring
  question. Four fixes, all verified against the real rows before they shipped:
  * **personal Google Voice is not Dialpad** — `customer-contact` read `dialpad_sms_cache` for
    every row, so five personal texts (two from Zellie, two from Genack, a pidyon-haben
    invitation) came back `unknown` and never reached him, and two more were called
    `PREMISE MOVED` against a business number that happens to share digits. A `gv-ingest` row is
    now declined by that probe, and `_premise_hold` no longer gates personal comms at all: a text
    is news, not a claim about a business record.
  * **"already sent" must mean *we* sent it** — the probe matched the *account* as well as the
    sender, so any inbound vendor mail in our own mailbox counted as a reply. Three 300DDR rows
    (tickets 73459 / 73896 / 74115) were held as "approval moot"; 74115 had never been answered.
    It also matched on snippet, where a pasted JotForm prefill looked like a reply. Now: sender
    only, subject only — and a clean read that finds no outbound answers **fresh**, because that
    negative is the measurement.
  * **a record is located from the row's own words** — `work-order` and `customer-contact` both
    took a phone number out of the quoted mail underneath the row. `(323) 230-0622` and
    `800-437-5556` are switchboards in a signature block; production was read for them, failed,
    and held two live rows as `unknown`. The number now comes from question/options/recommendation,
    and a toll-free number is never a customer's device.
  * **`sweep` crashed under the 20-minute ingest lock** — the connection had the default 5 s
    timeout. 30 s busy timeout; a sweep is idempotent, but a crash mid-sweep is still a crash.
  Closed on the evidence, not on age: **#640** and **#693** (he had replied to both 300DDR tickets
  himself; the vendor acknowledged and then said the backup was gone), **#682** (folded into #726 —
  the same order 108746338), **#685** (already carried by the money digest #676). Briefed and
  released: **#805/#806/#807**, the anti-reset trio, which the dossier gate was hiding for want of
  a number — the recommendations now carry the 30-seat trial and ~$7/device/3yr from
  `ANTI-RESET-ARCHITECTURE.md`.
  Also migrated: **16 tasks assigned to `owner`** that had been sitting in `tasks` for up to 14
  days were each checked against the queue row that had already answered them and closed with a
  pointer — the queue is the one list, and a task table nobody reads is a second one. One live
  item that existed nowhere was filed as **#822** (Moishe Bachrach: two emails asking for a call,
  nothing out since 2025-09-15).
  **The rule this audit adds:** a probe may only read (a) the record the row *names* and (b) the
  row's own words. An evidence blob pasted under the row is the counterparty's text, not ours.
