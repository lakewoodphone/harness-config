# B2 — Our tool stack, audited (2026-09-30)
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30

## 1. Verdict
Every external tool we pay for lives in one preset (`zabz`), while the mesh's own children (`subagent` = remote, `remoteProfile: headless`) get none of them, so the fleet cannot scrape, browse or reach `ps_*`. Of the owner's three names: keep **Firecrawl** narrowed to scrape/search, keep **Jina Reader** as the cheap reader (price now unverifiable — Elastic-owned, `/pricing` 404), and note **"Coral" exists nowhere** in the configuration, so it is a mis-transcription or something never mounted. Cheapest adequate 2026 stack: the harness's own `web_search`/`web_fetch` (193/186 of 1,611 sessions) plus Spider pay-as-you-go — **$0.23–$4.50/month** at 5–20 pages/day versus Firecrawl Standard **$83/month**. Best structural change: drop the two MCP families with no measured use (`fetch`, `context7` = 10.0 % of MCP schema bytes, ~2,200 tokens/request) and give headless workers a browse path.

## 2. What is actually mounted, by profile
`~/.dsh/settings.yaml` (read 2026-09-30) has **no MCP section**; the preset is the only source. Default preset `zabz`; model `deepseek-flash`; `maxParallelToolCalls: 20`; permission `danger-full-access`; spend-guard 35/80/150 USD, cap 12.

| Profile | Bundles | Reload | Presets | MCP servers seen |
|---|---|---|---|---|
| **web** (seat) | dsh-base, dsh-web-app + 9 local plugins (attention, -badge, cost, mobile, windows, health, mesh-http, remote-fanout, session-link) | live | cordis-bg (19 rows), yocheved (20), **zabz (26)** — injected as ROWs by `profiles/web/cordis.patch.yml` | **6**: secretary, firecrawl, jina, context7, fetch, playwright |
| **mesh** | dsh-base, dsh-headless, remote-fanout | startup | none | none |
| **headless** (mesh children) | dsh-base, dsh-headless; patch is an empty `[]` | startup | none | **none** |
| sdk / acp | documented only (`docs/mesh/62-worker-runtime.md`); no dir here | — | none | none |

`zabz` mounts all six MCP rows; `yocheved` **only `mcp-secretary`** (`presets/yocheved/agent.cordis.yml:449`); `cordis-bg` none. All are `failOnStartupError: false`, Win32-gated except `mcp-secretary-linux`. firecrawl/jina/context7 launch via `mcp_launcher.py` as **unpinned npx** (firecrawl-mcp; `mcp-remote https://mcp.jina.ai/v1` + Bearer; `@upstash/context7-mcp@latest`) with keys from `personal-secretary-mvp/.env`; fetch and playwright run **direct pinned node** from `~/.dsh/tools/mcp/node_modules` (playwright `--headless --no-sandbox`); secretary is `ssh -T secretary-ts python ps_mcp_server.py` (14 tools).

**Headless answer:** a headless worker gets the **same base tool plane** (`pwsh`, fs, jobs, goals, subagent ×2, workflow, ralph, todo, **tool-web**, skill), because `dsh-base` mounts it and only `dsh-web-app` disables it and inserts the preset roster (`docs/mesh/62-worker-runtime.md:248-288`). It lacks the preset composition: no persona, no realm, no orchestration skill, **no MCP bridge (firecrawl/jina/playwright), no `ps_*`**. `subagent` is `provider: remote-ssh, remoteProfile: 'headless'` (`profiles/web/cordis.patch.yml:192`), so that is the fleet default.

