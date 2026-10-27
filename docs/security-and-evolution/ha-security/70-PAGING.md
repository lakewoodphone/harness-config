# 70 — Paging: how a security decision reaches the owner

**2026-10-27. Written before any code, because the contract is the hard part and the mapping is nearly free.** The
estate already owns a priority-aware owner notification system; the security page must join it, not imitate it.

> **CORRECTED the same evening, from a measured reading of the live path.** The first version of this document assumed
> the security alert already travelled through the priority system and only needed a level→priority mapping. **It does
> not. `POST /webhook/ha/security-alert` bypasses `notification_manager` entirely** and calls `send_message` directly,
> so there is **no priority, no quiet-hours awareness, no digest and no interrupt-cost gating anywhere on the security
> path today**. The mapping below is therefore a *change of route*, not a reuse of an existing one — and the four
> defects in §1b are things that would have made the pager fail silently *after* it looked finished.

## 1. The system to reuse, and the reason it is not currently reused

`app/services/notification_manager.py` — read at `228-337` (2026-10-27):

```python
async def notify_owner(settings, message: str, *, urgency: str | Priority | int = "normal",
                       source: str = "system", force_immediate: bool = False) -> dict
```

| priority | what it does (`CHANNEL_ROUTING`, line 74-77) |
|---|---|
| **P0** `urgency="critical"` | **SMS now + a voice call attempt**, always interrupts, never batched |
| **P1** `urgent` / `stuck` | SMS now if interrupt cost < 0.8, else digest |
| **P2** `normal` | SMS if interrupt cost < 0.5, else digest |
| **P3** `low` | digest only |

Also already present and inherited for free: `owner_quiet_hours` inference, digest snooze
(`snooze_digests_for`, line 86), the outbound retry buffer, `_owner_sms_allowed()` (line 406), digest batching
(`_batch_for_digest`, line 442), and a **hard kill switch that blocks all owner SMS including P0** (line 370).

## 1b. What the live path actually does — measured by the fleet, 2026-10-27, from the repo at `da7d1946`

Read from `app/main.py:8505-8666`, `app/sms_service.py:1743-1949` and `app/config.py` on a mesh child that reported its
revision. Five findings, each of which would have shipped as a silent failure:

| # | finding | why it matters |
|---|---|---|
| 1 | **The owner's daily SMS quota (20/day) applies to security pages.** `direct_owner_request` is never set on this path (`sms_service.py:948-1042`), so only the kill switch is bypassed, not the quota. | After 20 owner sends in a UTC day, **the owner is silently dropped while the extra recipients still get paged** — the one person the page exists for is the one who can miss it. |
| 2 | **`paged: true` is hardcoded** in the 200 response, including when no recipient is configured or Twilio is unconfigured (`main.py:8653-8663`, `sms_service.py:1937-1938`). | `ok` is the only honest field. Anything that gates on `paged` believes a page happened. |
| 3 | **`ok = all(recipients)`** (`sms_service.py:1948`) and Home Assistant retries on `not ok` up to 4 more times, 12 s apart (`phoenix_intrusion_evidence.yaml:303-332`). | **One** bad or quota-blocked number makes every retry re-page the recipients who succeeded: up to five copies for them, zero for him. |
| 4 | **Dedupe is inert.** The DB duplicate-body block references an undefined `settings` and imports a `get_db_connection` that does not exist (`sms_service.py:572-617`). What actually holds is an in-memory 10/hour per number. | Two POSTs ten seconds apart produce two full pages; nothing at the endpoint is idempotent. |
| 5 | **No cancel, no nonce, no id.** Two security routes exist in the whole app (`main.py:8505`, `8670`); the request and response carry no identifier, and the only handle is the per-recipient Twilio SID returned over HTTP. | An acknowledgement cannot be built on top of this without inventing the identifier first. |

Two further measured facts that shape the work: the recipient list is **`owner_phone_number` plus a comma-separated
`HA_SECURITY_EXTRA_RECIPIENTS` env var** — not a roster, not a tier — and `OWNER_NOTIFY_NUMBER` is **ignored** on this
path although `owner_notify_target()` exists for exactly that purpose; and **the picture has never travelled**, because
the Home Assistant evidence script aborts: `shell_command.phoenix_verify_evidence_files` contains a bare `for … done`
that is `exec`'d rather than shell'd (`[Errno 2] No such file or directory: 'for'`), and the WIP fix `069a18b` does not
parse.

