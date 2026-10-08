# B4 — Agent memory and context economics: what is real, and what we should change
**Researcher:** mesh subagent, ZABZ-TECH, 2026-09-30

## 1. Verdict
No memory product fixes the complaint: at a tight budget, raw turns chosen by a typed model are non-inferior to LLM fact-extraction (−3.0 pts vs a −5 margin) at 3,061× lower write cost [S13]; long context beats fact-memory on recall and memory wins on cost only after ~10 turns [S12]; vendor benchmarks are self-reported and contested [S11]. Our $0.036–0.068/shift for 3–5M tokens is already cache-dominated (DeepSeek Flash hit $0.003–0.006/M = 2% of miss), so the levers are a smaller, byte-stable re-sent prefix, not a vendor or a database. Compounding is curation: LLM-authored skills gave +0.0pp vs +16.2pp human-curated, and only outcome-driven retirement plus a bounded active cap improved a library (0.258→0.584 pass@1) [S16]. Do: freeze and shrink the prefix, make the ledger + a 2k-token packet the only cross-shift channel, govern procedures by measured outcome.

## 2. Memory systems (what it stores | retrieval cost | licence/price | independent evidence | verdict)

| System | Stores | Retrieval cost | Licence/price | Independent evidence | Verdict |
|---|---|---|---|---|---|
| Letta | OS tiers; agent self-edits blocks | tool calls, token-priced | Apache 2.0; Pro $20/mo; API $20 + $0.10/agent/mo [S10] | DMR is its own metric; no repro | Runtime, not a library |
| Zep/Graphiti | bitemporal KG, validity intervals | vendor ~90% latency cut | Graphiti OSS; Zep CE deprecated; ~$25/mo credits (secondary) [S19] | own paper asks for repro; Zep-vs-Mem0 dispute [S11] | Keep intervals in SQLite |
| Mem0 | extracted facts; optional graph | vendor 91% lower p95 | Apache 2.0; $19/mo → $249/mo graph (secondary) | 26% disputed; independent 49.0% LongMemEval, below long context [S12] | Destroys evidence; skip |
| cognee | KG triplets + vectors over docs | vector+graph; no price | open core; €8.50/1M, €1,970/mo on-prem (secondary) [S19] | none found; a coverage gap [S11] | Wrong shape for a ledger |
| MemOS | not verified | — | — | no source, price or benchmark found | Unknown; do not buy blind |
| Supermemory | managed profiles; contradiction resolution | managed API, unpublished | closed; enterprise self-host only | vendor 81.6% LongMemEval; no repro | Hosted memory = wrong risk |
| LangMem | key-value + vectors in LangGraph | single-strategy search | MIT; LangGraph-coupled | leaderboard numbers only [S11] | Copyable, unneeded dep |
| Hindsight (2026) | semantic+BM25+graph+temporal, rerank, reflect | vendor 100–600ms; reflect 800–3000ms | MIT self-host; usage-based cloud | 94.6% LongMemEval on its own leaderboard [S19] | Idea real; product unvalidated |
| **Our file+SQLite** | journal (~2,800 md) + ledger + JSON | local grep ms; zero LLM read cost | owned; no licence | no head-to-head test, but none beats a well-indexed local store on exact ids/tests | Correct substrate; defect is re-derivation |

