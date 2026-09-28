#!/usr/bin/env python3
"""Make an owner text ANSWER HIM: reply with the top unasked decision from his own queue.

THE PROBLEM, measured 2026-09-28 22:57Z. When the owner texts, `sms-responder.py` files a ledger item and
then does not reply, because the acknowledgement is gated on `AITEXT_ACK_OWNER_REQUESTS == "1"` and that is
unset. He noticed: "Are you sure you're even replying to someone?"

AND SIMPLY SWITCHING THE OLD ACK ON WOULD BE WRONG. It says "Got it - filed as housekeeping#76", which
tells him nothing he can act on - the kind of message he has called pointless twice. The real gap is
underneath: **24 owner decisions are pending, the oldest from 2026-09-16, and not one has ever been texted.**

SO THE REPLY SHOULD CARRY THE QUESTION. He said it himself at 22:43Z:
    "Text me the top question you have for me right now, but you can first think about it."

WHAT THIS DOES: when his text is handled and there is an UNASKED pending decision in the owner queue, the
reply is that decision's own question and recommendation - already written, already ranked, already carrying
a recommendation - and the row is stamped `asked_by_text` so it is never asked twice. That turns the one
moment we reliably have his attention into exactly one question, which is his stated preference
("ask me one at a time").

WHEN THERE IS NO UNASKED QUESTION it sends NOTHING. Not an acknowledgement, not a receipt - silence, because
a text that carries no question, no warning and no deadline is the thing he told us not to send.

IT REPLACES the old acknowledgement rather than adding to it, so there is never a "Got it + question" pair.
One message, one question.

SAFETY: it only ever sends to the owner's own number (the queue's rows are his by definition), it respects a
per-ask stamp so no question repeats, and any failure is caught and printed - a reply path must never break
the responder.

Usage: python3 wire-queue-replies.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")

NEW_FN = '''

def _reply_with_top_question(conn, phone: str) -> bool:
    """Reply to the owner with the TOP UNASKED decision from his own queue. True if something was sent.

    WHY THIS EXISTS, in his words: he texted "Text me the top question you have for me right now" and, before
    that, "Are you sure you're even replying to someone?" - while 24 decisions sat pending, the oldest from
    2026-09-16, and not one had ever been texted. The old acknowledgement said "Got it - filed as
    housekeeping#76", which is a message he has twice called pointless.

    SO THE REPLY CARRIES THE QUESTION. It is already written, already ranked, and already has a
    recommendation attached. Every owner text becomes one question and nothing else, which is his stated
    preference: "ask me one at a time".

    SILENCE WHEN THERE IS NOTHING TO ASK. A reply that carries no question, no warning and no deadline is
    the thing we were told not to send.
    """
    import json as _json
    import subprocess as _sp
    import os as _os
    queue = _os.environ.get("OWNER_QUEUE_CLI") or str(Path.home() / "bin" / "owner-queue.py")
    try:
        raw = _sp.run(["python3", queue, "list", "--json"], capture_output=True, text=True,
                      timeout=60).stdout
        rows = _json.loads(raw or "[]")
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("items") or []
    except Exception as exc:
        print(f"    queue read failed: {type(exc).__name__}: {exc}")
        return False

    # RANK BY DATED CONSEQUENCE, not by recency: a collector and a closing window outrank a fresh idea.
    SIGNALS = [("collector", 6), ("collections", 6), ("revoked", 6), ("revocation", 6), ("overdue", 5),
               ("no cover", 5), ("lapsed", 4), ("suspend", 5), ("past the", 4), ("deadline", 5),
               ("expires", 4), ("penalt", 4), ("owed", 3), ("final", 3)]
    cands = []
    for r in rows:
        if str(r.get("status")) != "pending":
            continue
        # NEVER ASK THE SAME QUESTION TWICE.
        if "asked_by_text" in (r.get("context") or "") or r.get("asked_at_text"):
            continue
        q = (r.get("question") or "")
        low = q.lower()
        score = sum(w for sig, w in SIGNALS if sig in low)
        if re.search(r"\\b\\d{2,}", q):
            score += 2
        if not q.strip():
            continue
        cands.append((score, -int(r.get("id") or 0), r))
    if not cands:
        print("    no unasked owner question - staying silent rather than sending a receipt")
        return False
    cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
    row = cands[0][2]

    question = " ".join((row.get("question") or "").split())
    rec = " ".join((row.get("recommendation") or "").split())
    body = question if not rec else f"{question} I recommend: {rec}"
    if len(body) > 300:
        body = body[:297].rstrip() + "..."

    try:
        import importlib.util as _il
        spec = _il.spec_from_file_location("textsend", str(Path.home() / "bin" / "textsend.py"))
        ts = _il.module_from_spec(spec)
        spec.loader.exec_module(ts)
        res = ts.send(phone, body, dry_run=False)
        print(f"    replied with queue #{row.get('id')}: {body[:70]}")
        # STAMP IT ASKED so it is never repeated, and record that the ask happened by text.
        try:
            _sp.run(["python3", queue, "defer", str(row.get("id")),
                     "--note", "asked_by_text %s - put to him by SMS; awaiting his reply"
                     % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")],
                    capture_output=True, text=True, timeout=60)
        except Exception as exc:
            print(f"    (asked, but could not stamp it as asked: {type(exc).__name__})")
        return True
    except Exception as exc:
        print(f"    reply failed: {type(exc).__name__}: {exc}")
        return False
'''

OLD_CALL = '''                if os.environ.get("AITEXT_ACK_OWNER_REQUESTS") == "1":
                    _ack_owner_request(r["from_number"], filed, body)
                continue'''

NEW_CALL = '''                # ANSWER HIM. The reply carries the top unasked decision from his own queue,
                # because he has twice called receipts pointless and 24 decisions sat pending with none
                # ever asked. Silence when there is nothing to ask. Replaces the old acknowledgement.
                _reply_with_top_question(conn, r["from_number"])
                continue'''

ANCHOR = "\ndef _ack_owner_request("


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "_reply_with_top_question" in src:
        print("already wired")
        return 0
    if ANCHOR not in src:
        print("ERROR: could not find the _ack_owner_request anchor")
        return 1
    if OLD_CALL not in src:
        print("ERROR: could not find the ack call site in cmd_run")
        m = re.search(r'.*_ack_owner_request\(r\["from_number"\].*', src)
        print("  what is there: %r" % (m.group(0)[:160] if m else "nothing"))
        return 1
    src = src.replace(ANCHOR, NEW_FN + ANCHOR, 1)
    print("1. added _reply_with_top_question")
    src = src.replace(OLD_CALL, NEW_CALL, 1)
    print("2. replaced the ack call with the queue reply")
    if "import re" not in src.split("\n\n")[0] and not re.search(r"^import re$", src, re.M):
        src = src.replace("import os", "import os\nimport re", 1)
        print("3. added the re import")
    else:
        print("3. re already imported")
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-queuereply-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup .bak-queuereply-%s)" % (p, stamp))
    out = __import__("subprocess").run(["python3", "-c",
        "import importlib.util,sys; s=importlib.util.spec_from_file_location('r','%s');"
        "m=importlib.util.module_from_spec(s); sys.modules['r']=m; s.loader.exec_module(m);"
        "print('  module imports OK; _reply_with_top_question present:', "
        "hasattr(m,'_reply_with_top_question'))" % p], capture_output=True, text=True, timeout=120)
    print(out.stdout.strip() or out.stderr.strip()[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
