# Model currency audit — 2026-10-19

**Auditor host:** `zabz-tech` (Windows) — `hostname` → `zabz-tech`; `$env:COMPUTERNAME` → `ZABZ-TECH`.
**Authority:** `secratary-cloud`, reached over SSH — `hostname` → `secratary-cloud`; `uname -a` → `Linux secratary-cloud 7.0.0-38-generic #38-Ubuntu SMP PREEMPT_DYNAMIC Fri Sep 4 09:10:14 UTC 2026 x86_64`.
**Window:** 2026-10-19T22:16Z – 22:36Z (`date -u` on both hosts; Windows clock `2026-10-19T18:16:10-04:00`).
**Posture:** read-only on the authority. No unit started, stopped or restarted; no database write; no credential value printed. The only write was this file plus a local git branch/commit in the Windows checkout.

**Provenance convention:** every claim carries either a `[cmd]` (the command and its output line) or a `[file:line  mtime]`. Anything not measured is listed in *What I could not verify* rather than inferred.

---

## 1. What DeepSeek actually has today (upstream, provider's own docs)

Source of truth: the provider's own documentation, not a blog.

- `https://api-docs.deepseek.com/quick_start/pricing` — the Models & Pricing table:
  - `MODEL` columns `deepseek-flash` and `deepseek-v4-pro`
  - `MODEL VERSION` → **`DeepSeek-V4.1-Flash-1017`** and **`DeepSeek-V4-Pro-0813`**
  - `CONTEXT LENGTH` 1M; `MAX OUTPUT` maximum 384K; `VISION` ✓ for flash, not supported for pro.
- `https://api-docs.deepseek.com/updates/` — the change log:
  - **`## Date: 2026-10-17` → `### DeepSeek-V4.1-Flash-1017 Update`** — "DeepSeek V4.1 Flash has been upgraded to DeepSeek-V4.1-Flash-1017 … simply use `deepseek-flash` to access the latest model."
  - **`## Date: 2026-09-10` → `### DeepSeek-V4.1-Flash Release`** — "Change the model name to `deepseek-flash` … The previous-generation models V4 Flash and V4 Flash Vision Exp have been retired; for compatibility, the model names `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are temporarily routed to V4.1 Flash."
  - **`## Date: 2026-08-13` → `### DeepSeek-V4-Pro Update`** — GA of `deepseek-v4-pro`.
  - **`## Date: 2026-07-31` → `### DeepSeek-V4-Flash Update`** — `deepseek-v4-flash` = DeepSeek-V4-Flash-0731.
  - **`## Date: 2026-04-24` → `### DeepSeek-V4`** — "The two legacy API model names, `deepseek-chat` and `deepseek-reasoner`, will be discontinued in three months (2026-07-24)."

**The owner's half-memory is correct.** "4.1 flash 10 17" is `DeepSeek-V4.1-Flash-1017`, released 2026-10-17, model id **`deepseek-flash`**. There is no "DeepSeek 4.1 Flash 10 17" as a literal id — the id is `deepseek-flash` and `1017` is the version suffix.

### 1.1 Verdict table

