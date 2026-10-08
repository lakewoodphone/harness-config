# The owner's text channel, and what "one brain" has to mean (2026-09-30)

Audited and partly fixed on **2026-09-30** by a session on ZABZ-TECH against the live
authority `secratary`. Every number below was measured in that session; the command that
produced it is printed with it. This is the record, not a request to read anything.

The owner's instruction, verbatim:

> i want the AI. Company and the secretary server, NDSH all share one unified brain ...
> And really just one smart you that thinks the same use the same tools across all
> interfaces.
>
> make sure the texting system is working properly, meaning it's registering what I send
> back and acting based on it. Stuff not sending me too much, not sending me too little.

---

## 1. What exists, and which parts already are one brain

```
  HIS iPHONE                 WINDOWS LAPTOP / DESKTOP          AUTHORITY  secratary (Linux)
  ──────────                 ────────────────────────          ──────────────────────────
  safari / home-screen  ──▶  DSH WEB  (phone-engine,           DSH ENGINE  (phone-engine,
    https://secratary.         127.0.0.1:3089, loopback)            3089, systemd)
    tail93e6e6.ts.net            │  preset `zabz`                    │  preset `zabz`
                                 ▼                                   ▼
                             ┌──────────────── SAME PRESET ────────────────┐
                             │  mcp-secretary -> 14 `ps_*` tools           │
                             │  over ssh (Windows) / local child (Linux)   │
                             └────────────────┬────────────────────────────┘
                                              ▼
                              personal-secretary-mvp  (FastAPI :8002)
                              618 routes, ~199 services, 203 tables
                              http://127.0.0.1:8002/v1/chat/completions   <-- ONE GATEWAY
                                              ▲
  HIS TEXTS  ──▶  sms-inbox.py  ──▶  inbox.db ──▶  sms-responder.py
   +18483897895     (sensor, cron */5)              textdecide.py  (its OWN model client)
                                                    textwork.py    (its OWN agent loop)
                                                    textsend.py    (its OWN Twilio send)
```

**Already unified, genuinely:** the phone web interface and this agent are the same engine
and the same `zabz` preset, and both reach the company through the same MCP server and the
same authoritative database. That is the piece the owner asked for that already works.

**Not unified, and this is the whole of the gap:** the text responder is a **fifth system**.
It calls the same gateway (good) but with its own resolver, its own alias preference list
(`textdecide.PREFERRED = secretary-auto, secretary-smart, secretary-fast`), its own nine-tool
agent loop (`textwork.py: TOOLS = web_search, memory_search, owner_state, owner_profile,
contacts, sms_thread, comms, app_db_query, queue_lookup`), its own Twilio send, and its own
anti-repeat store. It never calls the app's own conversation contract.

---

## 2. Measured defects

### 2.1 A named model was answered `200` and never served (FIXED, live)

`POST /v1/chat/completions`, reading both the response `model` field and the `model_usage`
row the gateway wrote:

| requested | actually served | verdict |
|---|---|---|
| `deepseek-v4-flash` | `deepinfra/.../DeepSeek-V4-Flash-0731` | correct, by luck |
| `deepseek-v4-pro` | `deepinfra/.../DeepSeek-V4-Flash-0731` | **wrong, silently** |
| `deepseek-v3.2` | `deepinfra/.../DeepSeek-V4-Flash-0731` | **wrong, silently** |
| `deepseek-r1-0528` | `deepinfra/.../DeepSeek-V4-Flash-0731` | **wrong, silently** |
| `secretary-smart` | `deepseek/deepseek-v4-pro` | correct |

A short id is not in `sr._CAPABILITY_DB`, so `prepare_request`'s direct-pin test fell through
to `sr.route_canonical_request`, which picked the cheapest capable model and said nothing.
The app's own `model_tier1/2/3` and `mem0_llm_model`, and the authority `.env`, all name
exactly those ids — **which is why the app's three tiers have never been three different
models.** And `GET /v1/models` returned 38 ids, none of them a short id the endpoint accepted,
so a caller obeying "validate every configured id against the catalog and drop what is not
listed" would have dropped working configuration.

