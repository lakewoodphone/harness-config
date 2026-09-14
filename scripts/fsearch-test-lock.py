"""Prove the single-instance lock refuses an overlap, without running a real walk."""
import os
import subprocess
import sys
import time

FSEARCH = os.path.join(os.path.expanduser("~"), ".fsearch")
REFRESH = os.path.join(FSEARCH, "refresh.py")
LOCK = os.path.join(FSEARCH, "refresh.lock")

# 1. no lock -> the refusal function permits a run
sys.path.insert(0, FSEARCH)
import importlib.util
spec = importlib.util.spec_from_file_location("r", REFRESH)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

if os.path.exists(LOCK):
    os.remove(LOCK)
refusal = r._acquire_lock()
print("no lock held  -> refusal:", refusal or "none (run permitted)")
assert refusal is None, refusal
r._release_lock()
print("lock released -> exists:", os.path.exists(LOCK))

# 2. a lock held by a LIVE process must refuse
with open(LOCK, "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))          # this process is alive
refusal = r._acquire_lock()
print("live lock held -> refusal:", refusal or "NONE (BAD)")
assert refusal and "already running" in refusal, refusal
os.remove(LOCK)

# 3. a lock held by a DEAD pid must be treated as stale and taken over
with open(LOCK, "w", encoding="utf-8") as fh:
    fh.write("999999")
refusal = r._acquire_lock()
print("stale lock     -> refusal:", refusal or "none (run permitted, correct)")
assert refusal is None, refusal
r._release_lock()

print("\nPASS: live overlap refused, stale lock recovered, lock released cleanly")
