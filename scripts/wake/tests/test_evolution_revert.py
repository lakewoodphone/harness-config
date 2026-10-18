#!/usr/bin/env python3
"""Prove the revert on a throwaway checkout. Never touches /opt/company.

Plants the exact condition the code exists for: a file that has REGRESSED on disk, and a
code snapshot holding its last-known-good content. Then it calls the real `_restore_snapshot`
and checks the bytes. Every case is a gate: a revert that restores nothing, or that can be
talked into writing outside the checkout, must fail this script.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="revertproof-"))
SNAPS = ROOT / "data" / "code_snapshots"
SNAPS.mkdir(parents=True)

GOOD = "def f():\n    return 'GOOD'\n"
REGRESSED = "def f():\n    return 'REGRESSED'\n"
TARGET = ROOT / "app" / "thing.py"
TARGET.parent.mkdir(parents=True)
TARGET.write_text(REGRESSED, encoding="utf-8")

(SNAPS / "abc123.json").write_text(json.dumps({
    "id": "abc123", "label": "pre-apply", "created_at": "2026-10-18T00:00:00Z",
    "files": {"app/thing.py": {"content": GOOD, "sha256": "x"}},
}), encoding="utf-8")

(SNAPS / "evil.json").write_text(json.dumps({
    "id": "evil", "files": {"../outside.py": {"content": "pwn"}},
}), encoding="utf-8")

(SNAPS / "empty.json").write_text(json.dumps({"id": "empty", "files": {}}), encoding="utf-8")

# The module reads CODE_CHECKOUT_ROOT at import time, which is why it must be set first.
os.environ["CODE_CHECKOUT_ROOT"] = str(ROOT)
sys.path.insert(0, "/opt/company")
from app.services.evolution_verifier import _restore_snapshot  # noqa: E402

fail = 0

# 1. the regression is restored
restored = _restore_snapshot("abc123")
content = TARGET.read_text(encoding="utf-8")
print("restore returned: %r" % (restored,))
print("file now reads : %r" % content)
if restored != ["app/thing.py"] or content != GOOD:
    print("FAIL: the regressed file was not restored to its snapshot content")
    fail += 1

# 2. a missing snapshot must raise, not return []
try:
    _restore_snapshot("nosuchid")
    print("FAIL: a missing snapshot returned normally -- a revert could silently do nothing")
    fail += 1
except FileNotFoundError as exc:
    print("PASS missing snapshot raises FileNotFoundError: %s" % exc)

# 3. a path outside the checkout must be refused
try:
    _restore_snapshot("evil")
    print("FAIL: a snapshot escaped the checkout")
    fail += 1
except ValueError as exc:
    print("PASS traversal refused: %s" % exc)

# 4. a snapshot with no files must raise
try:
    _restore_snapshot("empty")
    print("FAIL: an empty snapshot returned normally")
    fail += 1
except ValueError as exc:
    print("PASS empty snapshot refused: %s" % exc)

# 5. the temp copy written beside the target must be gone (no .revert.tmp debris)
debris = list(TARGET.parent.glob("*.revert.tmp"))
if debris:
    print("FAIL: revert left temp files behind: %s" % debris)
    fail += 1
else:
    print("PASS no .revert.tmp debris left behind")

print("\n%s  %d failure(s)   (throwaway root: %s)" % (
    "RESULT: FAIL" if fail else "RESULT: PASS", fail, ROOT))
sys.exit(1 if fail else 0)
