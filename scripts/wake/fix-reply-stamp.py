#!/usr/bin/env python3
"""Fix the anti-spam stamp, which was calling `defer` without its REQUIRED --until and failing silently.

THE FINDING, measured 2026-09-28 23:06:41Z. `_reply_with_top_question` stamps a question as asked with:

    _sp.run(["python3", queue, "defer", str(row.get("id")),
             "--note", "asked_by_text ... - put to him by SMS; awaiting his reply"],
            capture_output=True, ...)

But `owner-queue.py defer` REQUIRES `--until`:

    usage: owner-queue.py defer [-h] [--until UNTIL] [--note NOTE] [--clear] id

So the call exits with a usage error, `capture_output=True` swallows it, nothing is recorded, and the row
stays eligible. Measured: after running the stamp exactly as the function does, #164 is still `pending` with
no `asked_by_text` marker, and the selection logic picks **#164 again**.

THAT MEANS: had sending been restored as-is, THE OWNER WOULD HAVE RECEIVED THE SAME QUESTION ON EVERY TEXT HE
SENT. He has already complained about exactly this shape twice - "way too much information at once", "aren't
you even replying to someone" - and I sent him two duplicates by accident an hour ago. A reply path that
repeats itself is worse than one that stays silent.

IT IS ALSO THE SAME FAMILY AS EVERYTHING ELSE TONIGHT: the stamp "worked" in the sense that the code ran and
the function returned True. Nothing checked whether the stamp TOOK. A guard whose effect is never read is not
a guard - which is how I came to send two identical texts claiming I had not sent one.

WHY +7d: a question put to him by text should not be repeated within the week, but it must not be retired
either - if he never answers, it should come back. Seven days matches the recency window the SMS mirror uses
and is long enough that a repeat would only follow a genuine silence.

Usage: python3 fix-reply-stamp.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")
OLD = '''            _sp.run(["python3", queue, "defer", str(row.get("id")),
                     "--note", "asked_by_text %s - put to him by SMS; awaiting his reply"
                     % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")],
                    capture_output=True, text=True, timeout=60)'''
NEW = '''            # --until IS REQUIRED by `owner-queue.py defer`. Without it the call exits with a usage
            # error, `capture_output=True` swallows the message, nothing is recorded and the row stays
            # eligible - so the SAME question goes out again on his next text. Measured 2026-09-28: the
            # stamp silently failed and the selector picked #164 again. Seven days is long enough that a
            # repeat follows only a genuine silence, and short enough that an unanswered question returns.
            _stamp = _sp.run(["python3", queue, "defer", str(row.get("id")),
                              "--until", "+7d",
                              "--note", "asked_by_text %s - put to him by SMS; awaiting his reply"
                              % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")],
                             capture_output=True, text=True, timeout=60)
            # AND READ THE RESULT. A stamp whose effect is never checked is not a stamp: the identical
            # defect is what let a supposedly-intercepted test send the owner two duplicate texts.
            _err = (_stamp.stderr or "").strip()
            if _stamp.returncode != 0 or _err:
                print(f"    WARNING: the asked-stamp did NOT take (rc={_stamp.returncode}): "
                      f"{(_err or _stamp.stdout or '')[:160]}")
                print("    -> this question WILL repeat on his next text until it is stamped")
            else:
                print(f"    stamped #{row.get('id')} as asked (re-askable in 7 days)")'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "--until" in src and "_stamp = _sp.run" in src:
        print("already fixed")
        return 0
    if OLD not in src:
        print("ERROR: could not find the stamp call - refusing to guess")
        m = re.search(r'.*"defer".*', src)
        print("  what is there: %r" % (m.group(0)[:160] if m else "nothing"))
        return 1
    src = src.replace(OLD, NEW, 1)
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-stampfix-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup .bak-stampfix-%s)" % (p, stamp))
    print("\n=== PROOF: run the stamp as the function now does, and check it TOOK ===")
    r = subprocess.run(["python3", str(Path.home() / "bin" / "owner-queue.py"), "defer", "164",
                        "--until", "+7d",
                        "--note", "asked_by_text %s - put to him by SMS; awaiting his reply"
                        % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")],
                       capture_output=True, text=True, timeout=60)
    print("  rc=%s  out=%r  err=%r" % (r.returncode, r.stdout.strip()[:120], r.stderr.strip()[:120]))
    import json
    q = subprocess.run(["python3", str(Path.home() / "bin" / "owner-queue.py"), "list", "--json"],
                       capture_output=True, text=True, timeout=60).stdout
    rows = json.loads(q or "[]")
    rows = rows if isinstance(rows, list) else rows.get("rows") or []
    for row in rows:
        if str(row.get("id")) == "164":
            print("  #164 now: status=%s deferred_until=%s"
                  % (row.get("status"), row.get("deferred_until")))
            print("  %s" % ("THE STAMP TOOK" if (row.get("deferred_until") or row.get("status") != "pending")
                            else "THE STAMP STILL FAILED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
