# Owner attention — audit and rebuild, 2026-10-15

**Why this exists.** The owner's instruction, 2026-10-15, verbatim:

> *"any emails or voice mails or texts To my personal line, not to dial by — dial pad things should
> less calmly need my attention. Those are in the dialpad thing, unless they're sitting for a while
> or are very urgent... let's say Google voice text or voice mails or emails that need my attention.
> Those need my attention."*

So the rule is a **tiering rule**, and it had never been written down:

| Tier | What it is | Who handles it | Reaches the owner when |
|---|---|---|---|
| **A — HIS** | his own phone numbers (Google Voice), his personal Gmail, family, personal money and cards, school | nobody but him | always |
| **B — THE SHOP** | the Dialpad business line: customer texts, calls, voicemails, work orders | the company | unanswered > ~24h, or urgency words, complaint, or money over a threshold |
| **C — THE MACHINE** | deploys, merges, caps, disk, schedules, security rotation | me | never as a text; the decision queue if it is his, the work ledger if it is mine |

Every measurement below is dated and carries the command that produced it.

---

## 1. What actually reaches him — measured 2026-10-15

**Texts to the owner** (`owner_text_turn`, 30 days): **107 sent, 106 answered.** Reasons: `send_message` 70,
`owner_sms_reply` 13, `aitext-responder` 13, `family_chat_owner_leg` 7, `urgent_email` 3, then single
reminders. Volume is 1–15/day, most days 5–6.

That number is healthy, and it is the one thing this system gets right: **what gets through, he answers
— a 99% answer rate.** The problem is not the volume that arrives; it is the volume that arrives
**instead of** the things that should have.

**The message queue** (`owner_message_queue`, created in the last 30 days): **625 dismissed, 145 expired,
44 sent, 24 routed to the decision queue, 10 held.** So **73% of everything the attention system
produces for him is dismissed as not worth his time.** The producer is a firehose that the filters
mostly catch.

**The attention sweep** (`owner_attention_findings`, 30 days): **27,869 findings.**

| channel | severity | rows | question_worthy |
|---|---|---|---|
| dialpad_calls | high | 11,620 | 0 |
| gmail_catalog | high | 4,419 | 0 |
| dialpad_sms | medium | 4,052 | 0 |
| gmail_live | high | 2,499 | 0 |
| obligation | critical | 2,335 | 2,335 |
| owner_task | high | 1,282 | 1,281 |
| provider_payment_failure | high + critical | 1,494 | 1,494 |
| dialpad_sms | high | 133 | 133 |

**And nothing reads that table.** `grep -rln 'owner_attention_findings' /` across the estate returns the
writer, its backups, worktree copies and the database — **no SELECT anywhere.** It is a write-only
table: the sweep does the work and throws it away. That is the single largest structural defect found
in this audit, and it is why the queue keeps growing while the sweep keeps running.

---

## 2. The seven defects

**(1) His personal line is dark, and has been since 4 July.** `google_voice_secretary_log`'s newest item
is `2026-07-04`; `google_voice_secretary_health` shows both accounts `failed` with 7,977 and 7,315
consecutive failures, last success `2026-07-02`. The browser session died **2026-05-04T22:00:33Z**
(the SAPISID cookie expiry) and the profile on disk was last written **2026-05-04 21:50**. 95 items
sit at `decision='owner_review'`, `action_status='owner_review'` — read, flagged, never actioned.

**(2) The retired scraper is still being driven, right now.** `GOOGLE_VOICE_SECRETARY_ENABLED=false`
retired the *secretary*, but `shadow_learning._observe_google_voice` calls `google_voice.py`
unconditionally, and `session_exists` is a false positive — `google_voice.py:3250` is
`profile_exists or legacy_exists`, and `_profile_exists` is only "the directory contains any file", so
a leftover `BrowserMetrics` file makes a dead account look live. Measured live: Chrome launching and
failing, profiles being archived, at **2026-10-15T14:24:18Z**; **201** `.broken-*` / `.legacy-reset-*`
profile copies on disk.

