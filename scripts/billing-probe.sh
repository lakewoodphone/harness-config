set -u
python3 - <<'PY'
import json, re, urllib.request, urllib.error

env = {}
for line in open("/home/zabz/personal-secretary-mvp/.env", errors="ignore"):
    m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"').strip("'")

def probe(label, url, headers, method="GET", body=None):
    try:
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body else None)
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = r.read().decode("utf-8", "replace")
        print("%-12s %-5s %s" % (label, r.status, txt[:190].replace("\n", " ")))
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")[:150].replace("\n", " ")
        print("%-12s %-5s %s" % (label, e.code, b))
    except Exception as e:
        print("%-12s %-5s %s" % (label, "ERR", "%s %s" % (type(e).__name__, str(e)[:80])))

print("BILLING AND PLAN, from each provider OWN api - more authoritative than the bank feed,")
print("which shows what was charged but not what is armed")
print("-" * 104)

t = env.get("TAVILY_API_KEY")
if t:
    probe("tavily", "https://api.tavily.com/usage", {"Authorization": "Bearer " + t})

f = env.get("FIRECRAWL_API_KEY")
if f:
    probe("firecrawl", "https://api.firecrawl.dev/v1/team/credit-usage", {"Authorization": "Bearer " + f})

s = env.get("SERPAPI_API_KEY")
if s:
    probe("serpapi", "https://serpapi.com/account?api_key=" + s, {})

e = env.get("EXA_API_KEY")
if e:
    for path in ("/usage", "/v1/usage", "/team/usage"):
        probe("exa" + path, "https://api.exa.ai" + path, {"x-api-key": e})

b = env.get("BRAVE_SEARCH_API_KEY")
if b:
    probe("brave", "https://api.search.brave.com/res/v1/web/search?q=test&count=1",
          {"X-Subscription-Token": b})

sp = env.get("SPIDER_API_KEY")
if sp:
    for path in ("/data/credits", "/credits", "/data/balance", "/usage"):
        probe("spider" + path, "https://api.spider.cloud" + path, {"Authorization": "Bearer " + sp})

j = env.get("JINA_API_KEY")
if j:
    probe("jina", "https://api.jina.ai/v1/usage", {"Authorization": "Bearer " + j})

p = env.get("PERPLEXITY_API_KEY")
if p:
    probe("perplexity", "https://api.perplexity.ai/usage", {"Authorization": "Bearer " + p})

print("-" * 104)
print("A 404 or 401 above means the endpoint does not exist or needs a different credential, NOT that")
print("nothing is billed. Anything not resolvable here stays unknown rather than being called free.")
PY
