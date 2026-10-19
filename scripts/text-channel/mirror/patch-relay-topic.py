#!/usr/bin/env python3
"""Insert the topic ledger into owner_text_relay.py, at three exact anchors.

Refuses to write if any anchor is missing or found more than once — a patch that guesses is a
patch that silently misses.

    python3 patch-relay-topic.py <mirror>/owner_text_relay.py --check
    python3 patch-relay-topic.py <mirror>/owner_text_relay.py
"""
import io
import sys

HELPER = '''
# --------------------------------------------------------------------------- #
# The topic ledger — "we already told him this" (added 2026-10-19)
# --------------------------------------------------------------------------- #
# WHY. `attempt.topic` and `ask.topic` have been written since 2026-10-14 and read by
# nothing. Dedup is `policy_hash`, which is the BODY: four reminders for one payment, each
# reworded, are four different hashes and all four are allowed. Measured in his thread
# 2026-10-05/08: four texts for the same $597.29 settlement, three of them inside 90 minutes.
# `owner_topic.admit()` answers the question this relay could not ask — have we already said
# this? — and `owner_flood_guard` cannot, because it keys on the body too.
#
# IT FAILS OPEN, ALWAYS. A missing module, a missing table or a corrupt store must never
# withhold a text. The helper returns None and the relay carries on exactly as before, with
# one line on stderr so the degradation is visible rather than silent.
_TOPIC_MOD = None
_TOPIC_WARNED = False


def _topic():
    """The topic ledger module, loaded once by path. None on any failure."""
    global _TOPIC_MOD, _TOPIC_WARNED
    if _TOPIC_MOD is not None:
        return _TOPIC_MOD
    try:
        import importlib.util

        path = os.environ.get("OWNER_TOPIC_PY", "/root/bin/owner_topic.py")
        spec = importlib.util.spec_from_file_location("owner_topic", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TOPIC_MOD = mod
        return mod
    except Exception as exc:  # noqa: BLE001 - a brake that raises is a brake that does nothing
        if not _TOPIC_WARNED:
            _TOPIC_WARNED = True
            print("owner-topic ledger unavailable (%r); topic cooldown is OFF for this run"
                  % (exc,), file=sys.stderr)
        return None


def _topic_verdict(body, topic, subsystem, now):
    """admit() or None. Read-only, and never inside the relay's write transaction."""
    mod = _topic()
    if mod is None:
        return None
    try:
        return mod.admit(body, reason=topic or "", subsystem=subsystem, topic=topic,
                         now=now, conn=None)
    except Exception:  # noqa: BLE001
        return None


def _topic_flush(body, topic, subsystem, now, verdict, reason_code):
    """Record the outcome, AFTER the relay has committed.

    Deliberately outside the transaction: a second connection writing while the relay holds
    SQLite's write lock is how `database is locked` wedges a tick on this estate. A ledger
    that fails here must cost nothing but the count.
    """
    mod = _topic()
    if mod is None:
        return
    try:
        if verdict == "SEND":
            mod.record(body, reason=topic or "", subsystem=subsystem, topic=topic, now=now)
        elif reason_code in ("topic_cooldown", "topic_closed"):
            mod.note_refusal(body, reason=topic or "", subsystem=subsystem, topic=topic, now=now)
    except Exception:  # noqa: BLE001
        pass


'''

# inserted as an elif in the verdict chain, immediately after the standing-rule branch
ADMIT = '''            # Rule 1d, the TOPIC LEDGER (added 2026-10-19). Placed after the standing-rule
            # mutes and before the ceiling/duplicate rules because it is a fact about the
            # conversation, not about this body: "we already told him about this payment".
            # A refusal here is `topic_cooldown` (later) or `topic_closed` (not until something
            # changes) -- two different sentences, never one.
            elif (tv := _topic_verdict(body, topic, subsystem, now)) is not None and not tv["allow"]:
                verdict, reason_code = "SUPPRESS", str(tv["code"])
                detail_t = "SUPPRESS: %s (attempt {aid})" % (tv["detail"],)

            elif len(body) > ceiling:'''

FLUSH = '''    finally:
        owns.close()

    _topic_flush(body, topic, subsystem, now, verdict, reason_code)

    return {
        "verdict": verdict,'''

ANCHORS = [
    ("helper-before-submit", "\ndef submit(door: str, subsystem: str, body: str, *, reason: str = \"\",",
     HELPER + "\ndef submit(door: str, subsystem: str, body: str, *, reason: str = \"\","),
    ("admit-elif", "            elif len(body) > ceiling:", ADMIT),
    ("flush-after-commit", "    finally:\n        owns.close()\n\n    return {\n        \"verdict\": verdict,",
     FLUSH),
]


def main(argv):
    path = argv[1]
    check_only = "--check" in argv[2:]
    src = io.open(path, encoding="utf-8").read()
    problems = []
    for name, old, new in ANCHORS:
        count = src.count(old)
        if count != 1:
            problems.append("%s: anchor found %d time(s), need exactly 1" % (name, count))
    if problems:
        for p in problems:
            print("REFUSED " + p)
        return 2
    for name, old, new in ANCHORS:
        src = src.replace(old, new, 1)
        print("anchored %s" % name)
    if check_only:
        print("check only; nothing written")
        return 0
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("written: %s (%d bytes)" % (path, len(src.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
