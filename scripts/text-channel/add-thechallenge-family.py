#!/usr/bin/env python3
"""add-thechallenge-family.py - six real complaints the classifier cleared, measured.

Running the deployed `is_non_answer` over all 325 of his inbound texts flagged 79 (24.3%) and the
flagged ones are right. The other direction was the risk, and six CLEARED texts are complaints about
the channel rather than answers to a purchase question:

    "Why did I have to ask you twice for you to respond. Audit your systems issues ..."
    "I find that very doubtful. People do not pay twice. Analyze and audit your sources and make
     sure you're not just making a big mistake."
    "I think you are wrong. I want you to verify this. I think they paused service ..."
    "That was a confusing and unclear text that had too many things in it. Talk to me like a normal
     person ..."
    "That was a confusing text and not Clear"
    "That's exactly the kind of weird mixed message with a digest the middle ..."

Each of those, cleared, becomes the ANSWER recorded against an ask - so the charge closes with "he
says we are wrong" filed as its category.

So a new STRONG family, "he is telling us to check our own work". Strong, not weak: the weak families
are overridden when his text names a category, which is right for "I told you that was shop
supplies", and wrong here - "I think you are wrong, verify this, and it was gas" is still him
refusing the question.

The patterns are deliberately narrow against the six measured texts: `check that/whether` alone would
catch ordinary sentences, and a bare `digest` would catch any mention, so neither is used alone.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/textdecide.py")

FAMILY = '''

#: THE SIXTH FAMILY, added 2026-10-19 from a measurement rather than a hunch: six of his 246 CLEARED
#: inbound texts are complaints about the channel, and a cleared complaint is recorded as the ANSWER
#: to whatever ask was open. Each pattern is narrow against the text that produced it -
#: `check that/whether` alone would catch ordinary sentences and a bare `digest` would catch any
#: mention, so neither stands alone.
_CHALLENGE_RE = re.compile(
    r"\\b(?:audit|analyse|analyze)\\b[^.!?]{0,40}\\b(?:sources?|records?|books?|systems?)\\b"
    r"|\\baudit your\\b"
    r"|\\bmake sure (?:you'?re|you are) not\\b"
    r"|\\bnot (?:just )?making a (?:big )?mistake\\b"
    r"|\\bverify (?:this|that|it)\\b"
    r"|\\bi (?:find that )?doubt(?:ful)?\\b|\\bnever mind\\b"
    r"|\\b(?:makes? no sense|nonsense)\\b"
    r"|\\b(?:i think )?you(?:'?re| are) wrong\\b|\\bthat'?s wrong\\b"
    r"|\\b(?:weird|mixed|muddled|confusing|unclear)\\s+(?:mixed\\s+)?(?:message|text|digest)\\b"
    r"|\\bthat was a confus",
    re.IGNORECASE)

'''

ANCHOR = "def attribute_reply(body: str, asks) -> dict:"

INSERT = '''    # THE SIXTH FAMILY: he is telling us to check our own work. Measured 2026-10-19 against all 325
    # of his inbound texts: six cleared texts are complaints, and a cleared complaint becomes the
    # ANSWER recorded against an open ask. Strong on purpose - not overrideable by naming a category,
    # because "I think you are wrong, verify this ... and it was gas" is still a refusal.
    found_challenge = _CHALLENGE_RE.search(text)
    if found_challenge:
        return True, ("he said %r (he is telling us to check our own work) - that is not an answer "
                      "to a purchase question" % found_challenge.group(0))

'''

OLD_LOOP = '''    for family, pattern in _NON_ANSWER_FAMILIES:'''
NEW_LOOP = None  # unchanged; the new family runs after the two existing tests


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "_CHALLENGE_RE" in text:
        print("OK    already applied")
        return 0
    if text.count(ANCHOR) != 1:
        print("FAIL  attribute_reply anchor found %d times" % text.count(ANCHOR))
        return 1
    out = text.replace(ANCHOR, FAMILY.lstrip("\n") + ANCHOR, 1)
    # insert the test just before the final `return False, ""` of is_non_answer
    old_tail = '''        return True, ("his text asks us a question back (%r) and names no category - "
                      "that is not an answer to a purchase question" % stripped[:120])
    return False, ""'''
    new_tail = '''        return True, ("his text asks us a question back (%r) and names no category - "
                      "that is not an answer to a purchase question" % stripped[:120])
''' + INSERT + '''    return False, ""'''
    if out.count(old_tail) != 1:
        print("FAIL  is_non_answer tail found %d times" % out.count(old_tail))
        return 1
    out = out.replace(old_tail, new_tail, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add the 'check your own work' family")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-challenge-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
