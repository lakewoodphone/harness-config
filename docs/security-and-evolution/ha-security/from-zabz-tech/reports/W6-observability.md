# W6 — Observability: does anything find out that the alarm fired and the page failed?

**LOCAL (zabz-tech)** · audit 2026-10-26 · read-only · no edits, no sends, no restarts.

## Step 0 — revision gate (passed)

```
pwd                                              -> C:\Users\ezabz\Code
phoenix_security.yaml sha256[:12]                -> e6b45f6b1c04   (expected e6b45f6b1c04)
personal-secretary-mvp\app\main.py sha256[:12]   -> f6955c96b0a4   (expected f6955c96b0a4)
```

Live reads: HA at `homeassistant.local:8123` via `_ha-cred-20261018\ha.ps1` (`/api/states` 1,036 entities, `/api/logbook`, `/api/services`, `/api/error_log`); authority `secratary-cloud` via `sqlite3 -readonly /root/authority.db` and `journalctl -u company-api`.

**Read this first — the checkout is behind the deployment.** The local `personal-secretary-mvp` is NOT what runs on the authority:

| file | deployed `/opt/company/...` sha256 | local checkout sha256 |
|---|---|---|
| `app/main.py` | `d0338adc7574cc1f…` | `f6955c96b0a4c3a7…` |
| `app/owner_text.py` | `cf9cd80235312a41…` | `2bbdbca0a576da3a…` |
| `app/sms_service.py` | `6e59347595d47c80…` | `5297e857bccb5c07…` |

`/opt/company` is at `8f19ab373 2026-10-25 19:38 UTC`. The deployed tree already has two things the checkout does not: a `rate_floor` refusal code in the owner-text gate (170 refusals in 7 days) and `owner_text_context={"subsystem":"security_alert_mms","urgency":"urgent"}` on the security page. Line numbers below are the checkout's unless marked *deployed*; every behavioural claim was checked against `/opt/company` where it mattered.

---

## 1. Every channel by which an intrusion becomes visible today

| # | Channel | PUSH/PULL | Proof (read this session) |
|---|---|---|---|
| a | HA logbook (`logbook.log`) — "captured N image(s)", "PAGE FAILED", TEST MODE note | **PULL** | `config/packages/phoenix_intrusion_evidence.yaml:374,387`; `config/packages/phoenix_security.yaml:191`. Live: 40,493 entries in the 10-24→10-27 window. |
| b | Persistent notification "SECURITY PAGE FAILED — intrusion not delivered" | **PULL** | `phoenix_intrusion_evidence.yaml:363-373` (`notification_id: phoenix_intrusion_paging_failed`). Never created — see §2. |
| c | Lovelace "Intrusion Evidence" page (image tiles) + "Intrusion state" card + "Intrusion logbook (7 days)" card | **PULL** | `config/ui-lovelace.yaml:138`; `config/lovelace/snapshots_admin.yaml:275-476` (verified 83 matching lines in `config/lovelace/`). |
| d | HA system-health persistent notifications (security hub offline/low memory/reboots) | **PULL** | `config/automations/system_health_monitoring.yaml:15,66,114,149` — every one is `persistent_notification.create`, none calls `notify.*`. |
| e | HA companion-app push (`notify.mobile_app_zabz_waze`, `notify.mobile_app_iphone_15`, `notify.mobile_app_monty`) | **PUSH** — but **not on the intrusion path** | Live `/api/services`: 14 `notify` services incl. 3 `mobile_app_*`. Used only by `config/automations/outside_door_stuck_open.yaml:89,96` (stuck door). Zero references in `phoenix_security.yaml` / `phoenix_intrusion_evidence.yaml`. |
| f | SMS/MMS to owner + `HA_SECURITY_EXTRA_RECIPIENTS` via Twilio | **PUSH** — the only intended intrusion page | `phoenix_security.yaml:284-292` (`rest_command.phoenix_security_page` → `https://ai.abletelsolutions.com/webhook/ha/security-alert`) → `app/main.py:8521` → `app/sms_service.py:2126 send_security_alert_mms`. |
| g | Email | **does not exist on this path** | No email call in `phoenix_security.yaml`, `phoenix_intrusion_evidence.yaml`, or the webhook handler (`main.py:8521-8682`). |
| h | Secretary task / goal | **does not exist** | The webhook writes no task, goal, memory or event row — the only write is the SMS audit row inside `send_message` (`sms_service.py:540-578`). See §4. |
| i | `ha-watch` (cron `7,37 * * * *`, authority) → wake flag + `/root/ha-watch/ALERT.txt` | **PULL** (queue, not a phone) | `/root/bin/ha-watch.py` docstring: *"It does not text the owner: outbound is not this job's to spend."* Live run log 18:07:03Z `OK entities=1036 unavailable=319`. Checks: HA reachable, security entities unavailable, door-contact staleness, door stuck open, clip age, off-site age, disk. **No check of the paging path.** |

