#!/usr/bin/env python3
"""Send one SMS from the AI line. Body from a file, so quoting is never the problem.

    python3 send-from-ai-line.py --to +18482102477 --body-file /tmp/body.txt
    python3 send-from-ai-line.py --to +18482102477 --body-file /tmp/body.txt --send

Default is a dry run. Everything sent from this line is signed Daniel - that is
the owner's standing rule (journal L1976). This script does NOT add the
signature; put it in the body so what you review is what gets sent.
"""
import argparse
import base64
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sms_inbox", str(Path(__file__).resolve().parent / "sms-inbox.py"))
inbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inbox)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--to", required=True)
    p.add_argument("--body-file", required=True)
    p.add_argument("--send", action="store_true")
    p.add_argument("--reason", default="manual send")
    a = p.parse_args()

    body = Path(a.body_file).read_text(encoding="utf-8").strip()
    if not body:
        sys.exit("empty body - refusing to send")
    if not body.endswith("- Daniel"):
        print("WARNING: this message is not signed '- Daniel' (owner's standing rule)")

    cfg = inbox.env()
    frm = cfg.get("TWILIO_PHONE_NUMBER") or inbox.AI_LINE_DEFAULT
    print(f"to   : {a.to}")
    print(f"from : {frm}")
    print(f"body :\n{body}\n")
    if not a.send:
        print("DRY RUN - nothing sent (pass --send)")
        return 0

    sid_acct, tok = cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"]
    data = urllib.parse.urlencode({"From": frm, "To": a.to, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid_acct}/Messages.json",
        data=data, method="POST")
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{sid_acct}:{tok}".encode()).decode())
    res = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    sid = str(res.get("sid"))
    print(f"SENT {sid} status={res.get('status')}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = inbox.connect()
    conn.execute(
        """INSERT OR REPLACE INTO messages
           (sid, direction, from_number, to_number, body, date_sent, status,
            first_seen, app_has_it, state, decided_by, decided_at, reason)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, "outbound", frm, a.to, body, now, res.get("status"), now, None,
         "answered", "zabz", now, a.reason))
    conn.commit()
    print("recorded in the inbox store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
