# Agent search path — one command, no new MCP family (2026-09-30)

**Node:** `zabz-yoga` (ZABZ-YOGA). **Owner files:** `scripts/search/` (all),
`docs/agent-search-20260930.md`.

## The problem this closes

The owner pays for five search providers (Tavily, Exa, Brave, SerpAPI,
Perplexity) and the application uses them, but the agent tool surface can reach
**none** of them: the seat falls back to the harness's own `web_search` plus
firecrawl/jina MCP, and headless mesh children have no browse path at all. The
six mounted MCP families already cost **87,777 characters of tool schema,
≈21,944 tokens, on every request that sees them**. Adding a seventh MCP family
would make that tax worse. This is one small stdlib-only command instead.

## What was built

| File | Role |
|---|---|
| `scripts/search/search.py` | The command. Python 3 stdlib only (`urllib`, `json`, `argparse`, `re`). |
| `scripts/search/routing.json` | **The durable part**: intent → provider routing rules, credential *variable names*, endpoints, and the "why" text, all in data. |
| `scripts/search/.gitignore` | Keeps `state/` (raw responses + usage log) local to each node. |
| `docs/agent-search-20260930.md` | This document. |

**No MCP row of any kind was added.** Nothing was installed into `~/.dsh`.

## Usage

```bash
python scripts/search/search.py --provider auto  --query "How much do iPhone 14 OLED replacement panels cost at wholesale quantities of 5 or more?"
python scripts/search/search.py --provider exa   --query "Find suppliers of iPhone 14 OLED replacement panels"
python scripts/search/search.py --provider spider --url  "https://example.com"
python scripts/search/search.py --provider tavily --query "..." --env-file "C:/path/to/.env"
```

Flags: `--provider tavily|exa|spider|auto` · `--query TEXT` xor `--url URL` ·
`--env-file` · `--routing` · `--state-dir` · `--max-results` · `--max-chars`
(default 1500) · `--timeout`.

## Routing rule (in data, one place)

`routing.json` holds an **ordered** rule list; edit the file, not the code.

| Order | Rule id | Matches | Provider | Why |
|---|---|---|---|---|
| 1 | `known-url` | a caller-supplied `--url` | **spider** | a URL is a fetch, not a search; Spider renders and unblocks it |
| 2 | `discovery` | `find/search/suppliers/sources/companies/alternatives/…` | **exa** | finds pages nobody has named, with their content |
| 3 | `answer-shaped` | question word, trailing `?`, `price/cost/compare/vs/cheapest` | **tavily** | Tavily synthesises an answer with sources |
| 4 | `default-discovery` | any other bare noun phrase | **exa** | a bare phrase is a discovery query by default |

Patterns (`discovery_patterns`, `answer_patterns`) are regexes stored beside the
rules. `--provider auto` prints exactly one routing line naming the provider and
the reason, e.g.:

```
route: provider=tavily rule=answer-shaped why="query is answer-shaped (question word, trailing '?', price/compare): Tavily synthesises an answer"
route: provider=exa    rule=discovery     why="query carries discovery intent (find/search/suppliers/sources): Exa finds pages nobody has named"
route: provider=spider rule=known-url     why="a caller-supplied URL is a fetch, not a search: Spider renders and unblocks it"
```

## Credentials: by name, never by value

`search.py` reads the **application env file** (`personal-secretary-mvp/.env`;
candidates and the `SEARCH_ENV_FILE` / `--env-file` overrides live in
`routing.json`). It reads only the variable **names** from `routing.json`:
`TAVILY_API_KEY`, `EXA_API_KEY`, `SPIDER_API_KEY`. Values are used to build a
request header and are never printed, logged, or written to the raw file.

A missing required credential is a **clean, named failure** (exit 2) with no
fallback to another provider:

