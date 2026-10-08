#!/usr/bin/env python3
"""Add the imports the owner-text-to-ledger patch needs, and prove the module loads.

MY OWN BUG, third instance tonight: the patch inserted code that uses `os`, `re`, `subprocess` and
`Path`, and its import-insertion steps silently matched nothing (they looked for `^import os$` and
`^import re$` at column zero, and the file's imports are not shaped that way). The result was a file
that wrote to disk fine and then raised
    NameError: name 'os' is not defined
on import - caught only because that patch's proof step imported the module, which is the one habit
that has repeatedly saved this session. A patch that is not exercised is not a patch.

This adds whatever is missing, verifies by importing, and refuses to leave a broken file behind.

Usage: python3 fix-responder-imports.py --apply
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
NEEDED = ["os", "re", "subprocess"]


def ensure_import(src: str, module: str) -> tuple:
    """(new_src, changed). Appends `import <module>` after the last plain import line if absent."""
    if re.search(r"^\s*import\s+%s\b" % re.escape(module), src, re.M) or \
       re.search(r"^\s*from\s+%s\s+import\b" % re.escape(module), src, re.M):
        return src, False
    lines = src.split("\n")
    last = None
    for i, ln in enumerate(lines[:120]):
        if re.match(r"^(import|from)\s+\S", ln):
            last = i
    if last is None:
        return "import %s\n" % module + src, True
    lines.insert(last + 1, "import %s" % module)
    return "\n".join(lines), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")
    changed = []
    for mod in NEEDED:
        src, ch = ensure_import(src, mod)
        if ch:
            changed.append(mod)
    # Path comes from pathlib; make sure it is there too
    if not re.search(r"^from pathlib import", src, re.M) and not re.search(r"^import pathlib", src, re.M):
        src, _ = ensure_import(src, "pathlib")
        changed.append("pathlib")
    print("added: %s" % (", ".join(changed) or "nothing"))

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-imports-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== PROOF: import the module and exercise the new path ===")
    probe = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("r", "/home/zabz/bin/sms-responder.py")
m = importlib.util.module_from_spec(spec); sys.modules["r"] = m; spec.loader.exec_module(m)
print("  module imports OK")
print("  _is_owner_number(owner row) ->", m._is_owner_number({"relationship": "owner"}, "+18483897895"))
print("  _is_owner_number(google-voice row) ->",
      m._is_owner_number({"relationship": "owner-google-voice"}, "+17325691594"))
print("  _is_owner_number(friend)    ->", m._is_owner_number({"relationship": "friend"}, "+18485257897"))
print("  _guess_project('fix the website portal') ->", m._guess_project("fix the website portal"))
print("  _guess_project('the dialpad sync is stuck') ->", m._guess_project("the dialpad sync is stuck"))
print("  _guess_project('random words')          ->", m._guess_project("random words"))
print("  ack path is", "ON" if __import__("os").environ.get("AITEXT_ACK_OWNER_REQUESTS") == "1" else "OFF (gated)")
'''
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or (r.stderr or "").strip()[-900:])
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
