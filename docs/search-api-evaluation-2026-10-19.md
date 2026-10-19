# Search API evaluation — DeepSeek Search/Fetch vs what we run

**Date:** 2026-10-19 (measurements 22:16–22:45 UTC)
**Host measured from:** `zabz-tech` (Windows 11, pwsh 7.6.6), DSH profile `headless`
(`DSH_PROFILE=headless`, `DSH_PROFILE_DIR=C:\Users\ezabz\.dsh\profiles\headless`)
**Authority read over SSH:** `secratary-cloud` (read-only; `hostname` → `secratary-cloud`, `date -u` → `Mon Oct 19 10:16:30 PM UTC 2026`)
**Question:** is DeepSeek's own search API useful to us, and should we add or switch to it?

Every claim below carries its source: a URL I read, a command and the output line it produced, or a
file plus its mtime. Anything I did not verify is listed in **What I could not verify**.

---

## 1. What DeepSeek's search offering actually is today

**It exists, and it is new.** DeepSeek publishes two standalone JSON APIs — **Search** and **Fetch** —
under its normal bearer auth. It is **not** a `tools`/`web_search` capability on Chat Completions: the
Chat Completions schema documents `tools: null` / `tool_choice: "none"` and `tool`-role messages, i.e.
ordinary function calling only, and the docs carry Search/Fetch as their own API-Reference section
(<https://api-docs.deepseek.com/api/create-chat-completion>). Separately, DeepSeek's Anthropic-compatible
Messages endpoint does accept a server-side `web_search_20250305` tool — that is the path DSH itself uses
(see §2), and it is not the same thing as the new endpoints.

**Endpoint liveness, measured without a key** (so: no spend, no credential printed):

```
POST https://api.deepseek.com/v1/tools/search  -> http=401 time=0.321356
{"error":{"message":"Authentication Fails (missing key) ...","type":"authentication_error"}}
POST https://api.deepseek.com/v1/tools/fetch   -> http=401 time=0.326311
{"error":{"message":"Authentication Fails (missing key) ...","type":"authentication_error"}}
```

Run on `secratary-cloud` with `curl -X POST ... -d '{}'` and **no** `Authorization` header. A 401 with a
structured body (rather than 404) proves both paths are deployed and reject only at auth.

### Table: DeepSeek search — capability | documented value | source URL

| Capability | Documented value | Source URL |
|---|---|---|
| Dedicated search endpoint | `POST https://api.deepseek.com/v1/tools/search` | <https://api-docs.deepseek.com/api/search> |
| Search request | `query` (1–128 chars, required), `count` 1–50 (default 10), `ori_question` (≤128, improves query understanding), `localization` (an IP used to localise), `need_content` (bool, default false) | <https://api-docs.deepseek.com/api/search> |
| Search response | `results[]` with `rerank_score` (0–3; ≥1.5 = high quality), `title`, `url`, `snippet` (**typically 100–200 chars**), `summary` (**typically 600–800 chars**), `content` (**page content; always empty when `need_content=false`**), `site_name`, `site_icon`, `date` (RFC 3339, nullable), `authority` (0–4, −1 unknown) | <https://api-docs.deepseek.com/api/search>, <https://api-docs.deepseek.com/guides/search/> |
| Full page content from search | Only with `need_content: true`; otherwise `content` is empty. Search is snippets + a ~600–800 char model summary by default | <https://api-docs.deepseek.com/guides/search/> |
| Dedicated fetch endpoint | `POST https://api.deepseek.com/v1/tools/fetch`, body `url` (≤8192 chars, http/https, no user:pass) → `{title, content}` where `content` is **Markdown** | <https://api-docs.deepseek.com/api/fetch> |
| Query operators | `site:`, `-site:`, `-term`, `-"phrase"`, `"phrase"`, `lang:`, `after:YYYY[-MM-DD]`, `before:YYYY[-MM-DD]` | <https://api-docs.deepseek.com/guides/search/> |
| Pricing | **$0.75 per 1,000 successful requests** for Search, **$0.75 per 1,000** for Fetch. Billed per successful request, not per result; `count` does not change the price; failed calls, empty results and timeouts are not billed | <https://api-docs.deepseek.com/guides/search/>, <https://api-docs.deepseek.com/quick_start/pricing> |
| Free period | "when you use the DeepSeek API through DeepSeek Harness, Claude Code, or Codex, server-side tool calls already hit the Search and Fetch APIs. These calls are currently free of charge; **per-request billing starts at 00:00 Beijing time on November 1, 2026**" | <https://api-docs.deepseek.com/guides/search/> |
| Rate limits | Search **100 QPS**, Fetch **25 QPS**, per account, independent; Fetch additionally has a **per-domain** QPS limit. Over-limit = HTTP 429. Separate from model concurrency | <https://api-docs.deepseek.com/guides/search/> |
| Errors | 400 bad request, 401 bad key, 402 insufficient balance, 403 fetch rejected by security policy, 404 no usable page content, 408, 413, 429, 500, 504. Retry only 408/429/5xx | <https://api-docs.deepseek.com/guides/search/> |
| Result freshness | **No crawl cadence or index age is documented.** The only freshness controls are `after:`/`before:` operators, the `date` field, and the claim that `rerank_score` combines "relevance, authority, and freshness" | <https://api-docs.deepseek.com/guides/search/> |
| Jurisdiction / data handling | **No search- or fetch-specific data-handling statement exists on the Search/Fetch pages.** The general Open Platform ToS §1.1 only describes processing Input→Output; I did not find a storage-location clause there. Treat the data path as unstated, not as cleared | <https://api-docs.deepseek.com/guides/search/>, <https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html> |

**Model prices used for the cost comparison below** (deepseek-flash, per 1M tokens): cache-miss input
$0.30 peak / $0.15 off-peak; output $1.20 peak / $0.60 off-peak; cache-hit input $0.006 / $0.003;
1M context, 384K max output. Source: <https://api-docs.deepseek.com/quick_start/pricing>.

---

## 2. What we run now, measured on this machine

### 2.1 DSH MCP plane

`settings.yaml` no longer exists on this box: `~/.dsh/settings.yaml` → *"Cannot find path"* (Get-Content,
2026-10-19). The live store is the profile patch (the file itself says so at line 1752: *"On 0.1.7+ THIS
document is the settings store"*). The headless profile is `@deepseek-ai/dsh-base` +
`@deepseek-ai/dsh-headless` (`~/.dsh/profiles/headless/package.json`) plus
`~/.dsh/profiles/headless/cordis.patch.yml` (7,669 bytes, mtime 2026-10-19 18:12:35).

**This session does not mount context7 or the fetch MCP server.** The headless patch deliberately omits
them — its own comment: *"It deliberately does NOT mount `mcp-context7` or `mcp-fetch`"*
(`~/.dsh/profiles/headless/cordis.patch.yml`, lines 20–22). My session tool list agrees: jina, firecrawl,
playwright, secretary — no context7, no fetch. The **web** profile does mount all six
(`~/.dsh/profiles/web/cordis.patch.yml`, 117,764 bytes, mtime 2026-10-19 15:17:08).

Mounted search/fetch surfaces and the exact mounting line:

| Surface | Mounted as | Config line (file:line) |
|---|---|---|
| **DeepSeek native web search** | `web-search-deepseek` provider, consumed by `web_search` | `C:\Users\ezabz\.dsh\engine\node_modules\@deepseek-ai\dsh-base\cordis.patch.yml:478` — `- id: web-search-deepseek` / `name: '@deepseek-ai/dsh-web-search-deepseek'` / `config: { apiKeyEnv: DEEPSEEK_API_KEY }`; selected at `:472` (`- id: web`, `searchProvider: deepseek-official`) |
| **Native web_fetch** | `web-fetch-http` provider, consumed by `web_fetch` | same file `:483` — `- id: web-fetch-http`; tool row `:486` — `- id: tool-web`, `config: { fetch: true, searchTimeoutMs: 60000 }` |
| **jina MCP** | `serverName: jina` | `~/.dsh/profiles/headless/cordis.patch.yml:105` (`- id: mcp-jina`, `:109` `serverName: jina`), command `...\.venv\Scripts\python.exe ...\mcp_launcher.py jina`; also `profiles/web/cordis.patch.yml:1679` |
| **firecrawl MCP** | `serverName: firecrawl` | `~/.dsh/profiles/headless/cordis.patch.yml:91` (`- id: mcp-firecrawl`, `:95`); also `profiles/web/cordis.patch.yml:1664` |
| **playwright MCP** | `serverName: playwright` (headless Chromium) | `~/.dsh/profiles/headless/cordis.patch.yml:119`; also `profiles/web/cordis.patch.yml:1723` |
| **context7 MCP** | `serverName: context7` — **web profile only** | `profiles/web/cordis.patch.yml:1694` |
| **fetch MCP** (`mcp-fetch-server`) | `serverName: fetch` — **web profile only** | `profiles/web/cordis.patch.yml:1709` |
| **ps_search / esearch** | `serverName: secretary` (stdio over ssh) | `~/.dsh/profiles/headless/cordis.patch.yml:30` — `- id: mcp-secretary` … `secratary-cloud /opt/company/.venv/bin/python /opt/company/scripts/ps_mcp_server.py` |

**The load-bearing finding: our `web_search` is already DeepSeek search.** The installed provider
`@deepseek-ai/dsh-web-search-deepseek` **0.2.0-rc.2** (`lib/index.js` mtime 2026-10-08 10:16:30) calls the
Anthropic-compatible Messages endpoint:

```
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic/v1"   // lib/index.js:20
DEEPSEEK_DEFAULT_MODEL    = "deepseek-v4-flash"                        // lib/index.js:22
type: "web_search_20250305", name: "web_search", max_uses: options.maxUses   // lib/index.js:119-121
```

and its README states the cost model plainly: *"one search costs a full model turn in latency and tokens,
because DeepSeek exposes no dedicated search endpoint"* (`README.md:12`), and *"Search is a full auxiliary
model request with server-side retrieval"* (`dsh-base/cordis.patch.yml`, comment above line 472).

**That README sentence is now stale.** On 2026-10-19 the same vendor documents a dedicated
`/v1/tools/search` endpoint (401 probe above). The harness is still paying a model turn for something the
vendor now sells as a $0.75/1k HTTP call.

Exercised once from this session: `web_search({queries:["DeepSeek Search API price per 1000 requests"]})`
returned 8 sources (gigazine, pandaily, tmi等) — **URLs and titles only, no per-source snippets or dates
in the rendered result**. The provider README says snippets are joined from `cited_text` *"where an excerpt
exists"* (`README.md:65`), so snippet-less results are a supported outcome, not an error.

### 2.2 The company's own search — `ps_search` / `esearch`

| Fact | Evidence |
|---|---|
| Service | `systemctl is-active esearch` → `active`; `ExecStart=/usr/bin/python3 server/esearch.py --host 127.0.0.1 --port 3095`; `WorkingDirectory=/root/code/unified-search` |
| Endpoint | `GET /search?q=…&scope=all&limit=20[&json=1][&events=1][&host=…]`, `GET /health`, `GET /` — docstring in `/root/code/unified-search/server/esearch.py:27-29` |
| Corpora | One index over `authority.db` (sessions, VS Code chats, memories) **plus** the central estate index. `/health` `by_source` lists: `files:zabz-tech` 218,014 docs, `comms:authority` 181,295, `files:zabz-yoga` 121,075, `mail:lakewoodphoneandtech` 65,910, `git:zabz-tech` 62,891, `mail:chevedy` 26,048, `chat:vscode` 7,050, `journal` 4,914, `files:authority` 4,266, and 20 more |
| Size / freshness | `/health`: `docs: 730219`, `chunks: 5242449`, `bytes: 14252384256`, `newest_indexed_at 2026-10-19T22:03:39Z`, `age_s: 798` |
| Latency, measured | `/search` end-to-end: `mesh+broker` **0.442 s**, `battery` **2.481 s**, `journal+lock` **0.356 s** (curl `time_total`, limit=5, scope=all). `/health` itself took **7,537 ms** (`"ms":7537`) — the health probe is slow even when queries are fast |
| Client path | `ps_search` (`/opt/company/scripts/ps_mcp_server.py:596`) → `POST /tools/run/search` → `/opt/company/data/tools/search.py`, which calls `ESEARCH_URL` default `http://127.0.0.1:3095` (`search.py:68`), `TIMEOUT = 30` (`search.py:64`), falling back to `find-anything` with `degraded:` only for the live-scan cases |
| Version | `/health` → `"version": "1.1.0"` |

### 2.3 Search-provider credentials and spend

**Key NAMES only** (values never printed), from `/opt/company/.env` (304 variable names, enumerated with
`grep -oE "^[A-Za-z_][A-Za-z0-9_]*=" | tr -d "="`):

| Variable name | Provider | Wired into code? (`grep -rl`, `*.py`, excludes `.venv`) |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek (chat + native search + the new Search/Fetch) | yes — and it is the **only** secret in the DSH credential store: `~/.dsh/.credentials.yaml` (223 bytes, mtime 2026-09-11 11:30:33) has one record whose ref is `DEEPSEEK_API_KEY` |
| `FIRECRAWL_API_KEY` | Firecrawl | yes — `data/tools/firecrawl_search.py`, `scripts/procurement/providers.py`, `scripts/find-flip-deals.py` |
| `JINA_API_KEY` | Jina | yes — `scripts/procurement/providers.py`, `scripts/collect_ebay_listing_images.py`, `app/config_contract.py` |
| `SERPAPI_API_KEY` | SerpAPI | yes — `scripts/procurement/{providers,search,scrape}.py` |
| `EXA_API_KEY` | Exa | yes — `app/services/research_dispatcher.py`, `app/config.py` |
| `PERPLEXITY_API_KEY` | Perplexity | yes — `app/services/research_dispatcher.py`, `scripts/ai_cost_tracker.py` |
| `CONTEXT7_API_KEY` | Context7 | yes — `scripts/vscode-update/mcp_launcher.py` |
| `BRAVE_SEARCH_API_KEY` | Brave | **essentially unwired** — the only hit in `*.py` is a *hint string* in `app/chat_action_resilience.py:556` ("Check BRAVE_SEARCH_API_KEY in .env if Brave fails.") |
| `TAVILY_API_KEY` | Tavily | **no `*.py` reference** |
| `SPIDER_API_KEY` | Spider | **no `*.py` reference** |

**Spend / call-count signals that actually exist:**

- `/root/authority.db` `model_usage`: **277,058 rows**, grouped by provider — deepseek 136,770, deepinfra
  58,855, copilot 21,543, google 21,307, openrouter 13,208, fireworks 11,961, xai 5,116, openai 3,291,
  anthropic 3,197, minimax 1,091, groq 596, **perplexity 74**, qwen3 43, gemini 5, local 1. **This table
  records LLM calls only — there is no row for Brave, SerpAPI, Tavily, Jina, Firecrawl or DeepSeek Search.**
- Tables matching `%usage% | %cost% | %api_call% | %search% | %spend%`: `model_usage`,
  `spend_requests` (**0 rows**), `research_jobs` (**461**), `ai_cost_snapshots` (**27,026**).
- `research_jobs`: **461 jobs, 321 with `search_count > 0`, 4,675 recorded searches**, `sum(cost_usd)` =
  **$122.5773** (that is the models' cost for those jobs, not a search fee).
- Firecrawl credits, read from the account API (`firecrawl_credit_usage`): period **2026-09-22 → 2026-10-22**,
  `remainingCredits 10106`, `planCredits 1000`; historical `creditsUsed`: Jul **1,600**, Aug **655**,
  Sep **5,781**, Oct 1–19 **9,651**. Price per credit was **not** verified.

---

## 3. Table: surface | what it does | cost | limits | good at | fails at | do we use it now

| Surface | What it does | Cost | Limits | Good at | Fails at | In use now (config line) |
|---|---|---|---|---|---|---|
| **DeepSeek native `web_search`** (harness) | Auxiliary Messages call with server tool `web_search_20250305`; returns structured `web_search_result` blocks | **A full model turn** of deepseek-flash tokens + (from 2026-11-01) the same $0.75/1k search fee | `max_uses 5`/request, 8 sources exposed, no result-count knob, 60 s tool timeout | Zero setup; live index; works in every profile on every OS | Latency and cost scale with the model, not the query; snippets often absent; undocumented surface; vendor README itself is stale | **YES** — `dsh-base/cordis.patch.yml:478` (`apiKeyEnv: DEEPSEEK_API_KEY`), provider selected at `:472` |
| **DeepSeek Search API** (new) | `POST /v1/tools/search` → ranked, structured results | **$0.00075 / successful query** | QPS 100/account; 50 results; `query` ≤128 chars | Cheapest per query we can buy; no model turn; `authority`/`rerank_score`/`date` per hit; operators incl. `site:`, `after:` | Result quality unproven here (no authenticated call made); no crawl-freshness statement; PRC data-handling unstated | **NO** — not mounted anywhere |
| **DeepSeek Fetch API** (new) | `POST /v1/tools/fetch` → `{title, content}` Markdown | **$0.00075 / successful fetch** | QPS 25/account **plus per-domain**; URL ≤8192 chars; no JS | Dead simple, server-side, markdown out, bypasses our egress | 403 security policy, 404 "no usable content", no JS/auth, no screenshot | **NO** |
| **Native `web_fetch`** (`dsh-web-fetch-http`) | Local HTTP fetch → text | **$0** (our own bandwidth) | Public HTTP(S) only; no JS; no auth | Free, private, fast, works on any DSH node | Dies on JS-rendered and bot-walled pages | **YES** — `dsh-base/cordis.patch.yml:483` |
| **Jina MCP** | `read_url` (markdown, PDF, OCR), `search_web`, arXiv/SSRN search, reranker | `JINA_API_KEY` present; **unit price not verified** | Provider-side rate limits (not read) | Best reader we have: PDFs, OCR, passages, "only the answering passages" | External dependency; one more key and bill | **YES** — `profiles/headless/cordis.patch.yml:105` |
| **Firecrawl MCP** | search, scrape, crawl, map, monitor, agent | Measured: **9,651 credits used 2026-10-01→10-19**; remaining 10,106. $/credit **not verified** | Credits; crawl page limits | JS pages, interactive actions, site crawl, structured JSON | Cost and latency; the heaviest-metered surface we run | **YES** — `profiles/headless/cordis.patch.yml:91` |
| **Playwright MCP** | Real headless Chromium | $0 licence; CPU/RAM | One browser; slow; per-call timeouts | Logged-in pages, JS, clicking, screenshots | Brittle, stateful, no index — not a search tool | **YES** — `profiles/headless/cordis.patch.yml:119` |
| **context7 MCP** | Library/framework docs lookup | `CONTEXT7_API_KEY` (rate tier unverified) | Provider-side | Version-correct library docs | Only docs, not the web; **not in this session's toolbelt** | Web profile only — `profiles/web/cordis.patch.yml:1694` |
| **fetch MCP** (`mcp-fetch-server`) | Plain fetch of one URL | $0 | Node-side; no JS | Simple page reads | Redundant with native `web_fetch`; not mounted here | Web profile only — `profiles/web/cordis.patch.yml:1709` |
| **`ps_search` / `esearch`** | One index over sessions, chats, memories, comms, mail, docs, code, journal, git, filenames | ~$0 marginal (our own box) | `scope` semantics; 30 s client timeout; index age 798 s at measurement | **The only surface that can see our own corpora**; provenance (`stores`, `did_not_answer`, `age_s`) | No web; index lag; `/health` 7.5 s; refusal is not a negative | **YES** — `profiles/headless/cordis.patch.yml:30` |

---

## 4. Decision per need

### (a) An agent searching the live web

**Today: DeepSeek native `web_search` (already mounted). Worth adding: the standalone Search API as the
primary, with the native route kept as fallback.**

One line of reasoning: the native path pays a **full auxiliary model turn per search**, and from
2026-11-01 it will *also* pay the same $0.75/1k per-request fee the dedicated endpoint charges — so the
standalone endpoint is strictly cheaper per query and removes the model from the latency path, while the
only thing we give up (an LLM summarising results) we can re-add deliberately and only when wanted.

Numbers, with the assumptions stated: a deepseek-flash search turn is roughly 1–3k input tokens plus a few
hundred output tokens; at peak cache-miss rates ($0.30/M in, $1.20/M out) that is on the order of
**$0.001–0.0015 per search in tokens alone**, i.e. **1.3–2× the $0.00075 request fee**, before counting the
turn's wall-clock. **Input/output token counts per search were not measured** — the per-call figure is an
estimate from the published price card, not a reading.

Tradeoffs: money — dedicated is cheaper and its price does not grow with `count`; latency — one HTTP call
(401 round trip measured at 0.32 s) versus a model generation, so dedicated should win by seconds, but
**authenticated latency was not measured**; quality — unknown, and this is the real risk (we have no
side-by-side); failure modes — dedicated returns a documented 429/402/5xx taxonomy, while the native path
fails as `WEB_PROVIDER_ERROR` when the model does not emit a `web_search_tool_result` block, which is a
harder failure to reason about.

Do **not** remove jina or firecrawl on the strength of this document. DeepSeek's index coverage and
freshness are undocumented; keep a fallback and measure.

### (b) Fetching and reading a specific page

**Keep native `web_fetch` as the default. Add DeepSeek Fetch only as a fallback tier; keep Firecrawl and
Playwright for JS, interaction and logged-in pages. Do not switch.**

One line of reasoning: our native fetch is free and local, so a $0.00075 remote fetch is only justified when
the free one fails — and DeepSeek Fetch fails in exactly the same places a plain HTTP client does (no JS,
plus a new 403 security-policy refusal it does not document the rules for), so it is a fallback, not a
replacement.

Tradeoffs: money — near-zero today; the metered cost we actually carry is Firecrawl (9,651 credits in 19
days), so if anything is worth displacing it is Firecrawl's *simple* scrapes, not our free fetch; latency —
unknown for DeepSeek Fetch, but a remote round trip cannot beat a local GET; quality — DeepSeek returns
Markdown, which is what we want; failure modes — 403/404 are opaque, and a blocked page is indistinguishable
from a missing page without reading the error code.

### (c) Searching our OWN corpora (sessions, comms, journal, docs)

**`esearch` via `ps_search`, unchanged. DeepSeek's offering changes nothing here.**

One line of reasoning: DeepSeek's Search API indexes **the public web** — it has no path to
`authority.db`, the estate index, or the 730,219 documents we already hold, so it cannot answer "what did we
tell this customer" at any price.

Tradeoffs: money — already paid for (our own box); latency — 0.36–2.48 s measured, which is competitive with
any remote search; quality — it is the only surface with the right *corpus*, and it reports per-store age and
`did_not_answer` so a refusal cannot be mistaken for a negative; failure modes — index lag (798 s at
measurement), a slow `/health` (7.5 s), and a scope filter that can hide a real hit if aimed wrong.

The one legitimate DeepSeek use *inside* (c) is not search: use deepseek-flash to **rerank or summarise
esearch hits** (cheap tokens, our corpus stays ours). That is a separate, optional build; it is not a
replacement for the index and is not recommended before (a) is settled.

---

## 5. Build spec — `deepseek-search` plugin (only thing worth adding)

**Scope:** one plugin exposing two tools, mounted beside the existing rows; no removal of any current
surface in the first release. Do this only after the (a) decision; it is ~1 day including tests.

| Item | Value |
|---|---|
| New files | `packages/plugin-deepseek-search/package.json`, `packages/plugin-deepseek-search/lib/index.js`, `packages/plugin-deepseek-search/test/index.test.mjs` in `C:\Users\ezabz\code\harness-config` |
| Tools registered | `deepseek_search` and `deepseek_fetch` (names distinct from the existing `web_search` / `web_fetch`, so a session can see which is which) |
| `deepseek_search` input | `{ query: string (1–128), count?: 1–50 = 10, need_content?: boolean = false, ori_question?: string }`; map operator syntax straight through (`site:`, `after:`, …) |
| `deepseek_search` output | `{ results: [{title, url, snippet, summary, content?, date, authority, rerank_score, site_name}], took_ms }` — keep the vendor fields verbatim; do **not** invent an `answer` (there is none) |
| `deepseek_fetch` input | `{ url: string }` |
| `deepseek_fetch` output | `{ title, content (markdown), took_ms }` |
| Credential | `DEEPSEEK_API_KEY` from the DSH credential store (`ctx.credentials`), never from config text — the store already holds exactly that ref |
| How it fails | `401/402` → terminal error naming the credential/balance, no retry; `429` → one retry after the `Retry-After` header, else `SEARCH_RATE_LIMITED`; `403` on fetch → `FETCH_BLOCKED_BY_POLICY`; `404` → `FETCH_NO_CONTENT`; 5xx/timeout (15 s) → `SEARCH_UPSTREAM` after 2 attempts. **Never silently fall back** to jina/firecrawl — the caller chooses |
| Mount | one `insert` row in `~/.dsh/profiles/headless/cordis.patch.yml` (after `mcp-jina`, line ~105) and the mirrored row in `profiles/web/cordis.patch.yml` (after line 1692), plus the same row in `profiles/web/presets.generated.patch.yml` so presets do not drift |
| Tests | (1) unit: fixture responses prove snippet/summary/`content` mapping and that `need_content:false` yields empty `content`; (2) error map: 401/429/403/404 fixtures → the exact codes above; (3) live smoke **gated** on `DEEPSEEK_SEARCH_LIVE=1`, asserting HTTP 200 and ≥1 result, skipped by default so CI never spends; (4) no-key test asserting the process fails closed, matching the 401 probe already run |
| Rollout / rollback | mount in `headless` first; run 50 real queries against both `web_search` and `deepseek_search` and record wall-clock + hit overlap; remove the row to roll back (no other surface changes) |
| Kill criteria | if ≥20% of queries return zero results that jina finds, or if p95 latency exceeds the native path, do not ship it |

---

## 6. What I could not verify

- **Authenticated Search/Fetch behaviour and result quality.** No key was sent; only the 401 path was
  proven. Latency, snippet quality, crawl freshness and per-domain coverage for the new endpoints are
  **unmeasured**.
- **Whether the harness's native search will actually be billed at $0.75/1k from 2026-11-01.** The pricing
  note says server-side tool calls through Harness are free "currently"; I read that as ending on
  Nov 1 00:00 Beijing, but I did not see a per-endpoint statement that the Anthropic-compatible
  `web_search` server tool is billed the same way.
- **Data handling / jurisdiction for Search and Fetch.** The pages contain no search-specific statement; the
  Open Platform ToS read did not yield a storage-location clause. I did not read the full privacy policy.
- **Jina and Firecrawl unit prices.** Firecrawl credit *usage* is measured above; the dollar value of a
  credit, and Jina's per-call price, were not read.
- **How many searches we actually make per day.** Session logs are `*.jsonl.zstd` (1,758 files, 625 MB live;
  3,619 files, 1,022 MB archived) and were not decompressed; `model_usage` cannot separate a search turn
  from a chat turn.
- **The `web_search` result shape in the UI.** My single call returned titles+URLs with no snippets or
  dates; I did not establish whether that is the provider, the renderer, or the particular query.
- **Whether `dsh-web-search-deepseek` 0.2.0-rc.2 will be updated to use `/v1/tools/search`.** No upstream
  changelog was read; the installed package is dated 2026-10-08, eleven days before the endpoint was
  documented.
- **`secratary` (office box) and other nodes.** All estate measurements are from `zabz-tech` and
  `secratary-cloud`; no other host was read.
