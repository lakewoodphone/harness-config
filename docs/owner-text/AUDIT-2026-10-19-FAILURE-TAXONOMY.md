# The owner text channel — failure taxonomy, 2026-10-19 (round 3)

**Purpose.** Every failure below was measured in this session against the authority's own
`sms_log` (4,283 rows), `owner_text_turn` (151 labelled rows), `owner_text_decision` (9,279
rows) and by running the live code. Each carries the command or the row that proves it.
This is the work list. Supersedes round 1/2 findings only where it says so.

Reading the corpus does not mean the prior audits were wrong — `OWNER-TEXT-AUDIT-2026-10-15.md`
found F1–F9 and round 2 (`7de8340a9`) shipped the topic ledger and preask. **What is new here
is §2 (the resolver lies), §3 (dual delivery), §4 (attribution), §5 (family chat), §6 (quiet
hours)** — none of which appear in the 10-15 "next in order" list.

---

## 0. The corpus, measured

```
select status, direction, count(*) from sms_log group by 1,2 order by 3 desc
  ('suppressed','outbound') 2043   ('failed','outbound') 1044   ('received','inbound') 487
  ('delivered','outbound')   380   ('sent','outbound')    305   ('undelivered','outbound') 15
```
Owner number `+18483897895`; AI line `+17324447361`. Owner-channel rows: 3,890
(548 outbound with a real from-number, 350 inbound, 2,955 attempted with `from_number='unknown'`).

Attempted-vs-delivered by sender (`agent_id`), all time:

| agent | attempted | suppressed | failed | **delivered** |
|---|---|---|---|---|
| `sms_service.audit` | 3,044 | 2,025 | 930 | **85** |
| `orchestrator` | 480 | 6 | 60 | **415** |
| `family_chat.owner_leg` | 15 | 6 | 0 | **9** |

**The gate is suppressing a firehose it should never have generated.** 85 of 3,044 audits reach
him; the work is spent on refusal, not on composition.

---

## 1. He said the same four things, in his own words, and each maps to a mechanism

| what he said | when | mechanism |
|---|---|---|
| *"You could do a little more research before you ask the questions"* (DeepSeek API charge) | 10-02 18:58 | resolver rung never consults what kind of merchant it is |
| *"I have no idea what it means, it's too much information, and it's weird"* (digest) | 10-13 14:21 | digest composer emits counts + a truncated file path |
| *"I already told you these random briefs seem pointless. I need one item at a time"* | 10-14 14:18 | same composer, still firing |
| *"You literally sent me this text earlier. What the hell I think you unified brain broke."* | 10-01 15:04 | he replies to a text the agent cannot see it sent |
| *"Don't you know what fuel is? It's gas to power a car. You're making me upset."* | 10-19 05:49 | charge ask with no category inference |
| *"Didn't we file a few days ago? What are you talking about?"* | 10-19 13:37 | answer not found → re-ask |
| *"I got the freaking message. You texted me three times already."* | 10-08 22:02 | same reminder, 4 sends |

---

## 2. The merchant resolver claims solutions it does not have — **the highest-value defect**

Command (this session, on the authority):
```
/usr/bin/python3 /root/bin/merchant_resolve.py --no-research --why \
  "fuel" "adjust membership fee" "photo" "api"
```

| merchant | resolver says | the truth |
|---|---|---|
| `fuel` | solved=True 0.97 `aliases` → *Gas & Fuel* | **learned only today, from him shouting.** Before today it asked. |
| `adjust membership fee` | solved=True **0.92** `records:owner-answer` | the "answer" was *"I don't know. I want you to figure this out"*. No entity, no category. |
| `photo` | solved=True **0.92** `records:owner-answer` | the "answer" was his reply about **Dave & Buster's** — a different merchant. |
| `api` | solved=True **0.92** `records:owner-answer` | the "answer" was *"Didn't we file a few days ago?"* — a non-answer. |

`_from_answered_asks()` treats **any** answered ask for a merchant key as a solution. Then
`solved=True` means **do-not-ask**, so the charge is never categorised and never fixed. So the
defect is two-sided and silent: it asks about the obvious ones, and it *stops asking* about the
ones it got a useless answer to. That is why the same merchants keep returning weeks apart.

