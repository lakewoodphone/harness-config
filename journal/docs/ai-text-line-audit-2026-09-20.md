# Audit — the AI text line (`+1 732-444-7361`)

**2026-09-20 · ZABZ-YOGA · measured, not inferred.** Every number below came from a command run in
this session; the command is named next to it.

## What the system is

| Piece | Where | Job |
|---|---|---|
| Twilio number `+17324447361` "Phone & Tech - Test/Staging" | Twilio account `AC274c4dd8…` | the **personal** line: owner, family, close friends. NOT customers. |
| `/webhook/twilio/sms` | `personal-secretary-mvp/app/main.py:3852` | records inbound into `sms_log` + conversation turns + memory |
| `~/bin/sms-inbox.py` | secratary, cron `*/5` | sensor: reconciles Twilio's own message log into `~/.sms-inbox/inbox.db`, flags app-side gaps |
| `~/bin/sms-responder.py` | secratary, cron `*/5` | decides: `auto` / `hold` / `queue` / `never` |
| `~/bin/send-from-ai-line.py` | secratary | the only sender for this line |
| `permissions` table | `~/.sms-inbox/inbox.db` | per-phone `allow = auto \| queue \| never` |

**The customer line is a different number on a different provider** — `+17326552355` on Dialpad
(`DIALPAD_SMS_FROM_NUMBER`), ~2,600 inbound customer texts in the last 7 days. Out of scope here by
the owner's own instruction, 2026-09-20: *"the ai line is for you and me personally, it's not to
manage customers / customers are managed via dialpad"*.

## What is actually working

1. **The sensor works.** `sms-inbox.py sync --pages 5` against Twilio's API → 1,000 outbound read,
   0 new, store holds 334 inbound / 1,211 outbound. `last_sync = 2026-09-20T15:15:05Z`.
2. **The gap detector works and it mattered.** 77 inbound texts reached Twilio that the app never
   recorded — the webhook 500'd on `database is locked` and Twilio does not retry an inbound SMS
   webhook after a 5xx.
3. **The permission ledger is real** — 15 rows, honest relationships, `never` on shortcodes and
   verification codes.
4. **Layer-2 safety in `classify()` is real and load-bearing.** It refuses to send a draft that
   contains markdown headings, an "Option" list, or >400 chars — written after the model answered
   `QUEUE` with `**QUEUE**\n\n### Reasoning…` and would have texted the scratch pad to the owner's
   father.

## What is broken — ranked, with evidence

### B1. The line is effectively dead, and the responder is why
- **0 inbound texts awaiting a decision.** `sms-responder.py run` prints `0 to decide` on every cron
  tick; `responder.log` is 40+ consecutive identical lines.
- Newest **real** inbound (excluding my own test texts today): **2026-09-18 03:29**, 3 days ago.
- Chips Zebrowski — the line's heaviest user, **239 inbound / 232 outbound** — has not texted since
  **2026-06-29**.
- The owner has sent **11 texts** to this line ever, the last on **2026-05-11**: *"what the heck are
  you talking about, i never wanted an ad in the shopper"*, *"Find me the Wi-Fi password to the
  network called hidden network. I'm there now and I forgot…"*. All were recorded `seen` or
  `ignored`. **The owner stopped texting his own assistant because it did not answer.**

### B2. The owner's own texts are filed as `queue` — the assistant refuses to talk to him
`permissions` row: `+17325691594 = Eliyahu (owner) … allow=queue`, note *"the owner talks TO the
system; never auto-reply to him"*. So when he texts his assistant, the only outcomes are "raise an
owner-queue row about yourself" or silence. 8 of his 11 texts are `ignored`.

### B3. `allow=queue` makes the system deaf to everyone it was built for
- **Yisroel Weinberg** `+18482102477`: **7 inbound, 5 `queued`, newest 2026-09-18 03:29** — Friday
  night, still unanswered. One of them, at 03:03, is *"Don't spend too much time on it"*.
- **Bachrach** `+18453762305`, 2026-09-09 02:37: *"Is this the door code for the outside door or it's
  the door code for t…"* — a **door-code question, unanswered for 11 days**.
- **Totty (his father)** `+17326747491`, 2026-09-09 03:53: *"I believe you sent this message to the
  wrong number"* — `queued`.
