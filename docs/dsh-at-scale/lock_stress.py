"""Prove the rewritten journal lock: mutual exclusion, kill-safety, and release.

Run:  python C:\\Users\\ezabz\\code\\_dsh-scale\\lock_stress.py
It imports journal.py by path and drives acquire_lock/release_lock in real child
processes, because the failure mode being fixed (two writers inside the critical
section) only appears across process boundaries.
"""
import importlib.util
import os
import subprocess
import sys
import time

TOOLS = r"C:\Users\ezabz\code\harness-config\journal\tools\journal.py"


def load():
    spec = importlib.util.spec_from_file_location("journal_under_test", TOOLS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def child(hold_seconds: float, tag: str):
    """Acquire, hold, release -- printing a machine-checkable timeline."""
    j = load()
    ok, token = j.acquire_lock("stress-" + tag, wait=30.0)
    if not ok:
        print("%s REFUSED" % tag, flush=True)
        return 2
    print("%s ACQUIRED %.3f" % (tag, time.time()), flush=True)
    time.sleep(hold_seconds)
    print("%s RELEASED %.3f" % (tag, time.time()), flush=True)
    j.release_lock(token)
    return 0


def run_children(n, hold, label):
    procs = []
    for i in range(n):
        p = subprocess.Popen([sys.executable, __file__, "child", str(hold), "c%d" % i],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(p)
    lines = []
    for p in procs:
        out, _ = p.communicate(timeout=hold * n + 120)
        lines.extend(l for l in out.splitlines() if l.strip())
    acquired = {}
    released = {}
    for l in lines:
        parts = l.split()
        if len(parts) >= 3 and parts[1] == "ACQUIRED":
            acquired[parts[0]] = float(parts[2])
        elif len(parts) >= 3 and parts[1] == "RELEASED":
            released[parts[0]] = float(parts[2])
    for l in lines:
        print("   ", l)

    ok = True
    if len(acquired) != n:
        print("  FAIL %s: only %d/%d acquired" % (label, len(acquired), n))
        ok = False
    # Overlap test: no child may acquire before another child released.
    spans = sorted((acquired[k], released.get(k, 1e18)) for k in acquired)
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1] - 1e-6:
            print("  FAIL %s: %d and %d overlapped -- TWO WRITERS INSIDE" % (label, i - 1, i))
            ok = False
    if ok:
        print("  PASS %s: %d writers, zero overlap" % (label, n))
    return ok


def kill_safety():
    """A writer killed mid-hold must not wedge the journal (kernel releases it)."""
    j = load()
    p = subprocess.Popen([sys.executable, __file__, "holder"], stdout=subprocess.PIPE, text=True)
    time.sleep(3.0)
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    t0 = time.time()
    ok, token = j.acquire_lock("kill-safety", wait=20.0)
    dt = time.time() - t0
    if ok:
        print("  PASS kill-safety: lock taken %.2fs after the holder was force-killed" % dt)
        j.release_lock(token)
        return True
    print("  FAIL kill-safety: lock still blocked %.2fs after the holder died" % dt)
    return False


HOLDER = """
import importlib.util, time
spec = importlib.util.spec_from_file_location("j", r"%s")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ok, tok = m.acquire_lock("stuck-holder", wait=5.0)
print("HOLDER", ok, flush=True)
time.sleep(300)
""" % TOOLS


def holder():
    j = load()
    ok, token = j.acquire_lock("holder", wait=5.0)
    print("HOLDER acquired=%s" % ok, flush=True)
    time.sleep(300)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "child":
        sys.exit(child(float(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) > 1 and sys.argv[1] == "holder":
        holder()
        sys.exit(0)
    print("== journal lock stress ==")
    a = run_children(3, 2.0, "3-writer")
    b = kill_safety()
    print("RESULT:", "PASS" if (a and b) else "FAIL")
    sys.exit(0 if (a and b) else 1)
