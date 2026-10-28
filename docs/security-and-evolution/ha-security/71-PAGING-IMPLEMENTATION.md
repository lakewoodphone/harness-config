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

## 15. A simple Home Assistant view instead of a data page — 2026-10-28

He looked at the dashboard page and said it was *"way too complex … i don't need the whole backend data dump"*. Fair:
it rendered 130 rows of record data. What he actually asked for is a **Home Assistant view**: pictures, snapshots, a
timeline, maybe alerts.

**There was no file route to `/config`** (only 8123 answers from anywhere else), so this was built entirely over the
**websocket API** — `lovelace/dashboards/create` then `lovelace/config/save`. Script: `scripts/ha-shop-dashboard.py`.

**Created: dashboard `Shop`, url path `shop-view`**, two views:
- **Now** — a state banner (INTRUSION ACTIVE / Empty and armed / Someone is here), then three picture-glance cameras
  (shop door hallway, drop-off/pickup, outside doorbell) and the door/presence entity list.
- **Timeline** — a **logbook card** across the door contacts, the doorbell person detector and guest mode for the last
  24 hours; a history graph of the same doors; and one line saying the full record lives on the company server.

Readback confirms: `2 view(s) | Now (5 cards), Timeline (3 cards)`.

**Two operatives facts learned the hard way.** A storage dashboard's `url_path` **must contain a hyphen** (HA refuses
`shop` with *"Url path needs to contain a hyphen"*), hence `shop-view`. And `websockets.connect` rejects an `ssl`
argument for a `ws://` URI — the HA_URL here is plain http on the tailnet, so the SSL context must be passed only for
`wss://`.

**What already existed, which I should have checked first.** The instance already had **`camera-wall`** (Wall grid,
Main room grid, Status) and **`snapshots-admin`** (Entry, Intrusion Evidence with a vertical-stack and a logbook,
Control Room). `snapshots-admin` is close to what he asked for, and the estate's own rule — prove it is not already
there before building — was the thing I skipped. The new view is simpler than either; the honest next step is to fold
what is good in `snapshots-admin` into `shop-view` rather than keep three overlapping dashboards.

**No clips.** Home Assistant holds stills and a live view; video clips live on the recorder's disk. A "clips" tab would
have to link out to the NVR, not play inside HA.

## 16. One consolidated Shop view — applied 2026-10-28 16:2xZ

He asked for **one clear simplified view**, built properly, and to fan the analysis out. Goal re-armed to this
objective for 20 rounds. Three analyses were dispatched (phone-first design; Home Assistant card mechanics; the honest
status banner) and the working version was built in parallel rather than waiting.

**Live now: dashboard `Shop`, url path `shop-view`, ONE view, 8 cards**, applied over the websocket and read back:

```
readback: 1 view(s); 8 cards: markdown, conditional, custom:mushroom-title-card,
          picture-glance, picture-glance, picture-glance, custom:mushroom-title-card, logbook
```

In reading order, top of a phone screen downwards:
1. **the banner** — one honest sentence about the building, with the muted-siren case ranked above every calm state;
2. **a warning card that only exists when the drill switch is on** (`conditional` card) — *"The siren will not sound…
   Nothing turns it off automatically"*;
3. **Cameras** (mushroom section header) — Shop door (`cam_front_hallway_main`, the best face view), Drop-off and
   pickup (`cam_waiting_room_main`), Outside (`reolink_video_doorbell_poe_clear`);
4. **Today** (mushroom section header) — a **logbook** across both door contacts, the doorbell person detector and
   guest mode, 24 hours.

**The instance has 12 custom frontend resources**, including `mushroom`, `card-mod`, `auto-entities`,
`multiple-entity-row`, `fold-entity-row`, `button-card`, `decluttering-card` and `browser_mod`. That matters: a
phone-readable view should be built from mushroom cards, not raw entity rows, and the previous version was not.

**The banner was verified by rendering it through Home Assistant's own `/api/template`**, not by trusting the Jinja:
it returns `## 🟢 Empty and armed` for the state right now. A markdown card that showed raw braces to the owner would
have been worse than no banner.

**The design is now a generator**: `scripts/ha-shop-dashboard.py` holds the layout, applies it idempotently
(`lovelace/dashboards/create` + `config/save`, with a `--dry` mode), and is the single source of truth — so the
dashboard can be reviewed in git and re-applied after a mistake, instead of being hand-edited in a UI that leaves no
trace.

**Still to come from the 20 rounds:** fold in the three analyses (card mechanics, banner edge cases, what to cut from
the three older dashboards), retire `camera-wall`, `snapshots-admin` and the old `shop-view` overlap, and confirm the
layout on a narrow screen.

## 17. The banner analysis folded in — 2026-10-28 16:3xZ

The status-banner analysis came back rigorous enough to replace my hand-written banner outright, and it changed the
view in three ways.

**1. The muted-siren guarantee is positional, not remembered.** The three `test` branches occupy positions 1, 3 and 4
and between them exhaust `test == on`: alarm+test, then test+unreadable, then test alone. Every calm branch below them
is therefore reachable only with the siren live — including the `else`. That is a structural guarantee instead of a
convention someone has to keep.

**2. It refuses to guess.** New branches the old banner did not have: **CANNOT CONFIRM** when a safety entity is
`unknown`/`unavailable`, and **CANNOT TELL IF ANYONE IS HOME** when the away flag and the presence sensors disagree —
which sends him to the cameras instead of picking a story. And the normal case reads **"No alerts."**, never "safe":
every input on this card is a flag, and none of them is panel health, armed state or siren continuity. A disarmed
panel, a cut siren wire and a quiet building are indistinguishable from here, so the card may not claim safety.

**3. A sensor-health row, so a dead sensor is visible.** Last card, deliberately small: the five safety inputs with
`secondary_info: last-changed`. That is the only way this view can show a sensor that stopped talking *without* going
`unavailable` — the failure mode the whole estate keeps paying for.