**So the build is not "wire level 3 to a page". It is: give the security path a priority, exempt it from the daily
quota, make its success signal honest, make it idempotent, and give it an identifier — then wire it.**

## 1c. **The page already exists. Do not build a second one.** (Measured 2026-10-27, second reading)

This is the correction that matters most, and it invalidates the plan in §2 and §6 below.

**Home Assistant already pages, end to end, today.** `live/phoenix_security.LIVE2.yaml:384-391` defines:

```yaml
rest_command.phoenix_security_page:
  url: https://ai.abletelsolutions.com/webhook/ha/security-alert
  method: POST
  headers: x-ps-api-key: !secret secretary_security_api_key
  payload: { event, detail, avs_level (default 3), snapshots }
```

called from `script.phoenix_intrusion_evidence_and_page` (`live/phoenix_intrusion_evidence.LIVE.yaml:312`), with a
four-attempt retry loop after it (`:324-335`). The receiving end is live (`app/main.py:8505`) and sends SMS/MMS to the
owner, his wife and his mother. It reaches a real Twilio send.

**Therefore a Python pager in the company would be the second one** — the thing this estate's own rule forbids and the
thing that would have produced two pages per intrusion. The architecture is already the one the owner described:
**reflex and response in Home Assistant, judgement in the company.** The company's job is to *record and judge*, not to
send.

**What that means for the build list in §6 — the corrected order:**

| # | work | where | why |
|---|---|---|---|
| 1 | **Make the evidence script finish.** A bare `for … done` inside `shell_command.phoenix_verify_evidence_files` is `exec`'d rather than shell'd (`[Errno 2] No such file or directory: 'for'`), so the chain aborts and **the picture has never travelled** | HA package file | without it, every page is text-only and the requirement "a picture of every person" fails at the first step |
| 2 | **Stop the retry amplification.** `ok = all(recipients)` plus HA's 4-attempt loop = up to five copies for whoever succeeded, driven by one bad number | backend + HA | a page that repeats is a page that gets ignored |
| 3 | **Exempt the security page from the owner's 20-a-day quota**, as the kill switch already is | `sms_service.py` | otherwise the owner is the one recipient who can be silently dropped |
| 4 | **Make the response honest** — `paged` must not be hardcoded `true`; `ok` must mean "the owner got it or did not" | `main.py:8653-6663` | every downstream decision gates on it |
| 5 | **Invent the page identifier** — the payload already carries `avs_level` and nothing carries an id | backend + HA | cancel, acknowledgement, dedupe and `security_action` all need it |
| 6 | **Write `security_action` on every attempt** — nothing anywhere writes that table today, so `security-digest` reports "0 pages" forever and its one-line summary keeps saying nothing happened | backend | the record must say what was *done*, not only what was *decided* |
| 7 | **The declared shop state**, so `R_DOOR` can reach level 3 at all | company | the judge cannot call an event level 3 while "empty" means "nobody anywhere in the basement" |

**Two further measured facts to carry:** a level-3 decision is stored as `decision='ESCALATE'` and **never `'ALARM'`**
(`security-sentinel.py:337`) — anything keyed on `ALARM` misses every level-3 event, and `avs_level` is a bare INTEGER
with no CHECK constraint; and the payload field `avs_level` that HA already sends **is not documented in the handler's
docstring and is not used**, so the priority hook exists in the wire format and is unwired.

**One stale-tree warning.** The child that produced §1c read `harness-config@92d318047` on another node and reported
that `security_evidence`, `02-evidence.sql` and `03-expected-state.sql` do not exist. That is true **of that commit** and
false of the branch: all three were created on 2026-10-27 and are in `agent/security-q1-20261027`. A mesh child cannot
see a local worktree, and its checkout was six weeks behind — so its schema claims are superseded, while its findings
about the HA page path and the missing `security_action` writer are not.

## 2. The level → priority mapping, and why it is exactly one line each

