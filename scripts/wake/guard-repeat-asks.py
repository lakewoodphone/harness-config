#!/usr/bin/env python3
"""Move the anti-repeat guard OUT of the locked owner queue and into a store this system owns.

THE FINDING, measured 2026-09-28 23:08Z:
  * `owner-queue.py defer` requires `--until`, and the reply code called it WITHOUT it - a usage error that
    `capture_output=True` swallowed, so nothing was ever stamped and the same question would repeat forever;
  * and fixing the argument is not enough, because the queue itself is WRITE-BLOCKED: owner_decision_queue
    lives inside the 13 GB `secretary.db`, and `uvicorn app.main:app` (pid 959335, ~53 open handles) holds the
    write lock. Measured now: reads `ok in 0.00s`, writes `database is locked after 8.05s`. Ledger item #54
    documents the same fault from 20:49Z and its own definition of done still fails.

SO THE GUARD CANNOT LIVE THERE. A guard that lives in a store which is write-blocked is a guard that does not
run - and this is the tenth time tonight that the defect was "the mechanism is real but cannot express
itself". The stamp must live somewhere this system owns and can always write.

WHAT THIS ADDS: `~/.sms-inbox/offered.db`, one table recording every question actually put to the owner by
text - id, when, and a hash of the body. `_reply_with_top_question` checks it before choosing, and writes it
after sending. It is SQLite in a store with no other writers, so the write is instant and cannot be blocked by
the app.

WHY A SEPARATE FILE AND NOT A COLUMN: the queue is the owner's record and the app owns it. Nothing here should
need a write lock on the app's 13 GB database to avoid annoying him twice.

THE 7-DAY WINDOW, stated in one place: a question asked by text is not repeated within 7 days, so a repeat
follows only a genuine silence, but an unanswered question does come back rather than being retired.

Usage: python3 guard-repeat-asks.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")
REASK_DAYS = 7
STORE = Path.home() / ".sms-inbox" / "offered.db"

HELPER = '''

def _offered_conn():
    """The record of what we have already put to the owner by text. A store WE own."""
    import sqlite3 as _s
    p = Path.home() / ".sms-inbox" / "offered.db"
    c = _s.connect(str(p), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS offered ("
              "queue_id INTEGER PRIMARY KEY, body TEXT, offered_at TEXT)")
    return c


def _already_offered(queue_id) -> bool:
    """True if this question was put to him within the re-ask window. Unreadable store -> False (ask)."""
    try:
        c = _offered_conn()
        row = c.execute("SELECT offered_at FROM offered WHERE queue_id=?", (int(queue_id),)).fetchone()
        c.close()
        if not row or not row[0]:
            return False
        when = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
        return age_days < __REASK_DAYS__
    except Exception as exc:
        print(f"    (offered-store read failed, will ask: {type(exc).__name__})")
        return False


def _record_offered(queue_id, body) -> None:
    """Record that this question went out. Unstampable here would mean it repeats - so print loudly."""
    try:
        c = _offered_conn()
        c.execute("INSERT INTO offered (queue_id, body, offered_at) VALUES (?,?,?) "
                  "ON CONFLICT(queue_id) DO UPDATE SET body=excluded.body, offered_at=excluded.offered_at",
                  (int(queue_id), (body or "")[:500],
                   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        c.commit()
        got = c.execute("SELECT offered_at FROM offered WHERE queue_id=?", (int(queue_id),)).fetchone()
        c.close()
        if not got:
            print("    WARNING: could not record the ask - this question WILL repeat")
        else:
            print(f"    recorded as offered ({got[0]}); will not re-ask for __REASK_DAYS__ days")
    except Exception as exc:
        print(f"    WARNING: could not record the ask ({type(exc).__name__}: {exc}) - it WILL repeat")
'''.replace("__REASK_DAYS__", str(REASK_DAYS))

OLD_SKIP = '''        if "asked_by_text" in (r.get("context") or "") or r.get("asked_at_text"):
            continue'''
NEW_SKIP = '''        if "asked_by_text" in (r.get("context") or "") or r.get("asked_at_text"):
            continue
        # AND THE GUARD THAT ACTUALLY WORKS: the owner queue is write-blocked by the app's 13 GB handle, so a
        # stamp there can silently fail. This one lives in a store we own and cannot be blocked.
        if _already_offered(r.get("id")):
            continue'''

OLD_RETURN = '''        return True'''
NEW_RETURN = '''        _record_offered(row.get("id"), body)
        return True'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "_already_offered" in src:
        print("already guarded")
        return 0
    anchor = "\ndef _reply_with_top_question("
    if anchor not in src:
        print("ERROR: could not find _reply_with_top_question")
        return 1
    src = src.replace(anchor, HELPER + anchor, 1)
    print("1. added the offered-store helpers")
    if OLD_SKIP not in src:
        print("ERROR: could not find the selection skip - refusing to guess")
        return 1
    src = src.replace(OLD_SKIP, NEW_SKIP, 1)
    print("2. the selector now skips anything already offered")
    # the return inside _reply_with_top_question only
    i = src.find("def _reply_with_top_question(")
    j = src.find("\ndef ", i + 10)
    seg = src[i:j]
    if OLD_RETURN not in seg:
        print("ERROR: could not find the success return inside the reply function")
        return 1
    seg = seg.replace(OLD_RETURN, NEW_RETURN, 1)
    src = src[:i] + seg + src[j:]
    print("3. a successful send is now recorded")
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-offered-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup .bak-offered-%s)" % (p, stamp))

    print("\n=== PROOF: the guard works, and it works WITHOUT the app's database ===")
    c = sqlite3.connect(str(STORE), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS offered (queue_id INTEGER PRIMARY KEY, body TEXT, offered_at TEXT)")
    c.execute("INSERT INTO offered (queue_id, body, offered_at) VALUES (?,?,?) "
              "ON CONFLICT(queue_id) DO UPDATE SET offered_at=excluded.offered_at",
              (164, "ESCAPE 101 LLC ...", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM offered").fetchone()[0]
    c.close()
    print("  offered.db now holds %d row(s); #164 marked as already put to him" % n)
    print("  (this write took no lock on secretary.db - the store has no other writers)")
    code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('r','%s');"
            "m=importlib.util.module_from_spec(s); sys.modules['r']=m; s.loader.exec_module(m);"
            "print('  #164 already offered?', m._already_offered(164));"
            "print('  #166 already offered?', m._already_offered(166))" % p)
    out = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=120)
    print(out.stdout or out.stderr[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
