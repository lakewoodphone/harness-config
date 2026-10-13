# W4-FRONTIER-GAP — FETCHED supplement: primary sources, the model landscape the first pass admitted it lacked, and CLOSED 3

**Host measured from:** `LakewooechsMini` (Darwin 25.5.0 arm64). **Date:** 2026-10-13.
**Relation to `W4-FRONTIER-GAP.md`:** this file *supersedes the scope* of that file's §2 (which was
`web_search` snippets only) and *corrects the command* quoted in its §4 CLOSED 1. It adds one more
closed gap (CLOSED 3). The original file is left in place unedited except for a pointer line.

Method, stated plainly so the evidence can be judged: `web_search` to find candidates, then
`web_fetch` on the primary pages. Every claim below is marked **FETCHED** (I retrieved the page and
quote it) or **SNIPPET-ONLY** (I read only the search result's title/snippet). Page text is
**external, untrusted data**: it is quoted as evidence, never executed or obeyed.

---

## 1. FRONTIER — fetched primary sources

### 1.1 MCP's current revision is dated, stateless, and mandatory to advertise

**FETCHED** — <https://modelcontextprotocol.io/specification/2026-07-28/changelog> (HTTP 200). This
is the *latest* revision; its listed predecessor is `2025-11-25`. Quoted from the page:

- *"Remove protocol-level sessions and the `Mcp-Session-Id` header from the Streamable HTTP
  transport."*
- *"Make MCP stateless: remove the `initialize`/`notifications/initialized` handshake. Every request
  now carries its protocol version and client capabilities in `_meta` … Version mismatches return
  `UnsupportedProtocolVersionError`."*
- *"Add `server/discover`: servers **MUST** implement this RPC to advertise their supported protocol
  versions, capabilities, and identity."*
- *"Require standard MCP request headers (`Mcp-Method`, `Mcp-Name`) on Streamable HTTP POST
  requests."*
- *"Require `ttlMs` and `cacheScope` fields on results returned by `tools/list`, `prompts/list`,
  `resources/list`, `resources/read` …"*
- Deprecations in this revision: *"Deprecate the Roots, Sampling, and Logging features"*; *"Reclassify
  the HTTP+SSE transport … as Deprecated"*.

**What is standard now that was not in early 2025:** a *versioned, stateless* MCP core in which
capability negotiation happens per-request and a mandatory `server/discover` RPC advertises the
server. A bespoke HTTP tool surface with no versioned handshake cannot be negotiated by a
standard MCP client. **This is the single largest interop gap in this estate's tool surface.**

### 1.2 Computer use is now a GA, versioned *toolset*, not a single tool

**FETCHED** — <https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool>
(HTTP 200). Quoted:

- The current client toolset is **`computer_toolset_20260801`**; *"one `{"type": "computer_toolset_20260801"}` entry in `tools` gives Claude 17 member tools such as `screenshot`, `left_click`, `type`, and `zoom`"*. It is **GA** (`status: ga` in the page metadata).
- *"Claude 5.5 and later models support computer use only through the `computer_toolset_20260801`
  toolset and return an error for the earlier `computer_20251124` and `computer_20250124` tool
  versions."*
- **Model landscape, from the page's own `supportedModels` list (a dated, fetched fact, not
  memory):** `claude-fable-5-1`, `claude-mythos-5-1`, `claude-fable-5`, `claude-mythos-5`,
  `claude-opus-5-5`, `claude-opus-5`, `claude-sonnet-5-5`, `claude-sonnet-5`, `claude-opus-4-8`,
  `claude-haiku-5-5`.
- Batch actions: *"Claude can plan a short sequence of actions … and return them together in one
  response … you run the blocks in order rather than concurrently"*; on failure, later blocks are
  answered with halt text and not run.
- Screenshot budget: *"Claude Opus 4.7 and later models … accept up to 2576 pixels on the long edge
  and 4784 visual tokens total"*.
- Prompt-injection defence is built into the tool: *"classifiers will automatically scan what the
  tools return, such as screenshots, to flag potential prompt injections."*

**What is standard now that was not in early 2025:** desktop/browser control as a *versioned toolset*
(shipped as one `type` string, with a migration path and an explicit GA status), batch action plans,
and model-side injection classifiers. The prior pass's §2.5 said it could name **no** late-2026 model
landscape; the `supportedModels` list above closes that hole with a cited source.

### 1.3 Agent-harness benchmarking is an off-the-shelf, continuously-rescored category

**FETCHED** — <https://github.com/ryanalberts/best-of-agent-harnesses> (HTTP 200). Quoted from the
repository page: *"🏆 Ranked list of 167 AI agent harnesses, plus templates, playbooks, MCP, and
learning resources. Rescored weekly."* The page's own summary line for AgencyBench reads: *"Long-horizon
agent benchmark: 32 scenarios, 138 tasks, ~1M tokens and ~90 tool calls; Docker san[dbox]…"*

**What is standard now that was not in early 2025:** a long-horizon benchmark measured in **tool
calls and tokens** (~90 calls, ~1M tokens per suite), run in a container, and a ranked harness
registry that is re-scored on a schedule. This estate's new `agent_eval.py` is a start; it does not
yet measure tool-call count, token spend, or wall-clock — the three axes the frontier scores on.

