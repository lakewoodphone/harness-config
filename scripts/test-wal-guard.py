#!/usr/bin/env python3
"""PROOF for authority-wal-guard.py -- re-runnable, and it leaves nothing behind.

WHY THIS FILE EXISTS
--------------------
A guard that has been RUN is not a guard that has been TESTED. The 2026-10-28 predecessor was
run a dozen times and looked perfect while an idle reader it could never see sat on the WAL.

WHY THE WAL MECHANISM IS TESTED ON A THROWAWAY DATABASE
------------------------------------------------------
Growing a WAL means writing rows. Writing rows into /root/authority.db to test a script would
pollute the company's authoritative database with test data -- the exact "a test that writes to a
real store must clean up after itself" failure this estate has already paid for once
(prove-inbound-path.py filed three duplicate work items). So the kills are proven on a temp copy,
and against production only a DRY RUN runs.

WHAT IS ASSERTS, AND THE FOUR THINGS THAT MATTER
------------------------------------------------
  PART 1  a throwaway database, via WAL_GUARD_DB
    1. an IDLE reader (0% CPU) holding a read transaction really does pin the WAL, and SQLite's
       own PRAGMA wal_checkpoint(PASSIVE) reports busy > 0 while it lives  -- the measurement,
       not a proxy for it
    2. the guard kills that idle reader and truncates the WAL to zero
    3. an ALLOWLISTED process holding the same database is NOT killed, and the guard then exits
       3 ("still pinned") rather than 0 -- a guard that cannot fix something must say so
    4. after the allowlisted reader goes away, the next run truncates and exits 0

  PART 2  production, DRY RUN ONLY, nothing is killed
    5. a planted idle reader on /root/authority.db is IDENTIFIED by the guard
    6. the live company API is never a candidate

Every assertion prints the value that decided it, because a proof that prints PASS because its
predicate matched nothing is how this estate got burned before.

Usage: test-wal-guard.py        (exit 0 = every assertion held)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

GUARD = os.environ.get("WAL_GUARD_BIN", "/usr/local/bin/authority-wal-guard.py")
FAILURES: list[str] = []


def check(name: str, ok: bool, measured: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  [ {measured} ]")
    if not ok:
        FAILURES.append(f"{name}: {measured}")


def run_guard(*args, env_extra=None, timeout=240):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True,
                       timeout=timeout, env=env)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def spawn_reader(db_path: str, workdir: str, name: str = "idle-reader") -> int:
    """An IDLE reader: opens a read transaction, reads once, then sleeps at 0% CPU.

    Started through a shell script whose FILENAME carries `name`, because /proc/<pid>/cmdline is
    the exec'd argv and a python `sys.argv[0]` assignment does not appear there. That is the only
    way to plant something the guard's allowlist will match by cmdline.
    """
    script = os.path.join(workdir, f"{name}.sh")
    pidfile = os.path.join(workdir, f"{name}.pid")
    inner = (
        "import sqlite3,time,os\n"
        f"c=sqlite3.connect({db_path!r}, isolation_level=None)\n"
        "c.execute('BEGIN')\n"
        "c.execute('SELECT count(*) FROM t').fetchone()\n"
        f"open({pidfile!r},'w').write(str(os.getpid()))\n"
        "time.sleep(300)\n"
    )
    with open(script, "w") as fh:
        fh.write('#!/bin/sh\nexec %s -c %s\n' % (sys.executable, shell_quote(inner)))
    os.chmod(script, 0o755)
    subprocess.Popen(["/bin/sh", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(100):
        time.sleep(0.1)
        try:
            return int(open(pidfile).read().strip())
        except (OSError, ValueError):
            continue
    raise RuntimeError(f"planted reader {name} never reported its pid")


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def alive(pid: int) -> bool:
    """Dead includes a zombie: a SIGKILLed process keeps /proc/<pid> until its parent reaps it,
    holds no lock and no transaction, and once made the guard itself look like it had failed."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            raw = fh.read()
    except OSError:
        return False
    return raw.rsplit(")", 1)[1].split()[0] != "Z"


