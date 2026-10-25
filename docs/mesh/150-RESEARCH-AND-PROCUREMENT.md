# 150 — ONLINE RESEARCH AND PROCUREMENT: what exists, what works, what is dead

**Written 2026-10-23.** Every line below was measured in that session; commands and outputs are in
the journal entry `H`/`L` pair written the same day. Read this before building a scraper, a
supplier search, a price sweep or a research pipeline — four of the surfaces named here look like
they exist and do not.

---

## 1. Online research

| surface | where it lives | state (2026-10-23) |
|---|---|---|
| **`ps_search` / esearch** — one index over every DSH session, customer comms, mail, journal, memories, VS Code chats, and the estate document/code index | `ps_search(query, what=…)` MCP tool on the authority | **LIVE.** Answered in 306 ms across 5 stores in this session. This is the first thing to reach for; `searched:false` is a refusal, never a negative. |
| **`ps_action("web_search")`** — the company's own web search | company action dispatch; provider recorded per call | **LIVE.** Returned 3 live results for a price query, including eBay item pages with prices. `provider` is in the response — quote it. |
| **Firecrawl** (scrape / crawl / map / search / agent / monitor) | MCP server `firecrawl` on every agent | **LIVE** and the working method for pages that block plain fetches. `proxy: stealth` renders eBay **search and item** pages; eBay **sold/completed is login-gated** and unreadable (lesson `L2386`). JSON-extraction mode fails on eBay search pages (context limit) — use markdown. |
| **Jina** (read_url, search_web, search_arxiv, search_ssrn, extract_pdf, screenshot) | MCP server `jina` | **LIVE.** Cheapest way to read one page as markdown with a question; `search_arxiv`/`search_ssrn` for literature. |
| **Playwright browser** | MCP server `playwright` | **LIVE.** Use when a page needs a session or a form; the persistent-profile assistants below are built on it. |
| **`browser_use_agent.py`** — LLM-driven browser with a per-task site allowlist (includes `ebay-seller: ["*.ebay.com"]`) | `personal-secretary-mvp/app/services/` | present |
| **`research_dispatcher.py`** (130 KB) + **`deep_research.py`** (18 KB) — budget-gated, provider-routed research jobs writing markdown/JSON under `docs/research/` | `personal-secretary-mvp/app/services/`; CLI `python -m app.services.research_dispatcher <directive> --model auto` | **PRESENT BUT IDLE.** `research_jobs` on the authority: 324 `complete`, 70 `queued`, 51 `failed`, 11 `partial`, 3 stuck in `running` since 2026-07-03, 2 `refused`. **Newest `submitted_at` is 2026-07-08T05:40:32Z** — the pipeline has submitted nothing for over three months. Before trusting it, run `--providers` and check `research_jobs` again; an empty `queued` backlog is not evidence that it is unhealthy, but 70 queued rows from May-July is. |
| **`hardware_repair_researcher.py`, `summarize_page.py`, `research_doc_writer.py`, `research_deliverable_tracker.py`** | `personal-secretary-mvp/data/tools/` | present; `hardware_repair_researcher` uses the keyless DuckDuckGo instant-answer API, so treat its coverage as thin |
| **Research directives** | `personal-secretary-mvp/docs/research/directives/` | the input format the dispatcher consumes |

**Trap:** the research dispatcher is the estate's most complete research machinery and it has been
silent since July. A session that "sets up research" without checking `research_jobs` will build a
fourth one. Check the table first.

---

## 2. Procurement and sourcing

### 2.1 eBay — use the API (new 2026-10-23)

`lpt-hub/scripts/sourcing/ebay_api.py` — stdlib-only Browse API client plus `doctor`, `selftest`,
`search`, `item`, `conditions`. Deployed to the authority as
`/opt/company/data/tools/ebay_api.py` (byte-identical, sha256
`1fc783361f5d0062391ff7ebe2d443a790dfe22e5cc6d35f0edada56344b8c17`) with the dispatcher wrapper
`ebay_browse_search.py`, so company agents can search eBay without a browser.

