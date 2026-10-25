# 161 — API ESTATE AND PURCHASES

**Workstream E.** Credential-and-API audit, re-measured live on **2026-10-25** (all times UTC), and
the purchase recommendation the owner is waiting for.

**Node:** `zabz-tech` (`ZABZ-TECH`), PowerShell 7.6.6.
**Authority read over ssh:** `secratary-cloud` (`178.156.194.1`, posture `writable` per
`settings/machines/host-posture.tsv`). `secratary` was **not touched** — it is `frozen`.
**No code changed. Nothing committed, pushed, deleted or purchased. No vendor was contacted.**

> **Two documents named in the brief do not exist.** `docs/mesh/160-AGENT-HANDOFF-SOURCING-AND-API-
> ESTATE.md` and `docs/mesh/150-RESEARCH-AND-PROCUREMENT.md` are on no host (`find / -name
> '160-AGENT-HANDOFF*'` on the authority returned nothing; `git log --all -- docs/mesh/160-*` shows
> that `docs/mesh/160` was the *migration record*, a different file). §1 of the handoff therefore
> could not be "re-measured against" — the estate was measured from scratch instead. If a prior
> session believes it wrote that table, it did not write it here.

---

## 1. Credential estate, measured

Every value below is a **name and a length**. No value, prefix, or hash of a short value is printed.
`sha256[:12]` was computed for each value during collection and deliberately **not** reproduced here
for secrets; it is available in the session if a future audit needs to prove two files are identical.

### 1a. This workstation — `C:\Users\ezabz\.secrets` (4 files)

| credential | where | state | evidence (command → output line) | headroom |
|---|---|---|---|---|
| `DATAFORSEO_LOGIN` (18), `DATAFORSEO_PASSWORD` (16) | `dataforseo.env` (73 B) | **live** | `python scripts\sourcing\dataforseo.py --balance` → `"status_code": 20000`, and `GET /v3/appendix/user_data` → `money.balance = 0.986` | **$0.986**. At the estate's own quoted rate (`price.serp.live.regular.cost = 0.002`, per_request) that is **~493 Google-organic SERP requests** left |
| `EBAY_APP_ID` (40), `EBAY_CERT_ID` (36), `EBAY_DEV_ID` (36), `EBAY_ENV` (10), `EBAY_MARKETPLACE_ID` (7), `EBAY_RUNAME` (39) | `ebay-personal.env` (580 B) | **live** | `python scripts\sourcing\ebay_api.py doctor` → `VERDICT: working — token issued, Browse answered, and the condition filter is honoured`; app token **289 ms**; Browse **4779 results** for `dell latitude 5420`; condition filter `2010` returned only 2010 (138) | free-tier ceiling quoted by eBay on its own developer sign-in page: *"5,000 API calls per day"*; no per-call charge. App token TTL 7200 s |
| deletion-notification token, single 40-char value, **no `=` in the file** | `ebay-deletion-token` (40 B) | **unknown** | no reader found in any tree scanned | n/a — compliance endpoint only |
| `EBAY_USER_*` (refresh token) | *not on this host* | — | see 1b; the refresh token lives only on the authority | — |

### 1b. The authority — `/root/.secrets` (6 files)

| credential | where | state | evidence | headroom |
|---|---|---|---|---|
| `DATAFORSEO_LOGIN` (18), `DATAFORSEO_PASSWORD` (16) | `dataforseo.env` (73 B) | **live** | `GET https://api.dataforseo.com/v3/appendix/user_data` → `status_code: 20000`, `money: {"total": 1, "balance": 0.986}` | **$0.986** of **$1.00** ever deposited; **$0.014** consumed today (`statistics.day.total = 0.014`) |
| `EBAY_APP_ID`, `EBAY_CERT_ID`, `EBAY_DEV_ID`, `EBAY_ENV`, `EBAY_MARKETPLACE_ID`, `EBAY_RUNAME` | `ebay-personal.env` (**565 B**) | **live** | same six names, same lengths as the workstation copy, but **15 bytes smaller** — the two files are *not* byte-identical | see 1a |
| `access_token` (2740), `refresh_token` (96), `expires_at`, `refresh_expires_at`, `obtained_at`, `variant`, **`scope` EMPTY** | `ebay-user-token.json` (3073 B) | **live** | `obtained_at = 2026-10-25T04:35:25.118039+00:00`; `expires_at = 1792910125`; `refresh_expires_at = 1840206925`; user-token Browse read: **2195 ms, total=41397, returned=3** | access token ≈ 2 h; refresh token ≈ 2028-04. `scope` being empty is why the app-keyset grant is the one exercised |
| deletion-notification token, 40 chars | `ebay-deletion-token` (40 B) | **unknown** | no reader found | n/a |
| Telnyx 2FA backup codes | `telnyx-2fa-backup-codes.txt` (1209 B) | **standby** | by nature unreachable by API; recovery material | n/a |
| Telnyx eSIM activation codes | `telnyx-esim-activation-codes.txt` (1749 B) | **standby** | static inventory, not a credential | n/a |

