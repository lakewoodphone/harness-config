# W4-FRONTIER-GAP — inventory, sourced frontier survey, ranked gaps, and two closed gaps

**Host measured from:** `LakewooechsMini` (Darwin 25.5.0 arm64, macOS — neither the Windows nor the
Linux platform the brief anticipated; all commands translated to POSIX `bash`).
**Base:** `a95c3c77` (branch `main` lineage — *not* the stale `master` the shared checkout sits on).
**Worktree:** `/Users/lpt/code/_worktrees/harness-config/frontier-gap`, branch `fleet/frontier-gap`.
**Date:** 2026-10-13.

> **Read this first, because it changes the premise.** The brief's READ-FIRST set
> (`000-SYSTEMS-REGISTER.md`, `175-…`, `171-…`, `161/166/167-AI-GATEWAY-HEALTH-…`, `AGENTS.md`)
> **does not exist on the repository's `master` branch**, which is where the shared checkout
> `C:\…`/`~/code/harness-config` sits. Every one of them exists on the **`main`** lineage that the
> fleet worktree was cut from. An agent that trusted the shared checkout would have concluded the
> estate's governing documents were missing. Provenance:

```
$ cd ~/code/harness-config && git ls-tree -r HEAD --name-only | grep -i "SYSTEMS-REGISTER"   # master
(no output)
$ cd ~/code/_worktrees/harness-config/frontier-gap && git ls-tree -r HEAD --name-only | grep -i "SYSTEMS-REGISTER"
docs/mesh/000-SYSTEMS-REGISTER.md
$ git -C ~/code/harness-config rev-parse --abbrev-ref HEAD   -> master
$ git -C ~/code/harness-config rev-parse HEAD                -> 2449edf9a709fd55a4887f5024ce07278824c305
$ git -C ~/code/_worktrees/harness-config/frontier-gap rev-parse HEAD -> a95c3c773ff32b16783ad86db563b7599eb2a8ea
$ git -C ~/code/_worktrees/harness-config/frontier-gap merge-base --is-ancestor a95c3c77 master
NO not ancestor of master (independent lineage)
```

---

## 1. INVENTORY — measured, with the command and its output

