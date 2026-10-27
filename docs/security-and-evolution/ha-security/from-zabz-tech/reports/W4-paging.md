# W4 — OUTBOUND PAGING PATH AUDIT

**LOCAL (zabz-tech)** · 2026-10-26 · read-only · no message sent · webhook not called · secrets not printed.

STEP 0 verification:
`phoenix_security.yaml` = `e6b45f6b1c04` (expected `e6b45f6b1c04`) · `main.py` = `f6955c96b0a4` (expected `f6955c96b0a4`). No REVISION-MISMATCH. `pwd` = `C:\Users\ezabz\Code`.

Live facts used below were read this session, not remembered: HA version `2025.10.3` (`GET /api/config` from the authority, `cfg_http=200`), the authority is `178.156.194.1`, the API listens `127.0.0.1:8002` and `/health` = 200, `cloudflared.service` and `company-api.service` both `active running`.

## BUILD IDENTITY — the checkout I audited is NOT the build that runs

The task named two checkouts on `zabz-tech`, and those are what I read. The authority does not run them: `company-api.service` has `WorkingDirectory=/opt/company`, `EnvironmentFiles=/opt/company/.env`, `ExecStart=/opt/company/.venv/bin/python -m uvicorn app.main:app`. So I hash-compared, and re-verified every critical construct in the live build by grep rather than assuming equivalence.

| File | Audited checkout (zabz-tech) sha256[:16] / bytes / mtime | Live build (`/opt/company/app`) sha256[:16] / bytes |
|---|---|---|
| `main.py` | `f6955c96b0a4c3a7` / 771,454 / 2026-10-07 16:05Z | `d0338adc7574cc1f` / 804,096 / 2026-10-25 04:30Z (23,410 lines) |
| `sms_service.py` | `5297e857bccb5c07` / 79,373 | `6e59347595d47c80` |
| `config.py` | `f1a2c088d105ded2` / 92,141 | `c8db43c17335ffff` |
| `owner_text.py` | `2bbdbca0a576da3a` / 70,264 | `cf9cd80235312a41` |

Every load-bearing construct in this report was found in the live build, at these lines (audited line in brackets): `ok = all(bool(results…))` live `sms_service.py:3011` [2174]; the 30-minute identical-body dedup live `:1271` [894]; `bypass_owner_kill_switch` live `:2953, :1472` [2126, 1072]; `ha_security_alert` live `main.py:9017` [8522]; `prepare_security_alert_media` call live `:9113` [8618]; the `intrusion_test` skip live `:9089` [8594]; `_supersedes_open_turn` live `owner_text.py:589` [305]; and `send_message`'s backstop gate live `:1566-1570` [1101-1115], still `reason="send_message", urgency="normal"`.

**Correction I have to record against myself.** My first environment read was `/home/zabz/personal-secretary-mvp/.env` — a checkout, not the running unit. I re-read `/opt/company/.env` (root-owned, mode 0600, read through `sudo -n`, values masked) and the paging keys are the same in both, so the roster finding did not change; the provenance in finding 1 is now the correct file. The same mistake produced one wrong statement: I looked for `data/security_media` under the checkout. The live path is `/opt/company/data/security_media`, which **does not exist** — it is created on the first `store_security_media` (`sms_service.py:1791`), so its absence still proves no picture was ever stored, but for the right reason.

---

## 1. THE ROSTER — two phones, one of them duplicated in config
**SEVERITY: MEDIUM**

**Claim.** A page fans out to **two** numbers, not three and not four: the owner's personal mobile (`…7895`) and his wife (`…5096`). His mother (`…5878`) is **no longer configured**, although the recorded decision says she was meant to be on it.

