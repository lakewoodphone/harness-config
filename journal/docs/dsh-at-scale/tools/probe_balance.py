"""Read-only: account balance. Establishes how much credit remains, not the $54 itself."""
import json, os, re, urllib.request

t = open(os.path.expanduser(r"~/.dsh/.credentials.yaml"), encoding="utf-8").read()
key = re.search(r"DEEPSEEK_API_KEY\s*:\s*(\S+)", t).group(1).strip().strip("\"'")
for url in ("https://api.deepseek.com/user/balance",):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("GET", url, "-> HTTP", r.status)
            print(json.dumps(json.load(r), indent=2)[:2000])
    except Exception as e:
        print("GET", url, "->", type(e).__name__, e)
        try:
            print(e.read().decode()[:800])
        except Exception:
            pass