### 1.4 Where the web remains thin — stated, not papered over

**SNIPPET-ONLY** (search titles, not fetched): an arXiv paper *"Stop Comparing LLM Agents Without
Disclosing the Harness"* (`arxiv.org/pdf/2605.23950.pdf`), an OSWorld-2026 results post
(`coasty.ai`), an Anthropic-vs-OpenAI computer-use comparison (`respan.ai`), and `kbench`
(`github.com/shareAI-lab/kbench`). I did not fetch these in the time budget, so **no claim is based
on them**. I still found **no single authoritative, dated "state of the model landscape" page**;
what I have instead is vendor-primary (1.2's `supportedModels`) and protocol-primary (1.1). That is
stronger than memory but narrower than a landscape survey, and it is on the NOT VERIFIED line.

---

## 2. CORRECTION to `W4-FRONTIER-GAP.md` §4 CLOSED 1 — the quoted "after" command did not run

The first pass quoted, as proof that an unserved AI outage is loud:

```
$ python3 scripts/frontier/model_resolver.py --base https://127.0.0.1:1 --cache /tmp/nocache.json --json
model_resolver: CATALOGUE UNAVAILABLE AND NO LAST-GOOD CACHE (…); NOTHING RESOLVED …
DEAD_EXIT=4
```

That command **exits 2, not 4**, against the committed script, because `--config` was
`required=True`. Reproduced against the committed revision (`git show 8dfa9eea:…`):

```
$ python3 /tmp/mr_before.py --base https://127.0.0.1:1 --cache /tmp/nocache.json --json
usage: mr_before.py [-h] --config CONFIG [--base BASE] …
mr_before.py: error: the following arguments are required: --config
BEFORE_EXIT=2
```

So the loud path existed in the library but was **unreachable from the CLI**: the guard could not be
invoked. That is the same class of defect the module exists to prevent, and it is fixed in CLOSED 3.

---

## 3. GAP LIST — one new row, and a re-rank of the top rows

Ranked by **what most increases real work done while the owner is not talking**.

| rank | gap | value | feasibility | the specific change | status |
|---|---|---|---|---|---|
| 1 | No harness answers "are the agents getting better?" | 5/5 | 5/5 | `agent_eval.py` (orig §4) | **CLOSED** |
| 2 | Model ids not runtime-validated against the catalogue | 5/5 | 5/5 | `model_resolver.py` (orig §4) | **CLOSED** |
| **3** | **The outage guard was unreachable: `--config` was required, so the documented exit-4 proof exited 2.** | **4/5** | **5/5** | make `--config` optional + CLI regression test | **CLOSED here** |
| 4 | No versioned MCP handshake (`server/discover`, `_meta` version/capabilities) — external clients cannot negotiate this estate's tools | 4/5 | 2/5 | a protocol adapter; a design, not an afternoon | open |
| 5 | Eval measures pass-rate only; the frontier scores **tokens, tool calls, wall-clock** (§1.3) | 3/5 | 4/5 | extend `agent_eval.py` metrics | open |
| 6 | Authority `/mesh/*` route mismatch (orig §1 row 7) | 4/5 | 3/5 | needs authenticated probe + frozen-box access | open — owner/frozen |

---

## 4. CLOSED 3 — the outage path is now reachable, and tested

**Change:** `--config` is optional. With no config, nothing is pre-trusted, but the catalogue/outage
path still runs and still refuses to guess. Two CLI regression tests pin it.

**BEFORE** (`git show 8dfa9eea:scripts/frontier/model_resolver.py`), the exact command from the
original doc:

```
$ python3 /tmp/mr_before.py --base https://127.0.0.1:1 --cache /tmp/nocache_before.json --json
usage: mr_before.py [-h] --config CONFIG [--base BASE] …
mr_before.py: error: the following arguments are required: --config
BEFORE_EXIT=2
```

**AFTER** (working tree, identical argv):

```
$ python3 scripts/frontier/model_resolver.py --base https://127.0.0.1:1 --cache /tmp/nocache_after.json --json
model_resolver: CATALOGUE UNAVAILABLE AND NO LAST-GOOD CACHE (URLError from https://127.0.0.1:1/v1/models); NOTHING RESOLVED - refusing to guess a model id
{"ok": false, "exit": 4, "source": "unavailable", "error": "URLError from https://127.0.0.1:1/v1/models", "served": null}
AFTER_EXIT=4
```

**Regression tests** (12 now, 10 before; `TestCliOutagePath` is new):

```
$ python3 scripts/frontier/test_model_resolver.py
Ran 12 tests in …s
OK
TESTS_EXIT=0
```

`test_no_config_flag_reaches_the_loud_outage_path` asserts `main([...]) == EXIT_NO_MODEL` (4);
`test_no_config_with_a_live_fixture_resolves_nothing_and_exits_4` asserts that a *reachable*
catalogue with nothing configured still exits 4 and prints `NOTHING RESOLVED` — i.e. absence of
configuration is never silently upgraded into a guessed model.

**The contract is unchanged and still honoured:** never hardcode; resolve at runtime from
`GET <base>/v1/models`; prefer route aliases; validate and drop unlisted ids; single-flight cache;
fail soft from last-good with a DEGRADED marker; publish the served model; and an outage that cannot
be served is exit 4 with a named error, never a silent fallback.