So: **one push channel exists (f)**, it has never delivered an intrusion page, and the three HA companion-app pushes that could reach a phone in 2 seconds are wired to a door that stays open, not to a break-in.

## 2. "The alarm failed to page and nobody would have known" — PROVEN

**Six real intrusion runs in the window, all six died before the page, and the failure notice died with them.**

Evidence, all from this session:

1. **The sequence aborts at step 4, which sits before both the page and the failure notice.** `phoenix_intrusion_evidence.yaml:251-256` runs `shell_command.phoenix_verify_evidence_files`; the page is step 6 (`:311`); the "fail LOUD" persistent notification is `:356-380`; the terminal audit line is `:387`. Home Assistant executes `shell_command` with `create_subprocess_exec`, so the pre-fix first word `for` raised `FileNotFoundError` **inside the service** — `continue_on_error` does not cover it, and the script aborted there. That defect is documented as measured in the same file at `:48-58` (quoted HA error: `Unexpected error for call_service at pos 5: [Errno 2] No such file or directory: 'for'`).
2. **The logbook shows exactly that shape.** Six `Phoenix: Intrusion Evidence And Page` runs, each 4-7 s, none followed by the step-7 line:

| real run (local) | duration | step-7 "captured" line? |
|---|---|---|
| 10-24 22:25:15 | 5 s | no |
| 10-25 16:59:36 | 5 s | no |
| 10-25 21:01:00 | 4 s | no |
| 10-25 21:38:54 | 5 s | no |
| 10-26 02:14:22 | 5 s | no |
| 10-26 14:03:43 | 7 s | no |
| 10-26 14:16:35 (drill, after the fix) | 5 s | **yes** — "captured 3 image(s) for intrusion_test …" at 14:16:40 |

   Whole window: `"PAGE FAILED"` matches = **0**, `"captured N image(s)"` matches = **1**. The notification branch at `:356` therefore never executed — the one surface built to say "NOBODY was paged" was placed after the step that stops the sequence.
3. **The page never reached the server either.** `journalctl -u company-api --since '2026-10-24 00:00:00' | grep -c 'security-alert'` = **2**, both on 10-26 at `18:16:04Z` and `18:16:40Z`, both `200 OK`. The second is the 14:16 drill. Zero hits at any of the six real episodes.
4. **No SMS was ever attempted.** `sms_log`: 4,507 rows, `2025-09-02T06:19:25Z → 2026-10-26T17:44:57Z`. `body LIKE '%LPT-SECURITY%'` = **0**; `body LIKE '%intrusion%'` = **0**. Every `send_message` attempt writes an audit row even when it fails or is suppressed (`sms_service.py:540-578`), so zero rows means zero attempts, not six failures.
5. **The one mechanism that would have surfaced it is the HA core log — and nothing reads it.** `/api/error_log` today holds **62 lines / 9,874 chars**, all since the 14:14:59 restart; the six failures' own `ERROR` lines are gone. Nothing consumes `/api/error_log`: `ha-watch.py` never reads it (grep for `error_log` in it: no match), and no automation does.