**`pass on`** (E-ZPass toll, `PASSNY TOLLBYMAI`) → `solved=False` on every rung, because the
key has no distinctive token and there is no descriptor inference. He answered it himself in
one line: *"It looks like easy pass to me and that's just from your text."*

---

## 3. One send is recorded twice, and a refusal is recorded as a failure

**CORRECTED 2026-10-19 16:50 UTC.** This section first said two paths *deliver* the same text.
That was wrong, and the check that falsified it is the SID.

```
select twilio_sid, count(*), group_concat(agent_id) from sms_log
 where to_number='+18483897895' and direction='outbound' group by 1 having count(*)>1
```
Every pair shares **one sid, one second, one body**, and differs only in `agent_id`:

| sid | time | rows |
|---|---|---|
| `SMf8afb70d965aff4eea5b…` | 2026-10-19T01:25:54 | `sms_service.audit` **delivered** + `orchestrator` **delivered** |
| `SMfeff4df9391f4eedd326…` | 2026-10-19T05:48:43 | same |
| …25 more | 2026-09-30 → 2026-10-19 | 27 pairs, **27 extra rows** over 300 real sids |

**One delivery, two ledger rows.** `sms_service.send_message` is wrapped in `_audited_send`,
which writes a row for every attempt and sets `result["_audit_logged"]`. Three call sites then
write a second row for the same send. `main.py:6139` already records what it costs: *"Writing
again here put two rows in the table ~7 ms apart, so ONE real message consumed TWO of the three
daily owner-quota slots."* — that site was fixed; these three were not.

**Worse than a duplicate row:** those callers force `status="sent" if ok else "failed"`. A send
the relay **SUPPRESSED** is therefore written as `failed` under `agent_id='orchestrator'` — 60
such rows. Suppression and failure are different facts and were recorded as one.

**What this did to every measurement**, including this audit's own first pass: a corpus of
"509 delivered texts" was really 482, and the "burst" of texts around each reply looked larger
than it was. A per-row count of `sms_log` is **not** a count of texts he received.

**Fixed this session:** the guard `if not result.get("_audit_logged")` added to
`chat_action_runtime.py:2035`, `chat_action_notifications.py:32`, `main.py:5976`; the caller's
`status` is now preserved when present rather than forced. Deployed by atomic rename with
`py_compile`-equivalent parse proof, `company-api` restarted, `/health` 200 at 0.026 s, and the
no-op proved by direct call: 0 rows when already audited, 1 when not.

### 3b. The real number: he answers into a pile

With that double-counting removed, the corpus says something worse than duplication:

```
delivered: 482 distinct texts      he replied within 6 h: 240 (49.8%)
responsive (reply shared a distinctive word with the text): 72 (14.9%)
burst: of 240 replies, 193 followed MORE THAN ONE text — median 4, maximum 32
```

**83% of the time he answers, he is answering into a pile of texts, four on average.** That is
the "unified brain is not working" complaint measured, and it is why any inference about which
message he answered is a coin toss — and why he has to ask *"which one are you calling out?"*

---

## 4. An answer closes the wrong ask — the root cause behind §2 and the re-asks

`owner_text_turn.answer_body` in the labelled set is filled with *the most recent inbound text*,
not the reply to that specific message. Proof: one reply — *"I don't know. I want you to figure
this out…"* — is attached to **ten consecutive rows** (ids 117–127), and *"That was just
groceries"* to six (ids 48–53).

Consequence chain: reply mis-attributed → ask closed with a non-answer → merchant alias learned
from it (§2) → charge not categorised → the question returns.

He has described this from the outside three times: *"which one are you calling out?"*,
*"Didn't we file a few days ago?"*, *"are you sure I didn't tell this to you already?"*

---

## 5. The family chat is wired into the owner channel

`agent=family_chat.owner_leg` — 15 attempted, 9 delivered, and 22 of the 151 labelled turns.
Delivered to him:

```
[Family Chat] Failed to deliver to: ETZ
[Family Chat] ETZ ((848) 389-7895) is unsubscribed at Twilio — removed from active roster.
[Family Chat] Chip was addressed by Dov and did not answer (quiet hours).
```
plus the family group's own messages (`Shabsi: MOOSE MASTER!`, `Mommy: Mazel tov!`) recorded as
owner-channel turns, which then consume the one-open-turn budget and shut the real channel.