```
python ebay_api.py doctor        # is the keyset working; names what is checkable and what is not
python ebay_api.py selftest      # proves the client with no credentials and no network: 17/17
python ebay_api.py search "latitude 5420" --condition 2000,2010,2020,2030 --target-sell 320 --profit --save
python ebay_api.py item 147473202913 --save
```

**Credentials** — env `EBAY_APP_ID` / `EBAY_CERT_ID` / `EBAY_DEV_ID` → `$EBAY_SECRETS_FILE` →
`~/.secrets/ebay-personal.env` (0600; ACL-restricted on Windows). Installed 2026-10-23 on
ZABZ-YOGA, ZABZ-TECH, `zabz-tech-linux`, and `secratary-cloud:/root/.secrets/ebay-personal.env`.
Pair fingerprint `a47e8d3196e8` (sha256[:12]) is identical on all four — that fingerprint is the
safe thing to quote, never the values.

> **The sha in decision `D10049` is the pre-fix value `a068cc…1db`.** Ten minutes after that decision
> was written, the module's selftest fixtures were found to contain the real keyset and were replaced
> with synthetic ones — that is the whole point of `P13b`/`P2938`, since a real credential in a test
> is a credential in a public repo. **This line and the module docstring are authoritative**; a
> future session that finds a mismatch re-deploys from `lpt-hub` and updates this line.

