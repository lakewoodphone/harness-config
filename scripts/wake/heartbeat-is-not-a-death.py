#!/usr/bin/env python3
"""Patch autonomy-status.sh: a spent daily cap is not a dead dispatcher.

WHY (measured 2026-10-14 14:19Z on secratary-cloud)

`autonomy-status.sh` printed, as its FIRST problem:

    PROBLEMS:
      - the dispatcher heartbeat is 183.4 minutes old (>15) - nothing can revive work

and it was not true. `~/.sms-inbox/wake-heartbeat` is written when a RELEASE happens, so the
file stops ageing whenever nothing is being released - which is exactly what a working cap
looks like. The dispatcher's own liveness is a different file: `wake-fanout.log`, appended
every minute. At that moment it read, to the minute:

    2026-10-14T14:19:02Z skip: nothing claimable; procs=0 gate={"gate": "daily-cap",
      "blocking_detail": "daily_cap: 150/150 releases today", "claimable_when_open": 58}

with `sources-heartbeat` 12.2 minutes old and `in flight 0 dispatch process(es)`. So the
system was ALIVE and GATED - the daily cap of 150 releases was spent at 11:16Z and the loop
had been correctly idle for three hours - while the one command whose job is to say what the
system is doing called it dead. This is the failure this file's own IDLE block was written to
fix for the queue ("a working guard in the PROBLEMS list is how a PROBLEMS list stops being
read"), one file further along.

WHAT THIS DOES

* measures `wake-fanout.log` as well, and records its last line;
* when the release heartbeat is old but the fan-out log is current (<= 5 min), says what the
  fan-out last said (the gate) instead of raising a problem - and prints it as
  `no release     : the dispatcher is alive and gated - <last fan-out line>`;
* only calls the dispatcher dead when BOTH are stale, and then says both ages.

Read-only tool, so the blast radius is one line of output either way. The live file is backed
up beside itself before the write (the pattern `scripts/wake/honest-idle-line.py` set), and the
patch refuses rather than half-writes: it verifies the source text it is replacing, checks the
result parses, and tells you if it was already applied.

USAGE
    heartbeat-is-not-a-death.py [PATH] [--check]
    PATH defaults to /home/zabz/bin/autonomy-status.sh on the authority.

EXIT
    0 applied (or already applied, or --check found nothing to do); 2 refused, with the reason.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys

TARGET = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "/home/zabz/bin/autonomy-status.sh"
CHECK = "--check" in sys.argv

OLD_PROBLEM = '''if wake_age is None or wake_age > 15:
    note_problem("the dispatcher heartbeat is %s minutes old (>15) - nothing can revive work"
                 % (wake_age if wake_age is not None else "missing"))
'''

NEW_PROBLEM = '''# THE RELEASE HEARTBEAT IS WRITTEN BY A RELEASE, SO A SPENT CAP LOOKS LIKE A DEATH.
# Measured 2026-10-14 14:19Z: this raised "the dispatcher heartbeat is 183.4 minutes old (>15) -
# nothing can revive work" while wake-fanout.sh was running every minute printing
# `skip: nothing claimable ... gate: daily-cap, daily_cap: 150/150 releases today`, and the
# sources heartbeat was 12 min old. The dispatcher's OWN liveness is the fan-out log, which is
# appended every minute whether or not anything is released.
fanout_age = age_min(fanout)
fanout_last = ""
try:
    fanout_last = (open(fanout, encoding="utf-8", errors="replace").read().splitlines() or [""])[-1].strip()[:180]
except Exception:
    fanout_last = ""
out["liveness"]["fanout_heartbeat_age_min"] = fanout_age
out["liveness"]["fanout_last"] = fanout_last
if wake_age is None or wake_age > 15:
    if fanout_age is not None and fanout_age <= 5:
        # ALIVE AND GATED, NOT DEAD. Nothing has been released and nothing needs to be: the
        # fan-out is running this minute and its own last line says why it started nothing.
        out["liveness"]["no_release_because"] = fanout_last or "the fan-out log says nothing yet"
    else:
        note_problem("the dispatcher is DEAD: no release for %s min and the fan-out log is %s min old"
                     % (wake_age if wake_age is not None else "missing",
                        fanout_age if fanout_age is not None else "missing"))
'''

OLD_PRINT = '''print("  liveness       : dispatcher heartbeat %s min, sources heartbeat %s min" % (
    out.get("liveness", {}).get("dispatcher_heartbeat_age_min"),
    out.get("liveness", {}).get("sources_heartbeat_age_min")))
'''

NEW_PRINT = '''print("  liveness       : dispatcher heartbeat %s min (fan-out log %s min), sources heartbeat %s min" % (
    out.get("liveness", {}).get("dispatcher_heartbeat_age_min"),
    out.get("liveness", {}).get("fanout_heartbeat_age_min"),
    out.get("liveness", {}).get("sources_heartbeat_age_min")))
if out.get("liveness", {}).get("no_release_because"):
    print("  no release     : the dispatcher is alive and gated - %s"
          % out["liveness"]["no_release_because"])
'''


def refute(reason: str) -> None:
    print("REFUSED: %s" % reason)
    raise SystemExit(2)


def main() -> None:
    if not os.path.exists(TARGET):
        refute("no such file: %s" % TARGET)
    src = open(TARGET, encoding="utf-8").read()

    already = "fanout_heartbeat_age_min" in src
    if CHECK:
        print("checked %s: %s" % (TARGET, "already applied" if already else "NOT applied"))
        raise SystemExit(0)
    if already and "no_release_because" in src:
        print("already applied: %s - nothing to do" % TARGET)
        raise SystemExit(0)

    for name, old in (("problem block", OLD_PROBLEM), ("liveness print", OLD_PRINT)):
        if src.count(old) != 1:
            refute("the %s this patch replaces appears %d time(s), not once - the file has moved on; "
                   "read it before patching" % (name, src.count(old)))

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = "%s.bak-heartbeat-alive-%s" % (TARGET, stamp)
    shutil.copy2(TARGET, backup)

    patched = src.replace(OLD_PROBLEM, NEW_PROBLEM).replace(OLD_PRINT, NEW_PRINT)
    if patched == src:
        refute("the substitution changed nothing")

    tmp = TARGET + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(patched)
    syntax = subprocess.run(["bash", "-n", tmp], capture_output=True, text=True)
    if syntax.returncode != 0:
        os.unlink(tmp)
        refute("the patched file does not parse: %s" % (syntax.stderr.strip()[:300]))

    os.replace(tmp, TARGET)
    print("patched %s (backup %s)" % (TARGET, backup))

    run = subprocess.run(["bash", TARGET], capture_output=True, text=True, timeout=180)
    print("--- run, exit %d ---" % run.returncode)
    for line in run.stdout.splitlines():
        if "liveness" in line or "no release" in line or "PROBLEMS" in line or line.startswith("    -"):
            print(line)
    if run.returncode != 0:
        refute("the patched script exited %d - restore %s" % (run.returncode, backup))
    print("OK: exit 0, and the two lines above are what it now says")


if __name__ == "__main__":
    main()
