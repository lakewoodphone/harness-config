#!/usr/bin/env python3
"""How many self-admission texts would the promise-salvage put on his phone?

THE DEFECT
----------
`textsend.classify_owner_body` drops the promise sentence out of a body and sends what
is left. When what is left is an apology for having asked -- "I was asking you for
something I should have found myself." -- the gate has removed the only sentence that
said what would happen and kept the one that says nothing. It then admits the leftover
as a RESULT because it is 58 characters and three words long. The owner ignores it: there
is nothing to answer.

THE MEASUREMENT
---------------
Every distinct provider sid sent to the owner inside the window, one body per sid (the
longest row: `sms_log` stores the pre-salvage body and the salvaged copy under the same
sid). Both gates are run over the same bodies:

    BEFORE  the mirrored file at --before (default HEAD, i.e. before the fix is committed)
    AFTER   the working tree file

and the report separates:
  * self-admission texts the gate would DELIVER (the dead family);
  * substantive salvages still delivered (a real answer inside a promise) -- must not fall;
  * every body whose fate changed, so the change can be read rather than trusted.

It sends nothing and writes nothing.

Run:
    cd /root/code/harness-config
    python3 scripts/text-channel/measure-self-admission-salvage.py --days 14 --before HEAD

After the fix is committed, the same before is `--before HEAD^`.
"""
from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MIRROR = HERE / "mirror" / "textsend.py"
AUTHORITY_DB = Path("/root/authority.db")
OWNER = "8483897895"


def load(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_before(rev: str):
    text = subprocess.check_output(
        ["git", "-C", str(REPO), "show",
         "%s:scripts/text-channel/mirror/textsend.py" % rev],
        text=True,
    )
    tmp = Path(tempfile.mkdtemp(prefix="textsend-before-")) / "textsend.py"
    tmp.write_text(text)
    return load(tmp, "textsend_before_measure")


def owner_sids(since: str):
    conn = sqlite3.connect(str(AUTHORITY_DB))
    conn.row_factory = sqlite3.Row
    rows = {}
    for r in conn.execute(
        """SELECT twilio_sid, body, created_at
             FROM sms_log
            WHERE direction = 'outbound'
              AND replace(replace(COALESCE(to_number,''),'+',''),'-','') LIKE ?
            ORDER BY created_at""",
        ("%" + OWNER,),
    ):
        if not r["twilio_sid"] or r["created_at"] < since:
            continue
        k = r["twilio_sid"]
        # The pre-salvage body is the longer of the two rows sharing the sid.
        if k not in rows or len(r["body"] or "") > len(rows[k]["body"] or ""):
            rows[k] = dict(r)
    conn.close()
    return rows


def self_admission_only(mod, body: str) -> bool:
    """A body that is only an admission: no specific, no question, no alert."""
    b = str(body or "").strip()
    return bool(b) and bool(mod._SELF_ADMISSION_RE.match(b)) \
        and not mod._specifics(b) and not mod._has_question(b) \
        and not mod._ALERT_RE.search(b)


def substantive(mod, verdict) -> bool:
    """A salvaged core that carries a fact or a question: the reason salvage exists."""
    core = verdict.get("send_body") or ""
    return bool(core) and (bool(mod._specifics(core)) or mod._has_question(core))


def tally(mod, bodies, judge):
    delivered_admission = 0
    substantive_salvage = 0
    for body in bodies:
        v = mod.classify_owner_body(body)
        send = v.get("send_body") or ""
        # The judge is always the NEW module: an old gate has no self-admission regex,
        # and the question is whether the text it delivered is an admission, not which
        # gate named it.
        if self_admission_only(judge, send):
            delivered_admission += 1
        if v.get("refused") and substantive(mod, v):
            substantive_salvage += 1
    return delivered_admission, substantive_salvage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--before", default="HEAD",
                    help="git revision of mirror/textsend.py to call BEFORE (default HEAD)")
    ap.add_argument("--all", action="store_true", help="ignore --days")
    args = ap.parse_args()

    since = "1970-01-01" if args.all else (
        datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    rows = owner_sids(since)
    bodies = [r["body"] or "" for r in rows.values()]

    new = load(MIRROR, "textsend_after_measure")
    old = load_before(args.before)

    before_admission, before_substantive = tally(old, bodies, new)
    after_admission, after_substantive = tally(new, bodies, new)

    changed = []
    for r in rows.values():
        body = r["body"] or ""
        o = old.classify_owner_body(body)
        n = new.classify_owner_body(body)
        if (o.get("send_body") or None) != (n.get("send_body") or None):
            changed.append((r["created_at"], body, o, n))

    window = "ALL TIME" if args.all else "last %d days" % args.days
    print("self-admission salvage — %s, %d distinct provider sids (owner %s)"
          % (window, len(rows), OWNER))
    print("  before: git %s:scripts/text-channel/mirror/textsend.py" % args.before)
    print("  after : %s" % MIRROR)
    print()
    print("  %-38s %6s %6s" % ("", "BEFORE", "AFTER"))
    print("  " + "-" * 54)
    print("  %-38s %6d %6d" % ("self-admission texts the gate delivers",
                               before_admission, after_admission))
    print("  %-38s %6d %6d" % ("substantive salvages still delivered",
                               before_substantive, after_substantive))
    print("  %-38s %6d" % ("bodies whose fate changed", len(changed)))
    print()
    print("COUNT   self-admission texts the gate would deliver: %d -> %d"
          % (before_admission, after_admission))
    print("COUNT   substantive salvages lost: %d"
          % max(0, before_substantive - after_substantive))
    print("COUNT   other bodies whose fate changed: %d"
          % sum(1 for _at, body, o, n in changed
                if not self_admission_only(new, o.get("send_body") or "")))
    print()
    for at, body, o, n in sorted(changed):
        print("  CHANGED %s  %s -> %s" % (at[:19], o.get("code"), n.get("code")))
        print("    body : %s" % " ".join(body.split())[:220])
        print("    before sends: %r" % (o.get("send_body") or "")[:140])
        print("    after  sends: %r" % (n.get("send_body") or "")[:140])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
