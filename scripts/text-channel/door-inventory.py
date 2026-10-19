#!/usr/bin/env python3
"""door-inventory.py - every path that can put a text on the owner's phone, and whether the
guards apply to it.

The three content guards live in `owner_text_relay.submit()`. A door that reaches the phone WITHOUT
passing through submit() is a door where quiet hours, credential_request and internal_prose do not
apply - and every individual guard test would still pass.

Two halves, both needed:
  1. every caller of the send functions, and whether the file mentions the relay;
  2. every subsystem the relay will NOT guard, declared in code, printed with the reason.

A STATIC check on purpose: sending a probe text to a real phone is the expensive way to learn this.
"""
import re
import subprocess
import sys
from pathlib import Path

SEARCH_ROOTS = ["/root/bin", "/opt/company/app", "/opt/company/scripts"]
#: The transport entry points. A file that calls one of these can put a text on a phone.
ENTRY = re.compile(
    r"\b(send_message|send_owner_update|send_from_ai_line|twilio_send|dialpad_send_sms_direct|"
    r"textsend\s+send|\.messages\.create|log_sms_best_effort|send_and_record)\b")
RELAY = re.compile(r"owner_text_relay|\brelay\.submit\b|owner_text\.gate|classify_owner_body")

rows = []
for root in SEARCH_ROOTS:
    for path in Path(root).rglob("*.py"):
        if ".bak" in path.name or "__pycache__" in str(path):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            continue
        if not ENTRY.search(src):
            continue
        rows.append((str(path), bool(RELAY.search(src)),
                     len(ENTRY.findall(src))))

rows.sort(key=lambda r: (r[1], -r[2]))
print("files that can put a text on a phone: %d" % len(rows))
guarded = [r for r in rows if r[1]]
unguarded = [r for r in rows if not r[1]]
print("  mention the relay / the app gate : %d" % len(guarded))
print("  DO NOT                          : %d" % len(unguarded))
print()
print("== files that reach a transport and never name the relay:")
for path, _g, n in unguarded:
    print("   %-64s %d transport call(s)" % (path.replace("/opt/company/", ""), n))

print()
print("== the relay's own declared exemptions, read from the code:")
sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402
for name in ("DEDUPE_EXEMPT_SUBSYSTEMS", "INTERRUPTING_URGENCIES", "REPLY_CLASS",
             "INBOUND_DOORS"):
    print("   %-28s %r" % (name, getattr(R, name, "absent")))
print()
print("== the guard switch state (an env var can turn any of the three off)")
for env in ("OWNER_TEXT_GUARD_QUIET", "OWNER_TEXT_GUARD_CREDENTIAL",
            "OWNER_TEXT_GUARD_INTERNAL", "OWNER_TEXT_RELAY_OFF"):
    import os
    print("   %-30s %r" % (env, os.environ.get(env)))