## 3. Structured state versus vector memory: the evidence
- Structure wins on temporal/exact queries: a "database of assertions" lifted LoCoMo temporal F1 21.3→41.9 at top-5; Mem0's graph leads temporal at 58.13 [S11]. But pure SQL cannot replace embeddings for fuzzy recall — even MemoriesDB (arXiv 2511.06179) falls back to pgvector.
- Retrieval rots with scale: evidence fixed and irrelevant sessions added, HippoRAG loses **16–20 pp** budget-compliant reliability inside a 2-call budget; LiCoMemory's failures depend on the agent (Qwen3-8B busts budget, 32B/235B stay reliable) [S14]. Condition reliability on agent, scale and call budget.
- The optimum is a composition: MESA beats the strongest baseline by **8.5% using 41% fewer evidence tokens** than all-structure [S15]; code not mentioned.
- Selection can replace extraction at tight budgets: pre-registered held-out LoCoMo+LongMemEval — typed-model raw-turn selection non-inferior to extraction (−3.0 pts vs −5 margin), raw turns **3,061× cheaper to write**; reranking adds +**17.4** LoCoMo/+**9.1** LongMemEval at 3-of-30 candidates, only +1.5/+1.1 at generous budgets where extraction wins; at matched context it equals an LLM reranker (bound −2.0) at **1/3 latency**; reranking lowers correct abstention. Plan, code (MIT), data released [S13].
- Cost crossover is real, accuracy is not: at 100k context fact-memory is cheaper after ~10 turns, but long-context GPT-5-mini has higher recall on LongMemEval/LoCoMo [S12].
- Hybrid for us: ledger as typed truth (id, status, owner, acceptance test, valid_from/valid_to) + FTS5/BM25 entry points + embeddings only after a real fuzzy-recall failure + a hand-written packet as the read path.

## 4. Context economics with real 2026 prices (arithmetic shown)
Prices fetched 2026-09-30. DeepSeek [S1]: Flash hit $0.003 off-peak/$0.006 peak, miss $0.15/$0.30; V4-Pro hit $0.022/$0.044, miss $0.66/$1.32. Anthropic [S3]: 5m write 1.25×, 1h write 2×, read 0.1× (0.05× Opus 5.5, 0.025× Fable/Mythos 5.1); Sonnet 5.5 $2.00/$2.50/$4.00/$0.20; Opus 5.5 $4.00/$5.00/$8.00/$0.20. OpenAI [S8]: GPT-5.6+ write 1.25×, read 0.1× (0.05× GPT-6.1 Sol), min cacheable prefix **1,024**, TTL **30m**, ≤4 writes/request, prefix-hash routing. Google [S9]: Gemini 3.8 Flash $0.75 in/$3.75 out, **cached $0.075**; implicit min 4,096 (3.x)/2,048 (2.5); explicit TTL 1h, storage billed separately. Scenario: a 120k-token stable prefix re-sent every step for 200 steps = **24.00M** tokens; 1 write + 199 reads.

| Provider/model | Uncached $/M | Write | Read | Uncached | Cached | Saving |
|---|---|---|---|---|---|---|
| DeepSeek Flash off-peak | 0.15 | 0.15 | 0.003 | $3.60 | 0.12×0.15+23.88×0.003 = **$0.0896** | 97.5% |
| DeepSeek Flash peak | 0.30 | 0.30 | 0.006 | $7.20 | 0.036+0.1433 = $0.179 | 97.5% |
| DeepSeek V4-Pro off-peak | 0.66 | 0.66 | 0.022 | $15.84 | 0.0792+0.5254 = $0.605 | 96.2% |
| Sonnet 5.5 (5m) | 2.00 | 2.50 | 0.20 | $48.00 | 0.30+4.776 = $5.076 | 89.4% |
| Opus 5.5 (5m) | 4.00 | 5.00 | 0.20 | $96.00 | 0.60+4.776 = $5.376 | 94.4% |
| Gemini 3.8 Flash (excl. storage) | 0.75 | 0.75 | 0.075 | $18.00 | 0.09+1.791 = $1.881 | 89.6% |
| OpenAI GPT-5.6+ (X = uncached) | X | 1.25X | 0.10X | 24X | 0.15X+2.388X = 2.538X | 89.4% |

**10× smaller prefix** (120k→12k, 2.40M tokens): reads and the one-off write both fall 10×, so the cached total falls ≈9× — Sonnet $5.076→**$0.508**; Opus $5.376→$0.538; DeepSeek Flash off-peak $0.0896→**$0.00896**; Gemini $1.881→$0.188. Prefill dominates time, so the same dollars buy ~10× more steps.

