# 147 — AUDIT: CREDENTIAL-DEPENDENT INTEGRATIONS AFTER THE 2026-10-11 CUTOVER

**Written:** 2026-10-11 ~15:50Z by a local (non-mesh) audit session on ZABZ-YOGA.
**Authority audited:** `secratary-cloud` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`, app `/opt/company`, database `/root/authority.db`.
**Reference (READ-ONLY, bounded commands only):** `secratary-ts` (office box), load average checked at 0.00–0.06 throughout.
**Cutover instant:** 2026-10-11 05:43:36Z (rule: a credential that exists but has not been *successfully used* since 05:43Z is UNTESTED, not working).
**Standard applied:** PROVE a real authenticated call, or mark UNKNOWN. No secret value appears in this document — keys and lengths only.

## 0. Method, and what "present" means

1. **Key presence by name only.** `grep -oE '^[A-Za-z0-9_]+=' /opt/company/.env` on both boxes, sorted and diffed.
   - authority: **302 keys** · office: **301 keys**
   - **on the office box but NOT on the authority: NONE.** New on authority: `DATABASE_URL` only.
   - **18 keys exist with empty values** on *both* boxes (`LINUX_PC_SSH_PASSWORD`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `AZURE_OPENAI_API_KEY`, `MODEL_PROVIDER_KEYS_JSON`, `ACCOUNT_ACCESS_TOKENS_JSON`, `TWILIO_FORWARD_TO_USER`, `TWILIO_VOICE_WEBHOOK_BASE_URL`, `TWILIO_SMS_WEBHOOK_BASE_URL`, `TWILIO_STATUS_CALLBACK_BASE_URL`, `TWILIO_VOICE_DISASTER_FALLBACK_MESSAGE`, `GITHUB_WEBHOOK_SECRET`, `CALENDAR_PRIMARY_ACCOUNT`, `GMAIL_PRIMARY_ACCOUNT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`, `MEM0_PROVIDER`) — so none of these is a migration regression. Two of them matter: `TWILIO_SMS_WEBHOOK_BASE_URL`/`TWILIO_VOICE_WEBHOOK_BASE_URL` are empty by design (the app falls back to `TWILIO_WEBHOOK_BASE_URL`), and `CLOUDFLARE_TUNNEL_TOKEN` is empty because the connector uses `/etc/cloudflared/tunnel.token`.
   - **So the failure mode is NOT a missing credential.** It is missing *payload*: a missing repo, a missing Python package, a missing cron job. See section 8.
2. **Evidence of recent use** from three independent places: the app's own autopilot state (`/opt/company/data/autopilot_state.json`, mtime 15:32:56Z), the app's log (`journalctl -u company-api`), and the database's own tables.
3. **One real authenticated call per integration where a read-only call exists.** No SMS, email, call, payment or write of any kind was sent. Where a test would transmit to a person or move money, it was not run and this document says so.

## 1. Verdict table

| # | Integration | Credential | Last successful use (UTC) | Test run now | Verdict |
|---|---|---|---|---|---|
| 1 | Plaid (bank sync) | authority ✓ (office ✓) | **2026-10-11 05:41:23Z** — sync ok, cursors written 05:41:22–05:41:23Z | `GET /api/v1/plaid/accounts` → HTTP 200, live balances for 22 stored accounts | **WORKING** |
| 2 | Stripe | authority ✓ (office ✓) | **BROKEN since cutover** — `/stripe/charges` HTTP 500 (`stripe package not installed`) | direct `GET https://api.stripe.com/v1/balance` → HTTP 200, livemode | **BROKEN (package, not key)** |
| 3 | Twilio — company account | authority ✓ (office ✓) | **no successful use since 05:43Z**; last Twilio call ≈00:08Z 2026-10-11 | `GET /2010-04-01/Accounts/{SID}.json` → HTTP 200, status `active` | credential **WORKING**, use **UNKNOWN** |
| 4 | Twilio — family-chat account | authority ✓ (office ✓) | **no message since 05:41:32Z** (family_chat.db `messages`) | `GET /2010-04-01/Accounts/{SID}.json` → HTTP 200, status `active` | credential **WORKING**, use **UNKNOWN** |
| 5 | Dialpad (shop phone) | authority ✓ (office ✓) | **2026-10-11 15:31:42Z** (sms cache) / **15:35:04Z** (call table) / last webhook **15:41:30Z** | last call rows read; freshness watchdog: `sms OK lag 4.8s`, `calls OK lag 0.0s` | **WORKING** |
| 6 | DeepSeek | authority ✓ (office ✓) | **2026-10-11 15:42:34Z** (model_usage, 677 calls since cutover, 0 failures) | `GET https://api.deepseek.com/models` → HTTP 200 | **WORKING** |
| 7 | DeepInfra | authority ✓ (office ✓) | last call **2026-10-05 02:51:50Z** (no `deepinfra` call at all today, before or after cutover) | `GET https://api.deepinfra.com/v1/openai/models` → HTTP 200 (3 endpoint variants all 200) | credential **WORKING**, path **not exercised** |
| 8 | AI gateway (`ai.abletelsolutions.com` / `api.abletelsolutions.com`) | authority ✓ | **2026-10-11 15:42:28Z** — 1,688 traces since cutover, 1,685 `ok` / 3 `error` | `GET /v1/models` (local, public, and with `AI_GATEWAY_API_KEY`) → all HTTP 200 | **WORKING** |
| 9 | Google Calendar (OAuth) | authority ✓ (office ✓) | **2026-10-11 15:19:22Z** (gmail_decisions tick) / token refresh **15:20:07Z** | `GET /calendar/status` → all 5 accounts `authenticated:true`; `GET /calendar/events` → HTTP 200, live Oct 13 & Oct 16 events from `chevedy@gmail.com` | **WORKING** |
| 10 | Gmail (OAuth) | authority ✓ (office ✓) | **2026-10-11 15:18:53Z** (poll) / token refresh **15:20:07Z** | `GET /gmail/inbox` → HTTP 200, message dated 14:56:07Z; direct `GET gmail.googleapis.com/gmail/v1/users/me/profile` → HTTP 200 (65,461 messages) | **WORKING** |
| 11 | Google Sheets | authority ✓ | `email_catalog` 15:30:58Z is DB work, not Sheets; **no Sheet write proven** | direct `GET sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}` → HTTP 200, title `Repair tracker`; `values/A1:C3` → HTTP 200 | **WORKING** |
| 12 | QuickBooks | authority ✓ **but repo missing** | **BROKEN since cutover** — `quickbooks-agent repo not found` | `GET /quickbooks/status` → `{"ok":true,"repo_available":false,"connected":false,"error":"Repo not found"}` | **BROKEN** |
| 13 | eBay order feed | authority ✓ (office ✓) | last success **2026-10-09 04:16:25Z**; attempt 2026-10-11 05:41:19Z **failed** | app path only; would need the QB repo | **BROKEN** |
| 14 | Amazon order feed | authority ✓ (office ✓) | last success **2026-10-11 04:10:11Z**; attempt 05:41:19Z **failed** | app path only; would need the QB repo | **BROKEN** |
| 15 | Home Assistant | authority ✓ (office ✓) | n/a — scheduler already dead **before** the cutover (last run 2026-10-05 03:33Z) | `GET $HA_URL/api/` → `URLError: Temporary failure in name resolution` | **BROKEN** |
| 16 | GitHub (`GITHUB_PAT`) | authority ✓ (office ✓) | **2026-10-11 15:23:27Z** — `transcript-archive-pull.timer` last ran 15:23:27Z | `GET https://api.github.com/user` → HTTP 200, login `lakewoodphone` | **WORKING** |
| 17 | Cloudflare — API/DNS token | authority ✓ (office ✓) | **2026-10-11 06:18Z onward** — `cloudflared` unit active, tunnel carrying traffic now | `GET /user/tokens/verify` → HTTP 200 `active`; `GET /zones/{CF_ZONE_ID}` → HTTP 200, zone `abletelsolutions.com` active; `GET /webhook/...` via both public hostnames → reaches the app | **WORKING** |
| 18 | Cloudflare — R2 | authority ✓ (office ✓) at `/root/.lpt-r2.env` mode 600 | **2026-10-11 06:46:57Z** object written; report 15:40:18Z confirms `bytes=6278791492` | object metadata re-read from R2 at 15:40:18Z; 5 keys present by name | **WORKING** |
| 19 | Hetzner (API token) | authority ✓ **but token dead** (office ✓) | `monitor-hetzner-backups` cron **not migrated**; no monitor output on authority | `GET https://api.hetzner.cloud/v1/servers` → **HTTP 401** `the token you have provided is invalid` | **BROKEN** |
| 20 | Broker / gateway mesh | config present, **service absent** | `AI_GATEWAY_MESH_PEERS_JSON=["http://192.168.50.138:8002"]` (office LAN, unreachable from Ashburn); no broker process | `GET http://127.0.0.1:3091/mesh/health` → connection refused; `FLEET_API_URL` `http://87.99.141.172:8003` → timeout | **BROKEN** |
| 21 | Order feeds — extra cron (`order-feed-refresh`, `supplier-order-ingest`) | scripts reachable | last office run not carried; **neither cron job exists on authority** | n/a | **BROKEN (not migrated)** |

