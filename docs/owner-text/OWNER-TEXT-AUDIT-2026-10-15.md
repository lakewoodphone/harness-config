# The owner text channel — audit, 2026-10-15

**Asked for, verbatim (2026-10-15):**

> *"Look at the system that text me, and I text back. I wanted to read the last 500 texts and analyze
> them really well... It's repetitive. Sometimes I ask the same thing more than once. Sometimes the
> brain isn't unified. And when I text back, it doesn't know who text me and responds weirdly. That
> needs to be a clear relay system that won't text me go through a clear agent that understands the
> entire context of my texting. And more than that, it asked me the same question more than once some
> cfo questions, and also some cfo questions that could figure out by itself, like, if it wants to
> know about a charge, I'll just text me, check all my emails, analyze the merchant. When you're done,
> and if you still don't understand, you still need to know, then send me a clearer text with the
> context."*
>
> *"Another thing I keep getting these like text that's a 36 items, 29 urgent and stuff like that.
> That's useless to me in a text. I wondered if you have an important question from your CFO question.
> Ask it to me clearly and I'll answer no mush of stuff. Also, why does it sometimes say context cuts
> short? ... It's not like a normal, human-like texting system."*

**The one-sentence diagnosis.** There is no owner-facing agent: nine independent senders put text on
his phone, three stores disagree about what he has already been asked, sixteen different length
ceilings judge the same body, and nothing at all owns the composition of a message for him.

---

## 0. The corpus, and three traps in reading it

The line is `+17324447361` (Twilio) → the owner's `+18483897895`. Every attempt is a row in
`/root/authority.db` `sms_log`.

```
SELECT direction,status,COUNT(*) FROM sms_log
 WHERE (direction='outbound' AND to_number='+18483897895')
    OR (direction='inbound'  AND from_number='+18483897895')
 GROUP BY 1,2;
```

| status | rows | what it means |
|---|---|---|
| suppressed | 2,023 | **refused by a gate. NOT delivered, NOT seen.** |
| failed | 985 | transport/provider refusal. NOT seen. |
| delivered / sent | 458 | really on his phone |
| undelivered | 5 | |
| queued | 30 | written, never confirmed |
| received (inbound) | 339 | his own texts |

**Trap 1 — "the last 500 texts" is not the last 500 texts.** The last 500 rows *by id* span only
seven days and are **414 suppressed rows**; the single largest group in them is 375 copies of one
reminder that was **never delivered**. Reading them as "what he received" would be wrong by an order
of magnitude. The honest corpus is the last 500 *real* messages (delivered + sent + received), which
reaches back to 2026-02.

**Trap 2 — the same message is logged twice, and that is not a double send.** Every outbound reply
appears twice, under `agent_id='sms_service.audit'` and `agent_id='orchestrator'`, ~1.5 ms apart.
Both rows carry the **same `twilio_sid`** (e.g. `SMdace1607f279310b4978f6cdff934ae6` on ids 3556 and
3557). One send, two log lines. 36 bodies have both rows. A count of rows overstates his volume by
~2×; a count of `DISTINCT twilio_sid` does not. **283 distinct outbound sids all time.**

**Trap 3 — the 375-message burst is a refusal storm, not spam he endured.** All 489 rows containing
the library-books reminder are `suppressed` with
`[suppressed] owner_text gate refused (awaiting_reply): he has not answered the message sent 1.98h
ago (turn #64); one at a time`, one per ~72 seconds for ten hours (2026-10-08 12:00→22:01). Exactly
**one** has a sid. The gate worked; the retry loop is the defect, and it wrote 488 rows that poison
any later analysis of this table. Same shape four more times: `Pay Yisroel Weinberg $597.29` n=863,
`Check 300DDR for Fishman tickets` n=840, `CALL TOPGOLF EDISON GUEST CARE` n=290.

**Real volume:** 1–15 outbound and 1–11 inbound a day, most days 5–6 each. The problem was never
volume. It is coherence.

---

## 1. FINDINGS

### F1 — The digest text he banned twice was sent anyway, 24 hours later

He said, `sms_log` 4152, 2026-10-14T00:33:10Z:

> *"This is a good example of a text that's useless. I have no idea what it means, it's too much
> information, and it's weird."*

and again, 4176, 2026-10-14T14:18:21Z:

> *"I already told you these random briefs seem pointless. I need one item at a time, either a
> question or notification, not some random text that says 36 items, 30 urgent, or something like
> that."*

The system acknowledged it 3m44s later (4177): *"No more digest blasts - one item at a time… Saving
that as a standing rule so it survives every session."* Then, **24 hours later**, `sms_log` 4186,
2026-10-15T14:13:28Z, 237 chars:

