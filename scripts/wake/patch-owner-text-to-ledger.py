#!/usr/bin/env python3
"""Wire the owner's own texts to the WORK LEDGER, so asking by text starts real work.

MEASURED (audit C, 2026-09-28): an inbound text from the owner reaches `sms-responder.py`, gets a
permission row (`allow=auto` since the identity fix), and then... does nothing that survives. The
responder's only text -> work door is `consume_await()`, which needs a PRE-EXISTING `awaited` row
(two ever, both 2026-09-18). So "text me a question and it gets worked" was not true, and neither
was "I can ask for something by text". The owner is still the only one who can start work by
opening a session himself, which is the exact failure this whole objective exists to end.

WHAT THIS ADDS. After the existing permission/identity checks, an owner text that is a request or
a question is filed as a real work item in the ledger (`~/bin/work.py`), tagged with the message
sid so the item and the text are linked in both directions. That is one verb and no new store.

WHAT IT DOES NOT DO, on purpose:
  * It does not send an acknowledgement. Nothing in this system sends the owner anything until he
    has approved the specific behaviour, and that approval has not been given - so the ack code
    below is written, gated behind AITEXT_ACK_OWNER_REQUESTS, and OFF by default.
  * It does not guess the project. It uses the project whose repo/state the text names, else
    `housekeeping` as the honest default, and it records which was used and why in --why.
  * It does not invent a definition of done. `dod` names the observable that will satisfy the
    request, in the requester's own terms, so the shift has something to prove.

Usage: python3 patch-owner-text-to-ledger.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")

ANCHOR = '''        if allow == "never":
            print("    never - recorded, not answered")'''

NEW = '''        # ---------------------------------------------------------------------------
        # THE OWNER'S OWN TEXT IS A WORK ORDER.
        #
        # Added 2026-09-28. Before this, an owner text became at best an owner-queue row asking
        # him about himself - so he still had to open a session to get anything done. Now a
        # request or question from the owner files a real item in the work ledger and is tagged
        # with the message sid, so the text and the item point at each other.
        #
        # It runs BEFORE the classify/decide path because the classification costs a model call
        # and the ledger filing does not need one: "the owner asked for something" is not a
        # judgement call, it is a fact about the sender.
        # ---------------------------------------------------------------------------
        if allow == "auto" and _is_owner_number(perm, r["from_number"]):
            try:
                filed = _file_owner_request(conn, r, body)
            except Exception as exc:                      # never break the responder
                print(f"    owner-request filing failed: {type(exc).__name__}: {exc}")
                filed = None
            if filed:
                print(f"    filed as ledger item {filed['project']}#{filed['id']}")
                _record(conn, r["sid"], "working", "owner-request",
                        f"filed as ledger item {filed['project']}#{filed['id']}")
                if os.environ.get("AITEXT_ACK_OWNER_REQUESTS") == "1":
                    _ack_owner_request(r["from_number"], filed, body)
                continue

        if allow == "never":
            print("    never - recorded, not answered")'''

HELPERS = '''

# --------------------------------------------------------------------------- #
# THE OWNER'S TEXTS BECOME LEDGER ITEMS
# --------------------------------------------------------------------------- #
WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")


def _is_owner_number(perm: dict, phone: str) -> bool:
    """True only for the owner's own numbers. Both sources are deliberate: the ledger's
    relationship, and OWNER_PHONE_NUMBER. A context that merely SAYS 'owner' is not trusted."""
    if (perm.get("relationship") or "").lower().startswith("owner"):
        return True
    env_owner = os.environ.get("OWNER_PHONE_NUMBER")
    if env_owner:
        strip = lambda s: re.sub(r"\\D", "", s or "")[-10:]  # noqa: E731
        if strip(env_owner) and strip(env_owner) == strip(phone):
            return True
    return False


def _guess_project(body: str) -> tuple:
    """(project_id, why). A text may name its own project; otherwise the honest default is the
    project that owns housekeeping, and the reason says so rather than implying a guess was a fact."""
    b = (body or "").lower()
    named = [
        (("website", "lpt website", "www", "portal", "storefront", "homepage"), "lpt-website"),
        (("filter", "kosher", "content filter", "blocking"), "kosher-ai-filter"),
        (("sync", "dialpad", "hub", "production db", "database"), "lpt-sync"),
        (("cfo", "quickbooks", "books", "invoice", "payroll"), "cfo"),
        (("personality",), "personality-system"),
        (("rental", "rent"), "rental-system"),
        (("bible", "chumash", "codes"), "chumash"),
    ]
    for words, pid in named:
        for w in words:
            if w in b:
                return pid, f"the text names '{w}'"
    return "housekeeping", "no project was named in the text, so it defaults to housekeeping"


def _one_line(s: str, n: int = 140) -> str:
    return " ".join((s or "").split())[:n]


def _file_owner_request(conn, row, body: str) -> dict | None:
    """File the owner's request as a ledger item. Returns {'id':..,'project':..} or None.

    DEDUPE IS THE LEDGER'S JOB, not this function's: `work.py add` refuses a second open item with
    the same title and returns the existing id, which is exactly the "don't do the same work twice"
    guard the owner asked for. So a repeated text does not create a second shift.
    """
    text = _one_line(body, 200)
    if len(text) < 8:
        return None                      # "ok", "?" and similar are conversation, not work
    project, why = _guess_project(body)
    title = "owner asked by text: %s" % text
    dod = ("the requester's question is answered with evidence - quote the command, the file or "
           "the source that settles it - and the answer is written back to the ledger item")
    cmd = ["python3", WORK_CLI, "add",
           "--project", project, "--title", title, "--dod", dod,
           "--why", "%s (message %s from %s at %s)" % (why, row["sid"], row["from_number"], row["date_sent"]),
           "--priority", "3", "--source", "owner-sms"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = (p.stdout or "").strip()
    m = re.search(r'"(?:id|item)":\\s*(\\d+)', out)
    if not m:
        print("    work.py add said: %s" % (out[:160] or p.stderr[:160]))
        return None
    return {"id": int(m.group(1)), "project": project, "already": "already-filed" in out}


def _ack_owner_request(phone: str, filed: dict, body: str) -> None:
    """Send the owner a one-line acknowledgement. OFF unless AITEXT_ACK_OWNER_REQUESTS=1.

    WRITTEN BUT NOT ENABLED, deliberately: nothing in this system sends the owner anything until
    he has approved that behaviour, and he has not. See
    ~/code/harness-config/docs/outbound-comms-hard-stop.md.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("textsend", str(Path.home() / "bin" / "textsend.py"))
        ts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ts)
        if filed.get("already"):
            body_out = "Already on it (%s#%d)." % (filed["project"], filed["id"])
        else:
            body_out = "Got it - filed as %s#%d." % (filed["project"], filed["id"])
        ts.send(phone, body_out, dry_run=False)
        print("    acknowledged to the owner")
    except Exception as exc:
        print(f"    ack failed: {type(exc).__name__}: {exc}")
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")

    if "_file_owner_request" in src:
        print("already wired; nothing to do")
        return 0
    if ANCHOR not in src:
        raise SystemExit("ERROR: could not find the `allow == \"never\"` anchor - refusing to guess")
    src = src.replace(ANCHOR, NEW, 1)

    # the helpers go after the last top-level def, before the CLI section if there is one
    markers = ["\ndef main() -> int:", "\n# --------------------------------------------------------------------------- #\n# cli"]
    for mk in markers:
        if mk in src:
            src = src.replace(mk, HELPERS + mk, 1)
            break
    else:
        src = src + HELPERS

    if "\nimport re\n" not in src:
        src = re.sub(r"^import os$", "import os\nimport re", src, count=1, flags=re.M)
    if "\nimport subprocess\n" not in src:
        src = re.sub(r"^import re$", "import re\nimport subprocess", src, count=1, flags=re.M)

    for need in ("def _file_owner_request", "def _is_owner_number", "def _ack_owner_request",
                 "AITEXT_ACK_OWNER_REQUESTS"):
        if need not in src:
            raise SystemExit("ERROR: %r missing from the rewritten file - aborting" % need)

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-owner-text-ledger-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== PROOF: the new path is importable and the owner predicate is exact ===")
    probe = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("r", "/home/zabz/bin/sms-responder.py")
m = importlib.util.module_from_spec(spec); sys.modules["r"] = m; spec.loader.exec_module(m)
print("  _is_owner_number(owner row) ->", m._is_owner_number({"relationship": "owner"}, "+18483897895"))
print("  _is_owner_number(friend)    ->", m._is_owner_number({"relationship": "friend"}, "+18483885257"))
print("  _guess_project('fix the website portal') ->", m._guess_project("fix the website portal"))
print("  _guess_project('random words')          ->", m._guess_project("random words"))
print("  ack gated by env, currently:",
      "ON" if __import__("os").environ.get("AITEXT_ACK_OWNER_REQUESTS") == "1" else "OFF")
'''
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or (r.stderr or "").strip()[-900:])
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