### 1c. `/opt/company/.env` on the authority (28,659 B, 334 keys total across the two env files)

Read with `cut -d= -f1`-equivalent parsing: **names and lengths only**. Never `cat`-ed.

**Keys present but EMPTY (a blank credential cannot work — these are configured and dead):**

`LINUX_PC_SSH_PASSWORD`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `AZURE_OPENAI_API_KEY`,
`MODEL_PROVIDER_KEYS_JSON`, `ACCOUNT_ACCESS_TOKENS_JSON`, `TWILIO_FORWARD_TO_USER`,
`TWILIO_VOICE_WEBHOOK_BASE_URL`, `TWILIO_SMS_WEBHOOK_BASE_URL`, `TWILIO_STATUS_CALLBACK_BASE_URL`,
`TWILIO_VOICE_DISASTER_FALLBACK_MESSAGE`, `GITHUB_WEBHOOK_SECRET`, `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`, `CF_ACCESS_*` (3 of 4 have values; `CF_ACCESS_CLIENT_SECRET`
present), `MEM0_PROVIDER`.

**Live third-party balances measured this session — the numbers, with the command that produced them:**

| provider | number | how |
|---|---|---|
| **DataForSEO** | **balance $0.986**; total deposited $1.00 | `python scripts\sourcing\dataforseo.py --balance`; cross-read via `GET /v3/appendix/user_data` |
| **DataForSEO unit cost** | **$0.002 per request** for live SERP regular | the account's own price table in the `user_data` response: `price.serp.live.regular → {"cost_type":"per_request","cost":0.002}` |
| **Firecrawl** | **9,815 credits remaining**; `planCredits: 1000`; period `2026-10-22T18:51:48Z` → `2026-11-22T18:51:48Z` | `GET https://api.firecrawl.dev/v2/team/credit-usage` → `{"remainingCredits":9815,"planCredits":1000,...}` |
| **SerpApi** | **222 of 250 searches left**; **28 used** this month; rate limit 250/hour; `plan_name: Free Plan` | `GET https://serpapi.com/account` → `plan_searches_left = 222`, `this_month_usage = 28` |
| **eBay** | app token in **289 ms**; Browse **4,779 results**; user token Browse **41,397 results** in 2,195 ms | `ebay_api.py doctor` |

Firecrawl's 9,815 against a 1,000/month plan means roughly **8.8 months of plan credits are banked** —
the headroom is not the constraint; the 1000/month replenishment is.

---

## 2. Keys that exist and nothing reads

**Method (exactly what was run, so it can be re-run or contradicted):**

```bash
# authority, over ssh
grep -rhoE '[A-Z][A-Z0-9_]{3,}' /opt/company/app /opt/company/scripts /opt/company/apps \
  --include=*.py --include=*.ts --include=*.js --include=*.mjs --include=*.sh --include=*.html \
  | sort | uniq -c | sort -rn > /tmp/kc.txt      # 6,595 distinct tokens, 654 python files
```
then joined against the 334 key names from `/root/.secrets/*.env` + `/opt/company/.env`.

**Result: 177 of 334 key names have zero references in the authority's own code.**

**The honest caveat, stated before the list:** a grep finds *static* references. A name assembled at
runtime (`f"{prefix}_API_KEY"`, a dict keyed by a config string) is invisible to it. So the correct
reading is **"no static reader in the scanned trees"**, *not* "provably dead". The cross-check below
proves the caveat is real, not decorative.

**The cross-check that saved this section from being wrong.** The same scan was run on this
workstation over `lpt-hub`, `harness-config`, `personal-secretary-mvp`, `scripts`, `lpt-ops`. It
reported `EBAY_APP_ID → 0 references`. That is false: `lpt-hub\scripts\sourcing\ebay_api.py` alone
contains 34 matches, including `env.get("EBAY_APP_ID")` at line 190. **The Windows-side pass
under-counts and its zeroes must not be published.** Keys it did show as read on this side —
`TAVILY_API_KEY` (12), `SPIDER_API_KEY` (16), `QWEN_API_KEY` (12), `EXA_API_KEY` (8) — are therefore
**removed** from the orphan list even though the authority never reads them.

