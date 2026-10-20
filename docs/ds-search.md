# DeepSeek Search & Fetch — what it is, what it costs, and how to use it here

Measured 2026-10-19 on the authority and on ZABZ-YOGA, with the estate's existing `DEEPSEEK_API_KEY`.
Everything below is a command that was run, not a claim from a blog post.

## The two endpoints

```bash
# search — 0.63 s measured
curl -s -X POST https://api.deepseek.com/v1/tools/search \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" -H 'Content-Type: application/json' \
  -d '{"query":"lakewood new jersey phone repair","count":5}'
# -> {"results":[{title, site_name, site_icon, authority, rerank_score, date, url, summary, snippet, content}]}

# fetch one page as markdown — 0.34 s measured
curl -s -X POST https://api.deepseek.com/v1/tools/fetch \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" -H 'Content-Type: application/json' \
  -d '{"url":"https://api-docs.deepseek.com/updates"}'
# -> {"content":"…markdown…"}
```

`count` is the result-count control (`count:2` returned 2, `count:5` returned 5 — measured). `summary` and
`snippet` carry the excerpt; `content` was empty on search results in every call made.

## Money, from the vendor's own guide

- A request is **billable only when it returns HTTP 200 and produces a result** — a failed request, an
  empty result set or a timeout is not billed.
- Through DeepSeek Harness the server-side tool calls are **free until 00:00 Beijing on 2026-11-01**;
  per-request billing starts then at **$0.75 per 1,000 requests** (0.075 cents each).
- Search and Fetch have independent rate limits; one does not consume the other's quota.

That price is not the reason to care. The reason is that `dsh-base` mounts `web-search-deepseek`, whose
own README says *"one search costs a full model turn … because DeepSeek exposes no dedicated search
endpoint"* — and the vendor's changelog for **2026-10-17** opens the in-house search API. So the estate
was paying a model turn per search to reach an endpoint that is now free and answers in 0.6 s.

## The command that uses it

`scripts/ds-search.mjs` — one file, no dependencies, exit codes a guard can read.

```bash
node scripts/ds-search.mjs search "who sells iPhone 15 screens wholesale" --count 5
node scripts/ds-search.mjs search "…" --json
node scripts/ds-search.mjs fetch https://example.com/page --max-chars 4000
```

| exit | meaning |
|---|---|
| 0 | ok |
| 2 | bad usage |
| 3 | no key (checked: `$DEEPSEEK_API_KEY`, else the **exact** key `DEEPSEEK_API_KEY` in `<home>/.dsh/.credentials.yaml`) |
| 4 | the API refused or failed — the HTTP status and body head are printed |
| 5 | a real negative: HTTP 200 with zero results, or a fetch with no content |

Exit 5 exists because "no results" and "the request failed" must never be the same answer.

**Why it is `node:https` and not `fetch`:** measured on Windows/node 24, a `fetch()` followed by
`process.exit()` crashed the runtime on exit (`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING),
src\win\async.c:76`, exit `0xC0000409`) because the keep-alive socket was still closing. A CLI whose exit
code is garbage cannot be used in a guard.

## Where it should and should not be used

- **Live web search** — yes, first choice: cheap, fast, and returns a dated, attributed result set.
- **Reading one page** — yes as a fallback tier; `web_fetch`/jina `read_url` remain the default because
  they are already mounted and free of quota.
- **Our own corpora** (sessions, customer comms, journal, docs) — **never**; that is `esearch`/`ps_search`,
  and no external engine can see those bytes.
- **Replacing jina/firecrawl** — not on this evidence. Their coverage is measured here; DeepSeek's index
  is not characterised beyond its own claim of hundreds of billions of pages.

## What was NOT verified

- Result quality and latency at rate-limit pressure (one call per query shape was made).
- Whether the native `web_search` server tool and this endpoint will be billed identically after
  2026-11-01.
- Jurisdiction / data-retention terms specific to the search endpoint (the general API terms apply).
- Search counts and spend per day for the estate — the session logs that would answer it are compressed.