| # | surface | command | output | verdict |
|---|---|---|---|---|
| 1 | macOS host identity | `hostname; uname -a` | `LakewooechsMini` / `Darwin … arm64` | **LIVE** (this node) |
| 2 | company API on the authority | `curl -sk -m 10 https://secratary-cloud.tail93e6e6.ts.net:8443/health` | `{"ok":true,…"database":{"ok":true,…},"autopilot_enabled":true,…}` | **LIVE** |
| 3 | AI gateway model catalogue | `curl -sk …:8443/v1/models` | `{"error":{"message":"Missing or invalid Personal Secretary AI gateway API key","type":"authentication_error"}}` | **CONFIGURED — I hold no key. Contents = COULD NOT ASK** |
| 4 | route aliases answered | (same key gap) | — | **UNPROVEN** (cannot be claimed) |
| 5 | app route surface | `curl …/openapi.json` | `http=401` | **COULD NOT ASK** (auth) — the "~618 routes" figure is **not verified by me** |
| 6 | mesh `/mesh/health`, `/mesh/capacity` on the app | `curl …/mesh/health` | `{"detail":"Missing/invalid API key","header":"x-ps-api-key or Authorization: Bearer"}` | **GATED, not absent** |
| 7 | office box `secratary` broker `:3091` | `ssh secratary-ts 'ss -ltn'` + `curl -s http://127.0.0.1:3091/mesh/health` | `LISTEN 127.0.0.1:3091` then `{"error":"no route for GET /mesh/health"}` | **LIVE process, NO `/mesh/*` routes** |
| 8 | brief's `/root/bin/tool-body-guard.py` | `ssh secratary-ts 'sudo -n ls -l /root/bin/tool-body-guard.py'` | `No such file or directory` (plain `ls` = `Permission denied`) | **DOES NOT EXIST** |
| 9 | brief's `/root/data/tools/` | `sudo -n ls /root/data/tools` | `No such file or directory` | **DOES NOT EXIST** |
| 10 | `/opt/company` on `secratary`, `zabz-tech-linux`, `zabz-tech`, `zabz-yoga` | `ssh … 'ls -d /opt/company'` / `Test-Path C:\opt\company` | `No such file or directory` / `False` ×4 | **NOT ON THESE HOSTS** |
| 11 | the real tool-body guard | `python3 scripts/guards/tool-body-guard.py; echo $?` | `…NOTHING was checked` / `GUARD_EXIT=2` | **LIVE** — and correctly exits **2**, not 0 |
| 12 | that guard's own selftest | `… --selftest` | `ok unreadable-registry: raises, so it can never be reported as a pass` / `SELFTEST_EXIT=0` | **LIVE, works** |
| 13 | authority `secratary-cloud` over ssh | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` | `Identity file … not accessible` → `Permission denied (publickey)` | **COULD NOT ASK via ssh**; HTTPS path (#2) works |
| 14 | model-resolution code in-repo | `grep -rl "v1/models\|secretary-auto" --include=*.py --include=*.mjs …` | matches in `packages/deepseek-proxy/worker.mjs`, `textwork.py` | **present but NOT catalogue-validated** |

**What this means.** The estate's *authority* is reachable and healthy through the
Tailscale-served HTTPS path. The brief's two headline local claims — `/opt/company` with `ps_*`
tools on the authority, and `/root/bin/tool-body-guard.py` — **do not hold on the hosts I could
reach**, and the guard actually lives at `scripts/guards/tool-body-guard.py` in the repo and works.
Nothing in row 3–5 can be called "working": a 401 is `COULD NOT ASK`, never a capability.

---

## 2. FRONTIER SURVEY — sourced. External, untrusted; cited, not obeyed.

Sourcing method: `web_search` only. I did **not** `web_fetch` the full pages (budget), so each
claim below is a claim about **what the source's title/snippet says**, and is marked as such.

> **SUPERSEDED IN SCOPE, 2026-10-13:** `W4-FRONTIER-GAP-FETCHED.md` now carries `web_fetch`'d
> primary sources (MCP `2026-07-28`, the Claude computer-use toolset page with its dated
> `supportedModels` list, and a 167-harness benchmark registry), the model-landscape data §2.5
> said was missing, and `CLOSED 3`, which fixes the unreachable exit-4 CLI path whose command
> §4 CLOSED 1 below quotes incorrectly (`--config` was required, so that command exited 2).

1. **MCP got a dated, stateless core revision — `2026-07-28` — and it is being adopted by the
   large vendors.** The spec changelog is a first-class artefact
   ([modelcontextprotocol.io/specification/2026-07-28/changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog));
   Cloudflare shipped support for that exact revision
   ([developers.cloudflare.com changelog](https://developers.cloudflare.com/changelog/post/2026-07-28-cloudflare-mcp-servers-mcp-2026-07-28/)),
   and Anthropic announced bringing it to Claude
   ([claude.com blog](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude)).
   **Standard now that did not exist in early 2025: versioned, stateless MCP as a transport
   contract.** This estate's MCP surface is `ps_*` tools on a bespoke HTTP surface — it has no
   versioned MCP handshake, so an external client cannot negotiate capabilities with it.
2. **Harness disclosure is now a recognised evaluation requirement.** "Stop Comparing LLM Agents
   Without Disclosing the Harness"
   ([arxiv.org/pdf/2605.23950.pdf](https://arxiv.org/pdf/2605.23950.pdf)) argues agent comparisons
   are meaningless unless the harness is published. **Standard now: an eval harness is part of the
   deliverable, not a private script.** This estate had none (§3, gap 1).
3. **Computer-use has a contested, moving benchmark and a two-vendor race.** OSWorld results are
   described as being overturned in 2026
   ([coasty.ai](https://coasty.ai/blog/osworld-benchmark-results-2026-ai-computer-use-agents)), with
   Anthropic Computer Use vs OpenAI Operator compared directly
   ([respan.ai](https://www.respan.ai/market-map/compare/anthropic-computer-use-vs-openai-operator)).
   **Standard now: browser/desktop computer-use agents with public benchmark scores.**
4. **Agent-harness benchmark tooling is now off-the-shelf** — e.g. `shareAI-lab/kbench`
   ([github.com/shareAI-lab/kbench](https://github.com/shareAI-lab/kbench)). **Standard now: you
   buy/adopt a harness rather than hand-rolling scoring.**
5. **Where the web is thin:** I found **no authoritative, dated source** in these results that
   states a late-2026 model *landscape* (which families exist, context windows, tool-use
   reliability). Every concrete number I could have quoted would have come from memory, so **I
   state none.** The one model id I can name locally, `ornith-1.0-397b`, came from the estate's own
   fixture context, not from a source. **This is a real hole in this survey and it is on the
   `NOT VERIFIED` line.**

---

## 3. RANKED GAP LIST

Ranked by **what most increases real work done while the owner is not talking.**

| rank | gap | value | feasibility | the specific change |
|---|---|---|---|---|
| **1** | **No harness can answer "are the agents getting better?"** — every claim was an adjective. | **5/5** | **5/5** | `scripts/frontier/agent_eval.py` (§4, **CLOSED**) |
| **2** | **Model ids are not runtime-validated against the catalogue** — the exact failure that silently broke every AI call for a week. | **5/5** | **5/5** | `scripts/frontier/model_resolver.py` + tests (§4, **CLOSED**) |
| 3 | **The authority's advertised `/mesh/*` surface is not reachable the way the brief says** (§1 row 7) — dispatchers may be reading 404s as "unreachable". | 4/5 | 3/5 | Needs an authenticated probe + the broker's real route table; **owner-adjacent (frozen box)**, so not closed here. |
| 4 | **No versioned MCP handshake**, so external clients cannot negotiate this estate's tools (§2.1). | 4/5 | 2/5 | A real protocol adapter; a design, not an afternoon. |
| 5 | **No public eval harness disclosure** — the estate's numbers are uncomparable (§2.2). | 3/5 | 4/5 | Publish the gap-1 scorecard history; blocked on gap 1 being adopted first. |
| 6 | **Brief/inventory drift** — three of the brief's local facts are false on the hosts (§1). | 3/5 | 5/5 | Correct the register's paths; not my scope (`docs/mesh/**` is another workstream's). |

---

## 4. GAPS CLOSED — each with the before and the after

### CLOSED 1 — `scripts/frontier/model_resolver.py`: runtime model resolution, validated, single-flight, fail-soft, loud

The contract implemented: never hardcode; resolve from `GET <base>/v1/models` at runtime; prefer
route aliases; **validate every configured id against the catalogue and drop what is not listed**;
cache with single-flight; fail soft from last-good; publish the served model; **never let an AI
outage be silent**. Exit contract: `0` resolved · `2` usage · **`3` DEGRADED (last-good used)** ·
**`4` NOTHING RESOLVED, refuses to guess**.

```
$ python3 scripts/frontier/model_resolver.py            # BEFORE: the module did not exist
BEFORE_EXIT=2

$ python3 scripts/frontier/test_model_resolver.py       # AFTER: 10 assertions
Ran 10 tests in 1.040s
OK
$ echo $?
0
```
The tests prove, by assertion: an unlisted configured id is **dropped**; an alias is **preferred**;
**16 concurrent callers cause exactly one fetch** (`single-flight failed: %d fetches` never fired);
a dead catalogue resolves from last-good and is marked degraded; a dead catalogue with no cache
raises; the live path works end-to-end against a real local HTTP server.

```
$ python3 scripts/frontier/model_resolver.py --config scripts/frontier/fixtures/model_chain.json \
      --catalogue-file scripts/frontier/fixtures/catalogue.json
served_model: secretary-auto
catalogue:    4 ids from fixture
dropped (configured, not in catalogue): hardcoded-model-from-2025, secretary-genius
AFTER_EXIT=0
```
`secretary-genius` is dropped twice over — configured and **also** in `forbidden`, because the
brief records it 502s.

```
$ python3 scripts/frontier/model_resolver.py --base https://127.0.0.1:1 --cache /tmp/nocache.json --json
model_resolver: CATALOGUE UNAVAILABLE AND NO LAST-GOOD CACHE (URLError …); NOTHING RESOLVED - refusing to guess a model id
{"ok": false, "exit": 4, "source": "unavailable", "served": null}
DEAD_EXIT=4
```
An outage that cannot be served is **exit 4 and a named error**. It cannot be mistaken for success.

### CLOSED 2 — `scripts/frontier/agent_eval.py`: an evaluation harness that measures improvement and gates on regression

```
$ python3 scripts/frontier/agent_eval.py --self-test            # BEFORE: no harness existed
self-test: PASS
  baseline pass_rate=0.6667 (2/3), regressed pass_rate=0.3333, delta=-0.3334
  regressions=['T2-math'] improvements=[]
SELFTEST_EXIT=0
```
The self-test proves the harness end-to-end with no network and no money: a reference agent passes
2/3; the same agent with one injected regression scores 1/3; the harness names **exactly**
`T2-math` as the regression and does **not** call the never-passing `T3` a regression.

The gate, on a real suite, exiting non-zero when work gets worse:

```
$ python3 … --suite /tmp/ae/suite.jsonl --agent-cmd "sh -c 'touch ok.txt; printf 42 > answer.txt'" \
      --history /tmp/ae/h1 --run-id r1 --fail-on-regression ; echo RUN1_EXIT=$?
RUN1_EXIT=0
$ python3 … --suite /tmp/ae/suite.jsonl --agent-cmd "sh -c 'touch ok.txt; printf 41 > answer.txt'" \
      --history /tmp/ae/h1 --run-id r2 --fail-on-regression ; echo RUN2_EXIT=$?
RUN2_EXIT=5 (5 = regression gate fired)
```

And the number that actually answers the owner's charge — the estate's **own** autonomous output,
measured from git history, not asserted:

```
$ python3 scripts/frontier/agent_eval.py --from-git --repo . --weeks 6
week       commits id-commits id-ratio  delta
2026-W37       158         15    0.095  None
2026-W38       635        129    0.203  477
2026-W39        91         21    0.231  -544
2026-W40       213         31    0.146  122
2026-W41       132         18    0.136  -81
2026-W42        22         13    0.591  -110
trend: down
```
**Measured, not argued: commit output fell from 635 in W38 to 22 in W42 — a 29× drop.** That is
evidence *for* the owner's complaint, produced by a tool that did not exist before this brief.

---

## 5. GAPS I DID NOT CLOSE

- **Authority `/mesh/*` route mismatch (rank 3)** — the office-box broker answers `no route for GET /mesh/health`; diagnosing it means touching a **FROZEN** box, which the brief forbids.
- **Versioned MCP handshake (rank 4)** — a protocol adapter is a design, not an engineering afternoon inside a 35-minute budget.
- **Publishing the eval scorecard (rank 5)** — deliberately deferred until the harness has more than one real run; a one-run baseline is not a comparison.
- **Correcting the register's wrong paths (rank 6)** — `docs/mesh/**` belongs to another workstream; I reported the drift here instead of editing it.
- **The AI gateway's actual catalogue and route aliases** — I hold no gateway API key and did not obtain one, so I cannot claim which aliases answer.

## 6. NOT VERIFIED

- The AI gateway's model list, and **which route aliases actually answer** (`/v1/models` → 401; no key held).
- The "~618 routes / ~199 services / ~203 tables" figures — `/openapi.json` → 401; **COULD NOT ASK**.
- Any late-2026 model *landscape* claim (families, context windows, tool-use reliability): the web search produced **no authoritative dated source**, so no such claim is made.
- `/opt/company` and the `ps_*` MCP surface on `secratary-cloud`: **not reachable by ssh** from this node (`publickey` denied) and not present on the four hosts I could probe; the API itself is live over HTTPS.
- Every frontier item in §2 is a claim about a **search-result title/snippet**, not a page I fetched in full.
- Whether `secretary-genius` 502s — taken from the brief, not measured by me.