### The orphan list that survives both passes

Configured, non-empty, and read by neither the authority's code nor any statically-visible reader on
this workstation:

- **Payments / banking:** `PAYPAL_CLIENT_ID` (80), `PAYPAL_CLIENT_SECRET` (80), `PLAID_CLIENT_ID` (24),
  `PLAID_SECRET` (30), `PLAID_SANDBOX_SECRET` (30), `BOA_USERNAME`, `BOA_PASSWORD`.
  A PayPal merchant integration and a Plaid bank link are **configured and unused** — the shape of a
  capability that was claimed and never delivered.
- **Marketplace / MDM identities:** `MOSYLE_API_TOKEN` (64), `MOSYLE_EMAIL`, `MOSYLE_PASSWORD`,
  `MOSYLE_ORG`, `MOSYLE_ABM_CLIENT_ID`, `MOSYLE_ABM_KEY_ID`, `NANODEP_API_KEY` (48),
  `NANOMDM_API_KEY` (48), `MDM_HOSTNAME`, `HETZNER_MDM_IP`.
- **Facebook / Gmail operator identities:** `FB_ACCOUNT_PRIMARY`, `FB_PASSWORD_PRIMARY`,
  `FB_ACCOUNT_ORDERS`, `FB_PASSWORD_ORDERS`, `FB_ACCOUNT_NOTINUSE`, `FB_PASSWORD_NOTINUSE`,
  `LPT_GMAIL_ACCOUNT`, `LPT_GMAIL_PASSWORD`, `APPLE_ID` (55), `APPLE_ID_PASSWORD` (15).
  These are human-account logins, not API keys. Nothing automates them.
- **Search/data keys the authority never reads** (but see §2 caveat): none of the web-data keys
  survive the cross-check except the empty ones.

**A stronger, caveat-free subset — keys that are empty *and* unreferenced.** A zero-length credential
cannot be live regardless of who reads it: `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`,
`AZURE_OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`,
`TWILIO_SMS_WEBHOOK_BASE_URL`, `TWILIO_VOICE_WEBHOOK_BASE_URL`, `GITHUB_WEBHOOK_SECRET`.
Either finish these or delete the names — a half-wired integration that silently no-ops is worse than
an absent one.

---

## 3. What to buy, in value order

**One recommendation per need. Every price below was read from the vendor's own page on 2026-10-25.**

| # | need | vendor | cost | what it unlocks | verdict | evidence |
|---|---|---|---|---|---|---|
| 1 | Phone/IMEI device check | **imeicheck.com** | **$0.75** Apple FULL+MDM+GSMA PRO; **$0.12** Apple FULL INFO; **$0.10** Samsung + KNOX GUARD; **$0.06** Blacklist PRO; **$0.01** model/iCloud-lite. Pay-as-you-go, no subscription | activation lock (Find My iPhone / iCloud Lost Mode), **MDM enrolment**, GSMA/US block status, carrier/blacklist, KNOX Guard — the exact set that turns a $300 purchase into a brick | **BUY NOW** | <https://imeicheck.com/pricing> (read 2026-10-25) |
| 2 | Sold-price history, phones + laptops | **eBay Product Research (Terapeak) — free** | **$0** with an eBay seller account | 90 days of *sold* prices in the UI, which is the actual question ("is this asking price normal") | **NO PURCHASE — use the free tool** | <https://www.ebay.com/help/selling/selling-tools/product-research?id=4853> (read 2026-10-25) |
| 3 | Repair-parts distributor feed | none | — | — | **NO** | see §3.3 |
| 4 | Amazon product data | none | — | — | **NO** | see §3.4 |
| 5 | Phone-screen/laptop spec lookups already covered | Firecrawl (**9,815 credits**) + Jina + local Playwright | $0 marginal | page reads, spec sheets, retailer grids | **NO NEW SPEND** | §1c |

### 3.1 IMEI / device check — four vendors compared on price and coverage