| model id | what it is | available from (date / source) | used by us where | verdict |
|---|---|---|---|---|
| `deepseek-flash` | DeepSeek-V4.1-Flash-1017; 1M ctx, 384K out, native vision, thinking default | **2026-10-17** — api-docs.deepseek.com/updates (`Date: 2026-10-17`) | DSH `agent-default-model` in `settings/base.yaml:60`, local `~/.dsh/settings.yaml.imported:9`, authority `/root/.dsh/settings.yaml.imported:9`; picker entry `DESKTOP-FGV6KMH.yaml:143`, `LAKEWOOECHSMINI.yaml:95` | **CURRENT** (newest of the flash class) |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813; 1M ctx, no vision | **2026-08-13** — api-docs.deepseek.com/updates (`Date: 2026-08-13`) | gateway concrete id `deepseek/deepseek-v4-pro`; picker `DESKTOP-FGV6KMH.yaml:145`, `LAKEWOOECHSMINI.yaml:97` | **CURRENT (pro class)** — no newer pro has been published; still the older generation and 3.3–4.4× flash's price |
| `deepseek-v4-flash` | **retired name**; requests are served by V4.1-Flash-1017 | retired **2026-09-10**; V4-Flash-0731 itself **2026-07-31** — updates | `/opt/company/.env:17` `CEO_MODELS_JSON`; `.env:517` `AI_GATEWAY_DELEGATE_MODEL`; gateway catalog `deepseek/deepseek-v4-flash`; `model_aliases` row → `openrouter/deepseek/deepseek-v4-flash`; **13,878 calls / $239.09 in 7 days** | **CURRENT BY PROXY — name retired.** Works today only because upstream temporarily routes it; no sunset date published |
| `deepseek-v4-flash-vision-exp` | **retired name**; routed to V4.1-Flash | released **2026-08-21**, retired **2026-09-10** — updates | machine default on two boxes: `DESKTOP-FGV6KMH.yaml:79`, `LAKEWOOECHSMINI.yaml:62`; picker `:141`, `:93` | **CURRENT BY PROXY — name retired.** Same temporary bridge as above |
| `deepseek-ai/DeepSeek-V4.1-Flash` (DeepInfra id) | V4.1 Flash on DeepInfra; which point release is **not stated** | not queried (see gaps) | `base.yaml:150`, `ZABZ-YOGA.yaml:16`, `DESKTOP-FGV6KMH.yaml:157`, `LAKEWOOECHSMINI.yaml:108`, `~/.dsh/settings.yaml.imported:39` | **UNKNOWN** — could be pre-1017 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` (DeepInfra id) | V4-Flash-0731, the July 31 model | **2026-07-31**; registry marks it `retired`, `last_verified_at 2026-10-12T03:47:45Z` | `base.yaml:148`, `ZABZ-YOGA.yaml:14`, `DESKTOP-FGV6KMH.yaml:155`, `LAKEWOOECHSMINI.yaml:106` | **OLD** |
| `deepseek-chat`, `deepseek-reasoner` | legacy aliases, discontinued | discontinued **2026-07-24** — updates | none found in live config (`grep -rn` over `settings/` and `/opt/company/.env`) | **OLD — not pinned** |
| `deepseek/deepseek-v3.2`, `deepseek-r1-0528` | V3.2 (2025-12-01) / R1-0528 (2025-05-28) | superseded; gateway measured them `NOT_FOUND HTTP 400` at `2026-10-19T22:07:41Z` / `22:07:42Z` | gateway `legacy_alias` entries; `model_aliases` rows | **OLD** (advertised only so a validator does not drop a working config) |

**Not a DeepSeek release:** `secretary-genius`. It is a company route alias, still advertised by our own catalog as `default_selectable: true`; the estate's standing rule forbids it (measured 502 on 2026-09-15). See remediation 7.

---

## 2. Every place a model id is pinned

Line numbers are from the files as read during this audit; `mtime` is UTC.

| # | location (file:line or command) | pinned value | mtime | verdict |
|---|---|---|---|---|
| 1 | `settings/base.yaml:58-60` | `agent-default-model: provider: deepseek-official, model: deepseek-flash` | 2026-10-05T21:08:51Z | CURRENT |
| 2 | `settings/base.yaml:148` | `llm-pi-ai` deepinfra `deepseek-ai/DeepSeek-V4-Flash-0731` | 2026-10-05T21:08:51Z | OLD |
| 3 | `settings/base.yaml:150` | `llm-pi-ai` deepinfra `deepseek-ai/DeepSeek-V4.1-Flash` | 2026-10-05T21:08:51Z | UNKNOWN (point release) |
| 4 | `settings/machines/ZABZ-YOGA.yaml:14` | deepinfra `deepseek-ai/DeepSeek-V4-Flash-0731` | 2026-09-11T16:23:51Z | OLD |
| 5 | `settings/machines/ZABZ-YOGA.yaml:16` | deepinfra `deepseek-ai/DeepSeek-V4.1-Flash` | 2026-09-11T16:23:51Z | UNKNOWN (point release) |
| 6 | `settings/machines/DESKTOP-FGV6KMH.yaml:79` | `agent-default-model.model: deepseek-v4-flash-vision-exp` | 2026-09-15T15:03:01Z | CURRENT BY PROXY (retired name) |
| 7 | `settings/machines/DESKTOP-FGV6KMH.yaml:141` | picker `id: deepseek-v4-flash-vision-exp` | 2026-09-15T15:03:01Z | CURRENT BY PROXY (retired name) |
| 8 | `settings/machines/DESKTOP-FGV6KMH.yaml:143` | picker `id: deepseek-flash` | 2026-09-15T15:03:01Z | CURRENT |
| 9 | `settings/machines/DESKTOP-FGV6KMH.yaml:145` | picker `id: deepseek-v4-pro` | 2026-09-15T15:03:01Z | CURRENT (pro) |
| 10 | `settings/machines/DESKTOP-FGV6KMH.yaml:155,157,159` | deepinfra `…V4-Flash-0731`, `…V4.1-Flash`, `…V3.2` | 2026-09-15T15:03:01Z | OLD / UNKNOWN / OLD |
| 11 | `settings/machines/LAKEWOOECHSMINI.yaml:62` | `agent-default-model.model: deepseek-v4-flash-vision-exp` | 2026-09-15T15:03:01Z | CURRENT BY PROXY (retired name) |
| 12 | `settings/machines/LAKEWOOECHSMINI.yaml:93,95,97` | picker `vision-exp`, `deepseek-flash`, `deepseek-v4-pro` | 2026-09-15T15:03:01Z | retired / CURRENT / CURRENT (pro) |
| 13 | `settings/machines/LAKEWOOECHSMINI.yaml:106,108,110` | deepinfra `…V4-Flash-0731`, `…V4.1-Flash`, `…V3.2` | 2026-09-15T15:03:01Z | OLD / UNKNOWN / OLD |
| 14 | `settings/machines/ZABZ-TECH.yaml` (whole file) | **no model pin** — only `agent-loop.maxParallelToolCalls: 20` | 2026-09-16T14:55:24Z | n/a |
| 15 | `settings/machines/SECRATARY.yaml` (whole file) | **no model pin** (`grep -nE 'model:\|deepseek'` → no match) | 2026-10-11T22:45:07Z | n/a |
| 16 | `zabz-tech: ~/.dsh/settings.yaml.imported:7-9` (effective) | `provider: deepseek-official`, `model: deepseek-flash` | 2026-10-19T22:17:10Z | CURRENT |
| 17 | `zabz-tech: ~/.dsh/settings.yaml.imported:37,39` | deepinfra `…V4-Flash-0731`, `…V4.1-Flash` | 2026-10-19T22:17:10Z | OLD / UNKNOWN |
| 18 | `secratary-cloud: /root/.dsh/settings.yaml.imported:7-9` | `provider: deepseek-official`, `model: deepseek-flash` | 2026-10-15T14:16:37Z | CURRENT |
| 19 | `secratary-cloud: /root/.dsh/settings.yaml.imported:37,39` | deepinfra `…V4-Flash-0731`, `…V4.1-Flash` | 2026-10-15T14:16:37Z | OLD / UNKNOWN |
| 20 | `secratary-cloud: dsh --profile web --dump-config` | effective: `provider: deepseek-official`, `model: deepseek-flash` | command 2026-10-19T22:2xZ | CURRENT |
| 21 | `/opt/company/.env:14` | `MODEL_TIER1=secretary-fast` | 2026-10-19T22:04:50Z | OK (route alias) |
| 22 | `/opt/company/.env:15` | `MODEL_TIER2=secretary-auto` | 2026-10-19T22:04:50Z | OK (route alias) |
| 23 | `/opt/company/.env:16` | `MODEL_TIER3=secretary-smart` | 2026-10-19T22:04:50Z | OK (route alias) |
| 24 | `/opt/company/.env:17` | `CEO_MODELS_JSON=[{"deepseek":"deepseek-v4-flash"},{"google":"gemini-3.5-flash-lite"},{"openai":"gpt-5.4-mini"}]` | 2026-10-19T22:04:50Z | retired name (upstream-current) |
| 25 | `/opt/company/.env:517` | `AI_GATEWAY_DELEGATE_MODEL=deepseek/deepseek-v4-flash` | 2026-10-19T22:04:50Z | retired name (upstream-current) |
| 26 | `secratary-cloud: /opt/company/app/config.py:171-174` | default `ceo_models_json` contains `deepseek-v4-flash` + `deepseek-ai/DeepSeek-V4-Flash-0731` | 2026-10-19T12:38:55Z | OLD (code default) |
| 27 | `secratary-cloud: /opt/company/app/config.py:176-180` | `fast_model_openai/anthropic/copilot/google/deepseek = "deepseek-v4-flash"` | 2026-10-19T12:38:55Z | retired name (code default) |
| 28 | `secratary-cloud: /opt/company/app/assistant_chat.py:1465,1496,1925,4295` | hardcoded `("deepseek","deepseek-v4-flash")` fallbacks | 2026-10-19T21:49:36Z | retired name (code literal) |
| 29 | `secratary-cloud: /opt/company/app/services/smart_router.py` `_CAPABILITY_DB` | 4 deepseek entries: `deepseek-v4-flash`, `deepseek-v4-pro`, `deepseek-v3.2`, `deepseek-r1-0528` — **no `deepseek-flash`** | 2026-10-19T22:08:46Z | catalog misses the current model |
| 30 | `secratary-cloud: sqlite3 /root/authority.db 'select * from model_aliases …'` | `deepseek-v4-flash → openrouter/deepseek/deepseek-v4-flash`; `deepseek-v4-pro → openrouter/deepseek/deepseek-v4-pro` | DB mtime 2026-10-19T22:17:33Z | stale alias targets |
| 31 | `curl -s http://127.0.0.1:8002/v1/models` (gateway catalog) | ids include `secretary-auto/-fast/-smart/-genius`, `deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-pro`; **no `deepseek-flash`** | fetched 2026-10-19T22:07Z (`verification.checked_at 2026-10-19T22:07:40Z`) | catalog misses the current model |