**Answer: proven.** The only record was a log line that (a) is not pushed anywhere, (b) is erased by any restart, and (c) is read by nothing. The siren was the entire observability system.

## 3. What the secretary backend does with an inbound security alert

- **Endpoint**: `main.py:8521-8682` (deployed `9016-9176`). Auth `_authenticate_webhook(security_api_key)`, body `{event, detail, snapshots, force}`.
- **Test events are skipped by design**: `main.py:8594-8596` returns `{"ok": true, "paged": false}` for `intrusion_test` / `test_drill` / `test` unless `force`. That is why the 14:16 drill proved the transport and nothing else.
- **A record is kept only if it sends.** The handler writes no DB row of its own — no task, no goal, no event, no operation_journal entry. The single row is the `sms_log` audit row written by the `_audited_send` wrapper (`sms_service.py:540-578`). When the event is a test, or when every recipient is refused, the request is answered and **nothing about why survives**: `{"ok": false, "paged": true, "result": {...}}` goes back to Home Assistant, which only uses `content.ok` to decide whether to retry (`phoenix_intrusion_evidence.yaml:322-351`).
- **Nothing reads it as a security signal.** `activity_log` rows matching `%intrusion%` or `%SECURITY PAGE%`: **0**. `operation_journal` security rows exist (318) but are unrelated operations.
- **`ha:security_alert` in `trigger_engine.py` is dead code.** The rule at `trigger_engine.py:685-730` (door unlocked at night) requires `ctx["home_assistant"]["doors"]`. The only caller builds `{"world_context": <text>, "tick": n}` and nothing else (`autopilot.py:6060-6067`), so `ha.get("doors", [])` is always `[]` and the rule returns `[]` at `:697`. It cannot fire from the autopilot tick. Even if it did, its output becomes a `goal_plans` row (`autopilot.py:6095-6102`) — a PULL artefact worked by an agent tick, not a page.

## 4. Is there a heartbeat or self-test that proves the paging path still works?

**No.** Established by elimination, not by assumption:

- No automation calls the page path on a schedule: grep of `config/automations/*.yaml` and `config/packages/*.yaml` for `heartbeat|self.test|paging.*test` returns only the test-mode comments in `phoenix_security.yaml`.
- `script.phoenix_test_intrusion_sequence` (`phoenix_security.yaml:259-268`) is manual, and it deliberately sends `intrusion_test`, which the secretary refuses to page (`main.py:8594`). It proves evidence capture and HTTP reachability — that is exactly what it did at 14:16:40 — and it can never prove delivery.
- `ha-watch` (30-min) covers HA reachability, sensor availability, door staleness, clip age, off-site age, disk. None of those is "did a page get through". On 10-24→26 it was green every 30 minutes while the pager was dead.
- `scripts/check-security-absence.py` exists in `personal-secretary-mvp` and is the right philosophy ("absence is the alarm"), but it is **not scheduled anywhere**: `crontab -l` on the authority has no line for it, and no systemd timer mentions it.
- `ha-config/scripts/check_intrusion_payload.py`, cited in `phoenix_intrusion_evidence.yaml:283`, **does not exist** (`Test-Path` false).

**Cheapest honest one** (no SMS, no human paged, ~zero cost):