| vendor | per-check price (read from the vendor) | Apple | Android | activation lock | MDM | blacklist / GSMA | API | batch | official/authorised |
|---|---|---|---|---|---|---|---|---|---|
| **imeicheck.com** | **$0.01–$0.75**; Apple FULL+MDM+GSMA PRO **$0.75**; Apple FULL INFO +carrier **$0.12**; MDM $0.25; KNOX GUARD $0.10; Blacklist PRO $0.06 | yes | Samsung, LG, Huawei, Xiaomi, Motorola, Sony, HTC, ZTE, OnePlus | **yes** (Find My iPhone, iCloud Lost Mode) | **yes, $0.25** | yes, incl. a "GSMA PRO" bundle and per-record blacklist history | **yes** — "50+ IMEI check services with instant API access for all of them" | yes, bulk/reseller tiers; *"we beat any market price for bulk orders"* | resells brand + GSMA data; **not stated to hold its own GSMA licence** |
| **imei.info** | API **from $0.02**/request (Simple Info); Extended Info "custom price"; **$5 minimum** to activate | yes | yes | partly (iCloud check sold separately) | not listed | yes | **yes** — REST/JSON, Swagger, Postman, webhooks | **yes, up to 1,000 IMEI/SN per batch** | TAC database 304,088; 495.8 M checks lifetime; not a GSMA licensee claim |
| **CheckMEND** (Recipero) | **$1.99** for 1; **$1.79** each at 10 ($17.91); **$1.39** each at 100 ($139.30) | yes | yes | no | no | **yes** — police, insurer, retailer, network, GSMA-sourced | **corporate contract only** ("email sales@checkmend.com") | yes via account | **the most authoritative of the four** — CTIA/GSMA/Vodafone-endorsed ecosystem |
| **Swappa** | **free** | yes | yes | **no** | **no** | yes — GSMA allowlist/blocklist only | no | no | consumer-facing, no SLA |

**Recommendation: imeicheck.com, pay-as-you-go.**

The arithmetic that decides it:

- The purchase it prevents is a **$300 brick**. One avoided bad phone pays for **400** full
  `$0.75` Apple screens, or **3,000** `$0.10` Samsung KNOX checks.
- A realistic month: 20 iPhones × $0.75 + 10 Samsung × $0.10 + 10 blacklist-only × $0.06
  = **$15.00 + $1.00 + $0.60 = $16.60/month**. Worst case at 40 iPhones = **$30.00/month**.
- CheckMEND at $1.99 is **2.7×** the price of the fuller $0.75 screen and does **not** report
  activation lock or MDM — the two things that actually brick a phone. Its strength (police/insurance
  records) matters for *stolen-goods* exposure, not for "can I activate this".
- imei.info's $0.02 headline is for **Simple Info** (model/TAC), not a lock screen; its Extended Info
  is "custom price" — a quote, not a price, so it cannot be the BUY line.
- Swappa stays as the **free first pass**: it answers GSMA allow/block in one click and costs nothing.
  It cannot see Find My iPhone or MDM, so it is a filter, not the decision.

**Practical rule to install:** Swappa free check → if clean, buy one `$0.75` Apple FULL+MDM+GSMA PRO
(iPhone) or `$0.10` Samsung KNOX Guard check before paying. Never pay for a phone on the strength of
a GSMA check alone.

### 3.2 Sold-price history — priced, and mostly the wrong market

| vendor | price | covers used/refurb? | verdict |
|---|---|---|---|
| **eBay Product Research (Terapeak)** | **$0** in Seller Hub; UI only | **yes** — actual sold prices, 90 days | **use this** |
| **eBay Marketplace Insights API** | — | yes (if you could get it) | **unreachable**: Limited Release, "available only to select developers approved by business units"; the docs URL itself redirects to `developer.ebay.com/signin?return_to=/api-docs/marketplace-insights-private/...` |
| **Keepa API** | **€49/mo** Starter (20 tokens/min, 892,800 tokens/mo); €459 Developer; €2,499 Business | **Amazon only** — new/Amazon offers, not eBay used | **NO** — wrong marketplace, and the floor is €49 not the "10/month tier" |
| **PriceAPI** | **€99/mo** (5,000 credits) at the table; €259 / €499 / €999 / €1,499 above. The page's own intro sentence says "starting at 499 Euro per month" — **the page contradicts itself** | new-retailer price history | **NO** — 6× Keepa's floor for data the free eBay tool already answers |
| multi-retailer history vendors | not priced this session | — | **unverified** |

