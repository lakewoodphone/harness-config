#!/usr/bin/env python3
"""Patch wake-fanout.sh: keep the failure evidence, and record the gate reason.

Two defects, both measured live on 2026-09-30:

  1. `rm -rf "$INST"` on a failed claim deleted wake-ssh.log, claim.json and prompt.txt - the only record
     of WHY a claim failed. Eleven consecutive ticks failed between 14:00Z and 14:45Z and left nothing
     behind, so a 55-minute stall was undiagnosable.
  2. The gate reason was computed by wake.py and thrown away, so no log line said "these rows are gated
     until a date".

Fails closed: if the expected block is not found exactly once, nothing is written.
"""
import os
import shutil
import sys
import time

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/home/zabz/bin/wake-fanout.sh"
NEW_BLOCK = '''  else
    # KEEP THE EVIDENCE, AND SAY WHY IT FAILED. This used to be `rm -rf "$INST"`, which deleted
    # wake-ssh.log, claim.json and prompt.txt - the only record of WHY a claim failed. Measured
    # 2026-09-30: eleven consecutive ticks failed to claim over 55 minutes and left nothing behind.
    # A failed instance is now MOVED ASIDE, never deleted here; cleanup is by age, separately.
    FAILED_DIR="$INST_ROOT/../wake-failed"
    mkdir -p "$FAILED_DIR" 2>/dev/null || true
    kept="left in place"
    if mv "$INST" "$FAILED_DIR/$(basename "$INST")-$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null; then
      kept="kept in $FAILED_DIR"
    fi
    gate=$(python3 "${WAKE_NEXTCLAIM:-/home/zabz/bin/wake-nextclaim.py}" --json 2>/dev/null || true)
    say "fanout: shift #$started (pid $pid) did not claim - stopping this run ($kept)"
    say "fanout: gate: ${gate:-unknown}"
    note "started shift #$started pid=$pid claimed=no; stopping; evidence=$kept; gate=${gate:-unknown}"
    break
  fi'''

src = open(TARGET, encoding="utf-8").read()
lines = src.split("\n")

idx = None
for i, line in enumerate(lines):
    if "did not claim - stopping this run" in line and line.strip().startswith("say "):
        idx = i
        break
if idx is None:
    sys.exit("FAIL: the 'did not claim' line was not found in %s - nothing written" % TARGET)

start, end = idx - 1, idx + 4          # the else ... fi block
old = lines[start:end + 1]
if old[0].strip() != "else":
    sys.exit("FAIL: line above the say is %r, expected 'else' - nothing written" % old[0])
if old[5].strip() != "fi":
    sys.exit("FAIL: line after 'break' is %r, expected 'fi' - nothing written" % old[5])
if not any('rm -rf "$INST"' in l for l in old):
    sys.exit("FAIL: the rm -rf line is not in the block - nothing written")

if "wake-failed" in src:
    sys.exit("SKIP: already patched (wake-failed present)")

stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
backup = "%s.bak-keepfailure-%s" % (TARGET, stamp)
shutil.copy2(TARGET, backup)

new_lines = lines[:start] + NEW_BLOCK.split("\n") + lines[end + 1:]
tmp = TARGET + ".tmpnew"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(new_lines))
os.chmod(tmp, os.stat(TARGET).st_mode)
os.replace(tmp, TARGET)
print("patched %s -> backup %s (%d lines replaced by %d)"
      % (TARGET, backup, len(old), len(NEW_BLOCK.split("\n"))))
