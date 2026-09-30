# Tooling and landscape audit — 2026-09-30

**Author:** Zabz seat (DSH) on ZABZ-TECH. **Sources:** four completed mesh research passes (B1 landscape,
B2 our tool stack, B3 always-on infrastructure, B4 memory and context economics), each citing primary
sources with dates, read 2026-09-30. Full reports, including every "not verified" list, are in
`C:\Users\ezabz\Code\_autonomy-fleet-20260930\`. Nothing here is from a listicle where a primary source
was reachable, and vendor benchmarks are labelled as such.

## 1. Are we behind?

**Current on the harness and the sandbox model; behind on durability semantics and on cost accounting.**
DSH's shape — a scheduler that starts headless sessions with nobody at a keyboard — is the shape the field
converged on in 2026; Claude Code, Codex CLI and Gemini CLI all ship the same headless, background and
scheduled primitives we rely on. What the field built underneath that shape during 2026 we do not have:
checkpoint-based durable execution with resumption, hibernation while waiting on a model call, and
exactly-once side effects. And our cost exposure is real: every serious sandbox and durable runtime now
bills idle time differently, while an always-on owned desktop is the worst possible shape under
wall-clock billing.

## 2. The two products you named

**Dots is OpenAI Dots — an always-on personal and business agent, launched at Dev Day on 2026-09-29.**
Each Dot runs on its own private cloud computer with its own browser, powered by GPT-6 Astra, connected to
4,000+ apps through plugins, learning from feedback, able to be granted access to your own laptop, with an
auto-review step before sensitive actions. Bundled with ChatGPT Pro at 100 USD/month; the first Dot is
included and Dot conversations do not count against usage limits ("for the next month", per the FAQ).
Rolling out now, excluded from the EEA, Switzerland and the UK.

*Verdict: not a tool for us — a substitute for the product.* It competes with the outcome you already own
(an always-on agent working on your behalf), and nothing verifiable shows a scheduler, headless API or
durable event log we could drive from the authority. **Caveat, and it is a real one:** the primary
announcement page returned HTTP 403 to our fetch, so those details rest on secondary reporting that quotes
it, and the day after launch OpenAI's own CFO called the product "Muse" on live television. Treat
brand-name reasoning about it with care.

**Coral is withcoral.com — an open-source data-retrieval layer giving agents one SQL interface across
APIs, databases and file systems.** Public since 2026-04-27, Apache-2.0 and free to self-host, with a team
tier at 249 USD/month for 50,000 queries. It is unambiguously in the same family as Firecrawl and Jina —
the "get external data into an agent" family — except that it targets *internal* systems you already hold
credentials for, rather than the open web. The vendor benchmark claims +31% accuracy and −70% cost on
complex multi-hop tasks versus direct provider MCPs; it is vendor-run, single-model and
sandbox-specific, so the direction is credible and the magnitude is not established.

*Verdict: worth a bounded pilot, not a migration.* The analogous win for this business is one queryable
surface over the repair/ticket system, inventory, supplier pricing and messaging, so an agent answers
"which SKU is under-priced and which supplier is late" in a joined query instead of a dozen MCP
paginations. Note there is also a Coral Protocol / CoralOS (unrelated, a multi-agent orchestration
platform) — your grouping with Firecrawl and Jina makes withcoral.com the far likelier referent.

## 3. What we actually mount, and what it costs us

Six MCP servers are mounted, all in the `zabz` preset, and none anywhere else:

| family | tools | schema chars | session mentions (of 1,611) | price | verdict |
|---|---|---|---|---|---|
| firecrawl | 27 | 39,770 | 32 | free; 16 USD/mo; 83 USD/mo standard | KEEP, narrowed |
| playwright | 24 | 17,006 | 4 | free, installed | KEEP + persistent profile |
| jina | 22 | 14,265 | 22 | price not published (page 404) | KEEP |
| secretary (`ps_*`) | 14 | 7,950 | 1 | internal | KEEP |
| context7 | 2 | 4,665 | 1 | not read | DROP |
| fetch | 6 | 4,121 | 5 | free | DROP |
| harness web_search / web_fetch | — | — | **193 / 186** | included | default path |

**The fixed tax: 95 tools and 87,777 characters of schema, about 21,944 tokens, re-sent on every request
that sees the preset.** Firecrawl alone is 34% of it and is the second-least-used large family. Dropping
`fetch` and `context7` removes 10.0% of the schema for about 2,196 tokens per request against 5 and 1
uses in 1,611 sessions.

**The gap that matters most: a headless worker — every mesh child, every woken shift — gets none of this.**
It has the base tool plane (shell, files, jobs, goals, subagent, workflow, todo, skill, web_search,
web_fetch) and no MCP bridge at all: no firecrawl, no jina, no playwright, **no `ps_*`**. So the fleet
cannot scrape a bot-walled page, cannot drive a logged-in browser, and cannot query the company database.
That single fact explains more of the fleet's limits than any model choice.

**Cost, at our plausible volume** (10-50 sessions/day, 5-20 reads each, so 1,500-30,000 reads/month):
status quo 83 USD/month on Firecrawl Standard plus an unknown Jina bill; harness-only zero vendor cost
with the page text landing on the token bill instead; Spider pay-as-you-go 0.23 to 4.50 USD/month; Exa
7.50 to 150; Brave 2.50 to 150. **The spread is under 20 USD/month; the real cost is the 22k-token catalog
and an 83-dollar floor on a plan we may not be using.** For driving a real browser into a portal, the best
option is the Playwright we already mount, given a persistent profile directory — one process, no
subscription.

## 4. What changed in 2026, and what is now table stakes

Three things changed materially, and all three are about the runtime, not the model.

1. **Durability became a named category.** After OpenClaw's rise, 2026 produced a wave of entrants around
   Temporal as the incumbent, and replay semantics became a design *choice*: checkpoint replay restores
   completed step results and lets ordinary code re-run, where Temporal demands deterministic replay. That
   is why multi-hour runs stopped being a bet on one heavyweight system.
2. **Waiting became free.** Cloudflare persists execution history and pending approvals across Durable
   Object hibernation; Absurd and Kitaru suspend by releasing compute; sandbox vendors moved to
   active-CPU billing with auto-pause around thirty seconds after activity stops. An agent that idles 70%
   of the time went from paying full wall-clock to paying roughly storage.
3. **Headless multi-hour orchestration shipped in the mainstream CLIs** — Claude Code orchestrates tens to
   hundreds of background agents with a pinned-session monitor and `--resume`, which is our shape, shipped.

**Table stakes we are missing**, in the order they cost us: checkpointed resumption of a killed session
including mid-tool-call; human-in-the-loop as *durable state* that survives process death and costs
nothing while pending (you are asleep — a blocking prompt is a lost night); exactly-once side effects for
anything that spends money, sends a message or writes a record; an agent-legible control plane so an agent
can list, inspect, replay, resume and unblock runs; per-run cost and duty-cycle accounting; and
capability-scoped credentials so broad keys never enter a model context.

## 5. The smallest set of infrastructure changes, ranked

From the infrastructure pass, each with effort and adoption risk. The first three are the ones I would do
before anything else in this document:

1. **Pull instead of push** — the worker claims from a `runs` table instead of being invoked over ssh. A
   dead tunnel can no longer lose an answer. Medium effort, medium risk (the endpoint needs auth).
2. **Result before acknowledgement** — commit the result and the terminal event, *then* release the lease.
   Small effort, low risk. This is the same fix as the local runner, expressed as a property.
3. **Lease, heartbeat and reaper on every queue** — requeue expired leases up to the attempt cap. Small
   effort, low risk.
4. Idempotency keys on side effects, keyed `run_id:step_index` — medium.
5. Per-turn checkpointing of conversation and tool state, so a restart resumes instead of re-paying —
   medium.
6. **An external dead-man switch** — two checks, a phone alert, 0 USD on the free tier and about 20
   USD/month at business tier. Small effort, very low risk. This is the only mechanism that catches the
   authority itself dying.
7. A cost ceiling that fails *closed*, in the gateway that holds the key — small to medium.
8. One outcome read: queued age, success rate, cost per run, dead-letter count on one screen — small.
9. A node capability and health table, with a drain flag for the desktop — medium.
10. SQLite to Postgres on the authority, for concurrent writers, `SKIP LOCKED` and point-in-time backups —
    medium, and it unlocks every queue option without changing callers.

**Do not adopt a durable-execution platform yet.** Every serious option either adds a service you must
operate (Temporal's own default stack is Postgres plus Elasticsearch) or is cloud-only. Restate is the
most proportionate of the real engines — one binary, single-node is an explicitly supported tier — and it
is still the wrong first move for tens of runs a day. Put the queue in SQL, add the dead-man switch, and
revisit when a single workflow must outlive a laptop sleep.

## 6. Memory and context: where the money and the intelligence are

Measured price behaviour today: prompt-cache reads are an order of magnitude cheaper than writes (Anthropic
documents writes at 1.25 to 2x and reads at 0.1x of the base rate; DeepSeek's Flash tier is documented at
0.003 versus 0.15 per million input tokens, hit versus miss). That makes the *arrangement* of the prompt
worth more than the choice of model.

Ranked by expected saving for this workload, with the evidence strength stated:

| # | Change | Expected | Evidence |
|---|---|---|---|
| 1 | Freeze a byte-stable cached prefix: constitution and tool list first, in fixed order, nothing dynamic before the breakpoint | 30-60% of input cost | strong, first-party |
| 2 | Cut re-sent context about tenfold with a generated 2k-token packet per shift | about 90% of the prefix-cost line | strong arithmetic |
| 3 | Defer tool and skill definitions, loading 3-5 at a time | 10-25% of the prefix | strong, first-party |
| 4 | Structured tool returns (status, ids, paths, counts, digest; full output to a file) | 30-60% of context growth | strong |
| 5 | Stop conditions, budgets and an elapsed-time clock | 20-40% of cost and 33-69% of wall time | strong |
| 6 | Effort routing: cheap by default, re-run only failures at high effort | about 50% of mechanical steps | strong |
| 7 | Subagent offload with structured returns | 30-50% on independently partitioned work | strong, with a quality cost |
| 8 | Compaction as a fallback | high, quality unpublished | documented |
| — | *Clearing old tool results, to invalidate the cache* | **negative — measured to cost more than it saved** | strong, against |

**The single highest-value structural idea in this section** is the 2k-token packet: a script renders it
from the ledger, the project state file and the journal index, in a fixed order, so the first several
hundred bytes are byte-identical between shifts and cache. Its content: about 300 tokens of constitution
(role, hard rules, tools in fixed order, output contract, stop conditions — never varies), 150 of the work
item with its verbatim proving command, 250 of interface contract, 250 of state snapshot, 400 of decisions
plus an explicit do-not-retry list, 100 of next action, 150 of a recall index, 200 of output contract.
Nothing dynamic, nothing queryable, no transcripts, no dumps.

**On self-improvement, the honest position.** The only surveyed method with a peer-reviewed reproducible
result is GEPA (reflective prompt evolution, ICLR 2026, code released): it reverses the usual order by
reflecting on trajectories before proposing changes, and reports +6 points average over GRPO with up to
35x fewer rollouts. Voyager-style skill libraries compound but rot: one study measures LLM-authored skills
at +0.0 points against curated at +16.2, and outcome-driven retirement plus a bounded active set lifted
pass@1 from 0.258 to 0.584 over a hundred rounds. Everything else in the category — Darwin-Gödel Machine,
SEAL, experience replay — was reachable only through secondary or promotional sources. **Do not spend
money on them yet.**

## 7. Verdict on our tool choices

- **Firecrawl: keep, narrowed.** Real value on bot-walled and JavaScript pages, 15 requests/minute, 34% of
  the MCP schema, and no per-tool allowlist. Narrow it to scrape and search; unload crawl, map, agent,
  monitors and research.
- **Jina: keep.** Cheapest everyday reader and the only one that returns passages; its price is currently
  unpublished (page returns 404), which is itself a reason not to depend on it alone.
- **Playwright: keep, then upgrade.** It is our only real browser and it has no persistent logged-in
  profile, so every login dies with the browser. Add `--user-data-dir` and a screenshot-to-vision path.
- **context7 and fetch: drop.** One and five uses in 1,611 sessions, both duplicated by tools we already
  have, together about 2,196 tokens off every request.
- **`ps_*` (secretary): keep, and give it to headless workers.** The fleet currently cannot reach the
  company database at all.
- **The harness's own web_search and web_fetch: keep as the default and escalate from it** — 379 combined
  uses against 54 for every MCP family together.

## 8. Not verified, and why

Jina's price (unpublished page), Serper and Apify and ScrapingBee's prices (client-rendered or absent),
Firecrawl's growth tiers (page truncated), Context7's price (no page read), the self-hosted licences (no
licence text read). **There is no per-tool call census** — the numbers above are server starts and session
mentions, not invocations; a real census would mean decompressing 487 MB of session archives and was
skipped as too expensive. All memory benchmark numbers in circulation are vendor-self-reported and none
was cleanly reproduced, including Mem0's and Zep's. Coral's benchmark is its own, single-model and
unreplicated. Dots' product page returned 403, so its details rest on secondary reporting. Nothing in the
memory or cost sections was tested on our own journal and ledger; the gains are cited measurements from
other workloads or arithmetic.
