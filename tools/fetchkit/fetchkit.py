#!/usr/bin/env python3
"""fetchkit - one fetch/search/browse command with the estate's paid keys, on every host.

WHY THIS EXISTS
---------------
The estate already pays for Firecrawl, Jina, Brave Search and SerpAPI. Those keys sit in
`personal-secretary-mvp/.env`, and they were reachable ONLY through MCP servers that are declared

    disabled: !!js process.platform !== 'win32'

so every Linux mesh node - the authority, the office boxes, the mini - had no search and no browse at
all, and a tool running outside an agent session could not use them on any host. The capability was
bought and then locked to one platform.

This is the CLI that removes both gates. It reads the same `.env`, needs no MCP, runs on Windows and
Linux, and every provider is optional: a missing key is reported as missing, never silently skipped.

DESIGN RULES, all learned the hard way
--------------------------------------
1. A provider that is not configured says so. It never returns an empty success.
2. Every answer names the provider that produced it, and `doctor` shows what each host can actually do.
3. Secrets are read from the environment or from a .env file. They are NEVER written into this repo,
   never printed, and never echoed in a reason string.
4. Structured beats scraped: where a provider offers a typed capability (Firecrawl Alexandria:
   amazon-com, walmart-com, newegg-com, dell-com), prefer it over fetching HTML and guessing.

USAGE
    fetchkit doctor                                   # what can THIS host do?
    fetchkit get <url> [--backend auto|http|jina|firecrawl|playwright]
    fetchkit search "<query>" [--backend brave|serpapi|jina] [--count 10]
    fetchkit alexandria <provider> <capability> --options '{"query":"..."}'
    fetchkit alexandria --catalogue <url>             # which capabilities exist for a site

Keys it looks for (any subset; absent = that provider is off):
    FIRECRAWL_API_KEY  JINA_API_KEY  BRAVE_SEARCH_API_KEY  SERPAPI_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 30

# Candidate .env locations, in priority order. The first that exists and holds a key wins per key.
ENV_CANDIDATES = [
    os.path.expanduser("~/code/personal-secretary-mvp/.env"),
    os.path.expanduser("~/personal-secretary-mvp/.env"),
    "/opt/company/.env",
    os.path.expanduser("~/.fetchkit.env"),
]

KEY_NAMES = ("FIRECRAWL_API_KEY", "JINA_API_KEY", "BRAVE_SEARCH_API_KEY", "SERPAPI_API_KEY",
             "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")

BLOCK_MARKERS = ("captcha", "are you a robot", "unusual traffic", "access denied",
                 "verify you are human", "request blocked", "you have been blocked")


# ------------------------------------------------------------------ keys

def load_keys() -> dict:
    """Environment first, then the first .env that has the key. Returns {name: value}. Never printed."""
    found = {}
    for name in KEY_NAMES:
        v = os.environ.get(name)
        if v:
            found[name] = v.strip()
    missing = [n for n in KEY_NAMES if n not in found]
    if not missing:
        return found
    for path in ENV_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k in missing:
                        v = v.strip().strip('"').strip("'")
                        if v:
                            found[k] = v
        except OSError:
            continue
        missing = [n for n in KEY_NAMES if n not in found]
        if not missing:
            break
    return found


def _src(name, keys) -> str:
    if os.environ.get(name):
        return "environment"
    return ".env" if name in keys else "MISSING"


# ------------------------------------------------------------------ providers

def p_http(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    low = r.text.lower()
    if r.status_code in (403, 429, 503):
        return {"ok": False, "reason": f"http {r.status_code}"}
    for m in BLOCK_MARKERS:
        if m in low:
            return {"ok": False, "reason": f"bot-wall: {m}"}
    if len(low) < 1200:
        return {"ok": False, "reason": f"body only {len(low)} chars"}
    return {"ok": True, "text": r.text, "meta": {"status": r.status_code}}


def p_jina(url, keys):
    v = keys.get("JINA_API_KEY")
    h = {"User-Agent": UA}
    if v:
        h["Authorization"] = f"Bearer {v}"
    try:
        r = requests.get("https://r.jina.ai/" + url, headers=h, timeout=90)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200 or len(r.text) < 400:
        return {"ok": False, "reason": f"http {r.status_code}, {len(r.text)} chars"}
    return {"ok": True, "text": r.text, "meta": {"status": r.status_code}}


def p_firecrawl(url, keys):
    v = keys.get("FIRECRAWL_API_KEY")
    if not v:
        return {"ok": False, "reason": "FIRECRAWL_API_KEY not set"}
    try:
        r = requests.post("https://api.firecrawl.dev/v1/scrape",
                          headers={"Authorization": f"Bearer {v}", "Content-Type": "application/json"},
                          json={"url": url, "formats": ["markdown"], "onlyMainContent": True, "maxAge": 0},
                          timeout=120)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "reason": f"http {r.status_code}: {r.text[:120]}"}
    text = (r.json().get("data") or {}).get("markdown") or ""
    if len(text) < 700:
        return {"ok": False, "reason": f"only {len(text)} chars"}
    return {"ok": True, "text": text, "meta": {"status": 200}}


def p_playwright(url):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"playwright unavailable: {e}"}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            ctx = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3000)
            text = pg.inner_text("body")
            html = pg.content()
            b.close()
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if len(text.strip()) < 700:
        return {"ok": False, "reason": f"rendered only {len(text.strip())} chars"}
    return {"ok": True, "text": text, "meta": {"html_chars": len(html)}}


def p_brave(query, keys, count):
    v = keys.get("BRAVE_SEARCH_API_KEY")
    if not v:
        return {"ok": False, "reason": "BRAVE_SEARCH_API_KEY not set"}
    try:
        r = requests.get("https://api.search.brave.com/res/v1/web/search",
                         headers={"X-Subscription-Token": v, "Accept": "application/json",
                                  "User-Agent": UA},
                         params={"q": query, "count": count}, timeout=30)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "reason": f"http {r.status_code}: {r.text[:120]}"}
    web = ((r.json().get("web") or {}).get("results") or [])
    rows = [{"title": w.get("title"), "url": w.get("url"), "description": w.get("description")}
            for w in web[:count]]
    return {"ok": True, "rows": rows, "meta": {"provider": "brave"}}


def p_serpapi(query, keys, count):
    v = keys.get("SERPAPI_API_KEY")
    if not v:
        return {"ok": False, "reason": "SERPAPI_API_KEY not set"}
    try:
        r = requests.get("https://serpapi.com/search.json",
                         params={"q": query, "num": count, "api_key": v, "engine": "google"},
                         timeout=45)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "reason": f"http {r.status_code}: {r.text[:120]}"}
    rows = [{"title": o.get("title"), "url": o.get("link"), "description": o.get("snippet")}
            for o in (r.json().get("organic_results") or [])[:count]]
    return {"ok": True, "rows": rows, "meta": {"provider": "serpapi"}}


def p_jina_search(query, keys, count):
    v = keys.get("JINA_API_KEY")
    if not v:
        return {"ok": False, "reason": "JINA_API_KEY not set (s.jina.ai returns 401 without one)"}
    try:
        r = requests.get("https://s.jina.ai/" + urllib.parse.quote(query),
                         headers={"Authorization": f"Bearer {v}", "User-Agent": UA}, timeout=60)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "reason": f"http {r.status_code}: {r.text[:120]}"}
    urls = re.findall(r"https?://[^\s\)\]\"'<>]+", r.text)
    rows = [{"url": u} for u in dict.fromkeys(urls)][:count]
    return {"ok": True, "rows": rows, "meta": {"provider": "jina-search"}}


def p_alexandria(provider, capability, options, keys):
    """Firecrawl Alexandria: typed records for amazon-com, walmart-com, newegg-com, dell-com, ebay-com."""
    v = keys.get("FIRECRAWL_API_KEY")
    if not v:
        return {"ok": False, "reason": "FIRECRAWL_API_KEY not set"}
    payload = {"alexandria": [{"provider": provider, "capability": capability, "options": options}]}
    try:
        # Alexandria lives on the v2 scrape endpoint. v1 rejects the `alexandria` body key outright with
        # "Unrecognized key in body" - measured 2026-10-22, and worth keeping in the code rather than a note.
        r = requests.post("https://api.firecrawl.dev/v2/scrape", json=payload,
                          headers={"Authorization": f"Bearer {v}", "Content-Type": "application/json"},
                          timeout=180)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "reason": f"http {r.status_code}: {r.text[:200]}"}
    body = r.json()
    blocks = (body.get("data") or {}).get("alexandria") or []
    if not blocks:
        return {"ok": False, "reason": "no alexandria block in response"}
    b0 = blocks[0]
    if b0.get("error"):
        return {"ok": False, "reason": f"provider error: {b0['error']}"}
    return {"ok": True, "data": b0.get("data"), "meta": {"creditsCost": body.get("creditsCost")}}


# ------------------------------------------------------------------ commands

def cmd_doctor(args):
    keys = load_keys()
    print("fetchkit doctor - what THIS host can actually do\n")
    print(f"  {'key':<24} {'source':<14} present")
    for n in KEY_NAMES:
        present = "yes" if n in keys else "NO"
        print(f"  {n:<24} {_src(n, keys):<14} {present}")
    print("\n  provider        status")
    print("  " + "-" * 60)
    rows = []
    for name, needs in (("http", []), ("jina-reader", []), ("playwright", []),
                        ("firecrawl-scrape", ["FIRECRAWL_API_KEY"]),
                        ("firecrawl-alexandria", ["FIRECRAWL_API_KEY"]),
                        ("brave-search", ["BRAVE_SEARCH_API_KEY"]),
                        ("serpapi", ["SERPAPI_API_KEY"]),
                        ("jina-search", ["JINA_API_KEY"])):
        miss = [k for k in needs if k not in keys]
        ok = not miss
        rows.append((name, ok, miss))
        print(f"  {name:<16} {'READY' if ok else 'OFF - missing ' + ','.join(miss)}")
    ready = sum(1 for _, ok, _ in rows if ok)
    print(f"\n  {ready} of {len(rows)} providers ready on this host.")
    if readme_env():
        print(f"  keys read from: {readme_env()}")
    return 0


def readme_env():
    for p in ENV_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def cmd_get(args):
    keys = load_keys()
    order = [args.backend] if args.backend != "auto" else ["http", "jina", "firecrawl", "playwright"]
    attempts = []
    for name in order:
        res = (p_http(args.url) if name == "http"
               else p_jina(args.url, keys) if name == "jina"
               else p_firecrawl(args.url, keys) if name == "firecrawl"
               else p_playwright(args.url))
        attempts.append((name, res.get("ok"), res.get("reason")))
        if res.get("ok"):
            text = res["text"]
            print(f"backend   {name}")
            print(f"chars     {len(text)}")
            for a in attempts[:-1]:
                print(f"  fell through {a[0]}: {a[2]}")
            print("\n" + text[:args.lines * 400])
            return 0
    print("REFUSED - every backend failed:")
    for a in attempts:
        print(f"  {a[0]}: {a[2]}")
    return 1


def cmd_search(args):
    keys = load_keys()
    order = [args.backend] if args.backend != "auto" else ["brave", "serpapi", "jina"]
    for name in order:
        res = (p_brave(args.query, keys, args.count) if name == "brave"
               else p_serpapi(args.query, keys, args.count) if name == "serpapi"
               else p_jina_search(args.query, keys, args.count))
        if not res.get("ok"):
            print(f"  {name}: {res.get('reason')}")
            continue
        print(f"provider  {name}   ({len(res['rows'])} result(s))")
        for r in res["rows"]:
            print(f"  - {r.get('title') or '(no title)'}")
            print(f"    {r.get('url')}")
            if r.get("description"):
                print(f"    {r['description'][:160]}")
        return 0
    print("REFUSED - no search provider could answer (that is not the same as no results).")
    return 1


def cmd_alexandria(args):
    keys = load_keys()
    if args.catalogue:
        # what capabilities exist for a site? free discovery, no credits
        v = keys.get("FIRECRAWL_API_KEY")
        print("catalogue discovery needs the firecrawl MCP tool (firecrawl_find_tools) with urls=[...]")
        print(f"FIRECRAWL_API_KEY present: {'yes' if v else 'no'}")
        return 0
    if not (args.provider and args.capability):
        print("need <provider> <capability>, e.g. walmart-com products/search --options '{\"query\":\"...\"}'")
        return 2
    try:
        options = json.loads(args.options or "{}")
    except json.JSONDecodeError as e:
        print(f"REFUSED: --options is not valid JSON: {e}")
        return 2
    res = p_alexandria(args.provider, args.capability, options, keys)
    if not res.get("ok"):
        print(f"REFUSED: {res.get('reason')}")
        return 1
    print(json.dumps(res["data"], indent=2)[:20000])
    if res.get("meta", {}).get("creditsCost") is not None:
        print(f"\ncreditsCost {res['meta']['creditsCost']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fetchkit", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("doctor", help="what can this host do"); s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("get", help="fetch one url through the chain")
    s.add_argument("url")
    s.add_argument("--backend", default="auto", choices=["auto", "http", "jina", "firecrawl", "playwright"])
    s.add_argument("--lines", type=int, default=40)
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("search", help="web search through a real search API")
    s.add_argument("query")
    s.add_argument("--backend", default="auto", choices=["auto", "brave", "serpapi", "jina"])
    s.add_argument("--count", type=int, default=10)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("alexandria", help="structured records: amazon-com, walmart-com, newegg-com, dell-com, ebay-com")
    s.add_argument("provider", nargs="?")
    s.add_argument("capability", nargs="?")
    s.add_argument("--options", default="{}")
    s.add_argument("--catalogue", action="store_true")
    s.set_defaults(fn=cmd_alexandria)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