1. HA automation, every 6 h: `rest_command.phoenix_security_page` with `{"event":"intrusion_heartbeat","detail":"paging path self-test","snapshots":[]}`.
2. Secretary: `main.py` returns `{"ok": true, "paged": false, "heartbeat": true}` for `intrusion_heartbeat` **before** the media/send block, and writes one row to a new `security_page_receipt(event, received_at, remote, ok)`. No Twilio call, no owner SMS.
3. HA: on `status < 400 and content.ok`, `input_datetime.phoenix_last_page_ok = now()`.
4. HA automation: if `now() - input_datetime.phoenix_last_page_ok > 8h` → `persistent_notification.create` **and** `notify.mobile_app_zabz_waze` (the push channel that already exists), so a dead pager reaches his phone once ever, instead of being discovered two days later by ear.
5. `ha-watch` gains one check: newest `security_page_receipt` older than 8 h, or any receipt with `paged=false AND event NOT LIKE '%heartbeat%'` in 24 h → fault. It already writes `ALERT.txt` and raises wake flags.

That chain proves HA → tunnel → API → auth → handler. Twilio itself can only be proven by a real send; the honest version is one labelled TEST message a month to the owner, or trust `sms_log` delivery status (Twilio status is stored per row, `sms_log.status`).

## 5. An intrusion at 03:00 with the shop empty

**Path (today, post-fix):**
door contact / zone motion → `automation.phoenix_extreme_intrusion_trigger` (6 s grace, `phoenix_security.yaml:69`) → `input_boolean.phoenix_intrusion_active` → `script.phoenix_intrusion_initial_response` (4+4 camera snapshots) → `rest_command.phoenix_alarm_mac_on` + `script.phoenix_intrusion_loop` (siren/strobe) → `script.phoenix_intrusion_evidence_and_page` → `shell_command.phoenix_verify_evidence_files` → `rest_command.phoenix_security_page` → `https://ai.abletelsolutions.com/webhook/ha/security-alert` → `send_security_alert_mms` → Twilio MMS to owner + extra recipients.

**Does it reach his phone?** Only through that single Twilio message, and only if four things are all true:

1. the evidence verifier does not abort the sequence (fixed 2026-10-26, proven by the 14:16 drill reaching step 7);
2. the secretary API and the Cloudflare tunnel are up (measured: 200 OK on 10-26 18:16Z);
3. the owner-text gate does not hold the message. The gate is called with `reason="send_message"`, `urgency="normal"` (*deployed* `sms_service.py:1566-1576`) → priority 21; `urgent` is passed only to the relay via `owner_text_context` (*deployed* `sms_service.py:3006`), and `send_message` never passes `interrupt=True` (grep: no `interrupt` in *deployed* `sms_service.py`). An open owner turn is normally answered within hours, but **there is one open right now**: `owner_text_turn` id 249, sent `2026-10-26T17:44:57Z`, `reason='manual send'`, `answered_at` empty. At 18:31Z that turn was 46 min old against a 12 h reply window, and the page (21) does not outrank a turn held at 21 — the graded lock at *deployed* `owner_text.py:3409-3436` decides, not an interrupt. 0 `awaiting_reply` refusals in the last 7 days, so this is latent, not firing;
4. the message is not suppressed as a duplicate — see §6.

**Time-to-notice (measured components, 2026-10-26):**
- trigger → `intrusion_active`: 6 s (by design, `:69`); observed 14:03:15 → 14:03:21.
- → siren: **28 s** (14:03:15 trigger → 14:03:43 `rest_command.phoenix_alarm_mac_on`/loop).
- → page handed to the secretary: the drill was active from 14:16:10 and the API logged the POST at `18:16:40Z` = 14:16:40 local → **~30 s** from start of sequence, ~5 s after the evidence step began.
- → Twilio delivery: **unmeasured**. There is no real-page row in `sms_log` to time, ever.

So: **best case ≈ 35-60 s from the door opening to a buzz, and that figure is inferred, not observed** — no real intrusion page has been delivered in the last 40 days. The last confirmed real page is the one described in `phoenix_intrusion_evidence.yaml:295-296` (2026-09-16, "Twilio confirmed all four roster recipients received it").

**The 03:00 answer in one line:** it reaches him only if the secretary API is up, the gate is not holding a turn, and the body is not a duplicate — and if it does not, nothing tells him, because the second channel does not exist and the failure notice is a dashboard notification he would have to go looking for.

