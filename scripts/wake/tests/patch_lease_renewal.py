#!/usr/bin/env python3
"""Three fixes around the lease-renewal kills measured at 04:17, 04:19 and 04:21 on 2026-10-18.

EVIDENCE
    wake-dispatch.log:
      04:17:51Z ERROR lease for wake #1170 not renewed - killing the session to avoid a double
                release: unknown
      04:19:40Z ERROR exited (rc=2) with wake #1169 still claimed - closing as failed
      04:21:21Z ERROR exited (rc=2) with wake #1123 still claimed - closing as failed
    and the warnings that precede them, at 01:50, 03:15 and 04:10:
      WARN heartbeat for wake #1123 could not renew (attempt 1, rc=2):
        wake: database error: database is locked; retrying while the lease has margin

So a transient `database is locked` on the wake store, repeated until the lease margin ran out, kills
real work. Three separate defects make that worse than it needs to be:

1. `wake.py:connect()` takes Python's sqlite3 DEFAULT 5-second busy timeout, so a write transaction
   held for six seconds is reported as a hard failure. Raised to 30 s: heartbeats and claims should
   WAIT, because waiting costs seconds and killing a shift costs a shift.

2. `cmd_heartbeat` returns **2** for `no-such-row` and `not-claimed`, while the dispatcher's own
   contract (`wake-dispatch.sh:1091`) says: "1 = the store itself says we do NOT hold this row...
   2 = transient". The dispatcher only survives that by string-matching the output. Exit codes are a
   contract; returning 2 for a known state makes every caller guess. Now returns 1 for both.

3. The kill message printed `unknown` because `LEASE_LOSS_REASON` was empty for the path taken, while
   `_LEASE_LAST_ERR` -- which held `wake: database error: database is locked` -- was discarded. The
   one line that explained the outage existed and was thrown away. It is now included.

Idempotent; parses before writing; refuses unless each anchor appears exactly once.
"""
import ast
import io
import sys

WAKE = "/root/bin/wake.py"
DISP = "/root/bin/wake-dispatch.sh"

PY_EDITS = [
    (WAKE,
     '''def connect() -> sqlite3.Connection:
    conn = inbox.connect()
    conn.isolation_level = None          # explicit transactions only''',
     '''def connect() -> sqlite3.Connection:
    conn = inbox.connect()
    # MEASURED 2026-10-18: the default 5 s busy timeout turned a transient
    # `database is locked` into a hard error, and a dispatcher heartbeat that cannot renew its
    # lease kills the shift (three died at 04:17-04:21). The wake store has many writers
    # (sources, fanout, mirror, responder, cost) and WAL cannot make writer-writer free.
    # Waiting is always cheaper here than losing a shift.
    conn.execute("PRAGMA busy_timeout=30000")
    conn.isolation_level = None          # explicit transactions only'''),
    (WAKE,
     '''        if row is None:
            sys.stdout.write(json.dumps({"ok": False, "id": args.id, "error": "no-such-row"}) + "\\n")
            return 2''',
     '''        if row is None:
            sys.stdout.write(json.dumps({"ok": False, "id": args.id, "error": "no-such-row"}) + "\\n")
            # 1, not 2: wake-dispatch.sh's contract is "1 = the store itself says we do not hold
            # this row; 2 = transient". A known state must not be reported as a transient fault
            # and left to a string match.
            return 1'''),
    (WAKE,
     '''        if row["state"] != "claimed":
            sys.stdout.write(json.dumps(
                {"ok": False, "id": args.id, "error": "not-claimed", "state": row["state"]}) + "\\n")
            return 2''',
     '''        if row["state"] != "claimed":
            sys.stdout.write(json.dumps(
                {"ok": False, "id": args.id, "error": "not-claimed", "state": row["state"]}) + "\\n")
            # See above: a known state is 1, not a transient error.
            return 1'''),
]

SH_EDITS = [
    (DISP,
     '''      OUTCOME_REASON="lease not renewed: ${LEASE_LOSS_REASON:-unknown}"
      log "ERROR lease for wake #$ID not renewed - killing the session to avoid a double release: ${LEASE_LOSS_REASON:-unknown}"''',
     '''      # MEASURED 2026-10-18: this printed "unknown" for three kills while the actual cause --
      # "wake: database error: database is locked" -- sat in _LEASE_LAST_ERR and was discarded.
      # A kill message that cannot say why is the same defect as a monitor that measures nothing.
      OUTCOME_REASON="lease not renewed: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}}"
      log "ERROR lease for wake #$ID not renewed - killing the session to avoid a double release: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}}"'''),
]


def apply(path, old, new, check_ast):
    src = io.open(path, encoding="utf-8").read()
    if new in src:
        print("ALREADY-PATCHED: %s" % path)
        return True
    if src.count(old) != 1:
        print("REFUSED: %s anchor found %d times" % (path, src.count(old)))
        return False
    out = src.replace(old, new, 1)
    if check_ast:
        try:
            ast.parse(out)
        except SyntaxError as exc:
            print("REFUSED: %s would not parse: %s" % (path, exc))
            return False
    io.open(path, "w", encoding="utf-8").write(out)
    print("WROTE %s  %d -> %d chars" % (path, len(src), len(out)))
    return True


ok = True
for p, o, n in PY_EDITS:
    ok = apply(p, o, n, True) and ok
for p, o, n in SH_EDITS:
    ok = apply(p, o, n, False) and ok
sys.exit(0 if ok else 1)
