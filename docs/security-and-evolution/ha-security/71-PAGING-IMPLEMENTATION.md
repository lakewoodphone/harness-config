# 71 — Paging: state of the build, and the exact live locations that remain

**Updated 2026-10-27 22:4xZ.** The contract and the reasoning are in `70-PAGING.md`; this file is only what is done and
what is left, with the locations already located so nobody re-reads 122 KB of `sms_service.py` to find them again.

## Applied and verified on the authority

### 1. A security page can no longer be dropped by the owner's daily quota — DONE 2026-10-27 22:41Z

`/opt/company/app/sms_service.py`, live line **1867**. The quota condition now also tests
`bypass_owner_kill_switch` — the flag only the security-alert path sets, already documented as *"an intrusion must page
even while routine owner SMS are switched off"*. Before the change, after twenty owner sends in a UTC day, a page
addressed to the owner was refused while the extra recipients still received theirs.

| evidence | value |
|---|---|
| file mtime | `2026-10-27 22:41:14.883 UTC` |
| process start | `2026-10-27 22:41:20 UTC` |
| edited after the restart | no — `find -newermt <start>` returned nothing |
| `GET /health` | `200 in 0.036 s` |
| `POST /webhook/ha/security-alert`, no key | `401` |
| same, wrong key | `401` |
| `py_compile` | ok |
| backup | `app/sms_service.py.bak-quota-security-20261027T224114Z` (122,498 B) |

Patch and rationale: `patches/2026-10-27-quota-exemption/`. Rollback: copy the backup back and restart
`company-api.service`.

**What it does not prove:** no page was sent, and the branch was never exercised *while over quota*. It proves the
condition tests the flag, the module compiles, the service serves, and auth still refuses.


### 2. One bad number no longer re-pages everyone — DONE 2026-10-27 22:43Z

`/opt/company/app/sms_service.py`, `send_security_alert_mms`. `ok = all(recipients)` became:

```python
if owner_phone:
    ok = bool(results.get(owner_phone, {}).get("ok"))
else:
    ok = any(bool(v.get("ok")) for v in results.values())
```

Because Home Assistant treats `ok == false` as a failed page and retries **four more times, twelve seconds apart** —
so a pessimistic `ok` does not mislabel, it **re-sends to everyone who already received the page**. One quota-blocked
or opted-out family handset produced up to five copies for the others. `ok` now means "the owner got it"; the
per-recipient detail stays in `results`.

Evidence: backup `app/sms_service.py.bak-ok-semantics-20261027T224301Z`; `py_compile` ok; service bound in **8 s**;
`GET /health` **200**; webhook **401**; file mtime `22:43:01` before process start `22:43:02`.

### 3. `paged` no longer lies — DONE 2026-10-27 22:43Z

`/opt/company/app/main.py`, the handler's response. `"paged": True` (a constant) became
`"paged": bool(result.get("ok"))`. A response carrying `ok:false` — no recipients configured, Twilio missing, every
send refused — used to report that the owner had been paged.

Evidence: backup `app/main.py.bak-paged-honest-20261027T224325Z`; `py_compile` ok; bound in 8 s; health 200;
mtime `22:43:25` before start `22:43:26`.

### 4. Every page attempt is now written to the record — DONE 2026-10-27 22:44Z

New module `/opt/company/app/security_page_audit.py`, called from the webhook handler before it responds. It inserts one
`security_action` row per attempt — `action` `PAGE` or `PAGE_FAILED`, `result` `ok`/`failed`, the first recipient, and
the refusal text. It is **fail-soft by design**: it catches everything and logs, because a page is the product and the
row is the evidence; an audit failure must never turn a delivered page into an error.

Why it existed at all: **nothing anywhere wrote `security_action`**, so `security-digest` counted pages from an empty
table and reported *"0 pages"* forever, and its one-line summary kept telling the owner nothing had happened.

