#!/usr/bin/env python3
"""DB INTEGRITY CHECK -- the alarm now checks a SNAPSHOT, never the live 20 GB database.

WHY THIS EXISTS (journal P167, verified 2026-09-30)
---------------------------------------------------
The authority has run this cron line since July:

    17 4 * * * out=$(sqlite3 ... "PRAGMA quick_check;" 2>&1); case "$out" in
      ok) ;; *) printf "%s\\n" "$out" | mail -s "SECRETARY DB CORRUPTION DETECTED" root;
                 echo "DB corruption detected at $(date)" >> ~/secretary-db-errors.log ;;
    esac

Measured: `command -v mail` -> nothing, `command -v sendmail` -> nothing. There is no mail
transport on this host. So the only route a corruption finding had to a human was a line in
`~/secretary-db-errors.log`, which nothing reads -- and that file's last entry was 2026-09-10.

The three defects this file already fixed:
  1. its alarm could never leave the machine      -> a status file plus a wake source
  2. nothing watched whether the check itself ran -> the status carries `at`, and the source
     raises Unreadable when it is more than a day stale, so a dead check is not a healthy check
  3. it ran an unbounded `PRAGMA quick_check`     -> bounded to `quick_check(1)`, read-only URI,
     and a hard timeout that reports rather than hangs

CHANGED 2026-10-07 (F-IO) -- the fourth defect: THE CHECK READ THE LIVE DATABASE END TO END.
Measured 2026-10-07: `PRAGMA quick_check(1)` against the live 20.4 GB
`personal-secretary-mvp/data/secretary.db` took 715-1784 s (16 589 s on 2026-10-06), while the
box sat at `/proc/pressure/io full avg10=85.6` with 98.5% util on dm-0 and 8-10 processes in
D-state. The API is writing that file the whole time, so the read starves the API to answer a
question the six-hourly snapshot answers just as well.

NOW: `PRAGMA quick_check(1)` runs against the newest local snapshot written by
`scripts/server/backup-data.sh` -- `<backup-root>/<STAMP>/sqlite/data/secretary.db`. A snapshot
directory is usable only once the backup has written its `COMPLETE` marker, so an in-flight
backup can never be checked. Only when no snapshot is usable does the check fall back to a
private copy made with SQLite's own online backup API into `~/.db-integrity/work/`, which is
deleted again afterwards. The live file is NEVER passed to `PRAGMA quick_check`.

SERIALISED: every one of these jobs takes the same advisory lock
(`/run/lock/secretary-io.lock`, `$SECRETARY_IO_LOCK` to move it). `backup-data.sh` waits up to
30 min for it, `company-offsite-push.sh` skips its run if it is held, and this check waits up
to 90 min. That is what stops the backup, the integrity check and the offsite push from
overlapping each other on a box whose block layer is the bottleneck.

READ-ONLY on whatever it checks. It opens the file with `mode=ro`, runs one pragma, and writes
only its own files. It never repairs anything: repairing a corrupt SQLite is a deliberate,
backed-up, owner-aware act.

CHANGED 2026-10-11 (the cutover port, cloud authority) -- THE DISK IS THE BINDING CONSTRAINT.
----------------------------------------------------------------------------------------------
Ported to `secratary-cloud` unchanged in behaviour, plus one gate it never needed on the office
box. The cloud box is 75 GB total, 23.7 GB of it the live database, ~26 GB free. `make_live_copy`
takes a consistent copy with SQLite's online backup API, which on this box is a second
database-sized file for the duration of the run. Measured 2026-10-11 06:25Z
(`secratary-cloud: df -B1 --output=avail /` -> 27,596,357,632 B = 25.7 GiB free;
`/root/authority.db` = 23,707,291,648 B = 22.1 GiB).

That is not a margin to discover at 04:17 by having the copy fill the disk the live database is
writing to. So a free-space pre-flight is a NEW step at this port: in copy mode the check refuses
to start unless the filesystem has at least `DB_INTEGRITY_FREE_COPY_FACTOR` (1.25) x the live
database plus `DB_INTEGRITY_FREE_MARGIN_GB` (4 GiB) free, and reports that requirement as its
finding (exit 2) rather than proceeding. Measured against the numbers above that is 31.6 GiB
required versus 25.7 GiB free, so **on the cloud box this job refuses today, on purpose** -- the
copy does not fit beside the live database, and a disk-full SQLite takes the company down.
`DB_INTEGRITY_MIN_FREE_GB` is a deliberate absolute override for when an operator has decided
otherwise. The live file is still NEVER passed to `PRAGMA quick_check` -- the check runs against
the copy, and the copy is unlinked in the same run, in a `finally`, so a killed run cannot leave
it behind.

EXIT 0 the database answered `ok`; 1 it did not; 2 the check could not be run at all
(including: not enough free space to take a consistent copy without endangering the live file).
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LIVE_DB = Path(os.environ.get("SECRETARY_DB", "/root/authority.db"))
BACKUP_ROOT = Path(os.environ.get("DB_INTEGRITY_BACKUP_ROOT", "/var/lib/authority-snapshots"))
STATE_DIR = Path.home() / ".db-integrity"
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "check.log"
WORK_DIR = STATE_DIR / "work"
TIMEOUT_S = float(os.environ.get("DB_INTEGRITY_TIMEOUT", "600"))
LOCK_WAIT_S = float(os.environ.get("DB_INTEGRITY_LOCK_WAIT", "5400"))
LOCK_POLL_S = 5.0
# A snapshot written before the COMPLETE marker existed is accepted only once it is this old,
# because until then a backup might still be writing into it. The lock closes that hole too.
LEGACY_SNAPSHOT_AGE_S = float(os.environ.get("DB_INTEGRITY_LEGACY_AGE", "3600"))
# The backup runs every 6 h; 8 h of slack means one skipped run is not yet a warning.
SNAPSHOT_STALE_S = float(os.environ.get("DB_INTEGRITY_SNAPSHOT_STALE", str(8 * 3600)))
# Added at the cutover: how much free space must exist BEFORE a private consistent copy is made.
# The copy costs the size of the live database (plus its WAL); 1.25x is that plus slack for the WAL
# to grow during the run, and MARGIN_GB is the headroom left for everything else on the box --
# the API's own writes, the autopilot, the eight logs that rotate. Measured 2026-10-11 06:25Z:
# 25.7 GiB free, live database 22.07 GiB -> this refuses on the cloud box TODAY, deliberately,
# and says so (exit 2) instead of filling the filesystem the live database is writing to.
MIN_FREE_GB = float(os.environ.get("DB_INTEGRITY_MIN_FREE_GB", "0"))   # 0 = derive from the DB
FREE_MARGIN_GB = float(os.environ.get("DB_INTEGRITY_FREE_MARGIN_GB", "4"))
FREE_COPY_FACTOR = float(os.environ.get("DB_INTEGRITY_FREE_COPY_FACTOR", "1.25"))


def required_free_gb() -> float:
    """Free space this run needs, in GiB: the copy plus a margin. Explicit override wins."""
    if MIN_FREE_GB > 0:
        return MIN_FREE_GB
    try:
        db_bytes = LIVE_DB.stat().st_size
    except OSError:
        return FREE_MARGIN_GB
    return round(db_bytes / float(1 << 30) * FREE_COPY_FACTOR + FREE_MARGIN_GB, 2)


def _free_gb(path: Path) -> float:
    """Free bytes on the filesystem holding `path` (walk up to the nearest existing parent)."""
    p = path
    for _ in range(12):
        try:
            st = os.statvfs(str(p))
            return (st.f_bavail * st.f_frsize) / float(1 << 30)
        except OSError:
            if p.parent == p:
                break
            p = p.parent
    return -1.0


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_path() -> Path:
    """The lock the backup and the offsite push use. /run is tmpfs, so take it when we can."""
    p = Path(os.environ.get("SECRETARY_IO_LOCK", "/run/lock/secretary-io.lock"))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a"):
            pass
        return p
    except OSError:
        fallback = Path.home() / ".secretary-io.lock"
        with fallback.open("a"):
            pass
        return fallback


class IOLock:
    """Advisory exclusive lock shared by the backup, this check and the offsite push."""

    def __init__(self, path: Path, wait_s: float):
        self.path = Path(path)
        self.wait_s = wait_s
        self._fh = None

    def __enter__(self) -> "IOLock":
        self._fh = self.path.open("a")
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("another I/O-heavy job has held %s for %.0f s"
                                       % (self.path, self.wait_s))
                time.sleep(LOCK_POLL_S)

    def __exit__(self, *exc) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            self._fh.close()
        self._fh = None


def snapshots() -> list:
    """Every snapshot directory under BACKUP_ROOT that carries a database, newest name first."""
    if not BACKUP_ROOT.is_dir():
        return []
    found = []
    for d in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        try:
            if not d.is_dir():
                continue
        except OSError:
            continue
        db = d / "sqlite" / "data" / "secretary.db"
        try:
            if not db.is_file():
                continue
            age = time.time() - db.stat().st_mtime
        except OSError:
            continue
        complete = (d / "COMPLETE").is_file()
        if complete or age >= LEGACY_SNAPSHOT_AGE_S:
            found.append({"dir": d, "db": db, "age": age, "complete": complete})
    return found


def make_live_copy() -> Path:
    """A consistent copy of the live database, via SQLite's own online backup API."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    dst = WORK_DIR / ("live-copy-%s.db" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    src = sqlite3.connect(LIVE_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=TIMEOUT_S)
    try:
        out = sqlite3.connect(str(dst))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dst


