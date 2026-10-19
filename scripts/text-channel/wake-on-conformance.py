#!/usr/bin/env python3
"""wake-on-conformance.py - the loop only watched his mood; watch the guards too.

The wake source files one flag a week when the dead-text rate is bad: "the texts are not worth
answering". That is the right long-horizon signal and it moves over weeks.

It cannot see a GUARD REGRESSION. If a bypass reopens, a guard is switched off, or a composer
starts writing instructions again, the dead-text rate will barely move - those texts simply start
arriving again, and the census is the only thing that notices.

So a second, INDEPENDENT flag: when too many of the texts that reached him are ones the live
guards would refuse, file a wake naming the classes. The prompt says the thing this session learned
the hard way - when the gate refuses a class, the defect is in the COMPOSER, and the repair is at
the sender, not a stricter guard. Suppressing harder hides a sender that writes badly.

Separate subject (`owner-text:conformance:<week>`) so it cannot dedupe away the scorecard flag, and
separate threshold, because the two conditions are independent.

The count excludes REMINDERS the gate rewrites and sends: those are delivered, readable, and not
defects. Counting them was the mistake the census itself made for a day.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "owner-text-scorecard.py"

FUNC = '''

#: The census threshold. 10% of the texts that reach him being ones the guards would refuse is a
#: regression, not noise; the first corrected reading was 11 of 77 (14%), and every one of those
#: eleven was a real defect of the composer that produced it.
CONFORMANCE_THRESHOLD = float(os.environ.get("OWNER_TEXT_CONFORMANCE_THRESHOLD", "0.10"))


def file_conformance_flag(conf, days):
    """File ONE wake when too many delivered texts are ones the guards would refuse.

    Independent of the dead-text flag: that one watches whether his texts do any work, this one
    watches whether the guards are holding. A guard regression moves this number and not that one.
    """
    if not conf or not conf.get("available"):
        print("no conformance flag: %s" % (conf or {}).get("why", "not measured"))
        return 0
    delivered = int(conf.get("delivered") or 0)
    refused = int(conf.get("would_refuse") or 0)
    if delivered < 20:
        print("no conformance flag: only %d delivered texts, too few to judge" % delivered)
        return 0
    rate = refused / delivered
    if rate <= CONFORMANCE_THRESHOLD:
        print("no conformance flag: %d of %d refused (%.1f%%) within threshold %.0f%%"
              % (refused, delivered, 100 * rate, 100 * CONFORMANCE_THRESHOLD))
        return 0
    y, w, _ = _now().isocalendar()
    subject = "owner-text:conformance:%04d-W%02d" % (y, w)
    classes = ", ".join("%s=%d" % (k, v)
                        for k, v in sorted((conf.get("by_class") or {}).items(),
                                           key=lambda kv: -kv[1])) or "(none named)"
    examples = "; ".join("%s :: %s" % (e.get("at", "")[:16], e.get("body", "")[:80])
                         for e in (conf.get("examples") or [])[:3]) or "(none)"
    prompt = (
        "%d of the %d texts that reached him in the last %g days are ones the live guards would "
        "refuse (%.1f%%, threshold %.0f%%). Classes: %s. Examples: %s\\n\\n"
        "DO ONE BOUNDED THING. The gate already refuses these - which means the defect is in the "
        "COMPOSER that writes them, and the repair belongs at the sender. Find the code that "
        "emits this class, make it write ONE human sentence (no paths, no task ids, no "
        "instruction verbs), and prove it by re-running `owner-text-scorecard.py` and reading the "
        "conformance block.\\n\\n"
        "Do NOT strengthen the guard to hide it: suppressing harder turns a bad message into no "
        "message, and for a reminder class that deletes the reminder. %s were rewritten by the "
        "gate in this window - those are delivered, not lost, and are not counted here."
        % (refused, delivered, days, 100 * rate, 100 * CONFORMANCE_THRESHOLD, classes, examples,
           conf.get("rewritten") or 0)
    )
    cmd = [sys.executable, WAKE, "flag", "--subject", subject, "--prompt", prompt,
           "--kind", "owner-text", "--source", "owner-text-conformance", "--priority", "normal"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("flag %s -> %s" % (subject, (out.stdout or out.stderr or "").strip()[:300]))
        return 0
    except Exception as exc:                                       # noqa: BLE001
        print("conformance flag filing FAILED: %r" % (exc,), file=sys.stderr)
        return 2

'''

OLD_CALL = '''    if args.flag:
        return file_flag(summary, args.days)'''
NEW_CALL = '''    if args.flag:
        # BOTH CONDITIONS, both filed, neither able to suppress the other.
        rc1 = file_flag(summary, args.days)
        rc2 = file_conformance_flag(result.get("conformance") or {}, args.days)
        return rc1 or rc2'''

ANCHOR = "\ndef main(argv=None):"


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "def file_conformance_flag" in text:
        print("OK    already applied")
        return 0
    for label, anchor in (("main()", ANCHOR), ("the --flag call", OLD_CALL)):
        if text.count(anchor) != 1:
            print("FAIL  %s found %d times" % (label, text.count(anchor)))
            return 1
    out = text.replace(ANCHOR, FUNC + ANCHOR, 1).replace(OLD_CALL, NEW_CALL, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add the conformance wake trigger")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