Fixed in `app/services/ai_gateway.py`: `_LEGACY_SHORT_MODEL_IDS` resolves a short id to its
canonical id before pinning; `build_models_payload` appends those aliases as
`kind: legacy_alias`; an id that is neither canonical nor a route alias is served on the
settings' **own default route** and logged at `WARNING`. Live after restart:

```
GET /v1/models -> 42 ids (was 38), all four short ids listed as legacy_alias
deepseek-v4-pro   -> deepinfra/deepseek-ai/DeepSeek-V4-Pro-0813
deepseek-v4-flash -> deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731
```

Backup: `/home/zabz/ai_gateway.py.bak-precatalog-20260930T1450Z`.

### 2.2 The responder does not honour the one-at-a-time turn ledger

`app/owner_text.py` is the contract, and its docstring quotes the owner's own ruling: *"you
send me one text at a time ... You have to respond back or address what I say."* It has one
enforcement point, `gate()`, reached from three app call sites.

`textsend.send` — the only path the owner actually hears from right now — is not one of them.
It posts straight to Twilio and never touches `owner_text`.

Consequences, both measured:

* **Two questions at once.** A question the responder is waiting on does not block the app,
  and a question the app is waiting on does not block the responder.
* **Volume he did not ask for.** Last 7 days: **117 texts to him against 14 replies from him.**
  (`text-health.py` G1.)

The gate itself works and is honest — `owner_text_decision` ids 605–612 show it refusing about
80 % of app-side autonomous sends with `awaiting_reply`, and it answered `allowed` at
13:36:03 for the Gusto message the owner then replied to at 13:41:20. It simply does not see
half the traffic.

### 2.3 Three ceilings for one concept (FIXED)

`config.py` default **20**, `.env` `OWNER_SMS_DAILY_QUOTA=20`, and
`owner_sms_flood_guard.OWNER_SMS_DAILY_CEILING` hardcoded **8** — while the text the owner
actually received on 2026-09-29 read *"quota reached (3/0 distinct messages sent today)"*.
The flood guard now reads the setting (0 blocks all, −1 lifts the daily ceiling, garbage logs
a warning and uses 20). Backup:
`/home/zabz/owner_sms_flood_guard.py.bak-20260930T1455Z`.

### 2.4 The flood, and the evidence that it is over

Duplicates delivered to `+18483897895`, repeats inside 30 minutes, by day:

```
2026-07-14: 14   2026-09-22: 191   2026-09-25: 53
2026-07-15:  9   2026-09-24:  10   2026-09-27: 23
...
2026-09-28:  1   ← the last one, 23:06Z. Nothing since.
```

Root cause, already fixed before this session: on 2026-09-27 the morning briefing was 1,736
characters, rejected by Twilio's 1,600-character limit, and **retried every 30 seconds from
07:30:16 to 07:41:26** — 25 submissions. A permanent failure became a loop because the day was
marked `sent` only on success. The briefings are now held in the owner queue, never texted,
and the day is marked unconditionally.

**Zero repeats inside a 30-minute window in the last 24 hours.** The honest reading of the
channel is still 117 outbound rows over 7 days for 28 distinct bodies — but that is history,
not a live fault.

### 2.5 Blocked obligations never escalate

Seven `owner_message_queue` rows sit `held`/`queued`, several with hundreds of recorded send
attempts (id 1991: **676**, id 2034: **266**). Each is a real obligation — a car inspection, a
tuition balance. The guard is right to refuse a text. The failure is that an obligation refused
six hundred times never becomes the **one question** that would clear it.

---

## 3. What "one brain" means concretely

Not a rewrite. Four seams, in this order.

**S1 — one gate, one conversation.** The responder's owner-bound send stops being
`textsend.send` and becomes the app's own send path. One gate then binds both, and the turn
ledger sees every outbound message. Definition of done: `text-health.py` check D1 goes green,
and a text to the owner while a turn is open is refused once, from either path.

**S2 — one model resolution.** `textdecide.ModelCatalog` becomes a thin client of the
gateway's catalog rather than a second resolver with its own preference list. The gateway is
already the single source; the second list is what drifts. Definition of done: exactly one
`PREFERRED`/alias list exists in the tree, and `text-health.py` A3 stays green.

