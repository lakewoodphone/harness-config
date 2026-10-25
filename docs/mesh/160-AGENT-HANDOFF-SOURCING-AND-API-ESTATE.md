# 160 — AGENT HANDOFF: the sourcing stack, the API estate, and what is left to buy

**Written 2026-10-25 by Zabz (chief engineer) on ZABZ-YOGA, at the owner's request: *"create a handoff
doc to the next agent about all the api keys and info we want to set up… who you are and your
instructions for the next agent."***

Read **`docs/mesh/150-RESEARCH-AND-PROCUREMENT.md`** first — it is the inventory of what exists.
This document is the layer above it: **who holds which credential, what is proven, what is parked,
and what will bite you.** Every number here was measured on 2026-10-25; where I could not verify
something I say so instead of asserting it.

---

## 0. Who I am, and what I expect of you

I am **Zabz** — Eliyahu's chief engineer and chief of staff. I run the systems, not a chat window. He
is the architect: product direction, constraints, domain rules, money, customers and family are his.
Everything else is ours. He is terse, he works the shop 12:30–5 and the machine late, and he is
right more often than a first reading suggests.

**The instructions that matter in this area specifically, each learned the hard way:**

1. **Every fact carries where you read it** — a command and its output line, a file and its
   timestamp, a row and its time, read *in this session*. If you cannot say where, the answer is
   "not verified" and that is a complete answer.
2. **A non-zero exit is an open item.** Put the code and the failing line in your next sentence.
3. **Verify, do not assume. And report `partial` as partial.** Half this estate's failures were a
   confident sentence about something nobody ran.
4. **Never claim a capability you have not executed.** Twice today a tool "had no data" when the
   truth was "the request was malformed".
5. **Ask what an account is FOR before you build a reader for it.** I built an orders reader for an
   eBay account that has never sold anything (`L13697`). One question at the start would have saved
   two hours.
6. **Never share sourcing detail with a customer** — no marketplace link, no source price, no margin,
   no seller name, no item id. They see brand and family, new/refurb, the LPT total.
7. **Nothing outbound without a per-message yes from the owner in the current conversation**, body
   shown first in a fenced block.
8. **Capability is never reduced for safety** — credentials get moved, encrypted or brokered, never
   withdrawn (`D2907`).
9. **A decision goes into the repo or journal that owns it, the moment it is made.** This conversation
   is the one thing guaranteed to be thrown away.

---

## 1. Credentials and accounts — exactly where they stand

All values live in files at mode 600. **Never print a value; print lengths, shapes or a
`sha256[:12]` fingerprint.** The eBay app pair's fingerprint is `a47e8d3196e8`.

| # | credential | where it lives | state 2026-10-25 |
|---|---|---|---|
| 1 | **eBay app keyset** (App ID, Cert ID, Dev ID) + `EBAY_RUNAME` | `~/.secrets/ebay-personal.env` on ZABZ-YOGA, ZABZ-TECH, `zabz-tech-linux`; `/root/.secrets/ebay-personal.env` (authority) | **WORKING.** Token in 158–324 ms, 4,763 live results. Was blocked for two days by a *non-compliant keyset*, not by a wrong paste — see §4. |
| 2 | **eBay user token** (OAuth, refreshable) | `/root/.secrets/ebay-user-token.json` | **WORKING but returns zero.** Access 2 h, refresh present. The account **buys, never sells**, so `sell/fulfillment/v1/order` returns 0 with no filter at all. Do not read that as breakage. |
| 3 | **eBay account-deletion token** | `/root/.secrets/ebay-deletion-token` + `~/.secrets/ebay-deletion-token` | **LIVE.** Endpoint challenge-verified over the public hostname, before and after a restart. |
| 4 | **DataForSEO** (login + password, Basic auth) | `~/.secrets/dataforseo.env` on all four nodes | **WORKING.** Balance **0.996 of 1.00** trial credit. Google Shopping at **0.001–0.002 per query**. |
| 5 | **Firecrawl** | `FIRECRAWL_API_KEY` in `/opt/company/.env` and `~/.secrets/fetch.env` (yoga) | **WORKING.** 9,926 credits remaining; ~5 credits per scrape. Also available in-session as the `firecrawl` MCP server (keyless). |
| 6 | **SerpApi** | `SERPAPI_API_KEY` in the same two files | **WORKING, demoted.** Free plan, 250/month, **226 left**, 24 used. Now a *fallback only* — DataForSEO answers the same question 25× cheaper. |
| 7 | **Playwright** (local Chromium) | `personal-secretary-mvp/.venv` | **WORKS headless.** Cannot sign into eBay: automation-flagged Chromium meets a "Security Measure" wall. |

