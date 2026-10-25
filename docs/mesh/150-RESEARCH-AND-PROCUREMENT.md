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
`120ce68a1cd37f4683400909ff7ad09193e1efaa835e259d034abea7a7e3691a`) with the dispatcher wrapper
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

**Measured state of the credential:** OAuth returns `401 invalid_client`. **Cause identified
2026-10-25 from the owner's own portal screenshot: the application is labelled "Non Compliant".**
eBay's [marketplace user account deletion guide](https://developer.ebay.com/develop/guides/marketplace-user-account-deletion.md)
requires every developer to subscribe to **or opt out of** Marketplace Account Deletion *before the
first production API call*; until then the Production keyset stays disabled, and a disabled keyset
answers `invalid_client` — indistinguishable from a mistyped secret. The App ID was compared
byte-for-byte with the value the portal displays: **identical**, 40 characters, no differing
position. Remediation, in order — **one change at a time, re-running `doctor` after each**:

1. **Subscribe** — developer.ebay.com → your app → **Alerts & Notifications** → leave the exemption
   toggle OFF, set the endpoint to
   `https://api.abletelsolutions.com/webhook/ebay-marketplace-account-deletion` and the verification
   token to the contents of `/root/.secrets/ebay-deletion-token`, then Save. The label beside
   *Environment* should leave "Non Compliant".
2. If it still refuses, check the Cert ID belongs to this App ID.
3. Only then re-copy App ID + Cert ID from Keys.

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
