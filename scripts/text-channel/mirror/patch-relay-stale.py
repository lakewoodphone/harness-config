#!/usr/bin/env python3
"""Add Rule 1e (a deadline that has already passed) to owner_text_relay.py.

Two anchors, both inside the block added on 2026-10-19, so they cannot be confused with the
file's older rules. Refuses to write unless each is found exactly once.

    python3 patch-relay-stale.py <mirror>/owner_text_relay.py --check
"""
import io
import sys

HELPER = '''
def _stale_verdict(body, subsystem, reason, now):
    """A deadline the body names has already passed. None when the body may go.

    Read-only and fails OPEN: an unreadable ledger must never silence a reminder that is
    still true.
    """
    mod = _topic()
    if mod is None:
        return None
    try:
        return mod.stale_reference(body, subsystem=subsystem, reason=reason, now=now)
    except Exception:  # noqa: BLE001
        return None


'''

ELIF = '''            # Rule 1e, STILL TRUE? (added 2026-10-19). A reminder fires because it is DUE;
            # nothing asked whether it is still TRUE. Measured in his thread: "PayPal case
            # ... seller response deadline is Oct 7, 2026" was delivered on 2026-10-08, a day
            # after the deadline it names. Topic identity cannot catch it -- the amount has
            # never been said, so it is a first message on a fresh topic -- and no
            # body-shaped rule can see a date. Only reminder/alert families are judged.
            elif (sv := _stale_verdict(body, subsystem, reason, now)) is not None:
                verdict, reason_code = "SUPPRESS", str(sv["code"])
                detail_t = "SUPPRESS: %s (attempt {aid})" % (sv["detail"],)

'''

ANCHORS = [
    ("helper", "\ndef submit(door: str, subsystem: str, body: str, *, reason: str = \"\",",
     HELPER + "\ndef submit(door: str, subsystem: str, body: str, *, reason: str = \"\","),
    ("rule-1e", "                detail_t = \"SUPPRESS: %s (attempt {aid})\" % (tv[\"detail\"],)\n\n            elif len(body) > ceiling:",
     "                detail_t = \"SUPPRESS: %s (attempt {aid})\" % (tv[\"detail\"],)\n\n" + ELIF + "            elif len(body) > ceiling:"),
]


def main(argv):
    path = argv[1]
    check = "--check" in argv[2:]
    src = io.open(path, encoding="utf-8").read()
    for label, old, _new in ANCHORS:
        n = src.count(old)
        if n != 1:
            print("REFUSED %s: anchor found %d time(s)" % (label, n))
            return 2
    for label, old, new in ANCHORS:
        src = src.replace(old, new, 1)
        print("anchored %s" % label)
    if check:
        print("check only; nothing written")
        return 0
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("written: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