**Not a credential but load-bearing:** the company API is public at
`https://api.abletelsolutions.com`; `/webhook/*` is the prefix `_api_access_guard` leaves open, and
every handler there verifies its own input.

---

## 2. What I built, and how each piece proves itself

All in **`lpt-hub/scripts/sourcing/`**, branch **`agent/ebay-browse-api-20261023`**.

| file | what it does | how to verify | known limit |
|---|---|---|---|
| `ebay_api.py` | eBay Browse API: `doctor`, `selftest`, `search`, `item`, `conditions`, `--aspects` | `selftest` → **17/17**; `doctor` proves token **and** that the condition filter is honoured (exit 7 if not) | app token only: no orders, no seller tools |
| `dataforseo.py` | Google Shopping: `google_shopping()`, `--balance` | one query returns ~40 items for **0.001** | task-based: `task_post` then poll ~18 s |
| `fetch_ladder.py` | per-site escalation `firecrawl_json → firecrawl_markdown → playwright → browser_service`, with `capabilities.json` remembering which tier won | `--selftest` → **7/7**; `--status` | Best Buy still `partial` |
| `sourcing_fanout.py` | one query across every source, classified whole/part/accessory, cached, profile-driven | see §3 numbers | ~35 s cold, 0.01 s warm |
| `ebay_browse_search.py` | dispatcher wrapper so company agents can call the search | `ps_action("ebay_browse_search")` reaches it (stops at the L1 autonomy gate) | gate, not a bug |

**Deployed copies** on the authority: `/opt/company/data/tools/{dataforseo,ebay_api,ebay_browse_search,sourcing_fanout,fetch_ladder}.py`.
`data/tools/` is **gitignored** — those copies are artefacts, so **redeploy from `lpt-hub`, never edit
the box**.

**Company-side, `personal-secretary-mvp`** (branches `agent/ebay-account-deletion-endpoint-20261025`
and `agent/ebay-sold-data-20261025`):

* `app/services/ebay_account_deletion.py` — Shopify-style compliance endpoint: challenge hash
  `sha256(challengeCode + token + endpoint)`, envelope parsing, and redaction that strips a seller
  name while keeping the commercial record. **Selftest 13/13.**
* `app/services/ebay_user_token.py` — consent URL, code exchange (tries five shapes, remembers the
  winner), refresh, and `sold_orders()`.
* Routes in `app/main.py`: `/webhook/ebay-marketplace-account-deletion` (GET+POST),
  `/webhook/ebay-oauth-callback` (instrumented — it logs the parameter names eBay sends to
  `/opt/company/data/ebay-oauth/callback.log`).

---

## 3. What is proven, with the numbers

| claim | measurement |
|---|---|
| eBay works | token 158–324 ms; 4,763 results for "dell latitude 5420"; `conditionIds:{2010}` → **138** matches, all 2010 |
| eBay auth is stable | 13 consecutive token requests, 0 refusals, 0 transport errors |
| DataForSEO works | task_post **0.001**, 40 items in ~18 s, numeric price + merchant + shopping_url |
| the fan-out works | "latitude 5420 16gb" → **48 offers, 5 sources, 45 s**; "latitude 5420 lcd screen fhd" → **24 part offers, 34.99–59.00** |
| the cache works | same query repeat: **37.31 s → 0.01 s**, each source labelled `cached Ns` |
| the model gate works | without profile: 32 rows, **2 wrong models** (5430/5350/5520). With `--profile laptop`: **27 rows, 0 wrong** |
| the deletion endpoint works | public GET returned 200 with a `challengeResponse` equal to a SHA-256 computed independently on the calling machine, before **and** after `company-api` restart; POST of a synthetic notification → `{"ok":true,"recorded":true}` |
| the OAuth exchange works | `redirect_uri=<full accepted URL>` → 200 + token; `redirect_uri=<RuName>` → 400 `invalid_grant` |

---

## 4. Traps — each one cost real time today

1. **`conditionIds`, not `conditions`.** eBay **silently ignores** an unrecognised filter key and
   answers the unfiltered query. `conditions:{2010}` returned 2,671 items across every condition;
   `conditionIds:{2010}` returned the correct 138. Lesson `L13504`. `doctor` now asserts it live.
