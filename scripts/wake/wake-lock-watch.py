#!/usr/bin/env python3
"""Record WHO holds the wake store's write lock, at the moment a writer is refused.

WHY. Measured 2026-10-18: three shifts died at 04:17-04:21 and another at 05:14 with
`lease not renewed ... wake: database error: database is locked`. Item 565 removed one holder
(reconcile-sent-status committed per row) and `wake.py` now waits 30 s, and it STILL happens.
SQLite keeps no history of a lock holder, so the only way to name the next one is to catch it in
the act. Ledger item 584 asks for exactly that.

DELIBERATELY ADDITIVE. This does not touch wake-dispatch.sh. The last time this session edited the
lease path without an end-to-end proof it cost two shifts (§68), and a watcher that can fail
silently is strictly better than a dispatcher that can fail loudly.

HOW IT WORKS. For a bounded window it repeatedly tries `BEGIN IMMEDIATE` with a short busy timeout --
the same lock a writer needs. When that fails it records:
  * the raw error,
  * every PID with the database open (scanned from /proc/*/fd, which needs no lsof),
  * each holder's command line.

OUTPUT. One line per failure into ~/.sms-inbox/wake-lock.log, plus a compact stdout summary so a cron
log shows that it ran. Exits 0 always: a watcher that fails must never look like a finding.

USAGE
    wake-lock-watch.py                # 20 probes, 3 s apart (~60 s), the cron default
    wake-lock-watch.py --probes 5 --gap 1
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.environ.get("WAKE_LOCK_DB") or "/root/.sms-inbox/inbox.db")
LOG = Path(os.environ.get("WAKE_LOCK_LOG") or "/root/.sms-inbox/wake-lock.log")
BUSY_MS = int(os.environ.get("WAKE_LOCK_BUSY_MS", "300"))


def holders(path: Path) -> list[tuple[int, str]]:
    """PIDs with `path` open, and their command lines. No lsof dependency."""
    target = os.path.realpath(str(path))
    out = []
    me = os.getpid()
    for pid_dir in os.listdir("/proc"):
        if not pid_dir.isdigit():
            continue
        if int(pid_dir) == me:
            continue   # the watcher holds the file open too; listing itself is noise
        fd_dir = "/proc/%s/fd" % pid_dir
        try:
            for fd in os.listdir(fd_dir):
                try:
                    if os.path.realpath(os.path.join(fd_dir, fd)) == target:
                        try:
                            cmd = open("/proc/%s/cmdline" % pid_dir, "rb").read()
                            cmd = cmd.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                        except OSError:
                            cmd = "?"
                        out.append((int(pid_dir), cmd[:200]))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes", type=int, default=int(os.environ.get("WAKE_LOCK_PROBES", "20")))
    ap.add_argument("--gap", type=float, default=float(os.environ.get("WAKE_LOCK_GAP", "3")))
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()

    if not Path(a.db).exists():
        print("wake-lock-watch: no store at %s" % a.db, file=sys.stderr)
        return 0

    failures = 0
    for n in range(a.probes):
        try:
            c = sqlite3.connect(a.db, timeout=max(BUSY_MS / 1000.0, 0.05))
            c.execute("PRAGMA busy_timeout=%d" % BUSY_MS)
            c.execute("BEGIN IMMEDIATE")
            c.execute("ROLLBACK")
            c.close()
        except sqlite3.OperationalError as exc:
            failures += 1
            when = datetime.now(timezone.utc).isoformat(timespec="seconds")
            hs = holders(Path(a.db))
            line = "%s LOCKED %s | holders: %s\n" % (
                when, exc,
                " ; ".join("pid %d %s" % (p, c_) for p, c_ in hs) or "(none visible)")
            try:
                with open(LOG, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError as log_exc:
                print("wake-lock-watch: cannot write %s: %s" % (LOG, log_exc), file=sys.stderr)
            print("LOCKED %s holders=%d" % (exc, len(hs)))
        if n < a.probes - 1:
            time.sleep(a.gap)

    if not failures:
        print("quiet: %d probe(s), the write lock was free every time" % a.probes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
