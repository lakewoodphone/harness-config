#!/usr/bin/env python3
"""verify-badge-gate.py — the gate half of the badge contract, as machine-readable checks.

Run by `scripts/verify-badge.js` (which knows nothing about Python) and runnable on its own:

    python scripts/verify-badge-gate.py          human-readable
    python scripts/verify-badge-gate.py --json   {"check name": true|false, ...}

WHY A HELPER AND NOT A COPY
The checks import the real `phone-gate.py` and call its real functions with the kernel state file
redirected at a temporary directory. A test that re-implements the thing it tests proves only that
the author can write the same bug twice.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "phone-gate.py"

RESULTS: dict[str, bool] = {}
DETAILS: dict[str, str] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS[name] = bool(ok)
    if detail:
        DETAILS[name] = detail


def load_gate(state_dir: Path):
    os.environ["CEO_KERNEL_STATE"] = str(state_dir)
    spec = importlib.util.spec_from_file_location("phone_gate_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def head_of(response: bytes) -> str:
    return response.split(b"\r\n\r\n", 1)[0].decode("latin-1")


def body_of(response: bytes) -> bytes:
    return response.split(b"\r\n\r\n", 1)[1]


def emit_payload() -> int:
    """Print the real payload for a real kernel document, for the cross-language round trip.

    This exists so `scripts/verify-badge.js` can render the *gate's own bytes* with the *badge's own
    renderer*. The two halves share a field contract and are written in different languages; the only
    test that can catch a rename on one side is one that crosses the boundary.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        gate = load_gate(state)
        (state / "latest.json").write_text(json.dumps({
            "kernel": "ceo-kernel",
            # Now, not a fixed date: the badge marks a reading stale past 20 minutes, so a hardcoded
            # stamp would make this test fail the moment the clock moved past it - and a test that
            # fails for the calendar rather than the code is a test nobody keeps.
            "at": datetime.now(timezone.utc).isoformat(),
            "host": "secratary",
            "summary": {"total": 13, "ok": 7, "attention": 6, "unknown": 0},
            "findings": [
                {"check": "liveness", "severity": "info", "ok": True, "needs_attention": False, "summary": "ticking"},
                {"check": "delivery", "severity": "critical", "ok": False, "needs_attention": True,
                 "summary": "nothing is reaching the owner for 57d"},
                {"check": "evolution", "severity": "high", "ok": False, "needs_attention": True,
                 "summary": "71 proposals unapplied"},
            ],
        }), encoding="utf-8")
        sys.stdout.write(gate.badge_payload().decode("utf-8"))
    return 0


