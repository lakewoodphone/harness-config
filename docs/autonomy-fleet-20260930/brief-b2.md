# BRIEF B2 — Our own tool stack, audited for 2026

You are a mesh research subagent auditing OUR OWN TOOL STACK: what this agent deployment mounts, what it costs, what we use it for, and whether each is still the right choice in 2026. Work alone.

**REPORT FILE (the only file you may create):** `C:\Users\ezabz\Code\_autonomy-fleet-20260930\b2-tool-stack.md`

## Context
Date: 2026-09-30. You run on ZABZ-TECH (Windows). The agent engine is DSH (DeepSeek Harness); the harness configuration is the git repository `C:\Users\ezabz\Code\harness-config` (presets, profiles, packages, docs), and the live configuration is `C:\Users\ezabz\.dsh\settings.yaml` plus `C:\Users\ezabz\.dsh\.agent-presets\`. The owner pays for these tools and asked, verbatim, whether Firecrawl, Coral and JINA are still the right tools.

## The main seat tool surface (base the audit on this list — it is what a working session sees)
- Local: `pwsh` shell, `read`, `write`, `edit`, `glob`, `grep`, `present`, `ask_user_question`, `todo_write`, `skill`, `admission_governor`, `engine_health`.
- Delegation: `subagent`, `subagent_remote`, `subagent_local`, `subagent_fork`, `workflow`, `ralph`, `list_agents`, `send_message`, `interrupt_agent`, goal tools, background job tools.
- Web and HTTP: `web_search`, `web_fetch` (the harness own).
- MCP servers mounted: `mcp__firecrawl__*` (search, scrape, crawl, map, extract, agent, monitors, parse, research_search_papers, research_read_paper, research_inspect_paper, research_related_papers, interact, find_tools, credit_usage, feedback), `mcp__jina__*` (read_url, search_web, search_images, search_arxiv, search_ssrn, search_jina_blog, capture_screenshot_url, extract_pdf, guess_datetime_url, deduplicate_strings, sort_by_relevance, primer), `mcp__context7__*` (resolve-library-id, query-docs), `mcp__fetch__*` (fetch_html, fetch_json, fetch_markdown, fetch_readable, fetch_txt, fetch_youtube_transcript), `mcp__playwright__*` (full browser automation), `mcp__secretary__ps_*` (the client own company MCP: ps_db_query, ps_health, ps_company_status, ps_ceo_chat, ps_action, and more).

## RULES
- WRITE EXACTLY ONE FILE: the report path above. No other file anywhere. No temp or scratch files. No git mutations. No messages to anyone.
- READ-ONLY. Do NOT run `mcp__secretary__ps_action`, do not send anything, do not write to any store. You may read files and run read-only shell commands (`Get-ChildItem`, `Get-Content`, `Get-Process`).
- **Do NOT call the firecrawl, jina or playwright tools to test them** — that spends the owner credits. Audit them from their configuration, their tool descriptions, their own pricing pages, and any usage records already on this machine. If a usage number does not exist locally, write "no usage record found" rather than generating a new call.
- You MAY browse the web with `web_search` and `web_fetch` if you have them; otherwise shell HTTP (`Invoke-WebRequest`, `curl.exe`). Every external claim carries a URL and the date you read it.
- Aim to finish in under 45 tool calls. Report 10 to 16 KB, dense.

## What to do
1. **Inventory what is mounted where.** Read `C:\Users\ezabz\.dsh\settings.yaml`, and the presets and profiles and packages under `C:\Users\ezabz\Code\harness-config\`. List every MCP server, tool family and package each profile mounts. Note explicitly which are only mounted in some profiles, and whether a headless woken session gets the same tools as an interactive one — a shift that cannot browse is a shift that cannot do half the work.
2. **Usage evidence.** Find recorded usage for each external provider: firecrawl credit or usage records if a log exists locally, jina calls in session logs, context7 calls, playwright usage. Report measured or recorded numbers where they exist, and "no usage record found" where they do not. If there is a cheap way to count total tool calls per tool name in the session store under `C:\Users\ezabz\.dsh\`, do it; if it is expensive, skip it and say so.
3. **Fitness audit, one row per provider**: what we use it for, what it is best at, its known failure modes (rate limits, JavaScript rendering, paywalls, the token cost of returned content, licence), its price per 1k calls or per credit, whether it duplicates another tool we already have, and the verdict KEEP or KEEP-BUT-NARROW or REPLACE or ADD.
4. **Search, fetch and scrape comparison for 2026**: Firecrawl, Jina Reader, Exa, Tavily, Brave Search API, Serper, SerpAPI, Bright Data, Apify, ScrapingBee, Olostep, ScrapeGraphAI, Spider, plus self-hosted options (Crawl4AI, Playwright with trafilatura, Docling, SearXNG, and Firecrawl self-hosted if the open-source version exists). Table: provider | what it does | price | best-for | weaknesses | source+date. Then, for our two dominant needs — (a) search the web and read 5 to 20 pages a day, (b) drive a real browser to log into a portal and click things — name the single best option and the cheapest adequate option.
5. **The gaps**: tools we do NOT have that a 24/7 autonomous agent obviously needs (persistent browser sessions with logged-in profiles, screenshot or vision on arbitrary pages, structured extraction at scale, a schema-validated extraction path, email and GitHub APIs, a code sandbox, a real browser running on the server, vector search over our own corpus). For each gap name the best 2026 tool with a source and say what it would unlock.
6. **Cost sanity**: if usage is roughly 10 to 50 agent sessions a day, each doing a handful of web reads, compute the monthly cost of each candidate stack and rank them. Show the arithmetic.
7. **Consolidation**: which mounted tools are redundant with each other, and which single change would cut the most surface area with no capability loss?

## Output format
```
# B2 — Our tool stack, audited (2026-09-30)
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30
## 1. Verdict (max 4 sentences)
## 2. What is actually mounted, by profile (table)
## 3. Usage evidence found (table: provider | metric | value | source | as-of)
## 4. Fitness audit, one row per provider (KEEP / KEEP-BUT-NARROW / REPLACE / ADD)
## 5. Search, fetch and scrape comparison (table) plus our best and cheapest-adequate picks
## 6. Gaps that stop a 24/7 agent, with the best 2026 tool for each
## 7. Monthly cost arithmetic per candidate stack
## 8. Redundancy and consolidation
## 9. Candidate improvements (numbered TS-1..TS-N; TOPIC / WHAT / WHY / EFFORT S|M|L / EXPECTED GAIN / RISK / SOURCE URL+date / FIRST CONCRETE STEP) — 8 to 12 items
## 10. Not verified, and why
## 11. Sources (URL + date + what it established)
```

## Honesty clause
A confident claim you did not earn is worse than an honest gap. Never invent a price or a capability. Where a tool config is unreadable or a usage record is missing, write "no record found" and say what you looked at. Prices must come from the vendor own page, with the date you read it.
