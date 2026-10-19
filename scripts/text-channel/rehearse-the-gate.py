#!/usr/bin/env python3
"""rehearse-the-gate.py - drive the REAL submit() chain with the REAL bodies, no wire.

Every guard so far is proved one function at a time. `submit()` is the thing the senders actually
call, and it is where the rules compose: class mutes, dup-sent, dup-inflight, retry cap, rate
floor, coalesce, topic cooldown, stale reference, quiet hours, credential, internal prose. A
function that is right on its own can still be wrong in that order.

Nothing has passed submit() since the guards went live, so this rehearses it on throwaway stores
with the exact bodies that were delivered to him and should not have been.

TWO STORES, BOTH THROWAWAY. The relay store is `OWNER_TEXT_RELAY_DB` and the topic ledger is
`OWNER_TOPIC_DB` - DIFFERENT variables, read by different modules. The first version of this
rehearsal redirected only the relay store, so its three SEND cases wrote real topic rows into
`/root/.owner-text/relay.db` at 17:27:43, which would have suppressed genuine messages for a
20-hour cooldown. They were removed (`clean-my-rehearsal-rows.py`, 3 rows, verified 0 after) and
both variables are redirected here so it cannot happen again.

Each case also gets its OWN store: the 20-minute rate floor would otherwise refuse the second
distinct body and every case after it would report FLOOR instead of its own reason.
"""
import os
import sys
import tempfile

STORE_ROOT = tempfile.mkdtemp(prefix="rehearse_")
sys.path.insert(0, "/root/bin")

OWNER = "+18483897895"

CASES = [
    ("machine string leaked to his phone",
     "[Budget exceeded for : ceoreserveexhausted]", "normal", None, "SUPPRESS", "internal_prose"),
    ("agent instruction with repo paths",
     "\u23f0 Reminder: EXECUTE: Pay Yisroel Weinberg $597.29 net CASH settlement (owner decided "
     "after Sukkot). Record date+amount in lpt-hub/docs/operations/payroll/ and append to the "
     "wages table in Yisroel-Weinberg-Payroll-Log-2026.md.", "normal", None,
         # A REMINDER IS RESCUED, NOT REFUSED (2026-10-19). This body carries a
         # clock marker, so the relay rewrites it - dropping the payroll paths and
         # the work-order ids - and SENDS the readable remainder. Refusing it
         # deleted the Weinberg payment reminder, which this class must never do.
         # The next case has NO marker, so it is a different body and is refused.
         "SEND", None),
    ("private health note with a branch name",
     "Task #26089: 14-day miconazole course finished 2026-10-02. Ask owner ONCE in conversation: "
     "did the rash clear? Record result in docs/personal/health/groin-skin-condition.md section 9 "
     "(branch docs/owner-health-2026-09-18).", "normal", None, "SUPPRESS", "internal_prose"),
    ("asks for a login in a text",
     "NJ payroll returns have no filer since Gusto was cancelled on 8 October \u2014 Give me the NJ "
     "Premier Business Services login and I will file 06/2026 now. Yes?", "normal", None,
     "SUPPRESS", "credential"),
    ("addressed to somebody else",
     "Dov - for Yitz's nightly learning, the OnePlus Buds 4. 109 on Amazon.", "normal", None,
     "SUPPRESS", "internal_prose"),
    ("content-free acknowledgement",
     "Captured as a task.", "normal", None, "SUPPRESS", "internal_prose"),
    ("half a sentence delivered as a whole one",
     "- The parent notice is live and unsigned, and the contact block you supplied is",
     "normal", None, "SUPPRESS", "internal_prose"),
    ("a status sentence carrying an id is still a MESSAGE",
     "Task #12 is still open in the hub.", "normal", None, "SEND", None),
    ("a security question is still a MESSAGE",
     "URGENT - CEO needs a decision Task #1342: Was the macOS Chrome sign-in to "
     "lakewoodphoneandtech@gmail.com legitimate (your device), or is this unauthorized access? "
     "Reply to this text and I'll get it.", "normal", None, "SEND", None),
    ("a plain result is a MESSAGE",
     "The Q3 ST-50 is filed. Confirmation number 4471. Nothing needed from you.",
     "normal", None, "SEND", None),
]

bad = 0
import importlib
import owner_text_relay as R

for i, (label, body, urgency, hint, want_v, want_r) in enumerate(CASES):
    os.environ["OWNER_TEXT_RELAY_DB"] = os.path.join(STORE_ROOT, "case%02d.db" % i)
    os.environ["OWNER_TOPIC_DB"] = os.path.join(STORE_ROOT, "topic%02d.db" % i)
    importlib.reload(R)
    got = R.submit("rehearsal", "rehearsal.gate", body, reason="cfo_ask",
                   urgency=urgency, class_hint=hint, to=OWNER)
    v = got.get("verdict")
    why = " ".join(str(got.get("reason") or "").split())
    ok = (v == want_v) and (want_r is None or want_r in why)
    bad += 0 if ok else 1
    print("  %-5s %-46s %-9s %s" % ("ok" if ok else "FAIL", label[:46], v, why[:60]))
    if not ok:
        print("        want %s%s" % (want_v, (" / " + want_r) if want_r else ""))

# the same body twice, in ONE store, through two different doors
os.environ["OWNER_TEXT_RELAY_DB"] = os.path.join(STORE_ROOT, "dupe.db")
os.environ["OWNER_TOPIC_DB"] = os.path.join(STORE_ROOT, "dupe-topic.db")
importlib.reload(R)
b = "The Q3 ST-50 is filed. Confirmation number 4471. Nothing needed from you."
first = R.submit("door-a", "rehearsal.a", b, reason="cfo_ask", to=OWNER)
second = R.submit("door-b", "rehearsal.b", b, reason="cfo_ask", to=OWNER)
# REFUSED is the requirement, not a particular reason code. The second submission must not reach
# him; whether the topic ledger, the body-hash duplicate rule or the rate floor catches it is an
# implementation detail, and pinning one of them failed this check while the behaviour was right.
ok = first.get("verdict") == "SEND" and second.get("verdict") != "SEND"
bad += 0 if ok else 1
print("  %-5s %-46s %s then %s (%s)"
      % ("ok" if ok else "FAIL", "same body, two doors",
         first.get("verdict"), second.get("verdict"),
         " ".join(str(second.get("reason") or "").split())[:36]))

print()
print("stores used (throwaway): %s" % STORE_ROOT)
print("RESULT:", "PASS" if not bad else "FAIL (%d)" % bad)
raise SystemExit(0 if not bad else 1)