**S3 — one tool surface, entered through `textwork`.** `textwork.py`'s nine tools are a
subset of what the app already offers. It keeps its bounded read-only loop — that is good
engineering and cheap — but each tool becomes a call into the app's own action registry
rather than a private implementation. Definition of done: every name in `textwork.TOOLS`
resolves to an app capability, and adding a capability needs no edit in `~/bin`.

**S4 — the phone and the text are the same agent turn.** The phone already is: `phone-engine`
runs the `zabz` preset with the secretary MCP mounted. The text path reaches the same brain by
S1+S2+S3, at which point a text, a wake, and a person typing are three triggers of one turn.
Definition of done: one recorded session exists that began as a text and used a `ps_*` tool.

---

## 4. The instrument, and its own bugs

`~/bin/text-health.py` — read-only, exit 1 on any failure, no arguments.
Twelve invariants over the gateway, the model tiers, the ceiling, the turn ledger, duplicate
sends, queue rot and channel liveness. It is what measured every defect in this document, and
it caught **five bugs in itself** on the way. Each is kept here, because each one looked like
a pass:

* `inbox.db.date_sent` holds **two formats** — RFC 2822 from `textsend` and ISO 8601 from the
  mirror. Comparing them against an ISO string with `>=` sorts them as text: it reported 258
  rows where the truth was 118, and turned 88 repeats inside a window into "49 duplicates
  across weeks".
* A phrase spanning **adjacent Python string literals** was not found, because the source
  keeps the quote characters — so a working fix was reported broken.
* An assertion strict enough to **stay red after the fix**.
* A verification script that fed an already-fitted body back through `inspect_body` at the
  **default** 320 limit, and so reported a correct 900-character pass as a failure.
* A test that set `DATABASE_URL` in the environment to point at a throwaway ledger, and was
  served the production database instead — because it read the merged config, which is the
  app's `.env` and always names production. It wrote a test turn into the live ledger, which
  was then closed as a test artefact.

Current reading: **12 checks, 0 FAIL** — `A3` and `D1` are both green. It read 6 FAIL before
the work in this session.

```
RESULT: 12 check(s), 0 FAIL
```

---

## 5. Round two: what the channel audit was NOT looking at

The audit in section 1 found the channel. Widening it to the systems the channel depends on
found four more faults, and the largest of them was the reason a five-day-old insurance
obligation had never reached him.

### 5.1 The escalation path was mechanically dead (FIXED)

The owner's car has had no fire, theft or collision cover since **19 May 2026**, because
Plymouth Rock never received proof of a Carco inspection. The system knew. Row 2034 of
`owner_message_queue` held it with **277 recorded send attempts**, every one refused with
"urgency 'normal' is below the send threshold 'urgent'".

There is an escalation for exactly this case, and it could never fire. Four independent
reasons, each measured, each sufficient alone:

1. **The age clock reset itself.** The age was read from `last_seen_at`, which
   `enqueue_owner_message` moved to `now` on every repeat. A reminder that fires every four
   hours was therefore permanently zero hours old.
2. **One obligation became five rows.** Dedup keyed on `(reason, body)`, and the dispatcher
   stamps a fresh reason per fire (`reminder:504`, `reminder:521` … `reminder:524`). Even a
   fixed clock would have had five rows to age, each brand new.
3. **The escalated body was too long to send.** Row 2060 escalated to `urgent` and was then
   refused by `app/owner_text.py`: "too_long: is 455 chars, over the 320-char limit",
   3 attempts. Nothing shortened it.
4. **The subject did not survive the 320.** Trimming cut row 2060 at "proof of a Carco
   inspection" — discarding the policy number, the suspension and the place to book. Its
   first sentence alone runs 238 characters.

Fixed in `app/database.py` (`owner_obligation_key`, body-keyed dedup, an age clock repeats
no longer move), `app/autopilot.py` (age from `created_at`; structural escalation) and
`app/owner_text.py` (`fit_for_one_text`, and a gate that accepts a caller ceiling). An
escalated obligation gets textsend's own 900-character SOFT_LIMIT; everything else keeps the
320 default. The live queue was consolidated 5 rows → 1 with a full SQL backup first.

### 5.2 The backup volume was two hours from a full disk (FIXED)

`/` was at **99%, 7.6 GB free**, with `/home/zabz/secretary-backups` holding 21 directories
and **298 GB**, and an 18 GB backup due at 18:00.