- **Radzik Sruly** `+18452745833`: **42 inbound, 1 outbound**; 40 rows `seen`, 2 `ignored`.
- 13 inbound texts have no reply after them.

### B4. "I'll look into it" is a dead end — the exact thing the owner asked for is missing
`HOLD:` sends an acknowledgement **and then raises an owner-queue row**. There is no third step. The
system can never make a promise it keeps, because "do the work, then reply" does not exist as an
action. The only investigation path is
`awaited` + `wake.py` — and that fires **only** for a reply to a message *we* sent (the `woke` state
on 2 of Weinberg's texts). A promise made by the responder itself is never tracked.

### B5. The owner's queue is a notification dump, not a decision queue
Rows like *"X texted your AI line and I have not answered: 'Thanks!' … Should I answer them, and may
I answer this person directly from now on?"* are not owner decisions — they are the assistant asking
to be given a job it should have done. This is the same defect class as the measured 595 messages
that reached him when 383 were engineering faults.

### B6. Latency: the assistant answers in up to 5 minutes, or never
Cron is `*/5`. For a personal line where the owner is standing in a shop asking *"what's the Wi-Fi
password"*, a 5-minute best case is a failure, and the worst case observed is 3 days.

### B7. No business context is ever available to the decision
The decision sees: the thread, the sender's name, and the ledger. It does not see owner state,
calendar, availability, doors, presence, memory, contacts, tasks or the owner queue — all of which
**already answer over HTTP on the authority** (verified this session):

| Endpoint | Status |
|---|---|
| `GET /owner/state` | 200 — `calendar_inference.availability = "available"` |
| `GET /owner/profile` | 200 — learned preferences with confidence |
| `GET /api/v1/comms/by-phone/{phone}` | 200 — per-line lineages, incl. AI line vs Dialpad |
| `GET /sms/thread/{phone}` | 200 — contact record + thread |
| `POST /web/search` | 200 — Tavily |
| `GET /semantic-memory/search` | 200 |
| `GET /contacts`, `GET /owner/outbox` | 200 |
| `GET /v1/models` (gateway) | 200 — 38 models incl. `secretary-auto` / `-fast` / `-smart` (`secretary-genius` is 502, do not use) |

### B8. Identity has exactly one source
`permissions.phone` only. Nothing consults `contacts`, `comms_identity_link`, `dialpad_sms_cache` or
memory to say *who this is*. 3 AI-line numbers are still `?`.
`+18482245096` is literally named `unknown (+18482245096)` with 3 in / 15 out.

### B9. The model output contract is enforced by one regex
`classify()` is the only validator. There is no length check against SMS segment limits, no
injection marker check, no `- Daniel` signature enforcement on the auto path (only the manual
`send-from-ai-line.py` warns about it, and only when a human runs it).

### B10. Four lines of test junk sit in the same tables as real traffic
`+15555550199` ("Understood — ignoring."), "DSH realtime delivery check 08:12:40Z", and two opt-in
auto-confirmations from `+17326552355` are counted alongside real correspondence.

### B11. Nothing measures whether the system is any good
`responder.log` prints `0 to decide`. There is no self-report: no reply rate, no time-to-answer, no
count of people left waiting, no "I sent something I should not have" counter.

## The rebuild, in one sentence

Give the line a real assistant: **resolve who the sender is from every source, read the owner's
actual state, answer what can be answered in his voice, turn every promise into tracked work with a
real follow-through reply, raise exactly one owner-queue row when it is genuinely his — and report
its own health.**

## Decisions taken while building (dev, not owner)

- **D-a1.** The rebuild stays on the personal line. Dialpad customer traffic is untouched.
- **D-a2.** New code lives in `harness-config/scripts/` (frozen) and deploys to `~/bin/` on
  secratary — the same one-source-of-truth pattern as the sensor.
- **D-a3.** Modules are split by file so several agents can build in parallel without touching each
  other: `textstore.py` (schema), `textctx.py` (who is this), `textdecide.py` (what to do),
  `textwork.py` (do it), `textsend.py` (send it), orchestrator `sms-responder.py`.
- **D-a4.** Models are resolved from the gateway catalog at runtime; an unreachable model queues,
  never guesses. Standing rule, `journal L1606`.
