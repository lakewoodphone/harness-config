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

### 2.2 The responder does not honour the one-at-a-time turn ledger (OPEN)

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

### 2.5 Blocked obligations never escalate (OPEN)

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

## 4. The instrument

`~/bin/text-health.py` — read-only, exit 1 on any failure, no arguments.
Twelve invariants over the gateway, the model tiers, the ceiling, the turn ledger, duplicate
sends, queue rot and channel liveness. It is what measured every defect above, and it caught
three bugs in itself on the way (two timestamp formats in `inbox.db`; adjacent string literals
breaking a phrase match; an assertion strict enough to stay red after the fix).

Current reading:

```
RESULT: 12 check(s), 2 FAIL
  A3  the responder's model cache is 4 ids stale until its next cron tick
  D1  the text responder does not obey the owner turn ledger   <- S1
```

It read 6 FAIL before the work in this session.

---

## 5. Decisions taken in this session

* The gateway **resolves** a short id, and the **catalog lists** it. A catalogue that disagrees
  with the endpoint is the defect, not the caller.
* An id nobody recognises is served on the **settings' own default route, loudly** — never on
  whichever model the router preferred. The status stays 200 for compatibility; the honest
  record is the log and `model_usage`.
* The autonomous owner-SMS ceiling is **the setting**, read from the environment. One number,
  one place. This ceiling governs the app's autonomous path only; a direct request is excused
  by the caller, and the conversation gate is what enforces one-at-a-time.
* A repeat check must be **scoped to the last 24 hours**. A check that stays red for a week
  after a fix is a check nobody reads.
* Mesh child failures: a brief with apostrophes or quotes is fed to the remote one-shot as
  shell arguments and dies before doing any work. **Put the brief in a file and make the prompt
  one argument-safe sentence** — proven twice, after two hours lost to it.

## 6. Open, and next

| # | What | Where |
|---|---|---|
| 1 | S1 — one gate, one conversation | `~/bin/sms-responder.py`, `~/bin/textsend.py`, `app/sms_service.py` |
| 2 | S2 — one model resolution | `~/bin/textdecide.py` |
| 3 | `owner_sms_min_urgency = "urgent"` vs obligations queued at `normal` | `app/config.py` |
| 4 | Escalate an obligation refused N times into one question | `app/services/owner_sms_flood_guard.py` |
| 5 | S3 — one tool surface | `~/bin/textwork.py` |
