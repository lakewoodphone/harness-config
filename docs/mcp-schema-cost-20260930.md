# MCP schema cost, measured — and the TS-1/TS-2 row removal (2026-09-30)

**Question this answers.** What do the six MCP families mounted by
`presets/zabz/agent.cordis.yml` cost on every request, measured from the files on this
machine, and what is the measured saving when `mcp-fetch` (TS-1) and `mcp-context7`
(TS-2) are dropped?

**Machine / when.** `ZABZ-YOGA`, 2026-09-30. Everything under `~/.dsh` was read only.
The only writes anywhere are this file and the two rows removed from the preset. No
install, no sync, no commit.

**Source note on the brief.** `docs/autonomy-fleet-20260930/b2-tool-stack.md` is not in
the working tree of the current branch (`agent/deployed-truth`) — `docs/` has no
`autonomy-fleet-20260930` directory. It does exist at commit `db19a7e`
("docs: add the fleet research reports and evidence log beside the audits"), and was
read from there:

```
git show db19a7e:docs/autonomy-fleet-20260930/b2-tool-stack.md
```

§8 is the cut ("disable `mcp-fetch` and `mcp-context7` — 4,121 + 4,665 = **8,786 of
87,777 MCP schema chars (10.0 %)**, ≈2,196 of ~21,944 tokens"); §9 lists TS-1, TS-2 and
TS-3. Sections 1, 3, 8 and 9 were read before any measurement.

---

## 0. Method, and the character convention

A `request/header` event in a DSH session log carries the whole tool catalogue exactly
as the model receives it: `data.header.tools`, each entry `{name, description,
parameters}`, with MCP names bridged as `mcp__<serverName>__<rawName>`
(`~/.dsh/profiles/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js:121`; the
`output` field exists on the runtime definition but is **not** in the header).

Every character count below is `len(json.dumps(tool))` with Python's default
separators — the same convention `docs/dsh-at-scale/notes/_m06/header_tools.py` uses,
so the numbers are directly comparable to the audit's. The instructed conversion is
**4 characters per token**.

Two independent measurements are reported:

1. **Recorded catalogue** — the real mount, from this machine's session store:
   ```
   & 'C:\Users\ezabz\code\personal-secretary-mvp\.venv\Scripts\python.exe' `
     docs/dsh-at-scale/notes/_m06/header_tools.py `
     'C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz-code--\session-b60e96b3-6a48-4898-a770-bc9eb576b9ce\session.v3.jsonl.zstd'
   ```
   (The repo script prints the *first* header; a scratch copy in `%TEMP%` was extended
   to walk all 67 headers and to re-serialize a filtered list. Same convention.)

2. **Live catalogue** — each server spawned with the exact command from the preset and
   asked `tools/list` over stdio (JSON-RPC `initialize` → `notifications/initialized` →
   `tools/list`), then each returned tool re-wrapped as `{name: "mcp__<family>__<raw>",
   description, parameters: inputSchema}` and measured in the same convention. The
   wrapper is validated by `fetch`: live gives **4,121 chars, byte-identical to the
   recorded header** (below).

---

## 1. Per-family cost — the recorded catalogue (the report's basis)

Source: `session-b60e96b3`, **first** `request/header` (`reason: "initial"`), replayed
and re-measured 2026-09-30.

| family | tool prefix | tools | chars | tokens @4 | share of MCP chars |
|---|---|---:|---:|---:|---:|
| firecrawl | `mcp__firecrawl__` | 27 | 39,770 | 9,942.5 | 45.3 % |
| playwright | `mcp__playwright__` | 24 | 17,006 | 4,251.5 | 19.4 % |
| jina | `mcp__jina__` | 22 | 14,265 | 3,566.2 | 16.3 % |
| secretary | `mcp__secretary__` | 14 | 7,950 | 1,987.5 | 9.1 % |
| context7 | `mcp__context7__` | 2 | 4,665 | 1,166.2 | 5.3 % |
| fetch | `mcp__fetch__` | 6 | 4,121 | 1,030.2 | 4.7 % |
| **MCP total** | | **95** | **87,777** | **21,944.3** | 100 % |
| builtin (no prefix) | | 27 | 29,399 | 7,349.8 | — |
| **whole catalogue** | | **122** | **117,176** | **29,294.0** | MCP = 74.9 % |

**This reproduces the report exactly: 95 MCP tools, 87,777 MCP chars, 122 tools,
117,176 chars.** Every per-family row matches `06-multipliers.md:105-114` digit for
digit.

**But it is one header out of 67, and not the modal one.** Across all 67
`request/header` events of the same session there are four distinct catalogues:

| count | tools | MCP tools | MCP chars |
|---:|---:|---:|---:|
| 26 | 122 | 95 | 87,777 |
| 38 | 110 | 83 | 81,231 |
| 2 | 108 | 81 | 79,827 |
| 1 | 127 | 97 | 90,952 |

So the fixed MCP block in that session ranged **79,827–90,952 chars (81–97 tools)** as
servers connected and disconnected across `series`/`resume` boundaries; the headline
87,777 is the initial, largest-but-one reading, and 81,231 is the mode. The
secretary row is the biggest single swing (14 tools → 0: `03-prefix.md:244`).

---

## 2. Live re-measurement of the same six servers (2026-09-30)

Same six commands the preset declares, spawned now and asked `tools/list`:

```
node  ...\mcp-fetch-server\dist\index.js
node  ...\@playwright\mcp\cli.js --headless --no-sandbox --output-dir <...>
node  ...\firecrawl-mcp\dist\index.js                                   (FIRECRAWL_API_KEY from .env)
node  ...\@upstash\context7-mcp\dist\index.js                           (CONTEXT7_API_KEY from .env)
node  ...\mcp-remote\dist\proxy.js https://mcp.jina.ai/v1 --header "Authorization: Bearer <JINA_API_KEY>"
ssh -T -o BatchMode=yes ... secretary-ts /home/zabz/.../python /home/zabz/.../ps_mcp_server.py
```

(all under `C:\Users\ezabz\.dsh\tools\mcp\node_modules\`; keys read from
`personal-secretary-mvp/.env`)

| family | recorded tools | recorded chars | live tools | live chars | Δ tools | Δ chars |
|---|---:|---:|---:|---:|---:|---:|
| firecrawl | 27 | 39,770 | 27 | 39,806 | 0 | +36 |
| playwright | 24 | 17,006 | **26** | **18,410** | +2 | +1,404 |
| jina | 22 | 14,265 | **12** | **8,228** | −10 | −6,037 |
| secretary | 14 | 7,950 | **0** | **0** | −14 | −7,950 |
| context7 | 2 | 4,665 | 2 | 4,689 | 0 | +24 |
| fetch | 6 | 4,121 | 6 | **4,121** | 0 | **0** |
| **total** | **95** | **87,777** | **73** | **75,254** | −22 | −12,523 |

Notes on the live column:

* `fetch` is **byte-identical** to the recorded header — the wrapping and the
  character convention are validated, so the other deltas are real definition drift,
  not measurement error.
* `jina` exposes 12 tools today against 22 in the recording; the remote endpoint's
  catalogue shrank. `playwright` exposes 26 against 24 (`browser_webmcp_call` /
  `browser_webmcp_list` now present, and per-tool descriptions grew ~60 chars).
  `firecrawl` and `context7` moved by +36 and +24 chars.
* `secretary` **did not answer at all** from this seat: `ssh -T -o BatchMode=yes ...
  secretary-ts` hung past a 120 s foreground test and past a 75 s in-script timeout.
  Its recorded 14 tools / 7,950 chars are carried in the table for completeness only.
  On the live seat today that family contributes **0** — so the *live* six-family fixed
  cost is 75,254 chars, not 87,777, and the difference is not a saving we chose.

**Conclusion for the table:** the recorded catalogue is a faithful reading of the
servers as they were, and today's servers are cheaper for jina, dearer for playwright,
and missing secretary entirely. The cut below is therefore measured on the **recorded**
basis (the brief's basis) and cross-checked on the live basis.

---

## 3. Before / after — measured, not estimated

`mcp-fetch` (6 tools) and `mcp-context7` (2 tools) removed from the real tool list, which
is then re-serialized and re-summed (no subtraction of summary figures):

**Recorded basis** (all families present)

| | tools | chars | tokens @4 |
|---|---:|---:|---:|
| before — whole catalogue | 122 | 117,176 | 29,294.0 |
| before — MCP only | 95 | 87,777 | 21,944.3 |
| **after — whole catalogue** | **114** | **108,390** | **27,097.5** |
| **after — MCP only** | **87** | **78,991** | **19,747.8** |
| **measured delta** | **−8** | **−8,786** | **−2,196.5** |

−8,786 chars is **10.0 %** of MCP schema chars and **7.5 %** of the whole catalogue;
the two rows are 3.75 % of the fixed prefix in tokens.

**Live basis** (five families that answered today; secretary absent)

| | tools | chars | tokens @4 |
|---|---:|---:|---:|
| before | 73 | 75,254 | 18,813.5 |
| after | 65 | 66,444 | 16,611.0 |
| **delta** | **−8** | **−8,810** | **−2,202.5** |

The delta moves by 24 chars between the two bases (context7's two descriptions grew);
the tool count removed is 8 either way.

---

## 4. Mentions in the stored session projections

Scan over every JSON projection in
`C:\Users\ezabz\.dsh\storages\session_projcache\sessions` — **983 projections on this
machine** (the brief counted 1,611, a different snapshot/machine). Read in full, 0
unreadable.

| family | projections containing `mcp__<family>__` | occurrences | projections containing the family name anywhere |
|---|---:|---:|---:|
| firecrawl | 20 | 30 | 48 |
| jina | 18 | 26 | 34 |
| fetch | 6 | 6 | 246 |
| secretary | 2 | 7 | 208 |
| playwright | 1 | 1 | 9 |
| context7 | **0** | **0** | 2 |

**This is a mention count, NOT a call count.** The projection cache carries no
tool-call field, so it can say a family was named in a stored session; it can never say
the family was invoked. The "name anywhere" column is dominated by false friends
(208 × `secretary` is mostly the repository name `personal-secretary-mvp`; 246 ×
`fetch` is mostly the builtin `web_fetch`). The `mcp__…__` column is the honest one, and
it reproduces the brief's verdict — `context7` 0/983 and `fetch` 6/983 are the two
least-mentioned families on the seat.

---

## 5. TS-3 — one reader, not two: evidence only, no row change

From the recorded table (§1):

| set | tools | chars | % of MCP chars |
|---|---:|---:|---:|
| firecrawl + jina (both general readers) | 49 | 54,035 | 61.6 % |
| firecrawl + jina + fetch | 55 | 58,156 | 66.3 % |

The brief's §8 quotes "54 tools / 54,035 chars" for this overlap. The **character**
figure is exact (39,770 + 14,265); the **tool** figure is 49, not 54 — the 54,035 is
firecrawl+jina alone, while 54 tools is not a sum of any two family rows in the table.
Adding fetch gives 55 tools. Flagging the slip rather than repeating it.

TS-3 cannot be patched from here: the mcp-client row shape has no per-tool allowlist
(`06-multipliers.md:123`), so "one reader" means deleting a whole family, and which one
to delete depends on invocation counts that do not exist on this machine (§4 is
mentions, not calls; the brief's own TS-3 says "needs TS-7"). No row was changed for
TS-3.

---

## 6. The patch (TS-1 + TS-2)

`presets/zabz/agent.cordis.yml` — two rows removed, nothing else touched. The diff is
the `git diff` on that one file; both blocks are deleted whole, with a short tombstone
recording why.

**What the patch does NOT do (read this before believing the cut is live):**

* `~/.dsh/.agent-presets/zabz/agent.cordis.yml` is the **installed** copy and is
  untouched — deliberately. The save appears on the seat only after a sync, and only
  after the running session reloads its composition.
* `profiles/web/cordis.patch.yml:1568-1595` contains a **managed "preset-rows" block**
  that injects all six MCP rows (including `mcp-context7` and `mcp-fetch`) into the
  `web` profile. Per `docs/autonomy-fleet-20260930/b2-tool-stack.md` §2 that injected
  block is what the live seat actually mounts. That file is outside this task's
  ownership and was not edited, so the repo patch alone does not yet stop the mount —
  the managed block must be regenerated by its own generator in a follow-up.
* `scripts/make_zabz_preset.py:427-464` still emits both rows; regenerating the preset
  with it would re-add them. The generator is not owned here and was not edited.
* `profiles/mesh-browse/cordis.patch.yml:29-32` already omits the two families on
  purpose and cites TS-1/TS-2 — consistent with this patch, no change needed.
* Other references to `mcp-fetch-server` / `context7-mcp` in `scripts/` and
  `packages/plugin-health` are process-classification patterns and a test fixture; they
  do not need to change.

---

## 7. Verdict on the report's "87,777 characters and 95 tools"

**Confirmed as a measurement** — reproduced digit for digit from the recorded header of
`session-b60e96b3`, and independently corroborated by live `tools/list` (fetch
byte-identical at 4,121 chars).

**Qualified as a constant** — it is one of four catalogues observed in that same
session (79,827–90,952 chars; 81–97 MCP tools), and it is not the mode (38 of 67
headers were 83 tools / 81,231 chars). Measured live today the same six families total
73 tools / 75,254 chars, because jina's catalogue shrank, playwright's grew, and
secretary did not answer from this seat at all.

**The delta for TS-1 + TS-2 stands on both bases: 8 tools and 8,786 characters removed
(10.0 % of MCP schema chars, ≈2,196 tokens per request at 4 chars/token).**

---

## 8. Not verified

* The **brief file itself is not on the branch**; §1/§3/§8/§9 were read from commit
  `db19a7e`, which may not be the revision the task assumed.
* **No call counts.** Every usage number here is a mention in projection text; the
  cached projections have no tool-call field, and a real census means decompressing the
  whole `.zstd` session store (the brief skipped the same 487 MB).
* **secretary live**: `ssh secretary-ts` did not answer (timed out at 120 s and at
  75 s), so its row is recorded-only and its live contribution is 0 on this seat.
* **jina live** was measured through `mcp-remote` to `https://mcp.jina.ai/v1`; the
  catalogue that came back (12 tools) depends on that remote endpoint today.
* **Token counts are the instructed 4 chars/token estimate**, not tokenizer counts; the
  audit's own cross-check divisor was ~3.9 (`06-multipliers.md:119`).
* **The mount is not changed.** Nothing was installed, synced or reloaded; the
  `profiles/web` managed block and the preset generator still carry both rows.
* Scratch measurement scripts lived in `%TEMP%\mcp-cost-20260930\` (outside the repo);
  the two commands in §0 reproduce the numbers with the repo's own `header_tools.py`.
