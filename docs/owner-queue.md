# The owner queue

**One table, one order, two kinds of thing.** Everything that needs Eliyahu — a decision only he can
make, and anything from his personal texts, calls and voicemails that he would want to know about —
lives in `owner_decision_queue` on the authority and comes out of one command in one order.

Written 2026-10-18, after he corrected a session that had started building it on the shop's telephone
line. Read the "His words" section before changing any rule here.

---

## 1. His words — the law this serves

> *"make sure it's one queue that has everything that I need to know or needs my either one ... any
> email or text that you deem worthy of my attention or something I might want to know should be in
> the owner queue ... once in a while I'm going to ask, hey, let's go through the queue or let's
> knock out the queue and you just tell me things one at a time. A mix of stuff that were emailed or
> texted. They don't specifically need my decision, but I would want to know about and also stuff
> and need my decision from."*

And the correction, same day, which overrides every earlier assumption:

> *"dial pad calls sms and voicemail do not count. I only want personal ones ... Google voice numbers
> and you do have access to my Google voice numbers because they get forwarded to my email ... The
> dial pad is not relevant to my queue And you can access my goal of voice through my emails."*

## 2. The channel law

| Channel | In the queue? | How it is reached |
|---|---|---|
| **Google Voice** texts, missed calls, voicemails | **YES — this is the queue's personal channel** | Forwarded mail: `voice-noreply@google.com`, `txt.voice.google.com` |
| Personal Gmail | Partly — the same forwards arrive as mail | `gmail_service.search_messages` |
| **Dialpad** (shop line: calls, SMS, voicemail) | **NO. Never.** | — |
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
Gmail (2 accounts, GV forwards)
   │  gmail_service.search_messages + read_message          ← the only live reader
   ▼
gv_email_handler.parse_gv_email                            ← reused, never re-implemented
   │  type ∈ {sms, missed_call, voicemail}
   ▼
classify()  →  DROP | DIGEST | ATTENTION | DECISION        ← the rules in §4
   ▼
collapse()  →  one row per thing, not per message          ← relays, repeats, same-day calls
   ▼
owner_decision_queue  (kind='attention' | 'decision')      ← THE one queue
   ▼
owner-queue.py queue / knock                               ← one order, one item at a time
```

`owner-queue-ingest-gv.py` runs under the app venv because it imports the app's Gmail client and the
app's GV parser. It **chdirs to the app root**: `gmail_service._tokens_dir` defaults to the *relative*
path `data/gmail_tokens`, and a run from `/root` reports every account "not authenticated" while the
tokens sit in the checkout — measured 2026-10-18, and it looks exactly like a credential outage.

## 4. Triage rules, and what each one actually caught

Corpus for tuning: **624 GV forwards over 45 days** (538 sms, 66 missed calls, 20 voicemails), and
**166 over 14 days**. Every rule below exists because that text was in front of me, not because it
seemed sensible.

**DROP — never shown.** A queue that shows these is the same as no queue. Counts are the measured
`--explain` tally over the **14-day** window: 166 forwards read → **34 queued**, **73 dropped**,
59 folded into digests.

| Rule | Why | 14d |
|---|---|---|
| shortcode senders (4-6 digit caller-ID) | bulk | **17** |
| daily zmanim / candle-lighting alerts | scheduled, knowable from a calendar | **13** |
| missed calls from a number with no name, no voicemail, no text | nothing to act on | **13** |
| empty / receipt-only ("MMS Received", "Test sms") | no content | **7** |
| bulk sender named in the body prefix (caller-ID is just a number) | marketing | **6** |
| vendor robots ("we just emailed you an update that requires your response") | the email is the item, not the notice of it | **5** |
| one-time codes / verification / "531021 is your GitHub code" | account security, not news | **3** |
| **our own alert texts** ("Google Voice monitoring is blind", "Reminder: PAY ...") | a queue that shows him our alerts is a loop | **2** |
| order & parcel lifecycle (shipped / tracking / proof of delivery) | he does not need to be told a parcel moved | **2** |
| carrier data-usage notice · toll-free marketing · robocall voicemail · voicemail with no transcript · bulk sender by name | | **1 each** |

**DIGEST — folded into one row.** A group relay is one thing happening, not 179 messages. Twelve or
more messages from one sender in the window makes them a relay; their messages fold into **one row per
sender per ISO week**, carrying a count, the speakers and any actual question. Simcha/levaya broadcast
listings fold the same way unless they are addressed to him — the test is the ask, not the vocabulary.

**ATTENTION — its own row.** A person asking him something; a named missed call; any voicemail that
survives the robocall test (callback + a real name ⇒ `critical`); a personal message with a date or a
sum of money in it.

**DECISION — its own row, `kind='decision'`.** The message asks him to choose, approve or commit, and
carries a question or a sum. This is the only path by which a text can become a decision.

## 5. The one ordering

Every reader uses one function, `_queue_score`, and **every line prints its own arithmetic** so the
order is judgeable rather than asserted:

```
score = tier                       critical 1000 · high 700 · medium 400 · low 150
      + 200 if it blocks other work
      + min(200, age_hours / 6)     anti-starvation: old things rise, capped
      + 40  if it arrived in the last 24h
      + 80  if a person is asking him something
      + 60  if it names a deadline
      + min(150, money / 10)        judged: 2026-10-18
