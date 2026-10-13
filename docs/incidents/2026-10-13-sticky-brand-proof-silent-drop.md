# INCIDENT — 2026-10-13 — Sticky Brand proof for order #828330: a counterparty deadline that never reached the owner

**Filed:** 2026-10-13 (ZABZ-TECH session, on the owner's direct complaint)
**Severity:** owner-facing process failure, realised in money and in a forfeited pre-print check. Bounded: nothing shipped.
**Systems implicated:** `personal-secretary-mvp` — `app/services/email_intake.py`, `app/services/email_classifier.py`, `app/services/email_actions.py`, the delegated-task lifecycle, the owner-notification gate.

## 1. What happened

| when (UTC) | event | evidence |
|---|---|---|
| 2026-10-05 04:13:39 | Order #828330 placed, Sticky Brand. 100 x 2.5" + 200 x 2" custom vinyl stickers for the Waze device product. Subtotal 48.00 + 8.49 shipping + 3.74 tax = **USD 60.23**, Amex 2005, Shop Pay. | Gmail `1a10a44713d3f00a`; Shopify order `7228475441408` |
| 2026-10-05 19:21:22 | **`Approval Needed #828330`** — "Your artwork is ready for approval. **ACTION REQUIRED: REVIEW AND APPROVE YOUR PROOF**" | Gmail `1a10d837b4e456ea` |
| 2026-10-05 19:24:21 | Triage logs it as `personal/needs_review`, `confidence_tier='low'`, **`action_taken='none'`, `action_status='skipped'`** | `email_triage_log` id 3791 |
| 2026-10-06 13:27:05 | **`Final reminder Review Proof for order #828330`** — "**IF NO FEEDBACK IS RECEIVED WE WILL AUTOMATICALLY BEGIN PRINTING YOUR ORDER IN 2 DAYS**" | Gmail `1a111657fb4aea08` |
| 2026-10-06 14:32:46 | A task is raised: `Review Sticky Brand print proof for order #828330 (auto-print in 2 days)` | `tasks` id 27694 |
| 2026-10-06 14:33:42 | The owner SMS that would have told him is refused by the one-at-a-time gate and only logged: `[suppressed] owner_text gate refused (awaiting_reply)` | `activity_log` id 323794 |
| 2026-10-06 14:37:07 | Task delegated to `dept_mashgiach` | `delegations` id 6065 |
| 2026-10-06 15:38:26 | Delegation `completed` and the task marked **`done`**, with **`result_summary=''`** | `delegations` 6065, `tasks` 27694 |
| ~2026-10-08 13:27 | Auto-print begins, as the email warned it would | vendor email text |
| 2026-10-13 ~18:26 | The owner, unaware of all of the above, creates a Sticky Brand customer account three times trying to find the proof himself | Gmail `1a136837ba6be26e`, `1a13683c823577a2`, `1a136843098fbced` |
| 2026-10-13 18:30 | Read live: `Fulfillment status: Confirmed — We're preparing these items for shipping`. **Nothing shipped. The proof approve control is gone.** | `account.thestickybrand.com/orders/f1bb883975d69505446670c743b93c2e` |

Never present anywhere he would see it: `owner_decision_queue` — no row. `owner_message_queue` — no row. SMS — none. Journal — none before this incident.

## 2. Root cause — four independent silences

**2.1 The classifier's unknown branch is silent.** `app/services/email_intake.py::classify_message()` is an ordered if-chain. `Approval Needed #828330` matched none of rules 1–10 and fell to the terminal fallback at ~line 455: `{"category": "review", "priority": "p2", "needs_owner": 0, "confidence": 0.4, "reason": "default"}`. Separately, `_ORDER_RE` (~line 231) includes the alternative `order\s+#`, so `Final reminder Review Proof for order #828330` matched rule 8 — `{"category": "order", "priority": "p2", "needs_owner": 0, "reason": "order/shipping"}`. **A printing deadline classified as a shipping notice.** There is no rule anywhere in the table for "someone is asking you to approve something".

**2.2 A triage outcome that means "I don't know" produces no action at all.** 177 rows since 2026-10-01 carry `action_taken='none'`, every one `sub_category='needs_review'`: Telnyx low-balance alerts, `[Action Required] Mark AI agent OAuth clients as agentic for Google Workspace MCP by Nov 11, 2026`, Dialpad voicemail notices, and customer mail. Structurally, 1,114 of the 1,116 triage rows since 2026-09-20 are `category='personal'` — the shop's business mailbox is being classified as personal mail.

**2.3 A task created for a decision was closed by an empty string.** `tasks` 27694 → `done` in 66 minutes, `delegations.result_summary=''`, and no `activity_log` row beyond `task_delegated`. Every downstream reader sees a closed loop.

**2.4 The last channel dropped instead of queueing.** The `owner_text` one-at-a-time gate is correct policy; refusing and writing only an `activity_log` line is not. The item was lost, not deferred.

## 3. Consequence

- The pre-print check the shop's own order included was silently forfeited, on the branded stickers for a product about to be sold.
- Money: USD 60.23 printed without the check the owner paid for the option to have. No refund is due; the loss is the check itself.
- The class is unmitigated until §4 lands: any counterparty that ever asks him to approve, confirm or respond by a date is currently at the mercy of a regex table with no rule for it.

## 4. Required fixes

| # | Fix | Where |
|---|---|---|
| 1 | High-precedence ACTION-REQUIRED/deadline rule *before* the money and order rules; the silent default branch must not report `needs_owner=0` unflagged | `app/services/email_intake.py` |
| 2 | `needs_review` must route to a surface a human or agent reads, never a bare `action_taken='none'` | `email_classifier.py` / `email_actions.py` |
| 3 | A task whose origin is an owner-facing approval or deadline cannot be closed with an empty result | task lifecycle |
| 4 | An owner-notification suppression must queue, never drop | owner-notification gate |
| 5 | One named, tested end-to-end path from inbox to owner — because four components each reported success while the owner learned nothing | system-level |

## 5. What is NOT claimed here

Nothing has been fixed by the filing of this document. Three mesh children (`subagent-19/20/21`) were dispatched the same session to produce patches for fixes 1–3; **no patch has been integrated, no test reproduced, no service restarted.** Until that integration is done and each test is reproduced independently, the status of every fix above is *proposed*.
