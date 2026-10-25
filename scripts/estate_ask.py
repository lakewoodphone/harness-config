#!/usr/bin/env python3
"""estate_ask.py — ask the estate a question and get a cited answer, not a list of files.

WHY THIS EXISTS (2026-10-25)
----------------------------
`esearch` finds documents. It does not answer questions. Measured 2026-10-25: `ps_search` for
"sourcing fanout price ledger" returned six hits in 345 ms — every one with `snippet: ""` and
`score: 0.0`, matched on the path, so the caller must open each file to learn why it matched.
That is retrieval without comprehension, and it is why agents here re-read whole documents
instead of searching.

The estate already had a research pipeline (`research_jobs` on the authority) and it has been
silent since **2026-07-08T05:40:32Z** — 70 rows queued since 2026-07-03, 3 stuck in `running`.
A dead pipeline is not a capability. This is the small live one: search, select, read, and
answer from the evidence with the citations attached — and say plainly what the evidence did
not cover, because "I found nothing" and "I could not look" are different sentences.

WHAT IT DOES
    1. expands one question into 3 bounded searches (the question, its content words, its phrase)
    2. asks `esearch` for each; dedupes by path; keeps the best
    3. prefers real excerpts, and falls back to the local copy of a known corpus path
    4. asks the company model gateway for a short answer that cites [n]
    5. prints ANSWER / EVIDENCE / NOT COVERED / STORES

Models are NEVER hardcoded (standing instruction 2026-09-15, journal L1606): the alias is
resolved against the gateway's own catalog at runtime and validated before use. If the model is
unavailable the evidence is STILL printed and the failure is stated — never a silent fallback,
because a silent fallback is how a week of broken AI calls went unnoticed.

USAGE
    python3 estate_ask.py "why does the wake dispatcher wedge"
    python3 estate_ask.py "what did we learn about ebay condition filters" --scope all --limit 10
    python3 estate_ask.py "..." --json
    python3 estate_ask.py "..." --no-model          # evidence only, no LLM, no cost
    python3 estate_ask.py "..." --model secretary-smart

EXIT CODES  0 answered · 1 no evidence found · 2 bad usage · 3 esearch unreachable
            4 evidence found but synthesis unavailable (partial, and it says so)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ESEARCH = os.environ.get("ESEARCH_URL", "http://127.0.0.1:3095")
GATEWAY = os.environ.get("SECRETARY_API_BASE", "http://127.0.0.1:8002").rstrip("/")
DEFAULT_MODEL = os.environ.get("ESTATE_ASK_MODEL", "secretary-auto")

STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was",
    "were", "be", "been", "do", "does", "did", "how", "why", "what", "when", "where", "which",
    "who", "that", "this", "it", "its", "we", "our", "us", "i", "you", "your", "any", "all",
    "should", "would", "could", "can", "not", "no", "if", "then", "than", "about", "from",
    "into", "but", "so", "as", "at", "by", "there", "here", "they", "them", "he", "she", "his",
}


# ---------------------------------------------------------------- credentials (never printed)
def _esearch_token() -> str:
    """Read the esearch token from the environment or the unit's env file. Names only, ever."""
    for name in ("ESEARCH_TOKEN", "USEARCH_TOKEN"):
        val = os.environ.get(name)
        if val:
            return val.strip()
    for path in (Path("/etc/esearch.env"), Path.home() / ".secrets" / "esearch.env"):
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                if key.strip().endswith("TOKEN"):
                    return raw.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


# ---------------------------------------------------------------- search
def _get(url: str, timeout: int = 40) -> dict:
    req = urllib.request.Request(url)
    tok = _esearch_token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
        req.add_header("X-Esearch-Token", tok)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def search(query: str, scope: str = "all", limit: int = 8, host: str = "") -> dict:
    params = {"q": query, "scope": scope or "all", "limit": str(limit), "json": "1"}
    if host:
        params["host"] = host
    return _get(f"{ESEARCH}/search?" + urllib.parse.urlencode(params))


