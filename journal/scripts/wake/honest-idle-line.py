#!/usr/bin/env python3
"""Patch autonomy-status.sh: the IDLE line must distinguish gated from stalled.

Measured 2026-09-30 on the authority. All seven rows in state `new` were gated by a `not_before` days
into the future (two of them by 28 days), and this line said:

    IDLE: 7 row(s) waiting and no cap in force - the next cron tick should claim

while `wake-fanout.sh` had spent 55 minutes starting shifts that could not claim. It reasoned only about
CAPS, so a `not_before` gate was invisible to it: a healthy gated queue and a stall printed the same
sentence, which is the one failure this system's own state document names as the pattern to check first.

After this patch the line has three distinct states: claimable now, gated until a named time, and a gate
that could not be read. Fails closed: if the expected block is not found, nothing is written.
"""
import os
import shutil
import sys
import time

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/home/zabz/bin/autonomy-status.sh"
NEW_BLOCK = '''    # A WAITING COUNT CANNOT DISTINGUISH GATED FROM STALLED. Measured 2026-09-30: seven rows waiting,
    # every one gated days into the future (two by 28 days), while this line said "the next cron tick
    # should claim" - so a healthy gated queue and a 55-minute stall printed the same sentence. Ask the
    # store when anything could ACTUALLY be claimed, and say that instead.
    nc = None
    try:
        raw_nc = subprocess.run(
            ["python3", os.environ.get("WAKE_NEXTCLAIM", "/home/zabz/bin/wake-nextclaim.py"), "--json"],
            capture_output=True, text=True, timeout=60).stdout
        d_nc = json.loads(raw_nc)
        if d_nc.get("ok"):
            nc = d_nc
    except Exception:
        nc = None
    if not waiting:
        print("  IDLE          : healthy - the queue is EMPTY (no new rows)")
    elif nc is None:
        print("  IDLE          : %d row(s) waiting; the claim gate could NOT be read" % waiting)
    elif nc.get("claimable_now"):
        print("  IDLE          : %d row(s) CLAIMABLE NOW (ids %s) and nothing running - the next cron tick should claim"
              % (nc["claimable_now"], ",".join(str(i) for i in nc.get("claimable_ids", [])[:6])))
    else:
        print("  IDLE          : healthy - %d row(s) waiting, NONE claimable now; earliest %s (%s)"
              % (waiting, nc.get("earliest") or "unknown", (nc.get("earliest_subject") or "")[:40]))'''

src = open(TARGET, encoding="utf-8").read()
if "wake-nextclaim" in src:
    sys.exit("SKIP: already patched (wake-nextclaim present)")
lines = src.split("\n")

j = k = None
for i, line in enumerate(lines):
    if 'if waiting and w.get("caps_in_force"):' in line:
        j = i
    if "the queue is EMPTY (no new rows)" in line:
        k = i
if j is None or k is None:
    sys.exit("FAIL: the IDLE block was not found in %s - nothing written" % TARGET)
if not (0 < k - j == 7):
    sys.exit("FAIL: unexpected block shape (j=%s k=%s) - nothing written" % (j, k))
if "caps_in_force" not in lines[j]:
    sys.exit("FAIL: the block head does not mention caps_in_force - nothing written")
if not lines[k].strip().startswith('print("  IDLE'):
    sys.exit("FAIL: the block tail is not an IDLE print - nothing written")

stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
backup = "%s.bak-honest-idle-%s" % (TARGET, stamp)
shutil.copy2(TARGET, backup)

new_lines = lines[:j] + NEW_BLOCK.split("\n") + lines[k + 1:]
tmp = TARGET + ".tmpnew"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(new_lines))
os.chmod(tmp, os.stat(TARGET).st_mode)
os.replace(tmp, TARGET)
print("patched %s -> backup %s (%d lines replaced by %d)"
      % (TARGET, backup, k - j + 1, len(NEW_BLOCK.split("\n"))))
