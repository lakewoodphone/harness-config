"""Read-only: ask the provider's own catalog which model ids exist. Prints no secret."""
import json, os, re, urllib.request

p = os.path.expanduser(r"~/.dsh/.credentials.yaml")
t = open(p, encoding="utf-8").read()
m = re.search(r"DEEPSEEK_API_KEY\s*:\s*(\S+)", t)
key = m.group(1).strip().strip("\"'") if m else None
print("DEEPSEEK_API_KEY recovered from ~/.dsh/.credentials.yaml:",
      bool(key), "(length %d, value not printed)" % (len(key) if key else 0))
if not key:
    raise SystemExit("no key")

for url in ("https://api.deepseek.com/v1/models",
            "https://api.deepseek.com/models"):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        print("\nGET", url, "-> HTTP", 200)
        print(json.dumps(body, indent=2)[:4000])
    except Exception as e:
        print("\nGET", url, "-> ", type(e).__name__, e)
        try:
            print(e.read().decode()[:800])
        except Exception:
            pass