### 2.1 The database (authority)

`[cmd] ssh secratary-cloud "sqlite3 /root/authority.db '.schema model_registry'"` → columns `canonical_id, provider, provider_model_id, display_name, tier, pricing_*, context_window, max_output_tokens, supports_*, lifecycle_state, is_verified, is_deprecated, discovered_at, last_verified_at, …`.

`[cmd] … 'select count(*), max(discovered_at), max(last_verified_at) from model_registry'` → `60 | 2026-08-30T16:26:04.027Z | 2026-10-12T03:47:45.307730+00:00`.

- **Newest `model_registry` row:** `copilot/claude-sonnet-4.6`, `discovered_at 2026-08-30T16:26:04.027Z`.
- **Newest DeepSeek `model_registry` row:** `deepinfra/deepseek-ai/DeepSeek-V4-Pro-0813`, `discovered_at 2026-08-23T16:21:09.630Z`, `lifecycle_state promoted`.
- **DeepSeek rows, all four:** `deepseek/deepseek-v4-pro` and `deepseek/deepseek-v4-flash` (discovered 2026-06-23), `deepseek/deepseek-r1` and `deepseek/deepseek-chat` (2026-03-06, `is_deprecated=1`). **No V4.1 row at all** — the registry has not learned about the 2026-09-10 or 2026-10-17 releases.
- **Newest row that records which model served a request:** `model_usage` id **353716**, `provider deepseek`, `model deepseek-v4-flash`, `tier fast`, `created_at 2026-10-19T22:16:11.686134+00:00`, `latency_ms 1293`, `success 1`. `served_by` is empty — the audit trail cannot name the upstream build.
- **7-day usage** (`created_at > datetime('now','-7 days')`):
  `deepseek-v4-flash` 13,878 calls / **$239.0949**; `gemini-3.5-flash-lite` 3,211 / $2.6778; `deepseek-v4-pro` 1,890 / $0.8443; `gemini-3.5-flash` 1,505 / $8.4479; `whisper-1` 226 / $2.3457.

