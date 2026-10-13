#!/usr/bin/env python3
"""verify-phone-icon.py — the gate's Home Screen icon, as machine-readable checks.

    python3 scripts/verify-phone-icon.py          human-readable, exit 1 on any failure
    python3 scripts/verify-phone-icon.py --json   {"check name": true|false, ...}

WHY IT IMPORTS THE REAL GATE
Same reason `verify-badge-gate.py` does: the checks call `phone-gate.py`'s own functions with
the module loaded from the file that ships. A test that re-implements the injection proves only
that the author can write the same bug twice.

WHAT IT IS FOR
A managed web clip takes its icon from the MDM payload's `Icon` key — but a clip the owner adds
from Safari by hand takes it from `<link rel="apple-touch-icon">` on the document, and before
this the served document carried none, so iOS used a screenshot instead. These checks pin the
three things that make that fix real: the tag is injected once, the PNG is served with the right
bytes and type, and the absence of either is reported rather than silently invented.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "phone-gate.py"
ICON = REPO / "assets" / "apple-touch-icon.png"

RESULTS: dict[str, bool] = {}
DETAILS: dict[str, str] = {}

PLAIN = (
    b"<!doctype html><html><head><meta charset=\"utf-8\"><title>DeepSeek Harness</title></head>"
    b"<body>hello</body></html>"
)


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS[name] = bool(ok)
    if detail:
        DETAILS[name] = detail


def load_gate():
    spec = importlib.util.spec_from_file_location("phone_gate_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def head_of(response: bytes) -> str:
    return response.split(b"\r\n\r\n", 1)[0].decode("latin-1")


def body_of(response: bytes) -> bytes:
    return response.split(b"\r\n\r\n", 1)[1]


def png_size(data: bytes) -> "tuple[int, int]":
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def env_without(name: str):
    """A context manager is overkill for one env var; this keeps the save/restore honest."""
    class _Ctx:
        def __enter__(self):
            self.saved = os.environ.pop(name, None)
            return self

        def __exit__(self, *exc):
            os.environ.pop(name, None)
            if self.saved is not None:
                os.environ[name] = self.saved
            return False
    return _Ctx()


def main() -> int:
    gate = load_gate()
    os.environ.pop("PHONE_TOUCH_ICON", None)
    os.environ.pop("PHONE_MOBILE_CSS", None)

    # --- the asset itself ---------------------------------------------------
    try:
        icon_bytes = ICON.read_bytes()
        w, h = png_size(icon_bytes)
        check("asset is a 180x180 PNG", (w, h) == (180, 180), f"{ICON.name} {w}x{h}")
        check("asset is under Apple's 1MB uncompressed limit",
              len(icon_bytes) < 1_000_000, f"{len(icon_bytes)} bytes")
        check("the gate resolves the asset it is given",
              gate.TOUCH_ICON.resolve() == ICON.resolve(), str(gate.TOUCH_ICON))
    except Exception as exc:  # noqa: BLE001 - a missing asset IS the failure being reported
        check("asset is a 180x180 PNG", False, f"{type(exc).__name__}: {exc}")
        check("asset is under Apple's 1MB uncompressed limit", False, str(exc))
        check("the gate resolves the asset it is given", False, str(exc))
        icon_bytes = b""

    # --- injection into a document -----------------------------------------
    once = gate.inject_mobile(PLAIN)
    twice = gate.inject_mobile(once)
    check("the icon link is injected once",
          once.count(b'rel="apple-touch-icon"') == 1,
          f"{once.count(b'rel=\"apple-touch-icon\"')} occurrence(s)")
    check("the icon link is injected before </head>",
          once.lower().find(b'rel="apple-touch-icon"') < once.lower().find(b"</head>"))
    check("the phone layer is still injected",
          b'id="dsh-phone-mobile"' in once)
    check("a second pass is byte-identical", once == twice,
          f"{len(once)} -> {len(twice)} bytes")

    mine = (b'<!doctype html><html><head>'
            b'<link rel="apple-touch-icon" href="/mine.png"></head><body>x</body></html>')
    kept = gate.inject_mobile(mine)
    check("a document that names its own icon keeps exactly one",
          kept.count(b"apple-touch-icon") == 1, f"{kept.count(b'apple-touch-icon')} occurrence(s)")
    check("...and keeps ITS icon, not ours", b"/mine.png" in kept)

    no_head = b"<html><body>no head here</body></html>"
    check("a document with no </head> is returned unchanged", gate.inject_mobile(no_head) == no_head)

    # --- the response -------------------------------------------------------
    response = gate.touch_icon_response()
    check("the icon is served 200", b"200 OK" in response.split(b"\r\n", 1)[0],
          head_of(response).splitlines()[0] if response else "(empty)")
    check("the icon is served as image/png", "Content-Type: image/png" in head_of(response))
    check("the icon is served no-store", "Cache-Control: no-store" in head_of(response))
    check("the served bytes ARE the asset", body_of(response) == icon_bytes,
          f"{len(body_of(response))} bytes")
    declared = [ln for ln in head_of(response).splitlines() if ln.lower().startswith("content-length")]
    check("Content-Length matches the body",
          bool(declared) and declared[0].split(":")[1].strip() == str(len(icon_bytes)),
          declared[0] if declared else "no Content-Length")

    # --- the two absence paths, because an empty result is not health -------
    real = gate.TOUCH_ICON
    missing = Path(tempfile.mkdtemp()) / "nope.png"
    gate.TOUCH_ICON = missing
    try:
        absent = gate.touch_icon_response()
        check("a missing icon file answers 404, not an empty 200",
              absent.split(b"\r\n", 1)[0].endswith(b"404 Not Found"),
              absent.split(b"\r\n", 1)[0].decode("latin-1"))
        check("a missing icon file injects no link",
              b"apple-touch-icon" not in gate.inject_mobile(PLAIN))
        check("...and the layer still injects without it",
              b'id="dsh-phone-mobile"' in gate.inject_mobile(PLAIN))
        check("the layer report names the icon as missing",
              f"{missing.name}=missing" in gate.layer_report(), gate.layer_report())

        os.environ["PHONE_TOUCH_ICON"] = "0"
        check("PHONE_TOUCH_ICON=0 switches the link off",
              b"apple-touch-icon" not in gate.inject_mobile(PLAIN))
        check("PHONE_TOUCH_ICON=0 switches the route off",
              gate.touch_icon_response().split(b"\r\n", 1)[0].endswith(b"404 Not Found"))
        check("PHONE_TOUCH_ICON=0 does NOT switch the layer off",
              b'id="dsh-phone-mobile"' in gate.inject_mobile(PLAIN))
        del os.environ["PHONE_TOUCH_ICON"]
    finally:
        gate.TOUCH_ICON = real

    check("with the icon present the layer report names its size",
          f"apple-touch-icon.png={len(icon_bytes)}B" in gate.layer_report(),
          gate.layer_report())

    for name, ok in RESULTS.items():
        mark = "PASS" if ok else "FAIL"
        extra = f"  ({DETAILS[name]})" if not ok and name in DETAILS else ""
        print(f"  [{mark}] {name}{extra}")
    failed = [n for n, ok in RESULTS.items() if not ok]
    print(f"\n  {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        main()
        print(json.dumps(RESULTS))
        sys.exit(0 if all(RESULTS.values()) else 1)
    sys.exit(main())
