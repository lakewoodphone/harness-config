set -u
python3 - <<'PY'
import json, os, re, time, urllib.request, urllib.error

env = {}
for line in open("/home/zabz/personal-secretary-mvp/.env", errors="ignore"):
    m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"').strip("'")

def call(label, fn):
    t = time.time()
    try:
        code, note = fn()
    except urllib.error.HTTPError as e:
        code, note = e.code, (e.read().decode("utf-8", "replace")[:90])
    except Exception as e:
        code, note = "ERR", "%s %s" % (type(e).__name__, str(e)[:70])
    ms = int((time.time() - t) * 1000)
    ok = "WORKS" if str(code).startswith("2") else "FAILS"
    print("%-12s %-6s http %-5s %5dms  %s" % (label, ok, code, ms, note.replace("\n", " ")[:90]))

def get(url, headers=None):
    r = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(r, timeout=25) as resp:
        return resp.status, "bytes=%d" % len(resp.read())

def post(url, headers, body):
    r = urllib.request.Request(url, method="POST", headers=headers,
                              data=json.dumps(body).encode())
    with urllib.request.urlopen(r, timeout=40) as resp:
        b = resp.read()
        return resp.status, "bytes=%d" % len(b)

print("RUNTIME PROBE - does the credential actually work, not does its name appear anywhere")
print("-" * 100)

if env.get("TAVILY_API_KEY"):
    call("tavily", lambda: get("https://api.tavily.com/usage",
                               {"Authorization": "Bearer " + env["TAVILY_API_KEY"]}))
if env.get("EXA_API_KEY"):
    call("exa", lambda: post("https://api.exa.ai/search",
                             {"x-api-key": env["EXA_API_KEY"], "Content-Type": "application/json"},
                             {"query": "test", "numResults": 1}))
if env.get("SPIDER_API_KEY"):
    call("spider", lambda: post("https://api.spider.cloud/scrape",
                                {"Authorization": "Bearer " + env["SPIDER_API_KEY"],
                                 "Content-Type": "application/json"},
                                {"url": "https://example.com", "return_format": "markdown"}))
if env.get("FIRECRAWL_API_KEY"):
    call("firecrawl", lambda: get("https://api.firecrawl.dev/v1/team/credit-usage",
                                  {"Authorization": "Bearer " + env["FIRECRAWL_API_KEY"]}))
if env.get("JINA_API_KEY"):
    call("jina", lambda: get("https://r.jina.ai/https://example.com",
                             {"Authorization": "Bearer " + env["JINA_API_KEY"]}))
if env.get("DEEPSEEK_API_KEY"):
    call("deepseek", lambda: get("https://api.deepseek.com/user/balance",
                                 {"Authorization": "Bearer " + env["DEEPSEEK_API_KEY"]}))
if env.get("BRAVE_SEARCH_API_KEY"):
    call("brave", lambda: get("https://api.search.brave.com/res/v1/web/search?q=test",
                              {"X-Subscription-Token": env["BRAVE_SEARCH_API_KEY"]}))
if env.get("PERPLEXITY_API_KEY"):
    call("perplexity", lambda: post("https://api.perplexity.ai/chat/completions",
                                    {"Authorization": "Bearer " + env["PERPLEXITY_API_KEY"],
                                     "Content-Type": "application/json"},
                                    {"model": "sonar", "messages": [{"role": "user", "content": "hi"}],
                                     "max_tokens": 5}))

print("-" * 100)
print("NOT PROBED here, and deliberately not called failed: providers whose endpoint I could not")
print("establish from the repo or public docs. A probe that guesses an endpoint and reports FAILS")
print("is the same defect as the name search that reported a live paid key as unused.")
PY
