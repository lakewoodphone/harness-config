#!/usr/bin/env python3
"""AUTHORITY WAL GUARD -- keep /root/authority.db's write-ahead log from eating the disk.

WHAT THIS GUARDS, AND WHY IT NEEDS TO EXIST
-------------------------------------------
2026-10-28, measured. The company API was ALIVE but NOT ANSWERING for ~10 minutes: /health
timed out at 5 s and at 30 s, with 54 connections queued. The owner got a text and a call at
16:13:12Z. Two orphans were responsible, both reparented to init, both started from inline
scripts on 2026-10-26:

  PID 377634  python -u -                         42 h, 99.8% CPU, rchar 148 TB
              held a READ TRANSACTION on /root/authority.db open the whole time
  PID 585597  scripts/ps_mcp_server.py            40 h, 99.5% CPU, rchar 174 TB

The second-order damage is the part worth automating. SQLite cannot checkpoint past the oldest
reader, so `/root/authority.db-wal` grew to 10,714,863,432 bytes on a 225 GB disk that was 91%
full with 20 GB free -- the same shape as this box's 2026-09-10 full-disk SIGBUS. Killing the two
processes and running PRAGMA wal_checkpoint(TRUNCATE) returned 10 GB (91% -> 86%) and /health
went to 200 in 0.16 s.

WHY THE FIRST VERSION WAS NOT ENOUGH (this file's own v1, same day)
-------------------------------------------------------------------
v1 reaped processes at >=90% CPU for >=6 h. That misses the worst case completely: a process at
**0% CPU** holding an open read transaction pins the WAL forever and looks innocent in top. An
attack, a bug and an abandoned `sqlite3` prompt all look identical to it. So pinning is detected
the only way that cannot be faked -- ask SQLite itself:

    PRAGMA wal_checkpoint(PASSIVE) -> (busy, log_frames, checkpointed_frames)

The signal is `log_frames - checkpointed_frames`: frames that did NOT drain. It is NOT `busy`,
and this file only knows that because its own proof refuted it (measured 2026-10-28): with an
idle reader holding a transaction, PASSIVE returned [0, 42, 0] -- busy=0, nothing checkpointed --
and only the later TRUNCATE reported busy=1. A busy-based predicate saw a healthy database and
never looked for the reader at all.

TWO RULES
---------
  A  HOT ORPHAN       cpu >= min-cpu (measured over two samples 10 s apart, not the lifetime
                      average) AND elapsed >= min-hours. Every legitimate long-lived process on
                      this box idles (the four ps_mcp_server instances measured 0.0/0.0/0.2/0.0%).
  B  WAL PIN          wal bytes >= --wal-max-gb. Then:
                        PASSIVE. If no frames are left undrained the WAL is merely trailing ->
                        TRUNCATE, reclaim, no kill.
                        If frames are left, find what holds authority.db open, exclude the
                        allowlist, exclude anything younger than --pin-min-hours, SIGTERM the
                        oldest, re-PASSIVE, and repeat until the WAL drains or candidates run out.

Rule B is the one that would have caught 2026-10-28 whether or not the pinner was burning CPU.

SAFETY
------
  * ALLOWLISTED cmdlines are never killed by either rule: the company API (busy is its job),
    the security services, esearch, cron, and the backup/integrity jobs that are supposed to
    hold the database under /run/lock/secretary-io.lock.
  * Never pid 1, never this process or its parent, never systemd.
  * SIGTERM, then SIGKILL only after 20 s.
  * SIGTERM on a reader destroys no data: WAL mode is crash-safe by construction -- the same
    guarantee a power cut relies on.
  * --dry-run reports and kills nothing.
  * Rule B only fires above the WAL ceiling, which normal operation never approaches
    (measured normal range: 0.4 MB - 12.5 MB against a 2048 MB ceiling).

EXIT CODES (so a failure is an open item and not a silent green)
----------------------------------------------------------------
  0  ran, nothing needed doing, or the guard did what was needed
  2  internal error (the guard itself is broken)
  3  the WAL is over the ceiling and is STILL pinned after every candidate was removed

Usage: authority-wal-guard.py [--dry-run] [--min-cpu 90] [--min-hours 6]
                             [--wal-max-gb 2.0] [--pin-min-hours 2]
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE_DIR = os.environ.get("WAL_GUARD_DIR", "/var/lib/wal-guard")
STATUS_PATH = os.path.join(STATE_DIR, "status.json")
ACTIONS_PATH = os.path.join(STATE_DIR, "actions.jsonl")

AUTHORITY_DB = os.environ.get("WAL_GUARD_DB", "/root/authority.db")
WAL_PATH = AUTHORITY_DB + "-wal"
CLK_TCK = os.sysconf("SC_CLK_TCK")

# Never killed, whatever they measure. Substring match against /proc/<pid>/cmdline.
ALLOWLIST = (
    "uvicorn app.main:app",       # the company API: being busy is its job
    "security-agent", "security-listener", "security-sentinel",
    "esearch", "sshd", "systemd", "tailscaled", "cloudflared", "fail2ban",
    "phone-gate", "cron",
    "backup-data", "offsite-push", "db-integrity-check", "authority-wal-guard",
    "runaway-process-reaper",     # the 2026-10-28 predecessor, if still installed
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def read_stat(pid: int) -> dict | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    head, tail = raw.rsplit(")", 1)          # comm may hold spaces and parens
    f = tail.split()
    try:
        return {"state": f[0], "ticks": int(f[11]) + int(f[12]), "starttime": int(f[19])}
    except (IndexError, ValueError):
        return None


def cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""


def uptime() -> float:
    with open("/proc/uptime") as fh:
        return float(fh.read().split()[0])


def elapsed_of(pid: int, up: float) -> float:
    st = read_stat(pid)
    return up - (st["starttime"] / CLK_TCK) if st else 0.0


def holds_db(pid: int) -> bool:
    """True when this process has the database, its WAL or its SHM open."""
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}").startswith(AUTHORITY_DB):
                    return True
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    return False


def allowed(cmd: str) -> bool:
    return any(a in cmd for a in ALLOWLIST)


def wal_bytes() -> int:
    try:
        return os.stat(WAL_PATH).st_size
    except OSError:
        return 0


def checkpoint(mode: str = "PASSIVE") -> list | dict:
    """(busy, log_frames, checkpointed_frames). A read-only handle cannot checkpoint --
    `mode=ro` fails here with OperationalError: disk I/O error (measured 2026-10-28)."""
    try:
        conn = sqlite3.connect(AUTHORITY_DB, timeout=30)
        row = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        conn.close()
        return list(row) if row else {"error": "no row"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


#: Frames that must remain undrained before a reader counts as PINNING rather than merely
#: working. A healthy busy database leaves a handful of frames from an in-flight writer; it
#: never leaves thousands, and it never has a multi-gigabyte WAL. 1000 frames is ~4 MB at the
#: default 4 KiB page size.
PIN_FRAMES_MIN = 1000


def frames_left(result) -> int | None:
    """log_frames - checkpointed_frames: the honest measure of an undrained WAL.

    MEASURED 2026-10-28 by this file's own proof: with an idle reader holding a transaction,
    `PRAGMA wal_checkpoint(PASSIVE)` returned [0, 42, 0] -- busy=0 with nothing checkpointed --
    so a busy-based predicate saw nothing wrong and never even looked for the reader. The later
    TRUNCATE did report busy=1. Frames-left is the signal that survives both shapes.
    """
    if not isinstance(result, list) or len(result) != 3:
        return None
    return result[1] - result[2]


def snapshot() -> tuple[dict[int, tuple[int, float]], float]:
    first, t0 = {}, time.time()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        st = read_stat(int(entry))
        if st and st["state"] != "Z":
            first[int(entry)] = (st["ticks"], t0)
    return first, t0


def hot_processes(first: dict[int, tuple[int, float]], t0: float, min_cpu: float,
                  min_hours: float, protected: set[int]) -> list[dict]:
    """Two-sample CPU, so a process that was hot yesterday and is idle now does not qualify."""
    time.sleep(10)
    t1, out = time.time(), []
    for pid, (ticks0, _) in first.items():
        if pid in protected:
            continue
        st = read_stat(pid)
        if not st or st["state"] == "Z":
            continue
        cpu = ((st["ticks"] - ticks0) / CLK_TCK) / max(t1 - t0, 0.001) * 100.0
        cmd = cmdline(pid)
        if cpu < min_cpu or allowed(cmd):
            continue
        el = elapsed_of(pid, uptime())
        if el < min_hours * 3600:
            continue
        out.append({"pid": pid, "cpu_pct": round(cpu, 1), "elapsed_s": round(el),
                    "cmd": cmd[:200], "rule": "A-hot-orphan"})
    return out


def db_holders(protected: set[int]) -> list[dict]:
    up, out = uptime(), []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in protected:
            continue
        cmd = cmdline(pid)
        if not cmd or allowed(cmd):
            continue
        st = read_stat(pid)
        if not st or st["state"] == "Z":
            continue
        if holds_db(pid):
            out.append({"pid": pid, "elapsed_s": round(elapsed_of(pid, up)),
                        "cmd": cmd[:200], "rule": "B-wal-pin"})
    out.sort(key=lambda r: r["elapsed_s"], reverse=True)
    return out


def gone(pid: int) -> bool:
    """Dead means no /proc entry OR a zombie. MEASURED 2026-10-28: this file's proof caught
    `terminate` reporting "still-alive-after-sigkill" for a process that had been SIGKILLed but
    not yet reaped -- a zombie keeps /proc/<pid> until its parent waits, holds no lock, and is
    not alive in any sense that matters here."""
    st = read_stat(pid)
    return st is None or st["state"] == "Z"


def terminate(pid: int, dry_run: bool) -> str:
    if dry_run:
        return "would-kill"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already-gone"
    except PermissionError as exc:
        return f"permission-denied: {exc}"
    for _ in range(20):
        time.sleep(1)
        if gone(pid):
            return "sigterm"
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "sigterm"
    # Confirm the kill landed rather than announcing it. MEASURED 2026-10-28: this file's own
    # proof caught it returning "sigkill-after-20s" while /proc/<pid> still existed, because it
    # reported the signal it sent instead of the outcome.
    for _ in range(50):
        time.sleep(0.1)
        if gone(pid):
            return "sigkill-after-20s"
    return "still-alive-after-sigkill"


def protected_pids() -> set[int]:
    pids = {1, os.getpid(), os.getppid()}
    for unit in ("company-api",):
        try:
            out = subprocess.run(["systemctl", "show", unit, "-p", "ExecMainPID", "--value"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            if out.isdigit():
                pids.add(int(out))
        except Exception:
            pass
    return pids


def main() -> int:
    argv = sys.argv[1:]
    dry = "--dry-run" in argv

    def arg(name, default):
        return type(default)(argv[argv.index(name) + 1]) if name in argv else default

    min_cpu = arg("--min-cpu", 90.0)
    min_hours = arg("--min-hours", 6.0)
    wal_max_gb = arg("--wal-max-gb", 2.0)
    pin_min_hours = arg("--pin-min-hours", 2.0)
    pin_frames_min = arg("--pin-frames-min", PIN_FRAMES_MIN)
    wal_max = int(wal_max_gb * 1024 ** 3)

    os.makedirs(STATE_DIR, exist_ok=True)
    protected = protected_pids()
    started = time.time()
    result: dict = {"at": now_iso(), "ok": True, "dry_run": dry, "actions": []}

    # --report-holders: answer "who is holding the database open, and would you touch them?"
    # without acting on anything. Rule B only hunts when the WAL has frames that did not drain,
    # which means a freshly-opened reader cannot be observed as a pin -- that is correct
    # behaviour, not a blind spot, but it does mean a test needs a way to see the candidate list.
    if "--report-holders" in argv:
        holders = db_holders(protected)
        print(json.dumps({"at": now_iso(), "holders": holders,
                          "protected_pids": sorted(protected),
                          "wal_bytes": wal_bytes()},
                         indent=1))
        return 0

    try:
        wal_before = wal_bytes()
        result["wal_bytes_before"] = wal_before

        # ---- rule A: hot orphans -------------------------------------------
        first, t0 = snapshot()
        for p in hot_processes(first, t0, min_cpu, min_hours, protected):
            p["action"] = terminate(p["pid"], dry)
            p["at"] = now_iso()
            result["actions"].append(p)

        # ---- rule B: the WAL is over the ceiling ---------------------------
        wal_now = wal_bytes()
        still_pinned = False
        if wal_now >= wal_max:
            result["trigger"] = f"wal {wal_now} >= {wal_max}"
            rounds = []
            passive = checkpoint("PASSIVE")
            rounds.append(passive)
            left = frames_left(passive)
            n = 0
            # MEASURED 2026-10-28, by this file's own proof: `busy` is NOT the pin signal.
            # With an idle reader holding a transaction SQLite returned passive=[0, 42, 0] --
            # busy=0, nothing checkpointed -- and only the later TRUNCATE said busy=1. The
            # honest signal is frames that did not drain: log_frames - checkpointed_frames.
            while left is not None and left >= pin_frames_min and n < 5:
                cands = [c for c in db_holders(protected)
                         if c["elapsed_s"] >= pin_min_hours * 3600]
                if not cands:
                    break
                victim = cands[0]          # db_holders() is oldest-first
                victim["action"] = terminate(victim["pid"], dry)
                victim["at"] = now_iso()
                result["actions"].append(victim)
                n += 1
                if dry:
                    break
                time.sleep(1)
                passive = checkpoint("PASSIVE")
                rounds.append(passive)
                left = frames_left(passive)
            result["passive_rounds"] = rounds
            result["frames_left"] = left
            if dry:
                result["truncate"] = "skipped: dry run"
                still_pinned = left is not None and left >= pin_frames_min
            else:
                trunc = checkpoint("TRUNCATE")
                result["truncate"] = trunc
                if isinstance(trunc, list):
                    still_pinned = trunc[0] != 0 or (trunc[1] - trunc[2]) > 0
                else:
                    still_pinned = True
        else:
            result["trigger"] = None

        result["wal_bytes_after"] = wal_bytes()
        result["elapsed_s"] = round(time.time() - started, 1)
    except Exception as exc:
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        with open(STATUS_PATH, "w") as fh:
            json.dump(result, fh, indent=1)
        print(json.dumps({k: result[k] for k in ("at", "ok", "error")}))
        return 2

    with open(STATUS_PATH, "w") as fh:
        json.dump(result, fh, indent=1)
    for a in result["actions"]:
        with open(ACTIONS_PATH, "a") as fh:
            fh.write(json.dumps(a) + "\n")

    print(json.dumps({k: v for k, v in result.items()
                      if k in ("at", "ok", "trigger", "wal_bytes_before", "wal_bytes_after",
                               "truncate", "elapsed_s")}))
    if still_pinned:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