| security decision | page | why |
|---|---|---|
| `avs_level 3`+ **and** `decision='ESCALATE'` | **P0** — SMS + voice call | this is the case the system exists for: a door opened with no credential in a shop declared closed. A page that waits for a digest is not a security system |
| `avs_level 2`, `decision='ESCALATE'` | **P2** — digest | "a note, not a page" is the sentinel's own words, and P2 is exactly that |
| `avs_level 0-1`, or `NO_ALARM` | nothing | a credential was used; there is nothing to say |
| the model's own verdict beside the rules (the `agent/…` lane) | **never pages on its own** | its output has no `action` field by design; it may raise confidence, not send |

**Night rule (D3, still open):** P0 interrupts at any hour. If he later wants a quieter night rule it belongs here, as
a priority *downgrade* with an expiry — never as a suppression, because a suppressed security page is indistinguishable
from a system that did not notice.

## 3. What a page must contain, and what it must never contain

It carries, in this order:

1. **the one line** — what happened, in the owner's language: *"Shop door opened with no key code, 3:41am Tuesday."*
2. **the declared state** at the moment it happened — `shop closed` / `apartment occupied` / `nobody here`;
3. **the picture** — the `security_evidence` row for that episode (the still exists already; the page links or attaches
   it);
4. **one action** — "reply CANCEL if this was you" — because a page the owner cannot answer is a page that trains him
   to ignore pages.

It never carries: an internal identifier (`WO…`, `ev-…`, a path), the sentence "reply with your answer", an
instruction verb, or any figure the owner did not set. Those are the four refusal classes the owner-pager guards
already enforce (`_plain_item`, `_one_sentence`, `_compose_one` in `scripts/owner_attention.py`), and a security page is
subject to the same rules — plus one of its own: **it must never be classified as machine-facing**
(`_machine_facing_why`, line 426, drops such messages *before any channel decision, including P0*). A mesh or heartbeat
vocabulary in a security page would silence it. So `source` is a constant, e.g. `security-page`, and the body is plain
sentences about a door and a person.

## 4. Dedupe, and why one intrusion is one page

Keyed on **episode**, not on event: `episode_id` already exists on `security_decision`. One page per episode, ever,
unless the episode escalates in level. The estate's own dedupe primitives (`event_queue` priority+dedup,
`trigger_goal_pipeline` dedup) are the pattern; the security record's `security_action` is where the fact is written.

## 5. Cancel, and the half of it that actually matters

A page is cancellable for **10 minutes** (D5). The cancel records **who** cancelled and **when**, and it does not
retro-edit the decision — it appends. A cancel never disarms anything and never deletes evidence; it changes the
escalation, nothing else.

**The honest limit, stated here because D12 taught it:** a cancel is only useful if it reaches a *recipient who can
act*. With one recipient, cancel means "stop escalating to me", and escalation to a second person exists only if D2
names one.

## 6. What is missing before this can run — the actual build order

1. **The declared shop state does not exist.** The level-3 rule is currently unreachable because
   `security-sentinel.py:260` defines "expected empty" as a 600-second presence latch over a basement that contains a
   dwelling (measured, D9385). **Nothing can page at level 3 until the state is declared rather than inferred.**
2. **A page has never been attempted**: `security_action` holds 0 rows and no code inserts into it.
3. **`security_action` needs no schema change** — it already has the columns for a page attempt; what it needs is a
   writer.
4. **The evidence row exists** (`security_evidence`, 3 rows written today) but nothing links a decision to its picture.
   `security_decision.evidence_id` was added on 2026-10-27 for exactly this and is empty.

**Order:** declared state → sentinel keys level 3 on it → `security_action` writer → page composer → dedupe → cancel →
escalation → the harness that proves it sends nothing → one real page the owner has approved.

## 7. The verification that counts

Not "the function returned ok". In order:

1. A **dry-run harness** that composes the page and asserts the routing decision (`P0`, channels `["sms","voice_call"]`)
   **without sending** — it must call `notify_owner` with a stub, or stop one line short of it.
2. A row in `security_action` for the attempt, with `result` and the priority actually chosen.
3. **One real page**, whose exact body the owner has seen and approved in the conversation, sent to him, and confirmed
   by him receiving it. Until that happens this is unverified, and the document says so.