2. **`redirect_uri` in the OAuth exchange is the FULL accepted URL, not the RuName.** Every guide
   says RuName; it returns `invalid_grant` here. Isolated by sending a deliberately bogus code —
   every variant carrying a `redirect_uri` then answered `invalid_grant`, which separated *shape*
   from *value*. A rejected exchange does **not** burn the single-use code, so several shapes can be
   tried inside the 299-second window.
3. **A "Non Compliant" application has a DISABLED keyset**, and a disabled keyset answers
   `401 invalid_client` — indistinguishable from a bad secret. eBay requires Marketplace Account
   Deletion to be subscribed to **or opted out** before the first production call. We subscribe,
   because the opt-out wording ("I do not persist eBay data") is false for us — the sourcing ledger
   keeps seller names.
4. **eBay blocks automated browsers at sign-in.** A `playwright` Chromium got a "Security Measure"
   interstitial then a blank window. A human, in their own browser, is the only path.
5. **Cloudflare masks a 502 body.** The real error was only in `journalctl -u company-api`. Read the
   log, never the browser page.
6. **Instrument a callback before debugging it.** The first live OAuth hit arrived with no `code`;
   recording parameter names turned the next attempt into a measurement within seconds
   (`ebaytkn/tknexp/username` = the app was still on Auth'n'Auth).
7. **`/opt/company/data/tools/` is gitignored.** Deployed copies drift. Redeploy from `lpt-hub`;
   the sha is recorded in the module docstring and in doc 150.
8. **Legacy eBay tools on the authority do not work.** `ebay_sourcing_tool.py` calls
   `buy/browse/v1/item_summary/search` with **no Authorization header at all**; `ebay_listing_fetcher.py`
   scrapes `ebay.com/sch/i.html` with the user-agent `eBayListingFetcher/1.0`. Both look like
   capability and are not. Do not cite them.
9. **This laptop's journal was 1,551 entries behind the authority** and minted a colliding id
   (`P12107`). Fetch `cloud` before believing `next-id`; append on the authority when ids matter.
10. **`google.com/search?tbm=shop` cannot be scraped** by Firecrawl on any engine — that is why a
    paid SERP tier exists at all.
11. **A buyer needs price history, not sold comps** (`L13697`). Sold data answers the seller's
    question. The buyer's question is "is this asking price normal", which is a range over time.

---

## 5. What we said we would set up and have NOT — the parked list

Ordered by value, with the measured reason each is parked. **Nothing here is blocked on the owner
except where marked.**

**Infrastructure APIs proposed early (they still stand, none bought):**

| # | item | cost | why it is parked now |
|---|---|---|---|
| 1 | **eBay Sell + Finances** | free with the keyset | *partly delivered*: the user token exists and `sold_orders()` runs. It returns zero because the account never sells. Worth keeping for the day it does. |
| 2 | **IMEI / device check** (IMEIGSX or similar) | per-check tiers | genuinely high value for *phone* buying: activation lock, MDM, FMI, carrier blacklist. Not started. **Needs the owner's money decision.** |
| 3 | **EasyPost** | free to 3,000 labels, then BYOCA 20/mo | labels + tracking + address verification. Not started; no blocker but no owner yes either. |
| 4 | **Google Business Profile** | free, access request | reviews and insights for the shop. Not started; needs a request against the profile's Google account (10+ business days). |
| 5 | **Google Ads** | free, developer token needed | spend and performance. Not started. |
| 6 | **iFixit API v2** | free | repair guides for odd devices. Not started; docs could not be loaded through bot protection, terms unverified. |

**Sourcing-specific, proposed during this session:**

| item | verdict |
|---|---|
| **SerpApi paid** | **cancelled** — DataForSEO is 25× cheaper for the same data |
| **Keepa Basic** (10/mo) | **withdrawn once**, after the owner pointed out he needs current data and Keepa's "current" is a crawler timestamp (`lastUpdate`, extra token if under an hour old). Revisit only if buyer price history is bought rather than built. |
| **Browserbase / Hyperbrowser / Steel** | the tier-6 adapter in `fetch_ladder.py` is written and reports *"no browser-service key configured"*. Buy only if Best Buy's missing prices start costing sales. |
| **Bright Data / Oxylabs** | residential proxies; buy only when outright 403s appear. None seen yet. |
| **Apify** | per-site prebuilt actors; an alternative to writing selectors. |
| **2Captcha** | only if a CAPTCHA wall appears in the ladder. None yet. |
| **eBay Marketplace Insights** | **no path.** Partner-only; the community reports access "can't be granted at this time". |
| **Terapeak** | market-wide sold data, but **UI only**, requires an eBay Store subscription and a *human* signed-in browser. Not an API. Only relevant if the owner ever sells. |
| **Amazon via DataForSEO** | **blocked.** `/merchant/amazon/products/live/advanced` returns `20000 Ok` with 0 items and 0 cost across three payloads, one naming `language_code` invalid although their docs list it. Amazon stays on the Firecrawl tier, which works. |
| **Amazon PA-API / Creators API** | PA-API 5 is deprecated (403 `AccessDeniedException`); the successor rides on an Amazon Associates account. |
| **Nexar / Octopart** | components only, and priced for engineering firms: 100 parts lifetime on evaluation. Not a candidate. |