His instruction, this session: *"This is not the family chat, obviously."*

---

## 6. It texts him while he is asleep, and asks for credentials over SMS

Delivered outbound by local hour (UTC−4, October): **112 of 548 (20.4%) arrive 23:00–07:00.**
The `sms_log` shows reminders at 02:29, 02:55, 03:09 local.

And two asks he should never have received on a phone:
- `2026-10-16 14:24` — *"Give me the NJ Premier Business Services login and I will file 06/2026"*
- `2026-10-17 14:22` — the same, with a user id in the body.

---

## 7. Bodies that are not messages to a human

| body | class | why it is wrong |
|---|---|---|
| `⏰ Reminder: VS Code session: present ONE numbered owner-approval ask — (1) #27836…` | instruction to an **agent** | he is not the agent |
| `⏰ Reminder: EXECUTE: Pay Yisroel Weinberg $597.29…Record date+amount in lpt-hub/docs/…` | work-order prose | paths and table names in his text |
| `Task #26089: … Record result in docs/personal/health/groin-skin-condition.md section 9 (branch docs/owner-health-2026-09-18)` | private + internal | branch names to a phone |
| `[Budget exceeded for : ceoreserveexhausted]` | internal error | sent to him, twice |
| `Dov - for Yitz's nightly learning, the OnePlus Buds 4…` | **addressed to someone else** | wrong recipient |
| `'10-13 14:21 UTC  36 items, 20 urgent\n- Q3 2026 estimated tax…full: data/owner-attention/latest.txt` | digest | his own words: *useless, too much, weird* |
| `- The parent notice is live and unsigned, and the contact block you supplied is` | truncated mid-sentence | no head, no ask |
| `Remembered.` / `Captured as a task.` | ack noise | carries no decision |
| `Telnyx balance at -$0.01 — services suspend at $0 Yes?` ×3 | **factually false** | his screenshot showed **$103.50** |

---

## 8. A duplicate row per send, in the ledger itself

29 of 151 labelled turns share a `sid` with another row (`1`/`2`, `3`/`4`, `33`/`34`,
`39`/`40`, `98`/`99`, `106`/`107`, `118`–`125`, `128`–`135`). One physical send is recorded
once per `reason`. Any statistic that counts turns rather than `sid` overstates volume by ~19%.

---

## 9. What is already built and must be USED, not rebuilt

| component | state | use it for |
|---|---|---|
| `owner_text_relay.py` (76 KB, live) | gate, topics, asks, cooldowns, stale-reference rule | the single chokepoint |
| `owner_topic.py` | topic keys + cooldown windows | §2 recurrence |
| `merchant_resolve.py` (1,198 lines) | aliases → records → receipts → research | **fix its honesty**, don't replace it |
| `preask.py` | the diligence ladder runner | wire the missing rungs |
| `owner-text-scorecard.py` | outcome instrument (ANSWERED/COMPLAINED/IGNORED) | the evolution loop |
| `owner-text-audit.py` + tests (106 KB) | static audit instrument | regression gate |
| `text-health.py` | 12 invariants, exit 1 on failure | post-deploy proof |
| `verify-owner-text.sh` / `deploy-owner-text.sh` | mirror⇄live hash, atomic rename | deploy path |

Stale but **not invoked** (a trap for the next reader, not a live risk): two 21 KB copies of
`cfo-ask.py` at `/opt/company/scripts/cfo/` and `/opt/company/scripts/owner-intake/`, dated
2026-10-07, still containing *"My guess: shop supplies"*. Verified: no cron or unit calls them.

---

## 10. The order of work, by measured cost to him

1. **§4 attribution** — one bug, and §2's lies plus four of his complaints fall out of it.
2. **§2 resolver honesty + descriptor inference** — stops the questions he calls stupid.
3. **§3 single delivery path** — stops the doubles.
4. **§7 one composer** — stops the task prose, the digests, the ack noise.
5. **§5 family chat unplugged** from the owner channel.
6. **§6 quiet hours + no credentials on SMS.**
7. **§1/§8 the evolution loop** — scorecard runs itself and the numbers are readable.
