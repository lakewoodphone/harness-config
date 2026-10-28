#!/usr/bin/env python3
"""One-shot: make estate-alerts-to-journal.py exit non-zero when a filing was refused.

MEASURED 2026-10-28
-------------------
The bridge is the consumer that turns a sustained estate CRIT into a journal `pain` entry, and
it is the last link between "the monitor knows" and "a session will pick it up". At 16:22:00Z it
logged:

    would file 1 entry:
      public_health_status  crit  1.0  streak=5  episode 1
      FAILED public_health_status  REFUSING to write P14347: this id is above everything this
      machine can see, and it has just reserved P14347..P14410

...and then `return 0`. systemd recorded "Finished", the unit went green, and nothing was filed.
`authority_wal_mb` had been sustained-critical since 2026-10-27T05:24Z (1048 runs) and its
episode was never filed at all; three earlier occurrences (P4442, P7499, P9035 on 15/18/19 Oct)
WERE filed, and nothing ever resolved them.

So the defect is the same one this estate keeps paying for: a step that reports success when its
work did not happen. A refusal must be an open item.

The ledger is already correct -- `ledger[mid]` is set only `if ok`, so a refused episode is not
marked filed and will retry on the next run. Only the exit code was lying.
"""
import shutil
import sys
import time

PATH = "/usr/local/bin/estate-alerts-to-journal.py"
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
BAK = f"{PATH}.bak-exitcode-{STAMP}"

ANCHOR = """    save_ledger(ledger)
    if a.json:
        print(json.dumps(out, indent=2))
    return 0"""

REPLACE = """    save_ledger(ledger)
    if a.json:
        print(json.dumps(out, indent=2))
    failed = [r for r in out.get("applied", []) if not r.get("ok")]
    if failed:
        # A refusal is an open item, not an event. MEASURED 2026-10-28: the journal's id
        # allocator refused P14347 ("this id is above everything this machine can see, and it
        # has just reserved P14347..P14410") and this function still returned 0, so systemd
        # recorded "Finished" for a run that filed nothing -- while authority_wal_mb had been
        # sustained-critical for 35 hours. The ledger is already safe (an item is only marked
        # filed when filing succeeded), so a non-zero exit here only makes the failure visible
        # and lets `systemctl --failed` carry it.
        print("\\nFAILED to file %d episode(s): %s"
              % (len(failed), ", ".join(r.get("metric", "?") for r in failed)))
        return 1
    return 0"""


def main() -> int:
    src = open(PATH, encoding="utf-8").read()
    if "FAILED to file %d episode(s)" in src:
        print("ALREADY PATCHED -- refusing to apply twice")
        return 1
    n = src.count(ANCHOR)
    if n != 1:
        print(f"REFUSED -- anchor matched {n} times, expected exactly 1")
        return 1
    new = src.replace(ANCHOR, REPLACE, 1)
    compile(new, PATH, "exec")
    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"PATCHED {PATH} (backup {BAK})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