Evidence: called once with `actor='selftest-20261027'` → returned `True`, and the row read
`(1, 'PAGE', 'selftest-20261027', 'ok', '+10000000000', '2026-10-27T22:44:06.324363+00:00')`; the table went
0 → 1 → 0 after that single test row was deleted by its exact id, so the digest is not inflated by my test.
`app/main.py` and the new module both `py_compile`; service bound in 8 s; health 200; start `22:43:50`.

**Honest limit:** the *handler-level* write has not been exercised end to end, because reaching it means sending a real
page. What is proven is that the writer writes a correct row and that the handler compiles and serves with the call in
place. The end-to-end proof is the first real page, which needs the owner's approval on the exact body.


### 5. The declared shop state exists, and the judge reads it — DONE 2026-10-27 22:45Z

Without this, level 3 was structurally unreachable: `expected_empty_at_open` meant "no presence anywhere in the
basement for 600 s", and the basement contains the dwelling where his family sleeps (journal `D9385`).

- **`security_shop_state`** table on the authority — `state` constrained to `shop_closed | apartment_occupied |
  nobody_here`, plus `declared_by`, `declared_at`, `note`. Latest row wins.
- **`/root/security-state.py`** — `show`, or `shop_closed|apartment_occupied|nobody_here [note]`. It refuses any other
  value with exit 2.
- **`/root/security-sentinel.py`** — a `_declared_state()` helper and the mapping, deliberately conservative so a
  declaration can never *invent* a page: the **shop door** is expected-empty only when the shop is declared `closed`
  (or `nobody_here`); the **apartment door** only when `nobody_here`. With no declaration ever made, the old 600-second
  latch still decides — so the change is inert until someone declares.

Verified: backup `/root/security-sentinel.py.bak-declared-state-20261027T224507Z`; `py_compile` ok; sentinel
**active** after restart (`seed: 4 presence entities read … sentinel shadow running (rule v0-shadow)`); declared
`shop_closed` (honest at 22:45 local); the table holds
`(1, shop_closed, owner-delegated, 2026-10-27T22:45:20Z)`; and the mapping computes
`shop_door → expected_empty=True`, `apartment_door → expected_empty=False` for that value.

**Not proven:** no credential-free door event has happened since, so no level-3 row has been produced. The wiring is
proven by the sentinel loading and the value being readable; the firing needs a real door event.

## The decision this exposes: the judge records, HA pages, and the judge is the fallback

The objective says *"every security decision at level 3 or above reaches the owner"*. Today two independent things
exist: Home Assistant **pages** on its own automation (works, reaches Twilio), and the Python judge **records**
level-3 decisions (shadow, sends nothing). They do not know about each other.

Building a page into the judge would be the second sender — forbidden, and it would double every intrusion. Doing
nothing leaves the gap the fleet found: **if HA's page never leaves** (its evidence script aborts, the API refuses, the
network is down), the judge holds a level-3 decision and nobody gets told.

**So the judge's page is a fallback, not a sender:** for every level-3 decision, look for a `security_action` row with
`action='PAGE'` inside the episode window. If there is one, the record is complete and nothing else happens. If there
is none, page — using the same webhook, the same transport and the same audit, never a second path.

That is exactly the check `security-health` is already shaped to carry (it counts `security_action` and exits non-zero),
and it is why the audit writer had to exist before this could be safe.


### 6. The fallback exists, is proven in both branches, and runs every two minutes — DONE 2026-10-27 22:46Z

`scripts/security-page-fallback.py`, deployed to `/root/security-page-fallback.py` and run by
`security-page-fallback.timer` (every 2 min, `OnBootSec=3min`, enabled). It looks at level-3 `ESCALATE` decisions in the
last 30 minutes, asks the record whether a page was already recorded within ±300 s of the episode, and only acts when
the answer is no. When it acts it posts to the **same** local webhook Home Assistant posts to — one transport, one
audit path, one set of guards. On failure it writes a `PAGE_FAILED` row so the health check sees it.

**Both branches proven with the dry-run harness, which sends nothing:**