```

Example, from the live queue: `#595 Can I purchase a Kyocera today?` = `high=700 age=+23 asks=+80
deadline=+60` → **863**.

Nothing reads a stored score. A score written at insert time goes stale the moment the ingest stops,
and then the order is a claim about urgency that nothing re-measures.

**Age bound.** Attention older than 21 days is hidden by default (`--max-age-days`, `--all` shows it)
and the hidden count is printed. News decays; a text from three weeks ago is still true but is not
what he should open the queue on. **Decisions are never aged out** — they block work until answered.
Nothing is deleted or closed by the bound.

## 6. Lifecycle, and why a dismissal sticks

`pending → seen (seen_at) → answered | resolved | dismissed | deferred`

* `dedupe_key` is **UNIQUE**, keyed on the message id (not the thread — two texts in one thread are
  two things said; keying on the thread made the second silently overwrite the first, measured as
  4 refreshes on the first backfill).
* Re-running the ingest **refreshes** a pending row and **never resurrects** a dismissed or answered
  one (`left_closed` in the run report). That is the dismissal memory the app's own attention tables
  never had — they re-appended every fingerprint on every run.
* `defer`/snooze keeps the row pending and stops it ranking until the day he named.

## 7. Commands

```bash
# the queue — one order, both kinds
python3 ~/bin/owner-queue.py queue --limit 20
python3 ~/bin/owner-queue.py queue --kind attention --new-only
python3 ~/bin/owner-queue.py show 591            # one item in full + the arithmetic; marks seen

# "let's knock out the queue" — one at a time, until it is empty
python3 ~/bin/owner-queue.py knock

# pull the personal channel (the timer also runs this every 20 min, --days 3)
python3 ~/bin/owner-queue.py ingest gv --days 3
python3 ~/bin/owner-queue.py ingest gv --days 14 --explain    # every verdict + per-rule tally, writes nothing

# decisions only — the raw table, and what the phone digest reads
python3 ~/bin/owner-queue.py list
```

`knock` verbs: `a <answer>`, `d [why]` dismiss, `s 3d` snooze, `n` skip, `q` quit — and **a bare
sentence is taken as the answer**, because he should not have to learn a syntax to reply.

## 8. Is it alive?

Three readings, and each answers a different question:

```bash
# 1. is the timer scheduled and did the last run succeed
ssh secratary-cloud 'systemctl list-timers lpt-owner-queue-gv.timer --no-pager'
ssh secratary-cloud 'systemctl status lpt-owner-queue-gv.service --no-pager | head -8'

# 2. is the queue actually receiving (newest attention row, and how many)
ssh secratary-cloud "sqlite3 /root/authority.db \
  \"SELECT COUNT(*), MAX(created_at) FROM owner_decision_queue WHERE source LIKE 'gv-ingest:%'\""

# 3. is GV still forwarding at all — the source, not the reader
ssh secratary-cloud 'cd /root/personal-secretary-mvp && ./.venv/bin/python -c "
import sys; sys.path.insert(0,\".\")
from app.services import gmail_service; from app.config import settings
print(len(gmail_service.search_messages(settings, account=\"eliyahuzabrowsky@gmail.com\",
      query=\"from:txt.voice.google.com OR from:voice-noreply@google.com newer_than:7d\", max_results=500)))"'
```

A queue that has stopped filling and a queue with nothing to say look identical from inside the
table. Reading the *source* is what tells them apart. Expected: ~80 forwards per week on the main
line.

## 9. Known limits — stated, not hidden

1. **Non-Voice email is not in this queue yet.** The queue covers GV texts/calls/voicemails. Ordinary
   Gmail reaches him through `scripts/owner_attention.py` (`from_email_catalog`, which already has
   `personal_accounts()` / `is_bulk_sender()`). Folding that into the same table is the next step and
   is *not* done.
2. **`scripts/owner_attention.py` still ranks independently for phone delivery**, reading
   `owner-queue.py list --json`, which is deliberately decisions-only. Two rankings exist in the
   estate: this one, and that one. If they are ever made one, it is by pointing that script at
   `queue --json`, and its parser must be adapted in the same change.
3. **Name resolution** for bare numbers depends on the comms index (`people` / `person_alias`). If the
   index is stale, a known caller appears as a number.
4. **GV recall is capped by the mailbox window we ask for.** A forward older than the mail retention
   window is simply not there.

## 10. Changelog

* **2026-10-18** — built. Ingest, rules, ordering, `queue`/`show`/`knock`/`ingest`, the timer, this doc.
  `owner-queue.py list` narrowed to decisions so the phone digest was not flooded by the new rows.
