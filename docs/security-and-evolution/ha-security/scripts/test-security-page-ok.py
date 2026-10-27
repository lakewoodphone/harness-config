#!/usr/bin/env python3
"""Prove that security-page `ok` reports the OWNER's send, without sending anything.

Why this exists (2026-10-27). `send_security_alert_mms` used to return
`ok = all(recipients)`. Home Assistant treats `ok == false` as a failed page and retries four
more times, twelve seconds apart -- so ONE refused number (a quota-blocked, opted-out or
mistyped family handset) made every retry re-send to the recipients who had already received
the page: up to five copies for them, and no honest signal about the one that failed.

The fix makes `ok` mean "the owner got it". This stubs the transport and varies who fails,
so the behaviour is proven rather than asserted, and no message leaves the building.

Run on the authority (it imports the deployed app):
  cd /opt/company && .venv/bin/python /root/test-security-page-ok.py

Expected output ends with: RESULT: PASS - ok reports the OWNER'S send
"""
from __future__ import annotations

import app.sms_service as S
from app.config import Settings
from app.services.owner_notifications import owner_notify_target


def main() -> int:
    settings = Settings()
    owner = str(owner_notify_target(settings) or "").strip()
    if not owner:
        print("SKIP: no owner target resolved, the case is meaningless")
        return 2
    extra = "+19990000001"
    real = S.send_message

    def run(owner_ok: bool, extra_ok: bool, label: str) -> dict:
        def fake(settings, to, **kwargs):  # noqa: ANN001, ARG001
            ok = owner_ok if to == owner else extra_ok
            return {"ok": ok, "error": None if ok else "stub refusal"}

        S.send_message = fake
        try:
            return S.send_security_alert_mms(
                body="selftest body", settings=settings, recipients=[extra])
        finally:
            S.send_message = real

    print("owner target resolved:", True, "| extra:", extra)
    print("cases (owner vs an extra recipient):")
    a = run(True, False, "owner OK, extra REFUSED")
    b = run(False, True, "owner REFUSED, extra OK")
    c = run(True, True, "both OK")
    for label, r in (("owner OK, extra REFUSED", a), ("owner REFUSED, extra OK", b),
                     ("both OK", c)):
        print("  %-26s ok=%-5s per-recipient=%s"
              % (label, r.get("ok"),
                 {k: v.get("ok") for k, v in (r.get("results") or {}).items()}))

    verdict = a.get("ok") is True and b.get("ok") is False and c.get("ok") is True
    print("RESULT:", "PASS - ok reports the OWNER'S send" if verdict
          else "FAIL - ok is still all(recipients)")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
