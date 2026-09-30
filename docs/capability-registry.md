# Capability registry

**Built:** 2026-09-30 by a mesh child on `zabz-yoga`.
**Owner:** whoever owns `scripts/cap/`. **Files:** `scripts/cap/cap.py`,
`scripts/cap/providers.json`, this document.

---

## 1. The problem this exists to solve

The owner pays for five search providers while the agents can reach none of them.
One env file holds the provider keys; some are used by the application, some by the
harness, some by nothing at all. Before this registry, nothing anywhere answered:

| question | before | now |
|---|---|---|
| what capability do we have | grep five repos | `cap.py list` |
| what does it cost | four vendor pages, half of them 404 | the COST column |
| is it wired | an opinion | the **WIRED** flag, derived by searching |
| can an agent actually reach it | an assumption | the **REACHABLE** flag, derived from the seat |
| is it alive right now | nobody knew | `cap.py --probe NAME` |

Every gap found on 2026-09-30 was one of those five questions.

## 2. The registry is data, not code

**All provider knowledge lives in `scripts/cap/providers.json`. `cap.py` contains no
provider list.** Adding a provider, retiring one, changing a price, a category, a
credential env var name, a search alias or a health check is an edit to that file.

Add a provider — append one object:

```json
{
  "id": "example",
  "name": "Example Search",
  "category": "search",
  "cred_env": ["EXAMPLE_API_KEY"],
  "billable": true,
  "cost": "free 1k/mo; $10/10k (example.com/pricing, read 2026-09-30)",
  "refs": ["EXAMPLE_API_KEY", "example.com"],
  "native_tool": null,
  "mcp_ids": [],
  "notes": "",
  "probe": {
    "kind": "http", "method": "GET", "url": "https://api.example.com/v1/models",
    "auth": {"type": "bearer", "env": "EXAMPLE_API_KEY"},
    "ok_status": [200],
    "detail": {"kind": "list_len", "path": "data", "label": "models"}
  }
}
```

Retire a provider — delete its object. To keep the *knowledge* that a capability
existed (as `context7` does), leave the object and say so in `notes`; a provider with
no executor and no credential is a record, not a bug.

What each field means:

| field | meaning |
|---|---|
| `id`, `name` | keys for `--probe`; `name` is what the table prints |
| `category` | `search`, `scrape`, `browser`, `model`, `comms`, `db`, `storage`, `other` |
| `cred_env` | env var NAMES only. Never a value. Drives the CRED column |
| `config_env` | hosts/endpoints that are configuration, not credentials |
| `billable` | drives the "costs money" section of `--report` |
| `cost` | human price string, with its source and read date |
| `refs` | the strings the wiring scan looks for: env var names and distinctive aliases |
| `native_tool` | a harness tool name, if the capability ships as a first-class tool |
| `mcp_ids` | MCP row ids that mount it |
| `probe` | health check spec, or `{"kind":"none","reason":"..."}` |

Probe kinds: `http` (with `auth` of `bearer`, `header`, `basic`, `query` or none;
`optional: true` for endpoints that answer keylessly), `tcp_from_dsn`, `file`,
`none`. `none` is a first-class answer: it prints **NOT PROBED** and the reason,
because an unknown provider must never pretend.

The same file holds `credential_sources`, `search_roots`, `mount_roots`, `scan`
pruning rules and the observed `seat`. Those are configuration for this machine, and
they are as editable as the provider table.

## 3. The two derived flags, defined exactly

Both are **derived by searching and stated with their evidence**. The `list` output
prints the paths it searched and the per-provider files it found, so a flag can be
audited rather than believed.

