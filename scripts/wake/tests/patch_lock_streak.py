#!/usr/bin/env python3
"""Only record a lock that PERSISTS, not one that merely overlaps.

MEASURED 2026-10-18 05:20:05, the watcher's first real capture:

    LOCKED database is locked | holders: pid 504337 sms-responder.py run --send ...
      ; pid 504373 sms-inbox.py sync --pages 3 ; pid 504634 wake.py stats --json
      ; pid 504668 wake.py heartbeat 1167 ...

Four processes with the database open, none of them obviously pathological: `_record()` in
sms-responder commits per row, `sms-inbox.py` batches then commits, and `wake.py stats` only reads
(`_ensure` early-returns once the columns exist -- verified by reading it, not assumed).

The problem is the watcher's own threshold. It probes with a 300 ms busy timeout, so it flags ORDINARY
CONTENTION -- two writers overlapping for a third of a second -- while the failures that kill shifts
happen after **30 seconds**. A log full of ordinary overlap would be read as noise, and then the real
event would be missed in it.

THE FIX: record only when the lock survives `--streak` CONSECUTIVE probes (3 x 3 s = ~9 s by default),
and record the streak length so persistence is visible. Short overlaps are counted in the summary and
written nowhere.

Proven both ways: a 12-second planted lock must be logged with streak>=3, and a 1-second one must not.
"""
import io
import sys

P = "/root/bin/wake-lock-watch.py"

EDITS = [
    (P,
     '''    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()''',
     '''    ap.add_argument("--db", default=str(DB))
    # MEASURED 2026-10-18: with a 300 ms busy timeout this flagged ordinary contention (two writers
    # overlapping briefly) while the events that kill shifts happen after 30 seconds. Only a lock that
    # survives several consecutive probes is the pathological one worth a log line.
    ap.add_argument("--streak", type=int,
                    default=int(os.environ.get("WAKE_LOCK_STREAK", "3")),
                    help="consecutive failed probes before a lock is recorded")
    a = ap.parse_args()'''),
    (P,
     '''    failures = 0
    for n in range(a.probes):''',
     '''    failures = 0
    streak = 0
    logged = 0
    for n in range(a.probes):'''),
    (P,
     '''            c.execute("BEGIN IMMEDIATE")
            c.execute("ROLLBACK")
            c.close()
        except sqlite3.OperationalError as exc:
            failures += 1''',
     '''            c.execute("BEGIN IMMEDIATE")
            c.execute("ROLLBACK")
            c.close()
            streak = 0
        except sqlite3.OperationalError as exc:
            failures += 1
            streak += 1
            if streak < a.streak:
                # Ordinary overlap: remembered, not written. Writing these would bury the real event.
                if n < a.probes - 1:
                    time.sleep(a.gap)
                continue'''),
    (P,
     '''            line = "%s LOCKED %s | holders: %s\\n" % (
                when, exc,''',
     '''            logged += 1
            line = "%s LOCKED streak=%d %s | holders: %s\\n" % (
                when, streak, exc,'''),
    (P,
     '''    if not failures:
        print("quiet: %d probe(s), the write lock was free every time" % a.probes)''',
     '''    if not failures:
        print("quiet: %d probe(s), the write lock was free every time" % a.probes)
    elif not logged:
        print("transient only: %d of %d probe(s) refused, but never %d in a row - not recorded"
              % (failures, a.probes, a.streak))'''),
]

ok = True
for path, old, new in EDITS:
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED")
        continue
    if src.count(old) != 1:
        print("REFUSED: anchor found %d times: %r" % (src.count(old), old.splitlines()[0][:60]))
        ok = False
        continue
    out = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8").write(out)
    print("WROTE %s  %d -> %d chars" % (path, len(src), len(out)))
sys.exit(0 if ok else 1)