**STATE 2026-10-25: WORKING.** The keyset authenticates and Browse answers from both the authority and
the workstations. The blocker was never the credentials — it was a **disabled keyset**. The portal
labelled the application "Non Compliant", and eBay disables Production keysets until the application
subscribes to **or opts out of** Marketplace Account Deletion
([eBay's guide](https://developer.ebay.com/develop/guides/marketplace-user-account-deletion.md)).
Once the endpoint below was saved, `doctor` went from `401 invalid_client` to a token in ~200 ms.
Verified the same day: 13 consecutive token requests, 0 refusals, 0 transport errors.

| check | result 2026-10-25 |
|---|---|
| OAuth application token | issued in 158–324 ms |
| Browse `item_summary/search` | 4,763 live results for "dell latitude 5420" |
| `conditionIds:{2010}` filter honoured | 138 matches, every one condition 2010 |
| workstation and authority | both green |

**The compliance endpoint** (live, challenge-verified): `GET/POST` on
`https://api.abletelsolutions.com/webhook/ebay-marketplace-account-deletion`, handled by
`personal-secretary-mvp/app/services/ebay_account_deletion.py`; verification token at
`/root/.secrets/ebay-deletion-token` (0600) and `~/.secrets/ebay-deletion-token` on the workstations.
Routes live under `/webhook/` because `_api_access_guard` already leaves that prefix public and every
handler verifies itself.

**What we do NOT claim:** the "Exempted from Marketplace Account Deletion" opt-out. Its wording is
*"I do not persist eBay data"*, and the sourcing ledger keeps `seller_ledger.seller_name` — a display
name tied to an eBay user account. Claiming it would be a false declaration under a page that warns
of penalties or account disablement. Deletions are answered by anonymisation: the matching
`seller_name` becomes `[deleted-user]` with `seller_name_redacted_at`, and the commercial record
survives. Run `python -m app.services.ebay_account_deletion --redact <username>` on a host that holds
the ledger — **the authority records a request but cannot redact it**, and says so in its own result
rather than reporting success.

**The filter trap, measured 2026-10-25.** eBay's Browse filter key is **`conditionIds`**;
`conditions:` is accepted and **silently ignored**, returning 2,671 items across every condition while
`conditionIds:{2010}` returned the correct 138. A wrong filter key is not an error at eBay — it is an
unfiltered answer that looks filtered, which is exactly how a sourcing sweep prices the wrong tier and
never notices (`L2386` is the same failure from the scraping side). `doctor` now runs a live
filter-honoured check: ask for 2010, assert every returned `conditionId` is 2010.

**Why subscribe and not the exemption** — corrected 2026-10-25 after reading eBay's guide properly.
The opt-out wording is *"I do not persist eBay data"*, and the sourcing ledger
(`sourcing/listings/*.json`) keeps `title`, `price`, `condition`, image URLs and
`seller_ledger.seller_name`. A seller display name is tied to an eBay user account — exactly the data
a deletion request concerns — and the portal warns that incorrect information "may result in
penalties or having your account disabled". So we subscribe. **This supersedes the opt-out advice in
lesson `L13440`**, which was wrong on that point.

**The endpoint is live and proven.** `personal-secretary-mvp/app/services/ebay_account_deletion.py`,
routes under `/webhook/` (already public in `_api_access_guard`, every handler verifying itself).
Verified 2026-10-25 over the real public hostname: `GET ?challenge_code=…` returned `200` with a
`challengeResponse` equal to a SHA-256 computed independently on the calling machine, both before and
after a clean `company-api` restart; `POST` of a synthetic notification returned
`{"ok":true,"recorded":true}`. Selftest 13/13.

**Deletion handling is anonymisation, not deletion:** the matching `seller_name` becomes
`[deleted-user]` with `seller_name_redacted_at`, and the commercial fields survive — a closed
account does not retract the fact that the listing was inspected. **The authority records a request
but cannot redact it**, because lpt-hub is not checked out there; the handler reports
`"note": "no ledger directory"` rather than pretending. Run
`python -m app.services.ebay_account_deletion --redact <username>` on a host that holds the ledger.

**Do not build on the dead surfaces — measured, not assumed:**

| surface | measured 2026-10-23 |
|---|---|
| `open.api.ebay.com` — legacy **Shopping** API, still called by `personal-secretary-mvp/data/tools/laptop_sourcing_order_executor.py` | **DNS: no such host.** The hostname no longer exists. |
| `api.ebay.com/ws/api.dll` — Trading XML | **HTTP 410 Gone** |
| eBay sold/completed listings | login-gated; not in the public Browse scope |

### 2.2 The other procurement surfaces

| surface | where | state |
|---|---|---|
| **procurement-assistant** — Playwright, persistent Chrome profile per site, for **Alibaba / AliExpress**: search snapshots, watchlist, supplier registry, inquiry drafting, guarded order staging (reaches checkout, never clicks pay) | `lpt-hub/scripts/procurement-assistant/` (478 KB, last touched 2026-05-15) + `README.md` (496 lines) | present; needs a per-site interactive `login` before use |
| **marketplace-assistant** — Playwright, **Facebook Marketplace** seller threads (no official messaging API) | `lpt-hub/scripts/marketplace-assistant/` (202 KB, 2026-04-09) | present; tuned for the treadmill sourcing workflow |
| **sourcing ledger** — listings, searches, image-sets, QC reports, `laptop-buying-knowledge.json`, `seller-ledger.json` | `lpt-hub/docs/customer-operations/sourcing/` | live; `README.md` corrected 2026-10-23 |
| **`alibaba_onetalk_automation.py`** | `data/tools/` | present |
| **`electronic_part_scout.py`** | `data/tools/` | **PLACEHOLDER.** 94 lines returning two hardcoded mock parts ("Placeholder for real part lookup"). Any agent quoting it has invented inventory. |
| **`source_auth_manager.py`** (all actions simulated, `authenticated: True` hardcoded) and **`scraper_auth_manager.py`** (0 consumers; `data/scraper_auth.json` does not exist) | `data/tools/` | **do not use either as a credential store** |

### 2.3 The four scripts that do not exist

The sourcing README used to instruct: `find-flip-deals.py`, `ebay_laptop_search.py`,
`laptop_sourcing.py`, `collect_ebay_listing_images.py`. Measured 2026-10-23: absent from `lpt-hub`
git history on **every ref** (`git log --all -- <path>` → empty) and absent from the estate file
index. The only two places the names survive are the old README and a 2026-09-17 session transcript
in which a previous agent was already searching for them. They were never committed, or they lived
in a working tree that no longer exists. **Do not cite them as existing capability.**

---



## 2.4 Where marketplace data can actually be had — measured 2026-10-25

Sourcing research means asking, programmatically: *what is this part or machine costing across the
places we buy from?* This is the map of what answers that, as of 2026-10-25. Each verdict is either
something tested with our own keyset or attributed to the vendor's own documentation.

| marketplace | can we research it programmatically? | how |
|---|---|---|
| **eBay — active listings** | **YES, working** | `ebay_api.py search`. Live: 4,763 results for "dell latitude 5420". |
| **eBay — category vocabulary** | **YES, working** | Taxonomy API, `get_default_category_tree_id` → tree `0` version `134`. Gives category ids and aspect definitions, so a query can be built from eBay's own vocabulary rather than guessed keywords. |
| **eBay — market characterisation** | **YES, working** | `search --aspects` sends `fieldgroups=ASPECT_REFINEMENTS` and returns aspect groups with match counts. Measured on "latitude 5420 screen": 606 matches, 256 at 14 in, 206 at 1920x1080, 96 LED LCD, 34 CCFL, **156 with no panel technology stated**. A sweep can now describe a market instead of listing rows. |
| **eBay — bulk item feeds** | **NO with this keyset** | `/buy/feed/v1/item`, `/item_snapshot`, `/item_group` all return **404 "Resource not found"**. Do not promise daily category dumps. |
| **eBay — sold/completed comps** | **NO API** | The Finding API (`findCompletedItems`) was decommissioned **2025-02-04**; Browse replaced it but does not reproduce sold search; Marketplace Insights is **Limited Release, not open to new applicants**, possibly reachable only through an eBay account manager (third-party source: compsniper.com). Sold comps remain a UI job (Terapeak) or a paid vendor. |
| **Amazon** | **NOT as documented by most guides** | **PA-API 5.0 is deprecated**; Amazon's own docs say calls now get `403 AccessDeniedException` and point to the **Creators API**, which rides on an Amazon Associates account. Paid alternates: **Keepa** (Amazon-deep: sales rank, seller and long price histories) or a multi-retailer vendor. |
| **Laptop screens / repair parts** | **NO distributor API** | MobileSentrix and Injured Gadgets integrations exist only *inside* POS products (RepairDesk, RepairQ). Research panels through eBay aspects + the suppliers' own portals. |
| **Newegg** | **NO official product API found** | Only third-party scrapers. Treat any Newegg data as scraped evidence with a timestamp. |
| **Back Market** | **Seller-side only** | Its API is a *seller* API — three separate platforms (EU / US / AP), each with its own account, token and sandbox. It is not a research catalogue of other people's prices. |
| **Best Buy** | **Limited** | A developer API exists but does not expose store-level stock; used/refurb inventory is not researchable that way. |
| **Walmart** | **Possibly** | Marketplace (seller) and Affiliate/Catalog (consumer) APIs exist, with OAuth and RSA-signature auth. Worth a trial if retail benchmarking matters. |
| **Electronic components** (board-level repair) | **Priced out** | Nexar/Octopart: evaluation tier is **100 parts lifetime**; the useful tiers run to hundreds or thousands per month. Priced for engineering firms, not a repair shop. |

**The practical research stack, in order:** eBay Browse + Taxonomy + aspects (free, ours, proven) →
licensed scraping with Firecrawl `proxy: stealth` for the marketplaces with no API (proven on eBay
pages; sold/completed stays gated) → one paid price-history vendor **if** Amazon or multi-retailer
history becomes load-bearing. Do not build a scraper where an API exists, and do not buy an API where
the data is a login-gated UI.

**Two research rules that have already cost money here:** a model number matches its own *parts*
(the first "latitude 5420" ladder read returned a 122 motherboard as the cheapest "laptop"), and eBay
silently ignores a filter key it does not recognise (`L13504`), so a sweep must assert what came back.

---


### 2.4b What actually reaches the market, measured 2026-10-25 (after the owner pushed back)

The owner's correction, verbatim: *"Don't you dare limit yourself… anything you can't do via API you
can do via normal web browsing — set this up in cascading systems."* He was right, and the estate
already held the keys: `FIRECRAWL_API_KEY` and `SERPAPI_API_KEY` in `/opt/company/.env` were never
wired into sourcing.

**The stack that now exists** — `lpt-hub/scripts/sourcing/`:

| file | role |
|---|---|
| `ebay_api.py` | eBay Browse API: listings, conditionIds, aspect distributions. Free, ours. |
| `dataforseo.py` | **Google Shopping at 0.001 per query** (measured). The cross-retailer tier. |
| `fetch_ladder.py` | Per-site escalation: `firecrawl_json → firecrawl_markdown → playwright → browser_service`, with `capabilities.json` remembering which tier won. |
| `sourcing_fanout.py` | One query, every source at once, classified into whole / part / accessory. |

**Measured costs and coverage (this session, on our own accounts):**

| tier | cost per query | reaches |
|---|---|---|
| eBay Browse API | free | eBay only, but with condition tiers and aspects no buyer-facing page exposes |
| DataForSEO Google Shopping | **0.001–0.002** | eBay, Walmart, Target, Back Market, Newegg, Swappa, Mercari, TikTok Shop, AliExpress, Parts-People, Bliss Computers, LaptopScreen.com, PCLiquidations, Neobids |
| SerpApi (fallback) | 0.025 (free plan: 250/month) | similar breadth; kept only as a fallback once DataForSEO works |
| Firecrawl site scrape | ~5 credits (9,926 left) | the specific site, including JS-rendered pages |

**Two live runs, same session:** "latitude 5420 16gb" → 48 offers across 5 sources in 45 s;
"latitude 5420 lcd screen fhd" → 24 part offers, from 34.99 to 59.00, spanning eBay sellers,
AliExpress, LaptopScreen.com, Newegg and aqscreenlcd.

**Where it still fails, and what that cost:**

* **Best Buy** — its JSON tier returns titles with no prices, its markdown tier fabricates a product
  out of a spec bullet, and Playwright renders a page our parser cannot price. Google Shopping
  surfaces a Best Buy price only sporadically (1 row in 80 for a Latitude). Recorded `partial`, and
  the ladder reports it as partial rather than filling the table with question marks.
* **Amazon via DataForSEO** — `/merchant/amazon/products/live/advanced` returns `20000 Ok` with 0
  items and 0 cost across three payloads, one naming `language_code` as invalid although their docs
  list it. **Not wired in.** Amazon stays on the Firecrawl tier, which returns prices. A support
  ticket was considered and deliberately not filed: the working path already exists.
* **Google's own shopping page cannot be scraped** — Firecrawl fails on
  `google.com/search?tbm=shop` across every engine it has. That is why a paid SERP tier is needed at
  all, rather than free scraping.
* **DataForSEO's Databases product is not the API** — it sells on-premises SERP database dumps
  (Amazon included) for bulk historical work, purchased per database. It does not answer "what does
  this cost right now".

**The rule this section exists to enforce:** "no public API" describes one access route, not the
market's readability. Before saying "I cannot see that", walk the ladder — API, aggregator, stealth
scrape, browser — and report which tier answered, which failed, and what it cost.

---

## 3. The two rules that outrank any of this

1. **Never send a customer a marketplace link, source price, margin, seller name, item number,
   ASIN or listing id.** Customer-facing: brand + broad product family, new/refurb status, the LPT
   total, what is included, and plain-English tradeoffs. (`personal-secretary-mvp/AGENTS.md`.)
2. **Grade and price are not monotonic in the used market.** Price the refurbished ladder
   (`2000`/`2010`/`2020`/`2030`) rather than assuming a better grade costs more; a guarantee that
   matches what your QC gate tests beats a tier that merely permits it. Lesson `L2386`.

---

## 4. Using something here

| need | use | do not |
|---|---|---|
| find what we already know | `ps_search` | grep the repos |
| a price or listing right now | `ebay_api.py search` | write another scraper |
| a page the API cannot reach | Firecrawl `proxy: stealth` → markdown | trust a JS-rendered fetch |
| a long multi-source answer | `research_dispatcher.py` **after** checking `research_jobs` | commission a fourth research pipeline |
| a supplier conversation (Alibaba) | `procurement-assistant` draft + confirmed send | auto-send |
| customer-facing words | `CUSTOMER-SMS-RUNBOOK.md`, body shown first | any automation as the sender |
