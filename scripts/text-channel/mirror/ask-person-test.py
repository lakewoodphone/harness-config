#!/usr/bin/env python3
"""ask-person-test -- the guarantees that stop a directed question leaving on the
family chat hub, re-proven on the live gate.

WHY THIS EXISTS (incident 2026-10-18, `sms_log` 4284)
    The CFO asked the owner's wife about an Audible charge and the message left from
    the FAMILY CHAT hub (+17328009174), so it landed in her family thread and she
    could not answer it privately. Nothing in the system objected, because no rule
    and no door said "a directed question belongs on the AI line".

WHAT IS PROVEN HERE (no message is transmitted)
    1. the AI line is +17324447361 (`TWILIO_PHONE_NUMBER`) and is NOT the hub.
    2. the allowlist opens the gate for her even though her ledger is `allow=queue`.
    3. the allowlist does NOT open the gate for anyone else -- a brother at
       `allow=auto`, a family line at `allow=auto`, and a stranger are all still
       refused. This is the difference between a named list and a global widen.
    4. `ask-person.py` REFUSES the hub number, by name, before any network call.
    5. `ask-person.py` REFUSES the owner, whose path is owner-ask/cfo-ask.
    6. a dry run for her resolves ok with no sid.

Exit 0 = every guarantee holds. Exit 5 = a guarantee is broken (which one is printed).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

BIN = Path("/root/bin")
sys.path.insert(0, str(BIN))
import textsend  # noqa: E402

HERS = "+18482245096"
HUB = "+17328009174"
OWNER = "+18483897895"
OTHERS = ["+18485257897", "+17326747491", "+15551234567"]

failures = []


def check(label, ok, detail=""):
    print("  %-58s %s%s" % (label, "PASS" if ok else "FAIL",
                            ("  <- " + detail) if (detail and not ok) else ""))
    if not ok:
        failures.append(label)


def run_cli(to):
    body = "Test body for the door, never transmitted.\n\n- Daniel\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(body)
        path = fh.name
    try:
        p = subprocess.run(
            [sys.executable, str(BIN / "ask-person.py"),
             "--to", to, "--body-file", path],
            capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    finally:
        os.unlink(path)


def main() -> int:
    cfg = textsend._config(None)

    print("1. the line")
    sender = textsend.sender_number(cfg)
    check("sender is the AI line " + str(sender), sender == "+17324447361", sender)
    check("sender is not the family hub", sender != HUB, sender)
    check("hub is configured and differs", str(cfg.get("FAMILY_CHAT_HUB_NUMBER")) == HUB,
          str(cfg.get("FAMILY_CHAT_HUB_NUMBER")))

    print("2. the allowlist opens it for her")
    allowed, why = textsend.can_send_to(HERS, {"allow": "queue"}, cfg)
    check("her ledger is queue yet the gate is open", allowed, why)

    print("3. and for nobody else")
    for other in OTHERS:
        ok, why2 = textsend.can_send_to(other, {"allow": "auto"}, cfg)
        check("still refused: %s" % other, not ok, why2)

    print("4. the hub is refused by name")
    rc, out = run_cli(HUB)
    check("hub -> exit 1", rc == 1, "rc=%s" % rc)
    check("hub -> names the refusal", "FAMILY CHAT hub" in out or "FAMILY CHAT" in out,
          out[:200])

    print("5. the owner is refused")
    rc, out = run_cli(OWNER)
    check("owner -> exit 1", rc == 1, "rc=%s" % rc)
    check("owner -> points at the owner path", "owner-ask" in out, out[:200])

    print("6. a dry run for her resolves cleanly and transmits nothing")
    rc, out = run_cli(HERS)
    check("her -> exit 0", rc == 0, out[:300])
    check("her -> ok True", "ok       True" in out, out[:300])
    check("her -> no sid", "(none)" in out, out[:300])

    print()
    if failures:
        print("BROKEN (%d): %s" % (len(failures), "; ".join(failures)))
        return 5
    print("ALL GUARANTEES HOLD")
    return 0


if __name__ == "__main__":
    sys.exit(main())