## 6. The gap between "the siren sounds" and "someone is told", quantified

First human action anywhere in the logbook after the outage began is the manual `Phoenix: Intrusion Reset` at **10-26 14:05:40** (no automatic disarm precedes it; `phoenix_security.yaml:175` records the same event: "ran until a human manually reset it at 14:05:40"). Gap = that timestamp minus each siren start:

| episode | siren loop start | gap to first human action (10-26 14:05:40) |
|---|---|---|
| 10-24 22:21:31 | 10-24 22:21:49 | **39 h 43 m 51 s** |
| 10-25 16:59:36 | 10-25 16:59:36 | 21 h 06 m 04 s |
| 10-25 21:01:00 | 10-25 21:01:04 | 17 h 04 m 36 s |
| 10-25 21:38:54 | 10-25 21:38:59 | 16 h 26 m 41 s |
| 10-25 23:23:21 | 10-25 23:23:38 | 14 h 42 m 02 s |
| 10-26 02:14:22 | 10-26 02:14:22 | 11 h 51 m 18 s |
| 10-26 14:03:15 | 10-26 14:03:43 | **2 m 19 s** — and that was him *hearing* it, not being told |

The gap is not "minutes": for every episode where he was not standing in the shop, the page was never sent and the notice was never created, so the gap is **unbounded until a human happens to be within earshot**. Six episodes, 39 h 44 m for the first, and the only reason it ended is that he walked past a screaming siren.

---

## Findings

### F1 — CRITICAL — The pager has never run; the "page failed" alarm sits behind the step that fails
**Claim.** In the whole 10-24→10-26 window there was not one page attempt and not one "SECURITY PAGE FAILED" notice. The abort happens at step 4 of six.
**Proof.** Logbook 40,493 entries / `"PAGE FAILED"` = 0 / `"captured N image(s)"` = 1 (10-26 14:16:40, drill). `journalctl -u company-api` since 10-24 → 2 `security-alert` hits, both 10-26 18:16Z, both 200. `sms_log` 4,507 rows, 0 `LPT-SECURITY`, 0 `intrusion`. Ordering: `phoenix_intrusion_evidence.yaml:251` (abort point) < `:311` (page) < `:356-380` (failure notice).
**Fix.** Page before evidence, or evidence without a shell step in the critical path: move `rest_command.phoenix_security_page` to step 1 of `phoenix_intrusion_evidence_and_page` with `snapshots: []`, then send the pictures as a second MMS. A text page that arrives in 3 s beats a picture page that arrives never. Independently, wrap the verifier result so a failure sets a flag rather than ending the script.

### F2 — CRITICAL — There is exactly one push channel, and it is the fragile one
**Claim.** The intrusion path has no channel that reaches a phone other than the secretary's Twilio MMS. The three HA companion-app pushes that exist in this installation are wired to the stuck-door automation only.
**Proof.** Live `/api/services`: `notify.mobile_app_zabz_waze`, `notify.mobile_app_iphone_15`, `notify.mobile_app_monty` all registered. `outside_door_stuck_open.yaml:89,96` uses two of them; `phoenix_security.yaml` and `phoenix_intrusion_evidence.yaml` contain no `notify.` call at all.
**Fix.** Add `notify.mobile_app_zabz_waze` + `notify.mobile_app_iphone_15` to `phoenix_intrusion_initial_response`, next to the siren and **before** the evidence step, with `continue_on_error: true`, carrying `tag: phoenix_intrusion` and `critical` priority so iOS bypasses silent/DND. That is a 6-line change, it depends on no server, no tunnel, no Twilio, no owner-text gate, and it converts a two-day discovery into a two-second one.