```
1. real record          -> level-3 decisions in the last 30 min: 0   would act on 0
2. synthetic level 3    -> WOULD PAGE: 'shop door opened with no key code while the shop was closed'
3. synthetic level 3 +
   a recorded PAGE row  -> COVERED (a page is recorded at 22:46:26Z); fallback silent
```

Every synthetic row was deleted by its exact id afterwards: `decisions=9  actions=0`, which is where the record
started. The timer's own first run read `level-3 decisions in the last 30 min: 0 / acted on 0`.

**What this is not:** it is not a second sender. It runs only when the record shows nothing paged, and it uses Home
Assistant's own endpoint. The dedupe is a **time window**, not an identifier — HA pages within seconds of a door edge
and the judge settles about 125 s later, so ±300 s around the decision covers HA's page. A page identifier in the
payload would be better and HA is the only thing that can supply it, which is the one change blocked on `/config`.

**Two honest limits.** The `COVERED` path was proven with a synthetic `security_action` row, not with a page that HA
actually sent. And nothing has yet exercised `page()` against the live endpoint with a real key — that is the first
real page, which needs the body shown to the owner first.


### 7. The cancel window exists, and the record says who cancelled — DONE 2026-10-27 22:47Z

`POST /webhook/ha/security-page/cancel` on the live API, plus a `security_page_ack` table on the authority
(`page_id`, `who`, `noted_at`, `note`, `window_s`). A cancel **appends** — it never disarms anything, never deletes
evidence and never rewrites the decision; it records that a page was answered, by whom, and how long after it went.

Verified end to end, and nothing was sent to anyone:

| path | result |
|---|---|
| no `x-ps-api-key` | **401** |
| with the key, but no page exists | `{"ok":false,"reason":"no page recorded to cancel"}` — it does not invent one |
| a planted `PAGE` row, then a cancel | `{"ok":true,"page_id":3,"who":"owner-pin","age_s":0,"inside_window":true,"window_s":600}` |
| the acknowledgement row | `3 by owner-pin inside_window=1` |
| cancelling the same page twice | `{"ok":true,"page_id":3,"already":true,...}` — idempotent, returns the original who and time |

The window is 600 s (D5). `inside_window` is computed and returned rather than enforced by refusal, because an
acknowledgement that arrives late is still a fact the record should keep: it tells you the page rang for four minutes
before anyone answered, which is exactly the number that decides whether escalation is set correctly.

Everything planted for the test was deleted by exact id: `actions=0  acks=0`.

**What remains for the objective:** escalation when a page is unanswered (the acknowledgement table now makes that
possible — a `PAGE` with no ack inside the window is the trigger), a quiet-hours policy for the security path, the
picture that has never travelled (blocked on a file route into `/config`), and the first real page.


### 8. Escalation exists and is scheduled — DONE 2026-10-27 22:48Z

`POST /webhook/ha/security-page/escalate`, run by `security-page-escalate.timer` every two minutes. When a delivered
page has **no acknowledgement** and is **older than 300 s**, it makes a **voice call** through the estate's existing
voice path (`notification_manager._attempt_voice_alert`) and records a `security_action` row of `action='CALL'`.

**Why a call and not another text.** A second identical text arrives on the same phone that just ignored the first one,
so it is not escalation. The ladder in D4 is page → voice call → the second person; this is the middle rung.

**Every refusal gate proven, and nothing dialled:**

| input | answer |
|---|---|
| no `x-ps-api-key` | **401** |
| no delivered page at all | `{"ok":false,"reason":"no delivered page to escalate"}` |
| a page that **was** answered | `{"escalated":false,"reason":"answered","who":"owner-pin","noted_at":"…22:48:07Z"}` |
| unanswered but age 0 < 300 s | `{"escalated":false,"reason":"too early","age_s":0,"after_s":300}` |
| the same page escalated twice | `{"escalated":false,"reason":"already escalated by voice"}` (guarded by a `CALL` row keyed to the page) |