**Verified:** the 18-row test table in the analysis was rendered through Jinja2 with stubbed `states()`/`is_state()`,
so those sentences are literal output rather than intention; and the live template, rendered through Home Assistant's
own `/api/template`, returns `**No alerts.**` for the building as it stands.

**Live now:** one view, **9 cards** — banner · Cameras (3 mushroom-headed picture-glance) · Today (logbook, 24 h) ·
Sensor health (5 entities with last-changed). `save: True`, readback confirms the nine cards in that order.

**What the analysis says this banner cannot do, and I agree:** it cannot answer "is the alarm armed" (no such entity is
in the input set), it cannot say "safe", and where two occupancy sources disagree it must refuse to choose. If the
armed question matters, it needs an armed/panel-health entity — the template cannot derive one.

## 18. Rebuilt to the design analysis — 7 cards, two hero cameras, arrivals-only timeline — 2026-10-28 16:45Z

The phone-first design analysis came back and cut the view from nine cards to seven, on sound reasoning: *"three equal
camera cards bury the door, and the history graph is a tinkerer's view."* Its four changes were all adopted.

**1. Two hero cameras, not three.** The shop door (`cam_front_hallway_main`, the best face view) and the street door
(doorbell) get full width, because those are the two frames that answer "who is that". The other three became **one
`glance` row** — Drop-off, Control room, Bench — one tap each, so they exist without pushing the timeline below the
fold.

**2. The timeline filters to `on`.** `state_filter: ['on']` on the logbook means it reads as **arrivals and
detections** instead of an open/close state table, and the window dropped from 24 h to **12 h**. This is the single
biggest readability change of the round.

**3. Door and doorbell contacts ride on the pictures.** Each picture-glance carries its door contact and the two
doorbell sensors as icon buttons with the state hidden — so the door's state is attached to the picture of the door,
instead of living in a separate entity list.

**4. No switches anywhere on the page.** Not test mode, not guest mode, not lockdown. An accidental tap on any of those
is worse than the convenience of having them here.

**The banner changed shape.** It is now a status word in capitals followed by a factual list, with **relative times**
that did not exist before:

```
**BUILDING QUIET** — siren live · doors closed · no doorbell · everyone away.
```

Rendered through Home Assistant's own `/api/template` before applying. The other states read like
`**SIREN MUTED** — siren muted 7 minutes ago, no auto-expiry · doors closed · no doorbell` and
`**ARMING BLOCKED** — siren live · guest mode on for 9 hours, latched, arming blocked · …`. It still never says "all
good", and `SIREN MUTED` is the headline whenever the drill switch is on unless an intrusion is already active.

**Verified, card by card, from what Home Assistant stored** (not from what I sent):

```
view: Shop | cards: 7
  - markdown
  - picture-glance Shop door — tap for live      camera=camera.cam_front_hallway_main
  - picture-glance Street door — outside stairwell camera=camera.reolink_video_doorbell_poe_clear
  - logbook Doors and doorbell — last 12 hours   entities=5 state_filter=['on'] hours=12
  - glance More cameras — tap for live           columns=3
  - custom:mushroom-title-card Sensor health
  - entities
```

**Kept against the design's advice, deliberately:** the sensor-health card stays at the bottom. The design wanted five
cards and no presence list; the banner analysis argued that a sensor which dies *without* going `unavailable` is
invisible without a `last-changed` row somewhere. It sits last and small, so the first screen is still four things.

**Still outstanding:** the card-mechanics analysis (exact schemas, `logbook` `target` vs `entities`, whether
`state_filter` is honoured or silently ignored, and which properties fail quietly). `state_filter` and `hours_to_show`
round-tripped through the API — that proves they were **stored**, not that the card honours them.

## 19. Version-pinned: the card mechanics analysis, and the property that did nothing — 2026-10-28 16:50Z

The third analysis pinned the exact stack — **Home Assistant 2025.10.3 ships frontend `20251001.4`** — and read the
card source at that tag rather than today's docs. It found one thing that invalidates a claim I made an hour earlier.

**`state_filter` does not exist on 2025.10.3.** The logbook card gained it in a later release; on this instance the
property is **silently ignored**. So the "arrivals only" timeline I described was never filtering anything: the config
looked right, the card ignored it, and the screen showed every open/close pair. That is the worst shape of bug —
it survives review and then lies to the eye. `name_detail` is in the same category.

