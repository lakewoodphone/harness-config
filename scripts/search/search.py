#!/usr/bin/env python3
"""search.py - one small, stdlib-only search/fetch command for agents.

Why this exists
---------------
The owner pays for search providers, but the agent tool surface cannot reach
them: the seat falls back to the harness's own web_search/web_fetch, and
headless mesh children have no browse path at all. The six mounted MCP families
already cost ~87,777 characters (~21,944 tokens) of tool schema on every request
that sees them, so the fix is NOT another MCP family. This is one command.

Design rules (the point of the exercise)
----------------------------------------
* Credentials are read from the application env file BY VARIABLE NAME. Values
  are never printed, never logged, never embedded in a result. Only names and
  whether they are present appear anywhere.
* A missing credential is a clean, named failure (exit 2). There is no silent
  fallback to another provider.
* Routing lives in data: scripts/search/routing.json. `--provider auto` reads it
  and prints which provider it chose and why, in one line.
* The caller gets a compact result; the full raw response goes to a file whose
  path is printed. Same principle as the schema tax: do not flood the context.
* Every call is appended to a small JSONL log (timestamp, provider, latency,
  outcome) so usage is answerable later instead of guessed.

Usage
-----
    python scripts/search/search.py --provider auto --query "how much do iPhone 14 OLED panels cost"
    python scripts/search/search.py --provider exa --query "OLED panel suppliers"
    python scripts/search/search.py --provider spider --url "https://www.ebay.com/itm/..."
    python scripts/search/search.py --provider tavily --query "..." --env-file /path/to/.env
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROUTING_FILE = SCRIPT_DIR / "routing.json"
DEFAULT_STATE_DIR = SCRIPT_DIR / "state"
USER_AGENT = "harness-search/1.0 (+stdlib)"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_CREDENTIAL = 2
EXIT_USAGE = 3


# --------------------------------------------------------------------------
# routing (data-driven)
# --------------------------------------------------------------------------
def load_routing(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _compile_patterns(patterns: list) -> list:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _matches(compiled: list, text: str) -> bool:
    return any(rx.search(text) for rx in compiled)


def decide_provider(routing: dict, query: str | None, url: str | None):
    """Apply the ordered rules in routing.json. Returns (provider, rule_id, why)."""
    discovery = _compile_patterns(routing.get("discovery_patterns", []))
    answer = _compile_patterns(routing.get("answer_patterns", []))
    for rule in routing.get("rules", []):
        kind = rule.get("match")
        if kind == "url" and url:
            return rule["provider"], rule["id"], rule["why"]
        if kind == "discovery" and query and _matches(discovery, query):
            return rule["provider"], rule["id"], rule["why"]
        if kind == "answer" and query and _matches(answer, query):
            return rule["provider"], rule["id"], rule["why"]
        if kind == "default":
            return rule["provider"], rule["id"], rule["why"]
    raise SystemExit("routing.json has no matching rule")


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------
def resolve_env_file(explicit: str | None, routing: dict) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    override = os.environ.get("SEARCH_ENV_FILE")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    repo_parent = SCRIPT_DIR.parents[1].parent  # .../Code
    rendered = [
        c.format(HOME=str(home), REPO_PARENT=str(repo_parent))
        for c in routing.get("env_file_candidates", [])
    ]
    for candidate in rendered:
        if Path(candidate).exists():
            return Path(candidate)
    # Nothing found: return the first expectation so the error names a real path.
    return Path(rendered[0]) if rendered else Path(".env")


def load_env_names(path: Path):
    """Parse KEY=VALUE names. Returns (dict name->value, error-or-None).

    The returned values are used only to build request headers. They are never
    printed, logged, or written into a result file by this program.
    """
    if not path.exists():
        return {}, "env file not found"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {}, f"env file unreadable ({exc.__class__.__name__})"

    values: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value:
            values[name] = value
    return values, None


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------
def build_request(provider: str, cfg: dict, key: str | None, query: str | None,
                  url: str | None, max_results: int):
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    auth = cfg.get("auth", {})
    if key:
        if auth.get("type") == "bearer":
            headers[auth.get("header", "Authorization")] = "Bearer " + key
        elif auth.get("type") == "header":
            headers[auth.get("header", "x-api-key")] = key

    if provider == "tavily":
        body = {
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }
    elif provider == "exa":
        body = {
            "query": query,
            "numResults": max_results,
            "contents": {"text": {"maxCharacters": 1200}},
        }
    elif provider == "spider":
        body = {"url": url, "return_format": "markdown"}
    else:
        raise SystemExit(f"unknown provider {provider!r}")

    return cfg["method"], cfg["endpoint"], headers, body


def http_call(method: str, endpoint: str, headers: dict, body: dict, timeout: int) -> dict:
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = getattr(response, "status", None) or response.getcode()
        return {
            "ok": True,
            "status": status,
            "raw": raw,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        return {
            "ok": False,
            "status": exc.code,
            "raw": raw,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # network, DNS, TLS, timeout
        return {
            "ok": False,
            "status": None,
            "raw": b"",
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": f"{exc.__class__.__name__}: {exc}",
        }


# --------------------------------------------------------------------------
# result shaping
# --------------------------------------------------------------------------
def parse_body(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def extract_cost(provider: str, data) -> str:
    if isinstance(data, dict):
        cost_dollars = data.get("costDollars")
        if isinstance(cost_dollars, dict) and cost_dollars.get("total") is not None:
            return f"USD {cost_dollars['total']} (reported)"
        if isinstance(data.get("cost"), (int, float)):
            return f"USD {data['cost']} (reported)"
        usage = data.get("usage")
        if isinstance(usage, dict):
            if usage.get("credits") is not None:
                return f"{usage['credits']} credits (reported)"
            if usage.get("total_tokens") is not None:
                return f"{usage['total_tokens']} tokens (reported)"
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("cost"), (int, float)):
                return f"USD {item['cost']} (reported)"
    return "not reported"


def extract_content(provider: str, data):
    """Return (text, [source lines], provider_error_or_None)."""
    sources: list = []

    if provider == "tavily":
        if not isinstance(data, dict):
            return str(data or ""), sources, None
        answer = (data.get("answer") or "").strip()
        chunks = []
        if answer:
            chunks.append("ANSWER: " + answer)
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            link = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            if title or link:
                sources.append(f"{title} — {link}".strip(" —"))
            if content:
                chunks.append(content)
        return "\n\n".join(chunks), sources, None

    if provider == "exa":
        if not isinstance(data, dict):
            return str(data or ""), sources, None
        chunks = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            link = (item.get("url") or "").strip()
            text = (item.get("text") or item.get("summary") or "").strip()
            if title or link:
                sources.append(f"{title} — {link}".strip(" —"))
            if text:
                chunks.append(text)
        return "\n\n".join(chunks), sources, None

    if provider == "spider":
        items = data if isinstance(data, list) else [data]
        chunks = []
        for item in items:
            if not isinstance(item, dict):
                chunks.append(str(item))
                continue
            if item.get("error"):
                return "", sources, str(item["error"])
            content = item.get("content")
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            if content:
                chunks.append(str(content))
        return "\n\n".join(chunks), sources, None

    return str(data or ""), sources, None


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def append_log(log_path: Path, entry: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search.py",
        description="One reachable search path: Tavily (answers), Exa (discovery), Spider (known URLs).",
    )
    parser.add_argument("--provider", choices=["tavily", "exa", "spider", "auto"], default="auto")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--query", help="a search query")
    target.add_argument("--url", help="a known URL to fetch")
    parser.add_argument("--env-file", help="env file to read credential NAMES from (never values)")
    parser.add_argument("--routing", default=str(ROUTING_FILE), help="routing rules file")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="where raw responses and the log live")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--max-chars", type=int, default=1500, help="max result characters printed to the caller")
    parser.add_argument("--timeout", type=int, default=45)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    routing = load_routing(Path(args.routing))
    state_dir = Path(args.state_dir)
    raw_dir = state_dir / "raw"
    log_path = state_dir / "search-log.jsonl"

    if not args.query and not args.url:
        print("usage_error: give --query TEXT or --url URL", file=sys.stderr)
        return EXIT_USAGE

    if args.provider == "auto":
        provider, rule_id, why = decide_provider(routing, args.query, args.url)
        print(f"route: provider={provider} rule={rule_id} why=\"{why}\"")
    else:
        provider = args.provider
        rule_id = None
        why = None
        if provider == "spider" and not args.url:
            print("usage_error: --provider spider needs --url URL", file=sys.stderr)
            return EXIT_USAGE
        if provider in ("tavily", "exa") and not args.query:
            print(f"usage_error: --provider {provider} needs --query TEXT", file=sys.stderr)
            return EXIT_USAGE

    cfg = routing["providers"][provider]
    cred_name = cfg.get("cred_env")
    env_path = resolve_env_file(args.env_file, routing)
    values, env_error = load_env_names(env_path)
    key = values.get(cred_name) if cred_name else None

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stub = {
        "ts": timestamp,
        "provider": provider,
        "rule": rule_id,
        "mode": "url" if args.url else "query",
        "target": args.url or args.query,
        "env_file": str(env_path),
        "cred_env": cred_name,
    }

    if not key and cfg.get("cred_required", True):
        detail = f" ({env_error})" if env_error else ""
        print(
            f"provider={provider} status=missing_credential missing={cred_name} "
            f"env_file={env_path}{detail}"
        )
        print(f"fix: add {cred_name}=... to {env_path} — this command will not fall back to another provider.")
        append_log(log_path, {**stub, "outcome": "missing_credential", "missing": cred_name,
                              "latency_ms": None, "http_status": None, "cost": None,
                              "chars": 0, "raw_path": None})
        return EXIT_MISSING_CREDENTIAL

    if not key:
        print(f"provider={provider} credential={cred_name} absent; {provider} documents keyless access, proceeding")

    method, endpoint, headers, body = build_request(
        provider, cfg, key, args.query, args.url, args.max_results
    )
    result = http_call(method, endpoint, headers, body, args.timeout)
    latency_ms = result["elapsed_ms"]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw_path = raw_dir / f"{stamp}-{provider}.json"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(result["raw"] or b"")

    data = parse_body(result["raw"])
    content, sources, provider_error = extract_content(provider, data)
    cost = extract_cost(provider, data) if result["ok"] else "not reported"
    http_status = result["status"]

    # Bounded body snippet for error diagnosis; the credential is in a header,
    # never in the body, and this is capped so it cannot flood the caller.
    snippet = ""
    if not result["ok"]:
        try:
            snippet = (result["raw"] or b"").decode("utf-8", errors="replace")[:300].replace("\n", " ")
        except Exception:
            snippet = ""

    outcome = "ok" if result["ok"] and not provider_error else (
        "provider_error" if provider_error else "http_error" if not result["ok"] else "ok"
    )

    header = (
        f"provider={provider} latency_ms={latency_ms} cost={cost} "
        f"chars={len(content)} status={http_status if http_status is not None else 'network_error'} "
        f"raw={raw_path}"
    )
    if rule_id:
        header += f" rule={rule_id}"
    print(header)
    if why:
        print(f"why: {why}")

    if result["ok"] and not provider_error:
        excerpt = content[: args.max_chars]
        print("--- content ---")
        print(excerpt if excerpt else "(no content returned)")
        if len(content) > args.max_chars:
            print(f"... [{len(content) - args.max_chars} more chars in the raw file]")
        if sources:
            print(f"--- sources ({len(sources)}) ---")
            for idx, source in enumerate(sources, 1):
                print(f"{idx}. {source}")
    else:
        print(f"error: {result['error'] or provider_error}")
        if snippet:
            print(f"body: {snippet}")

    append_log(log_path, {
        **stub,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "http_status": http_status,
        "cost": cost,
        "chars": len(content),
        "sources": len(sources),
        "raw_path": str(raw_path),
        "error": result["error"] or provider_error,
    })

    if result["ok"] and not provider_error:
        return EXIT_OK
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