The buyer's question is a *range over time for a used unit*, and the only source that is literally that
is eBay's own sold data. It is free, and the shop already holds an eBay seller identity
(`EBAY_RUNAME`, a live user token, 41,397 live Browse results). **No purchase.**

### 3.3 Repair-parts distributors — no API, and the terms forbid the scrape

- **MobileSentrix** and **Injured Gadgets** both sell through a web portal behind a wholesale account.
  **No public developer API documentation was found on either site.** Ordering integration exists only
  through repair-shop POS partners — RepairDesk advertises a MobileSentrix integration and vendor
  price sync across "MobileSentrix, Injured Gadgets, and Phone LCD Parts"; MyRepairApp advertises
  ordering "directly from integrated suppliers like MobileSentrix and Injured Gadgets".
- **Injured Gadgets' terms** (read in full, 2026-10-25) grant permission to copy/print site content
  *"solely for the purpose of placing an order"* and state that *"any other use, including but not
  limited to the reproduction, distribution, display or transmission of the content of this site is
  strictly prohibited, unless authorized"*. **A licensed scrape is therefore not available on their
  terms** — it would need written authorisation, which is an owner action, not an agent one.
- **MobileSentrix terms could not be read**: `https://www.mobilesentrix.com/terms-and-conditions`
  returns **404**. Their scraping posture is **unverified** — do not assume it mirrors Injured Gadgets'.

**Verdict: NO.** Parts sourcing stays on eBay + Google Shopping (already covered by the live eBay
keyset and Firecrawl credits). The improvement available is not a purchase: it is a **MobileSentrix
wholesale account** so a human can price parts against eBay, which costs nothing but an application.

### 3.4 Amazon product data — not reachable for this business

Read from Amazon's own documentation, 2026-10-25:

1. **PA-API 5 is deprecated.** `webservices.amazon.com/paapi5/documentation/` now serves a
   *"PA-API 5 Deprecation Notice"*: calls to the old endpoint return
   `403 AccessDenied — "Product Advertising API is deprecated. Please migrate to Creators API"`.
2. **The successor's gate is a sales quota.** `affiliate-program.amazon.com/creatorsapi/docs/en-us/
   introduction` lists the prerequisites: *"Be enrolled in the Amazon Associates program…"* and
   **"Have at least 10 qualifying sales within the past 30 days to access the PA API through the
   Creators API."**

A repair shop that does not run an Amazon affiliate funnel has **zero** qualifying affiliate sales,
so it cannot meet a 10-sales-in-30-days gate. **Verdict: NO — unreachable, not merely expensive.**

### 3.5 The withdrawn list — re-confirmed, with the reason that still holds

| withdrawn item | does the reason still hold on 2026-10-25? | evidence |
|---|---|---|
| **SerpApi paid** | **yes.** Free plan = **250/month**; **222 left**, 28 used this month. Paid floor is **$25/mo** for 1,000. Buying would add 750 searches the shop is not using | `GET serpapi.com/account`; <https://serpapi.com/pricing> |
| **Keepa** (withdrawn once) | **yes, more strongly.** Cheapest API is **€49/mo**, and it tracks **Amazon**, not the eBay used market | <https://keepa.com/api/pricing> |
| **Browserbase** | **yes.** Local Playwright is in the harness; no new need | no new evidence |
| **Bright Data** | **yes.** Firecrawl (**9,815 credits**) already returns pages that Bright Data would proxy | §1c |
| **Apify** | **yes.** Same: managed scraping is already paid for and under-used | §1c |
| **2Captcha** | **yes.** No CAPTCHA-walled source has been shown to be necessary | no new evidence |
| **Nexar / Octopart** | **yes.** Both are *electronic component / BOM* APIs. Nothing in phone, tablet or laptop repair sources a PCB bill of materials | domain mismatch |

**Nothing on the withdrawn list should be re-opened.** The one thing that changed is that Firecrawl's
credit balance (9,815) makes the scraping category *more* over-supplied, not less.

---

## 4. What only the owner can do

1. **Create the imeicheck.com account and put a card on file**, then top up a small balance
   (~$25 covers the first month at the realistic $16.60). KYC/identity and payment are his.
2. **Set the per-phone check budget and the rule** — e.g. "never buy a phone without a
   `$0.75` Apple FULL+MDM+GSMA PRO or `$0.10` Samsung KNOX check". A spend rule an agent can follow
   is worth more than the account.
3. **Confirm the eBay seller account** that Product Research/Terapeak runs under. If the shop sells
   from a different login than the one behind `EBAY_RUNAME`, that is his to reconcile.
4. **Apply for the MobileSentrix wholesale account** if he wants parts priced against eBay — the
   application is his identity, not ours.
5. **Decide the empty-credential cleanup** (§2): finish or delete the half-wired integrations. Deleting
   a name is a one-line change an agent can make, but *which* capability he still wants is his call.

---

## 5. Total monthly cost

**If he says yes to everything recommended:**

| item | monthly |
|---|---|
| imeicheck.com, realistic month (20 iPhone × $0.75 + 10 Samsung × $0.10 + 10 blacklist × $0.06) | **$16.60** |
| imeicheck.com, worst case (40 iPhone × $0.75) | **$30.00** |
| Terapeak / Product Research | **$0.00** |
| parts sourcing (eBay + Firecrawl + Google Shopping) | **$0.00 marginal** |
| Amazon product data | **$0.00 — not purchasable** |
| **TOTAL, recommended set** | **$16.60/month realistic; $30.00/month ceiling** |
| **fixed subscription commitment** | **$0.00/month** |

**If he instead said yes to every vendor *evaluated* (not recommended):**

```
Keepa Starter            €49.00
PriceAPI Go              €99.00
SerpApi Starter          $25.00
imeicheck.com usage      $16.60
------------------------------------
                         ≈ $190–200/month, of which ≈ $173 buys nothing he does not already have