```
$ python scripts/search/search.py --provider tavily --query "test wrong name" --env-file <file with TAVILY_API_KEY_TYPO=...>
provider=tavily status=missing_credential missing=TAVILY_API_KEY env_file=...\_probe-wrong-name.env
fix: add TAVILY_API_KEY=... to ...\_probe-wrong-name.env — this command will not fall back to another provider.
[exit code: 2]
```

Spider's key is marked `cred_required: false` (Spider documents keyless access);
when absent the tool says so on its own line and proceeds — it does not switch
provider.

**Leak check (measured):** the command's combined stdout/stderr, every raw
response, and the usage log were grepped for the live `TAVILY_API_KEY` value:

```
MATCHES_IN_COMMAND_OUTPUT: 0
MATCHES_IN_RAW_AND_LOG: 0
```

## Results the caller sees, and where the bulk goes

The caller gets one header line plus a bounded excerpt (`--max-chars`); the full
raw JSON response is written to `scripts/search/state/raw/<stamp>-<provider>.json`
and its path is printed. This is the same "full output to a file" principle as
the schema-tax argument in `docs/tooling-audit-20260930.md` §6.

Real calls made while building this (2026-09-30):

* **Tavily, auto-routed (`answer-shaped`), HTTP 200, 2723 ms** — returned the
  price answer: "Alibaba lists prices ranging from **$7.50 to $8.90** for
  individual screens and **$41.80 to $46.20** for minimum order quantities of 5
  pieces", plus 3 supplier sources. This matches the brief's tested result.
* **Spider, auto-routed (`known-url`), HTTP 200, 2144 ms** — returned
  `https://example.com` as markdown (223 chars), keyless.
* **Exa** — see the gap below.

## The honest gap: no Exa credential on this node

`EXA_API_KEY` is **absent** from `personal-secretary-mvp/.env` and `.env.local`,
and from this shell's environment. `scripts/cap/providers.json` had already
recorded this ("NO Exa key exists in the env file"), so it is a known gap, not a
regression. **A real Exa search therefore could not be run from this node**, and
no Exa result is claimed. The routing is proved up to the credential, and the
request shape is proved reachable by a deliberate dummy-key probe:

```
$ python scripts/search/search.py --provider exa --query "OLED panel suppliers" --env-file <EXA_API_KEY=dummy-probe-value-not-a-real-secret>
provider=exa latency_ms=443 cost=not reported chars=0 status=401 raw=...-exa.json
error: HTTP 401
body: {"requestId":"...","error":"Invalid API key. Provide a valid key using 'Authorization: Bearer <key>' or 'x-api-key: <key>'. ...","tag":"INVALID_API_KEY"}
```

A 401 (not a 400/404) means the endpoint, method, header *name* and body shape
are accepted; only a valid key is missing. Put `EXA_API_KEY` in the app env file
and the same command returns Exa results with no code change.

Also not done: no Brave/SerpAPI/Perplexity adapter (the brief scoped the command
to Tavily/Exa/Spider), and no automatic fallback to another provider of any kind — by design.

## Usage log

Every call appends one JSON line to `scripts/search/state/search-log.jsonl`:
`ts, provider, rule, mode, target, env_file, cred_env, outcome, latency_ms,
http_status, cost, chars, sources, raw_path, error`. Seven calls recorded while
building this (3 Tavily ok, 1 Exa missing_credential, 1 Spider ok, 1 Exa 401
probe, 1 Tavily wrong-name failure). `cost` reads "not reported" where the
provider returned no cost/credit field — Tavily's `/search` response carried no
`usage` object today, so cost is not invented.

## Verification status

* Verified: real Tavily call with results; real Spider call; auto-routing lines
  with provider **and** reason; clean exit-2 failure on a wrong variable name;
  JSONL log with all calls; 0 occurrences of the key value in output/raw/log.
* Not verified: a real Exa call (no credential on this node — see above); no
  live-tested Brave/SerpAPI/Perplexity path; Spider's eBay-unblock claim was not
  re-run here (the tool path is wired and worked on `example.com`).