## 3. Usage evidence found
| Provider | Metric | Value | Source | As-of |
|---|---|---|---|---|
| firecrawl / jina / context7 | server starts | **114 / 199 / 103** | `personal-secretary-mvp/data/logs/mcp-launcher.log` (421 lines, created 2026-08-07, mtime 2026-09-28; **no timestamps in lines**) | read 2026-09-30 |
| firecrawl | credits; rate limit | **no usage record found** (`firecrawl_credit_usage` in 0/1,611 projections); measured **15 req/min** | projection scan; `journal/entries/lessons/L218.md:31` | 2026-09-30 |
| all MCP | fixed schema cost/request | **95 tools, 87,777 chars ≈ 21,944 tok** (firecrawl 27/39,770 · playwright 24/17,006 · jina 22/14,265 · secretary 14/7,950 · context7 2/4,665 · fetch 6/4,121) | `docs/dsh-at-scale/notes/06-multipliers.md:101-121` | measured 2026-09 |
| families | mentions of 1,611 projections | web_search **193**, web_fetch **186**, firecrawl **32**, jina **22**, fetch **5**, playwright **4**, context7 **1**, secretary **1** (titles/briefs, **not** a call log) | `~/.dsh/storages/session_projcache/sessions` | 2026-09-30 |
| all tools | per-tool **call** census | **not produced** — no call key in the cache (0/1611); a real census = decompressing **487 MB / 1,611 `.zstd`** → skipped as expensive | `~/.dsh/sessions` | 2026-09-30 |
| LLM | spend | **2,747 requests, USD 4.555924**, day 2026-09-28 | `~/.dsh/health/spend-guard.json` | 2026-09-28 |
| playwright | calls | **no usage record found**; 4 briefs instruct driving `mcp__playwright__browser_*` | projection samples | 2026-09-30 |

## 4. Fitness audit, one row per provider
| Provider | Use / best at | Failure modes | Price | Duplicates | Verdict |
|---|---|---|---|---|---|
| firecrawl (27) | scrape/search on bot-walled or JS pages (eBay `proxy: stealth`, Best Buy `intl=nosplash`, Uline); crawl/extract | 15 req/min; credit multipliers; `jsonOptions` flaky (plain `formats:["markdown"]` works); 34 % of MCP schema, 2nd-least-used big family | Free $0; Hobby $16/mo; Standard $83/mo (yearly); 1k credits/$5 | jina, harness web_fetch | **KEEP-BUT-NARROW** (no per-tool allowlist → unload crawl/map/agent/monitors/research_*) |
| jina (22) | everyday reader; `read_url` + `question`/`topk` passages; PDFs, arxiv/ssrn | **eBay returns an Error Page** (`docs/mesh/61-buy-list-verified.md:841`); no JS; per-token billing; price unpublished | **NOT VERIFIED** (`/pricing` 404; Elastic) | firecrawl scrape, mcp-fetch, harness web_fetch | **KEEP** |
| context7 (2) | library/API docs | 1/1,611 use; duplicates web search | not read | harness web_search/web_fetch | **REPLACE (drop)** |
| fetch (6) | raw X/HTTP fetch, YouTube transcripts | covered by harness `web_fetch` + jina; 5/1,611 use | $0 local OSS | harness web_fetch, jina | **REPLACE (drop)** |
| playwright (24) | only real browser driver; audits, clicking portals | headless `--no-sandbox`; **no persistent logged-in profile**; browser may be absent on a fresh machine; heavy | $0 (OSS, installed) | nothing | **KEEP**, then **ADD** persistent profile + screenshot→vision |
| secretary (`ps_*`, 14) | company DB/API (status, db_query, ceo_chat, action) | `ps_health` ~90 KB poisons context (use `ps_company_status`); failures arrive `isError:false`; `ps_action` sends SMS | internal $0 | nothing | **KEEP** (also for headless) |
| harness web_search/web_fetch | default search/fetch, most-used path | JS-blind; truncates to nav on commerce pages; text lands in the token bill | $0 marginal | firecrawl/jina/mcp-fetch | **KEEP as default; escalate** |
| "Coral" | — | no tool/server/row/package/doc of that name exists; nearest `firecrawl_crawl`, context7 | — | — | **ASK THE OWNER** |