```
'10-15 14:13 UTC  36 items, 18 urgent
- The prepaid AI balance is low. Top it up so the autonomous work does not stop?
- The camera product's entire difference from what already exists is that it upl
full: data/owner-attention/latest.txt
```

Proof it left the building: relay `attempt_id=29`, `door=app`, `verdict=SEND`, `status=sent`,
`sid=SM433eb01717ad795a7523621ad0f289b9`.

**Why the durable instruction did not bind — two independent holes:**

1. `app/services/owner_notifications.py:122,331` gates briefings with
   `reason.startswith("owner_briefing")`. The digest's reason is **`owner_attention_digest`**, so the
   gate never applied. The switch itself exists and is off: `owner_profile_v2` id 24
   `owner_briefings_enabled=false`.
2. `owner_text_suppression` holds exactly **one** row, all time, and its `topic` is
   `"I have no idea what it means, it's too much information, and it's weird"` — the *complaint
   sentence*, extracted by the stop-ack at `app/main.py:2925-2926` (`f"Got it — no more about
   {topic}."`). Matching is a lowercase **substring** test against `f"{reason} {body}"`
   (`app/owner_text.py:1970,2003`). A whole English sentence can never appear in a later body, so
   that row is structurally inert. **The mechanism that records "stop sending me this" is real; the
   topic written into it is unusable, so no such instruction has ever had an effect.**

**Cost of the truncation:** the digest composes from `data/owner-attention/latest.txt`, **15,221
chars**, into 237 — **98.4% never reached him**, with no marker saying so, and the only
"where is the rest" pointer is a relative filesystem path that cannot be opened from a phone. The
producer is `sms_body()` at `scripts/owner_attention.py:493-514`, fired by
`lpt-owner-attention.timer` (`OnCalendar=*-*-* 14:10:00 UTC`, +`RandomizedDelaySec=900`).

### F2 — "why does it sometimes say context cuts short?" — answered

`SMS_TRUNCATION_MARKER = " [cut short - ask me to continue]"` (`app/sms_service.py:47`), mirrored at
`/root/bin/owner_text_relay.py:148` and re-exported by `app/owner_text.py:1049`. It is appended
whenever a body must be shortened to fit one text. It **asks the owner to ask for the rest of his own
message.**

Measured over 30 days: **19 rows, 11 distinct sids** (8 plausibly delivered). Worst losses, with the
pre-cut original recoverable from the relay's own `ref`:

| relay attempt | submitted | posted | he read |
|---|---|---|---|
| 6 (`reminder:530`) | 543 chars | 194 | 36% |
| 8 (`reminder:534`) | 612 chars | 281 | 46% |

And every long reply in the conversation ends with it — because the reply is composed as a numbered
multi-part answer that could never fit 320 chars in the first place.

### F3 — The "unified brain" is not one brain: two inbound paths, none coordinated

Inbound arrives two ways that do not know about each other:

* **the Twilio webhook** → `app/owner_text.py` → `app/assistant_chat.py`, which replies inline;
* **a cron sensor** → `sms-inbox.py sync` (read-only Twilio) → `sms-responder.py run --send`, every
  5 minutes.

Measured: `responder.log` holds **707 runs, 699 `0 to decide`, 0 sends.** The cron responder is
effectively a no-op; the replies he actually reads come from the app's webhook path. His text of
2026-10-15T01:35:13Z is the proof of the race: the **app answered at 01:35:21** with the provider
outage line; **one second later** the responder's copy of the same text was classified `ANSWER`, the
ask was marked answered, and it *sent nothing*. He then had 12.6 hours of silence and got the digest.

**"It doesn't know who text me."** Identity is decided in `textctx._identity()`
(`/root/bin/textctx.py:551`), and the owner is recognised by a single `LIKE 'owner%'` test
(`sms-responder.py:1831`) against one cell of `inbox.db` `permissions`. `$OWNER_PHONE_NUMBER` is
**not set** anywhere (root crontab, `cron-wrap.sh`, `/etc/environment` — 0 matches). And the
Google-Voice line `+17325691594` is stored as `relationship='owner-google-voice'`, `allow='never'`,
while `textdecide.py:765` tests `rel == "owner"` **exactly** — so the two rules disagree and nothing
covers the gap. Meanwhile that number received **10,223 outbound messages** between 2026-05-08 and
05-19.

**What is NOT true:** the system does *not* reply to its own outbound as if he sent it. `messages`
has **zero** rows where an inbound sender is one of our own numbers, and `_direction()`
(`sms-inbox.py:455`) fails *closed*. I checked this specifically because it looked like the cause;
it is not. The "you literally just sent that text to me" incidents (his pastes at `sms_log` 1932,
4109, 4152) are the two-brain problem, not a loop.

**Three stores disagree about "what is outstanding":**