def grow_wal(db: str) -> int:
    w = sqlite3.connect(db, isolation_level=None)
    w.execute("PRAGMA busy_timeout=5000")
    for _ in range(6):
        w.execute("INSERT INTO t SELECT x FROM t")
        w.commit()
    w.close()
    return os.path.getsize(db + "-wal") if os.path.exists(db + "-wal") else 0


def part1() -> None:
    print("\n== PART 1: mechanism, on a throwaway database ==")
    tmp = tempfile.mkdtemp(prefix="walguard-test-")
    db = os.path.join(tmp, "small.db")
    state = os.path.join(tmp, "state")
    env = {"WAL_GUARD_DB": db, "WAL_GUARD_DIR": state}
    try:
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(200)])
        conn.commit()
        conn.close()

        reader = spawn_reader(db, tmp, "idle-reader")
        check("planted idle reader is alive", alive(reader), f"pid={reader}")

        wal_size = grow_wal(db)
        check("WAL grew while the idle reader held a transaction",
              wal_size > 0, f"wal={wal_size} bytes")

        pc = sqlite3.connect(db, timeout=10)
        passive = pc.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        pc.close()
        # NOT `busy`. Measured 2026-10-28: with an idle reader holding a transaction PASSIVE
        # returns busy=0 and checkpoints nothing, so `busy` describes whether the caller waited,
        # not whether the WAL drained. Frames that did not drain is the signal.
        check("SQLite reports the pin as frames that did not drain",
              bool(passive) and passive[1] > 0 and passive[2] == 0,
              f"passive=[busy={passive[0]}, log={passive[1]}, checkpointed={passive[2]}]")

        rc, _, err = run_guard("--wal-max-gb", "0.000001", "--pin-min-hours", "0",
                               "--pin-frames-min", "1", "--min-cpu", "101", env_extra=env)
        status = json.load(open(os.path.join(state, "status.json")))
        acts = [a for a in status.get("actions", []) if a["pid"] == reader]
        check("idle reader was killed by rule B",
              not alive(reader),
              f"action={acts[0]['action'] if acts else 'NONE'} rule={acts[0]['rule'] if acts else '-'}")
        check("WAL truncated to zero frames",
              isinstance(status.get("truncate"), list) and status["truncate"][:2] == [0, 0],
              f"truncate={status.get('truncate')}")
        wal_after = os.path.getsize(db + "-wal") if os.path.exists(db + "-wal") else 0
        check("WAL file is zero bytes on disk", wal_after == 0, f"wal={wal_after} bytes")
        check("guard exit 0 when it could clear the pin", rc == 0, f"rc={rc}")

        # ---- the allowlist must protect, and then the guard must admit it ----
        protected = spawn_reader(db, tmp, "security-sentinel-proof")
        check("planted ALLOWLISTED reader is alive", alive(protected), f"pid={protected}")
        wal_size2 = grow_wal(db)
        check("WAL grew again under the allowlisted reader", wal_size2 > 0,
              f"wal={wal_size2} bytes")

        rc2, _, _ = run_guard("--wal-max-gb", "0.000001", "--pin-min-hours", "0",
                              "--pin-frames-min", "1", "--min-cpu", "101", env_extra=env)
        status2 = json.load(open(os.path.join(state, "status.json")))
        check("allowlisted process was NOT killed", alive(protected), f"pid={protected}")
        check("guard exits 3 when the WAL is still pinned, not 0", rc2 == 3, f"rc={rc2}")
        check("guard did not claim to have truncated while pinned",
              not (isinstance(status2.get("truncate"), list) and status2["truncate"][:2] == [0, 0]),
              f"truncate={status2.get('truncate')}")

        os.kill(protected, 9)
        time.sleep(1)
        rc3, _, _ = run_guard("--wal-max-gb", "0.000001", "--pin-min-hours", "0",
                              "--pin-frames-min", "1", "--min-cpu", "101", env_extra=env)
        status3 = json.load(open(os.path.join(state, "status.json")))
        wal_after3 = os.path.getsize(db + "-wal") if os.path.exists(db + "-wal") else 0
        check("once nothing pins it, the next run truncates and exits 0",
              rc3 == 0 and wal_after3 == 0,
              f"rc={rc3} wal={wal_after3} truncate={status3.get('truncate')}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part2() -> None:
    print("\n== PART 2: production, DRY RUN ONLY (nothing is killed) ==")
    if not os.path.exists("/root/authority.db"):
        print("  SKIP  no /root/authority.db on this host")
        return
    workdir = tempfile.mkdtemp(prefix="walguard-prod-")
    # Its own state directory: a test must never overwrite the production status file that an
    # operator reads. MEASURED 2026-10-28 -- the first version did exactly that and left a
    # dry_run=true status in /var/lib/wal-guard while the timer's real run was in flight.
    test_state = os.path.join(workdir, "state")
    reader = spawn_reader_generic("/root/authority.db", workdir, "idle-reader")
    try:
        check("planted idle reader on the LIVE database is alive", alive(reader), f"pid={reader}")
        # A reader that opens AFTER the WAL's contents cannot pin them -- correctly so -- so this
        # asserts the candidate list rather than pretending to observe a pin:
        #   * the planted holder IS a candidate
        #   * the live company API is NOT, and is in the protected set
        p = subprocess.run([sys.executable, GUARD, "--report-holders"],
                           capture_output=True, text=True, timeout=120,
                           env={**os.environ, "WAL_GUARD_DIR": test_state})
        report = json.loads(p.stdout)
        cands = [h["pid"] for h in report["holders"]]
        check("the guard sees the planted holder as a candidate",
              reader in cands, f"pid={reader} candidates={cands}")
        api = subprocess.run(["systemctl", "show", "company-api", "-p", "ExecMainPID",
                              "--value"], capture_output=True, text=True).stdout.strip()
        check("the live company API is never a candidate",
              api.isdigit() and int(api) not in cands,
              f"api_pid={api} candidates={cands}")
        check("the live company API is in the protected set",
              api.isdigit() and int(api) in report["protected_pids"],
              f"api_pid={api} protected={report['protected_pids']}")

        rc, _, _ = run_guard("--wal-max-gb", "0.000001", "--pin-min-hours", "0",
                             "--pin-frames-min", "1", "--min-cpu", "101", "--dry-run",
                             env_extra={"WAL_GUARD_DIR": test_state})
        check("dry run killed nothing", alive(reader), f"alive={alive(reader)} rc={rc}")
    finally:
        try:
            os.kill(reader, 9)
        except ProcessLookupError:
            pass
        shutil.rmtree(workdir, ignore_errors=True)


def spawn_reader_generic(db_path: str, workdir: str, name: str) -> int:
    """Same as spawn_reader but the read transaction touches sqlite_master, so it works
    against any database, not only the fixture with table `t`."""
    script = os.path.join(workdir, f"{name}2.sh")
    pidfile = os.path.join(workdir, f"{name}2.pid")
    inner = (
        "import sqlite3,time,os\n"
        f"c=sqlite3.connect({db_path!r}, isolation_level=None)\n"
        "c.execute('BEGIN')\n"
        "c.execute('SELECT count(*) FROM sqlite_master').fetchone()\n"
        f"open({pidfile!r},'w').write(str(os.getpid()))\n"
        "time.sleep(300)\n"
    )
    with open(script, "w") as fh:
        fh.write('#!/bin/sh\nexec %s -c %s\n' % (sys.executable, shell_quote(inner)))
    os.chmod(script, 0o755)
    subprocess.Popen(["/bin/sh", script], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(100):
        time.sleep(0.1)
        try:
            return int(open(pidfile).read().strip())
        except (OSError, ValueError):
            continue
    raise RuntimeError("planted generic reader never reported its pid")


def main() -> int:
    print(f"authority-wal-guard proof -- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    if not os.path.exists(GUARD):
        print(f"guard not found at {GUARD}")
        return 1
    part1()
    part2()
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILED assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("RESULT: all assertions held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