**Worst pathology: a moving prefix.** Change one byte in the cached block (timestamp in the system prompt, edited tool description, reordered tools) and every step pays a write: Sonnet 24M×1.25×$2.00 = **$60.00, 25% more than not caching at all ($48)**. Vendor guidance: stable instructions first; keep tool names/descriptions/schemas/order stable; disable a tool with `tool_choice:"none"`; append after the breakpoint; prewarm after gaps; compaction resets reuse [S3][S8]. DeepSeek has no write premium but a best-effort cache cleared in hours–days [S2], so cross-shift reuse needs a byte-identical prefix within TTL. Mapped to us: 3–5M tokens at $0.036–0.068 implies ≈$0.012–0.014/M blended, i.e. already ~90%+ hits at Flash pricing; a 10× prefix cut removes ≈90% of the cache-read line (≈$0.02–0.06/shift; $1.3–3.9/day at 65 shifts) — small in dollars, but ~10× throughput and fewer wasted shifts, which is where the complaint lives.

## 5. Techniques ranked by expected saving for our workload

| # | Technique | Measured effect | Evidence | Saving |
|---|---|---|---|---|
| 1 | Byte-stable cached prefix | 84% median cache-read (top decile ≥94%); loop cost −2.7–5.3×; triage −83%/−88%; DeepResearch $37.94→$7.12 [S4] | Strong | 30–60% input cost |
| 2 | Shrink re-sent context ~10× | §4 arithmetic; ≥10-turn crossover vs long context [S12] | Strong math, moderate empirical | ~90% of prefix cost |
| 3 | Defer tool/skill definitions | ~55k-token catalog cut >85%; 3–5 tools loaded; degrades past 30–50 tools [S5] | Strong, first-party | 10–25% of prefix |
| 4 | Subagent offload, structured returns | corpus 47–55% cheaper, 10–12 pts lower, 2.3h vs 15–20h; p90 $33→$12 [S4] | Strong; quality costs | 30–50% on parallel work |
| 5 | Effort routing + re-run failures | equal pass rate at ~half cost; 64k max_tokens sufficed in 13,998/14,000 turns [S4] | Strong | 30–50% mechanical steps |
| 6 | Cheap model for mechanical steps | advisor paid off only sometimes: +1.7 pts for ~2.1× cost [S4] | Mixed | 10–30%, measure |
| 7 | Stop criteria + elapsed-time clock | 33–69% less wall time, 28–54% lower cost/task, ≤1.9 pts lower [S4] | Strong | 20–40% |
| 8 | Compaction / summarisation | structured summary replaces old turns; doc example 100k→~2–3k [S6] | documented, quality unpublished | High as fallback |
| 9 | Clearing old tool results | invalidates cache; measured **costing more than it saved** [S6][S4] | Strong against | Negative |
| 10 | Filesystem memory + progress log | `/memories`, "view memory first", checklist, verify before complete [S7] | practice, no benchmark | Structural (§6) |
| 11 | Batch API | 50% cost reduction [S9] | Strong, published | 50% of batchable set |
| 12 | Retrieval, not dumping | memory cheaper after ~10 turns at 100k; long context wins accuracy [S12] | Mixed | 50–90% context, accuracy risk |

## 6. State across amnesiac runs: minimum viable handoff (first-2000-token template)
Checkpoint context **and** environment to resume rather than restart [S18]; append, never rewrite history — rewriting resets cache and destroys evidence [S8]; give each session a progress log + checklist [S7]. Minimum: **ledger owns truth, packet owns position, journal owns evidence, nothing else loads.** Template (~1,800–2,000 tokens, fixed order, first ~700 bytes byte-identical so it caches): `[~300] CONSTITUTION` (role, hard rules, tools in fixed order, output contract, stop conditions; never varies) · `[~150] WORK ITEM` (id/title/owner/acceptance test + exact proving command, verbatim from the ledger) · `[~250] INTERFACE CONTRACT` (paths, schemas, env vars, URLs, versions, pre/post commands) · `[~250] STATE SNAPSHOT` (last known-good commit, artifacts, cursor, branch, last verified test digest) · `[~400] DECISIONS + DEAD ENDS` (one line per decision with journal pointer + explicit **do-not-retry** list with reason and evidence pointer) · `[~100] NEXT ACTION` (one unambiguous step) · `[~150] RECALL INDEX` (`path → holds → open when`; no listings) · `[~200] OUTPUT CONTRACT` (where to append, schema, "unrecorded progress is lost"). Excluded: raw dumps, full journal, prior transcripts, tool outputs, anything queryable from the ledger.