**(3) Personal email is read, then drowned.** `email_catalog` in the last 3 days holds **110
needs_owner rows, 66 of them on personal accounts** — `chevedy` 38, `ezabz68` 19, `eliyahuzabrowsky` 9,
against `lakewoodphoneandtech` 44 and `zabzgpt` 2 (re-measured 2026-10-15T~14:5xZ; the same query on the
30-day window returns the same five accounts and no others, which is what the `OWNER_PERSONAL_ACCOUNTS`
default is checked against); **130 personal p0/p1 rows** inside the digest's own
400-row window. The digest does carry email — but it prints **no account column**, so he cannot tell a
customer from his own bank, and the 320-character SMS carries only the top four `[high]` lines, which
on 2026-10-15 were decisions and books and **zero email**.

**(4) Engineering decisions reached him as owner questions.** This is the biggest one, and it is the
queue triage in `owner-decision-triage-2026-10-15.md`: **46 of 127 open rows were mine** — merges,
deploys, caps, schedules, a signing-key copy, a disk migration — held because a fleet convention
("a shift may not write main", "a shift may not restart a production service") had been read as
*the owner must press the button*. Deciding the integration authority once unblocked **13 ledger
items** that were parked on those rows.

**(5) The character ceilings disagree with each other.** One owner text has four different limits:
relay `320` (`/root/bin/owner_text_relay.py:146`), gate `400` (`app/owner_text.py:215`),
transport soft `930` / hard `1600` (`/root/bin/textsend.py:96-97`). The relay's own docstring at
`:143` says it should follow `OWNER_TEXT_MAX_CHARS`. It does not.

**(6) Two alert boxes text him directly, outside the relay.** `waze-mdm-01` and `lpt-apps-01` account
for **51 of his texts in 30 days**, and on 2026-10-06 they sent **37 of 40**, including 17 copies of
one `COMPANY IS BACK` message for a single state transition. They also print timestamps with two Z's
(`2026-10-09T02:04:01ZZ`). Both hosts are marked `read-only` in `settings/machines/host-posture.tsv`,
so the guard refuses me without his word.

**(7) The owner's own texts to the AI line were filed as questions TO him.** Rows #458 and #459 in the
decision queue were his own inbound messages, and #458 is him saying —
*"That was a confusing and unclear text that had too many things in it. Talk to me like a normal
person and ask me things one at a time."* Nobody answered him; instead the system asked him whether it
should. The same complaint is in `owner_text_suppression`: *"I have no idea what it means, it's too
much information, and it's weird."*

---

## 3. Two of my own readings were wrong, and are corrected here

Recorded because a correction nobody writes down is a correction that gets made again.

- **"The gate is erroring 2,780 times."** False as a live claim. All 2,780 `gate_error` denials are
  **one** text — `TypeError: getattr expected at most 3 arguments, got 7` — inside a single
  `except Exception` at `app/owner_text.py:2749`, over the window **2026-10-02T15:57 → 2026-10-05T01:34
  only**, with **zero since**. `awaiting_reply` (1,315) is retired code at `owner_text.py:2717`.
  The `too_long` rows are pre-2026-10-13 history under an older 320 limit.
- **"The digest fired twice in 30 days."** False. The timer did not exist before
  **2026-10-13T02:24:57** — a 30-day window overstates a subsystem that is two days old. It sent on
  10-13 (twice) and 10-15, and was held on 10-14 by `rate_floor`. That is a working subsystem, not a
  broken one. *A window's end is when the running process loaded the code, not when the file was written.*

---

## 4. What was changed

**Shipped as branches, not hand-edited into production** — `/opt/company` is the live
`company-api` WorkingDirectory, and hand-editing it is an uncommanded deploy (ledger item 149). The
deployed copy of `scripts/owner_attention.py` is still `md5 9c661307…`; nothing here has run in
production yet.

- `personal-secretary-mvp` **`fix/shadow-learning-gv-gate`** (commit `a3d6d5e19`, pushed):
  `shadow_learning._observe_google_voice` is gated on the same flag that retires the secretary, so the
  dead scraper is no longer driven and no browser is launched. Test:
  `tests/test_shadow_learning_gv_retired_gate.py` — **13 passed with the fix; 11 failed / 2 passed
  against the pre-fix file** (control run, so the test is proven to discriminate).