Note the shape: essentially every company-app DeepSeek call rides `deepseek-v4-flash`, i.e. the retired name. It is being served by the current model **only because upstream chose to keep the compatibility route alive**.

---

## 3. Classification evidence — the two facts that matter

### 3.1 DSH is on the current model

`[cmd] …/dsh/lib/bin.js --profile web --dump-config | grep 'model:'` on `secratary-cloud` →
```
- id: agent-default-model
    provider: deepseek-official
    model: deepseek-flash
```
`[file] settings/base.yaml:58-60` (2026-10-05), `zabz-tech:~/.dsh/settings.yaml.imported:7-9` (2026-10-19T22:17:10Z), `secratary-cloud:/root/.dsh/settings.yaml.imported:7-9` (2026-10-15T14:16:37Z) all agree.

`deepseek-flash` is the literal id of V4.1-Flash-1017 per the provider's own pricing table. DSH resolves it directly against `api.deepseek.com`, so DSH sessions are **current**.

### 3.2 The company gateway is not — and it fails *silently*

The gateway's catalog is built from `smart_router._CAPABILITY_DB`, which has no `deepseek-flash` entry. What happens when a client asks for it was measured, not assumed:

```
[cmd] POST http://127.0.0.1:8002/v1/chat/completions  {"model":"deepseek-flash", …}
      REQ=deepseek-flash
        served_model= deepseek/deepseek-v4-pro | cost_model= deepseek-v4-pro | err= None
[cmd] POST … {"model":"deepseek-v4.1-flash", …}
      REQ=deepseek-v4.1-flash
        served_model= deepseek/deepseek-v4-pro | cost_model= deepseek-v4-pro | err= None
[cmd] POST … {"model":"deepseek/deepseek-v4-flash", …}
      REQ=deepseek/deepseek-v4-flash
        served_model= deepseek/deepseek-v4-flash | cost_model= deepseek-v4-flash | err= None
```

