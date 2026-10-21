# The decision queue's texter: three defects, and the asymmetry that hid them

Written 2026-10-21 ~01:15Z, ZABZ-TECH session, **read-only**. Nothing was edited, deployed,
restarted or sent, and no queue row was changed. This is a handover to whoever owns the owner
text channel.

It deliberately covers only what `docs/text-channel/STATE-2026-10-21.md` does **not**. That
document's F1–F8 describe the channel, `owner_message_queue`, the CFO and the store lock. None
of them describes the path from `owner_decision_queue` to a text, which is where these three
defects live.

---

## The symptom, and the measurement that exposes it

Owner, 2026-10-20: *"the questions getting asked to me in text are a different queue than the
regular queue."* He is right, and the reason is not cosmetic.

| what | measured | how |
|---|---|---|
| pending questions in `owner_decision_queue` | **96** (865 rows all time, oldest 32.3 days) | `python3 /root/bin/owner-queue.py health`, 00:56Z |
| questions `owner-ask.py` has ever texted | **0** | `sqlite3 ~/.owner-ask/asks.db "select count(*) from ask where sent=1"` |
| questions `decision-deliver.py` has ever sent | **0** | `sqlite3 ~/.decision-deliver/state.db "select count(*) from send"` |
| questions `cfo-ask.py` has texted | **15** | `sqlite3 ~/.cfo-asks/asks.db "select count(*) from ask where sent=1"` |

So every text he has received about money, tax or cards came from `cfo-ask.py` and the reminder
producers. The 96-row decision queue has never produced one, while its timer runs green every
30 minutes. `owner-ask.timer` is `active (waiting)`, last run 2026-10-21 00:43:21.

The service **exits 0 while refusing its own top item**:

```
gate: sent_today=0/2 hours=20:00 local candidates=97 kept=94
chosen: decision:511  The camera product's entire difference from what already exists is tha
--- body (152 chars, ceiling 160) ---
[q1792543401] The camera product's entire difference from what already exists. Ask one rav
you trust before I spend a dollar on this - one conversation,
--- end ---
GATE REFUSED this body - nothing was sent, nothing recorded:
   - it neither asks him anything nor tells him anything he can act on (152 characters)
   - carries a reference ([q1792543401]) but asks him nothing he can answer
```

(`journalctl -u owner-ask.service -n 12 --no-pager`, 00:43:21.) A refusal that exits 0, on a
timer, is indistinguishable from health from the outside. That is why this sat unseen.

---

## D1 — The asker texts rows the owner has explicitly parked

**Severity: highest of the three. It would send him a question he told us to hold.**

Row 511, read from `/root/authority.db`:

```
id             = 511
length(question) = 447
status         = pending
deferred_until = 2027-04-14T23:59:00+00:00
defer_note     = OWNER-INITIATED DEFERRAL, 2026-10-16. His words: 'these are decisions about
                 the product for next time i bring it up, they aren't pending owner decisions'.
                 So this row is NOT waiting on him - it is wai[t...]
severity       = high
```

`owner-ask.py:179-182` selects it anyway:

```sql
SELECT id, question, {rec} AS recommendation, severity, asked_at, status
  FROM owner_decision_queue WHERE status='pending' ORDER BY id
```

There is no `deferred_until` predicate, and none anywhere in the file:

```
$ grep -c deferred_until /root/bin/owner-ask.py      -> 0
$ grep -c deferred_until /root/bin/decision-triage.py -> 0
$ grep -c deferred_until /root/bin/decision-deliver.py -> 0
```

`decision-triage.py:650` has the same shape: `... FROM owner_decision_queue WHERE status='pending'`.
The new deliverer therefore inherits the bug — fixing only `owner-ask.py` fixes nothing once
`decision-deliver` is the sender.

**How many rows are affected:** 7.

```sql
select count(*) from owner_decision_queue
 where status='pending' and deferred_until is not null
   and deferred_until > date('now');        -- 7
```

**Why nobody saw it: the read path already gets this right.** `owner-queue.py` carries the rule
in its SQL — `owner-queue.py:1230-1231`:

```sql
CASE WHEN deferred_until IS NOT NULL AND julianday(deferred_until) > julianday('now')
```

So `card` and `queue` correctly skip or sink a parked row, while every program that can *send*
one ignores the column. The queue looks disciplined in every interface a human reads, and is
undisciplined in the only one that reaches his phone.

**Fix:** add the predicate to both senders, in the SELECT, not after ranking:

```sql
AND (deferred_until IS NULL OR deferred_until <= datetime('now'))
```

`ORDER BY id` is also worth re-examining while you are in there: the asker picks the **oldest
row**, not the ranked one. Whatever ranking the queue maintains is irrelevant to what he is
texted.

---

## D2 — The composer throws away the question

Row 511's stored `question` is not a fragment. It is a complete 447-character paragraph that
**ends in a real, answerable question**:

