#!/usr/bin/env python3
"""Acceptance test for the production owner-attention pager.

Runs against a module file, sends NOTHING, and writes only a temp state file.
The fixture is the real 2026-10-19 digest and the real item that was sent as a
79-character fragment.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
from pathlib import Path

MOD = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/personal-secretary-mvp/scripts/owner_attention.py")
ART = Path("/root/personal-secretary-mvp/data/owner-attention/2026-10-19-1412.txt")


def load(path: Path):
    spec = importlib.util.spec_from_file_location("oa_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    m = load(MOD)
    text = ART.read_text(encoding="utf-8")
    raw = next(l for l in text.split("\n") if "The parent notice is live" in l)
    rendered = m._render_item(raw)
    key = m.pick_one_item([raw], {})
    assert key == rendered, (key, rendered)

    body, picked = m.compose_sms_body(text, {})
    assert picked == rendered, (picked, rendered)
    assert m.item_fingerprint(picked) == m.item_fingerprint(rendered)
    assert len(body) <= m.OWNER_SMS_MAX, len(body)
    assert "?" in body, body
    assert "Reply with your answer" in body, body
    assert "items," not in body and "urgent" not in body, body
    assert "data/owner-attention" not in body, body
    assert body.rstrip()[-1] not in " ,;:-", body
    assert "sign it?" in body, body
    print(f"PASS one complete question: {len(body)} chars, key={picked[:40]!r}")

    # The exact defect: the 79-char preview must not be what he receives.
    assert body != rendered
    assert not body.startswith("- "), body
    print("PASS the body is the full question, not the 79-char preview")

    # No-repeat: after recording the item, the next call must pick a different one.
    state = {m.item_fingerprint(rendered): "2026-10-19T14:12:23+00:00"}
    body2, picked2 = m.compose_sms_body(text, state)
    assert picked2 and picked2 != picked, (picked2, picked)
    print(f"PASS no-repeat: next item key={picked2[:40]!r}")

    # send() must record the PICKED key, not the composed body, or the state
    # would never match pick_one_item and the same item would repeat daily.
    with tempfile.TemporaryDirectory() as td:
        m._SENT_STATE = Path(td) / "sent-items.json"
        m.destination = lambda: "+18483897895"
        app = types.ModuleType("app")
        app.__path__ = []
        tf = types.ModuleType("app.tool_factory")
        tf.send_owner_update = lambda body, **kw: {"ok": True}
        app.tool_factory = tf
        sys.modules["app"] = app
        sys.modules["app.tool_factory"] = tf
        with contextlib.redirect_stdout(io.StringIO()):
            rc = m.send(text, dry_run=False, urgency="urgent")
        assert rc == 0, rc
        saved = json.loads(m._SENT_STATE.read_text(encoding="utf-8"))
        assert m.item_fingerprint(rendered) in saved, saved
        assert m.item_fingerprint(body) not in saved, saved
    print("PASS send() records the item key, not the body (fake sender; no SMS)")

    # A pathological 1000-character item must still stay a bounded text.
    long_body = m._compose_one("  1. [high] " + ("word " * 200))
    assert len(long_body) <= m.OWNER_SMS_MAX, len(long_body)
    assert "Reply with your answer" in long_body
    print(f"PASS long item bounded: {len(long_body)} chars")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
