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
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sms_inbox", str(Path(__file__).resolve().parent / "sms-inbox.py"))
inbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inbox)


# --------------------------------------------------------------------------- #
# THE OWNER-TEXT RELAY. This file is a raw Twilio POST with no gate of any kind -
# it is where the 18-books duplicate came from - so it is given the one policy layer
# it can be given without retiring it. `/root/bin/owner_text_relay.py` is not a
# sibling of this file, so it is loaded by path.
#
# FAIL-SOFT, NEVER FAIL-SILENT: if the relay cannot be imported, the send proceeds
# exactly as it did before (this script must keep working if the relay is not
# deployed) and ONE line naming the failure goes to stderr.
# --------------------------------------------------------------------------- #
_RELAY = None                      # None = untried, False = unavailable, else the module
_RELAY_LOGGED = False


def _relay_log_once(message: str) -> None:
    global _RELAY_LOGGED
    if _RELAY_LOGGED:
        return
    _RELAY_LOGGED = True
    try:
        print("send-from-ai-line: owner_text_relay %s - sending WITHOUT the relay "
              "(fail-soft, not fail-silent)" % message, file=sys.stderr)
    except Exception:
        pass


def _relay_module():
    """The relay module, or None. Imported once; a failure is logged once."""
    global _RELAY
    if _RELAY is False:
        return None
    if _RELAY is None:
        mod = None
        err = ""
        try:
            import owner_text_relay as mod
        except Exception as exc:
            err = "%s: %s" % (type(exc).__name__, exc)
        if mod is None:
            for candidate in (Path(__file__).resolve().parent / "owner_text_relay.py",
                              Path("/root/bin/owner_text_relay.py")):
                if not candidate.exists():
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(
                        "owner_text_relay", str(candidate))
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["owner_text_relay"] = mod
                    spec.loader.exec_module(mod)
                    break
                except Exception as exc:
                    err = "%s: %s" % (type(exc).__name__, exc)
                    mod = None
        if mod is None:
            _RELAY = False
            sys.modules.pop("owner_text_relay", None)
            _relay_log_once("unavailable (%s)" % (err or "not importable"))
            return None
        _RELAY = mod
    return _RELAY


def _relay_ref(body) -> str:
    """The `ask-<n>` / `q<n>` token a caller put in the body, if there is one."""
    for pattern in (r"\[(ask-\d+)\]", r"#(ask-\d+)\b", r"\b(ask-\d{6,})\b", r"\[(q\d+)\]"):
        found = re.search(pattern, str(body or ""), re.I)
        if found:
            return found.group(1).lower()
    return ""


def _relay_gate(body, reason):
    """Ask the relay before this raw POST. Returns `(refusal, attempt_id)`.

    `(None, attempt_id)` means "post it". A refusal is a dict for stderr; nothing is
    posted when it is returned, and the script exits 1.
    """
    mod = _relay_module()
    if mod is None:
        return None, None
    try:
        verdict = mod.submit(
            door="send-from-ai-line",
            subsystem=str(reason or ""),
            body=body,
            reason=str(reason or ""),
            urgency="normal",
            ref=_relay_ref(body) or None,
            opens_ask=bool(re.search(r"[?\uFF1F]", str(body or ""))),
        )
    except Exception as exc:
        _relay_log_once("submit failed (%s: %s)" % (type(exc).__name__, exc))
        return None, None
    if not isinstance(verdict, dict):
        _relay_log_once("submit returned %r, not a verdict dict" % (verdict,))
        return None, None
    if str(verdict.get("verdict") or "").upper() == "SEND":
        return None, verdict.get("attempt_id")
    return {"verdict": str(verdict.get("verdict") or "SUPPRESS"),
            "reason": str(verdict.get("reason") or "-"),
            "detail": str(verdict.get("detail") or "")}, None


def _relay_record_sent(attempt_id, *, sid: str = "", status: str = "sent", body=None) -> bool:
    """Never raises: this script's job is to send, not to keep the ledger."""
    mod = _relay_module()
    if mod is None or attempt_id is None:
        return False
    try:
        mod.record_sent(attempt_id, sid=str(sid or ""), status=str(status or "sent"), body=body)
        return True
    except Exception as exc:
        _relay_log_once("record_sent failed (%s: %s)" % (type(exc).__name__, exc))
        return False


def _relay_record_failed(attempt_id, *, error: str = "", status: str = "failed") -> bool:
    mod = _relay_module()
    if mod is None or attempt_id is None:
        return False
    try:
        mod.record_failed(attempt_id, error=str(error or ""), status=str(status or "failed"))
        return True
    except Exception as exc:
        _relay_log_once("record_failed failed (%s: %s)" % (type(exc).__name__, exc))
        return False


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
    # ── THE OWNER-TEXT RELAY, before the POST ────────────────────────────────
    # Below the dry-run return on purpose: a dry run must not write an attempt row and
    # must not wake the relay at all. On anything but SEND nothing is posted.
    _refusal, _attempt_id = _relay_gate(body, a.reason)
    if _refusal is not None:
        print("REFUSED by the owner-text relay: %s (%s): %s"
              % (_refusal["verdict"], _refusal["reason"], _refusal["detail"]),
              file=sys.stderr)
        return 1

    sid_acct, tok = cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"]
    data = urllib.parse.urlencode({"From": frm, "To": a.to, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid_acct}/Messages.json",
        data=data, method="POST")
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{sid_acct}:{tok}".encode()).decode())
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    except Exception as exc:
        # The outcome goes to the relay BEFORE the traceback goes to the operator:
        # a POST that failed is exactly what the relay's retry cap counts.
        _relay_record_failed(_attempt_id, error="%s: %s" % (type(exc).__name__, exc))
        raise
    sid = str(res.get("sid"))
    print(f"SENT {sid} status={res.get('status')}")
    _relay_record_sent(_attempt_id, sid=sid, status=str(res.get("status") or "sent"), body=body)

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