> The camera product's entire difference from what already exists is that it uploads the
> customer's photos to a cloud store we control - and every seller in this market advertises the
> ABSENCE of connectivity as the kosher feature (one of them calls local-only storage "actually a
> feature for many users"). Before we spend anything on it: **is a camera that uploads to the
> cloud acceptable, or should it be a camera that keeps everything on the device?**

`compose()` never uses that sentence. For a non-purchase row (`owner-ask.py:313-338`) it takes
the text *before the colon*, else the first sentence, caps it at 72 characters, strips trailing
coordinators and prepositions, then staples on the recommendation's first sentence. The question
is the one part it discards — the takeaway is a statement, and the gate then correctly refuses a
statement.

This is not a one-row problem: the composer is written to produce a *subject line plus a
recommendation*, and an asker that must end in a question cannot be built that way.

**Fix, in preference order:**

1. Take the **last interrogative sentence** of `question` (the text up to and including the final
   `?`) as the ask, and use the recommendation only if the result exceeds the ceiling — or not at
   all. If the interrogation does not fit in 160 characters, **refuse with a named verdict such as
   `NEEDS_REWORD`** rather than emitting a statement. A refusal that names its cause is a work
   item; a refusal that names a character count is a mystery.
2. If (1) leaves too many refusals, add a nullable `short_question TEXT` column that the producer
   fills when it files the row, and have the composer prefer it. That is a schema change and
   belongs to whoever owns `owner-queue.py`, not to the deliverer.

Note that this must not become a licence to reword history, and `amend` is right to refuse:
`owner-queue.py amend` *"TOUCHES CONTEXT AND RECOMMENDATION ONLY. The QUESTION is never
rewritten: that is what the owner was asked."* The composer is what must change, not the row.

---

## D3 — Two senders, two ledgers, one queue

```
owner-ask.timer         :13 and :43 every hour   -> owner-ask.py       ledger ~/.owner-ask/asks.db
decision-deliver cron   :00 and :30 every hour   -> decision-deliver.py ledger ~/.decision-deliver/state.db
```

Both select `status='pending'` from the same table. **Neither ledger can see the other's sends.**
`owner-ask.py` dedupes on `ask(source, source_id)`; `decision-deliver.py` writes `send(row_id)`.
The day either one starts sending, the same row can be texted twice in the same hour, and the
owner — who asked for *one question at a time* — gets two.

Today this is latent, not live: both are at zero. It becomes live the moment
`~/.decision-deliver/APPROVED` is created.

**Fix:** one sender. My recommendation is that `decision-deliver.py` is the queue's only sender
(it is the newer design, it paces, it ladders, it composes under a judge), and that `owner-ask.py`
stops emitting decision rows entirely while keeping its transaction generators, which are its own
value. If both must stay, the seen-ledger has to be shared — one table, written by both, keyed on
the row id — and the read of it has to happen in the same transaction as the pick.

---

## D4 — The repo copy of `owner-ask.py` is five days behind the one that runs

| file | md5 | size | mtime |
|---|---|---|---|
| `secratary-cloud:/root/bin/owner-ask.py` (deployed) | `98eb4a0682546af12a93d096b7fc9898` | 32,171 | 2026-10-21 00:13 |
| `harness-config/scripts/text-channel/mirror/owner-ask.py` (repo) | `641f09cce4df9d3ebfabd76c9b431009` | 31,490 | 2026-10-16 11:20 |

681 bytes of live change are not in the repo. Editing the repo copy and deploying it would
**revert tonight's modifications**; editing deployed only leaves the repo lying about what runs.

For contrast, the other two are in sync right now:

```
1c47c2188c2b02f11a6e14b781e16f3d  decision-triage.py   (repo == deployed)
d8fa9276514f9c51d27f79afab22b210  decision-deliver.py  (repo == deployed)
```

Take a diff of deployed against repo first (`diff -u` both ways), commit the deployed version as
the base, and then patch. Also, per `harness-config/AGENTS.md` §8, publish by atomic rename —
`cp -p f f.new`, edit, `bash -n f.new`/`python3 -m py_compile`, then `mv f.new f`. Truncating a
script in place while a timer may be executing it is how this estate has produced three rounds of
impossible diagnostics.

---

## How to prove a fix

1. **Deferral honoured, both senders:**
   ```bash
   ssh secratary-cloud 'sqlite3 /root/authority.db "select id from owner_decision_queue
     where status=\"pending\" and deferred_until > datetime(\"now\")"'   # the 7 ids
   ```
   then confirm none of those ids appears in `decision-triage.py`'s shortlist or in
   `owner-ask.py`'s candidate list, by running each in its dry-run mode and grepping for the ids.
   A fix that filters *after* ranking passes this test; a fix in the SELECT is the one to want.

2. **The composer emits a question or refuses by name:**
   ```bash
   ssh secratary-cloud 'python3 /root/bin/owner-ask.py --help'   # find the dry-run flag
   ```
   For a real row, the composed body must end in `?`, or the verdict must name the missing
   reword. A body ending in a full stop is a regression.

3. **One sender.** `systemctl list-timers owner-ask.timer` and the `decision-deliver` crontab
   entry must not both be able to emit a `owner_decision_queue` row. Prove it either by removing
   one, or by a shared ledger row that both read.

4. **End-to-end, deliberately, once:** with `APPROVED` present for exactly one message, send one
   question and read the `To` header back — `SENT` describes what we did with the message, not
   who received it. The owner's rule is a per-message yes, so this test needs his word for that
   one body.

---

## What would make this document wrong

- If `deferred_until` has been added to the two senders between 01:15Z and your reading, D1 is
  closed — check `grep -c deferred_until` on both deployed files before acting on it.
- If `owner-ask.timer` has been disabled, D3 narrows to a single-sender question.
- If the composer has been rewritten, D2's line numbers moved; the *shape* of the defect (a
  statement where a question belongs) is still the thing to test.

Every number above was read in this session, and no claim here rests on a previous session's
memory. Where a claim is about code, the line number is given so you can check it without
trusting me.