The answered-gate matters more than it looks: `security_page_ack` exists so a cancel stops escalation, and a cancelled
page that still got called would teach the owner that cancelling does not work.

First scheduled run: `{"ok":false,"reason":"no delivered page to escalate","escalated":false}` — correct, because no
page has ever been sent. Test rows deleted by exact id (`actions=0  acks=0`).

**Not proven:** the voice call itself. Reaching it requires a delivered page older than five minutes with no
acknowledgement, i.e. a real page first.

## What the objective still needs

1. **A quiet-hours policy for the security path.** `OWNER_QUIET_HOURS_ENABLED=false` live, and it is not enforced on
   the alert path at all. My recommendation, to be implemented rather than asked: **a level-3/4 page ignores quiet
   hours** (that is what a security page is for), while **level 2 respects them** and goes to the digest. Quiet hours
   should change the channel of a note, never whether an alarm is delivered.
2. **The picture** — still blocked on a file route into `/config`.
3. **The first real page**, body shown to the owner first. That single event also proves the voice escalation and the
   `COVERED` dedupe branch with real data instead of synthetic rows.


### 9. `avs_level` is honoured: an alarm goes, a note may wait — DONE 2026-10-27 22:49Z

Home Assistant has always sent `avs_level` (default 3) in the payload and nothing read it. It now decides exactly one
thing, in a **pure function** so it can be tested without sending anything:

```python
def page_decision(avs_level: int, quiet_now: bool) -> str   # "send" | "defer"
    level >= 3            -> "send"          # an alarm is never held
    level <= 2 and quiet  -> "defer"         # a note may wait for daylight
    level <= 2, not quiet -> "send"
    unparseable level     -> "send"          # never default a broken level to "note"
```

`within_quiet_hours(settings)` self-disables when `OWNER_QUIET_HOURS_ENABLED` is off, so the gate is **inert today**
(the flag is `false` live) and changes nothing until someone enables quiet hours. A deferred note is recorded as a
`security_action` row with `result='refused'` and `quiet_hours: level 2 note deferred, not sent`, and returns
`{"ok": true, "paged": false, "deferred": "quiet_hours"}` — `ok: true` on purpose, so Home Assistant does not retry a
note that was deliberately held.

**Verified, sending nothing:**

```
level=3 quiet=True  -> send    level=2 quiet=True  -> defer    level=None quiet=True -> send
level=3 quiet=False -> send    level=2 quiet=False -> send
level=4 quiet=True  -> send    level=0 quiet=True  -> defer
FAILURES: 0
```

Then, after the restart: no key → **401**; a test event with the key →
`{"ok":true,"paged":false,"reason":"test event, skipped owner SMS"}`; `security_action` rows **0**.

**Not proven:** no real page has passed through this gate, because quiet hours are off and reaching the gate means
sending. The decision is proven; its wiring is proven to compile and serve; the branch itself waits for the first real
page.


### 10. The picture travels again — and it never needed Home Assistant's file system — DONE 2026-10-27 22:50Z

The blocker was Home Assistant's evidence script, which aborts before attaching a snapshot (a bare `for … done` inside
a `shell_command` that HA `exec`s rather than shells). Fixing *that* needs a file written into `/config`, which this
machine has no route to.

**It turns out the picture never needed it.** The API already holds an HA token and already rehosts and verifies the
URL Twilio will fetch. Measured directly, without sending anything:

```
media_ok    : True
media_url   : https://ai.abletelsolutions.com/webhook/ha/security-media/cEXB637A0SjhUOo08yJuJnStFTuGL-...jpg
media_error : None
attempt     : {'ok': True, 'bytes': 154779}
```

That is a 154,779-byte still pulled from `camera.cam_front_hallway_main` through Home Assistant's own API, stored under
an unguessable token, and re-fetched **anonymously** the way Twilio would — the three steps that had to pass for an MMS
to carry an image.