---

## 6. Where everything holds

| thing | path |
|---|---|
| sourcing code | `C:\Users\ezabz\code\lpt-hub\scripts\sourcing\` (branch `agent/ebay-browse-api-20261023`, pushed) |
| deployed tools | `secratary-cloud:/opt/company/data/tools/` |
| compliance + OAuth service code | `C:\Users\ezabz\code\personal-secretary-mvp\app\services\` (branches `agent/ebay-account-deletion-endpoint-20261025`, `agent/ebay-sold-data-20261025`, pushed) |
| eBay / DataForSEO secrets | `~/.secrets/{ebay-personal.env,dataforseo.env,fetch.env,ebay-deletion-token}` on the workstations; `/root/.secrets/` on the authority (includes `ebay-user-token.json`) |
| ledger of what each site's fetch tier did | `lpt-hub/docs/customer-operations/sourcing/capabilities.json` |
| saved sweeps | `lpt-hub/docs/customer-operations/sourcing/searches/` (`fanout-*.json`, `ebayapi-*.json`) |
| this document | `harness-config/docs/mesh/160-AGENT-HANDOFF-SOURCING-AND-API-ESTATE.md` |
| the inventory it sits on | `harness-config/docs/mesh/150-RESEARCH-AND-PROCUREMENT.md` §2.1, §2.4, §2.4b |
| journal | `L13504`, `L13697`, `L13440`, `L13503`, `H13033`, `P12107`, `D10049` |

Branches are **published, not merged**: the estate's rule is to let an integrator merge rather than
push to `main`.

---

## 7. Ten minutes to verify the whole thing

```bash
# eBay: token, live read, and whether the filter is honoured
python lpt-hub/scripts/sourcing/ebay_api.py doctor        # expect VERDICT: working

# the client itself, no credentials, no network
python lpt-hub/scripts/sourcing/ebay_api.py selftest      # expect 17/17

# DataForSEO: one paid query, ~0.001
python lpt-hub/scripts/sourcing/dataforseo.py "dell latitude 5420" --depth 20

# the ladder's memory and its selftest
python lpt-hub/scripts/sourcing/fetch_ladder.py --status
python lpt-hub/scripts/sourcing/fetch_ladder.py --selftest

# the fan-out, profiled, with the cache warm on a second run
python lpt-hub/scripts/sourcing/sourcing_fanout.py "latitude 5420" --profile laptop

# the compliance endpoint, publicly
curl -s "https://api.abletelsolutions.com/webhook/ebay-marketplace-account-deletion?challenge_code=test" | head -c 120
```

Use `personal-secretary-mvp/.venv/Scripts/python.exe` on the Windows boxes.

---

## 8. What I would do next, in this order

1. **Build the price ledger.** Every sweep already saves to `sourcing/searches/`. Record each one and
   compute a rolling normal range per model, so the answer stops being "here are twelve listings"
   and becomes "this one is worth buying". Free, uses tiers already paid for, and it is the only way
   to give a *buyer* history without buying a vendor.
2. **Run the first real customer sourcing request** through `--profile` and file the result in the
   ledger. Nothing else in this stack has been exercised by an actual job yet.
3. **Decide on the IMEI check** with the owner — it is the one purchase that prevents a loss rather
   than describing a market.
4. **Fund DataForSEO with the 50 deposit** when the 1.00 trial runs down. It is a deposit consumed by
   usage, not a subscription.
5. Leave Best Buy and Amazon alone until one of them costs money.

---

## 9. One thing I would not repeat

I proposed a vendor before pricing the market (SerpApi), and I built an orders reader before asking
what the account was for. Both were corrected inside a single session, and both corrections are in
this document so they do not have to be learned again: **price two candidates before recommending
one, and ask what the thing is used for before writing the code that reads it.**
