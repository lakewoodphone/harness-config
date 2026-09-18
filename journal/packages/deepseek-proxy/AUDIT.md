# DeepSeek direct for a filtered machine — audit and implementation

**Question:** will a proxy or Cloudflare Worker work robustly, and is it worth it?
**Answer:** yes, and it is already deployed and verified. Her harness still needs one config edit on her
machine, which requires the machine to be online.

Measured **2026-09-14**. Every number here is from a run, not an estimate.

---

## 1. Is it worth doing? Yes — measured, not assumed

The owner said DeepSeek direct felt faster. He was right, and it is a different serving tier:

| Route (same prompt, `max_tokens=200`, streaming, 3 runs each) | TTFT | total | tok/s |
|---|---|---|---|
| **`deepseek-flash` direct** | **747 ms** | **1,895 ms** | **160** |
| `deepseek-v4-pro` direct | 737 ms | 2,563 ms | 85 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` (DeepInfra) | 1,693 ms | 8,126 ms | 24 |
| `deepseek-ai/DeepSeek-V4.1-Flash` (DeepInfra) | 1,939 ms | 8,457 ms | 18 |

**2.3× slower to first token, ~6.7× slower per token** on DeepInfra. That is the difference between an
assistant that feels quick and one that does not.

## 2. Why direct doesn't work from her box

Techloq blocks `api.deepseek.com` **by URL category**, and answers with an HTML page that carries a
**success status** (302 via `node:https`), so the harness cannot even tell it was blocked. This is not a
port or DNS problem — TCP 443 is open to everything.

## 3. Worker vs machine-hosted proxy

| | Cloudflare Worker | Proxy on one of the owner's machines |
|---|---|---|
| Depends on a host being up | **No** | Yes |
| Depends on a service staying alive | **No** (nothing to run or patch) | Yes |
| Streaming support | Native, verified below | Native |
| Route to DeepSeek | Cloudflare edge → DeepSeek | via the tunnel, then out |
| Failure surface | Cloudflare + this zone | machine + service + tunnel + Cloudflare |
| Maintenance | none | patching, monitoring |

**Chosen: the Worker.** The deciding factor is the absence of a host. Today already demonstrated the cost
of a fragile single route — her laptop's tunnel dropped twice in one afternoon **while the machine itself
was up the whole time** (uptime 726 min at the second check). Adding a dependency on one of the owner's
desktops would recreate exactly that failure mode, on purpose.

## 4. The blocking problem, and why a custom hostname solves it

Techloq intercepts TLS for **every** destination (issuer `CN=env1.dc3.us.techloq.com`), so it sees the SNI
hostname of whatever the harness calls. The fix is therefore not to hide the traffic but to **call a
hostname the filter already allows**.

`ds.abletelsolutions.com` was chosen because `*.abletelsolutions.com` is **already proven reachable from
her machine** — she reaches `yocheved-cmd.abletelsolutions.com` on that zone. A `*.workers.dev` hostname
would carry an unproven, different category. (That account also has no `workers.dev` subdomain registered,
so a custom hostname was the only option without another dashboard step.)

## 5. Robustness — measured

**Deployed and live:** `https://ds.abletelsolutions.com`

| Check | Result |
|---|---|
| `/__health` | **200** `{"ok":true,"upstream":"https://api.deepseek.com"}` |
| No token | **401** — refused |
| An unverifiable token | **401** — refused here, not forwarded |
| Valid key → `/v1/models` | **200**, real model list through the proxy |
| Streaming | **122–201 SSE events per call**, `[DONE]` intact every time |
| Steady-state stream smoothness | **six sequential runs, ZERO inter-chunk gaps over 300 ms** (maxGap 72–294 ms, direct baseline 175 ms) |
| Overhead | **none measurable** — 4-run comparison: proxy 429 ms vs direct 662 ms TTFT (noise); 154 vs 138 tok/s |

The one **1000 ms gap** seen in the first verification run was **cold start on run 1**, not buffering.
That distinction matters — buffering would eat the speed this exists to restore — so
`scripts/gap-analysis.mjs` exists specifically to separate the two, and it shows runs 2+ streaming cleanly.

**Security posture:** the Worker holds **no key**. The caller sends its own bearer token exactly as it
would to DeepSeek and the Worker forwards it, so the key's blast radius is **identical** to calling DeepSeek
directly, and rotating it needs no redeploy. An unknown token is rejected at the Worker (verified against
`GET /v1/models`, cached 10 minutes) so the hostname is not an open relay.

## 6. What it cost to build, and what is still needed

Deployed with the `CF_ZERO_TRUST_TOKEN` already in the repo — **no new credential from the owner**. Two
credentials split the work: `CF_API_TOKEN` can write DNS, `CF_ZERO_TRUST_TOKEN` can write Workers
(`Workers Scripts:Edit`). Neither can edit zone Workers **routes** (403), which is why the Worker is
published as a **custom domain** instead — that path needs no route permission.

**Status: all four steps are DONE — see 6b below.**

---


## 6b. ALL OF THE ABOVE IS DONE — deployed and proven end to end (2026-09-14)

Her harness now runs on the proxy route and **answered a real turn on it**: `PROXY_ROUTE_OK` in **5
seconds**, exit 0, via `--profile headless` with
`agent-default-model: { provider: deepseek-proxy, model: deepseek-flash }`.

**The block and the workaround, from her own machine in one run:**

| From her laptop, behind the filter | Result |
|---|---|
| Proxy `/__health` | **200** — reachable |
| Proxy with a valid key | **200**, real model list |
| Proxy with no token | **401** — refused |
| **Direct `api.deepseek.com`** | **200 with `text/html`** ← the block page, confirming the diagnosis |

**Latency measured from her box** (same prompt, `max_tokens=150`, streaming):

| Route | TTFT | total | tok/s |
|---|---|---|---|
| **PROXY `deepseek-flash`** | **465 ms** | **1,406 ms** | **159** |
| DeepInfra `V4-Flash-0731` | 382 ms | 2,759 ms | 57 |
| PROXY `deepseek-v4-pro` | 698 ms | 2,642 ms | 77 |

**~2.8× the throughput and half the total wait.** DeepInfra's TTFT is marginally better on this run (382
vs 465 ms) — that is the part she waits for before text starts — but it then takes twice as long to
finish, which is what makes a reply feel slow.

### Deployment trap worth remembering

`sync.ps1` reported **`settings.yaml: already up to date`** right after the machine file was updated in
git, and her live settings still said `deepinfra`. Cause: `sync.ps1` merges the machine settings file **as
it exists on that machine**, and the updated file had only been committed — never pushed to her box. The
change looked applied and was not.

*Rule:* for a machine that cannot pull `harness-config` itself, a committed change is not a delivered
change. Push the file, run sync, then **read the live value back** — the read-back is the only evidence.

## 7. Failure modes, and the fallback

| If this breaks | What happens | Fix |
|---|---|---|
| Worker or zone breaks | her calls error | one line: `agent-default-model.provider: deepinfra` |
| DeepSeek key rotated | calls 401 at the Worker | update `.credentials.yaml` on her box; no redeploy |
| DeepSeek itself down | calls error | switch to `deepinfra` (independent provider) |

The `deepinfra` route is **retained and selectable** for exactly this reason, so the fallback needs no
deployment — only a settings edit, and the adapter re-reads its route per request.
