---
name: owner-queue
description: Use whenever the owner asks to go through, knock out, clear, review or open his queue, asks "what needs me", "what's waiting on me", "anything I should know", or asks about a decision he owes — and BEFORE answering any question about his personal texts, calls, voicemails or email. The queue is the single list of everything that needs him, and it must be worked one item at a time, never as a list. Also use when filing something into the queue or when a queue item needs closing.
---

# The owner queue — one item at a time, fully briefed, and it learns

`owner_decision_queue` on `secratary-cloud` is the **one** list of everything that needs Eliyahu: a
decision only he can make, and anything from his personal texts, calls, voicemails or email he would
want to know about. The rule set is `harness-config/docs/owner-queue.md` — read it before changing a
rule. This skill is the procedure for *using* it.

## When he says "let's knock out the queue"

```bash
ssh secratary-cloud 'python3 /root/bin/owner-queue.py card'
```

That prints **one** item: the why, what he would do, my recommendation, the full text, history with
that sender, and the arithmetic behind its rank. Then:

1. **Tell him that item, in plain chat text.** Two or three sentences: what happened, who from, why
   it is in the queue. For a decision, end with **my recommendation in one line** — it is already in
   the row under "MY RECOMMENDATION"; do not re-derive it, and do not invent one.
2. **Wait.** Never send two items in one message, never a list, never a table of items. If he asked
   for the queue and you answer with ten bullets, you have failed the instruction even though every
   bullet is correct.
3. **Record his answer, verbatim**, then fetch the next one:
   ```bash
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py answer 651 --answer "yes, order it"'
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py resolve 651 --dismissed "not mine"'
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py defer 651 --until 2026-10-25 --note "after yom tov"'
   ```
   His words are the training data and the journal copy — never paraphrase them into the answer.
4. Stop when he says stop, when `card` says the queue is empty, or after about 25 items.

## Hard rules

- **A POSSIBLY MOOT line means check the premise before you speak.** The row itself is telling you the
  day it named has passed; re-measure, then either close it yourself or say what happened.
- **Never ask him something the row already answers.** The dossier is there so he does not have to
  work; if the number he needs is missing, gather it first and put it in the row.
- **A decision without a recommendation is a defect.** File it with one (`add --recommendation`).
- **Anything you can do yourself does not belong in the queue.** Solve it; a row is an admission that
  you could not.
- **Dialpad is never in this queue.** The personal channel is Google Voice, reached through its
  forwarding mail. His own inboxes are judged separately. If you are reading `dialpad_*` tables to
  answer a queue question, you are reading the wrong lineage — stop.

## Reading state without the card

```bash
ssh secratary-cloud 'python3 /root/bin/owner-queue.py queue --limit 15'   # the working set, ranked
ssh secratary-cloud 'python3 /root/bin/owner-queue.py queue --all'        # including what is held back
ssh secratary-cloud 'python3 /root/bin/owner-queue.py show 651'           # one item in full
ssh secratary-cloud 'python3 /root/bin/owner-queue.py health'             # is it still being fed
ssh secratary-cloud 'python3 /root/bin/owner-queue.py learning'           # what his answers have taught it
```

**A queue with nothing in it and a queue that stopped being fed look identical from inside the table.**
`health` is the difference; it exits non-zero when a source has gone quiet, and the 20-minute timer
(`lpt-owner-queue.timer`) runs it after every ingest.

## Filing something new

```bash
# text never passes a shell
ssh secratary-cloud 'python3 /root/bin/owner-queue.py add --from-json -' <<'JSON'
{"question": "...", "context": "...", "options": ["..."], "recommendation": "...",
 "severity": "medium", "blocks": "...", "domain": "owner"}
JSON
```

`domain` defaults to `owner`; `customer`, `business` and `engineering` are refused on purpose —
those belong in the ledger, not on his desk.
