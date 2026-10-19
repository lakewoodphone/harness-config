#!/usr/bin/env python3
"""under-fire-check.py - which of the CLEARED texts are really complaints he is making?

The classifier calls 79 of his 325 inbound texts non-answers, and the ones it flags are right. The
risk is the other direction: a complaint it clears is a text the ledger will treat as an answer, so
the ask closes with "he says we are wrong" recorded as the answer.

This looks for the shapes of a challenge that the cue list does not yet carry, counts them among the
CLEARED texts, and prints them - so a rule can be added against a number rather than a hunch.
"""
import re
import sqlite3
import sys

sys.path.insert(0, "/root/bin")
import textdecide as T  # noqa: E402

OWNER = "%18483897895%"
rows = []
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
rows += [(str(w), b or "") for w, b in a.execute(
    "select created_at, body from sms_log where from_number='+18483897895' and direction='inbound'")]
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
rows += [(str(w), b or "") for w, b in m.execute(
    "select coalesce(date_sent_utc,date_sent), body from messages "
    "where direction='inbound' and from_number like ?", (OWNER,))]

seen = set()
texts = []
for w, b in rows:
    k = " ".join(b.split())[:120]
    if not k or k in seen:
        continue
    seen.add(k)
    texts.append((w, b))

cleared = [(w, b) for w, b in texts if not T.is_non_answer(b)[0]]
print("inbound texts: %d, cleared as answers: %d" % (len(texts), len(cleared)))
print()

#: The shapes of "you are wrong, go and check" that the cue list does not yet carry.
CANDIDATES = {
    "audit/analyse the sources": re.compile(
        r"\b(audit|analyse|analyze)\b[^.]{0,40}\b(sources?|records?|books?)\b|\baudit your\b",
        re.I),
    "make sure you are not wrong": re.compile(
        r"\bmake sure (you'?re|you are) not\b|\bnot (just )?making a (big )?mistake\b|"
        r"\bcheck (again|that|whether|your)\b", re.I),
    "verify this": re.compile(r"\bverify (this|that|it)\b|\bgo and verify\b", re.I),
    "i find that doubtful": re.compile(
        r"\b(doubtful|i doubt|doesn'?t make sense|makes no sense|nonsense)\b", re.I),
    "that is wrong": re.compile(r"\b(i think )?you are wrong\b|\bthat'?s wrong\b|\byou'?re wrong\b",
                                re.I),
    "weird/mixed message": re.compile(
        r"\b(weird|mixed|muddled|confusing|unclear) (mixed )?(message|text|digest)\b|"
        r"\bdigest\b", re.I),
}

hits = {}
for label, rx in CANDIDATES.items():
    found = [(w, b) for w, b in cleared if rx.search(b)]
    if found:
        hits[label] = found
        print("%-30s %d cleared text(s) match" % (label, len(found)))
        for w, b in found[:3]:
            print("     %s | %s" % (w[:10], " ".join(b.split())[:84]))
print()
allhit = set()
for found in hits.values():
    for w, b in found:
        allhit.add(b)
print("distinct cleared texts that these shapes would newly flag: %d" % len(allhit))