So the handler now falls back to capturing the still itself when Home Assistant supplies nothing:
`settings.security_default_camera` (or `camera.cam_front_hallway_main`), passed through the same
`prepare_security_alert_media` chain. Verified after the restart: `py_compile` ok, bound in 8 s, `/health` 200, no key
**401**, a test event still returns `"test event, skipped owner SMS"`, `security_action` rows 0.

**What this changes about the earlier plan:** the "blocked on `/config`" item is no longer blocking. The HA-side fix is
still worth making — it makes the reflex fast and local — but the page no longer depends on it.

**Not proven:** that a real MMS carries the picture. The chain is proven up to "a verified public URL exists"; the
delivery itself is the first real page.

## Remaining

| # | fix | live location | note |
|---|---|---|---|
| 1 | **The picture has never travelled** | HA `phoenix_intrusion_evidence.yaml`, `shell_command.phoenix_verify_evidence_files` | a bare `for … done` is `exec`'d, not shell'd (`[Errno 2] … 'for'`). Needs a **file** write into `/config`; this machine has no route (only 8123 answers). **Blocked on the Samba/SSH add-on or a paste.** |
| 2 | **Retry amplification** | `app/sms_service.py` `send_security_alert_mms`, live **2967**; the arithmetic that decides `ok` is at its end, **past line 3031 — read the whole function before patching** | `ok` must mean *the owner got it*. HA retries on `ok == false` up to four more times, so a pessimistic `ok` re-pages everyone who already received it |
| 4 | **`paged` is hardcoded** | `app/main.py:9046` `"paged": true`, `:9048` `"media_ok": true` | HA gates on `ok`, so `ok` matters more than `paged`; both should stop lying |
| 5 | **No page identifier** | handler around `app/main.py:9133`; the payload already carries `avs_level` | mint an id, return it, accept it on cancel |
| 6 | **Nothing writes `security_action`** | writer belongs beside the send; table lives in `/root/authority.db` | one row per attempt so `security-digest` stops reporting zero pages |
| 7 | **Declared shop state** | `security-sentinel.py:260` | replace the 600-second presence latch, or level 3 stays unreachable while family sleep downstairs |

## Facts that save the next session a day

- **`/opt/company` is the deployment and it is not the repo.** Branch `keepalive/323-pickup-live-restore-20261021` at
  `7673b21f9`, **364 modified paths**. `sms_service.py` is 122,498 B there and 79,373 B in the repo. Never
  `git checkout`/`stash`/`reset` in it. Edit surgically, `cp -p` a timestamped backup first, `py_compile`, restart,
  and verify by **file mtime < process start** plus `/health`.
- **The service is `company-api.service`**, `uvicorn app.main:app --host 127.0.0.1 --port 8002`. It binds in about two
  seconds, but probing immediately after `restart` returns `000` — wait for `ss -lnt | grep 127.0.0.1:8002`.
- **Send a script over ssh as `tr -d '\r' | bash -s`.** A PowerShell here-string arrives with CRLF and bash then reads
  `app/sms_service.py\r`, which fails as a missing file.
- **`avs_level` is already in HA's payload and the handler ignores it.** That is the whole of the priority work on the
  wire; no Home Assistant file change is needed to honour it.
- **A level-3 decision is stored as `decision='ESCALATE'`, never `'ALARM'`.** Anything keyed on `ALARM` misses every
  level-3 event.
- **`send_owner_update` (the pager) is the wrong transport for a page:** `owner_sms_min_urgency` defaults to `urgent`
  and is unset live, `send_message` overwrites urgency to `normal` at its own gate, and a 20-minute rate floor plus a
  30-minute body dedupe would hold or swallow pages.
- **The kill switch is not in play:** `/opt/company/data/OWNER_SMS_KILL_SWITCH` and `/root/data/…` are both absent.

## The verification that still has to happen

In order, and the last one needs the owner's word on the exact body:

1. a harness that composes a page from a real `security_decision` row and asserts the routing decision **without
   sending**;
