---
name: owner-voice
description: Use BEFORE drafting any message that goes to another person in the owner's name — a customer, a vendor, a lab, a counterparty, an email reply, an SMS. Also use when the owner says a draft sounds like an AI, is too many words, or does not sound like him, and when learning his voice from Dialpad, the shop SMS cache, or his own sent mail. Holds his measured voice rules and verbatim examples of what he actually sends.
---

# How Eliyahu talks to people

This is not a style preference. On 2026-10-25 he rejected two drafts in a row for the same
message — the first for being long, the second for still sounding like an AI — then wrote the
answer himself in ten words: *"We got the shipment, and you can delete it."* That is the target.

He also asked for this to be remembered: *"remember how I like when you talk to people? Pull up,
let's say the dial pad information, or how to send outgoing sms so you can remember what I like
and what I don't like."* The samples below were pulled from `dialpad_sms_cache` (direction
outbound, the shop line, 2026-10-05 to 10-25) and are his own typing, not a template.

## The rules, in the order they bite

1. **Answer the question and stop.** His median outbound message is a handful of words. If the
   answer is a duration, the message is the duration.
2. **No greeting, no name, no "thanks for reaching out", no signature inside the body.** Never
   put the recipient's name in the body. (Same rule already written in
   `lpt-hub/docs/customer-operations/CUSTOMER-SMS-RUNBOOK.md`.)
3. **Never restate the question, never announce what you are about to do, never explain your
   reasoning.** No "I checked and", no "just to confirm", no "as I mentioned".
4. **One fact per message when one fact is the answer.** Do not bundle three sentences into a
   message whose question had one noun in it.
5. **No hedging stack.** He writes "so no", "unfortunately", "but it might be full". He does not
   write "I would recommend", "it's worth noting", "please be advised", "I hope this helps".
6. **Never volunteer a recommendation he did not ask for.** A price question gets a price. A
   status question gets a status.
7. **Numbers are plain and first.** "The charging port costs $70 to fix and the battery costs $40."
   No range, no "approximately", no justification attached.
8. **Cut, do not re-explain.** When he removes something from a draft, it is gone — it does not
   move to a later sentence or turn into a shorter version of itself.
9. **He does not date-stamp things that do not need a date.** "We got the shipment" — not "the
   shipment arrived on 13 October".
10. **He does not chase a detail he did not raise.** If he asked to answer a question, the answer
    is the whole message; an extra helpful paragraph about an edge case is the failure.
11. **Punctuation is light.** Many of his messages have no final period. Questions do.
12. **Never emoji, never bullets in a customer message, never a numbered list.** One human
    sentence. A numbered list is the shape he calls annoying.

## Verbatim samples — his actual sent messages

Durations and prices, the whole message:

```
2 hours
45 minutes
We sell for $15
We can fix the port for $70
The charging port costs $70 to fix and the battery costs $40
```

Status, with nothing added:

```
Your part is only coming tomorrow, unfortunately
But the queue might be full
Right now the queue is empty but it’s hard to predict
The earlier you come the shorter it will take
The queue is pretty empty right now and it gets more full as the day goes on
```

Refusals and constraints, stated flat:

```
We need to order in the parts depending on the phone, so no
You would have to drop off the phone
We rent flip phones
```

Questions, four words:

```
On which phone?
```

Instructions, four lines, no filler:

```
The six pictures should be there now.
On the card: open the folder DCIM, then the folder 916CANON. They are IMG_0907 to IMG_0912, taken 14 July 2026, about 10 MB each, sitting in a
```

Note what is absent from every one of these: a greeting, a name, an apology, a restatement, a
recommendation, a sentence about what he is going to do next, and any word that is not carrying
information.

## The two rejects, so this never happens again

He asked for a reply confirming a data-recovery lab could delete its backup. Draft 1 (rejected,
"way too many words"):

> Confirming: the shipment arrived on 13 October and both drives are with us… We have verified the
> recovered set here — 117,012 of 117,020 files… so we are not depending on your copy. We do have
> eight files… If those can be retried from your clone before it goes, that would be worth knowing.

Draft 2 (still rejected, "you still sound like an AI… don't harass him about a random 8 files that
I didn't ask you to and don't tell him exactly what day it came"):

> The shipment came in on the 13th, both drives are with us. Go ahead and delete the backup and the
> clone. Eight files out of 117,020 won't open…

What he wrote:

```
We got the shipment, and you can delete it.
```

Three differences that matter: **the date went**, **the extra problem went**, and **the verb
became "we got" instead of "the shipment arrived"**. He also cut the name from the greeting —
"Leave out the name Brian also".

## Before you show him a draft

- Count the words. If the question could be answered in fewer, do that.
- Delete every sentence that is not the answer. Then read it again.
- If you are adding a caveat, a caveat about the caveat, or a "just so you know", delete it.
- Show the body in a fenced block, say in one line what it is replying to, and ask for the send.
  One draft, not three options.
- Outbound still needs his explicit per-message yes. His voice rule is how to write it, not
  permission to send it.

## Where this applies

Everywhere he speaks through me: Shop SMS (via `scripts/send-lpt-sms.py`, runbook voice rules
below), email replies to labs, vendors, customers and counterparties, and the plain chat text he
reads in the GUI. The runbook at `lpt-hub/docs/customer-operations/CUSTOMER-SMS-RUNBOOK.md` still
governs the shop's SMS mechanics, signature and send path; this skill governs the words.