**Proof.**
- Roster is built at `app/sms_service.py:2155-2162`: `owner_notify_target(settings)` first, then each extra, skipped if already present (`if r and r not in roster`).
- `owner_notify_target` prefers `owner_notify_number` (`app/services/owner_notifications.py:64-73`).
- Read from `/opt/company/.env` — the file the running unit actually loads (`EnvironmentFiles=/opt/company/.env`, root-owned, 0600, read via `sudo -n`, values masked). The `/home/zabz/personal-secretary-mvp/.env` checkout carries the same values:
  - `OWNER_NOTIFY_NUMBER` = `+1***…7895` (len 12)
  - `OWNER_PHONE_NUMBER` = `+1***…7895` (len 12) — same number now, so the "monitored inbox repoint" at `sms_service.py:1020-1051` is a no-op
  - `HA_SECURITY_EXTRA_RECIPIENTS` = `+99999999999,+99999999999` shape (len 25, digits masked) = **two** entries: `extra[1] …5096`, `extra[2] …7895`
  - Secret keys present, values never read out: `HA_SECURITY_API_KEY` (len 44), `HA_PTT_API_KEY` (len 44), `DASHBOARD_API_KEY` (len 43)
- Where each is declared: `app/config.py:125` (`security_api_key`, env `HA_SECURITY_API_KEY`), `app/config.py:129` (`security_alert_extra_recipients`, env `HA_SECURITY_EXTRA_RECIPIENTS`), fallback resolution `app/config.py:1816-1833`; HA side sends `x-ps-api-key: !secret secretary_security_api_key` (`ha-config/config/packages/phoenix_security.yaml:290`) — that `secrets.yaml` is not in the repo, it exists only on the HA host.
- The duplicate: `extra[2] …7895` is byte-identical to the owner target, so it is dropped by the exact-string `not in roster` test — but that test is **string equality, not phone-normalised**. Write that entry as `+1 848 389 7895` (internal spaces) and the same phone gets two texts.
- Intent on record, contradicted by the above: `journal/entries/decisions/D240.md` (roster = Google Voice + personal + mother + wife, "his personal mobile was appended to HA_SECURITY_EXTRA_RECIPIENTS") and `journal/entries/wins/W195.md` ("reaches three people"). Neither matches tonight's `.env`.

**Fix.** Delete the redundant `…7895` entry from `HA_SECURITY_EXTRA_RECIPIENTS`; normalise with `_normalize_phone()` before the `not in` test in `send_security_alert_mms`; and decide the mother explicitly — that is the owner's call, not a config accident (see "could not verify").

---

## 2. PAGING IS ALL-OR-NOTHING, AND HA RETRIES THE WHOLE FAN-OUT
**SEVERITY: HIGH**

**Claim.** `ok` is `all()` over recipients. One recipient failing makes the entire page "failed", and HA's retry condition then re-runs the **whole** fan-out — including the recipients who already received it.

**Proof.**
- `app/sms_service.py:2174`: `ok = all(bool(results.get(r, {}).get("ok")) for r in roster)`.
- HA's success test, three times, verbatim (`phoenix_intrusion_evidence.yaml:325-327`, `:347-349`, `:359-361`):
  `{{ not (page_result is mapping and page_result is not none and (page_result.get('status') | int(0)) < 400 and (page_result.get('content') | default({}, true)).get('ok')) }}`
  i.e. success requires **HTTP < 400 AND `content.ok`**. `/webhook/ha/security-alert` returns HTTP 200 with `ok:false` on any send failure (`main.py:8669-8679`) — the two axes are independent, and only `ok` carries the failure.
- Consequence: the wife's copy succeeding and the owner's being refused is reported to HA as a total failure. There is no `partial` state anywhere in the response.

**Fix.** Return per-recipient state and make `ok` mean "every intended recipient accepted", with an explicit `partial` boolean. Then let HA retry only the failed recipients (pass a `recipients` filter in the retry payload), or drop the retry to a notification-only failure path so a delivered page is not re-sent.

---

## 3. `stop` INSIDE THE RETRY LOOP KILLS EVERY RETRY AFTER THE FIRST AND MAKES "SECURITY PAGE FAILED" UNREACHABLE
**SEVERITY: CRITICAL — this is the defect that explains the silence**

**Claim.** The retry loop's failure branch uses `stop:`, and in Home Assistant `stop` ends the **whole script run**, not the loop iteration. Therefore: attempt 1 fails → attempt 2 (12 s later) fails → the script terminates. Attempts 3, 4 and 5 never run, and the fail-loud block at lines 356-380 — the persistent notification and the logbook "PAGE FAILED" line — is **dead code**. A failed page is not merely quiet, it is structurally unreportable.