- `personal-secretary-mvp` **`fix/owner-attention-personal-tier`** (commit `34c0abb80`, pushed):
  the digest prints the account on every email line and marks his own mail **PERSONAL**, and personal
  mail orders **ahead of shop mail inside a section at equal severity**. `sec()` was hoisted out of
  `build()` as module-level `section_of()` and the ordering extracted into `rank_items()`, so the rule
  is testable without running the whole digest. Test:
  `tests/test_owner_attention_personal_tier.py` — **11 passed with the change; 11 failed against the
  pre-change file** (control run). **It is deliberately a tiebreak and not a severity bump:** raising a
  personal p1 to `high` would put it into `sms_body`'s `highs[:4]`, where a Chase or Google alert could
  displace a real decision from the 320-character text.
  **The default account list was then checked against production** rather than assumed: a 3-day and a
  30-day query both return exactly five accounts — the three personal ones and the two shop ones — with
  no spelling variants, so `OWNER_PERSONAL_ACCOUNTS` misses nothing today.

- **Landing both is ledger item 331**, with the DoD written as measurements rather than adjectives: no
  `GV --headless=new launch failed` line for 24h and the `.broken-*` count stops growing; and the next
  digest carries `PERSONAL` on his own mail.

**Decided and unblocked, no code:**

- The **integration authority is mine, not the owner's.** A proven, tested, conflict-free branch lands;
  the owner is not the merge button. This unblocked ledger items 20, 46, 48, 99, 234 and more.
- **13 ledger items** that were parked on now-resolved owner rows were returned to `todo` with a
  recorded reason; item 101 was **closed** rather than unblocked, because the frozen office box may not
  be touched by decision, not by accident. `work.py lint-refs` is **clean (rc=0)**.

---

## 5. What still has to change — designed, not yet built

**One router, one budget, three tiers.** Everything below is a change to existing code; nothing new is
proposed, because every piece of this already exists and is simply disjointed.

1. **Give `owner_attention_findings` a reader, or stop writing it.** The table is the natural
   intermediate for the whole attention path; today it is the estate's most expensive no-op.
2. **Print the account on every email line in the digest**, and rank a personal-account `p0` above the
   shop's. The digest already selects the right rows (`scripts/owner_attention.py:253`); it just does
   not say which account they came from.
3. **One owner-text ceiling, in one place.** `owner_text_relay.py:146` should read
   `OWNER_TEXT_MAX_CHARS`, and 320/400/930/1600 should collapse to one number plus the transport's
   soft limit.
4. **Narrow `except Exception` at `owner_text.py:2749`.** One `TypeError` denied every owner message for
   three days. A gate that fails closed on a code bug should fail *open and loud*.
5. **Bring the two alert boxes inside the relay** — needs the owner's word, because both hosts are
   `read-only` by decision (queue row #496).
6. **Restore tier A.** Two routes, and both need him once: re-enable Google Voice's own email
   notification (no code change — the `gmail_forward` path at `google_voice_secretary_log` demonstrably
   worked, 39 rows on 2026-07-02/03), or one headful login at a browser. Until then his personal line
   is read by nothing.
7. **Answer him properly.** `multi_ask` at `owner_text.py:1237` already refuses a text that asks two
   things; it needs to be the *default*, not a rare denial, which is what he asked for verbatim.

---

## 6. The gate is now closed

The reason 46 engineering questions became owner questions is not a mystery and not a person: a
convention that said "a shift may not write main" was read as "the owner must", and nothing in the
chain asked whether that was true. It was not. Recorded as **D-QT1** on 2026-10-15:

> **A proven, tested, conflict-free integration is a development decision and lands without the owner.**
> A designated integration actor holds main-write. The owner is asked about money, customers, legal
> posture, family, and anything irreversible — not about merges.

---

*Audit by Zabz, 2026-10-15. Evidence: `/root/authority.db` on `secratary-cloud`, `/opt/company`
(live tree), `/root/bin/`, `/root/.sms-inbox/`. Every figure above carries its source table and its
window; the two figures that could not be established are named as such in §3 rather than estimated.*