**HTTP 200, no error, and a different model than the one requested.** The newest id (`deepseek-flash`) is answered by **`deepseek/deepseek-v4-pro`** — the 2026-08-13 generation. This is the single most dangerous finding here: the "obvious fix" (change a config from `deepseek-v4-flash` to `deepseek-flash`) would silently make the company app *older and more expensive*, while reporting success.

A second, separate request for the bare alias `deepseek-v4-pro` failed outright:
`err= No reachable upstream for deepinfra/deepseek-ai/DeepSeek-V4-Pro-0813 (provider=deepinfra)` — i.e. the catalogue advertises a lane whose upstream was not reachable at that moment.

A later pair of probes (`secretary-fast`, `deepseek/deepseek-v4-pro`) returned **no HTTP response within 45 s** (`HTTP=000`) while `/health` and `/v1/models` both returned `200` at the same time. That is recorded as an observed state at 22:2xZ, not as a model verdict.

---

## 4. What a user experiences today

**If DSH is serving (the normal case):** nothing is outdated. They get V4.1-Flash-1017 — 1M context, 384K output, vision, thinking-on by default. Its measured gains over the September V4.1 are real: Terminal-Bench 4.0 **42.3 vs 31.2**, DeepSWE v1.1 **77.0 vs 74.2**, ProgramBench **29.1 vs 20.3**, HLE **42.6 vs 36.8** (updates, 2026-10-17 vs 2026-09-10). The 10-17 release also states it reduced task runtime and output length — fewer tokens for the same work.

