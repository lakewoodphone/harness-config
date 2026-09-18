# DeepSeek pass-through proxy (Cloudflare Worker)

Terminates TLS on an allowed hostname and makes the `api.deepseek.com` call from Cloudflare's edge, so a
machine behind a URL-category filter can still reach DeepSeek's own (much faster) serving tier.

## Why, measured

From a neutral network, same prompt, `max_tokens=200`, streaming — three runs each:

| Route | TTFT | total | tok/s |
|---|---|---|---|
| **`deepseek-flash` (direct)** | **747 ms** | **1,895 ms** | **160** |
| `deepseek-v4-pro` (direct) | 737 ms | 2,563 ms | 85 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` (DeepInfra) | 1,693 ms | 8,126 ms | 24 |
| `deepseek-ai/DeepSeek-V4.1-Flash` (DeepInfra) | 1,939 ms | 8,457 ms | 18 |

Direct is **2.3× faster to first token and ~6.7× faster per token.** That is a different serving tier, not
noise, and it is why this proxy exists rather than just living with DeepInfra.

## Why a Worker and not a machine

A proxy hosted on one of the owner's machines inherits that machine's availability, and today already
demonstrated what a single fragile route into a box costs (his laptop dropped off twice in one afternoon
while the machine itself was up the whole time). A Worker has **no host machine, no service to keep alive,
no disk, and nothing to patch** — which is the property that matters most for a machine nobody is watching.

## Why a custom hostname and not `*.workers.dev`

The filter decides by URL category. `*.abletelsolutions.com` is **already proven allowed from her machine**
— it reaches `yocheved-cmd.abletelsolutions.com` and the Cloudflare Access login page on that zone. An
arbitrary `*.workers.dev` hostname carries a different, unproven category. So the proxy is published on the
zone that is known to work.

Also: this account has **no `workers.dev` subdomain registered** (the API answers 404), so a custom hostname
is not merely preferable here, it is the only option without another dashboard step.

## Key handling

The Worker stores **no key**. The caller sends its own `Authorization: Bearer …` exactly as it would to
DeepSeek, and the Worker forwards it. Consequences worth being explicit about:

* the key's blast radius is identical to calling DeepSeek directly — this neither widens nor narrows it;
* rotating the key needs no redeploy;
* an unknown token is **rejected here** (verified against `GET /v1/models` upstream, cached 10 minutes) so
  the hostname is not an open relay to DeepSeek for anything that does not already hold a valid key.

## Deployment

```powershell
# deploy the script
curl.exe -X PUT "https://api.cloudflare.com/client/v4/accounts/$acct/workers/scripts/deepseek-proxy" `
  -H "Authorization: Bearer $CF_ZERO_TRUST_TOKEN" `
  -F "metadata=@metadata.json;type=application/json" `
  -F "worker.mjs=@worker.mjs;type=application/javascript+module"

# publish it on the zone (DNS record is a placeholder; the route intercepts it)
#   ds.abletelsolutions.com  A  192.0.2.1  proxied
curl.exe -X POST "https://api.cloudflare.com/client/v4/zones/$zone/workers/routes" `
  -H "Authorization: Bearer $CF_ZERO_TRUST_TOKEN" -H "Content-Type: application/json" `
  --data '{"pattern":"ds.abletelsolutions.com/*","script":"deepseek-proxy"}'
```

Then on the machine:

```yaml
llm-pi-ai:
  providers:
    deepseek-proxy:
      apiKeyEnv: DEEPSEEK_API_KEY
      api: openai-completions
      baseURL: https://ds.abletelsolutions.com/v1
      models:
        - id: deepseek-flash
        - id: deepseek-v4-pro
```

## Verify

```powershell
curl.exe -s https://ds.abletelsolutions.com/__health
curl.exe -s https://ds.abletelsolutions.com/v1/models -H "Authorization: Bearer $key"
node scripts/verify-proxy.mjs          # streaming fidelity + latency, side by side with direct
```