```
(€ figures converted at ~1.08 for the arithmetic only — the FX rate was **not** read from a vendor and
is not a quoted price.)

**The recommendation costs $0 in commitments and under $20/month in use.** That is the whole point:
the highest-value purchase on the list is a **$0.75 check**, and everything else on the list is either
free already or unreachable.

---

## 6. What I could not verify

Item by item, so nobody later quotes it as fact:

1. **`160-AGENT-HANDOFF-SOURCING-AND-API-ESTATE.md` and `150-RESEARCH-AND-PROCUREMENT.md` do not
   exist** on this workstation or the authority. §1 and §5 of the brief could not be read.
2. **MobileSentrix terms of service** — the URL 404s. Their scraping posture is unknown.
3. **Whether MobileSentrix or Injured Gadgets expose a partner API** to non-POS customers. Absence of
   public docs is not proof of absence; both may have private APIs (a MobileSentrix "custom Shopify
   API integration app" is mentioned in a third-party profile).
4. **Whether imeicheck.com holds a direct GSMA licence** or resells another provider's GSMA access.
   Their page says "we are the direct source for most services" — marketing, not a licence.
5. **eBay's API call quota** — the 5,000/day figure comes from the developer sign-in page's marketing
   copy, not from a rate-limit document, and was not tested to exhaustion.
6. **DataForSEO's per-request cost as seen in a task response.** The `$0.002` above is from the
   account's own *price table*, not from a billed task — I ran no billable task, because the brief
   forbids spending money. `user_data` and `--balance` are free (`cost: 0`).
7. **Keepa's consumer/Pro tier price.** Third-party pages say €19 or €29; Keepa's own page was not read
   for it. Irrelevant to the verdict — the **API** floor of €49 is what was read.
8. **CheckMEND's API price.** Only "email sales@checkmend.com for a corporate account" is published.
9. **PriceAPI's real entry price** — its own page says both "starting at 499 Euro per month" and
   "Go €99/mo". Unresolved; either way it is far above the free alternative.
10. **Firecrawl plan tier / how 9,815 credits were accrued** — the API reports remaining and plan
    credits but not the grant history.
11. **The Windows-side `grep` pass under-counts.** Proven by `EBAY_APP_ID → 0` on a file containing 34
    references. Any zero from that pass is unreliable; the orphan list in §2 reflects this.

---

## 7. Definition of done — checked

- Every balance and quota above is a **number with the command** that produced it. ✔
- **Four** IMEI vendors compared, with per-check prices and URLs read 2026-10-25. ✔
- Every **BUY NOW** line has a price **and** a URL. ✔ (one BUY NOW: imeicheck.com, $0.75, §3.1)
- `git -C C:\Users\ezabz\code\harness-config status --porcelain` was run:
  **55 entries — 21 modified (` M`), 34 untracked (`??`)**. Before this document was written the count
  was **54 (21 modified, 33 untracked)**. The single entry this workstream added is
  `?? docs/mesh/161-API-ESTATE-AND-PURCHASES.md`; the other 54 pre-date it and were not touched.
