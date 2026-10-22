# Owner-text channel: audit and unified relay — 2026-10-14

**Status:** audit complete, relay built and installed. The inbound brain and the outbound door are live.
One owner question remains (two read-only hosts).
**Author:** Zabz, from a 5-agent read-only audit fleet + a 4-agent build fleet + 2 integration agents,
every load-bearing claim reproduced by the manager.

---

## 1. Why this was commissioned

The owner, 2026-10-14:

> "It's supposed to be a robust system where it takes me questions, and I respond, and sometimes I ask
> it to research something… But it has to be like a unified brain… the CFO asks me something and I text
> back, and then a different part of the reminder system texts me back. There has to be one agent, the
> frontline, that sends and gets the text and orchestrates that they all make sense with each other.
> I think the system's getting worse, not better. And it's sometimes very annoying."

Every part of that complaint is confirmed by measurement below.

---

## 2. The measured problem

### 2.1 It is getting worse. Four doors, not one.

| # | Door | Where it runs | Gate it obeys | Owner-bound sends / 30 d |
|---|---|---|---|---|
| 1 | `/root/bin/textsend.py` | authority | its own owner-turn ledger + 20-min floor | **43 of 502** |
| 2 | app `sms_service.send_message` + `owner_message_queue` flush (`autopilot.py`) | authority | `app/owner_text.py` only | **~400** |
| 3 | `company-heartbeat.sh` → raw Twilio `curl` (line 323-328) | `waze-mdm-01`, `lpt-apps-01` | **none** — no gate, no ledger, no DB row | **51** |
| 4 | `send-from-ai-line.py` → raw Twilio POST | any | **none** | **12** |

`owner_body_seen_recently` in `textsend.py` is **dead code with zero callers**. `flood_breaker` has
**0 rows**. The 320-character ceiling is enforced 1 273× while **365 messages over 320 characters were
delivered**.

Volume trend, delivered to him: ~4-10 texts/week in early September → 18-116/week now
(`outbound to owner: last 4 weeks 498 vs prior 4 weeks 14`). Outbound-to-owner is up ~7×-36×
(the exact factor is not verified — the prior window spans a store gap).

### 2.2 The incidents, with evidence

- **18-books duplicate** — two *byte-identical* 243-char bodies 74 s apart (2026-10-08T23:14:03Z and
  23:15:17Z). Not sent by any gate: door 4 wrote them, `decided_by='zabz'`, `reason='manual send'`.
- **193-message failed burst** — 2026-09-22, all `status='failed'`, median interval 31.0 s, **186 copies
  of one body**, from a retry loop with **no stop condition** (`app/autopilot.py`). Slowed on 2026-10-10
  (60 s→6 h backoff), capped on 2026-10-13 (`_OWNER_MESSAGE_MAX_SEND_ATTEMPTS=12`). `max(send_attempts)`
  in the live queue is still **2104**.
- **17 copies of "COMPANY IS BACK"** for one state transition in one day; 2026-10-06 was **37 of 40 of
  his texts = 92.5 % alarms**. Cause: three cron lines firing into one unlocked `STATE_DIR`, the mark
  written *after* the POST, and two hosts with independent state.
- **His own instruction was filed as `ignored`.** 2026-09-25T15:26:40Z, `state='ignored'`:
  *"The text you are sending me have way too much information at once. I don't read them. You only
  should text me when you have like a question one at a time for me to answer and I'll answer it."*
  After it: **231 more outbound, 63 of them over 320 characters.**