## 5. Search, fetch and scrape comparison (vendor pages read 2026-09-30)
| Provider | What it does | Price | Best for | Weaknesses | Source |
|---|---|---|---|---|---|
| Firecrawl | search/scrape/crawl/extract/agent/monitors | Free $0; Hobby $16/mo; Standard $83/mo (yearly); extra 1k credits/$5 | unblocking, JS, extract | multipliers, 15 req/min, credits expire | firecrawl.dev/pricing |
| Jina Reader | read (`r.jina.ai`), search, images, arxiv/ssrn, PDF | **not published** (404) | cheapest read, passages | no JS, eBay-blocked, opaque price | jina.ai/reader |
| Exa | neural search, contents, agent, monitors | Search $4/1k instant–$15/1k deep; Contents $1/1k pages; Agent $0.012–$1/run; $10 free/mo | search quality, cheap contents | no JS/unblock | exa.ai/pricing |
| Tavily | search/extract/crawl/research | Free 1,000 credits/mo; $30/4k; $100/15k; $220/38k; $500/100k; PAYG $0.008/credit | agent-native search+extract | help page "updated 1 year ago" | help.tavily.com |
| Brave Search API | index + LLM context | $5/1k requests; Answers $4/1k + $5/M tok; $5 free/mo | cheapest quality SERP | no scraping/JS | brave.com/search/api |
| Serper | Google SERP | 2,500 free queries; **price not read** (404) | cheap Google SERP | one engine | serper.dev |
| SerpAPI | multi-engine SERP | Free 250/mo; $25/1k; $75/5k; $150/15k; $275/30k | engine coverage | priciest per search | serpapi.com/pricing |
| Bright Data | Unlocker, SERP, Browser API, Scraper APIs, proxies | from $1/1k req; Scraper APIs from $0.75/1k rec; Browser from $5/GB | hardest unblocking, managed browser | enterprise pricing, multipliers | brightdata.com/pricing |
| Apify | actor marketplace | **not read** (JS page) | ready-made actors | credit complexity | apify.com/pricing |
| ScrapingBee | scrape + JS + proxies | **not read** (JS page); Spider claims $49+/$99–249/$599+ (third party) | simple scrape + JS | multipliers claimed | scrapingbee.com/pricing |
| Olostep | scrape/crawl/map/batch/search/answer | Trial $0/500; Starter $9/5k; Standard $99/200k; Scale $399/1M; packs 10k/$20, 250k/$200, 2M/$1,000 | JS + residential default, cheap at volume | low trial limits, young | olostep.com/pricing |
| ScrapeGraphAI | scrape/extract/search/crawl/monitor | Free 500 credits; Starter $17/10k; Growth $85/100k; Pro $425/750k (scrape 1, extract 5, stealth +4) | prompt-to-JSON extraction | credit burn | docs.scrapegraphai.com |
| Spider | scrape/crawl/search/screenshot/unblock/browser | PAYG $1/GB + $0.0001/min ($1 = 10k credits); /scrape ≈$0.0001, /search ≈$0.001; credits never expire | cheapest metered reads | smaller ecosystem | spider.cloud/guides |
| Self-hosted: Crawl4AI, Playwright + trafilatura, Docling, SearXNG, Firecrawl OSS | crawler / browser+extraction / doc parse / metasearch / OSS Firecrawl | $0 licence (only Crawl4AI's page was read; licence texts **not verified**) | offline/bulk work on our Linux node; private search | we run and maintain them | github.com/unclecode/crawl4ai; §10 |

**Our two dominant needs.** (a) *Search + read 5–20 pages/day*: **best** Exa ($4/1k searches + $1/1k contents, one key); **cheapest adequate** harness `web_search`/`web_fetch` ($0 marginal) plus **Spider PAYG** for the JS/blocked minority (~$0.03/month at 10 pages/day). (b) *Drive a real browser into a portal*: **best** the **Playwright MCP we already mount** ($0, installed, full a11y-tree automation) once given a persistent `--user-data-dir`; managed alternative **Bright Data Scraping Browser $5/GB**; **cheapest adequate** the same Playwright row — one browser process, no subscription.

## 6. Gaps that stop a 24/7 agent
| Gap | Best 2026 tool | Source | Unlocks |
|---|---|---|---|
| Mesh/headless workers have **no MCP browse path** | dsh-base + a patch profile re-inserting what `dsh-web-app` disables | `docs/mesh/62-worker-runtime.md:270-288` | every child can scrape/browse/`ps_query` |
| **Persistent logged-in browser sessions** | Playwright `--user-data-dir`; managed: Bright Data Scraping Browser $5/GB | local config; brightdata.com/pricing | supplier portals, seller tools |
| **Screenshot/vision on arbitrary pages** | Playwright `take_screenshot` (mounted) + the seat's image reader | local tool list | image-rendered prices/PDFs, proof |
| **Schema-validated extraction at scale** | Firecrawl `extract` (mounted); ScrapeGraphAI 5 credits; Spider `/transform` $0.0001/obj | firecrawl.dev/pricing; spider.cloud/guides | supplier pages → rows |
| **A code sandbox that is not the host** | `dsh-bash-sandbox` + container on the Linux node (installed here) | local `profiles/node_modules` | untrusted code without `danger-full-access` |
| **A browser that runs on the server** | headless Playwright on the authority, or Spider cloud browser $0.0001/min + $1/GB | spider.cloud/guides | 24/7 polling, nobody logged in |
| **Vector search over our own corpus** | embeddings + local vector store (company already has ChromaDB via `ps_memory_search`) | `presets/zabz/agent.cordis.yml` | semantic recall over journal + sessions |
| **GitHub API at the seat** | a GitHub MCP server (not mounted; **not read this session**); mail via `ps_*` | preset MCP rows | PR/issue triage without a browser |

## 7. Monthly cost arithmetic per candidate stack
Assumption (the brief's): **10–50 sessions/day × 5–20 reads** = 50–1,000 reads/day = **1,500–30,000 reads/month**.
**A status quo:** Firecrawl Standard $83/mo + Jina (unknown) + context7 (unverified) + Playwright $0 ⇒ flat **$83/mo**. **B harness-only:** $0 vendor cost; 30,000 pages ≈ 39 M tokens of page text — a context bill, not a vendor bill. **C Spider PAYG:** 1,500 × $0.0001 = $0.15 + 75 MB × $1/GB = $0.08 ⇒ **$0.23/mo**; 30,000 ⇒ $3.00 + 1.5 GB = $1.50 ⇒ **$4.50/mo**. **D Brave + harness fetch:** 1,500 × $5/1k = **$7.50**; 30,000 = **$150**. **E Exa:** (1,500 × $4/1k) + (1,500 × $1/1k) = $6 + $1.50 = **$7.50**; 30,000+30,000 ⇒ $120 + $30 = **$150**. **F Tavily PAYG:** 1,500 × $0.008 = **$12** (free tier covers 1,000); 30,000 = **$240**. **G Firecrawl Hobby:** $16 covers 5,000 pages ⇒ **$16/mo**; 30,000 ⇒ ~25,000 extra credits × $5/1k = $125 ⇒ **$141/mo**. **H Olostep:** Starter $9 covers 5,000 ⇒ **$9/mo**; 30,000 ⇒ Standard $99 ⇒ **$99/mo**. **I ScrapeGraphAI:** Starter $17 = 10,000 credits ⇒ **$17**; Growth $85 = 100k ⇒ **$85**. **J self-host:** **$0/mo** + existing compute.
**Rank:** B $0 → C $0.23–4.50 → D $2.50–150 → E $7.50–150 → H $9–99 → F $12–240 → G $16–141 → I $17–85 → A $83+. Spread **under $20/month**; the real cost is the ~22k-token MCP catalog and an $83 floor on a plan we may not be using.

## 8. Redundancy and consolidation
*Readers:* mcp-fetch (6 tools), jina `read_url`, firecrawl `scrape`, harness `web_fetch`. *Searchers:* harness `web_search`, jina `search_web`, firecrawl `search`, context7. *Extractors:* firecrawl `extract`, jina `primer`. Unique: `mcp-playwright`, `mcp-secretary`. **Largest cut with no measured capability loss: disable `mcp-fetch` and `mcp-context7`** — 4,121 + 4,665 = **8,786 of 87,777 MCP schema chars (10.0 %)**, ≈**2,196 of ~21,944 tokens off every request**, against 5/1,611 and 1/1,611 use, both covered by harness + jina. Second-order: pick **one** general reader (both mounted = 54 tools / 54,035 chars of overlap; the row shape has no per-tool allowlist).

## 9. Candidate improvements
1. **TS-1 Drop `mcp-fetch`** (regenerate the patch): 6 tools/4,121 chars, 5/1,611 use, duplicated. S · ~1.0k tok/request · RISK lose transcripts · §3/§8 · edit, then `make-preset-rows.mjs --check`.
2. **TS-2 Drop `mcp-context7`**: 2 tools/4,665 chars, 1/1,611 use. S · ~1.2k tok/request · RISK none measured · §3 · same batch as TS-1.
3. **TS-3 One reader, not two**: 54 overlapping tools / 54,035 chars. M · up to ~13.5k tok/request, one vendor less · RISK losing unblocking or cheap bulk reads · §4/§5 · tally invocations (needs TS-7).
4. **TS-4 Give mesh/headless children the browse path**: `subagent` = remote `headless`, so the fleet cannot scrape or reach `ps_*`. M · children become real researchers · RISK ~22k extra tokens/child; must be a profile, not a bundle edit · `docs/mesh/62-worker-runtime.md:192-288` · `dsh --profile <new> --dump-config`.
5. **TS-5 Persistent Playwright profile + screenshot→vision**: logins die with each browser today. S/M · logged-in portals · RISK stored credentials · local row · add `--user-data-dir`, run one login by hand.
6. **TS-6 Pin the three npx MCP servers locally** under `~/.dsh/tools/mcp`: `npx -y` + `@latest` hits the registry per start (~3–4 s measured) and can drift. M · start latency, reproducibility · RISK manual upgrades · `mcp_launcher.py` · extend `provision-mcp-tools.ps1`.
7. **TS-7 Timestamp the MCP launch log + per-tool call counter in the session projection**: the log is today the only usage record for firecrawl/jina/context7, and a real census costs 487 MB of zstd. S+M · usage over time, evidence-based narrowing · RISK schema bump · log + cache scan · one-line edit, then the writer.
8. **TS-8 MCP cost guard + one search tool**: spend-guard is LLM-only (2,747 req/$4.56 on 2026-09-28), `credit_usage` is never called, three search families cost ~22k tokens. L · no silent credit burn, token cut, predictable fallback · RISK a wrapper that hides failures · `health/spend-guard.json`, §4/§8 · nightly `firecrawl_credit_usage` → `~/.dsh/metrics/`.

## 10. Not verified, and why
**Jina price** (`/pricing` 404; Elastic-owned) · **Serper price** (404) · **Apify and ScrapingBee prices** (client-rendered; ScrapingBee's only figures are Spider's third-party comparison) · **Firecrawl Growth/Scale credit maths** (page truncated) · **Context7 pricing** (no page read) · **self-hosted licences** (no licence text read) · **Firecrawl/Jina credit balances** (no local record) · **per-tool call counts** (skipped: 487 MB of `.zstd`; every number above is a server start or session mention, not an invocation) · **Playwright call counts** · **what "Coral" is** (nothing in `~/.dsh` or `harness-config` matches; grep covered presets, packages, docs, scripts, journal) · **sdk/acp profiles** (documented only).

## 11. Sources (read 2026-09-30 unless dated)
- Config: `~/.dsh/settings.yaml`; `~/.dsh/.agent-presets/{zabz,yocheved,cordis-bg}`; `~/.dsh/profiles/{web,mesh,headless}/package.json` + `cordis.patch.yml`; `harness-config/profiles/web/{cordis.patch.yml,presets.generated.patch.yml}`; `presets/zabz/agent.cordis.yml`; `presets/yocheved/agent.cordis.yml:449`.
- Evidence: `mcp_launcher.py` + `data/logs/mcp-launcher.log`; `docs/mesh/62-worker-runtime.md:248-288`; `docs/dsh-at-scale/notes/06-multipliers.md:101-125`; `docs/mesh/61-buy-list-verified.md:841`; `journal/entries/lessons/L218.md:31`; `~/.dsh/health/spend-guard.json`; `~/.dsh/storages/session_projcache/*`; `~/.dsh/sessions`.
- Prices: [firecrawl.dev/pricing](https://www.firecrawl.dev/pricing) · [jina.ai/reader](https://jina.ai/reader/) + [/pricing 404](https://jina.ai/pricing) · [exa.ai/pricing](https://exa.ai/pricing) · [help.tavily.com](https://help.tavily.com/articles/8816424538-pricing) · [brave.com/search/api](https://brave.com/search/api/) · [serpapi.com/pricing](https://serpapi.com/pricing) · [brightdata.com/pricing](https://brightdata.com/pricing) · [olostep.com/pricing](https://www.olostep.com/pricing) · [docs.scrapegraphai.com](https://docs.scrapegraphai.com/knowledge-base/account/pricing) · [spider.cloud pricing guide](https://spider.cloud/guides/pricing-and-plans/) (8 Mar 2026) · [github.com/unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) · [serper.dev/pricing 404](https://serper.dev/pricing) · [apify.com/pricing](https://apify.com/pricing) + [scrapingbee.com/pricing](https://www.scrapingbee.com/pricing/) (no prices rendered).