**If the company app/gateway path serves (CEO chat, delegates, bulk work):** they get V4.1 Flash too, but only through a retired name. Nothing is visibly broken; the risk is that the name disappears without notice and the failure is a 400/404, not a prompt.

**If anyone "upgrades" a gateway config to `deepseek-flash` without fixing the catalogue:** they get **V4-Pro-0813** at HTTP 200 with no warning. Consequences:
- **Cost:** V4-Pro is **4.4× flash** on cache-miss input and **3.3×** on output (off-peak $0.66/$1.98 vs $0.15/$0.60 per 1M; peak $1.32/$3.96 vs $0.30/$1.20 — pricing page). At the current 7-day run-rate ($239 on flash) a full move to pro would cost roughly $800–1,000/week.
- **Capability:** older generation, and **image-blind** — the pricing table marks Vision "Not supported" for pro, and the estate's own measurement found `direct deepseek-v4-pro … IMAGE 0/3` (`DESKTOP-FGV6KMH.yaml:117`). A user attaching a photo would get an empty reply (HTTP 200, no content), which reads as "the app is broken".
- **Latency:** the only like-for-like numbers on file are for the *older flash* on DeepInfra, not for pro: `deepseek-flash direct 747 ms to first token, 160 tok/s` vs `DeepInfra V4-Flash-0731 1693 ms, 24 tok/s` (`LAKEWOOECHSMINI.yaml:42-43`, measured 2026-09-14). They show the direction (a second-hop provider is ~2.3× slower to first token and ~6.7× slower per token), but I did not measure pro's latency and will not claim a number for it.

**If the vision name is ever cleaned up upstream:** the two machines whose default is `deepseek-v4-flash-vision-exp` (`DESKTOP-FGV6KMH`, `LAKEWOOECHSMINI`) lose images first, because the *default* is the retired name, not the current one.

---

## 5. Exact remediation

Marking rule: **SAFE-TO-APPLY-NOW** = a repo/config text edit with no key, no purchase and no service restart (DSH resolves per request; `scripts/autosync.ps1` publishes committed settings). **NEEDS-OWNER** = needs a credential, a purchase, a service reload/restart, or a behaviour change the owner should choose.

