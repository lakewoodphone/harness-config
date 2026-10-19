#!/usr/bin/env python3
"""add-k1-marked-sent-never-sent.py - "sent" in the queue must mean a text left.

MEASURED 2026-10-19: `owner_message_queue` holds 353 rows for one body ("Google Voice monitoring is
blind for account 0") in status `sent`, and there is no `sms_log` row within thirty minutes of any
sampled claim. The newest occurrences of that body (30 September, 3 October) are `dismissed` with
`last_send_error = "dropped: machine-facing: a comms pipeline..."`, so the LIVE path is already
fixed - the discrepancy is historical.

Historical or not, the class is the one this estate has paid for repeatedly: a status field that says
"this happened" with nothing behind it. `sent` is exactly such a field, and nothing checks it.

K1: no queue row in status `sent` inside the window may lack an sms_log row for the owner at about
that time. Window-scoped like J1, so a historical backlog is REPORTED (with its count) and only a
fresh regression FAILS the gate.

A "sent" row with no text behind it is the same sentence as "no answer" and "an answer that never
closed" - two different facts that must never read the same.
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
# K1: "sent" in the queue must mean a text left.
#
# Measured 2026-10-19: 353 queue rows for one body in status `sent` with no sms_log row within
# thirty minutes of any sampled claim. The live path was already fixed (those occurrences are now
# `dismissed` with "machine-facing: a comms pipeline..."), so the backlog is historical - but
# nothing was checking, and `sent` is precisely the field a reader trusts.
#
# Window-scoped like J1: the backlog is reported every run, and only a row claimed sent inside the
# window fails the gate, because a gate that is red for last quarter's rows stops being a gate.
# Match by TIME as well as by body: a template or a re-prefixed send must not hide a real send.
# ---------------------------------------------------------------------------------------
try:
    _db = _resolve_app_db()
    _q = ro(_db)
    try:
        _win = int(os.environ.get("QUEUE_SENT_WINDOW_DAYS", "7") or 7)
        _cut = (datetime.now(timezone.utc) - timedelta(days=_win)).isoformat()
        _claimed = [dict(r) for r in _q.execute(
            "select id, body, sent_at from owner_message_queue "
            "where status='sent' and sent_at is not null and sent_at >= ?", (_cut,))]
        _backlog = _q.execute(
            "select count(*) from owner_message_queue where status='sent' "
            "and sent_at is not null and sent_at < ?", (_cut,)).fetchone()[0]
        _missing = []
        for _row in _claimed:
            _hit = _q.execute(
                "select 1 from sms_log where to_number=? "
                "and (abs(julianday(created_at)-julianday(?)) < 0.02 "
                "     or substr(coalesce(body,''),1,60)=substr(coalesce(?,''),1,60)) "
                "limit 1",
                (OWNER_NUMBER, _row["sent_at"], _row["body"] or "")).fetchone()
            if not _hit:
                _missing.append(_row["id"])
        check("K1 a queue row marked 'sent' has a sms_log row behind it",
              not _missing,
              "%d row(s) claimed sent in the last %d days; %d of them have NO sms_log row within "
              "~30 minutes, so 'sent' there means nothing we can show. %d older row(s) carry the "
              "same claim and are reported, not failed: #%s"
              % (len(_claimed), _win, len(_missing), _backlog,
                 ",".join(str(i) for i in _missing[:8]) or "none"))
    finally:
        _q.close()
except Exception as exc:                                       # noqa: BLE001
    check("K1 a queue row marked 'sent' has a sms_log row behind it", False,
          "%s: %s" % (type(exc).__name__, exc))

'''

ANCHOR = 'print("TEXT-HEALTH %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
OWNER_ANCHOR = "APP_DB = _resolve_app_db()"


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "K1 a queue row marked" in text:
        print("OK    already applied")
        return 0
    if text.count(ANCHOR) != 1:
        print("FAIL  print anchor found %d times" % text.count(ANCHOR))
        return 1
    out = text
    if "OWNER_NUMBER" not in out:
        # the owner's own number, as the rest of the channel uses it
        out = out.replace(OWNER_ANCHOR,
                          OWNER_ANCHOR + '\n#: The owner\'s personal iPhone, the number every owner '
                          'text is judged against.\nOWNER_NUMBER = os.environ.get('
                          '"OWNER_PHONE_NUMBER", "+18483897895")', 1)
    out = out.replace(ANCHOR, CHECK + ANCHOR, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add K1 (marked sent, never sent)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-k1-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    rc = subprocess.run([sys.executable, "-c",
                         "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
                         str(tmp)], capture_output=True)
    if rc.returncode != 0:
        print("FAIL  tmp does not parse: %s" % rc.stderr.decode()[:300])
        tmp.unlink(missing_ok=True)
        return 1
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