def reap_work_dir() -> None:
    """A copy is normally deleted in a finally; this catches ones killed mid-run."""
    if not WORK_DIR.is_dir():
        return
    cutoff = time.time() - 86400
    for f in WORK_DIR.glob("live-copy-*.db"):
        with contextlib.suppress(OSError):
            if f.stat().st_mtime < cutoff:
                f.unlink()


def probe(path: Path) -> dict:
    """One read-only `PRAGMA quick_check(1)` against `path`."""
    out = {"ok": None, "result": None, "error": None, "seconds": None}
    try:
        out["bytes"] = path.stat().st_size
    except OSError as exc:
        out["ok"] = False
        out["error"] = "cannot stat %s: %s" % (path, exc)
        return out
    started = time.time()
    try:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = "could not open read-only: %s" % exc
        return out
    try:
        con.execute("PRAGMA busy_timeout = %d" % int(TIMEOUT_S * 1000))
        # quick_check(1) stops at the first error: a full check on 20 GB takes minutes, and one
        # named error is what a human needs to start.
        row = con.execute("PRAGMA quick_check(1)").fetchone()
        out["result"] = (row[0] if row else "") or ""
        out["ok"] = out["result"].strip().lower() == "ok"
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        with contextlib.suppress(Exception):
            con.close()
    out["seconds"] = round(time.time() - started, 1)
    return out