| store | open | answered/expired |
|---|---|---|
| `/root/.cfo-asks/asks.db` `clarification` | 6 asked | 2 answered, 15 expired |
| `/root/.owner-text/relay.db` `ask` | 1 | 1 |
| `authority.db owner_text_turn` | 2 unanswered | 108 answered |
| `/root/.sms-inbox/offered.db` `offered` | 0 rows | — |

and the responder logs its own gap: `relay: ask ask-… -> missing` **×6**, because
`textctx.recent_asks()` is not importable on this host and it falls back to the CFO store only.

### F4 — The same question, asked and answered, then asked again

* **Polkadot 299.** Asked 2026-10-02T00:00:06; he answered the same minute ("my wife's second holiday
  dress totally personal"). Re-raised 2026-10-13; he replied *"are you sure I didn't tell this to
  you already?"*; the system answered *"I don't have a record of you telling me about the Polkadot
  $299."*
* **Weinberg 1,000.** He answered 2026-09-29. Asked again #50, #51, #52, #64, #85. His reply
  2026-10-12: *"I already told you in a DSH session… I paid him $1000 from my personal account. You
  should have that documented."*
* **American Professional 36.14.** He explained it 2026-10-08; six memory rows were written saying
  **"Do not flag as unknown vendor charge again."** It was asked again 2026-10-15T01:00:36. His
  reply 01:35:13: *"Didn't we already go through that…"* — and that is the text that got the provider
  outage answer.
* **`owner_text_turn` contains 10 exact-duplicate ask rows** (#1/2, #3/4, #5/6, #12/13, #14/15,
  #33/34, #39/40, #66/67, #98/99, #106/107); #39 is annotated `duplicate-row` in its own record.

### F5 — CFO charge questions: 13 duplicate compositions, and the one-at-a-time rule never engaged

`cfo-ask.py` runs every 30 minutes. Measured in `/root/.cfo-asks/asks.db`:

* distinct charges put to him: **10**; compositions: **23**; **13 duplicate compositions**;
  **5 charges composed more than once**; delivered duplicates: **0**.
* worst: **`pass` 135.33 composed TEN times** between 2026-10-13T06:00 and 2026-10-14T03:01 — nine
  sender refusals then one delivery, 21 hours later.

**The mechanism, and it is the finding that explains his complaint precisely.** The ask body ends:

> `No guess from me - say what it was and I'll file it for good.`

`textsend.py` opens the owner's one-at-a-time turn only when `_QUESTION_RE` (`[?？]`) matches, and
records otherwise: *"no turn opened: the body asks nothing (no question mark), so the one-at-a-time
rule does not apply."* **So every CFO ask was exempt from the single-ask protection**, and the daily
cap of 3 was the only brake left — which is exactly why three charge questions went out at 00:00,
01:00 and 02:00 on 2026-10-15. Verified by A/B on the live predicate:

```
OLD body → opens a turn: False
NEW body → opens a turn: True
```

**And 6 of the last 20 were answerable from data already on the box:**

| charge | evidence already held | when the text went |
|---|---|---|
| VisionTek 31.73 | `purchases` row 8281 is linked to **this exact charge** — and the row was created 2026-10-14T14:58:35Z, eleven hours before the text | 2026-10-15T02:00:35 |
| American Professional 36.14 | 6 memory rows from 2026-10-08, including "Do not flag as unknown vendor charge again" | 2026-10-15T01:00:36 |
| Sticky Brand 60.23 | his own answer, `sms_log` 3546, 2026-10-07T13:08:03 | 2026-10-15T00:00:45 |
| Pass 135.33 | statement line is self-describing (`PASSNY TOLLBYMAIL`); the ledger already holds 15 `nj e-zpass` rows | 2026-10-14T03:01:24 |
| Pocono Whitewater 107.78 | our own Pocono Biking booking SMS (`sms_log` 1054-1058), same 1 Oct date | 2026-10-14T04:30:06 |

**CORRECTION, and it is the interesting part.** First pass at this table said the VisionTek link
was `purchases.matched_transaction_id` = "the exact Plaid id of this charge". That is only half
right and the half that matters: `purchases.matched_transaction_id` does **not** join to
`transactions.id`, which is a UUID. It joins to **`transactions.external_transaction_id`**.
Measured: on the wrong key the join returns **0 rows** — a silent absence that would have looked
like "we hold no order for this charge" and sent the text anyway; on the right key it returns
**2,173** of the 2,401 `matched` rows. The VisionTek charge's ledger id is
`4b550706-cd12-44d8-9742-758c1043a3f3` and its `external_transaction_id` is
`Rzagj969nZILgjOoM8J8haNrQvJP89urAoEQAg`, which is what the purchases row holds.

`purchases` holds **4,205 rows (2,401 matched) in `/root/authority.db`** and neither `charge_msg.py`
nor `merchant_resolve.py` read it before 2026-10-15. Note also that the similarly-named
`/root/personal-secretary-mvp/data/secretary.db` holds **0** `purchases` rows while being 1.8 MB and
present — a mirror that answers "no match" as confidently as the authority.

`merchant_resolve._from_answered_asks` (`merchant_resolve.py:327-350`) read only the two asks
databases — never `sms_log`, `owner_text_turn` or `memories`, which is where his answers of
2026-10-07 and 2026-10-08 actually are. And `order_evidence.ORDER_SUBJECT_RE`
(`order_evidence.py:55-61`) had no arm for `Order W009615 confirmed` (only `Order #<n>`), so the
resolver's order rung returned `solved=False` on an order the box had already matched.

**And a refused question is re-composed at every tick.** `next_question()` deliberately treats a
definite sender refusal as *non*-suppressing (item 104, 2026-10-14 — correct on its own terms: a
question that never reached him is not an ask) but nothing re-armed it.

**The question never says why he is being asked.** It states the amount, date, card and statement
line, and closes with "no guess from me". It never says that the ledger, his mail and his own earlier
answers were consulted and came up empty — which is the exact "clearer text with the context" he
asked for.

### F6 — The provider outage he was texted was one provider, and a healthy route existed

2026-10-15T01:35:21Z he received: *"Sorry - all providers are currently unavailable. I tried every
option. Try again in a few minutes."* (`assistant_chat.py:5793`).

The log at that second:

```
ERROR app.assistant_chat: All 1 providers failed for tier=ceo:
  deepseek/deepseek-v4-flash: Error code: 503 - {type: service_unavailable_error}
```

**"All 1 providers."** `.env:412 USE_DYNAMIC_REGISTRY=false` means `_get_ceo_models()`
(`assistant_chat.py:1446`) never reads `data/model_registry.json`. `.env:456
LLM_DISABLED_PROVIDERS_JSON=["openrouter","copilot","deepinfra","fireworks"]` removes both fallback
pipes **while `DEEPINFRA_API_KEY` and `FIREWORKS_API_KEY` are set** (lines 451, 452). The CEO pool is
one model; the `:1462` last resort is the same hardcoded literal.

**The gateway was healthy and unused by this path:** `GET /v1/models` → 200, 35 ids including the
route aliases; `text-health.py` → 15 checks, 0 FAIL; and `smart_router` served
`alias=secretary-fast model=google/gemini-3.5-flash-lite` from that catalogue **one second later**,
at 01:35:23. `textdecide.py:53 PREFERRED = ("secretary-auto","secretary-smart","secretary-fast")`
uses the aliases correctly. The SMS reply path is the one that bypasses them — which is the standing
rule *"AI models are never hardcoded"* being violated on the one path the owner is looking at.

**Not fixed here** — `docs/mesh/177-DEEPSEEK-SPOF-INCIDENT-2026-10-15.md` is the live workstream for
it and was already at 21,718 bytes when this audit read it. Two sessions must not fix one outage.

### F7 — Nine doors, sixteen ceilings, and one channel

Doors that can put text on his phone, with what mediates them:

| door | where | schedule | mediated by |
|---|---|---|---|
| app `sms_service.send_message` | `/opt/company/app/sms_service.py:1268` | in-process | relay (**`door="app"`**, 23 attempts) |
| `textsend.send()` | `/root/bin/textsend.py:2320` | on demand | relay (**`door="textsend"`**, 6 attempts) |
| `sms-responder.py` | `/root/bin/sms-responder.py:206` | `*/5` | via textsend; 0 sends observed |
| `cfo-ask.py` | `/root/bin/cfo-ask.py:714` | `*/30` | via textsend, **6 texts, all stuck `queued`** |
| `owner-ask.py` | `/root/bin/owner-ask.py:374` | **no cron line** | via textsend; **never seen by the relay** |
| `card-due-watch.py` | `/root/bin/card-due-watch.py:363` | `0 13 * * *` | via textsend notify; **never seen** |
| `owner_attention.py` | `/opt/company/scripts/owner_attention.py` | timer 14:10 | via app; **never seen as its own door** — but since 2026-10-15 it composes through the front desk's `relay.compose()` |
| `family_chat` owner leg | `app/family_chat/twilio_client.py:618` | in-process | `owner_text.gate` only — **not the relay** (`verbatim_relay=True` skips even that) |
| `company-heartbeat.sh` | `waze-mdm-01` + `lpt-apps-01`, line 358/382 | `*/2` | **raw `curl … api.twilio.com`** — no gate, no row anywhere, and those two hosts are `read-only` in `host-posture.tsv` |

The relay can only ever see two `door` literals, `"app"` and `"textsend"` — 29 attempts, ever.
Sixteen length constants guard one channel; four of them act on the same body in sequence
(900 → 400 → 320, `app/autopilot.py:698` → `app/owner_text.py:215` → `owner_text_relay.py:146`), and
the 320 ceiling is enforced by **no** judge: the relay records `too-long` rather than refusing
(L3791's deliberate choice) while `textsend` posts up to `SOFT_LIMIT=930`.

### F8 — A send loop is running right now, and the relay is the only thing between it and his phone

**Found while writing this document, not by looking for it.** The relay's own ledger —

```
SELECT attempt_id,at,door,subsystem,verdict,verdict_reason,status,substr(body,1,50)
  FROM attempt WHERE at > '2026-10-15T14:15:00';
```

```
30|14:45:18Z|app|sms_service.send_message|SEND  |ok          |pending|I still have your message and I'm routing it now.
31|14:45:18Z|app|sms_service.send_message|SEND  |ok          |pending|The charge posted on the 14th.
32|14:50:22Z|app|sms_service.send_message|DEDUPE|dup-inflight|pending|I still have your message and I'm routing it now.
33|14:50:22Z|app|sms_service.send_message|DEDUPE|dup-inflight|pending|The charge posted on the 14th.
34|14:53:17Z| … same pair …
36|14:54:04Z| … same pair …
```

The same two bodies were first submitted at **2026-10-14T19:55:10Z** (attempts 9 and 10) and are
**still being re-submitted every 2–5 minutes 20 hours later** (attempts 9→37; `verdicts_24h` shows
SEND 9 / DEDUPE 20). Every attempt sits at `status='pending'`, because the door never calls
`record_sent()`/`record_failed()`, so the relay's dup-inflight window can never close and it holds
each repeat as `dup-inflight` forever.

**Two conclusions, and both matter:**

* **The relay is working.** 20 holds in 24 hours, and `sms_log` shows **zero** outbound rows to the
  owner in that window. This is the policy component doing exactly what it was built to do.
* **The loop underneath it is not.** Something re-processes one event and emits a receipt each time.
  Producer candidates, both in `app/main.py`: line 3540
  (`"Still escalating this to the owner now. If you can, text the exact blocker or location."`) and
  the receipt described at line 3562; the second body has **no literal anywhere** in `app/`, `scripts/`
  or `/root/bin` and is therefore probably model-generated. `textsend.py:1543-1544` already names this
  class of message — *"a receipt: it buys him nothing"*. **I did not find the clock and I am not
  guessing at it.** Until it is found, the relay is load-bearing for a defect nobody has diagnosed,
  which is a fragile place for the only thing standing between a loop and his phone.

### F9 — Dead weight that makes the next audit lie

* `owner_text_decision`: **9,236 rows**, none read by any sender or responder. `too_long` 1,273,
  `awaiting_reply` 1,315, `gate_error` 2,780.
* `owner_attention_findings`: **27,840 rows**, read only by its own producer.
* `owner_message_queue`: 2,608 rows — 625 dismissed, 145 expired, 44 sent, 10 held in the last 30
  days. **73% of what the attention system produces for him is dismissed as not worth his time.**
* `/root/bin/owner_flood_guard.py:108` `APP_OWNER_TEXT_MAX_CHARS = 320` with a comment calling it
  "The app's own one-text ceiling (`app/owner_text.DEFAULT_MAX_CHARS`)" — that constant is **400**.
  The comment and the constant disagree by 80 chars (journal H3617b item 4, still open).
* `textsend.py:97 SOFT_LIMIT=930` hardcodes a number that `scripts/text-channel/textsend.py:133`
  reads from `app/owner_text.py`; the `/root/bin` copy on the live path holds the stale literal.

---

## 2. What was changed, and what was verified

Every change below is backed up under `/root/text-fix-20261015/backup/` and reversible with `cp -p`.

| # | change | file | verified by |
|---|---|---|---|
| 1 | **The daily digest text is OFF.** `ExecStart` is now `build`, not `send`. The sweep still runs, still writes `latest.txt` and the timestamped artefact, still files its decisions into `owner_decision_queue`; it no longer texts a 237-char truncation of a 15,221-char report. | `/etc/systemd/system/lpt-owner-attention.service.d/10-no-text-20261015.conf` | `systemctl show … -p ExecStart`; ran the new `ExecStart` by hand → `rc=0`, `latest.txt` written 14:56:12Z, nothing sent |
| 2 | A **standing-rules file** was created so an instruction about this channel can take effect without a deploy: classes, the new one-item class allowed, and the retired digest body **closed with his quotes as the reason**. **CORRECTION, verified 15:04Z: the file is on disk but its READER is not live** — `standing_rule_blocks()` lived in the `owner_attention.py` revision a concurrent session overwrote (item 1 of §3). Nothing reads the file today. It is preserved as the intended mechanism, not as a working one. | `/root/.owner-text/standing-rules.json` | parsed as JSON; `standing_rule_blocks()` returns the reason for the closed class **when run against the overwritten draft**, and `AttributeError` against the live file |
| 3 | **The truncation marker is retired.** `SMS_TRUNCATION_MARKER = ""` in the app and in the relay; `fit()` cuts at a sentence boundary, appends nothing, and records `original→posted` to `/root/.owner-text/fit.log`. | `app/sms_service.py:47`, `app/owner_text.py:1049`, `/root/bin/owner_text_relay.py:148`, `fit()` | `fit("…"*40, 320)` → 314 chars, no marker, `fit.log` line written; trim of the LONG sample now ends `"…I actually see it."` instead of `"…\n\n2."` |
| 4 | A cut **no longer ends on a dangling list marker** (`"…see it.\n\n2."` → `"…see it."`). | `app/sms_service.py:_truncate_at_sentence` | the test file below, plus the direct render |
| 5 | **The CEO/CFO question now ends in a question mark**, so the owner's one-at-a-time protection engages instead of every ask being exempt. | `/root/bin/charge_msg.py`, `/root/bin/cfo-ask.py` (bare fallback) | A/B on `textsend._QUESTION_RE`: OLD `opens a turn: False` → NEW `True` |
| 6 | A **refused** question stops suppressing for `REFUSAL_SILENCE_HOURS` (6), so a busy channel no longer re-composes the same charge at every 30-minute tick (the 10-composition storm). | `/root/bin/cfo-ask.py:next_question()` | `cfo-ask.py` runs clean and reports `sent_today=3/3 asked_merchants=25` |
| 7 | The three sentence-boundary tests now hold the **new** contract (ends at a sentence, appends nothing, **and the cut is still recorded in the log**) instead of asserting the retired marker. Rewritten deliberately, with the reason in the docstring, not weakened to pass. | `tests/test_sms_sentence_boundary_trim.py` | `6 passed` |
| 8 | **Charge questions are now self-serve.** `merchant_resolve.resolve()` gained two rungs and one widened exemption: (a) `records:owner-text` — his answer given **in a text**, read from `sms_log` inbound (this is the rung the ask ledger never had); (b) `records:order-match` — the charge already linked to its order mail by `purchases.matched_transaction_id = transactions.external_transaction_id`, amount-checked; (c) `_finish` now lets `owner-text`, `order-match`, and an `alias` learned from the owner's own answer resolve **without** naming a category, exactly as `ask-answer` already did. Nothing invents a category: `category` stays `''` and `planned_rows` stays empty on all of them. | `/root/bin/merchant_resolve.py` | all nine live merchants resolve: visiontek systems **0.95 order-match**, sticky brand **0.92 owner-text**, newegg **0.97 alias**, the home depot **0.95 order-match**, american professional 0.97 alias. Categories verified empty with `planned_rows=0` |
| 9 | `order_evidence.ORDER_SUBJECT_RE` accepts `Order <CODE> confirmed` (the Shopify-family subject), which neither `order\s*(is\s*)?(confirm|#)` nor `order confirmed` could match. | `/root/bin/order_evidence.py` | `Order W009615 confirmed` → True, `Order #828330 confirmed` → True, `Coffee with Dov` → False |
| 10 | **The CFO's question is now filed with the relay**, so a reply can resolve against it. Until today the question lived only in `/root/.cfo-asks/asks.db` while the component that answers his reply looks the reference up in `owner_text_relay`'s own `ask` table — the two never met, and the responder logged it six times: `relay: ask ask-1792026036 -> missing` (that was the American Professional charge). `cfo-ask.py` now calls `relay.record_ask(ref, "cfo_ask", merchant, body, ttl_hours=72)` next to its own record, fail-soft. | `/root/bin/cfo-ask.py` | `record_ask` → `created=True, state=open`; the ref appears in `open_asks(within_hours=72)`; `answer_ask` closes it to `answered` and it leaves the open list. The test ref was removed by answering it; `open_asks` is back to what it was |
| 11 | **The front desk now exists as a primitive, in the one file every door already passes through.** `owner_text_relay` gained `compose(item)` — an ITEM dict in, ONE message out, cut to the ceiling by construction at a sentence then a clause boundary, with the retired marker and the machine shapes (`items, `, `full: `, a filesystem path) refused after composing — plus `submit_item(door, subsystem, item, ref=…)`, which composes, gates, and files the ask in one call, returning the body so **the judged body and the posted body are the same object** (`L3790`). And `standing_rule_mutes()`: a durable class-mute read from `/root/.owner-text/standing-rules.json` on **every** submit, keyed on the class the producer names, allowing on any read failure. | `/root/bin/owner_text_relay.py` + `/root/bin/owner-text` (`item`, `compose`) | 20-assertion probe, **ALL PASS**, against an isolated store: `/root/text-fix-20261015/probe_frontdesk.py`. Every pre-existing verdict unchanged (SEND, DEDUPE, FLOOR, class SUPPRESS, over-ceiling recorded-not-refused); the retired digest class now returns `SUPPRESS/standing-rule` **at the relay**, for any door; `compose` refuses a count head, drops an unclosed parenthesis, and composes subject+action for the four real shapes he complained about. Live store untouched |
| 12 | **The daily attention text is ONE item, and it goes out again.** The systemd drop-in from #1 is **removed** (`ExecStart` is `send` again), and the merge with the concurrent session's file is done rather than overwritten: their `_PERSONAL_MARK` / `PERSONAL_SMS_SLOTS` / `email_title` / `rank_items` are kept, and their reservation — the old 320-char digest carried four decisions and **zero** of his own mail — becomes a *selection*: `deserves_his_phone` lets `tier == "personal"` be the item, alongside `owner-queue` and `books`. The count head, the ranked list and `full: data/owner-attention/latest.txt` are gone. The composer is the front desk's, reached by path with a local fallback; a standing rule and a one-a-day cap gate it; and a queue item that contains no question gets a closing `Yes?`, because `textsend` opens an owner turn only on `[?？]` — the same defect as the CFO asks. | `/opt/company/scripts/owner_attention.py`, `/etc/systemd/system/lpt-owner-attention.service.d/10-no-text-20261015.conf` (**deleted**) | `send --dry-run` on the live queue → **231 chars, one item**, no count, no path, no marker: *"Apple's own Apple Business Manager Agreement forbids what we are already selling — Keep selling, but get the exposure measured by a lawyer before the camera product is built - and stop adding devices until that reading exists. Yes?"*. Six live items composed, 86–249 chars. `textsend._QUESTION_RE` on the body → opens a turn. `Deserves`-probe: a count head → `''`, a non-personal email → `''`, a personal email → its line. **The first real fire is 2026-10-16 14:13:52Z; nothing was sent by hand.** |

**Test attribution — done by A/B, because claiming green is how this estate lies to itself.**

### !! TWO OF THESE WERE REVERTED UNDER ME, AND ONE WAS NOT !!

Found at **15:2xZ**, while re-verifying: `/root/bin/cfo-ask.py`, `/root/bin/charge_msg.py` and
`/root/bin/merchant_resolve.py` had been **restored to their pre-change originals** (mtimes back to
`2026-10-14 03:11-03:13`, every one of my markers gone — `grep -c` returned 0 for all of them), while
`/root/bin/order_evidence.py` (mtime `15:09:43`) and the `/opt/company` files survived. They were
re-applied from the copies in this session's working tree at 15:2xZ and all four compile and carry
their markers again.

**No job admits to it.** Checked and cleared: root crontab (`lpt-deploy-drift` runs at minute 17),
`cron-script-guard.py` (its log has **zero** `HEALED`/`ALERT` lines and names none of the files — and
it only restores a script that is MISSING), the canonical `/opt/company/scripts/cfo/cfo-ask.py`
(different hash from both my version and the reverted one), and journald 15:05-15:30. A 6-minute hash
sampler was left running at `/root/text-fix-20261015/watch-hashes.sh` to catch a repeat.

**What this means for every "verified" claim above about a `/root/bin` file.** The verification was
real at the time (hash + behaviour, with the hash printed). **The persistence was not.** Treat items 5,
6, 8 and 9 as "applied and verified at 15:0xZ, found reverted at 15:2xZ, re-applied" until the
sampler has run clean for a day. This is `L4771` — a live artefact is not a branch — happening to the
same session twice inside one hour.

*Targeted subset* (8 owner-text/SMS test files, 132 tests), with and without the two app-file changes:

| | failed | passed |
|---|---|---|
| **without** my app changes | 13 | 119 |
| **with** my app changes | **10** | 122 |

The diff is exactly the three marker tests, fixed by the change. **No test regressed.**
Every remaining failure in that set (`test_api_endpoints` ×4, `test_owner_escalation_ceiling_agrees`,
`test_owner_message_dedup`, `test_owner_outbound_classification_gate`,
`test_owner_send_failure_is_recorded`, `test_owner_text_no_question`, `test_sms_charge_misroute`)
**fails identically with my changes reverted** — pre-existing, from the 30+ dirty files this tree
already carried.

*Full suite:* `47 failed, 3686 passed, 16 skipped` (later run 48 — the extra is a flake in the golden
gateway set). The failures are in `test_department_tools` (11), `test_shabbat_orchestrator`,
`test_shalom_zmanim`, `test_tool_contracts`, `test_work_generation`, `test_config_contract`,
`test_communications_contract` and friends. **None of them is mine**; I verified the two SMS-adjacent
ones by the A/B above and the rest do not touch a file I edited.

---

## 3. What is NOT done — read this before trusting the channel

1. **The doors are not wired to the front desk yet — one of them now is.** `compose`/`submit_item`/
   `standing_rule_mutes` are live and probed, `/root/bin/owner-text item` makes them reachable from a
   shell line, and **the daily attention text now composes through `relay.compose()`** (see #12). Still
   unmediated: `family_chat` writes its own, and the two read-only hosts still `curl` Twilio.
2. **Nothing composes for him yet.** Every door still writes its own body. The 900 → 400 → 320
   triple-cut, and the "compose long then truncate" habit, are unchanged. The marker removal makes a
   half-message *quieter*; it does not stop one being half.
3. **Two inbound paths are still uncoordinated.** The app webhook replies inline; the cron responder
   is a no-op. `textctx.recent_asks()` is missing, and the three ask stores still disagree. **What
   changed today:** the responder's `relay: ask -> missing` can no longer happen for a CFO question
   (#10), so a reply to one now resolves against the relay — the first time the ask ledger and the
   reply path have agreed about the same question. The other askers (`owner-ask.py`) still do not
   file with the relay.
4. **Identity is still one `LIKE 'owner%'` cell plus an unset `$OWNER_PHONE_NUMBER`,** and
   `+17325691594` is still `owner-google-voice` / `allow=never` against an exact `== "owner"` test.
5. **Six doors are still outside the relay**, including two hosts with a raw `curl` that the posture
   file marks read-only. The heartbeat's independence is deliberate (P3176) — the *other* unmediated
   doors are not.
6. **The provider pool is still one model** on the reply path. See `docs/mesh/177`.
7. **The 10,223 messages to his Google-Voice line** remain unexplained.
8. **`owner_text_suppression`'s single inert row is left in place**, undeleted, as evidence. The new
   standing-rules file is the working mechanism; a future session should migrate the *class* logic
   and then retire the substring matcher rather than delete the row.

## 4. Next, in order

1. Merge the two `owner_attention.py` versions — one item, no counts and no file path, **plus** the
   concurrent session's reserved personal-mail slot (a digest with four decisions and zero email
   lines was a real defect they measured; the one-item composer must not lose his own mail either).
   Then lift the systemd drop-in and prove the next fire.
2. Give every door one `compose()`: take an intent (subsystem, ref, evidence) and return **one**
   ≤320-char message. The relay already has the ledger; it needs the voice.
3. Route the remaining doors through the relay: `family_chat` owner leg, `owner-ask.py`,
   `card-due-watch.py`, `lpt-freshness-watchdog.py`. The heartbeat stays independent by design.
4. One ask ledger. Wire `textctx.recent_asks()` to `relay.open_asks()`, call
   `relay.answer_ask()` from *both* inbound paths, and delete the other two stores' authority.
5. **~~Wire the self-serve ladder into `cfo-ask`~~ — DONE 2026-10-15, see #8 above.** What is still
   open on this rung: `asked_keys` is keyed on the **merchant**, not the charge
   (`cfo-ask.py:484`), so an answered charge at a shop suppresses every future charge there; and
   `clarification` has a unique index on `reference` only (`cfo_clarify.py:186`), so N rows per
   charge are legal. Key the suppression on `(account_id, amount, date)` or the transaction id.
6. **Say why he is being asked.** The rungs now put the strongest evidence found into `evidence`,
   which `cfo-ask` copies into the question ("what our records DO say about it"), but the body still
   never says *which* rungs ran and came up empty. That sentence is the difference between an ask
   and an accusation.

## 5. The collision, recorded so it is not re-derived

At 14:46:16Z another session wrote `/opt/company/scripts/owner_attention.py` **while this audit held a
verified change to the same file**, replacing it wholesale and taking the `'N items, M urgent` head
back. That is journal **P13** ("concurrent sessions share one repo") happening to a live, deployed
script rather than to a git branch, so no merge conflict ever surfaced — the later writer simply won.
`/root/work/r7/` was mid-round on journal collisions at the same moment; `harness-config` was on
branch `incident/deepseek-spof-20261015` and carried `docs/owner-attention-audit-2026-10-15.md`.

**The rule this needs:** a file under `/opt/company/scripts` or `/root/bin` is a **live artefact**, not
a branch. Before writing one, check its mtime is not seconds old, and write a `.claim-<host>` beside
it — or do the edit in the repo and let the deploy carry it. `/root/bin` is not a git repository at
all, so a change there is invisible to every review this estate has.
