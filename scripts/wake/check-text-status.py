#!/usr/bin/env python3
"""Did the text I sent actually deliver? Ask the provider, using the same credentials the sender uses.

WHY THIS IS NEEDED: the store row still says `queued` 25 minutes after the send, and `textsend.py` exposes no
way to check a message's fate (measured: its status-ish functions are `[]`). So there is no way - from the
system - to answer "did that text reach him?". That is a real hole in a channel whose entire purpose is
reaching him: a send returns `ok=True sid=...` and then nobody ever learns whether a human saw it.

This queries Twilio's own API for the sid. Read-only: it makes no calls, sends nothing, changes nothing.

Usage: python3 check-text-status.py <sid> [<sid> ...]
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILES = [
    Path.home() / "personal-secretary-mvp" / ".env",
    Path.home() / ".sms-inbox" / ".env",
]


def load_env() -> dict:
    vals = dict(os.environ)
    for p in ENV_FILES:
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            continue
    return vals


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check-text-status.py <sid> [<sid> ...]")
        return 2
    env = load_env()
    sid_acct = env.get("TWILIO_ACCOUNT_SID", "")
    token = env.get("TWILIO_AUTH_TOKEN", "")
    if not sid_acct or not token:
        print("no Twilio credentials found in the env or the usual .env files")
        print("  looked for TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN in: %s"
              % ", ".join(str(p) for p in ENV_FILES))
        return 3
    print("account: %s...%s" % (sid_acct[:6], sid_acct[-4:]))
    auth = base64.b64encode(("%s:%s" % (sid_acct, token)).encode()).decode()
    for msg_sid in sys.argv[1:]:
        url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/%s.json" % (sid_acct, msg_sid)
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            print("\n  sid     : %s" % d.get("sid"))
            print("  status  : %s" % d.get("status"))
            print("  to      : %s" % d.get("to"))
            print("  from    : %s" % d.get("from"))
            print("  sent at : %s" % d.get("date_sent"))
            print("  error   : %s" % (d.get("error_message") or "none"))
            print("  price   : %s %s" % (d.get("price"), d.get("price_unit")))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            print("\n  sid %s -> HTTP %s: %s" % (msg_sid, exc.code, body))
        except Exception as exc:
            print("\n  sid %s -> %s: %s" % (msg_sid, type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