def main() -> int:
    if "--payload" in sys.argv:
        return emit_payload()
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        gate = load_gate(state)

        # ---- the payload, from a real kernel document --------------------------------
        real = {
            "kernel": "ceo-kernel",
            "generatedAt": "2026-09-14T06:00:00+00:00",
            "at": "2026-09-14T06:00:00+00:00",
            "host": "secratary",
            "database": {"tables": 213, "authoritative": True},
            "summary": {"total": 13, "ok": 7, "attention": 6, "unknown": 0},
            "findings": [
                {"check": "liveness", "severity": "info", "ok": True, "needs_attention": False, "summary": "ticking"},
                {"check": "delivery", "severity": "critical", "ok": False, "needs_attention": True, "summary": "57d silent"},
                {"check": "evolution", "severity": "high", "ok": False, "needs_attention": True, "summary": "71 unapplied"},
                {"check": "dead_weight", "severity": "medium", "ok": False, "needs_attention": True, "summary": "5 idle"},
            ],
        }
        (state / "latest.json").write_text(json.dumps(real), encoding="utf-8")
        payload = json.loads(gate.badge_payload().decode())

        check("payload reads a real kernel document", payload.get("read") is True)
        check("the success flag is not a count", not isinstance(payload.get("read"), int) or payload.get("read") is True)
        check("payload has no key that is both a flag and a count",
              not ("ok" in payload and payload.get("ok") is not True))
        check("payload carries the healthy count", payload.get("healthy") == 7 and payload.get("ok_count") == 7)
        check("payload reports the attention count", payload.get("attention") == 6)
        check("payload reports the worst severity", payload.get("highest") == "critical")
        check("payload orders findings worst-first",
              [c["check"] for c in payload["checks"]] == ["delivery", "evolution", "dead_weight"])
        check("payload excludes findings that need no attention",
              all(c["needs_attention"] for c in payload["checks"]))
        check("payload lists the quiet checks", payload.get("quiet") == ["liveness"])
        check("payload carries the reading's timestamp", payload.get("at") == "2026-09-14T06:00:00+00:00")
        check("payload always carries a checks list", isinstance(payload.get("checks"), list))

        # ---- a healthy zero is not a refusal -----------------------------------------
        (state / "latest.json").write_text(json.dumps({
            "at": "2026-09-14T06:00:00+00:00", "host": "secratary",
            "summary": {"total": 13, "ok": 13, "attention": 0, "unknown": 0},
            "findings": [{"check": "liveness", "severity": "info", "needs_attention": False}],
        }), encoding="utf-8")
        zero = json.loads(gate.badge_payload().decode())
        check("a healthy zero reads as a reading", zero.get("read") is True)
        check("a healthy zero reports zero attention", zero.get("attention") == 0)
        # THIS is the regression the first version shipped: with `ok` holding the healthy CHECK COUNT,
        # an all-clear produced `ok: 0`, and any truthiness test on it called a healthy system broken.
        check("a healthy zero is not falsy under a truthiness test", bool(zero.get("read")) is True)
        check("a healthy zero is distinguishable from a refusal",
              zero.get("read") is True and "error" not in zero)
        check("a healthy zero has the worst severity info", zero.get("highest") == "info")

        # ---- every refusal direction -------------------------------------------------
        (state / "latest.json").write_text("{not json", encoding="utf-8")
        gate._BADGE_CACHE.update({"key": None, "body": b"", "at": 0.0})
        broken = json.loads(gate.badge_payload().decode())
        check("unparseable state is a refusal", broken.get("read") is False and "not valid JSON" in broken.get("error", ""))

        (state / "latest.json").write_text("[1,2,3]", encoding="utf-8")
        gate._BADGE_CACHE.update({"key": None, "body": b"", "at": 0.0})
        notobject = json.loads(gate.badge_payload().decode())
        check("a non-object state is a refusal", notobject.get("read") is False and "object" in notobject.get("error", ""))

        (state / "latest.json").unlink()
        gate._BADGE_CACHE.update({"key": None, "body": b"", "at": 0.0})
        missing = json.loads(gate.badge_payload().decode())
        check("a missing state file is a refusal", missing.get("read") is False and "cannot read" in missing.get("error", ""))
        check("a refusal carries no checks list, so the badge cannot mistake it for data",
              "checks" not in missing)

        # ---- the read cache ----------------------------------------------------------
        (state / "latest.json").write_text(json.dumps(real), encoding="utf-8")
        gate._BADGE_CACHE.update({"key": None, "body": b"", "at": 0.0})
        first = gate.badge_payload()
        # Delete it, but keep the clock inside the cache window: the cached reading must still be
        # served, which is what proves the cache is doing anything at all.
        (state / "latest.json").unlink()
        second = gate.badge_payload()
        check("a fresh read is served from cache", second == first,
              f"cached_key={gate._BADGE_CACHE.get('key')} first={len(first)}B second={len(second)}B")
        check("a cached read is a complete payload, not a fragment",
              json.loads(first.decode()).get("read") is True)
        # Changing the file must be seen immediately, cache or no cache: the key carries mtime+size.
        gate._BADGE_CACHE_SECONDS = 3600.0
        (state / "latest.json").write_text(json.dumps({**real, "summary": {**real["summary"], "attention": 9}}), encoding="utf-8")
        changed = json.loads(gate.badge_payload().decode())
        check("a changed file is never served from cache", changed.get("attention") == 9)
        gate._BADGE_CACHE_SECONDS = 0.05
        gate._BADGE_CACHE["at"] = 0.0
        time.sleep(0.1)
        expired = json.loads(gate.badge_payload().decode())
        check("an expired cache re-reads", expired.get("read") is True)
        gate._BADGE_CACHE_SECONDS = 5.0

        # ---- a state file whose parts are the wrong type -----------------------------
        # A document whose summary and findings are the wrong types is NOT a reading. This is the
        # defect the audit found: it used to return read:true with null counts and an empty checks
        # list, the browser turned null into 0, and the pill announced "nothing needs attention"
        # about a file it had not understood.
        (state / "latest.json").write_text(json.dumps({
            "at": "2026-09-14T06:00:00+00:00", "summary": "not a dict", "findings": "not a list",
        }), encoding="utf-8")
        weird = json.loads(gate.badge_payload().decode())
        check("a wrong-typed summary is a refusal, not a green zero", weird.get("read") is False)
        check("a wrong-typed summary refusal names the types it got",
              "summary=str" in weird.get("error", "") and "findings=str" in weird.get("error", ""))
        check("a wrong-typed summary refusal carries no checks list", "checks" not in weird)

        (state / "latest.json").write_text(json.dumps({
            "at": "2026-09-14T06:00:00+00:00", "summary": {"total": 2, "ok": 1, "attention": 1},
            "findings": ["a string, not an object", {"check": "delivery", "severity": "critical", "needs_attention": True}],
        }), encoding="utf-8")
        mixed = json.loads(gate.badge_payload().decode())
        check("a well-formed document with one bad finding is still a reading", mixed.get("read") is True)
        check("non-object findings are dropped, not rendered", len(mixed.get("checks", [])) == 1)
        check("dropped findings are counted out loud", mixed.get("dropped") == 1)

        # ---- the kill switch ----------------------------------------------------------
        (state / "latest.json").write_text(json.dumps(real), encoding="utf-8")
        os.environ["PHONE_ATTENTION_BADGE"] = "0"
        off = json.loads(gate.badge_payload().decode())
        os.environ.pop("PHONE_ATTENTION_BADGE", None)
        check("the kill switch produces a refusal", off.get("read") is False and "switched off" in off.get("error", ""))

        # ---- CORS: only a loopback harness is allowed to read this ---------------------
        allowed = [
            "http://127.0.0.1:3099", "http://localhost:3099", "http://localhost",
            "http://127.0.0.1:1", "http://[::1]:3099",
        ]
        refused = [
            "", "*", "null", "https://evil.example", "http://evil.example",
            "http://localhost.evil.example", "http://127.0.0.1.evil.example:80",
            "https://127.0.0.1:3099", "ftp://localhost",
        ]
        check("loopback origins are allowed", all(gate.badge_allowed_origin(o) == o for o in allowed))
        check("every other origin gets no CORS", all(gate.badge_allowed_origin(o) == "" for o in refused))

        (state / "latest.json").write_text(json.dumps(real), encoding="utf-8")
        same_origin = head_of(gate.badge_json_response(origin=""))
        local = head_of(gate.badge_json_response(origin="http://127.0.0.1:3099"))
        hostile = head_of(gate.badge_json_response(origin="https://evil.example"))
        check("a same-origin read gets no Allow-Origin", "Access-Control-Allow-Origin" not in same_origin)
        check("a loopback read is echoed", "Access-Control-Allow-Origin: http://127.0.0.1:3099" in local)
        check("a loopback read varies on Origin", "Vary: Origin" in local)
        check("no credentials are ever allowed", "Allow-Credentials" not in local and "Allow-Credentials" not in hostile)
        check("a hostile origin gets no CORS headers", "Access-Control-Allow-Origin" not in hostile)
        check("every response is no-store", "no-store" in local and "no-store" in hostile and "no-store" in same_origin)
        check("the body is unchanged by CORS decisions",
              body_of(gate.badge_json_response(origin="")) == body_of(gate.badge_json_response(origin="https://evil.example")))

        # ---- the script route ---------------------------------------------------------
        script_response = gate.badge_script_response()
        check("the script route answers 200", script_response.startswith(b"HTTP/1.1 200 OK"))
        check("the script route is javascript", b"application/javascript" in head_of(script_response).encode())
        check("the script route serves the real file", b"__dshAttentionBadge" in body_of(script_response))
        check("the script route is no-store", b"no-store" in script_response)

        # ---- the injected tag ---------------------------------------------------------
        tag = gate.badge_script_tag(available=True).decode()
        check("the injected tag is deferred", "defer" in tag)
        check("the injected tag declares the loader id", 'id="dsh-attention-badge-loader"' in tag)
        check("the injected tag declares an empty data origin for the phone", 'data-attention-json=""' in tag)
        check("a missing badge file means no tag", gate.badge_script_tag(available=False) == b"")

        doc = b"<html><head><title>t</title></head><body>x</body></html>"
        once = gate.inject_all(doc)
        check("the badge is injected into a document", b"dsh-attention-badge-loader" in once)
        check("the phone layer is injected too", b"dsh-phone-mobile" in once)
        check("injection is idempotent", gate.inject_all(once) == once)
        check("a document with no head is left alone",
              gate.inject_all(b"<html><body>x</body></html>") == b"<html><body>x</body></html>")

    if "--json" in sys.argv:
        print(json.dumps(RESULTS))
    else:
        failed = 0
        for name, ok in RESULTS.items():
            if not ok:
                failed += 1
            detail = DETAILS.get(name, "")
            print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
        print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
