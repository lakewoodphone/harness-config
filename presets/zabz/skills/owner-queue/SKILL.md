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

That prints **one** item: the why, what he would do, my recommendation, the full text, the record
behind it, history with that sender, and the arithmetic behind its rank. Then:

1. **Tell him that item, in plain chat text.** Two or three sentences: what happened, who from, why
   it is in the queue, and the number that matters (from the card, never from memory). For a decision,
   end with **my recommendation in one line** — it is already in the row under "MY RECOMMENDATION";
   do not re-derive it, and do not invent one.
2. **Wait.** Never send two items in one message, never a list, never a table of items. If he asked
   for the queue and you answer with ten bullets, you have failed the instruction even though every
   bullet is correct.
2b. **The instant an item needs investigation, it leaves your hands — and the queue does not wait.**
   His rule, 2026-10-19, after watching me go quiet twice in one evening to read commits and hunt for
   a credential: *"if there is work to do to figure this out you pass it off to a subagent to do teh
   heavy lifting and move on to the next thing with me in teh meantime, you keep forgettting."* So:
   one `subagent` call (the MESH — never a local fork while the mesh is reachable), a full
   self-contained brief, `run_in_background: true`, and the **very next command is
   `owner-queue.py card`**. Say in one line what you handed off and that you are moving on; never
   narrate the investigation in the conversation, and never leave him waiting while you look
   something up. When the subagent reports, the finding goes onto the row as evidence — the decision
   is still his.
3. **Record his answer, verbatim**, then fetch the next one:
   ```bash
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py answer 651 --answer "yes, order it"'
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py resolve 651 --dismissed "not mine"'
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py defer 651 --until 2026-10-25 --note "after yom tov"'
   ```
   His words are the training data and the journal copy — never paraphrase them into the answer.
4. **If the card says PROBABLY THE SAME MATTER, close the cluster with one sentence** — his one answer
   is the answer to both, and a second row asking the same thing tomorrow is the defect he feels:
   ```bash
   ssh secratary-cloud 'python3 /root/bin/owner-queue.py answer 631 --with 645 --answer "paid it"'
   ```
5. Stop when he says stop, when `card` says the queue is empty, or after about 25 items. **At the end,
   run `learning` and tell him one line of what the session taught it** — that is the loop closing.

## Hard rules

- **An item is open until he acknowledges it, and an acknowledgement is the only thing that closes
  it.** His words, 2026-10-21, after I presented the Manela voicemail and then let it drop when he
  moved to another subject: *"i had to look back to see the manela, you shouldve told me about it
  again to make sure i read it, you have to have some sort of acknowledgement to close it out."* So:
  an item you have presented and he has not answered **reappears at the top of your next message, in
  one line, before anything new.** His silence is not a decision; his moving to a different subject is
  not a dismissal; his answering a *different* question in your message is not an answer to this one.
  There are exactly three ways an item leaves your hands — he answers (`answer`), he dismisses
  (`resolve --dismissed`), or he tells you to leave it, which is `defer`, recorded with **his** words
  so it returns as his and not as yours. Never carry an unanswered item out of a session silently:
  either it is closed on the record or the last line says it is still open.
- **A place-bound item is never raised where he is not.** His words, 2026-10-21: *"you have to
  remind me when i'm by my office, at night i'm home."* He works the shop 12:30–17:00 local and is
  home in the evening. An item whose action is physical — look at a door sensor, bring a device in,
  check a drawer, sign for a parcel — is parked to the window when he is standing where the thing
  is, and the deferral note names the place and the window. The CLI's `defer` takes a date only, so
  a timed deferral is written into `deferred_until` directly, in UTC: shop 12:30 local is 16:30Z.
  Asking a man about his office door at nine at night is a question he cannot answer.
- **An answer given in any session closes the row in that session.** His words, 2026-10-21, after
  the queue asked him to rotate two keys he had already ruled on hours earlier in another chat:
  *"i already told you i'm not worrries about them now, you broght them to my attention in another
  session today."* If he answers something that exists as a queue row, call `answer` / `resolve` /
  `defer` before the session ends and quote him. A session that takes an answer and leaves the row
  pending makes him answer the same question twice, and that is the defect he actually feels. If the
  row belongs to a surface you cannot write to, the handoff names the row id and his verbatim words.
  **Before presenting a row, check whether he has already answered it today** — `ps_search` with
  `what="sessions"` on the subject, or `journal.py search` on it; a row he settled at noon must not
  reach him at night.
- **A child that executes a row closes it — in the same breath.** Measured 2026-10-19, and it is
  why the owner was asked twice about one deletion: queue #721 (the ten pre-deploy Home Assistant
  backups) was executed at 02:07:42Z by a mesh child, archived to R2 first, freed 7.23 GiB — and the
  row stayed `pending` all evening, so the card asked him again at 21:40. **Work taken off a queue
  row is not finished until the row is closed with the evidence** (`resolve ID --how "<what was
  measured>"`). Before asking the owner anything, re-measure the thing: a row is a claim about the
  state of the world on the day it was written, never a fact about tonight.
- **A POSSIBLY MOOT line means check the premise before you speak.** The row itself is telling you the
  day it named has passed; re-measure, then either close it yourself or say what happened.
- **Never ask him something the row already answers.** The dossier is there so he does not have to
  work; if the number he needs is missing, gather it first and put it in the row.
- **A decision without a recommendation is a defect.** File it with one (`add --recommendation`). An
  item that says "Investigate it and bring me a recommendation" is the defect wearing a suit: that is
  the item asking itself to do its own work.
- **A decision he has not been briefed on never reaches him.** If `queue` reports *"N decision(s) held
  back while I gather the facts"*, that is the gate working — go and gather them, do not widen the gate.
- **Anything you can do yourself does not belong in the queue.** Solve it; a row is an admission that
  you could not. An item that is news and needs no decision is welcome; an item that is a chore you
  could have finished is not.
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
`health` is the difference. It reads two different things and both matter: **freshness** (each
source's newest arrival against a limit derived from its own rate) and **completeness** (`* read
everything` — fetched, folded, dropped, rows written, errors, from `owner_queue_ingest_run`). It exits
non-zero on a stale source, a run that reported errors, arithmetic that comes out negative, or a run
older than 48 hours. The 20-minute timer (`lpt-owner-queue.timer`) runs it after every ingest.

`learning` prints what his closes taught: what **rises**, what **sinks**, the count behind each, and
how much of its evidence comes from a channel that still writes. If it says *"0 close(s) from a
channel that still writes"*, the learning is wired but has not been taught yet — say that plainly
rather than claiming it learns.

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

**Before you file a decision, answer these three.** They are the gate, and filing past them only means
the row is held back until someone notices:

1. What is the amount, the date, or the named party? If the row cites an evidence table, write it as
   `Evidence: <table> row <id>` in the context — the reader joins it and prints it on the card.
2. What would *I* do, in one line? If the honest answer is "investigate it", the item is not ready.
3. Is this a choice, or is it news? News is `kind=attention` and needs no recommendation.
