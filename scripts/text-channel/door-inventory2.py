#!/usr/bin/env python3
"""door-inventory2.py - the real bypasses are the DIRECT transports, not the shared choke point.

`sms_service.send_message` is the app's declared choke point and it calls the relay, so any file
that calls `send_message`/`send_owner_update` inherits all three guards without naming the relay. A
first pass that looked for the word "relay" in the file reported 33 "unguarded" files and was
measuring the wrong thing.

The true bypass is a DIRECT transport call - a Twilio messages.create, a dialpad_send_sms_direct, a
raw requests.post to the provider - which never touches the choke point at all. Those are the files
where the guards may not apply, and they are the only ones worth examining.
"""
import re
from pathlib import Path

DIRECT = re.compile(
    r"(\.messages\.create|dialpad_send_sms_direct|api\.twilio\.com|"
    r"dialpad\.com/api|requests\.(post|put)\s*\([^)]*sms|client\.messages\.create)")
SHARED = re.compile(r"\b(send_message|send_owner_update|send_and_record)\s*\(")
RELAY = re.compile(r"owner_text_relay|\brelay\.submit\b|owner_text\.gate|classify_owner_body")

roots = ["/root/bin", "/opt/company/app", "/opt/company/scripts"]
direct_files, shared_files = [], []
for root in roots:
    for path in Path(root).rglob("*.py"):
        if ".bak" in path.name or "__pycache__" in str(path):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            continue
        d = len(DIRECT.findall(src))
        s = len(SHARED.findall(src))
        if d:
            direct_files.append((str(path), d, s, bool(RELAY.search(src))))
        elif s:
            shared_files.append(str(path))

print("== DIRECT transport callers - these never touch the app choke point")
print("   %-62s %8s %7s %s" % ("file", "direct", "shared", "names relay"))
for path, d, s, r in sorted(direct_files, key=lambda x: -x[1]):
    print("   %-62s %8d %7d %s"
          % (path.replace("/opt/company/", "").replace("/root/bin/", "bin/"), d, s,
             "yes" if r else "NO"))
print()
print("   %d direct-transport file(s); %d of them never name the relay"
      % (len(direct_files), sum(1 for x in direct_files if not x[3])))
print()
print("== files using the shared choke point only: %d (all inherit the relay)" % len(shared_files))