def _run(source: str, snapshot, do_probe: bool) -> dict:
    out = {"at": _utc(), "db": str(LIVE_DB), "ok": None, "result": None, "error": None,
           "seconds": None, "bytes": None, "source": None, "checked": None, "snapshot": None,
           "snapshot_age_seconds": None, "warning": None}
    if snapshot is not None:
        p = Path(snapshot)
        out["source"] = "snapshot(explicit)"
        out["checked"] = str(p)
        out["snapshot"] = str(p.parent.parent.parent)
        if do_probe:
            out.update(probe(p))
        return out
    if source not in ("auto", "snapshot", "copy"):
        out["ok"] = False
        out["error"] = "unknown --source %r" % source
        return out

    temp = None
    try:
        with IOLock(lock_path(), LOCK_WAIT_S):
            reap_work_dir()
            target = None
            if source != "copy":
                usable = snapshots()
                if usable:
                    chosen = usable[0]
                    target = chosen["db"]
                    out["source"] = "snapshot" if chosen["complete"] else "snapshot-legacy"
                    out["snapshot"] = str(chosen["dir"])
                    out["snapshot_age_seconds"] = round(chosen["age"], 1)
                    if chosen["age"] > SNAPSHOT_STALE_S:
                        out["warning"] = ("the newest usable snapshot is %.1f h old (ceiling "
                                          "%.1f h): the six-hourly backup may not be running"
                                          % (chosen["age"] / 3600.0, SNAPSHOT_STALE_S / 3600.0))
                elif source == "snapshot":
                    out["ok"] = False
                    out["error"] = "no usable snapshot under %s" % BACKUP_ROOT
                    return out
            if target is None:
                # THE FREE-SPACE GATE (added at the cutover). Taking a consistent copy of a 22 GiB
                # live database needs a second 22 GiB on the same filesystem. On a box that shares
                # that filesystem with the live database, filling it is how SQLite SIGBUSes the
                # whole company -- so this refuses to start rather than discovering the margin.
                free = _free_gb(WORK_DIR if WORK_DIR.parent.exists() else Path("/"))
                need = required_free_gb()
                if free >= 0 and free < need:
                    out["ok"] = False
                    out["source"] = "refused"
                    out["error"] = ("not enough free space for a consistent copy: %.1f GiB free, "
                                    "%.1f GiB required (DB_INTEGRITY_FREE_COPY_FACTOR=%.2f x the "
                                    "live database + %.1f GiB margin; override with "
                                    "DB_INTEGRITY_MIN_FREE_GB). The live database was not read. "
                                    "Point DB_INTEGRITY_BACKUP_ROOT at a snapshot stream, or free "
                                    "space, or lower the gate deliberately."
                                    % (free, need, FREE_COPY_FACTOR, FREE_MARGIN_GB))
                    return out
                target = make_live_copy()
                temp = target
                out["source"] = "live-copy(online-backup-api)"
                out["warning"] = ("no usable snapshot under %s; checked a private consistent copy "
                                  "of the live database instead" % BACKUP_ROOT)
            out["checked"] = str(target)
            if do_probe:
                out.update(probe(target))
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = "could not run the check: %s: %s" % (type(exc).__name__, exc)
        return out
    finally:
        if temp is not None:
            with contextlib.suppress(OSError):
                temp.unlink()
    return out


def check(source: str = "auto", snapshot=None) -> dict:
    return _run(source, snapshot, True)


