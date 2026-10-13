"""Test sync.py's refusal-to-journal bridge WITHOUT touching the real journal.

Builds a throwaway repo containing a real copy of journal.py, imports sync.py from it, and calls
the refusal path directly. Any journal entry it files lands in the throwaway tree, so the estate's
permanent record is untouched -- a test that writes to a real store is the defect `secretary-wake`
names, and this one deliberately does not.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL = Path(os.path.expanduser("~/code/harness-config"))
fake = Path(tempfile.mkdtemp(prefix="syncrepo-"))
(fake / "scripts").mkdir(parents=True)
(fake / "journal" / "tools").mkdir(parents=True)

shutil.copy2(REAL / "scripts" / "sync.py", fake / "scripts" / "sync.py")
shutil.copy2(REAL / "journal" / "tools" / "journal.py", fake / "journal" / "tools" / "journal.py")

dsh = fake / ".dsh"
dsh.mkdir()
os.environ["DSH_HOME"] = str(dsh)

spec = importlib.util.spec_from_file_location("syncmod", fake / "scripts" / "sync.py")
syncmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(syncmod)
except SystemExit:
    pass

print("REPO seen by the module :", syncmod.REPO)
print("DSH_HOME seen           :", syncmod.DSH_HOME)
assert str(syncmod.REPO) == str(fake), "module did not resolve to the throwaway repo"

print()
print("=== refusal #1: the generated rows are stale ===")
r1 = syncmod.report_generated_step(1, "--check: DRIFT -- presets.generated.patch.yml")
print("returned:", r1, "(must be False -- the profile layer is NOT published)")

entries = list((fake / "journal" / "entries").rglob("*.md"))
print("journal entries filed  :", len(entries))
if entries:
    txt = entries[0].read_text(encoding="utf-8")
    print("  title :", txt.splitlines()[2][:110] if len(txt.splitlines()) > 2 else "?")
    print("  names the FIX:", "make-preset-rows.mjs --install" in txt)
    print("  names the CHECKER:", "preset-drift.py" in txt)

print()
print("=== refusal #2: the SAME reason again -- must not file a second time ===")
syncmod.report_generated_step(1, "--check: DRIFT -- presets.generated.patch.yml")
print("journal entries now    :", len(list((fake / "journal" / "entries").rglob("*.md"))), "(must still be 1)")

print()
print("=== refusal #3: a DIFFERENT reason -- must file again ===")
syncmod.report_generated_step(2, "node: command not found")
print("journal entries now    :", len(list((fake / "journal" / "entries").rglob("*.md"))), "(must be 2)")

print()
print("=== and a clean run must file nothing ===")
before = len(list((fake / "journal" / "entries").rglob("*.md")))
r = syncmod.report_generated_step(0, "managed block UP TO DATE")
after = len(list((fake / "journal" / "entries").rglob("*.md")))
print("returned:", r, "(must be True)")
print("entries before/after   :", before, "/", after, "(must be equal)")

print()
print("=== the real journal was NOT touched ===")
real_count = len(list((REAL / "journal" / "entries").rglob("*.md")))
print("real harness-config entries:", real_count)
print("throwaway:", str(fake))