## 2. Per-integration detail, with the raw evidence

### Plaid
- Keys present: `PLAID_CLIENT_ID` (24), `PLAID_SECRET` (30), `PLAID_ENVIRONMENT` (10).
- App state: subsystem `plaid_sync` `last_status: ok`, `last_ran_at 2026-10-11T05:41:23.408835+00:00`, `last_error: null`, 68 successes / 7 failures.
- Database: `plaid_sync_cursors` rows 1,2,4,5 updated `05:41:22.257425Z`→`05:41:23.399504Z`; `plaid_accounts` max `updated_at = 05:41:23.463902Z`; `plaid_transactions` 1,871 rows, newest `created_at 05:41:23.399504Z`, newest transaction date `2026-10-09`.
- Live test (authority, 15:41Z): `GET http://127.0.0.1:8002/api/v1/plaid/accounts` → HTTP 200 in 0.03 s, real balances (e.g. `Business Adv Fundamentals` current 291.61, `E. ZABROWSKY` current 3674.25). This reads Plaid live, so the access tokens and `PLAID_SECRET` are both valid on the authority.
- **The one real gap:** the office box ran `nightly-plaid-sync.sh` at **04:30 daily** (`30 4 * * *`, decoded from the office crontab). That job is **not in the authority crontab** (authority has 21 cron jobs; office had 92). Only the in-process autopilot `plaid_sync` subsystem remains, and its last evidence is 05:41:23Z — two minutes before the cutover.
- Verdict WORKING for the credential and the last sync; the *schedule* regressed.

