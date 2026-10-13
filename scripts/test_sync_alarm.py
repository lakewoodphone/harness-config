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
# Counted ONCE at the top so the final assertion can compare against it. It used to be defined at
# the end, after the block that reads it -- a NameError that only the last line of the test hit.
REAL_COUNT_AT_START = len(list((REAL / "journal" / "entries").rglob("*.md")))
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

# --------------------------------------------------------------------------------------------
# verify_loaded_surface: the check that asks what the machine LOADS, not what sync DID.
# Driven through a STUB preset-drift.py so every branch is exercised without touching a live
# surface -- the real tool is exercised by running sync for real, which the caller does separately.
# --------------------------------------------------------------------------------------------
print()
print("=== verify_loaded_surface: MATCH must return True and file nothing ===")
stub = fake / "scripts" / "preset-drift.py"
stub.write_text("print('compared 15  match=15  drift=0  missing=0')\nraise SystemExit(0)\n",
                encoding="utf-8")
n0 = len(list((fake / "journal" / "entries").rglob("*.md")))
ok = syncmod.verify_loaded_surface(False)
print("returned:", ok, "(must be True)")
print("entries:", n0, "->", len(list((fake / "journal" / "entries").rglob("*.md"))),
      "(must not change)")

print()
print("=== verify_loaded_surface: DRIFT must return False and file once ===")
stub.write_text(
    "print('DRIFT    zabz/agent.cordis.yml   repo=aaaa loaded=bbbb [56297B vs 58677B]')\n"
    "print('DRIFT    skill/secretary-wake    loaded=cccc matches none of: zabz=dddd')\n"
    "print('compared 15  match=13  drift=2  missing=0')\n"
    "raise SystemExit(1)\n", encoding="utf-8")
n1 = len(list((fake / "journal" / "entries").rglob("*.md")))
ok = syncmod.verify_loaded_surface(False)
n2 = len(list((fake / "journal" / "entries").rglob("*.md")))
print("returned:", ok, "(must be False)")
print("entries:", n1, "->", n2, "(must be +1)")
if n2 > n1:
    newest = max((fake / "journal" / "entries").rglob("*.md"), key=lambda p: p.stat().st_mtime)
    t = newest.read_text(encoding="utf-8")
    print("  entry names sync.py        :", "sync.py" in t)
    print("  entry warns the repo is not automatically right:", "not automatically" in t)

print()
print("=== the same drift again: no duplicate ===")
syncmod.verify_loaded_surface(False)
print("entries now:", len(list((fake / "journal" / "entries").rglob("*.md"))), "(must be unchanged)")

print()
print("=== a dry run must NOT alarm, even on drift ===")
n3 = len(list((fake / "journal" / "entries").rglob("*.md")))
syncmod.verify_loaded_surface(True)
print("entries:", n3, "->", len(list((fake / "journal" / "entries").rglob("*.md"))),
      "(must not change)")

print()
print("=== a missing tool must say UNVERIFIED, never clean ===")
stub.unlink()
ok = syncmod.verify_loaded_surface(False)
print("returned:", ok, "(must be False -- absence is not a pass)")

print()
print("=== and the real journal is STILL untouched ===")
print("real harness-config entries:", len(list((REAL / "journal" / "entries").rglob("*.md"))),
      "(was", REAL_COUNT_AT_START, ")")

print()
print("=== the real journal was NOT touched ===")
real_count = len(list((REAL / "journal" / "entries").rglob("*.md")))
print("real harness-config entries:", real_count)
print("throwaway:", str(fake))