### F3 — HIGH — No heartbeat exists for the paging path; every scheduled check is blind to it
**Claim.** Nothing in the estate can answer "did the pager work today", and `ha-watch` — the only 30-minute watcher — was green throughout the outage.
**Proof.** `ha-watch.py` docstring checklist + run log `2026-10-26T18:07:03Z OK entities=1036 unavailable=319 disk=10259MB clip_age=142s offsite_age=49621s`; grep of `ha-watch.py` for `error_log`/`paging`: no check. No crontab line, no systemd timer, no HA automation exercises the page path. `check_intrusion_payload.py` referenced at `phoenix_intrusion_evidence.yaml:283` does not exist.
**Fix.** §4 above — a 6-hourly `intrusion_heartbeat` that pages nobody, a receipt row, an 8-hour staleness alarm on the existing push channel, and one new `ha-watch` check.

### F4 — HIGH — The secretary keeps no record of an inbound alert, so "did it page" is unanswerable afterwards
**Claim.** The webhook's only durable trace is an `sms_log` row when it actually sends. A test, a gate refusal, a media failure with no send, or a 500 leaves nothing in any table.
**Proof.** `main.py:8521-8682` (deployed `9016-9176`): no DB write outside `send_message`'s audit wrapper. `activity_log` rows matching `intrusion`/`SECURITY PAGE`: 0.
**Fix.** One `security_alert_receipt` row per request (`event`, `ok`, `paged`, `reason`, `recipients`, `media_ok`, `received_at`, `remote`), written before the media block. Then the watchdog question becomes a SQL count instead of an archaeology exercise — and a silent 200 for a skipped test stops looking identical to a delivered page.

### F5 — HIGH — A second intrusion inside 30 minutes pages nobody (duplicate suppression)
**Claim.** The page body is a fixed string; `_preflight_send_request` refuses an identical body to the same number within 30 minutes.
**Proof.** `sms_service.py:873-901` (deployed equivalent): `WHERE to_number=? AND created_at > datetime('now','-30 minutes') AND body = ?` → `Duplicate suppressed`. Body is constant: `phoenix_security.yaml:214` (`"Extreme intrusion triggered - nobody expected present"`) + `"⚠️ LPT-SECURITY"` (`main.py:8599`).
**Fix.** Put a per-event nonce in the body — the trigger timestamp, e.g. `Extreme intrusion triggered at 03:04:17`. One Jinja expression; kills the whole class. Also add `force`-style bypass so the dedup never applies to `event` starting `intrusion`.

### F6 — HIGH — The page can be held behind an open owner text; `urgent` is only given to the relay
**Claim.** The gate sees `reason="send_message"`, `urgency="normal"` (priority 21) and `send_message` never passes `interrupt=True`; the `urgent` label exists only in `owner_text_context` for the relay. An open turn in the money or obligation band outranks it.
**Proof.** *Deployed* `sms_service.py:1566-1576` (gate call) vs `:3006` (`owner_text_context`); grep `interrupt` in *deployed* `sms_service.py`: no match. Priority arithmetic: `owner_text.py:200-263`, bands 0/10/20/30 with `_BAND_STEP=10`. Live: `owner_text_turn` id 249 `sent_at=2026-10-26T17:44:57Z reason='manual send' answered_at=NULL` (1 open turn), reply window default `DEFAULT_REPLY_WINDOW_HOURS = 12.0` (`owner_text.py:98`).
**Fix.** Call the gate from the security path with `interrupt=True`, or pass `urgency="critical"` through `send_message` for `event in {"intrusion","panic","duress"}`. The `interrupt` parameter exists precisely for "person or property in immediate danger" (`owner_text.py:1383-1388`) and the intrusion page is that case; today it is entitled to rank, but it is not entitled to interrupt.