Shift output (append-only): `item_id, outcome(verified|partial|blocked), files_touched(path:lines), commands(exit codes), evidence(digest), decisions[], dead_ends[{what,why,pointer}], next_action, blockers, tokens_in/out, cache_read_pct, cost, confidence` → SQLite (truth) + one ≤400-word journal entry (evidence) + project JSON (position). The next packet is generated by a script from those stores, never by an LLM summarising a transcript; Anthropic's compaction summary structure is the fallback for in-context continuation.

## 7. Compounding improvement without gradient updates
- Prompt evolution works and code is released: GEPA (ICLR 2026) beats GRPO by **+6 pp average, up to +19 pp, with up to 35× fewer rollouts**, and MIPROv2 by >10 pp (+12 pp AIME-2025); code github.com/gepa-ai/gepa [S17]. Reproduction-fidelity paper (arXiv 2606.19605) not read; transfer untested.
- Skill libraries compound and rot: Voyager's executable-skill library needed no fine-tuning and gave **3.3× more unique items, 2.3× longer travel, milestones up to 15.3× faster**, reusable in a new world; code released [S19b]. Single domain, 2023; no independent reproduction found.
- Drift is the failure mode and governance fixes it: LLM-authored skills **+0.0 pp** vs curated **+16.2 pp**; disabling injection = flat +0.002, premature retirement = −0.019; outcome-driven retirement + bounded active cap + meta-skill authoring prior lifted pass@1 **0.258→0.584** over 100 rounds; code amazon-science/Self-Evolving-Agents-Ratchet [S16].
- No-gradient playbook: promote a procedure only after an outcome check passes on a held-out item; cap the active set and retire on measured contribution; put preconditions/failure signatures in each procedure; run GEPA-style evolution on a pre-registered eval with the real harness; journal = evidence with pointers, not a corpus to re-read.

## 8. Top 5 changes for us, with expected measurable effect
1. **Freeze a byte-stable cached prefix** (constitution+tools first, fixed order, nothing dynamic above the breakpoint, defer the tail, prewarm after gaps). Effort **M**. Removes the +25% pathology; cache-read share toward the measured 84–94% band → **30–60% lower input cost/shift**.
2. **Generate the 2k-token packet (§6) and cut re-sent context 10×.** Effort **M**. **~90% of the prefix-cost line**, ~**10× more steps per dollar**, fewer duplicate shifts.
3. **Offload the mechanical middle to cheap/low-effort workers returning structured summaries**, plan+verification on the frontier model. Effort **M–L**. **47–55% lower cost** on bulk/parallel work (10–12 pts if misapplied); tail capped (p90 $33→$12).
4. **Stop conditions + budgets + elapsed-time clock; sweep effort down, re-run only failures at high.** Effort **S–M**. **~50% cost at equal pass rate**; **28–54% lower cost/task**, 33–69% less wall time, ≤1.9 pts.
5. **Outcome-scored procedure library with retirement and a cap, plus periodic prompt evolution.** Effort **M**. **+0.0 vs +16.2 pp** and **0.258→0.584 pass@1** — the only mechanism that makes shift N+1 better than N.

