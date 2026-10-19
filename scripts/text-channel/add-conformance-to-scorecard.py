#!/usr/bin/env python3
"""add-conformance-to-scorecard.py - the loop cannot see whether the fix worked.

`owner-text-scorecard.py` measures the dead-text rate: how many texts he answered, complained
about, or ignored. That is the right long-horizon measure and it moves slowly.

It cannot answer the question this week's overhaul turns on: **are the guards still letting
through the things they were built to stop?** The rate would have to be measured against
grievances that arrive as texts, so it lags by weeks and is confounded by everything else.

So add the conformance census: take every text that actually REACHED him in the window and ask
the live guards whether they would refuse it now. That number is not a rate of his mood; it is a
count of defects that shipped. It should fall to zero and stay there, and if it rises the guards
or a bypass has regressed.

This is the closed loop the owner asked for: the wake source files a flag from the dead-text
rate, and this census says whether the structural fix is holding in between.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "owner-text-scorecard.py"

FUNC = '''

# ---------------------------------------------------------------------------------------
# THE CONFORMANCE CENSUS (added 2026-10-19).
#
# The dead-text rate answers "did this text do any work", and moves over weeks. It cannot say
# whether the GUARDS are holding: if the quiet-hours rule and the internal-prose rule are doing
# their job, nothing they would refuse should reach him at all - and if something does, that is
# a defect that shipped, not a slow trend.
#
# So count it directly: every text that reached him in the window, scored against the guards
# that are live NOW. A rising number means a bypass, a regression, or a guard switched off.
# ---------------------------------------------------------------------------------------
RELAY_DIR = os.environ.get("OWNER_TEXT_RELAY_DIR", "/root/bin")
_GUARD_FUNCS = ("internal_prose", "credential_request")


def _load_relay():
    """The live relay module, or None. Never raises - a census must not break the scorecard."""
    try:
        if RELAY_DIR not in sys.path:
            sys.path.insert(0, RELAY_DIR)
        import owner_text_relay  # noqa: WPS433 - deliberate late import from a sibling dir
        return owner_text_relay
    except Exception:
        return None


def conformance(rows, since):
    """{delivered, would_refuse, by_class, rate} over texts that reached him in the window."""
    relay = _load_relay()
    if relay is None:
        return {"available": False,
                "why": "owner_text_relay not importable from %s" % RELAY_DIR,
                "unmeasured": ["conformance"]}
    since_s = since.isoformat() if hasattr(since, "isoformat") else str(since)
    delivered = 0
    flagged = 0
    by_class = {}
    examples = []
    seen_sids = set()
    for r in rows:
        if r.get("direction") != "outbound":
            continue
        if (r.get("status") or "").lower() not in ("delivered", "sent"):
            continue
        if str(r.get("created_at") or "") < since_s:
            continue
        # ONE TEXT IS ONE EVENT. `sms_log` records the same send twice - an audit row from
        # `_audited_send` and a second row from the caller - so counting rows would double
        # every figure here exactly as it did in the audit.
        sid = r.get("twilio_sid")
        key = sid if sid and sid not in ("twiml-reply",) else ("id", r.get("id"))
        if key in seen_sids:
            continue
        seen_sids.add(key)
        delivered += 1
        body = r.get("body") or ""
        hits = []
        for name in _GUARD_FUNCS:
            fn = getattr(relay, name, None)
            if not callable(fn):
                continue
            try:
                got = fn(body)
            except Exception:
                got = None
            if got:
                hits.append(name)
        if hits:
            flagged += 1
            for name in hits:
                by_class[name] = by_class.get(name, 0) + 1
            if len(examples) < 5:
                examples.append({"at": r.get("created_at"), "classes": hits,
                                 "body": " ".join(body.split())[:120]})
    return {"available": True, "delivered": delivered, "would_refuse": flagged,
            "by_class": by_class, "examples": examples,
            "rate": (flagged / delivered) if delivered else None}
'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "def conformance(" in text:
        print("OK    already applied")
        return 0
    if "import os" not in text:
        text = text.replace("import json", "import json\nimport os", 1)
    anchor = "\ndef summarise(result):"
    if text.count(anchor) != 1:
        print("FAIL  summarise anchor found %d times" % text.count(anchor))
        return 1
    text = text.replace(anchor, FUNC + anchor, 1)

    # print it in the human report
    rep_anchor = "def report(result, summary, days, window_h):"
    if text.count(rep_anchor) != 1:
        print("FAIL  report anchor not unique")
        return 1
    text = text.replace(
        rep_anchor,
        rep_anchor + "\n    conf = result.get(\"conformance\") or {}", 1)

    # compute + emit in main()
    old_main = "    result = judge(rows, since, until, args.reply_window)\n    summary = summarise(result)"
    new_main = ("    result = judge(rows, since, until, args.reply_window)\n"
                "    result[\"conformance\"] = conformance(rows, since)\n"
                "    summary = summarise(result)")
    if text.count(old_main) != 1:
        print("FAIL  main() anchor not unique")
        return 1
    text = text.replace(old_main, new_main, 1)

    old_print = ('        report(result, summary, args.days, args.reply_window)')
    new_print = ('''        report(result, summary, args.days, args.reply_window)
        conf = result.get("conformance") or {}
        print()
        print("  CONFORMANCE - texts that reached him and the live guards would refuse")
        if not conf.get("available"):
            print("    NOT MEASURED: %s" % conf.get("why"))
        else:
            rate = conf.get("rate")
            print("    %d of %d delivered texts   (%s)"
                  % (conf.get("would_refuse", 0), conf.get("delivered", 0),
                     "%.1f%%" % (rate * 100) if rate is not None else "n/a"))
            for k, v in sorted((conf.get("by_class") or {}).items(), key=lambda kv: -kv[1]):
                print("      %-20s %d" % (k, v))
            for e in (conf.get("examples") or [])[:3]:
                print("      e.g. %s %s | %s"
                      % (str(e.get("at"))[:16], e.get("classes"), e.get("body")))''')
    if text.count(old_print) != 1:
        print("FAIL  report() call not unique")
        return 1
    text = text.replace(old_print, new_print, 1)

    import ast
    try:
        ast.parse(text)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add the conformance census to the scorecard")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(text)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