`scripts/server/prune-backups.sh` did not exist. `backup-data.sh` looks for that exact path
and, when it is missing, prints `WARN: prune-backups.sh missing; skipping pre-backup
retention` and carries on. The file was untracked, so `git status` never showed it missing.
The mechanism is in that script's own comment, from 2026-09-10:

> Incident: retention used to live at the END of this script. With the disk full, the backup
> step failed, the script exited non-zero, retention ran -> disk stayed 100% full -> SQLite
> SIGBUS core-dumps every …

Restored from its documented policy (all < 1 day, one per day for 1–7 days, one per week for
7–30 days, nothing older than 30). Removing 6 backups freed **82 GB**: 99% → 80%, 15
backups kept with a full month of history. Committed, so a deploy cannot delete it again.

### 5.3 The API unit's restart cap trips silently (FIXED)

`secretary-api.service` caps itself at 3 starts per 15 minutes — deliberately, installed
2026-09-28 after 27.9 minutes of downtime in one day, so a service that cannot become healthy
is not restarted forever. The reasoning is sound; the failure mode is not. When the burst is
exhausted the unit goes to `failed` and **nothing notices**. A session deploying several
fixes in one afternoon hit it, and the company was down until a human ran
`systemctl reset-failed`.

`api-watchdog.sh` + a 5-minute timer now recover a failed unit at most once an hour, append
every incident to `/home/zabz/.api-watchdog-incidents.log`, and tell the owner through the
app's own queue. It acts only on a unit systemd itself gave up on — `inactive` is a unit
stopped on purpose. The cap is untouched.

### 5.4 The responder now obeys the same conversation ledger (FIXED - was 2.2)

`textsend.py` gained `open_owner_turn()` and `record_owner_turn()`, reading and writing the
**same** `owner_text_turn` table the app's `gate()` uses. One unanswered text now holds the
channel from either side. `direct_request=True` is the single way past it and is set in
exactly one place: the owner-queue question. `textdecide.py` gained `--refresh-catalog`
(cron, every 5 minutes) so the model list cannot go stale again.

---

## 6. Decisions taken in this session

* The gateway **resolves** a short id and the **catalog lists** it. A catalogue that disagrees
  with the endpoint is the defect, not the caller.
* An id nobody recognises is served on the **settings' own default route, loudly** — never on
  whichever model the router preferred. The status stays 200 for compatibility; the honest
  record is the log and `model_usage`.
* The autonomous owner-SMS ceiling is **the setting**, read from the environment. One number,
  one place.
* An **escalated obligation gets a longer text than an unasked-for one.** 320 characters is
  right for a message he did not ask for; an obligation he did ask to be reminded about gets
  up to textsend's 900-character SOFT_LIMIT, because its first sentence can be 238 characters.
* A reminder that **cannot fit** in one text at all is escalated **immediately**, not after
  24 hours: it is undeliverable, and waiting does not change that.
* A **repeat does not move a row's age.** `repeat_count` counts repeats; age means age.
* A repeat check is scoped to the **last 24 hours**. A check that stays red for a week after
  a fix is a check nobody reads.
* A service's **restart cap is a safety control and is not to be weakened by a session that
  wants to restart it.** The right response to a silent trip is a watchdog, not a larger cap.
* **Never edit `/etc/systemd/system/<unit>.service` when a drop-in owns the key.** `30-contention.conf`
  already set `StartLimitBurst`, and editing the base file only looked effective.
* Mesh subagent briefs: **put the brief in a file**, and make the prompt one argument-safe
  sentence — an apostrophe or quote reaches the remote one-shot as a shell argument and kills
  the child before it does any work. Two dispatches, four children, two hours, zero findings.

## 7. Open, and next

| # | What | Where |
|---|---|---|
| 1 | S3 — one tool surface: `textwork.py`'s nine tools become calls into the app's registry | `~/bin/textwork.py` |
| 2 | `owner_sms_min_urgency = "urgent"` and the machine-facing `comms_freshness` notice | `app/config.py` |
| 3 | `~/bin` is still not a git repo; 60 `.bak-*` siblings of six live scripts | `/home/zabz/bin` |
| 4 | Unknown but nearby: the memory ceiling the contention drop-in describes | `30-contention.conf` |