## 9. Candidate improvements
**MC-1 PREFIX-FREEZE** / WHAT: freeze constitution+tools byte-identically; dynamic values after the breakpoint / WHY: one changed byte makes every step a write ($60 vs $48) / EFFORT S / GAIN 30–60% input cost / RISK stale block (version it) / SRC [S3][S8] 2026-09-30 / STEP: hash first 4KB, log write-vs-read tokens for 20 shifts.
**MC-2 PACKET** / WHAT: script renders the §6 packet from ledger+JSON+journal index / WHY: selection non-inferior to extraction at tight budget, 3,061× cheaper writes / EFFORT M / GAIN ~90% of prefix cost / RISK bad packet misdirects a shift / SRC [S13] 2026-09-27, [S12] 2026-03-05 / STEP: render for one project, 10 shifts, diff vs what shifts read.
**MC-3 DEFER-TOOLS** / WHAT: 3–5 hot tools loaded; rest `defer_loading` + tool search / WHY: ~55k-token catalog cut >85%, cached prefix preserved / EFFORT S–M / GAIN 10–25% of prefix / RISK extra search round trip / SRC [S5] 2026-09-30 / STEP: measure tool-definition tokens/shift.
**MC-4 STRUCTURED-RETURNS** / WHAT: tools return a schema (status, ids, paths, counts, digest) + ≤N lines; full output to a file / WHY: tool results dominate re-sent context / EFFORT M / GAIN 30–60% of context growth / RISK lost detail / SRC [S7] 2026-09-30 / STEP: rank tools by returned bytes over 100 shifts.
**MC-5 PROCEDURE-GOVERNANCE** / WHAT: promote only on an outcome check; cap active; retire on measured contribution / WHY: +0.0 vs +16.2 pp; governance 0.258→0.584 / EFFORT M / GAIN compounding / RISK over-retirement (−0.019) / SRC [S16] 2026-07-29 / STEP: add `outcome`,`last_verified`, backfill 20 procedures.
**MC-6 EFFORT-ROUTING** / WHAT: low effort default; failures re-run at high; per-shift budget / WHY: equal pass rate at ~half cost / EFFORT S / GAIN 30–50% mechanical steps / RISK quality on hard steps / SRC [S4] 2026-09-30 / STEP: 20 items at low vs default, compare verified pass and cost.
**MC-7 CLOCK-STOP** / WHAT: inject elapsed time + "time matters"; kill past budget with a partial record / WHY: −33–69% wall time, −28–54% cost/task / EFFORT S / GAIN 20–40% / RISK ≤1.9 pts lower / SRC [S4] 2026-09-30 / STEP: log duration distribution, cap at p90.
**MC-8 SUBAGENT-OFFLOAD** / WHAT: coordinator plans; workers read partitions and return structured summaries / WHY: 47–55% cheaper on a 21.6M-token corpus; 2.3h vs 15–20h / EFFORT M–L / GAIN 30–50% on the qualifying subset / RISK 10–12 pts on dependent chains / SRC [S4] 2026-09-30 / STEP: pick one project with independent files, measure both ways.
**MC-9 CACHE-TELEMETRY** / WHAT: log cache-read %, write tokens, cost, prefix hash; alert below 80% / WHY: "below about 80%, look for what breaks the cache" [S4] / EFFORT S / GAIN protects MC-1/2 / RISK negligible / SRC [S4] 2026-09-30 / STEP: emit `usage` fields into the ledger per shift.
**MC-10 PRE-REGISTERED-EVAL** / WHAT: held-out items with outcome checks; score cost per verified action + cache-read %; only then test any external memory system / WHY: vendor numbers self-reported; Mem0 below long context; LoCoMo answer key ~6.4% wrong, Zep re-scored 84%→58.44% / EFFORT M / GAIN avoids a wrong purchase / RISK a week before savings / SRC [S11] 2026-07-09, [S12] / STEP: freeze 30 completed items with verification commands.

## 10. Not verified, and why
**MemOS**: no primary source, price or benchmark found — unknown. **cognee/LangMem/Supermemory/Zep cloud** pricing and latency come from a competitor-authored comparison that sells Hindsight [S19]; only licences are corroborated by [S11], which itself lists cognee/LangMem internals as gaps. **All headline memory accuracies** (Mem0 26%, Zep 94.8% DMR/18.5% LongMemEval, Supermemory 81.6%, Hindsight 94.6%) are vendor-self-reported; none cleanly reproduced. **Anthropic's minimum cacheable token count** was truncated in my fetch; OpenAI's 1,024 and Gemini's 4,096/2,048 are verified; DeepSeek's doc states no minimum. **Gemini explicit-cache storage pricing** was cut off, so §4's Gemini figure excludes it (lower bound). **OpenAI dollar prices** were not read; that row is in multiples of the uncached rate. **Compaction's accuracy effect** is unpublished; the 100k→2–3k figure is a doc example. **AgentRewind** gives no numbers or code link. **GEPA** transfer untested (arXiv 2606.19605 not read). **Voyager's** figures are 2023 abstract numbers with no independent reproduction. **[S11]** is a third-party aggregation (self-reported 24/25 claims verified) used as a map to primaries. Nothing in §5/§8/§9 was tested on your journal/ledger: gains are cited measurements from other workloads or §4 arithmetic.