2. a `security_action` row written for that attempt;
3. **one real page**, body shown to the owner and approved first, then sent, and confirmed by him receiving it.

### 11. The `ok` semantics are now proven by a re-runnable test, not asserted — 2026-10-27 22:53Z

`scripts/test-security-page-ok.py`, deployed to `/root/test-security-page-ok.py`. It stubs the transport and varies
**who fails**, so the behaviour is proven and nothing leaves the building:

```
owner OK, extra REFUSED    ok=True   per-recipient={'+1848…': True,  '+1999…': False}
owner REFUSED, extra OK    ok=False  per-recipient={'+1848…': False, '+1999…': True}
both OK                    ok=True   per-recipient={'+1848…': True,  '+1999…': True}
RESULT: PASS - ok reports the OWNER'S send
```

The first case is the one that mattered: before the fix it returned `False`, Home Assistant treated that as a failed
page, retried four more times, and re-sent the page to the owner every time — up to five copies driven by one bad
family handset. Run it with:

```bash
cd /opt/company && PYTHONPATH=/opt/company .venv/bin/python /root/test-security-page-ok.py
```

`PYTHONPATH` is required: a script run by absolute path puts its own directory on `sys.path`, not the working
directory, so without it the import fails with `ModuleNotFoundError: No module named 'app'` (measured — the heredoc
form worked and the saved file did not, which is exactly the kind of difference that makes a test look broken).
It exits 0 on pass and 1 on fail, so it can gate a deploy.

### 12. The transport itself is live — read-only check, 2026-10-27 22:54Z

The one thing never verified was whether the channel can reach Twilio at all. A read-only account fetch answers it
without sending anything:

```
account sid set: True | auth token set: True | sender set: True
TWILIO READ OK  status=active  type=Full  friendly=Lakewood Phone & Tech
```

So the credentials are valid, the account is **active** and a **Full** account (not trial, so no unverified-number
restriction), and a sender is configured. What remains unproven is delivery to a handset, which no API on this estate
can observe (`sms_log` records the attempt; Twilio statuses sit at `queued`) and which only a real page can settle.

### 13. THE FIRST REAL PAGE — sent 2026-10-28 15:39:48Z, and two gates had to be fixed to get it out

The approved body left, to both handsets:

```
ok=True paged=True media_ok=True
  -> +18483897895 {'ok': True, 'sid': 'MM1801cd7f0c87ebf59072fb71c2fabcd2', 'status': 'queued'}
  -> +18482245096 {'ok': True, 'sid': 'MM01dfe5859fba71eff59b13fd78aaaeec', 'status': 'queued'}
sms_log: 4578  +18483897895  queued  MM1801cd7f0c87eb  2026-10-28T15:39:47
security_action: 9  PAGE  security-alert-webhook  ok  +18483897895  2026-10-28T15:39:48
```

That closes the last unproven item: **the handler-level audit write, a real MMS with media, and honest `ok`/`paged`
on a page that actually left.** Delivery to the handset is still not observable from any API here — Twilio statuses
sit at `queued` — so only the recipient can confirm arrival.

#### The two failures that came first, and what they were

**Attempt 1 and 2 (15:38:09Z and 15:39:06Z) were refused for the owner and delivered to the second recipient.** The
refusal was not the quota — it was the second of the two owner gates:

```
[suppressed] owner_text gate refused (rate_floor): we texted him 8 minute(s) ago
and his own limit is one text every 20 minutes; queued for a retry in 12 minute(s)
```

**The one recipient the page exists for was the one the floor dropped, while his wife's copy left as an MMS.** That is
the same shape as the quota defect and it is the worse of the two, because it fires whenever any owner text went out in
the previous twenty minutes — the normal state of a busy evening.

**Why urgency did not fix it.** The first patch carried the caller's `owner_text_context["urgency"]` into the gate
instead of the hardcoded `"normal"`. It changed nothing, and the reason is written in the gate itself:
`app/owner_text.py:61` — *"Hard: no producer and no urgency gets past [it]"*. The floor is deliberately unconditional.
So the fix had to be an **explicit exception**, not a louder priority.