def resolve(source: str = "auto", snapshot=None) -> dict:
    """Same resolution, no pragma: used to show which file would be checked."""
    return _run(source, snapshot, False)


def render(r: dict) -> str:
    where = r.get("source") or "?"
    if r.get("ok"):
        line = "ok - %s answered 'ok' in %ss (%s bytes)" % (r.get("checked"), r.get("seconds"),
                                                            r.get("bytes", "?"))
    elif r.get("error"):
        line = "FAILED TO CHECK - %s" % r["error"]
    else:
        line = "CORRUPTION - %s answered %r" % (r.get("checked"), (r.get("result") or "")[:300])
    line = "%s [%s]" % (line, where)
    if r.get("warning"):
        line += " WARNING: %s" % r["warning"]
    return line


def selftest() -> int:
    """Prove the detector fires on a database that is actually damaged, and stays quiet on a good one."""
    import tempfile
    problems = []
    good = Path(tempfile.mkdtemp()) / "good.db"
    con = sqlite3.connect(str(good))
    con.execute("CREATE TABLE t (a TEXT)")
    con.execute("INSERT INTO t VALUES ('x')")
    con.commit()
    con.close()
    r = probe(good)
    if not r["ok"]:
        problems.append("a healthy database was reported corrupt: %r" % r)

    # A real corruption, made with the documented escape hatch: overwrite half the file with zeros.
    bad = Path(tempfile.mkdtemp()) / "bad.db"
    con = sqlite3.connect(str(bad))
    con.execute("CREATE TABLE t (a TEXT)")
    for i in range(2000):
        con.execute("INSERT INTO t VALUES (?)", ("x" * 200,))
    con.commit()
    con.close()
    raw = bytearray(bad.read_bytes())
    for i in range(len(raw) // 2, len(raw)):
        raw[i] = 0
    bad.write_bytes(bytes(raw))
    r2 = probe(bad)
    if r2["ok"]:
        problems.append("a zeroed database was reported healthy: %r" % r2)

    if problems:
        print("SELFTEST FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("SELFTEST OK (healthy -> ok, zeroed -> %s)" % ((r2.get("result") or r2.get("error")) or "")[:80])
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--source", choices=["auto", "snapshot", "copy"], default="auto",
                    help="auto/snapshot = newest local snapshot; copy = private online-API copy "
                         "of the live database (never a check of the live file itself)")
    ap.add_argument("--snapshot", default=None, help="check this database file instead")
    ap.add_argument("--resolve-only", action="store_true",
                    help="report which file would be checked and exit without running the pragma")
    ap.add_argument("--preflight-only", action="store_true",
                    help="run the free-space gate and the snapshot resolution, take no copy, run "
                         "no pragma. Used to prove the gate fires on a box where the copy would "
                         "not fit -- and it never touches the live database.")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    # The preflight: same gate, no side effects, no read of the live database. Its whole purpose is
    # to be runnable on the authority at any time, including when the honest answer is "refuse".
    if a.preflight_only:
        free = _free_gb(WORK_DIR.parent if WORK_DIR.parent.exists() else Path("/"))
        need = required_free_gb()
        try:
            db_bytes = LIVE_DB.stat().st_size
        except OSError as exc:
            print(json.dumps({"at": _utc(), "ok": False, "error": "cannot stat %s: %s" % (LIVE_DB, exc)}) if a.json
                  else "preflight: cannot stat %s: %s" % (LIVE_DB, exc))
            return 2
        r = {"at": _utc(), "mode": "preflight", "live_db": str(LIVE_DB), "live_db_gib": round(db_bytes / float(1 << 30), 2),
             "free_gib": round(free, 2), "required_gib": need, "backup_root": str(BACKUP_ROOT),
             "snapshots_usable": len(snapshots()), "would_run": bool(free >= need or snapshots()),
             "ok": bool(free >= need or snapshots())}
        print(json.dumps(r, indent=1) if a.json else
              "db-integrity-check preflight: live=%s (%.2f GiB) free=%.2f GiB required=%.2f GiB "
              "usable_snapshots=%d -> %s"
              % (r["live_db"], r["live_db_gib"], r["free_gib"], r["required_gib"],
                 r["snapshots_usable"], "would run against a snapshot" if r["snapshots_usable"]
                 else ("would take a copy" if r["would_run"] else "WOULD REFUSE (no space, no snapshot)")))
        return 0 if r["ok"] else 2

    r = resolve(a.source, a.snapshot) if a.resolve_only else check(a.source, a.snapshot)
    print(json.dumps(r, indent=1) if a.json else render(r))
    if a.write_status and not a.resolve_only:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
            tmp.replace(STATUS)
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write("%s  %s\n" % (r["at"], render(r)))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)
    if a.resolve_only:
        return 0
    return 0 if r["ok"] else (2 if r["error"] else 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