### F7 — MEDIUM — Every HA-side failure surface is PULL, and the dashboard shows green while the pager is dead
**Claim.** Logbook, persistent notifications and the Lovelace cards all require someone to look. The "Intrusion state" card shows `input_boolean.phoenix_intrusion_active` — which goes `off` again on disarm — and nothing on any card shows whether the page was delivered.
**Proof.** `config/ui-lovelace.yaml:138` and `lovelace/snapshots_admin.yaml:446-476` (state + 7-day logbook); `phoenix_intrusion_evidence.yaml:363` (the only delivery-status surface, PULL, and never created).
**Fix.** Add the heartbeat's `input_datetime.phoenix_last_page_ok` and a `Page delivered: 14:16 / FAILED` line to the "Intrusion state" card. A card that cannot go red is not a monitor.

### F8 — MEDIUM — The only technical record of a paging failure is erased by a restart
**Claim.** `/api/error_log` holds 62 lines since the 14:14:59 restart; the six `FileNotFoundError` aborts are not in it.
**Proof.** `/api/error_log` read this session: 62 lines, 9,874 chars, earliest `2026-10-26 14:14:59`.
**Fix.** The receipt table in F4 is the durable answer; additionally have HA `system_log` → `logbook.log` any `phoenix_intrusion_evidence_and_page` error, which the recorder keeps.

### F9 — LOW (adjacent, same class) — A security service failed 3 days ago and nothing said so
**Claim.** `pin-rotation-scheme2.service` has been `failed` since `2026-10-22 22:58:33Z`; its own cause was an owner SMS refused by the text gate (`rate_floor`), and the run then rolled back the helpers.
**Proof.** `systemctl status pin-rotation-scheme2.service` this session: `Failed with result 'exit-code'`, `status=2/INVALIDARGUMENT`, logged `FAILURE: owner SMS not accepted: [suppressed] owner_text gate refused (rate_floor)`. 170 `rate_floor` refusals in `owner_text_decision` in 7 days (13 of them `reason='send_message'`).
**Fix.** Any unit whose job is security state must page a human on failure, not just exit 2. Add `OnFailure=` to a unit that pushes to the companion app.

---

## What I could not verify

- **Persistent notifications cannot be read over REST.** HA exposes them only on the websocket (`persistent_notification/get`); `/api/states` has no `persistent_notification` entity. So "the SECURITY PAGE FAILED notification does not exist" is proven **indirectly** — the logbook line at `phoenix_intrusion_evidence.yaml:374` that is written in the same branch is absent (0 matches), and the branch is after the abort — not by reading the notification store itself.
- **`/api/error_log` is not evidence of absence.** It is 62 lines since the last restart; the six failures' `ERROR` lines were pruned before this session. I relied on the logbook, the API access log and `sms_log` instead.
- **Twilio delivery time is unmeasured.** `sms_log` contains no security page in 40 days, so there is no observed "queued → delivered" interval for this message class. The 35-60 s figure in §5 is component arithmetic from the 14:16 drill, not an observation of a delivered page.
- **Whether the companion-app pushes actually ring.** `notify.mobile_app_*` services are registered (live `/api/services`), but `/api/states` contains **0** `mobile_app_*` entities — no battery/sensor entities for those devices. I did not send a test notification (out of scope, and it would page a human), so registration is proven and delivery is not.
- **The six aborts' own error text.** The `[Errno 2] … 'for'` line is quoted from the fix notes in `phoenix_intrusion_evidence.yaml:48-58`, not re-read from a live log (it is gone). The live evidence is the termination shape: no step-7 line, no webhook hit, no `sms_log` row.
- **Deployed-code line numbers.** The authority runs `/opt/company` at `8f19ab373`, whose `main.py`/`owner_text.py`/`sms_service.py` differ from the checkout I was given. Behaviour claims for the webhook, the gate call and the `urgent` context were read from the deployed files; anything else cites the checkout and may be offset by ~495 lines in production.
- **`check-security-absence.py`'s complete schedule.** It is absent from the authority's `crontab -l` and from `systemctl list-timers`; I did not audit work orders, other hosts' crons, or agent-driven invocation, so "not scheduled" is proven for the authority's cron/timers only.