def expand(question: str) -> list[str]:
    """Three bounded queries from one question. Deterministic — a model in this path would add
    latency, cost and non-determinism to the one step that must be repeatable."""
    words = [w for w in re.findall(r"[A-Za-z0-9_\-\.]+", question.lower()) if w not in STOP]
    qs: list[str] = []
    quoted = re.findall(r'"([^"]+)"', question)
    for phrase in quoted:
        if phrase.strip():
            qs.append(phrase.strip())
    qs.append(question.strip())
    if len(words) > 1:
        qs.append(" ".join(words[:6]))
    if len(words) > 4:
        qs.append(" ".join(words[:3]))
    out: list[str] = []
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[:3]


def gather(question: str, scope: str, limit: int, host: str = "") -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (hits, stores, did_not_answer). A store that refuses is never a negative."""
    seen: dict[str, dict] = {}
    stores: dict[str, dict] = {}
    refused: dict[str, dict] = {}
    errors: list[str] = []
    for q in expand(question):
        try:
            resp = search(q, scope=scope, limit=limit, host=host)
        except urllib.error.HTTPError as exc:
            errors.append(f"esearch HTTP {exc.code} for {q!r}")
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"esearch unreachable: {type(exc).__name__}: {exc}")
            continue
        for s in resp.get("stores") or []:
            name = s.get("name") or "?"
            cur = stores.setdefault(name, {"name": name, "answered": False, "ms": 0, "hits": 0})
            cur["answered"] = cur["answered"] or bool(s.get("answered"))
            cur["ms"] = max(cur["ms"], int(s.get("ms") or 0))
            cur["hits"] = max(cur["hits"], int(s.get("hits") or 0))
        for d in resp.get("did_not_answer") or []:
            key = str(d.get("store") or d.get("name") or "?")
            refused[key] = d
        for h in resp.get("hits") or []:
            path = h.get("path") or h.get("locator") or h.get("title") or ""
            if not path:
                continue
            keep = {"query": q, **h}
            if path not in seen or _rank(keep) > _rank(seen[path]):
                seen[path] = keep
    hits = sorted(seen.values(), key=_rank, reverse=True)
    if errors:
        refused.setdefault("esearch", {"store": "esearch", "reason": "; ".join(errors[:2])})
    return hits, list(stores.values()), list(refused.values())


KIND_WEIGHT = {"lesson": 6, "journal": 6, "doc": 5, "code": 3, "file": 1, "session": 2,
               "email": 2, "memory": 3, "comms": 3}


def _rank(hit: dict) -> float:
    """Content beats a path match. A hit with a real excerpt and a real score outranks one that
    only matched its filename — the defect measured on 2026-10-25 was six hits ranked purely on
    path with `score: 0.0` and `snippet: ""`."""
    score = float(hit.get("score") or 0.0)
    kind = str(hit.get("kind") or "")
    return score * 10 + KIND_WEIGHT.get(kind, 2) + (2 if (hit.get("snippet") or "").strip() else 0)


# ---------------------------------------------------------------- evidence
_AUTH_PREFIXES = {
    "C:\\Users\\ezabz\\code\\harness-config\\": "/root/code/harness-config/",
    "C:\\Users\\ezabz\\code\\lpt-hub\\": "/root/code/lpt-hub/",
}


def local_copy(path: str) -> str:
    """A Windows path indexed from a laptop often has a twin on this host. Try the known
    roots, then a basename search inside the journal (the corpus that matters most)."""
    p = path.strip()
    if os.path.isfile(p):
        return p
    for win, lin in _AUTH_PREFIXES.items():
        if p.lower().startswith(win.lower()):
            cand = lin + p[len(win):].replace("\\", "/")
            if os.path.isfile(cand):
                return cand
    m = re.search(r"journal[/\\]entries[/\\]([a-z]+)[/\\]([A-Za-z0-9\-]+)\.md$", p)
    if m:
        cand = Path("/root/code/harness-config/journal/entries") / m.group(1) / f"{m.group(2)}.md"
        if cand.is_file():
            return str(cand)
    return ""


def excerpt(hit: dict, question: str, width: int = 700) -> str:
    """A real quotation from the hit, or an honest statement that there is none."""
    snip = (hit.get("snippet") or "").strip()
    if snip:
        return re.sub(r"\s+", " ", snip)[:width]
    loc = local_copy(str(hit.get("path") or hit.get("locator") or ""))
    if not loc:
        return ""
    try:
        text = Path(loc).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    terms = [w for w in re.findall(r"[A-Za-z0-9_\-]+", question.lower()) if w not in STOP and len(w) > 2]
    pos = 0
    for t in terms:
        found = text.lower().find(t)
        if found >= 0:
            pos = found
            break
    start = max(0, pos - 260)
    chunk = text[start:start + width]
    if start > 0:
        chunk = "…" + chunk
    return re.sub(r"\s+", " ", chunk)[:width]


def build_prompt(question: str, evidence: list[dict]) -> list[dict]:
    blocks = []
    for i, e in enumerate(evidence, 1):
        line = f"[{i}] {e['kind']} · {e['title']} · {e.get('host') or '?'} · {e.get('when') or '?'}"
        body = e.get("body") or ""
        blocks.append(line + ("\n" + body if body else "\n(no excerpt available for this item)"))
    system = (
        "You answer questions about a small business and its engineering estate using ONLY the "
        "numbered EVIDENCE below. Rules: cite the bracketed number after every claim you make "
        "from evidence; never invent a fact, a number, a path or a date that is not in the "
        "evidence; if the evidence does not answer the question, say so in one sentence and name "
        "what is missing; if an item says no excerpt is available, say you could not read it "
        "rather than guessing its content. Answer in at most 150 words, plain prose, no preamble, "
        "no headings, no lists unless the answer is genuinely a list."
    )
    user = f"QUESTION: {question}\n\nEVIDENCE:\n" + "\n\n".join(blocks)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- model (resolved, never hardcoded)
def catalog() -> tuple[list[str], str]:
    try:
        body = _get(f"{GATEWAY}/v1/models", timeout=20)
    except Exception:  # noqa: BLE001
        return [], ""
    ids = [m.get("id") for m in (body.get("data") or []) if m.get("id")]
    aliases = [m.get("id") for m in (body.get("data") or [])
               if m.get("id") and m.get("kind") == "route_alias"]
    return ids, (aliases[0] if aliases else (ids[0] if ids else ""))


def resolve_model(wanted: str) -> tuple[str, str]:
    """Validate the configured alias against the gateway's own catalog. An unlisted id is
    dropped rather than sent, because a hardcoded name that stopped existing is exactly how
    every live AI call in this estate failed silently for a week (journal L1606)."""
    ids, first_alias = catalog()
    if not ids:
        return "", "catalog unreachable"
    if wanted in ids:
        return wanted, ""
    if first_alias:
        return first_alias, f"{wanted!r} not in catalog; used {first_alias!r}"
    return "", f"{wanted!r} not in catalog and no route alias offered"


def synthesise(question: str, evidence: list[dict], model: str) -> tuple[str, str]:
    """Returns (answer, error). An error is stated, never swallowed."""
    chosen, note = resolve_model(model)
    if not chosen:
        return "", note or "no model available"
    payload = {"model": chosen, "messages": build_prompt(question, evidence),
               "temperature": 0.2, "max_tokens": 700}
    req = urllib.request.Request(
        f"{GATEWAY}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return "", f"gateway HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:  # noqa: BLE001
        return "", f"gateway unreachable: {type(exc).__name__}: {exc}"
    try:
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:  # noqa: BLE001
        text = ""
    if not text.strip():
        return "", f"gateway returned no text (served_by={body.get('model') or '?'})"
    served = body.get("model") or chosen
    return text.strip(), ("" if not note else note + f" (served by {served})")


# ---------------------------------------------------------------- main
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Ask the estate a question; get a cited answer.")
    ap.add_argument("question")
    ap.add_argument("--scope", "--what", dest="scope", default="all",
                    help="all|code|docs|journal|sessions|data|files|symbol")
    ap.add_argument("--limit", type=int, default=8, help="hits per search (default 8)")
    ap.add_argument("--host", default="")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-model", action="store_true", help="evidence only: no LLM, no cost")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if len(a.question.strip()) < 3:
        print("a question needs at least three characters", file=sys.stderr)
        return 2

    hits, stores, refused = gather(a.question, a.scope, max(1, min(a.limit, 25)), a.host)
    evidence = []
    for h in hits[: max(6, a.limit)]:
        evidence.append({
            "kind": h.get("kind") or "?",
            "title": h.get("title") or "(untitled)",
            "host": h.get("host") or "",
            "when": h.get("when") or "",
            "path": h.get("path") or h.get("locator") or "",
            "score": h.get("score"),
            "body": excerpt(h, a.question),
        })

    answer, err = ("", "not requested (--no-model)")
    if evidence and not a.no_model:
        answer, err = synthesise(a.question, evidence, a.model)

    if a.json:
        print(json.dumps({"question": a.question, "queries": expand(a.question), "answer": answer,
                          "synthesis_error": err, "evidence": evidence, "stores": stores,
                          "did_not_answer": refused}, indent=2, ensure_ascii=False))
    else:
        print(f"QUESTION  {a.question}\n")
        if answer:
            print("ANSWER")
            print("  " + answer.replace("\n", "\n  ") + "\n")
        elif evidence:
            print("ANSWER")
            print(f"  none — {err}\n")
        if evidence:
            print("EVIDENCE")
            for i, e in enumerate(evidence, 1):
                print(f"  [{i}] {e['kind']:<7} {e['title'][:88]}")
                print(f"      {e['host'] or '?'} · {e['when'] or '?'} · {e['path']}")
                if e["body"]:
                    print(f"      {e['body'][:300]}")
                else:
                    print("      (no excerpt available — this hit matched on its path)")
            print()
        missing = [e["title"] for e in evidence if not e["body"]]
        print("NOT COVERED")
        if not evidence:
            print("  nothing matched in any store — this is a real negative, not a refusal")
        elif missing:
            print(f"  {len(missing)} of {len(evidence)} hits could not be read (path-only match)")
        else:
            print("  every hit carried an excerpt; the answer is bounded by the evidence above")
        print()
        print("STORES")
        for s in sorted(stores, key=lambda x: x["name"]):
            print(f"  [{'ok ' if s['answered'] else 'MISS'}] {s['name']:<22} "
                  f"{s['hits']:>3} hits · {s['ms']} ms")
        for d in refused:
            print(f"  [refused] {d.get('store') or d.get('name')}: "
                  f"{str(d.get('reason'))[:140]}")

    if not evidence:
        return 1
    if not a.no_model and not answer:
        return 4
    return 0


def run(question: str = "", **kwargs: Any) -> dict[str, Any]:
    """Company-dispatcher entry point (`data/tools/*.py` `run()` convention)."""
    if not question:
        return {"ok": False, "result": "question is required"}
    hits, stores, refused = gather(question, kwargs.get("scope") or "all",
                                   int(kwargs.get("limit") or 8), kwargs.get("host") or "")
    evidence = [{"kind": h.get("kind"), "title": h.get("title"), "host": h.get("host"),
                 "when": h.get("when"), "path": h.get("path") or h.get("locator"),
                 "body": excerpt(h, question)} for h in hits[: max(6, int(kwargs.get("limit") or 8))]]
    answer, err = ("", "no question")
    if evidence:
        answer, err = synthesise(question, evidence, kwargs.get("model") or DEFAULT_MODEL)
    return {"ok": bool(evidence), "result": {
        "question": question, "answer": answer, "synthesis_error": err,
        "evidence": [{k: v for k, v in e.items() if k != "body"} | {"excerpt": (e["body"] or "")[:240]}
                     for e in evidence],
        "stores": stores, "did_not_answer": refused}}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
