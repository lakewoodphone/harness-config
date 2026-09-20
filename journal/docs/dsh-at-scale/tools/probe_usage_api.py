"""Read-only probe for a usage/billing endpoint on api.deepseek.com.

Only GET; nothing is created, nothing is sent anywhere else.
"""
import json, os, re, urllib.request, urllib.error

t = open(os.path.expanduser(r"~/.dsh/.credentials.yaml"), encoding="utf-8").read()
key = re.search(r"DEEPSEEK_API_KEY\s*:\s*(\S+)", t).group(1).strip().strip("\"'")

PATHS = [
    "/user/balance",
    "/user/usage",
    "/user/billing",
    "/dashboard/billing/usage?start_date=2026-09-14&end_date=2026-09-16",
    "/dashboard/billing/subscription",
    "/v1/usage",
    "/v1/dashboard/billing/usage",
    "/usage",
]
for p in PATHS:
    url = "https://api.deepseek.com" + p
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(2000).decode()
            print(f"HTTP 200  {p}\n    {body[:800]}")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}  {p}  {e.read()[:200].decode(errors='replace')}")
    except Exception as e:
        print(f"ERR   {p}  {type(e).__name__} {e}")