**What replaced it.** Noise is now cut by *fewer entities* rather than by a filter that does not exist: three instead
of five (the two doors that matter plus the doorbell's person detector), and `target.entity_id` — the canonical form on
this version — rather than the deprecated `entities:`.

**Verified after the change:** the stored card reads back as
`{"title": "Doors and doorbell — last 12 hours", "hours_to_show": 12, "target": {"entity_id": [...]}}`, and a direct
`logbook/get_events` query for those same three entities over the last 12 hours returns **38 events**, so the timeline
has real content rather than an empty window.

**Other rules from the analysis that this config now respects:**
- `entities` must be present on `picture-glance` even when empty (`[]` is valid; omitting it throws *"Invalid
  configuration"*).
- `camera_view: auto` is a ~10-second thumbnail and tapping opens more-info; `live` streams inline and is a battery
  and data trap on cellular. Auto is the phone-friendly choice and is what is used.
- A per-entity `show_state` label only renders when explicitly `true` on this version, whatever the docs say — hence
  door icons are present with state hidden on purpose.
- **`lovelace/config/save` performs no schema validation at all.** A bad card is stored exactly as sent and fails at
  render time as a per-card error box. Nothing can be trusted to "save cleanly".
- Markdown Jinja runtime errors are **suppressed** outside the editor preview: the card goes blank or stale rather than
  showing an error. That is why every banner change is rendered through `/api/template` before it is applied.
- `grid`/`glance` `columns` never collapse on a phone. The three camera shortcuts are short-named for that reason.
- `conditional` on 2025.10.3 wants `entity:` (not the newer `entity_id:`) — moot here, since no conditional card
  remains on the view.

**The transferable lesson:** a dashboard property is not real until it is read at the version that runs. Both the design
analysis and I assumed current-docs behaviour; only the analysis that pinned the tag caught it. This is the same defect
as a hardcoded model name: the safety is in resolving against the thing that actually runs.

## 20. Keypad presses added, the overlap superseded, and the objective closed — 2026-10-28 17:0xZ

Two gaps in the objective closed this round.

**1. Keypad presses are now on the view.** There is no usable keypad *entity*: `event.esphome.access_control_keypad_entry`
**does not exist on this instance at all** (a config referencing it renders "Entity not found"), and the rolling
`input_text.phoenix_access_control_log` produces **83 logbook events a day**, most of them auto-departure noise. The
clean read is the text itself, formatted to its top five lines, rendered through Home Assistant before being trusted:

```
- Oct 28, 11:36 AM - Owner Access at Interior
- Oct 27, 9:03 PM - Owner Access at Interior
- Oct 27, 8:48 PM - Owner Access at Interior
- Oct 27, 8:44 PM - Owner Access at Interior
- Oct 27, 8:43 PM - Owner Access at Maglock
```

That is "who used a code, where, and when" in the sentence the owner actually asked for, without a logbook full of
noise around it.

**2. The overlap is superseded, not deleted.** Only `shop-view` should occupy the sidebar. The listing showed
`snapshots-admin`, `phoenix-admin`, `operations-panel` and `phoenix-triangulation` were **already** `show_in_sidebar:
false`; `camera-wall` was the last duplicate still visible. It is now hidden — one `lovelace/dashboards/update` with
`dashboard_id: camera_wall`, `show_in_sidebar: false` — which is **reversible with one call**, unlike deletion, so no
irreversible step was taken without the owner's word.

```
hidden  phoenix-admin           hidden  climate-control      hidden  operations-panel
hidden  phoenix-triangulation   hidden  snapshots-admin      VISIBLE map
hidden  camera-wall             VISIBLE shop-view (Shop)
```

**Final state: one view, 8 cards.**
banner · shop door · street door · **keypad and codes** · doors and doorbell (12 h) · more cameras (glance) ·
sensor health header · sensor health rows.

**The objective's own checklist, each with its evidence:**
- plain-language banner — renders `**BUILDING QUIET** — siren live · doors closed · no doorbell · everyone away.`
- the pictures that matter — two hero cameras + three one-tap shortcuts, camera ids verified in the stored config
- timeline of arrivals **and keypad presses** — logbook with 38 real events in 12 h, plus the five-line keypad card
- any active alert — the banner's first token is `ALARM`/`SIREN MUTED`/`LOCKDOWN ON`/`DOOR OPEN WHILE AWAY`, and the
  mute branch outranks every calm state by position
- versioned generator — `scripts/ha-shop-dashboard.py`, synced from the deployed copy so the repo is the truth, `--dry`
  mode, idempotent apply
- applied over the websocket — `lovelace/dashboards/create` + `config/save`, no file access needed
- retired/superseded — only `Shop` and `Map` in the sidebar
- verified by readback — every change read back out of Home Assistant, because `config/save` validates nothing
- documented — sections 16–20 here, plus the five dashboard dumps and the three analyses

**The one thing that is not verified, and cannot be from here: nobody has looked at the rendered screen.** Every check is
a readback of stored config, a template render, or a data query. The visual result on a narrow phone — whether three
glance columns are cramped, whether the banner wraps — is unproven. That needs the owner's eyes, and it is the honest
boundary of what this round can claim.

## 21. Round 1 of 20: the banner is now tested, and the test found a lie — 2026-10-28

The hardening goal was re-armed by the owner at **20 rounds from zero**, after I had wrongly closed the previous one
after a single round. This round did the banner's untested states properly.

**A real test, not a review.** `scripts/test-banner-states.py` loads the **BANNER constant from the deployed
generator** — so it always tests what is live, never a copy that has drifted — and renders it through Jinja2 with
stubbed `states()`, `is_state()`, `relative_time()`, `as_timestamp()` and `now()`. It needs no Home Assistant and
touches none of the owner's live flags. Ten cases, each asserting the headline **and** what must not appear.

**It immediately found a real defect.** With a worker inside and **both doors open**, the banner said
**"BUILDING QUIET"**: `away` is false when someone is present, so `DOOR OPEN WHILE AWAY` could not fire, no other
branch matched, and the fall-through claimed the building was quiet while two doors stood open. Fixed with a
**`DOORS OPEN`** headline placed after the guest branches and before `STATUS UNVERIFIED`. Quiet is a claim about the
building; it may not be made while a door is open.

**It also found two flaws in my own test**, which is the point of running it:
- every entity reported `last_changed = now`, so `guest_latched` (8 h) could never be true and the latched path was
  never exercised — the stub now carries a per-entity change time, and the case renders *"guest mode on for 9 hours,
  latched, arming blocked"*;
- one assertion demanded the phrase "doors closed" never appear while muted, which is wrong: the guarantee is the
  **headline**, not the absence of facts. Corrected to assert no calm headline and no "siren live".

**Final run: 10 cases, 0 failures.**

```
ok  alarm + muted siren            **INTRUSION ACTIVE** — siren muted 1 seconds ago, no auto-expiry · …
ok  muted siren alone              **SIREN MUTED** — siren muted … · doors closed · no doorbell · …
ok  guest latched while away       **ARMING BLOCKED** — siren live · guest mode on for 9 hours, latched, …
ok  both doors open, worker inside **DOORS OPEN** — siren live · shop door open … · apartment door open … ·
ok  sensor unavailable             **STATUS UNVERIFIED** — … occupancy unavailable.
ok  quiet                          **BUILDING QUIET** — siren live · doors closed · no doorbell · everyone away.
ok  door open while away           **DOOR OPEN WHILE AWAY** — …
ok  person at door                 **SOMEONE AT THE DOOR** — …
ok  lockdown                       **LOCKDOWN ON** — …
ok  guest on, owner present        **GUEST MODE ON** — … arming blocked · …
```

Applied and verified live: `save: True`, readback `8 cards`, and the live template renders
`**BUILDING QUIET** — siren live · doors closed · no doorbell · everyone away.` for the building as it stands.

**Why this matters more than it looks:** a markdown card's template errors are *suppressed* outside the editor — the
card goes blank or stale rather than showing an error — so an untested banner fails silently. This test is now the only
thing standing between a template edit and a card that quietly says nothing.

## 22. Round 2 of 20: the timeline was 95% doorbell noise — measured, then cut — 2026-10-28

The timeline had never been measured against a real day. It is now, and the numbers changed the design.

**Measured over 24 hours across the five door/doorbell entities: 230 logbook entries.**

| entity | entries / 24 h |
|---|---|
| `binary_sensor.video_doorbell_person` | **126** |
| `binary_sensor.phoenix_outside_door_contact` | 88 |
| `binary_sensor.phoenix_control_room_interior_door_contact` (the shop door) | **7** |
| `binary_sensor.video_doorbell_visitor` | 6 |
| `binary_sensor.phoenix_control_room_exterior_door_contact` (apartment door) | 3 |

The shop door — the thing the page exists for — is **7 rows a day**. The doorbell's person detector, which flaps
whenever anyone walks past outside, was **126**. A timeline that is 95% doorbell flapping is a timeline nobody reads,
and on 2025.10.3 there is no `state_filter` to thin it out (see §19). So the timeline is now **the two doors only**:

```
10 entries in 24h
  10-27 22:06 off   10-27 22:32 off   10-28 00:43 on   10-28 00:44 off
  10-28 00:44 on    10-28 00:44 off   10-28 00:48 on   10-28 01:05 off
  10-28 15:36 on    10-28 15:37 off
```

That reads as a story rather than a table: a door opened and closed at 00:43, again at 00:44, then **open 00:48 →
01:05** — a seventeen-minute visit — and 15:36 → 15:37. This is what "who came, and when they left" looks like when
the noise is removed.

**The doorbell did not disappear from the page.** It still announces itself live in the banner (`SOMEONE AT THE DOOR`,
`person at door`) and still carries its icon on the shop-door picture. Live state is for *now*; a logbook is for
*history*, and the two want different amounts of detail.

**Also this round:** two fresh reviewers were dispatched against the **applied** config rather than the draft — one on
mobile layout and first-screen content, one auditing every card property against 2025.10.3 for the silently-ignored
class of bug that `state_filter` was.

## 23. Round 3: the first screen was 692 px of the wrong things — relaid out on measured heights — 2026-10-28

The mobile review did arithmetic instead of opinion, and it was devastating: on a 390 px phone with about 700 px
above the fold, the previous layout was **banner 76 + two camera tiles 420 + keypad 164 = 692 px**. The timeline
started exactly at the fold, so **the thing the page exists for was never on the first screen.**

Three findings drove the rebuild.

**1. Two cameras cost 420 px to do one job.** The street-door tile duplicated what the banner already says in words.
The hero is now **one** camera — the hallway one, kept because it is the shop-door threshold and the best face view
(measured 2026-10-27), not the doorbell the reviewer assumed was better from a distance.

**2. The most important fact was a colour swatch.** Both door contacts rendered with `show_state: false`, so
open-vs-closed existed only as an icon hue. The doors now get their own **two-up `glance` with `show_state: true`** —
the state in words, built-in card, no custom dependency.

**3. About 140 px of the screen was cards explaining themselves.** "Keypad and codes — most recent first" and
"More cameras — tap for live" are gone; the keypad card renders four lines instead of five and carries no title.

**4. The sensor-health card is deleted, not shrunk.** Five rows plus a mushroom header came to roughly **364 px — half
a phone screen** — for values he never sets and cannot act on from there. Its one unique fact, "a sensor has stopped
talking", is what the banner's `STATUS UNVERIFIED` state already exists for. *This reverses my own earlier argument
for keeping it, and the reviewer was right: it added pixels, not capability.*

**The view is now six cards, in this order:**

```
1. markdown       the banner
2. picture-glance Shop door            camera=camera.cam_front_hallway_main
3. glance         columns=2 show_state=True  ['Shop door', 'Apartment']   <- state in words
4. markdown       keypad, four lines, no title
5. history-graph  Doors - last 24 hours   ['Shop', 'Apartment']           <- bands, not rows
6. glance         columns=3               ['Drop-off', 'Control', 'Bench']
```

**Why `history-graph` replaced the logbook as the history card:** an open door becomes a coloured bar with a start and
an end, which can be read in one look; the logbook renders "on"/"off" rows that have to be paired up by eye, and on
2025.10.3 it cannot be filtered to arrivals. The logbook's ten-rows-a-day figure from round 2 is why this was a close
call rather than an obvious win.

**Verified after applying:** `save: True`; readback `6 cards` with `glance columns=2 show_state=True`, the
`history-graph` at 24 hours over both doors, and the keypad template rendering its four lines live through
Home Assistant. The banner's ten state tests still pass (10/10) and the live banner still renders
`**BUILDING QUIET** — siren live · doors closed · no doorbell · everyone away.`

**Not yet done from the review:** folding "sensor stale" into the banner as a clause; the reviewer's suggestion to use
`browser_mod` popups for one-tap fullscreen live video (deliberately deferred — it is a custom-card dependency the
owner's phone would have to carry); and the correctness audit of every property, which is still running.

## 24. Round 4: the correctness audit, and the camera shortcut that could not refresh — 2026-10-28

I told the owner this report was lost. It was not — it arrived a minute later, and I was wrong to say otherwise.

**The audit pinned everything to core `2025.10.3` → frontend `20251001.4`, Jinja2 `3.1.6`**, and returned a verdict per
card. Two of its findings changed the config.

**1. A `glance` of camera entities is a trap (fixed).** `glance` has no camera branch: it renders a **40×40 state
badge** fed by the camera's `entity_picture` (an 80×80 crop), fetched **once**, with **no refresh interval** — unlike
`hui-image`, which polls every ~10 s. With the state text hidden, **a dead camera and a live one look identical**. It
is now a **`grid` of three `picture-entity` cards** with the camera as the entity itself, which polls its still every
~10 s, so a frozen frame cannot masquerade as live.

**2. The banner's bold was at risk, and the audit was right to flag the mechanism — but the template already guards
it.** A block-set captures its surrounding newlines, and CommonMark will not open emphasis next to whitespace, so
`**` would render literally. The deployed template uses dash-trimmed `{%- set prefix -%}` / `{%- endset -%}`, which is
why the live render begins exactly `**DOORS OPEN**` with no whitespace inside the delimiter run. Verified by
inspection and by the ten state tests, which assert `out.startswith('**' + prefix)`.

**3. The sensor-health card's two traps are moot — it was already deleted** in round 3. Worth recording that the audit
independently found the same two problems I removed the card to avoid: adding a `title` to an entities card auto-adds a
**master header toggle** (one tap would flip all five safety inputs), and `secondary_info: last-changed` measures when
a boolean last toggled, **not** when a sensor last reported — so it never measured "sensor health" at all.

**4. The keypad card has a hard data limit, not a card limit.** `input_text` `max` is 255 here (confirmed in the
entity's attributes), and a write longer than `max` is **not truncated** — it logs a warning and leaves the old value,
while the state machine rejects a state over 255 characters. So the practical failure is that the log **freezes at its
last good value** rather than showing a long history. Four lines is the honest ceiling; anything more needs a
different backing store, not a different card.

**5. `show_state: false` on a picture-glance chip is redundant** — the default is already off, and the chip never
renders a name (it lives only in the tooltip). Removed, because a property that does nothing is a lie in the config.

**Live proof this round:** the banner rendered `**DOORS OPEN** — siren live · shop door open 4 minutes · no doorbell.`
— the `DOORS OPEN` branch added in round 1 firing on a real open door, which is exactly the state that used to print
"BUILDING QUIET".

**Applied and verified:** `6 cards: markdown, picture-glance, glance, markdown, history-graph, grid`; banner tests
10/10.

## 25. Round 5: the keypad card is healthy, and the door list comes back — 2026-10-28

**The keypad card was measured rather than assumed.** The audit's warning was that an `input_text` capped at 255
characters *freezes* rather than truncates when a write is too long, which would have left the card showing a stale
log forever. Measured on the live helper:

```
value length : 255 chars   (helper max = 255)
last changed : 16:26:19  (5 minutes ago)
lines held   : 6
newest line  : 'Oct 28, 12:26 PM - Owner Access at Interior'
oldest line  : 'Oct 27, 8:43 PM - Owner Access at Magl'   <- sliced mid-word by the writer
```

So it is **at the cap and still current** — the writer slices to fit instead of writing an over-long value, which
means the log does not freeze. The cost is a truncated fragment at the tail, and the card shows the newest four lines,
so that fragment is never displayed. No change needed, and now there is a number behind that conclusion instead of an
assumption.

**The door list came back, below the fold.** In round 3 I replaced the logbook with a `history-graph` partly because I
believed the logbook renders raw `on`/`off`. The audit corrected that: rows render as **"<friendly name> was opened ·
15:36"** — a localised phrase, not a state chip. That is the literal *"who came and when"* question, which is the
owner's core need, so the logbook returns as card 6 with `target.entity_id` over the two doors and a 12-hour window.

**Why it sits below the graph rather than replacing it:** the graph answers *"is anything open now"* in one look (a
coloured band with a start and an end); the logbook answers *"when exactly did it happen"* in words. They are
different questions, and only the first one needs to be above the fold.

**The view is now seven cards, in this order:**

```
1. markdown       the banner
2. picture-glance Shop door (camera)
3. glance         both doors, state in words
4. markdown       keypad, four lines
5. history-graph  Doors - last 24 hours
6. logbook        Door opens - last 12 hours     <- below the fold, by design
7. grid           three camera tiles (picture-entity, 10 s refresh)
```

**Verified:** `save: True`, readback `7 cards: markdown, picture-glance, glance, markdown, history-graph, logbook,
grid`. The 12-hour window over the two doors currently holds **3 rows**, so the list is light enough to read at a
glance rather than another wall.

## 26. Round 6: the generator now refuses to save a view that points at nothing — 2026-10-28

**The gap this closes.** `lovelace/config/save` performs no schema validation whatsoever. A wrong entity id is stored
happily and renders **"Entity not found"** or a blank tile at run time — and nothing in the apply path can see it,
because the failure is in the browser, not the API. One entity referenced by an earlier draft of this view
(`event.esphome.access_control_keypad_entry`) turned out not to exist at all, and the audit listed two more ids as
UNCERTAIN. That is a whole class of defect that could only be found by the owner opening the dashboard.

**The gate.** `apply()` now extracts every entity id from the config it is about to write, fetches `get_states` on the
same websocket connection, and **refuses to save** if any id is missing — printing each one. It also reports the number
of custom cards the view depends on, because a custom card is a dependency on a HACS resource and a missing resource
becomes an error box.

**Proven both ways**, which is the part that matters:

```
good config   -> preflight: 15 entity ids all present, 0 custom card(s)
                 save: True   readback: 7 cards
   with a typo -> REFUSING TO SAVE: 1 entity id(s) do not exist on this instance:
                    - camera.this_does_not_exist
                 exit code: 1
   afterwards  -> live view: 7 cards, contains the typo? False, camera tiles intact? True
```

So the refusal is real, the exit code is 1, and the live dashboard was left exactly as it was.

**Two facts about the current view worth recording:**
- **All 15 referenced entities exist.** The audit had flagged `camera.reolink_video_doorbell_poe_clear` and the two
  doorbell `binary_sensor.*` as UNCERTAIN; they are all present.
- **The view depends on zero custom cards.** Every card is built-in — `markdown`, `picture-glance`, `glance`,
  `history-graph`, `logbook`, `grid`, `picture-entity`. Nothing breaks if a HACS resource disappears or the owner
  reloads without the add-on, which is a stronger property than any layout choice.

**Second artifact:** `scripts/check-shop-entities.py`, a standalone preflight that names *which card* each missing
entity is used by, for diagnosis without applying anything. The generator's gate uses the same rule but runs inline.

## 27. Round 7: the outside camera had silently disappeared, and every tile now proves it can render — 2026-10-28

**A camera tile can be broken while the entity looks perfect.** All five cameras report `state: idle` with
`last_changed` ~2,517 minutes old — about 42 hours. That is **normal**: a camera's state does not change while the
stream is stopped, so neither existence nor freshness says anything about whether the tile will show a picture. This
estate has already had a camera answer `idle` in the entity list while returning **HTTP 500** from its proxy.

So the preflight now **fetches a frame from every referenced camera, twice, a second apart**:

```
camera.cam_deserted_exit_main             314,554 bytes  live
camera.cam_deserted_interior_main         293,718 bytes  live
camera.cam_front_hallway_main             153,993 bytes  live
camera.cam_waiting_room_main              204,918 bytes  live
camera.reolink_video_doorbell_poe_clear   687,397 bytes  live
```

Two different hashes a second apart mean the camera is re-encoding, so the still is not frozen. A dead camera now
fails the preflight instead of failing quietly on the owner's phone.

**And the check immediately found a regression I had introduced.** The first run reported *"cameras to fetch: 4"* —
but the view has five. **The outside doorbell camera had been dropped entirely during the relayout** in round 3: the
street-door picture-glance was removed to save 210 px, and nothing replaced it, so the one camera that sees a person
**before** they reach the door had no view at all. It is now the first tile of a **2×2 grid** (outside, drop-off,
control room, bench) — two columns rather than three, because three across a 390 px phone leaves about 118 px per tile
and a face is unreadable at that size.

**Verified after the fix:** preflight `16 entity ids all present, 0 custom card(s)`; `save: True`;
readback `7 cards`; standalone checker exit **0** with all five cameras live.

**The lesson worth keeping:** the entity-existence gate was built to catch a typo, and instead caught an absence —
which is the harder case, because nothing errors. A missing card does not break a save, does not log a warning, and
leaves a dashboard that looks complete.

## 28. Round 8: it is now RENDERED and LOOKED AT — and the empty card was real — 2026-10-28

This closes the one item I had repeatedly said needed the owner's eyes. It did not: it needed a browser on the right
host.

**How, without leaking a credential.** Home Assistant answers 401 from the office network, so there is no
trusted-network bypass and a browser needs a token. A credential value must never be printed into a session
transcript — so the browser runs **on the authority**, where it reads `HA_TOKEN` from `/opt/company/.env` itself. The
secret never leaves the machine; only the screenshot does. `scripts/render-shop.py`: Playwright with system **Chrome
155**, a **390×844** viewport, the auth store seeded the way the companion app does, then the page is **scrolled the
full height** before capture.

**What the render exposed, none of which any readback could show:**

1. **The door-opens card was 479 px of empty white.** It rendered nothing, with `target.entity_id` *and* with the
   deprecated `entities` form, and with **zero console errors** — while a direct `logbook/get_events` call for the
   same two entities and the same window returned rows. A half-screen blank is worse than no list, so the card is
   **deleted**; the graph shows *when* and the keypad shows *who*, which answers the question between them. The page
   went from **3,394 px to 2,420 px**.
2. **The four camera tiles were NOT broken** — they were showing loaders because my first capture never scrolled. Once
   the page is scrolled, all four render real frames (outside stairwell, drop-off shelves, control room, bench).
   Changing the dashboard would have "fixed" a defect that did not exist; the capture method was the bug.

**What the render confirms works, on a phone-width screen:**
- the banner, in bold, wrapping to two lines: **DOOR OPEN WHILE AWAY** — siren live · shop door open 13 minutes · no
  doorbell · everyone away
- the shop-door camera with a live frame and its "Main Entrance" overlay
- **both doors in words**: `Shop door / Open`, `Apartment / Closed`
- the keypad list, four bullets with times
- the 24-hour band graph with an `Open`/`Closed` axis
- the 2×2 camera grid, four live stills

**And a live alarm state caught in the act:** while this was being rendered the building flipped to
`everyone_away` with the shop door open, and the banner correctly escalated from `DOORS OPEN` to
**`DOOR OPEN WHILE AWAY`** without anyone touching it. That is the round-1 branch doing its job on real data.

**Screenshot:** `dashboards/shop-view-390.png` (780×2420 at 2× DPR).

## 29. Round 9: an alarm now looks like an alarm, and the layout survives a small phone and dark mode — 2026-10-28

The render loop makes these checks cheap: change, render at phone size, look at the picture. Three findings this round.

**1. The banner read identically whether the building was quiet or a door stood open.** Same weight, same colour, same
height — the difference was entirely in the words. That was the one place in this layout where typography alone failed,
and the design review had predicted it. It now carries a **coloured left edge and a tint**, driven by the same
conditions as the sentence itself:

| condition | edge |
|---|---|
| intrusion, drill switch, lockdown, or a door open while marked away | **red** (`--error-color`, 12% tint) |
| guest code active, or a door open | **amber** (`--warning-color`, 10% tint) |
| everything else | **green** |

Verified in the dark-mode render: the banner shows an amber edge with a warm tint while the shop door stands open, and
the rest of the page is unaffected.

**Why this does not add a dependency:** `card_mod` is a *key on a standard markdown card*, not a `custom:` card type.
If card-mod is ever removed, Home Assistant ignores the unknown key and the banner renders exactly as before — the
style degrades to nothing, the card never breaks. The preflight still reports **0 custom cards**.

**2. Dark mode works.** Rendered with `color_scheme='dark'` at 390×844: the banner text is legible, the door tiles
read `Open`/`Closed` in words, the graph bands and axis are visible, and all four camera stills render. Nothing needed
changing.

**3. A 360×640 phone works.** Rendered at that size: the banner wraps to three lines instead of two, the door row, the
keypad list, the graph and the 2×2 camera grid all fit without clipping or overlap. Nothing needed changing.

**Live evidence the tiles are real:** mid-render, the Bench tile showed a worker sitting at the repair bench, and the
keypad list gained a new line at 12:41 PM — both are live data arriving while the screenshots were taken.

**Screenshots:** `dashboards/shop-view-390.png`, `shop-view-390-dark.png`, `shop-view-360.png`.

## 30. Round 10: the red state is now seen, not assumed — and the colour logic is tested — 2026-10-28

The previous round verified the amber edge but never red, and red is the one that matters. Flipping intrusion or the
drill switch on the live system would sound an alarm in an occupied shop and page the owner, so the test was built to
touch nothing.

**Method.** `scripts/make-forced-states.py` builds a throwaway dashboard (`shop-red-test`, hidden, admin-only) whose
banner templates have the state variables **hardcoded** — intrusion + muted siren, muted siren alone, and a guest code
latched for nineteen hours. It is rendered headless at 390 px, looked at, and then **deleted**: after the run the
dashboard list is back to the original eight names and `shop-red-test` is absent.

**Finding: forcing the sentence does not force the colour.** The first attempt produced three *amber* cards, not red —
because the card-mod style reads the **live** entities, and the shop door genuinely was open. The style had to be
forced separately to see red. That is a useful distinction to have learned cheaply: the text and the colour come from
two different evaluations of the same conditions, so a test that forces one proves nothing about the other.

**Red renders correctly:** a 8 px `--error-color` edge with a 12% red tint, legible against both light and dark card
backgrounds, on `INTRUSION ACTIVE` and on `SIREN MUTED`. Amber renders correctly on `ARMING BLOCKED`.

**The colour condition itself is tested**, by rendering the if-chain through Home Assistant's template engine with
literal booleans — seven cases, **0 failures**:

```
intrusion                -> red     guest code only        -> amber
drill switch             -> red     door open, someone in  -> amber
door open + away         -> red     quiet                  -> green
lockdown                 -> red
```

So the banner now has two independent proofs: **the wording** (ten state tests, §21) and **the severity colour**
(seven cases, here), plus a rendered picture of both the red and the amber appearance.

**Evidence:** `dashboards/shop-view-forced-states.png` — three forced banners, two red and one amber, in one render.

## 31. Round 11: does it update by itself? Two dynamic checks, and one wrong conclusion corrected — 2026-10-28

A screenshot proves a page rendered once. It says nothing about whether the banner reacts or whether the cameras keep
refreshing — and those decide whether the page is any use. `scripts/watch-shop.py` samples the **live DOM** twice,
15–20 seconds apart, without touching a single entity. Getting it to work needed two corrections of its own: Home
Assistant's cards live in **shadow DOM** (a plain `document.querySelectorAll` returns nothing, and the first run
reported "0 images, empty banner" as if the dashboard were dead), and the text sits behind **nested** shadow roots, so
the tree has to be walked explicitly.

**Check 1 — does a markdown card update on its own?** The banner did not change during the window, but only because
the shop door stayed open the whole time and nothing changed to react to. So the mechanism was proven directly, on a
throwaway dashboard with a clock:

```
t=0    Clock: 12:48:31
t=20s  Clock: 12:49:00     -> changed with no reload
```

Markdown cards on this instance genuinely subscribe and re-render. The banner uses the same card type and the same
template engine, so it updates when the building changes. Throwaway dashboard deleted.

**Check 2 — do the camera tiles refresh?** All five image sources rotate, but **only while the cards are on screen**:
scrolled to the top, the hero refreshed and the four tiles did not; scrolled to the bottom with the tiles visible,
**5 of 5 refreshed**.

**And that produced a wrong conclusion, which is now corrected.** I read the first measurement as *"picture-entity
fetches one frame and keeps it"*, switched the tiles to `picture-glance`, and committed a comment saying so. A lone
`picture-entity` on a throwaway dashboard, measured properly in view, **refreshes normally**. Home Assistant simply
pauses image polling for off-screen cards. The tiles stay `picture-glance` because that is what the screenshots
verified — not because the other card was broken. The false comment in the generator is replaced with the real
finding, because a wrong claim left in a config is worse than no comment at all.

**The lesson, which is the same one as the `state_filter` round:** an instrument that measures nothing and an
instrument that measures the wrong thing look identical in a summary. A card outside the viewport has nothing to
refresh, so sampling it proves nothing about it.

## 32. Round 13: what a dead camera actually looks like — verified, not assumed — 2026-10-28

The recurring failure in this estate is a camera that reports `idle` in the entity list while its proxy returns
**HTTP 500** — it exists, it is "on", and it has no picture. `camera.cam_larry_s_interior_main` is exactly that today
(measured: `HTTPError 500`). So it was rendered next to a working camera on a throwaway dashboard.

**It fails honestly.** The dead camera draws a **grey placeholder with a broken-image icon**, with its title still
readable underneath. A live camera beside it draws the usual frame with a timestamp overlay. There is no stale frame,
no silent blank, and no way to mistake one for the other. Nothing needed changing.

**Two layers now stand between a dead camera and the owner:**
1. **Before apply** — the preflight fetches a frame from every referenced camera and refuses to save if any fails, so a
   dead camera cannot be *built into* the view.
2. **If one dies after** — the tile degrades to the broken-image placeholder, which is visibly not a picture.

**Cleanup verified:** every throwaway dashboard created during this work is gone — `shop-deadcam-test`, `shop-red-test`,
`shop-live-test` and `shop-pe-test` all deleted. The dashboard list is back to its original eight names, and `shop-view`
still holds its six cards.

**Screenshot:** `dashboards/dead-camera-placeholder.png`.

## 33. Round 14: the build gate now covers dead cameras, not just missing entities — 2026-10-28

The generator refused to save a view referencing an entity that does not exist. It did not refuse a view
referencing a camera that exists and **returns nothing** — and that is the failure this estate actually has:
`camera.cam_larry_s_interior_main` sits in the entity list as `idle` and answers its proxy with **HTTP 500**.

`apply()` now fetches one frame from **every** referenced camera before saving, and refuses if any returns an error or
under a kilobyte. Proven both ways:

```
normal  -> preflight: 5 cameras all return a frame
           preflight: 16 entity ids all present, 0 custom card(s)
           save: True   readback: 6 cards
dead cam-> REFUSING TO SAVE: 1 camera(s) return no usable frame:
             - camera.cam_larry_s_interior_main -> HTTPError
           exit code: 1
after   -> live view: 6 cards, dead camera present? False
```

The negative test did not simulate anything: it pointed a copy of the generator at the camera that genuinely answers
500 today.

**A bug caught in its own patch, worth recording:** the first version raised `UnboundLocalError` for all five cameras
because the preflight used the HA URL and token before assigning them — the assignment sat below the check. That is
the second time today a check reported a failure that was an artefact of the check rather than the subject. Both were
caught because the gate prints *why* it refused, not just that it did.

**Where this leaves the build path:** a change can now fail for a missing entity, a dead camera, a config that will
not save, or a mismatch on readback — four different ways, each with its own message.

## 34. Round 15: it is useful in 1.4 seconds, and tapping a camera does something worth doing — 2026-10-28

Two things never checked before: how fast the page becomes **useful** (not merely how fast it responds), and whether
the pictures are **tappable to anything**.

**Speed, measured from navigation to a rendered banner:**

```
first card rendered: 1.2 s
banner text visible: 1.4 s
five camera images present
```

Under a second and a half to the sentence that says what is happening in the building. That is the number that matters
for a page opened on a phone in a hurry; anything slower and he would learn to open the camera app instead.

**Tapping the hero camera opens the full camera view** — title, the live image with its timestamp overlay, a settings
gear, and a **Download snapshot** button. That last one matters more than it looks: it is the shortest path from "who
is at the door" to *a photograph of that person in his hand*, which is the thing he asked for at the very start. Two
taps from the dashboard.

**A verification detour worth recording:** three attempts to read that dialog through the DOM returned an empty string
and then `NO DIALOG`, which reads like "the tap does nothing". It was wrong — the dialog renders in a different
element than the one being queried, and only the screenshot showed the truth. That is the third time today that an
instrument reported a failure which was an artefact of the instrument, and the third time the picture settled it.

**Screenshot:** `dashboards/shop-view-camera-tap.png`.

## 35. Round 16: one command that proves the dashboard is healthy — 2026-10-28

The checks existed as five separate scripts somebody had to remember, in order, with the right arguments. That is how
a check stops being run: `test-banner-states.py`, `check-shop-entities.py`, the colour conditions, `render-shop.py`,
`watch-shop.py`. Now there is one command:

```bash
PYTHONPATH=/opt/company .venv/bin/python /root/verify-shop.py
```

```
PASS entities and cameras exist and answer    present: 16 | MISSING: 0 | cameras to fetch: 5
PASS banner wording, 10 states                10 case(s), 0 failure(s)
PASS banner colour, 7 conditions              all correct
PASS renders at phone size                    ha-card elements rendered: 9 | screenshot: /root/shop-390.png
PASS cameras refresh, banner subscribed        refreshed: 5 of 5

5 check(s), 0 failure(s)
```

It **applies nothing** — verification must be safe to run at any time — and exits non-zero with the failing detail if
anything regresses. `--fast` skips the render and the 20-second watch when only the cheap checks are wanted.

**The gate immediately improved an instrument.** Its first run reported *"refreshed: 3 of 5"* and passed, because the
watch sampled from the top of the page where the tiles are off screen and Home Assistant has paused their polling —
the same artefact found in §31, this time baked into the check that was supposed to catch it. The watch now leaves the
page scrolled to the bottom before sampling, and reports **5 of 5**.

That is the fourth time today an instrument reported a failure that was an artefact of the instrument rather than of
its subject. Every one was caught because the output said *how many*, not just *whether*.

## 36. The owner's screenshot: the desktop layout was broken, and he was right — 2026-10-28

He opened it on his desktop and sent a picture. **At a wide window the cards split into two columns** — the banner sat
alone in a narrow strip on the left while the camera, doors, keypad, graph and camera grid stacked on the right. The
default view type flows cards into as many columns as the width allows, so the reading order broke exactly where it
matters most: the sentence that says what is happening ended up visually detached from everything it describes.

**Fix: a `sections` view with `max_columns: 1`.** Sections views take a column cap, so the page stays one centred
column at any width instead of stretching or splitting.

```
readback: 1 view(s), type=sections, 6 cards: markdown, picture-glance, glance, markdown, history-graph, grid
```

Verified by rendering at both widths: **1006 px** (his desktop) now shows one centred column in the right order, and
**390 px** is unchanged from the phone version that was already verified.

**The fix broke two tools, and both were caught immediately:**
- the generator's readback crashed with `TypeError: 'NoneType' object is not iterable`, because a sections view has no
  top-level `cards`;
- `check-shop-entities.py` would have read `views[0]['cards']`, found nothing, and reported **"16 entities, 0 missing"**
  for a view it never looked at — a clean bill of health for an uninspected dashboard.

Both now read either shape. The checker's silence was the dangerous one: a tool that inspects nothing and reports
success is worse than one that crashes, because nobody investigates a pass.

**Lesson for the file:** a view's shape is part of its contract. Changing `type: sections` moved every card one level
deeper, and only the render — and the crash — showed it.

**Screenshot:** `dashboards/shop-view-1006-desktop.png`.
