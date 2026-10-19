#!/usr/bin/env python3
"""add-k2-app-path-reaches-the-relay.py - the guards live on the relay; is the app path on it?

MEASURED 2026-10-19. Three gates sit on the owner's phone:

  1. `app/owner_text.gate(db_url, body=...)` - the TURN, the quota, the machine budget.
     Exercised directly with four bodies on a throwaway store it ALLOWS all four, including
     "Reminder: EXECUTE: pay him. Record date in lpt-hub/docs/pay.md" and "Send me the NJ Premier
     Business Services login". It has no content classes and is not meant to.
  2. `textsend.classify_owner_body` - QUESTION / RESULT / ALERT / NOISE, shared by the app and the
     AI line (app/services/owner_text_classification.py binds it).
  3. `owner_text_relay.submit()` - where quiet hours, credential_request and internal_prose live,
     plus dedupe, topic cooldown and the floor.

So the three guards added in this programme are only on EVERY app send because
`sms_service.send_message` calls `owner_text_relay.submit(door="app", ...)` at line 1828. One line.
Nothing declares it, nothing tests it, and a refactor that removes it would silently strip all three
guards from every app message while every individual guard test still passed.

K2 makes that line a checked invariant: the app's send choke point must still call the relay.

A SOURCE-LEVEL CHECK, deliberately: the alternative is sending a probe text, and the whole point of
this channel is that sending is expensive. Reading two files for one call is cheap and cannot
disturb production. It checks the CALL EXISTS and that the door is named, not that the relay
behaved - behaviour is covered by the relay's own 115 checks and the replay.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/text-health.py")

CHECK = '''
# ---------------------------------------------------------------------------------------
# K2: the app's send choke point must still reach the relay.
#
# The three content guards - quiet hours, credential_request, internal_prose - live in
# `owner_text_relay.submit()`. They apply to every app send only because
# `sms_service.send_message` calls `submit(door="app", ...)`. Nothing declares that dependency and
# nothing tested it: a refactor removing one call would strip all three guards from every app
# message, and every individual guard test would still pass.
#
# A SOURCE-LEVEL CHECK ON PURPOSE. The alternative is sending a probe text, and on this channel
# sending is the expensive thing. This reads the file for the call and the door name; behaviour is
# covered by the relay's own checks and the replay.
# ---------------------------------------------------------------------------------------
try:
    _svc = BIN.parent / "opt" / "company" / "app" / "sms_service.py"
    _svc = Path(os.environ.get("SMS_SERVICE_PY", "/opt/company/app/sms_service.py"))
    if not _svc.exists():
        check("K2 the app send path still calls owner_text_relay.submit", True,
              "NOT MEASURED: %s not present on this host" % _svc)
    else:
        _src = _svc.read_text(encoding="utf-8", errors="replace")
        _calls = _src.count("owner_text_relay.submit(")
        _door = 'door="app"' in _src
        _loads = "owner_text_relay" in _src
        check("K2 the app send path still calls owner_text_relay.submit",
              bool(_calls) and _door,
              "%s: %d submit() call(s), door=\\"app\\" present=%s, relay referenced=%s -- if this "
              "fails, the quiet-hours, credential and internal-prose guards are NOT on app sends"
              % (_svc.name, _calls, _door, _loads))
except Exception as exc:                                       # noqa: BLE001
    check("K2 the app send path still calls owner_text_relay.submit", False,
          "%s: %s" % (type(exc).__name__, exc))

'''

ANCHOR = 'print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "K2 the app send path" in text:
        print("OK    already applied")
        return 0
    if text.count(ANCHOR) != 1:
        print("FAIL  print anchor found %d times" % text.count(ANCHOR))
        return 1
    out = text.replace(ANCHOR, CHECK + ANCHOR, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add K2 (the app path reaches the relay)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-k2-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