## 11. Sources (URL + date + what it established)
- [S1] api-docs.deepseek.com/quick_start/pricing/ 2026-09-30 — Flash hit $0.003/0.006, miss $0.15/0.30; V4-Pro $0.022/0.044, $0.66/1.32.
- [S2] api-docs.deepseek.com/guides/kv_cache/ 2026-09-30 — best-effort on-disk cache, cleared hours–days, no stated minimum.
- [S3] platform.claude.com/docs/en/build-with-claude/prompt-caching 2026-09-30 — write 1.25×/2×, read 0.1×, 5m TTL refreshed on use.
- [S4] platform.claude.com/.../optimizing-for-cost-and-intelligence 2026-09-30 — 84% cache-read, −2.7–5.3×, triage −83%/−88%, $37.94→$7.12, orchestrator 47–55%, clock −28–54%, clearing cost more than saved.
- [S5] platform.claude.com/.../tool-search-tool 2026-09-30 — 55k tokens cut >85%, 3–5 tools, degrades past 30–50.
- [S6] platform.claude.com/.../compaction + /context-editing 2026-09-30 — summary mechanics; clearing invalidates cache.
- [S7] platform.claude.com/.../memory-tool 2026-09-30 — /memories store; progress-log+checklist pattern.
- [S8] developers.openai.com/api/docs/guides/prompt-caching 2026-09-30 — write 1.25×, read 0.1×, 1,024-token min, 30m TTL, compaction resets reuse.
- [S9] ai.google.dev/gemini-api/docs/pricing + /generate-content/caching 2026-09-30 — 3.8 Flash $0.75/$0.075/$3.75, min 4,096/2,048, TTL 1h, batch −50%.
- [S10] docs.letta.com/pricing 2026-09-30 — Free/Pro $20, API $20 + $0.10/agent/mo.
- [S11] raw.githubusercontent.com/nlqdb/nlqdb/.../agent-memory-quality-landscape.md 2026-07-09 — claims map; F1 21.3→41.9; answer key 6.4% wrong; Zep 84%→58.44%.
- [S12] arxiv.org/abs/2603.04814 2026-03-05 — long context beats fact-memory; memory cheaper after ~10 turns at 100k.
- [S13] zenodo.org/records/22985242 v3 2026-09-27 — selection non-inferior at tight budget, 3,061× cheaper writes; code/data released.
- [S14] arxiv.org/abs/2605.07313 2026-05-08 — HippoRAG −16–20 pp under irrelevant-session growth.
- [S15] arxiv.org/abs/2608.10108 2026-08-10 — MESA +8.5% with 41% fewer evidence tokens.
- [S16] arxiv.org/abs/2605.19576 v3 2026-07-29 — library drift; +0.0 vs +16.2 pp; 0.258→0.584.
- [S17] proceedings.iclr.cc/.../0e9e708b6f48e14fd0ac29e167413f76 ICLR 2026 — GEPA +6/+19 pp over GRPO, 35× fewer rollouts.
- [S18] arxiv.org/abs/2608.14380 2026-08-14 — AgentRewind context+environment checkpoints; MettleBench.
- [S19] vectorize.io/articles/best-ai-agent-memory-systems 2026-03-14 — competitor-authored licence/pricing table.
- [S19b] arxiv.org/abs/2305.16291 (2023-05) + github.com/MineDojo/Voyager — skill library: 3.3× items, 2.3× distance, 15.3× faster milestones.
