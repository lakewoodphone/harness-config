#!/usr/bin/env python3
"""rescue-reminders.py - the gate must not lose a reminder; it must stop it being an instruction.

MEASURED 2026-10-19, the day the internal-prose guard went live: of 34 distinct reminder-class
texts ever delivered, **9 would now be refused** - and a refused reminder is a reminder he never
receives. Among the nine: the Weinberg cash settlement, the Fisher SD-card search, the Weitman
bench job for that day, and the Yaakov refund. Money and customers.

That is the wrong trade. The guard exists because these bodies were written as AGENT
INSTRUCTIONS - "EXECUTE: Pay X. Record date+amount in lpt-hub/docs/...", "WO2602180002 ... Then
add the check number to the order production notes." The owner cannot act on a repository path. He
CAN act on "pay Yisroel Weinberg 597.29 in cash - it is due today."

So the relay gains a REMEDIATION step, before the guards, for reminder-class bodies only:

    _rescue_reminder(body, to, subsystem) ->
        strip the internal scaffolding (paths, branch names, Record-in, append-to, EXECUTE:,
        task/work-order ids, and any parenthetical or trailing sentence that carries one)
        collapse and cap at a sentence boundary
        if what remains is empty or still reads as internal prose -> return the ORIGINAL body
        so the guard suppresses it and the loss is at least deliberate and logged

Only owner-directed, reminder-class bodies are touched. Nothing else in the chain moves: the
rescued body then faces every other rule exactly as before, including the credential rule.

SPLIT BY MARKER, NOT BY HOPE. The same text without its marker is not a reminder - "Pay Yisroel
Weinberg 597.29" from a cron with no marker is a second body and is not rescued; it still faces
the guard and is refused. That is recorded so nobody assumes this rescues every body.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/owner_text_relay.py")

RESCUER = '''
# ---- rule 1h's rescue: a reminder is rewritten, never dropped ------------------

#: Bodies this may touch. A clock or siren opener is what this system's own reminder composer
#: puts on the wire; anything else is a different class and is left to the guard.
_REMINDER_OPENERS = ("\\u23f0", "\\U0001f6a8", "reminder:", "reminder -")
#: Scaffolding removed from a reminder body. Each of these is an instruction to an agent, or a
#: reference only an agent can follow, and none of them helps the owner do the thing.
_RESCUE_DROP_SENTENCE = re.compile(
    r"(?:docs/|data/|lpt-hub/|branch\\s|\\bRecord\\b[^.]{0,80}\\bin\\b|\\bappend\\b[^.]{0,40}\\bto\\b"
    r"|\\.md\\b|\\.py\\b|\\.json\\b|\\bWO\\d{8,}\\b|\\bTask\\s*#\\d+"
    r"|\\bDo NOT\\b|\\bNOT approved\\b|\\bproduction note\\b|\\bget the owner's\\b)",
    re.IGNORECASE)
_RESCUE_DROP_PAREN = re.compile(r"\\s*\\([^)]*(?:docs/|data/|lpt-hub/|branch\\s|\\.md\\b|\\.py\\b"
                                r"|\\bRecord\\b|\\bTask\\s*#\\d+|\\bWO\\d{8,})[^)]*\\)")
_RESCUE_STRIP_PREFIX = re.compile(r"\\bEXECUTE:\\s*|\\bTask\\s*#\\d+:?\\s*|\\bWO\\d{8,}\\b\\s*:?\\s*",
                                 re.IGNORECASE)
_RESCUE_MAX = 280


def _is_reminder_class(body: str) -> bool:
    low = " " + " ".join(str(body or "").lower().split()) + " "
    return any(op in low for op in _REMINDER_OPENERS)


def _rescue_reminder(body, to, subsystem):
    """(body, note). Rewrite an instruction-shaped reminder into a sentence; never lose it."""
    text = "" if body is None else str(body)
    if not text.strip():
        return body, None
    if subsystem in DEDUPE_EXEMPT_SUBSYSTEMS or not _owner_scope(to):
        return body, None
    if not _is_reminder_class(text):
        return body, None
    try:
        if _internal_hit(text) is None:
            return body, None
    except Exception:                                          # noqa: BLE001
        return body, None
    # ... rewrite
    work = text
    for _ in range(6):
        nxt = _RESCUE_DROP_PAREN.sub("", work)
        if nxt == work:
            break
        work = nxt
    work = _RESCUE_STRIP_PREFIX.sub("", work)
    parts = re.split(r"(?<=[.!?])\\s+", " ".join(work.split()))
    kept = [p for p in parts if not _RESCUE_DROP_SENTENCE.search(p)]
    while kept and (len(" ".join(kept)) > _RESCUE_MAX or _RESCUE_DROP_SENTENCE.search(kept[-1])):
        kept.pop()
    human = " ".join(kept).strip()
    if human and human[-1] not in ".!?":
        human += "."
    if not human or len(human) < 20:
        return body, "rescue: nothing readable remained; left for the guard to refuse"
    try:
        if _internal_hit(human) is not None:
            return body, ("rescue: rewritten body still reads as internal prose (%r); "
                          "left for the guard" % _internal_hit(human)[1][:60])
    except Exception:                                          # noqa: BLE001
        pass
    return human, "rescue: reminder rewritten for a human (%d -> %d chars)" % (
        len(text), len(human))

'''

ANCHOR = "def _body_guard(body, to, subsystem):"

CALL_OLD = '''            got_b, err_b = _guarded("body-guards", _body_guard, body, to, subsystem)'''

CALL_NEW = '''            # A REMINDER IS REWRITTEN, NEVER DROPPED. Measured 2026-10-19: 9 of 34 distinct
            # reminder texts would otherwise be refused - the Weinberg settlement, the Fisher
            # SD-card search, the Weitman bench job. The guard is right that the body was an
            # agent instruction and wrong to make that a reason he never hears the reminder.
            # The rescued text then faces every rule below exactly as any other body does.
            body, rescue_note = _rescue_reminder(body, to, subsystem)
            got_b, err_b = _guarded("body-guards", _body_guard, body, to, subsystem)'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "_rescue_reminder" in text:
        print("OK    already applied")
        return 0
    for label, anchor in (("_body_guard", ANCHOR), ("the call site", CALL_OLD)):
        if text.count(anchor) != 1:
            print("FAIL  %s found %d times" % (label, text.count(anchor)))
            return 1
    out = text.replace(ANCHOR, RESCUER.lstrip("\n") + ANCHOR, 1)
    out = out.replace(CALL_OLD, CALL_NEW, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add the reminder rescuer and wire it before the body guards")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-rescue-" + stamp))
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