1. **SAFE-TO-APPLY-NOW — drop the retired DeepInfra id.** Delete `deepseek-ai/DeepSeek-V4-Flash-0731` from `settings/base.yaml:148` and `settings/machines/ZABZ-YOGA.yaml:14` (also the picker copies at `DESKTOP-FGV6KMH.yaml:155`, `LAKEWOOECHSMINI.yaml:106`). It is the July 31 model; the authority registry itself marks it `retired` with `last_verified_at 2026-10-12T03:47:45Z`.
2. **SAFE-TO-APPLY-NOW — move the two vision defaults to the supported id.** `DESKTOP-FGV6KMH.yaml:79` and `LAKEWOOECHSMINI.yaml:62`: `model: deepseek-v4-flash-vision-exp` → `model: deepseek-flash`. Both providers already declare `defaultInput: [text, image]` (`DESKTOP-FGV6KMH.yaml:122`, `LAKEWOOECHSMINI.yaml:85`) and the estate's own measurement found `direct deepseek-flash … IMAGE 3/3 … "Green"` (`DESKTOP-FGV6KMH.yaml:131`), so this does not cost image support — and it stops the *default* being a name upstream retired on 2026-09-10.
3. **SAFE-TO-APPLY-NOW — demote the retired vision id to a legacy picker entry** (`:141`, `:93`) or delete it. Keep `deepseek-flash` as the vision-capable entry.
4. **NEEDS-OWNER — make the gateway catalogue know the current model.** In `/opt/company/app/services/smart_router.py` `_CAPABILITY_DB`, add `deepseek/deepseek-flash` (`provider: deepseek`, `provider_model_id: deepseek-flash`, `tier: fast`, 1,000,000 ctx, tools, vision) — or better, populate the DeepSeek entries from `GET https://api.deepseek.com/models` at startup instead of a literal table. Requires deploying and restarting `company-api.service`. **Until this lands, no client may name `deepseek-flash` at the gateway** — see 3.2.
5. **NEEDS-OWNER — refuse unknown ids instead of substituting.** The measured behaviour (unknown DeepSeek id → `deepseek/deepseek-v4-pro`, HTTP 200) must become a `400 model_not_found`. This is a behaviour change in the chat-completions resolver, needs deploy + restart. It is the control that makes every other edit here safe.
6. **NEEDS-OWNER — stop pinning concrete ids in the company env.** `/opt/company/.env:517` `AI_GATEWAY_DELEGATE_MODEL=deepseek/deepseek-v4-flash` → a route alias (`secretary-fast`); `/opt/company/.env:17` `CEO_MODELS_JSON` → route aliases, or delete it so `model_resolution.resolve_model_detail("ceo")` decides. Both need a `company-api` reload to take effect.
7. **NEEDS-OWNER — remove the hardcoded literals in application code.** `app/assistant_chat.py:1465,1496,1925,4295` and `app/config.py:171-174,176-180` hardcode `deepseek-v4-flash`. Replace `_get_ceo_models` / `_select_ceo_model` fallbacks with `app/services/model_resolution.resolve_model_detail("ceo")`, which already implements the standing rule (route aliases first, `ZABZ_MODEL_<TIER>` comma-separated env chain, mandatory catalogue validation, single-flight cache, fail-soft, publish what served). This is exactly the "literal model id is a time bomb" the module's own docstring names.
8. **NEEDS-OWNER — stop advertising `secretary-genius`.** It is in the catalogue with `default_selectable: true` at 2026-10-19T22:07Z, while the standing rule says never (measured 502 on 2026-09-15) and `model_resolution._NEVER_ALIASES` already blacklists it. Either drop the route policy from `_META_MODELS` or set `default_selectable: false`. Code + restart.
9. **NEEDS-OWNER — teach `model_liveness` the difference between "accepted" and "current".** The catalog marks `deepseek/deepseek-v4-flash` `is_verified: true` and `lifecycle_state: promoted`; the retired entries by contrast carry a `verification` block with `served_model: null` and `retired_reason`, while this one carries no verification block at all. Nothing in the row can say that the *name* is retired. Add `lifecycle_state`/`successor_model_id` from the provider docs or a provider-version probe, and add the V4.1 row the registry lacks (newest DeepSeek row is 2026-08-23).
10. **SAFE-TO-APPLY-NOW — record the alias policy.** State in `docs/` (and in the comments at `base.yaml:38-49`) that `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are compatibility names with no published sunset, must never become the canonical id, and that `deepseek-flash` is the only supported name for V4.1 Flash.
11. **SAFE-TO-APPLY-NOW — keep DSH as it is.** `agent-default-model.model: deepseek-flash` on base and both machines is correct; do **not** "fix" it to `deepseek-v4-flash`. If the estate wants the runtime-catalogue rule applied to DSH too, that requires pointing DSH at the company gateway and selecting `secretary-auto` — that is a **NEEDS-OWNER** change and it is blocked on step 4; do not do it before the catalogue lists the id.

**What would make the newest model serve without hardcoding a name:** steps 4 + 5 + 7 together. The resolver already exists (`model_resolution.py`) — the work is to make the catalogue truthful (4), make an unlisted id an error rather than a silent substitution (5), and move the remaining call sites onto the resolver (6, 7). Route aliases `secretary-auto` / `secretary-fast` / `secretary-smart` are the only model names that should appear in an operational config; `secretary-genius` must not appear at all.

---

## 6. What I could not verify

1. **Which upstream build actually served the 13,878 `deepseek-v4-flash` calls.** The provider documents that the name is routed to V4.1-Flash-1017, but the gateway's response carries only `model: deepseek/deepseek-v4-flash` and a `system_fingerprint` hash — no version field — and `model_usage.served_by` is empty on every sampled row. The routing is documented, not independently measured.
2. **DeepInfra's current catalogue.** I did not call `https://api.deepinfra.com/v1/openai/models` (would need the DeepInfra key; I did not use provider credentials). So `deepseek-ai/DeepSeek-V4.1-Flash` is **UNKNOWN** as to whether it is the `-1017` build, and I cannot say whether DeepInfra still serves `DeepSeek-V4-Flash-0731`.
3. **Whether `~/.dsh/settings.yaml.imported` is loaded by design.** Both hosts have no `settings.yaml` but do have `.imported`, and `dsh --profile web --dump-config` on the authority prints exactly the `.imported` values — strong evidence it is the loaded file, but I found no documentation for the import mechanism. If it is *not* the loader, both hosts' effective model is the engine default, which I did not identify.
4. **`secretary-genius`'s current status.** Not re-tested — the standing rule forbids using it, and re-measuring would mean calling it. The catalogue still advertises it; I did not confirm whether it still 502s.
5. **`deepseek/deepseek-v4-pro` and the `secretary-*` aliases at the moment of the second probe.** Both returned no HTTP response in 45 s while `/health` and `/v1/models` returned 200. I did not chase whether that was a transient provider stall, a circuit breaker, or load — so I cannot say whether those lanes are healthy right now.
6. **The gateway's own served-model field.** `/v1/models` has no top-level `served_model`; only retired entries carry `verification.served_model` (and those are `null`). There is no per-call "what version actually answered" field anywhere in the catalog.
7. **`MODEL_PROVIDER_KEYS_JSON`** in `/opt/company/.env:34` was deliberately not read (credential-shaped). I read variable *names* only, plus the non-secret model values at lines 14-17 and 517.
8. **Windows engine effective config.** I read `zabz-tech:~/.dsh/settings.yaml.imported`, but did not run `dsh --dump-config` for the Windows engine — the local binary path/derivation was not established. The authority's effective config was dumped; the local one is file-level only.
9. **No 30-day or per-agent cost trend** — only the 7-day `model_usage` aggregate above.
10. **No write was made to `model_registry`, `model_aliases`, or `model_usage`** (read-only posture), so every remediation that touches them is marked NEEDS-OWNER even where the edit is mechanically trivial.

---

## 7. Reproduce

```bash
# upstream
#   https://api-docs.deepseek.com/updates/         (Date: 2026-10-17, 2026-09-10, 2026-08-13)
#   https://api-docs.deepseek.com/quick_start/pricing  (MODEL VERSION column)

# gateway catalogue
ssh secratary-cloud "curl -s -m 15 http://127.0.0.1:8002/v1/models"

# effective DSH settings
ssh secratary-cloud "cd /root && DSH_HOME=/root/.dsh node /opt/dsh-phone/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --dump-config | grep -E 'agent-default-model|model:'"

# registry / usage
ssh secratary-cloud "sqlite3 /root/authority.db '.schema model_registry'"
ssh secratary-cloud "sqlite3 -header -column /root/authority.db 'select id,provider,model,created_at from model_usage order by id desc limit 5'"

# the silent substitution (key read from .env, never echoed)
ssh secratary-cloud 'K=$(sed -n "s/^AI_GATEWAY_API_KEY=//p" /opt/company/.env | head -1); \
  curl -s -X POST http://127.0.0.1:8002/v1/chat/completions \
    -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
    -d "{\"model\":\"deepseek-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}],\"max_tokens\":4}"'
```