- **He asked for briefings to stop on 2026-05-05** (*"I thought we're stopping with the morning and
  evening briefings by text"*). They continued: 288 briefing-shaped attempts in 30 days.
- **Internal strings said to a human:** `[Budget exceeded for : ceoreserveexhausted]` ×2,
  `turn-ledger probe; if you see this, the gate failed` ×1,
  `[cut short - ask me to continue]` ×8 (the marker sat *inside* the truncation budget, so it ate the
  end of the sentence), `Want me to open it and draft a reply?` ×6, `Captured as a task.` ×3.
- **His messages go unanswered:** 30 days, 79 inbound, **only 18 answered (22.8 %)**; longest gap from
  his text to any reply **248 hours**.

### 2.3 The correlation was broken in two independent ways

This is the "unified brain" complaint, and fixing only one of them does nothing.

1. **The ask was invisible.** `~/.cfo-asks/asks.db` has **no row older than 2026-10-13**. The Audible
   question was put to him on 2026-10-11 and simply does not exist in the store the responder reads:
   `_asks_for → 0`.
2. **The reply was unreadable even when the ask is present.** `textdecide.py:1376` required
   `strength>=2 or marker or named`, and `REQUEST_RE` had **no `look into` and no form of `cancel`**.
   So his only unambiguous instruction — *"I think it's some leftover subscription… we should really
   cancel look into it"* — classified as **NOISE** and was dropped. Reproduced with the ask supplied and
   in-window: still NOISE.

The consequence in the transcript: he replied, the responder said *"I need to know which charge you're
looking at - I don't have the amount or merchant in front of me"*, and then the same CFO question was
put to him again — *"You literally just sent that text to me. Your unified brain is not working."*

---

## 3. What was built

**One module, one store, every door submits, one thing decides.** The relay is *policy only*; it never
transmits. `textsend.py` remains the transport.

```
door 1 textsend.py ─┐
door 2 app senders ─┤  relay.submit(intent) -> SEND|DEDUPE|FLOOR|COALESCE|SUPPRESS   relay.record_sent()
door 3 heartbeat ───┼──► every submission written down, whatever the verdict ──► textsend.py ──► Twilio
door 4 ai-line   ───┘                         ▼
                                    one ask ledger ──► sms-responder reads it, routes his reply back
```

- **`/root/bin/owner_text_relay.py`** (new) + **`/root/bin/owner-text`** (CLI). Store
  `/root/.owner-text/relay.db` (WAL). Policy: kill switch → class suppress → duplicate → retry cap →
  20-min floor → coalesce → send. The hash is `sha256(normalised body)` with **no timestamp**, which is
  how identical re-reports used to bypass the old dedupe. `BEGIN IMMEDIATE` around read-decide-write:
  12 threads and 6 processes submitting the same body returned **exactly one SEND**, with every
  submission recorded. 47 unit tests, all pass.
- **`textsend.py`** consults it at one call site (line 2495, below its own gate); refuses with a
  structured `error: DEDUPE|FLOOR|…` and exit 1, never a traceback; `record_sent` after a real POST.
  Dry runs never reach it. Fail-soft: if the relay is missing it sends anyway and logs one line.
- **`send-from-ai-line.py`** (the ungated door behind the 18-books duplicate) now submits and is refused.
- **The app door** (`app/sms_service.py:1762`) submits at its single transmit point. A relay-suppressed
  queue row is marked terminal (`suppressed_by_relay:` in `status_note`, `status='dismissed'`) instead of
  retrying toward the 12-attempt cap.
- **Reply routing** (`textdecide.py`, `textctx.py`, `sms-responder.py`): the vocabulary now has
  `look into`/`cancel`/`stop`/…; `textctx.recent_asks` merges the relay's ask ledger with `asks.db`; and
  the answer rule is now **explicit ref → content match → inferred most-recent** (the old
  "exactly one ask open" gate was removed because live data yields **0 or 2+, never 1** — it would never
  have fired). An inferred match is **told to him**: *"Filed against X - correct me if that is not the
  one."* A complaint is never swallowed as an answer.
- **`safe_send(..., class_hint="reply")`** on the reply path, so an answer to his own question is
  exempt from the 20-minute floor.
- **Briefings to the owner default OFF** (`autopilot.py:_owner_briefings_enabled`, fail-closed, three
  call sites), honouring his 2026-05-05 instruction.
- **`SMS_TRUNCATION_MARKER` no longer eats the sentence** — content is truncated to a complete clause
  first, then the marker (if any).

---

## 4. Verification — what was actually run

| Claim | Evidence |
|---|---|
| The relay is correct | `python3 test_relay.py` → `Ran 47 tests` / `OK` |
| Concurrency: no double-send | 12 threads + 6 processes, same body → exactly one `SEND` |
| The 193-storm is stopped | 193 × the real briefing body → `SEND SEND SEND SUPPRESS×190`, 193 rows recorded |
| The 18-books duplicate is stopped | the two real bodies hash equal; 2nd → `DEDUPE` |
| A security page is never lost | `security_alert_mms` exempt from dedupe, retry cap still applies |
| A reply is never floored | `normal→SEND`, `class_hint=reply→SEND`, `plain normal→FLOOR` |
| His incident sentence now resolves | 9/9 mandated rows; ANSWER count on the live corpus 1 → 2 — including his real two-letter **"Yes"**, previously `state='ignored'` |
| The app can reach the relay | under `/opt/company/.venv`: resolver → `/root/bin/owner_text_relay.py`, `submit→SEND`, repeat→`DEDUPE` |
| The reply wire is in place | `safe_send` accepts `class_hint`; exactly **1** call site passes `"reply"` (line 1533) |
| The app is healthy after restart | `company-api active pid=82771`, `/health` 200, `/docs` 200, `"ok":true`, database ok |
| The text cron is healthy | `responder.log` tracebacks **0**; `modules=store=ok ctx=ok decide=ok work=ok send=ok` |

**Service state changed:** `company-api.service` restarted on `secratary-cloud` at **2026-10-14T01:43:59Z**
(guard: `ALLOW: secratary-cloud is WRITABLE`, exit 0). Recorded here as required.

**Revert, one command per file** (backups, with the old sha):
`/root/text-fleet-20261014/r2-door/textsend.py.orig` (6f1b4fdc),
`int-manager/sms-responder.py.pre-reply-wire` (f894d070),
`r3-app/{sms_service,owner_text,autopilot}.py.orig` (0c517c99, e9396c5c, 2d825d75).

---

## 5. What is NOT verified, and what is still open

- **The relay has not yet carried live traffic.** `/root/.owner-text/relay.db` holds **0 attempt rows**:
  no owner-bound text has passed a door's gate since install. Unit-tested and seam-tested, **not**
  field-proven. This is the honest state.
- **No real Twilio leg was made anywhere.** Every `SEND` in this work is a verdict, not a delivery.
  Nothing was sent to any human.
- **Door 3 (`company-heartbeat.sh`) is not mediated.** It lives on two **read-only** hosts
  (`waze-mdm-01`, `lpt-apps-01`; `settings/machines/host-posture.tsv`) and posts to Twilio directly, so a
  relay on the authority cannot see it. Its live bugs remain on the wire: the literal `ZZ` in
  `...01ZZ (down 4 minutes)` (line 762), the unlocked three-cron duplicate race, and the `peer` class
  exempt from the single-sender rule. **This is the owner question.**
- **`owner-ask.py` carries a live 90-min / 2-per-day cap while being unscheduled** — one future crontab
  line adds a second asker to the same phone.
- **The relay's dedupe key is the body.** Two legitimately different events with the same words inside
  6 h collapse to one text; `dedupe_extra` exists for callers that have a real event identity, and
  security pages are exempt, but any other sender with a repeated caption should pass one.
- `textctx.relay_asks` drops a relay ask stamped with microseconds when his text is stamped to the
  second (hit once; behaviour unchanged).
- The other 38 modified files in the live checkout were already loaded before this work (service start
  01:14:20 > their mtimes); the restart at 01:43:59 did not put them into production — they already were.

---

## 6. Next

1. Owner: may the two read-only alert hosts be touched (the ZZ bug, the duplicate race)?
2. Watch `/root/.owner-text/relay.db` for the first real verdicts and confirm the policy behaves on
   live traffic; `owner-text status` is the view.
3. Mediate door 3 — route `company-heartbeat.sh` through the relay instead of Twilio directly.
4. Give every sender an event identity (`dedupe_extra`) rather than relying on the body hash.

---

# ADDENDUM — 2026-10-14, second pass (the owner said "fully take care of it")

## What changed after the first report

| # | Change | Verified by |
|---|---|---|
| 1 | **Door 3 fixed on both read-only alert hosts.** `company-heartbeat.sh` on `waze-mdm-01` and `lpt-apps-01`: a `flock` so four cron lines firing into one `STATE_DIR` cannot double-send, and `${down_since}Z` → `${down_since}` (the doubled Z). | live `flock` count 0→1, `down_since}Z` 1→0, `bash -n` OK, sandboxed run exit 0 / no stderr; `e37fa87c…` → `0b6702c3…` on both |
| 2 | **The relay's `COALESCE` rule withdrawn.** It returned a verdict saying a text was "batched into the next 90-min digest window" when **no coalescer exists**. | `class_hint` of `reminder`/`digest`/`info` now all return `SEND` |
| 3 | **One owner ceiling, enforced where it can be.** `MAX_CHARS = 320` in the relay; the **app door** fits through `relay.fit()` before submitting. | relay `doctor` `max-chars` ok; app door wired at `sms_service.py:1764-1777` through `owner_text_relay_module()` |
| 4 | **A message-loss hole closed.** `textsend` was handing the relay the raw body while posting the fitted one, so any owner text of 321–930 chars would have been **refused = silently dropped** by the new ceiling. | judged/ posted/ recorded now agree (below) |
| 5 | **`company-api` restarted** at `01:43:59Z` and again at `02:38:57Z` (guard `ALLOW`, authority writable) to load the app-door plumbing. | `/health` 200, `"ok":true`, database ok, pid 133498 |

## Two corrections to my own first report

**(a) My recommendation for door 3 was architecturally wrong.** I proposed routing
`company-heartbeat.sh` through the relay. That would break the alarm: the heartbeat's job is to alert
when the company API is *down*, so sending its alerts via the company's own API would silence it
precisely when it is needed. Its direct-to-Twilio independence is a feature. I fixed only the lock and
the timestamp instead.

**(b) The "17 duplicate COMPANY IS BACK" texts are historical, not live.** The deployed 2026-10-09
revision already demotes every class except `down` and `guard-exposure` (gate C4), and its own line 789
reads "recovery is never an SMS". What was actually still live on those hosts was the doubled Z and the
unlocked race — and those are now fixed.

## The finding that changed a decision

The relay's first real submission was a **766-character** wall of text delivered at `01:54:51Z`
(`door=app`, `subsystem=ask_owner`, `sid=SM04f9f349…`). Chasing that exposed a worse bug: `textsend`
handed the relay the **raw** body while posting the **fitted** one, so the relay **judged one text and
the phone received another** — and after two attempted repairs, the relay still *recorded* 636 chars
while 270 were sent, because `textsend._relay_module()` and a second loader each held their own
`owner_text_relay` instance (there are two `.pyc` names for that one file).

**I chose a true record over a shorter text.** A relay whose record of what the owner was told can be
wrong poisons the dedupe, the retry cap, the ask ledger and the "what did we decide not to tell him"
view — and `wrong-data` is this estate's measured number-one failure. So `textsend` now submits exactly
the bytes it posts, and over-ceiling is **recorded** (`verdict_reason='too-long'`) rather than refused.
Final measured state: `submit` received 636, the wire carried 636, the row says 636 with `too-long`.

## Still open, stated plainly

1. **`textsend`'s owner texts are not capped at 320.** Unifying `fit_owner_body` (320) with
   `fit_to_segments` (930) is a separate tested change; the app door (the loud one, ~400 of 502 sends)
   *is* capped. Deliberate, recorded, not hidden.
2. **The same `ask_owner` question reached him three times** — `01:54:51Z` (delivered), `02:35:15Z`,
   `02:38:42Z`. The relay recorded only the first, because the app was still on pre-restart code for the
   other two; the restart was fifteen seconds after the third. After the restart nothing new reached him
   in a 90-second watch and **no `suppressed_by_relay` row exists yet**, so the suppression is in place
   and unit-tested but **not observed on live traffic**.
3. **Door 3 is still outside the relay** by design (see correction (a)); what it can text is already
   limited to two classes.
4. `owner-ask.py` carries a live 90-min / 2-per-day cap while being **unscheduled** — one crontab line
   adds a second asker to the same phone.

## Service state changed, recorded

- `company-api.service` restarted on `secratary-cloud` at **2026-10-14T01:43:59Z** and
  **2026-10-14T02:38:57Z**.
- `company-heartbeat.sh` **edited on two hosts whose posture is `read-only`**, on the owner's
  instruction of 2026-10-14 ("do what needs to be done and fully take care of it"). Backups on each
  host; revert is one `cp -p`. File mode tightened 755 → 700.

