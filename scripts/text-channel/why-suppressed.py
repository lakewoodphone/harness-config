#!/usr/bin/env python3
"""why-suppressed.py - the duplicate rehearsal refused the FIRST send too. Why?

The body is a plain result ("The Q3 ST-50 is filed...") which SENDs in an isolated store. In the
duplicate rehearsal the same body through door-a with reason=cfo_ask came back SUPPRESS. Print the
reason and every rule that could produce it.
"""
import os
import sys
import tempfile

ROOT = tempfile.mkdtemp(prefix="why_")
os.environ["OWNER_TEXT_RELAY_DB"] = os.path.join(ROOT, "x.db")
sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
B = "The Q3 ST-50 is filed. Confirmation number 4471. Nothing needed from you."

for label, reason, urgency, hint in (
        ("reason=cfo_ask", "cfo_ask", "normal", None),
        ("reason=''", "", "normal", None),
        ("reason=reminder", "reminder", "normal", None),
        ("cfo_ask + class_hint=reply", "cfo_ask", "normal", "reply"),
):
    os.environ["OWNER_TEXT_RELAY_DB"] = os.path.join(ROOT, label.replace(" ", "_") + ".db")
    import importlib
    importlib.reload(R)
    got = R.submit("door-a", "rehearsal.a", B, reason=reason, urgency=urgency,
                   class_hint=hint, to=OWNER)
    print("  %-28s -> %-9s %s"
          % (label, got.get("verdict"), " ".join(str(got.get("reason") or "").split())[:90]))

print()
print("standing rules in force:")
try:
    print("  policy_sources:", R.policy_sources())
except Exception as exc:                                       # noqa: BLE001
    print("  policy_sources failed: %s" % exc)
try:
    print("  mutes for cfo_ask:", R.standing_rule_mutes("cfo_ask"))
    print("  mutes for reminder:", R.standing_rule_mutes("reminder"))
except Exception as exc:                                       # noqa: BLE001
    print("  standing_rule_mutes failed: %s" % exc)
print()
print("policy():")
for k, v in sorted(R.policy().items()):
    print("  %-28s %r" % (k, v))