**WIRED** — *some code in this repo or in `/home/zabz/bin` references it.* This is
the brief's definition. It is computed from the roots whose `role` is `primary`:
`harness-config` (this repo, with `journal/`, `_scratch/` and `scripts/cap/` pruned)
and `/home/zabz/bin` (the authority node's deployed scripts). A reference is a match
on any of the provider's `refs`. Prose is not wiring: only code and config file
extensions are scanned, `.env` files are skipped (defining a name is not using it),
and the registry's own `providers.json` is excluded so it cannot cite itself.

**REACHABLE** — *an agent running as this seat could actually call it today.* A
first-class invocation path exists in this seat's observed tool plane: a native tool
(`web_search`, `web_fetch`) or a mounted MCP row. It is deliberately **not** a
function of whether we hold a key, which is what makes *"reachable but has no
credential"* expressible.

The seat is recorded in `providers.json` (`seat.observed_tools`,
`seat.observed_mcp_tools`) because a subprocess cannot read the agent's tool plane.
It carries the date and the method, and `seat.reobserve_with` says how to refresh it.
**That is the registry's one hand-maintained input, and it is labelled as such.**

**Provenance is separate from WIRED on purpose.** The scan also covers the
application (`personal-secretary-mvp`) and `~/.dsh` (the harness config, read only),
and prints them under `REFERENCED BY`. "The app uses it" and "the fleet is wired to
it" are different facts, and collapsing them is how a capability gets paid for and
never used.

### Paths searched (and why)

| root | role | contributes to WIRED | why |
|---|---|---|---|
| `~/Code/harness-config` | primary | yes | this repo; `scripts/deployed/` inside it is the tracked mirror of `/home/zabz/bin` |
| `/home/zabz/bin` | primary | yes | the brief's second path. **ABSENT on a Windows laptop; the output says so** instead of silently skipping it |
| `~/code/personal-secretary-mvp` | application | no (provenance only) | the app's key usage, which is real but is not fleet wiring |
| `~/.dsh` | harness | no (provenance only) | where the harness wires model providers (`apiKeyEnv`) and presets. Read only; this tool never writes there |

Pruning (vendored libraries, caches, generated test artefacts, the journal) is
declared in `providers.json` under `scan` and each root's `prune_dirs` /
`prune_prefixes` / `prune_paths`, so the scan's blind spots are visible.

## 4. Commands

```bash
python3 scripts/cap/cap.py list            # the human table + all evidence
python3 scripts/cap/cap.py --json          # the same data for machines
python3 scripts/cap/cap.py --probe tavily  # one real health check (repeatable)
python3 scripts/cap/cap.py --probe all     # every provider that has a recipe
python3 scripts/cap/cap.py --report        # the publishable markdown block
python3 scripts/cap/cap.py selftest        # proves the redactor holds
```

Notes: `--json` also works with `--probe` and `--report`. `list` is the default.
`--probe` exits `1` if any probe **FAIL**s, so a monitor can alert on it; `list`,
`--json` and `--report` always exit `0`. `--env-file PATH` and `--data PATH` override
the credential file and the provider table.

### Probe policy

A probe is a real request with a real credential, and it prints **status, latency and
a one-line result** — never the credential. `OK` / `FAIL` / `NOT PROBED`. A provider
is **NOT PROBED** (with the reason) when it has no credential, no established
endpoint, or no plain-HTTP health route — Context7 (MCP over stdio/SSE), Langfuse
(both keys empty), Mosyle (no endpoint established), Plaid (would have to touch a real
bank item), the `harness-*` rows (native tools, no URL). A credential that the vendor
rejects is reported as `FAIL ... credential rejected`, which is the answer, not an
error to hide.

Two probes are worth explaining:

* **Perplexity** would bill for a completion, so the probe sends a deliberately
  invalid model. `400 invalid model` means the credential authenticated and no token
  was generated; `401` means it did not.
* **Fleet Postgres** is not HTTP. The probe parses host and port out of the DSN in
  memory and does a TCP connect. The DSN is never printed.

## 5. Credential safety

`cap.py` reads the credential file to answer *is a credential present* and *which env
var holds it*. It never prints a value:

* the CRED column carries the env var **name** and a yes/no;
* every byte the program emits passes through a redactor loaded with every non-empty
  value read from the credential file, plus the declared credential names present in
  the process environment;
* `selftest` renders every mode, pushes it through the same redactor `emit()` uses,
  and exits `2` if any guarded value survives;
* the check was also run externally: all five output modes, all 138 values in the env
  file — **0 appeared**.

The redactor is deliberately blunt, and that is visible: an 8-character configuration
value in the env file that happens to be an English word is redacted wherever it
collides with prose. A mangled word is a cheaper failure than a leaked key.

## 6. The nightly job this is for

```bash
python3 scripts/cap/cap.py --report >> "$(date +%F)-capability-registry.md"
```

`--report` answers exactly three questions in one block: **what is present but
unreachable** (grouped by category), **what is reachable but has no credential**, and
**what costs money** (metered search/scrape itemised with prices; per-token and
subscription families grouped). It closes with the set that is credentialled,
unreachable and referenced by the application alone — the "we pay for it and no agent
can touch it" list. It is short on purpose: it is meant to be read every day, so a
change in it means something changed.

## 7. What the first run found (2026-09-30, `zabz-yoga`)

43 providers. 16 wired. 33 credentialled but unreachable from this seat. 2 reachable
with no credential (`web_search`, `web_fetch`). 34 billable. The scan covered 593
files in this repo, 7,661 in the application, 21 in `~/.dsh`; `/home/zabz/bin` was
absent.

* **The paid search providers are the headline.** Tavily, Brave Search API, SerpAPI and
  Perplexity all hold valid keys. At the start of this run all four were referenced
  **only by the application** — not by this repo and not by `/home/zabz/bin` — and no
  seat could call any of them. Probes: Tavily `OK`, Brave `OK`, SerpAPI
  `OK 189ms (Free Plan)`, Perplexity `OK` (auth accepted, invalid model deliberately
  rejected so no token was generated).
* **The tree moved while this ran, and the flags moved with it.** A sibling mesh child
  landed `scripts/search/routing.json` + `search.py` mid-run, and Tavily immediately
  went from `WIRED no` to `WIRED yes(2)` with no edit to the registry. Brave, SerpAPI
  and Perplexity are still application-only. This is the registry behaving as
  intended: it reports the tree, it does not cache an opinion.
* **Mounted is not reachable.** `mcp-firecrawl`, `mcp-jina` and `mcp-playwright` are
  real rows in `presets/zabz/agent.cordis.yml` and in `profiles/mesh-browse`, and this
  seat's tool plane contains **zero** `mcp__*` tools. The registry states that per
  provider rather than calling the capability wired.
* **A live divergence.** `~/.dsh/profiles/web/cordis.patch.yml` still carries a real
  `mcp-context7` row although the repo preset removed it on 2026-09-30. The comment
  saying it is gone and the row that mounts it are in different files; the registry
  reads rows, not comments.
* **Spider and Exa have no key at all.** Both are named in the brief. Spider's
  `/scrape` answered keylessly (`OK 269ms`) — a genuine reachable-without-credential
  capability nobody arranged; Exa returns `402` without a key.
* **Probe failures worth a human look** (not registry bugs): Qwen `401`, Hetzner
  `401`, Tailscale `401` (an enrolment auth key, not an API token — the registry says
  so), Fleet Postgres TCP `ConnectionRefused`. Firecrawl's keyless `403` became `OK`
  once the stored key was used, so the endpoint is fine.
* **This registry was already committed once, badly.** Commit `6f01ddf` (round 34)
  contains an earlier in-flight snapshot of these same two files, staged and pushed by
  the manager while the child that wrote them was still working; the manager's own
  commit message records that a mesh child's `git push` over ssh hung. This revision
  supersedes that snapshot. The lesson is the durability one: an untracked file in a
  working tree can be committed by someone else at any moment.

## 8. Not verified, and why

* **Most model prices.** "per token; price not verified this session" is the honest
  value; only the search/scrape prices carry a source and a read date.
* **Jina's price** — `jina.ai/pricing` 404s (Elastic-owned). An unverified bill, and
  the registry says unverified rather than guessing.
* **Mosyle, AI Gateway, NanoDep** — no endpoint established from the repo or public
  docs in this session, so they are `NOT PROBED` with that reason.
* **Whether the MCP rows actually start.** The registry proves a row is *mounted*;
  it does not launch MCP servers. Start-up evidence lives in
  `personal-secretary-mvp/data/logs/mcp-launcher.log`.
* **Per-tool call counts.** The registry reports wiring and liveness, not usage. There
  is no call census yet (see `docs/mcp-schema-cost-20260930.md`, TS-7).
* **Python 3.10.11 on `python`, not `python3`.** On this Windows node `python3` is the
  Microsoft Store alias stub and refuses to run. The script is stdlib-only and 3.8+,
  so `python3 scripts/cap/cap.py ...` is the correct invocation on the Linux
  authority; on Windows use `python`.
* **This node only.** `/home/zabz/bin` does not exist here; on the authority the
  primary scan is wider and the WIRED counts will be higher.
