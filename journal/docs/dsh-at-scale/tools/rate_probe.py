"""Settle the REAL per-token price empirically.

One tiny non-streaming chat request with a deliberately cold, unique prefix
(no cache hits possible), then read the account balance before and after.
balance_delta / measured_tokens = the true delivered price.

The request is trivially small (a few hundred tokens). Nothing is sent anywhere
except api.deepseek.com; no data from the owner's business is included.
"""
import json, os, re, time, urllib.request

t = open(os.path.expanduser(r"~/.dsh/.credentials.yaml"), encoding="utf-8").read()
KEY = re.search(r"DEEPSEEK_API_KEY\s*:\s*(\S+)", t).group(1).strip().strip("\"'")
H = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}


def get(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=H), timeout=30))


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=H)
    return json.load(urllib.request.urlopen(req, timeout=120))


bal = lambda: float(get("https://api.deepseek.com/user/balance")
                    ["balance_infos"][0]["total_balance"])

b0 = bal()
print(f"balance before            : ${b0:.10f}")

# A unique, cold prompt: nothing like it exists in any cache.
nonce = f"{time.time_ns()}-cold-probe"
messages = [
    {"role": "system", "content": "Reply with exactly one word."},
    {"role": "user", "content": f"Nonce {nonce}. Reply with the single word: ok"},
]
body = {"model": "deepseek-flash", "messages": messages,
        "max_tokens": 8, "stream": False}
r = post("https://api.deepseek.com/v1/chat/completions", body)
u = r.get("usage", {})
print("usage returned by the API :")
print(json.dumps(u, indent=2))

time.sleep(3)
b1 = bal()
print(f"balance after             : ${b1:.10f}")
print(f"balance delta             : ${b0 - b1:.10f}")

pt = u.get("prompt_tokens", 0)
completion = u.get("completion_tokens", 0)
total = u.get("total_tokens", pt + completion)
hit = u.get("prompt_cache_hit_tokens", 0)
miss = u.get("prompt_cache_miss_tokens", pt - hit)
print(f"\nprompt_tokens={pt}  (hit={hit}, miss={miss})  completion={completion}")

delta = b0 - b1
if delta > 0 and total:
    print(f"\nREALISED blended rate     : ${delta/total*1e6:.4f} per 1M total tokens")
if delta > 0 and miss:
    print(f"REALISED rate on miss tok : ${delta/miss*1e6:.4f} per 1M  "
          f"(if output were free)")
    print(f"  at the documented $0.15/M miss + $0.60/M out, this call should "
          f"have cost ${(miss*0.15+completion*0.60)/1e6:.10f}")
    print(f"  observed / documented   : {delta/((miss*0.15+completion*0.60)/1e6):.2f}x")
if delta == 0:
    print("\nbalance unchanged — the balance API is not a per-request ledger "
          "(it may be batched or rounded to cents).")