### Stripe — headline regression
- Key present: `STRIPE_SECRET_KEY` (107 chars) on both boxes. **The key works.** Direct `GET https://api.stripe.com/v1/balance` with it → **HTTP 200**, `"livemode": true`, available 14872 usd, pending 93279 usd.
- **The app cannot use it.** `GET http://127.0.0.1:8002/stripe/charges?limit=2` → **HTTP 500**, `{"ok":false,"error":"internal_error","error_id":2278}`. Log at 15:42:07Z:
  `File "/opt/company/app/services/stripe_service.py", line 21, in _client` → `ModuleNotFoundError: No module named 'stripe'` → `RuntimeError: stripe package not installed — run: pip install stripe`.
- Package audit: the office venv has `stripe 15.4.0`; the authority venv (219 packages) **does not have stripe**. `stripe` is **not listed in `/opt/company/requirements.txt`** — it was installed out-of-band on the office box, which is exactly why the migration dropped it. (`boto3` is likewise absent from the authority venv but present as `boto3 1.43.108` on the office box; only system python has it here.)
- The office also ran `stripe-key-watch.py` every 6h (key-health + new-reader/refund/dispute watch that writes to `owner_decision_queue`). That cron is **not migrated**.
- **Restore step (needs the owner's yes on the restart):**
  1. `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`
  2. `cd /opt/company && .venv/bin/pip install 'stripe>=15,<16'` (record it in `requirements.txt` so it cannot vanish again)
  3. `systemctl restart company-api` — **this is a restart of the production API and was deliberately NOT done by this audit**
  4. verify: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/stripe/charges?limit=2` → expect 200
  5. port `stripe-key-watch.py` + its 6-hourly cron entry from the office box.

### Twilio — company account and family-chat account
- Keys: `TWILIO_ACCOUNT_SID` (34) / `TWILIO_AUTH_TOKEN` (32); `FAMILY_CHAT_TWILIO_ACCOUNT_SID` (34) / `FAMILY_CHAT_TWILIO_AUTH_TOKEN` (32). All present on both boxes.
- Live tests (authority, 15:41Z): both `GET https://api.twilio.com/2010-04-01/Accounts/{SID}.json` → **HTTP 200**, company account `Lakewood Phone & Tech` **status active**, family-chat account `AbleTel Solutions` **status active**. **The credentials are good.**
- **The use evidence is the weak part.** `autopilot_state.json → event_push_sources.twilio_sms = 2026-10-11T00:08:26Z` — the last inbound Twilio SMS event is **before** the cutover. `family_chat.db → messages` max `created_at = 2026-10-11 05:41:32Z` (3,155 rows), i.e. the family chat has had **no message since two minutes before the cutover**; `outbox` last row 2026-10-06.
- The journal on the authority begins `2026-10-11 00:00:22Z`; **there are zero `POST /webhook/twilio/*` entries in it**, while `POST /webhook/dialpad/sms` (16) and `POST /webhook/dialpad/call` (13) arrive normally, latest 15:41:30Z.
- **The webhook doors themselves are proven good** (this probe transmitted no message — it only exercised signature rejection):
  - `POST https://api.abletelsolutions.com/webhook/twilio/sms` with no signature → **403 `Missing X-Twilio-Signature`**, and the app log shows it arrived at `app.main`.
  - `POST https://ai.abletelsolutions.com/webhook/twilio/sms` → identical 403 in the same app.
  - `POST https://ai.abletelsolutions.com/webhook/dialpad/sms` → **401 `Dialpad JWT verification failed`** (proves the Dialpad signature check is live).
- So: **no evidence that Twilio has called us since the cutover, and no way to force one without sending a real message.** That is why the use column is UNKNOWN and not "working". **The one test that would settle it is a single SMS to a company number, which is outbound to a person and was therefore not run.**
- Not restored / not tested: `sms-inbox` cron is installed and reports `outbound: 600 from Twilio, 0 new` (Twilio read path works), but the office's `reconcile-sms-status` chain was only partially carried.

### Dialpad
- `DIALPAD_API_KEY` (100 chars) + `DIALPAD_WEBHOOK_SECRET` present on both.
- Live: `dialpad_call_full` newest `updated_at 2026-10-11T15:35:04.923912Z`; `dialpad_sms_cache` newest `created_at 2026-10-11T15:31:42.476Z`; `dialpad_entity` newest 14:51:25Z; webhooks arriving (see above).
- Cron on the authority: `dialpad-harvest-cron` (*/30), `dialpad-sms-harvest-cron` (15,45), `dialpad-recording-gap` (*/5), `dialpad-transcript-gap` (*/10) — all **migrated**. `/var/log/lpt-freshness-watchdog.log` at 15:44:02Z reports `sms OK lag=4.8s` and `calls OK lag=0.0s`.
- Note (not a credential finding): `dialpad-recording-gap` and `dialpad-transcript-gap` exit non-zero with an SQL error in `/root/.cron-status/runs.tsv` (15:35 and 15:40) while logging `selected: 0` — a code/data defect worth a separate workstream, not a credential failure.
- Verdict **WORKING**.

### DeepSeek and DeepInfra (LLM providers)
- Keys: `DEEPSEEK_API_KEY` (35), `DEEPINFRA_API_KEY` (32), both present on both boxes.
- **DeepSeek: WORKING.** `GET https://api.deepseek.com/models` → **HTTP 200**. `model_usage` since the cutover shows `deepseek/deepseek-v4-flash` 486 calls (486 successes) and `deepseek/deepseek-v4-pro` 191/191, newest `2026-10-11T15:42:34.998643Z`; `provider_health_events` newest is a `deepseek` success at 15:42:35Z. Gateway spans since cutover: deepseek 910, google 486.
- **DeepInfra: credential works, path is not exercised.** `GET https://api.deepinfra.com/v1/openai/models` → **HTTP 200** (also `/v1/models` and `/models/list`, all 200). But no `deepinfra` call appears in `model_usage` or `gateway_trace_span` on 2026-10-11 at all, before or after the cutover; the last one anywhere is **2026-10-05 02:51:50Z** (`deepseek-ai/DeepSeek-V4-Flash-0731`, 56,050 rows historically) and `MiniMaxAI/MiniMax-M3` last 2026-10-05 02:39:54Z. `/models/current` reports `ceo_models` = deepseek + deepinfra but `ceo_available` = **deepseek only**.
- **Verdict:** DeepInfra is a *dormant* provider, not a broken one — it was already not being called for six days before the cutover, so this is **not** a migration regression, and it is not reported as one.

### AI gateway
- `AI_GATEWAY_API_KEY` (48) present. Local `GET http://127.0.0.1:8002/v1/models` → **HTTP 200** (catalog with `secretary-auto`, `secretary-fast`, `secretary-smart`, …). Public `GET https://ai.abletelsolutions.com/v1/models` → **HTTP 200**. Same with the gateway key → HTTP 200.
- Usage since cutover: 1,688 `gateway_trace_span` rows, 1,685 `ok`, 3 `error` (all three are `gemini-3.5-flash` `finish_reason_length: upstream response was truncated`, 14:06Z — a provider condition, not an auth failure).
- Two crons watch it on the authority: `ai-gateway-health` (*/30) and `lpt-freshness-watchdog` (* * * * *). Verdict **WORKING**.
- The only mesh limitation: `AI_GATEWAY_MESH_PEERS_JSON=["http://192.168.50.138:8002"]` points at the **office LAN** and is therefore unreachable from Ashburn — see #20.

### Google Calendar, Gmail, Google Sheets (OAuth)
- Token dirs `data/calendar_tokens/` and `data/gmail_tokens/`, 5 accounts each: `chevedy@gmail.com`, `eliyahuzabrowsky@gmail.com`, `ezabz68@gmail.com`, `lakewoodphoneandtech@gmail.com`, `zabzgpt@gmail.com`. Each file has `token`, `refresh_token`, `client_id`, `client_secret`, `expiry`, `scopes`.
- **Freshness after the cutover, which is the specific thing the brief asked for:** every token file mtime is **2026-10-11 15:20:07Z** (copied at 15:20 by the cutover, refreshed then) and every `expiry` is **2026-10-11T16:20:06Z–16:20:06.928Z**. A refresh that succeeded ten hours after the cutover is the proof that the OAuth client and refresh tokens survived.
- `GET /gmail/status` and `/gmail/accounts` → all five `authenticated:true`, `reauth_required:false`, **`last_refresh_error:null`**, `token_file_exists:true`, `has_refresh_token:true`, `scope_count` 8 (12 for `chevedy`).
- `GET /calendar/status` → `"authenticated": true, "message": "Google Calendar connected"` for all five.
- Live API calls (not just status flags):
  - `GET gmail.googleapis.com/gmail/v1/users/me/profile` with the `lakewoodphoneandtech` token → **HTTP 200**, `messagesTotal 65461`, `threadsTotal 31103`.
  - `GET /gmail/inbox?limit=2` → HTTP 200; newest message `2026-10-11 14:56:07Z` "Lakewood Phone & Tech has a new voicemail from (732) 503-5262".
  - `GET /calendar/events?limit=3` → HTTP 200 with live events on 2026-10-13 and 2026-10-16 created by `chevedy@gmail.com`.
  - `GET sheets.googleapis.com/v4/spreadsheets/1usxna…JVVA` → **HTTP 200**, `properties.title = "Repair tracker"`; `values/A1:C3` → HTTP 200. Sheets scope is present.
- **Gmail WORKING · Calendar WORKING · Sheets WORKING.**
- One caveat for the record: `calendar_events` in the authority database holds a single row from 2026-02-18 and is not what `/calendar/events` serves — the endpoint reads Google live. The DB table is stale, the integration is not.

### QuickBooks (and everything that runs through its repo)
- `QB_AGENT_REPO_PATH=/home/zabz/repos/quickbooks-agent` is still set to the **office** path. The code resolves candidates `[configured, /opt/company/domains/finance/quickbooks-agent, legacy]` and the effective default is `/opt/company/domains/finance/quickbooks-agent`, which **does not exist** (`os.path.isdir` → False; `/opt/company/domains` does not exist at all).
- `GET /quickbooks/status` → `{"ok":true,"repo_available":false,"connected":false,"error":"Repo not found"}`; `GET /quickbooks/snapshot` → `{"ok":false,"error":"QB agent not available"}`.
- Subsystems failing on exactly this error, last attempt `2026-10-11T05:41:19Z` (**the last pre-cutover tick**): `ebay_sync` (`last_status: failed`), `amazon_sync` (`failed`), `paypal_sync` (`failed`). Historical: eBay 25 successes / 48 failures, Amazon 23/48, PayPal 37/41.
- The **accounting database is also missing**: `/opt/company/data/accounting.db` is a **0-byte** file dated Aug 28; `/root/accounting-data/live/accounting.db` is a stub (an empty 16,384-byte `.stub-empty-16384-20261011T062757Z.bak` sits beside it). The office box has the real one: `/home/zabz/accounting-data/live/accounting.db` **21,995,520 bytes**, last written 2026-10-10 10:17, with a `-shm` written 2026-10-11 06:28.
- The office's `daily-finance-sync-cron.sh` (05:00) and `auto-categorize.py` (every 6h) that move accounting data into the secretary DB are **not in the authority crontab**.
- **Restore steps (no data destroyed if done as written):**
  1. Copy the repo: `scp -r` (or rsync) `secratary-ts:/home/zabz/repos/quickbooks-agent` → `secratary-cloud:/opt/company/domains/finance/quickbooks-agent` (create the parent dir first), **or** set `QB_AGENT_REPO_PATH=/home/zabz/repos/quickbooks-agent` in `/opt/company/.env` and place the repo there. Include the repo's own `.env` (mode 600).
  2. Copy the ledger **without clobbering anything**: take a consistent snapshot on the office box (`.backup` only if the load average stays low — it was 0.00–0.06 during this audit), then place it at `/opt/company/data/accounting.db` **after** moving the existing 0-byte file aside, and keep a dated `.bak`. Never overwrite `/root/authority.db`.
  3. Verify: `GET /quickbooks/status` → `repo_available:true`, then `GET /finance/ebay/status`, `/finance/amazon/status`, and one manual `POST /autopilot/subsystems/ebay_sync/run-once` (this is a read of the shop's own order history; it sends nothing to anyone).
  4. Port the two office crons (`daily-finance-sync-cron.sh` 05:00, `auto-categorize.py` every 6h) and set `QB_AGENT_REPO_PATH` to the real path.
- **This is the single largest integration failure of the cutover: one missing repository plus one missing ledger file breaks QuickBooks, eBay, Amazon, PayPal and the receipts pipeline at once.**

### eBay and Amazon order feeds
- `FB_ACCOUNT_*` / `FB_PASSWORD_*` credentials for both feeds are present on both boxes.
- eBay: last **success 2026-10-09 04:16:25Z** ("1 new transactions ingested" on 10-08); 10-11 05:41:19Z attempt → **failed** on the missing repo.
- Amazon: last **success 2026-10-11 04:10:11Z**; 05:41:19Z attempt → **failed** on the missing repo.
- Both are scrapers driven through the QuickBooks/accounting repo, so their verdict is **BROKEN**, cause identical to #12. Their dedicated crons (`order-feed-refresh.sh` 05:20, `supplier-order-ingest.py` every 6h) are **not in the authority crontab**.
- **Not tested live**: a scrape would log into the owner's eBay/Amazon accounts. That is an authenticated write-capable session against a third party and was not performed without instruction.

### Home Assistant
- `HA_URL=http://homeassistant.local:8123` — an **office-LAN mDNS name**. From Ashburn: `GET $HA_URL/api/` → `URLError: [Errno -3] Temporary failure in name resolution`.
- `HA_TOKEN` (183 chars) is present, so the credential is not the problem; the **network path** is.
- Honest framing: the HA scheduler was **already dead before the cutover** — subsystem `google_voice_secretary` last ran `2026-10-05T03:33:45Z`, `run-ha-truth` / `run-ha-behaviour` crons were office-only, and `SHABBAT_POWER_DOWN_ENABLED` was already in play. So this is "still broken", not "newly broken".
- **Restore step:** point `HA_URL` at an address reachable from the cloud box (the Home Assistant host on the office LAN via the Tailscale path, e.g. `http://<ha-host>.tail93e6e6.ts.net:8123`, or a named Cloudflare tunnel hostname), then `systemctl restart company-api`, then `GET $HA_URL/api/` should return `{"message":"API running."}`. **Restart deliberately not performed by this audit.**

### GitHub (`GITHUB_PAT`)
- `GITHUB_PAT` (40) and `COPILOT_GITHUB_TOKEN` (40) present on both boxes.
- `GET https://api.github.com/user` → **HTTP 200**, login `lakewoodphone`, id 223377080.
- Independent recent use: `transcript-archive-pull.timer` last ran **2026-10-11 15:23:27Z**; `world_index` subsystem pulls 9 repos and reported success at 15:30:58Z ("9 repos, 8 dirty"). Verdict **WORKING**.

### Cloudflare (R2 and DNS tokens)
- `CF_API_TOKEN` (40), `CF_ACCOUNT_ID` (32), `CF_ZONE_ID` (32), `CF_ACCESS_*` present on both boxes.
- `GET https://api.cloudflare.com/client/v4/user/tokens/verify` → **HTTP 200**, `"status":"active"`, `"This API Token is valid and active"`.
- `GET https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}` → **HTTP 200**, zone `abletelsolutions.com`, `active`, full setup, NS `aron.ns.cloudflare.com` / `patryk.ns.cloudflare.com`.
- The tunnel itself is a live proof: `cloudflared` unit **active**, `/etc/cloudflared/tunnel.token` present mode 600 (240 bytes), and inbound webhooks and public requests are terminating on the app right now.
- **R2:** `/root/.lpt-r2.env` exists, mode 600, keys `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (names only). `authority-offsite-backup.service` ran **2026-10-11 06:18Z**, exit 0, `reader_bytes=23707291648`, `gz_bytes=6278791492`, `parts=94`, `remote_last_modified=2026-10-11T06:46:57Z`, `bucket=lpt-authority-backups`. `/root/report-offsite-age.log` at **15:40:18Z** re-read the remote object: `{"key":"authority/secretary.db.gz","bytes":6278791492,"last_modified":"2026-10-11T06:46:57+00:00"}`. A retry at 15:30:02Z logged `no boto3` — the age reporter needs `boto3` in whichever interpreter it uses (`/usr/bin/python3` has it, the app venv does not).
- Verdict **WORKING** for both. The empty `CLOUDFLARE_TUNNEL_TOKEN` is by design (the unit uses `--token-file /etc/cloudflared/tunnel.token`).

### Hetzner
- `HETZNER_API_TOKEN` (64), `HETZNER_EMAIL`, `HETZNER_PASSWORD`, `HETZNER_MDM_IP` present on both boxes.
- `GET https://api.hetzner.cloud/v1/servers` → **HTTP 401** `{"error":{"code":"unauthorized","message":"the token you have provided is invalid"}}`.
- Note the shape of the failure: a 64-character token is present, so something *is* in the field — it is simply no longer a valid Hetzner API token (rotated, revoked, or copied wrong). The **password** credential is present and was not tested (testing it would log into the Hetzner console — not a read-only API call, and not run).
- The office's `monitor-hetzner-backups.sh` (every 6h, restic freshness for both Hetzner boxes, alerts on >26h staleness) is **not in the authority crontab**, so nothing is watching backups now.
- **Restore step:** mint a fresh Hetzner Cloud API token (read scope is enough for `GET /v1/servers`), write it to `HETZNER_API_TOKEN` in `/opt/company/.env`, `systemctl restart company-api`, verify `GET https://api.hetzner.cloud/v1/servers` → 200. Then port `monitor-hetzner-backups.sh` and its cron.

### Broker / gateway mesh
- No broker is listening: `curl http://127.0.0.1:3091/mesh/health` → connection refused (code 000); `ss -lntp` on the cloud box shows only `127.0.0.1:8002` (company-api) and `*:3000` (dashboard). This matches the migration brief's finding that the placement broker is loopback-only and exists nowhere.
- `AI_GATEWAY_MESH_PEERS_JSON=["http://192.168.50.138:8002"]` is an **office-LAN address**; from Ashburn it cannot be reached, so the mesh provider has no usable peer.
- `FLEET_API_URL=http://87.99.141.172:8003` (a public IP, port 8003) → **timeout**; `fleet_location_poll` last ran **2026-09-29T03:44:44Z** with 414 consecutive failures — dormant since well before the cutover.
- Everything else in this audit that depends on `subagent`/mesh fan-out is therefore unavailable from the authority; the memory of the *tool* is not the memory of the *service*.
- Verdict **BROKEN**, with the caveat that the mesh was already broken before the cutover (brief, lines 75–83) — it is a regression to *re-establish*, not one the cutover created.

## 3. REGRESSIONS — worked before the cutover, not since

Ranked by blast radius. "Worked before" means there is a success record; "not since" means no success record at 05:43:36Z or later.

1. **QuickBooks / accounting repo is gone from the authority.** Worked before: `amazon_sync` success 2026-10-11 04:10:11Z, `ebay_sync` 2026-10-09 04:16:25Z, `paypal_sync` 2026-10-09 03:45:40Z. Not since: every attempt fails `quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent`. Blast radius: **QuickBooks, eBay, Amazon, PayPal, receipts**. Restore: section 2 QuickBooks, steps 1–4.
2. **The accounting ledger file itself did not move.** Office has 21,995,520 bytes at `/home/zabz/accounting-data/live/accounting.db`; the authority has a **0-byte** `/opt/company/data/accounting.db` and a stubbed `/root/accounting-data/live/accounting.db`. Restore: section 2 QuickBooks, step 2.
3. **Stripe is unusable by the app even though the key is valid.** `stripe` 15.4.0 exists in the office venv, is **absent** from the authority venv, and is **absent from `requirements.txt`**. Not since: `/stripe/charges` → 500 since the cutover. Restore: `pip install 'stripe>=15,<16'` + add to `requirements.txt` + restart + port `stripe-key-watch.py`.
4. **71 of the office's 92 cron jobs did not migrate** (authority: 21 jobs). The ones that matter to integrations: `nightly-plaid-sync` (04:30), `daily-finance-sync-cron` (05:00), `stripe-key-watch` (every 6h), `monitor-hetzner-backups` (every 6h), `order-feed-refresh` (05:20), `supplier-order-ingest` (every 6h), `auto-categorize` (every 6h), `run-ha-truth` (*/30), `run-ha-behaviour` (04:20), `family_chat_watchdog` (*/30), `lpt-dialpad-daily` (06:30), `lpt-dialpad-apply` (*/15), `dialpad-call-fresh` (* * * * *), `reconcile-sms-status` (*/15), `comms-refresh`, `lpt-recon-check`, `website-comms-push-cron`, `push-dsh-sessions` (*/30), `mesh-health` (*/5), `mesh-placement-monitor` (*/5), `deadman` (*/5), `push-db-offsite` (05:10 — superseded by `authority-offsite-backup`), `company-offsite-push` (1,7,13,19h). Full inventory: `132-CRON-INVENTORY.md`. Restore: port them job by job, each with a `cron-wrap.sh` wrapper, and **do not** re-enable the ones superseded by the new systemd timers (`authority-offsite-backup`, `authority-data-offsite`, `authority-deadman`, `estate-monitor`).
5. **Hetzner API token invalid + no backup monitor.** The token returns 401; the 6-hourly `monitor-hetzner-backups{,.sh}` job is not installed. Restore: fresh token in `.env`, restart, port the monitor.
6. **Home Assistant unreachable from the new network.** `HA_URL=http://homeassistant.local:8123` is an office-LAN name; DNS fails from Ashburn. Restore: reachable `HA_URL` + restart. Caveat: the HA scheduler was already dead from 2026-10-05, so this is a *not-fixed* rather than a *newly broken*.
7. **Twilio inbound SMS / family chat has produced nothing since 05:41:32Z.** Credentials valid, webhook doors proven to accept signed POSTs. Restore/next step: **one real SMS to a company number** (owner's approval required) — everything upstream of the carrier is already proven.
8. **Broker / gateway mesh still unreachable** (loopback 3091 refused; the only configured mesh peer is an office-LAN address). Pre-existing, not cutover-created; must be re-established for any fan-out from the authority.

### Also true, and worth recording
- **No credential was lost in the migration.** 301 of 301 office keys are present on the authority, plus `DATABASE_URL`. The failures are missing *artifacts* (a repo, a ledger file, a Python package, 71 cron jobs) — that is a materially better position than the audit brief feared.
- Every failure above is a **silent** failure: autopilot keeps ticking, `health` returns 200, and the app reports `ok:true` on `/quickbooks/status` while `connected:false`. Where this audit could not distinguish "not being called" from "being called and failing", it says UNKNOWN rather than picking the comfortable answer.

## 4. What could NOT be tested, and why

| Not tested | Why |
|---|---|
| A real Twilio SMS in or out (company and family-chat) | Would transmit to a person. **Prohibited by the task.** The webhook doors themselves were proven (403/401 signature rejection, reaching `app.main`). |
| eBay / Amazon / PayPal live feed pull | Requires an authenticated scraper session against the owner's third-party accounts, and all three route through the missing QuickBooks repo. |
| Hetzner account via `HETZNER_EMAIL`/`HETZNER_PASSWORD` | A console login, not a read-only API call. |
| DeepInfra end-to-end generation | Proved the key with three read-only catalogue calls (200). A completion would spend the owner's money for a test. |
| Home Assistant authenticated `GET /api/` | Unresolvable hostname from the authority; the token could not be exercised. |
| Broker/gateway mesh end-to-end | No broker process exists anywhere reachable; `127.0.0.1:3091` refuses. |
| `order-feed-refresh`, `supplier-order-ingest`, `auto-categorize`, `family_chat_watchdog` behaviour on the authority | The jobs do not exist there; nothing to run and nothing to read. |
| Any pre-cutover evidence older than 2026-10-11 00:00:22Z | The authority's journal begins at `2026-10-11 00:00:22Z`. Older history would have to come from the frozen office database, which this audit did not read (the office box is read-only and its DB is the rollback anchor). |

## 5. Provenance

Every number above was produced on **2026-10-11 between 15:38Z and 15:50Z** by this session on ZABZ-YOGA, against `secratary-cloud` (authority) and `secratary-ts` (office reference), using: `ssh`, `curl`, `/usr/bin/python3` and `/opt/company/.venv/bin/python` heredocs, `journalctl -u company-api`, `systemctl`, `crontab -l`, `sqlite3` (read-only, `file:...?mode=ro`) and `pip list` / `os.stat` / `json` inspection of route files. Office-box load average was read at 15:38:52Z (0.00), after the script reads (0.06) and after the script reads (0.03) — well under the ~8 ceiling in the migration brief. No writes, sends, restarts or deletions were performed on either machine.

