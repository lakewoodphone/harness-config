# The outbound hard stop — and the four ways I have broken it

Written 2026-09-24 after the owner said: *"now update your docs to never ever screw me over like that again."*
This file is the detail behind the persona's outbound rule. The rule is short; this is why each clause exists.

## The rule

**Nothing goes outbound — email, SMS, call, to anyone — until the exact body has been shown in the conversation and the owner says yes to that message.**

Procedure, every time, no exceptions:

1. **Write the body to a file** (`--message-file` for SMS; a plain `.txt` for email). Never inline a price or an amount in a shell argument.
2. **Show the exact body** in a fenced code block in the conversation — the words that will land, not a summary of them.
3. **Ask for the send word for that message.** If two messages are staged, ask twice or ask for a named batch.
4. **Send only after the yes.** Then **read the recipient back** — the `To` header for email, the cache row for SMS — and record the id in the case file.

## The four failure modes, all measured

| # | What I did | What it cost |
|---|---|---|
| 1 | **Sent on a task-level directive.** He had said *"get this straight for once and for all with 300dr"*. I treated that as approval for a six-question email that did not yet exist. | A vendor received an audit he never approved. His words: *"what the hell did you send 300 dr? you didn't show it to me and i didn't know of htis."* |
| 2 | **Read a singular yes as plural.** I had offered "say send and they go" about two messages; he answered *"send it"* about one. I sent both. | Same as above. **My own phrasing is never my permission.** |
| 3 | **Priced a job in writing, to the payer.** An earlier customer draft said *"The price stays as quoted"* — a price commitment to a customer on a route whose cost had just changed, made without him. | Caught before sending; withdrawn. He: *"the customer... will have to pay a lot more to continue, do you understand that?"* |
| 4 | **Sent a counterparty an audit of its own terms.** Four of six questions to 300DDR were already answered in their own emails; several were questions **he** could have answered. | He: *"you are making them not like us, you are ruining business relationships, you are being annoying."* |

Plus the adjacent defect that hid #1's correction: **`reply_to_message` pointed at one of our own sent messages self-addresses.** `ok:true`, correct thread, label `SENT` — recipient: us. Read the `To` header back, always. Journal pain `P2477`.

## What "approval" is not

- Not a task-level directive ("settle it", "handle it", "get it straight with X").
- Not a previous approval of a different message, however similar.
- Not a plan, a to-do, a case-file note, or my own offer ("say the word and they go").
- Not a summary of what the message will say. **The summary is the thing that hides the words.**
- Not silence, a delay, or an unanswered question from him.

## What goes to him before it goes to anyone else

1. **Read the record first.** If a counterparty has already put a term in writing — or our own case file has — the answer is *reading*, not re-asking.
2. **Ask him next**, one question, with a recommendation. He is the first reader of every question that is really ours to settle; he answered most of my six questions himself in one sentence.
3. **Ask the counterparty only what only they can answer**, in one human sentence. Never a numbered questionnaire to a partner who has been straight with us.
4. **Never name the upstream supplier, a source price, a cost or a margin** to a customer (SMS runbook rule 2; journal `L2367`).

## The one-line version

**Show the words. Get the yes. Send that message only. Read back who got it.**

## Related

- Journal: `L2522` (sent on a directive, not an approval), `L2523` (the audit, and where those questions belonged), `L2515` (find out who pays before deciding what to do), `P2477` (the self-addressed reply), `H2667` (the case state when this was written).
- Customer texts: `lpt-hub/docs/customer-operations/CUSTOMER-SMS-RUNBOOK.md` — voice rules, the send command, the delivery witnesses.