**Proof.**
- The branch, verbatim (`phoenix_intrusion_evidence.yaml:344-351`):
  ```
  - if:
      - condition: template
        value_template: >-
          {{ not (page_result is mapping and ... .get('content') ... .get('ok')) }}
    then:
      - stop: "page not confirmed - retrying"
  ```
- Home Assistant, Stop building block, current docs, *Good to know*: **"Stop ends the whole run, not only the current building block. Inside Run in parallel, the other actions that already started still finish. … To only stop the steps that follow in the current sequence when something is not true, use a Condition building block instead."** — https://www.home-assistant.io/building-blocks/stop/
- The 2022 behaviour where `stop` inside a nested sequence leaked and the script continued was the bug in [home-assistant/core#70999](https://github.com/home-assistant/core/issues/70999), fixed by PR #71195 in 2022.5. The deployed host is `2025.10.3` (measured), so the whole-run semantics apply.
- The loop comment says the opposite of what the code does (`:319-321` "Retry up to 4 more times, 12 s apart, stopping the moment the page is confirmed"), and `attempts` is therefore never above 1.
- Live corroboration that the fail-loud block has never executed: `GET /api/states/persistent_notification.phoenix_intrusion_paging_failed` → **HTTP 404 `{"message":"Entity not found."}`**. A created persistent notification becomes an entity; there has never been one.

**Fix.** There is no loop-break in HA, so condition the repetition instead of stopping it — and reset the attempt state inside the loop, not before it:
```yaml
- variables:
    page_ok: >-
      {{ page_result is mapping and page_result is not none
         and (page_result.get('status') | int(0)) < 400
         and (page_result.get('content') | default({}, true)).get('ok') }}
    attempts: 1
- repeat:
    while:
      - condition: template
        value_template: "{{ not page_ok and attempts < 5 }}"
    sequence:
      - delay: {seconds: 12}
      - service: rest_command.phoenix_security_page
        continue_on_error: true
        response_variable: page_result
        data: {event: "{{ page_event }}", detail: "{{ page_detail }}", snapshots: "{{ snapshot_urls }}"}
      - variables:
          attempts: "{{ attempts + 1 }}"
          page_ok: >-
            {{ page_result is mapping and page_result is not none
               and (page_result.get('status') | int(0)) < 400
               and (page_result.get('content') | default({}, true)).get('ok') }}
```
Then the existing `if: not page_ok` block becomes reachable, and `attempts` in its message is finally true.

---

## 4. DUPLICATE-SEND RISK: retries cannot re-deliver, but a *changing body* can double-send
**SEVERITY: HIGH**

**Claim.** The question "if the SMS went out but the HTTP response was lost, does HA re-send?" has three answers, and only the first is the one the code intends:
1. **No, not within 30 minutes** — the identical body is refused by the duplicate guard.
2. **Yes, if the body differs** — the body embeds the media-error sentence, which can differ between attempts, and that is the one real duplicate path.
3. **Yes-looking, but recorded as failure** — a delivered page that could not be confirmed is written to the ledger as suppressed/failed, so the record is wrong even when the SMS arrived.

**Proof — HA side (the retry that fires on `content.ok` false):** `phoenix_intrusion_evidence.yaml:322-343`; payload is byte-identical each pass (`event`, `detail`, `snapshots` are unchanged variables), so the retry text is identical except for the media sentence inside it (`main.py:8649`).
**Proof — server side (the guard that stops it):** `app/sms_service.py:873-901`
```
SELECT COUNT(*) FROM sms_log
 WHERE direction='outbound' AND to_number=?
   AND created_at > datetime('now','-30 minutes')
   AND body = ?
```
→ returns `ok:false, "Duplicate suppressed: identical message sent to this number within the last 30 minutes"`.
**Proof — the guard is armed by the failure itself:** `_audited_send` (`sms_service.py:540-571`) writes an `sms_log` row for **every** outcome — success, error, kill switch, quota refusal, duplicate suppression. The dedup query has **no status filter**, so attempt 1's own failed row is what blocks attempt 2. A transient Twilio error therefore creates a 30-minute dead zone for that exact body.
**Proof — the duplicate path:** the body is built at `main.py:8599-8651`; line 8649 appends `📷 No picture attached — {media_error}`, and `media_error` is a different string per failure mode (`prepare_security_alert_media` returns "no snapshot was supplied…", "media time budget exceeded…", "HA snapshot fetch returned HTTP 404", "rehosted media url did not return an image…"). Two attempts with two different media failures produce two different bodies → **no dedup** → a recipient who already got page A gets page B.
**How many pages one intrusion can produce:** with the `stop` bug, **at most 2 per recipient** (attempt 1 + one retry). With finding 3 fixed and the body unchanged, **1** (dedup holds). With finding 3 fixed and the media outcome changing each pass, **up to 5 per recipient** (one per distinct body). So the bug in finding 3 is currently the only thing bounding the storm — fix it alone and the duplicate risk rises.

**Fix.** Give the security path a real idempotency key rather than a body hash: an `event_id` minted by HA (the `stamp` variable already exists, `:123`) plus the recipient, stored in a small table with a `sent` flag; treat a repeat of the same `(event_id, recipient)` as **success** ("already delivered"), never as a failure. Exclude `event_id`-tagged security pages from the 30-minute body dedup so a genuine retry is not swallowed.

---

## 5. THE OWNER'S COPY SITS BEHIND "ONE TEXT AT A TIME" AND A DAILY QUOTA; THE WIFE'S COPY DOES NOT
**SEVERITY: CRITICAL**

**Claim.** `send_security_alert_mms` passes `bypass_owner_kill_switch=True`, and that bypasses **only** the kill-switch file marker. It does not pass `interrupt=True` and it does not lift the daily quota, so an intrusion page to the owner is judged as an ordinary autonomous `send_message` at urgency `normal` and can be refused for four different reasons. The wife's number is not owner-recognised, so her copy is subject to none of them — the page can reach the wife and be refused for the owner, which HA then reports as a total failure.

**Proof.**
- Only the kill switch is bypassed: `sms_service.py:1072` `if owner_sms_kill_switch_active() and not bypass_owner_kill_switch:` — the flag appears nowhere else in the owner branch.
- The gate is called with the generic defaults (`sms_service.py:1101-1115`): `reason="send_message"`, `urgency="normal"`, `direct_request=is_owner_direct_request()` (false for a webhook), **`interrupt` not passed** (defaults `False`, `owner_text.py:1367`).
- Refusal 1 — open turn: `owner_text.py:1453-1479` refuses with code `awaiting_reply` when an unanswered owner turn is younger than the reply window (`DEFAULT_REPLY_WINDOW_HOURS = 12.0` for a message containing a question; `DEFAULT_NO_QUESTION_GRACE_MINUTES = 45.0` otherwise, `:98-110`). `_supersedes_open_turn` (`:305-337`) lets a message past only if it **outranks** the open turn or `interrupt` is set — and `interrupt` is documented as "the ONE way past an open turn … for a person or the property in immediate danger" (`:1383-1388`). The single case that docstring names is the one caller that does not use it.
- Refusal 2 — length: `owner_text.py:619-624` refuses a body over 320 chars (`DEFAULT_MAX_CHARS = 320`, `:93`). The page body is two lines plus, on a media failure, `📷 No picture attached — <reason>`; the longer and more diagnostic the media failure, the more likely the page is refused outright rather than sent text-only. **The live build has already fixed this one**: `send_message` fits the body at a sentence boundary with a cut marker before gating (`/opt/company/app/sms_service.py:1546-1567`, `fit_for_transport`), and its ceiling is `DEFAULT_MAX_CHARS = 400` (`owner_text.py:262`). So on the running host, length trims instead of silencing; on the audited checkout it silences.
- Refusal 3 — multi-ask: `owner_text.py:630-636` refuses at 2 question marks. `verify_public_media_url`'s error string itself contains one (`sms_service.py:1753-1755`, "…is /webhook/ha/security-media/* reachable from outside?").
- Refusal 4 — daily quota: `sms_service.py:1231-1268`, default `owner_sms_daily_quota = 20` (`config.py:1057`; live `.env` sets 20). Only a "direct request" is exempt, via the burst ceiling path at `:1174-1217`.
- Measured scale of the suppressor, `sms_log` since 2026-10-01, `status='suppressed'`: **`turn_awaiting_reply` = 827**, **`too_long` = 911**, other = 153. The gate is not theoretical; it fires dozens of times a day against ordinary traffic and a security page has no exemption.

**Live-build delta, read line by line — this is what has and has not changed on the running host.**
- The live `send_security_alert_mms` does now pass a context: `owner_text_context={"subsystem": "security_alert_mms", "urgency": "urgent"}` (`/opt/company/app/sms_service.py:2986-3009`). **It does not reach the turn gate.** That gate is called from inside `send_message` with hard-coded defaults — `reason="send_message", urgency="normal"` (`:1566-1570`) — and the context is consumed by the relay path instead. So a page still arrives at `owner_text.gate` labelled `normal`.
- And `urgent` would not have helped: the live `_supersedes_open_turn` (`owner_text.py:589-620`) still excludes it — "`urgent` does NOT [interrupt], and that single omission is what stops a sender from promoting itself past the queue on the strength of its own name", with only `critical`/`stuck` and an explicit `interrupt=True` interrupting. A page labelled `urgent` inside the machine/owner band therefore still loses to an open money question.
- Unchanged and still biting: the open-turn refusal (`awaiting_reply`, window 12 h / 45 min grace) and the daily quota (20/day, direct requests only). Fixed live: the length refusal.
- Net on the running host: a real intrusion page can still be refused as `awaiting_reply` or by the daily quota, and the wife's copy still cannot.

**Fix.** Four lines in the security path, none of them optional — and note the first is the one the live build *looks* like it already made but did not:
- in `send_message`, let `owner_text_context` (or an explicit `urgency`/`reason` pair) reach `_owner_text.gate(...)` instead of the hard-coded `reason="send_message", urgency="normal"`; the live build already carries `urgency: "urgent"` and `subsystem: "security_alert_mms"` for the relay and stops short of the gate — finish the wire;
- `send_security_alert_mms` → pass `interrupt=True` through to that gate, because an intrusion is exactly the "person or property in immediate danger" the gate already reserves a bypass for;
- use `reason="security_intrusion"` so the message lands in the obligation band — `_OBLIGATION_REASON_MARKERS` already contains `"security"`, `"intrusion"`, `"alarm"` (`owner_text.py:211-214`), so the band exists and only the label is missing;
- exempt it from the daily quota with the same deliberate bypass as the kill switch.

---

## 6. THE PICTURE DOES TRAVEL — five named ways it silently does not, one of them admitting nothing
**SEVERITY: LOW (the path is sound; the last hop is unverified)**

**Claim.** The bare filename HA sends is resolved to a LAN/Tailscale URL by the secretary, fetched, rehosted under a 256-bit token, verified unauthenticated, and only then attached. Both network hops were measured working tonight from the authority. Every failure mode except Twilio's own fetch is spelled out in the SMS body.

**Proof — the chain, link by link.**
| Step | Where | Shape |
|---|---|---|
| HA confirms files on disk | `phoenix_intrusion_evidence.yaml:59-60`, `:251-256` | `bash -c 'for f in …; do [ -s "$f" ] && echo "PHOENIX_EVIDENCE_OK $f"; done'` |
| bare filename list | `:276-281` `snapshot_urls: {{ confirmed_files | map('regex_replace','^.*/','') }}` | `intrusion_20261026_181635_123456_doorbell.jpg` |
| payload | `:317`, `:343`; `phoenix_security.yaml:291` | `"snapshots": {{ snapshots \| default([], true) \| tojson }}` |
| name → URL | `sms_service.py:1608-1638` | `{HA_URL}/local/snapshots/{quote(name)}` |
| fetch | `:1641-1707` | 2xx **and** `content-type: image/*` required |
| store | `:1772-1826` | `secrets.token_urlsafe(32)` → `data/security_media/<token>.jpg` |
| verify as Twilio would | `:1709-1769` | unauthenticated GET, must be 2xx image with bytes |
| attach only if verified | `main.py:8660-8667` | `media_url=media_url if media_ok else None` |

- Measured, from the authority, this session — the exact URL the code builds for `HA_URL=http://zabz-tech.tail93e6e6.ts.net:8123`:
  `GET /local/snapshots/latest_intrusion_control_room_interior.jpg` → **200, `image/jpeg`, 298,175 bytes**.
- Measured, from the public internet on ZABZ-TECH: `GET https://ai.abletelsolutions.com/webhook/ha/security-media/<random 43-char>.jpg` → **404** — i.e. the rehost route is reachable through Cloudflare and is *not* behind Access, which is the trap the yaml comments describe for `ha.abletelsolutions.com`.
- `data/security_media` under the **live** working directory (`/opt/company/data/security_media`) **does not exist** — it is created on the first store (`sms_service.py:1791`) — so not one picture has ever been stored by this path on the running host.

**Paths to text-only, and whether the SMS admits it** (`main.py:8649` appends the reason; no reason line means the reader is told nothing):
1. `snapshots` empty → body says "no snapshot was supplied by Home Assistant" — **admits**.
2. no `PUBLIC_BASE_URL` → "no public base URL is configured" — **admits** (not hit: `PUBLIC_BASE_URL=https://ai.abletelsolutions.com` is set).
3. HA fetch non-2xx / not an image / empty → "HA snapshot fetch returned HTTP N" — **admits**.
4. store raised → "could not store the intruder picture" — **admits**.
5. rehosted URL fails verification → "rehosted media url did not return an image … is /webhook/ha/security-media/* reachable from outside?" — **admits**.
6. **Twilio accepts the MMS and then fails to fetch the media**: Twilio downgrades to text-only, `media_ok` was true so no reason line is appended — **admits nothing**. This is the only silent path, and it is the one the docstring at `main.py:8561-8564` correctly identifies but the code cannot observe.

**Fix.** Nothing structural. Close path 6 by reading the message's own status/subresource after send and recording whether the media was fetched; and if the media budget (`SECURITY_MEDIA_DEFAULT_TOTAL_TIMEOUT_SEC = 12.0`) is exhausted, page first and attach on a second pass rather than spending 12 s before the alarm.

---

## 7. FAILURE VISIBILITY — a human sees nothing, no phone is touched, and nothing durable records it
**SEVERITY: CRITICAL**

**Claim.** If every attempt fails, the only two intended surfaces are the `persistent_notification` and the `logbook.log` inside the block that finding 3 makes unreachable. So a failure produces: no HA notification, no logbook line, no SMS, no call, no email, and — when the failure is a transport failure — **no record anywhere at all**.

**Proof.**
- The two surfaces: `phoenix_intrusion_evidence.yaml:363-380` (`persistent_notification.create` with `notification_id: phoenix_intrusion_paging_failed`, and `logbook.log` "PAGE FAILED after N attempt(s) — owner SMS not delivered").
- Measured: `GET /api/states/persistent_notification.phoenix_intrusion_paging_failed` → **404, `{"message":"Entity not found."}`** (twice, same result). The notification has never been created.
- Nothing outbound exists on the failure path, by explicit design — the yaml says so at `:353-355`: *"Nothing here is outbound: no SMS, no email, no second channel — only HA-local surfaces."* That sentence is the defect written down as a principle: the alarm when the alarm fails is a dashboard tile nobody is looking at at 3 a.m.
- Server side, per attempt: a `logger.warning` (`main.py:8642-8648` for text-only media; `sms_service.py:1101-1131` logs the gate refusal) and an `sms_log` row with `status='suppressed'` or `'failed'` (`sms_service.py:460-479`). Nothing watches those rows — measured: `error_log` holds no `security-alert`/`security_alert` entry, `operation_journal` none.
- A transport failure (the case the loop was written for — `:287-298` documents two such dead alarms on 2026-09-15/16 with `ECONNREFUSED` and HTTP 500) writes **no row anywhere**: the request never reaches `send_message`, so `_audited_send` never runs.

**Fix.** The fail branch must be reachable (finding 3) **and** must carry an independent channel: a Twilio **voice call** to the roster, or the same SMS through a second provider, plus one unconditional durable row (`intrusion_paging_failed` event on the authority) written whenever `page_ok` is false. A local notification may remain, but it cannot be the only surface.

---

## 8. THE PUBLIC MEDIA ENDPOINT — unauthenticated by design, unguessable, 7-day expiry
**SEVERITY: MEDIUM**

**Claim.** `/webhook/ha/security-media/<token>.jpg` requires no authentication (Twilio has no credentials), the token is 256 bits and not derived from anything guessable, it expires after 7 days, and what leaks if found is a photograph of the inside of the house. No filename, LAN address or HA token leaks.

**Proof.**
- Route and its deliberate lack of auth: `main.py:8742-8762`; `Cache-Control: no-store` at `:8761`.
- Token: `secrets.token_urlsafe(32)` (`sms_service.py:1793`) = 32 bytes of entropy, 43 URL-safe chars; validated against `^[A-Za-z0-9_-]{20,128}$` before any filesystem access (`:1573`, `:1926-1932`) — traversal-proof, not a file-read primitive.
- Expiry: `SECURITY_MEDIA_DEFAULT_RETENTION_SEC = 604800` (7 days, `:1566`), enforced at read (`:1945`) and pruned on every store (`:1814`, `prune_security_media_store`, 256 MiB budget).
- Measured reachability from the public internet: 404 for an unknown token → the route is internet-facing on the API host, not Access-gated.
- What leaks to a holder: the JPEG (`home_assistant/logbook` shows the doorbell and interior cameras are the evidence set, `:125-133`), for up to 7 days, with no login. The URL also travels in the Twilio API request and is retained in Twilio's message record.

**Fix.** A page is read in minutes: cut retention to hours, or delete the file on first successful fetch (single-use). Do not return `media_url` in the webhook response body, which is the only place it is currently published beyond Twilio.

---

## 9. HA → SECRETARY: the assumptions, and what the failure costs
**SEVERITY: MEDIUM**

**Claim.** The path depends on four things being true at once, all of which are true tonight and all of which fail silently: DNS/Cloudflare → tunnel → API; the scoped key matching; the reverse fetch over Tailscale; and the handler finishing inside HA's 15 s timeout. When the forward path fails, HA's retry loop bounds the total delay at roughly 27 s **by accident**, and pays for it with finding 3.

**Proof.**
- (a) Forward path: measured `cloudflared.service active running`, `company-api.service active running`, `127.0.0.1:8002` listening, `/health` 200, and two real deliveries logged in the API journal: `Oct 26 18:16:04 … "POST /webhook/ha/security-alert HTTP/1.1" 200 OK` and `Oct 26 18:16:40 … 200 OK`.
- (b) The key matches: 200 rather than 401 proves HA's `!secret secretary_security_api_key` equals the server's `HA_SECURITY_API_KEY` (present, len 44, value not read). If that key were absent the server would fall back to the dashboard key (`config.py:1816-1821`) — which the config comment says HA must never hold.
- (c) Reverse path: the API fetches from `HA_URL=http://zabz-tech.tail93e6e6.ts.net:8123` (Tailscale MagicDNS, port 8123). Measured from the authority: `/` → 200 in 58 ms; a snapshot → 200 `image/jpeg`. Note that name is **not** the machine this audit runs on — `127.0.0.1:8123` is closed on ZABZ-TECH — so it is a distinct tailnet endpoint whose name must stay accurate.
- (d) Timeout race: `rest_command` sets `timeout: 15` (`phoenix_security.yaml:292`), while the handler can legitimately spend `SECURITY_MEDIA_DEFAULT_TOTAL_TIMEOUT_SEC = 12.0` in the media loop, plus 5 s per verify (`:1564-1565`), plus up to **3** Twilio attempts per recipient with 1 s + 2 s backoff (`sms_service.py:750-813`, `max_retries=3` at `:952`) for two recipients, run sequentially at `:2166-2173`. A page that takes >15 s is recorded by HA as a transport failure **after** it was sent — and then finding 4 refuses the retry as a duplicate, so it can never be confirmed.
- When the forward path is down: `continue_on_error: true` (`:312`, `:338`) swallows the transport error, `page_result` keeps `{}`, the condition is true, one retry fires 12 s later (`:335-336`), and finding 3 ends the script. **Total added delay ≈ 12 s + up to 15 s of timeout ≈ 27 s.** So no — the loop does not meaningfully bound delay; it bounds it at two attempts and, in exchange, throws away attempts 3-5 and the alarm.

**Fix.** `timeout: 45` on the rest_command; the `while`-conditioned loop from finding 3; send to recipients in parallel or shrink the Twilio retry for this path; and add a second transport (a direct `http://zabz-tech.tail93e6e6.ts.net:8002` POST, tried when the public host fails) so one Cloudflare or DNS fault cannot remove the only route.

---

## 10. Context: what the live deployment is actually doing (so the next session does not re-derive it)
**SEVERITY: informational**

- HA is `2025.10.3` (`/api/config`), the version the package comments cite — so the `stop` semantics in finding 3 apply without qualification.
- The deployed evidence script **passes step 5**: today's two runs reached the webhook at 18:16:04 and 18:16:40. A step-5 `FileNotFoundError: 'for'` abort (documented as fixed in the repo at `:48-58`) would have prevented that, so the `bash -c` fix is live — as is, by the same reasoning, the pruning sibling it shares a defect class with.
- Both runs were **drills and were correctly skipped**: HTTP 200 with `{"ok": true, "paged": false}` and no `sms_log` row, no media work. So the deployed `phoenix_security.yaml` honours `intrusion_test` (`:213`), and the W195 warning that "phoenix_test_intrusion_sequence pages all three recipients for real" is now obsolete.
- Consequence for the headline: since the step-5 fix, **no real page has been attempted on this host**. `/opt/company/data/security_media` does not exist (no picture ever stored) and `sms_log` holds **zero** `LPT-SECURITY` rows lifetime (`SELECT COUNT(*) … WHERE body LIKE '%LPT-SECURITY%'` → 0). Tonight's evidence proves the pipes are connected; it does not prove the page. Findings 3, 4, 5 and 7 are the reason the first real one will still not arrive.
- Two stray facts worth keeping: `OWNER_PHONE_NUMBER` and `OWNER_NOTIFY_NUMBER` are now the same number, so the monitored-inbox repoint is inert; and `MOCK_OUTBOUND_COMMS` is absent on the authority, so nothing is being shadow-sent.

---

## WHAT I COULD NOT VERIFY

1. **No end-to-end page.** I did not call the webhook with a real event, as instructed, so I have not observed: the SMS arriving, the MMS media being fetched **by Twilio**, the retry path executing, or the fail-loud branch executing. Findings 3, 4, 5 and 7 are code-and-documentation findings plus two live 404s, not a captured failure.
2. **Twilio's own media fetch.** Everything up to `media_url` verification is proven; whether Twilio then retrieves the JPEG is unmeasured, and it is the one silent path (finding 6, path 6).
3. **Secret values.** Never read. I know `HA_SECURITY_API_KEY` is set and 44 chars and that HA's header matched (200, not 401); I do not know which value HA holds, and `secrets.yaml` is not in the repo — it exists only on the HA host.
4. **The HA host's files.** No file access to the HA host. Deployment state is inferred from behaviour (the 200s, the skipped drill, the version) — strong, but indirect. I could not read the deployed YAML to diff it against the repo.
5. **Build equivalence.** The live build is not the audited checkout (23,410 lines vs 22,778, hashes differ). I verified the constructs this report rests on, by grep and by reading the live regions around `send_message`'s gate, `_supersedes_open_turn` and `send_security_alert_mms` — but I did not read 652 lines of delta, so a live-only change elsewhere on this path would not have been seen. Findings 3, 4 and 7 are HA-side and unaffected by that delta.
6. **The full history of missed pages.** HA's `/api/error_log` is only 9,872 bytes, so older episodes are gone. The "6 intrusion episodes on 2026-10-24..26, 0 SMS" figure is from the repo comment (`:57`), not from my own read of a log.
7. **What `zabz-tech.tail93e6e6.ts.net:8123` is.** It answers as Home Assistant, but `127.0.0.1:8123` is closed on ZABZ-TECH, so the node behind that name is not the machine I audit from. Which box actually serves HA, and whether the name survives a re-image or a Tailscale re-registration, is unresolved.
8. **The roster decision.** Whether the mother belongs on the page is the owner's call (`D240` says yes, tonight's `.env` says no). I have not changed anything; the queue row is his.