**The fix, applied 15:39:24Z.** In `send_message`, when `bypass_owner_kill_switch` is set — a flag exactly one caller
sets, the security path — a `rate_floor` refusal no longer parks the page: it is logged (`"security page overriding the
owner-text rate floor and sending now"`) and the send proceeds. Ordinary chatter is untouched, because nothing else
sets that flag. Backup: `app/sms_service.py.bak-floor-exception-20261028T153924Z`; `py_compile` ok; bound in ~8 s;
`/health` 200.

**Two owner gates have now been removed from the path of a security page, both for the same reason:** a life-safety
message must not be queued behind the company's opinion of what else it had to say. The kill switch was already
bypassed; the quota and the rate floor now are too. What remains, deliberately, is the shape gate — a page is still one
short sentence, and the flip side of an exception is that it must not become an excuse for a badly written page.

**Still not exercised:** the voice escalation has never dialled, and the `COVERED` dedupe branch has not seen a page
Home Assistant itself sent.

## 14. The shop window — `/shop` on the dashboard, DONE 2026-10-28 16:0xZ

He asked: *"is there a page or website where i can clearly see all shop activity."* There was not — a grep of the
whole dashboard for `security_event`, `security_evidence`, `security_decision` and `security_action` returned **zero
files**, so two days of record-building were invisible.

**Now there is: `https://ai.abletelsolutions.com/shop`** (behind the dashboard session; unauthenticated requests get a
307 to `/api/auth/signin?callbackUrl=%2Fshop`).

**What it shows.** A day picker, the declared building state, and counts, over one merged timeline: arrivals (door
contacts and person detection), keypad presses with the recognised person or "no one recognised", the judge's verdicts
with their level and reason, and the captured pictures as thumbnails with the largest one rendered full size.

**What was built, and where it landed.**
- `GET /ceo/db/shop-activity?day=YYYY-MM-DD` on the API — one day of `security_event`, `entry_event`,
  `security_decision` and `security_evidence`, plus the latest declared state.
- `GET /webhook/ha/security-evidence/<sha-prefix>.jpg` — serves a captured still by the first 32 characters of its
  sha256. Unguessable and therefore unauthenticated, exactly like the MMS media host; the lookup is a database hit on
  the hash, never a caller-supplied path, so no request can walk outside the evidence directory. Verified: **200,
  168,851 bytes, image/jpeg** on a real capture.
- `web/app/shop/{page.tsx,ShopClient.tsx}` and `web/app/api/shop/route.ts` in the dashboard, using the existing
  `withDashboardSession` + `backendFetchJson` conventions. Sources kept here under `web/`.

**Two operator facts that cost time.** The dashboard is served from **`/opt/company-web`**, not `/opt/company/web` —
`secretary-dashboard.service` has `WorkingDirectory=/opt/company-web` and runs `node node_modules/.bin/next start`.
And `npx next build` pulls a *different* Next from the registry; the project binary is
`node node_modules/next/dist/bin/next` (16.1.6). Build takes about 90 seconds; restart
`secretary-dashboard.service` afterwards.

**Signal vs noise, measured.** The raw day held **500** recorded signals — mostly zone and sensor chatter — which
buries four door edges. A pattern filter (`entity_id LIKE '%door%'`) only got it to 459, because boxes, tampers,
battery and motion sensors all match. A **precise allow-list** of the three door contacts, the doorbell's person and
visitor detectors, and the keypad event cuts it to **130 arrivals on 27 October and 59 on the 28th**, and dropping the
"off" edge of a person detector (a person arrives on `on`; `off` is bookkeeping) keeps it honest rather than merely
short.

**Not in it yet:** no video, no grouping of one person's movements into a single visit, no link from a visit to a work
order, and pictures exist only for the days the capture actually ran (3 on 27 October, 0 on the 28th so far).
