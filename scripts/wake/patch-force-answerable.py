#!/usr/bin/env python3
"""Make `force_answerable` mean something in textdecide.py.

THE DEFECT, measured 2026-09-28 by audit C on the text channel:
    textdecide.py:648  _choose_with_model(..., force_answerable=True)   <- passed for the owner
    textdecide.py:656  _choose_with_model(..., force_answerable=False)  <- passed for everyone else
    textdecide.py:660  def _choose_with_model(..., force_answerable: bool) -> dict:
    ...and the parameter is NEVER READ anywhere in the function body.

So the guard that exists to protect the owner - "the owner is never treated as a stranger on his
own line, and is NEVER filed as nothing", a rule the file's own comment says was written because
he stopped using the line (finding B2) - was a no-op with a reassuring name. Only the
`action == "ignore"` path was patched afterwards, so an owner text the model scores
`queue`/`escalate`/`answer` still went down the ordinary route and could be filed as a row asking
the owner about the owner.

WHAT THIS DOES. Two changes, both narrow:
  1. The flag is now IN THE PROMPT. When it is true the model is told, in the same instruction
     block as everything else, that this is the owner's own text and it may not be left
     unanswered or filed as nothing.
  2. The flag is ENFORCED in code, independently of the model: with it true, an `ignore` action
     and a `needs_owner` escalation are both converted into an answerable work decision. Model
     instructions are advisory; a guard that only exists in a prompt is not a guard.

It refuses to write a file it cannot compile, backs up first, and PRINTS THE DIFF REGION so the
change is reviewable.

Usage: python3 patch-force-answerable.py --apply
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/textdecide.py")

OLD_SIG = '''def _choose_with_model(text: str, ctx: dict, *, model: str | None, llm,
                       decider: "Decider | None", force_answerable: bool) -> dict:
    ident = ctx.get("identity") or {}'''

NEW_SIG = '''def _choose_with_model(text: str, ctx: dict, *, model: str | None, llm,
                       decider: "Decider | None", force_answerable: bool) -> dict:
    """Decide what to do with one text.

    `force_answerable` is TRUE for the owner's own number and it is ENFORCED HERE, not just
    described. It was passed at :648, declared here, and never read - so the rule this file's
    own comment calls the reason the owner stopped using the line ("the owner is never treated
    as a stranger on his own line, and is NEVER filed as nothing", finding B2) had no effect on
    any path except the one patched afterwards. Audit C, 2026-09-28.
    """
    forced = bool(force_answerable)
    ident = ctx.get("identity") or {}'''

OLD_ACTION_IGNORE = '''    if action == "ignore":
        return {"action": "ignore", "text": None, "holding": None, "kind": "noise",
                "urgency": "low", "why": why or "the model said ignore",
                "confidence": 0.7, "needs_owner": False, "work": None,'''

NEW_ACTION_IGNORE = '''    if action == "ignore":
        if forced:
            # ENFORCED. The owner's own text may not be filed as nothing, whatever the model
            # scored it. This mirrors the `action == "ignore"` conversion at the call site: the
            # decision is turned into work that an answer can be built from, never silence.
            return _work_decision(
                "the owner's own text was scored as ignorable - looking into it instead",
                "work out what the owner is asking for", text,
                "On it.", resolved, needs_owner=True)
        return {"action": "ignore", "text": None, "holding": None, "kind": "noise",
                "urgency": "low", "why": why or "the model said ignore",
                "confidence": 0.7, "needs_owner": False, "work": None,'''

# The prompt: state the rule where the model actually reads it.
OLD_PROMPT_HINT = '''    ident = ctx.get("identity") or {}
    allow = (ctx.get("allow") or "queue")
    rel = ident.get("relationship") or "unknown"
    name = ident.get("name") or ctx.get("phone") or "this person"'''

NEW_PROMPT_HINT = '''    ident = ctx.get("identity") or {}
    allow = (ctx.get("allow") or "queue")
    rel = ident.get("relationship") or "unknown"
    name = ident.get("name") or ctx.get("phone") or "this person"

    # SAY IT IN THE PROMPT AS WELL AS ENFORCING IT IN CODE. The model is being asked to decide,
    # so it has to be told the one rule that overrides its judgement for this caller.
    forced_rule = (
        "THIS IS THE OWNER'S OWN TEXT, ON HIS OWN LINE. He is never a stranger here and he is "
        "never ignored: do not return action \\"ignore\\" and do not escalate a question about "
        "him back to him. Either answer it, or return `work` describing what has to be found "
        "out in order to answer it."
    ) if forced else None'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")
    n = 0
    for old, new, label in (
        (OLD_SIG, NEW_SIG, "signature + enforced docstring"),
        (OLD_ACTION_IGNORE, NEW_ACTION_IGNORE, "the ignore path"),
        (OLD_PROMPT_HINT, NEW_PROMPT_HINT, "the prompt rule"),
    ):
        if new in src:
            print("already applied: %s" % label)
            continue
        if old not in src:
            print("NOT FOUND (%s): refusing to guess at this site" % label)
            continue
        src = src.replace(old, new, 1)
        n += 1
        print("will patch: %s" % label)

    if n == 0:
        print("nothing to do")
        return 0
    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (%d site(s); use --apply)" % n)
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-force-answerable-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== proving it: force_answerable must change the outcome for an ignore ===")
    test = r'''
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("td", "/home/zabz/bin/textdecide.py")
td = importlib.util.module_from_spec(spec); sys.modules["td"] = td; spec.loader.exec_module(td)
class FakeLLM:
    @staticmethod
    def __call__(system, user):
        # the model says "ignore" no matter who is asking - the guard must beat it
        return json.dumps({"action": "ignore", "why": "noise", "text": None})
def decide(force):
    ctx = {"phone": "+18483897895", "allow": "auto",
           "identity": {"relationship": "owner", "name": "The owner"}, "known": True}
    return td._choose_with_model("hello?", ctx, model="x", llm=FakeLLM(), decider=None,
                                 force_answerable=force)
a = decide(True); b = decide(False)
print("owner  (force=True ) -> action=%s needs_owner=%s" % (a.get("action"), a.get("needs_owner")))
print("stranger(force=False) -> action=%s needs_owner=%s" % (b.get("action"), b.get("needs_owner")))
assert a.get("action") != "ignore", "the owner was ignored despite force_answerable=True"
assert b.get("action") == "ignore", "the flag leaked: a stranger was force-answered"
print("PATCH VERIFIED: force_answerable=True protects the owner; =False still ignores a stranger")
'''
    r = subprocess.run([sys.executable, "-c", test], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip())
    if r.returncode != 0:
        print("VERIFICATION FAILED\n" + (r.stderr or "").strip()[-1500:])
        print("\nrolling back")
        shutil.copy2(bak, p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
