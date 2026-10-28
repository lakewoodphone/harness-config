#!/usr/bin/env python3
"""RUNAWAY PROCESS REAPER -- kill a process that has burned a core for hours.

WHY THIS EXISTS (2026-10-28, measured)
--------------------------------------
The company API wedged at ~16:10 UTC. The API process was ALIVE and bound; /health timed out
at 5 s and at 30 s, with 54 connections queued on 127.0.0.1:8002. The r4 liveness probe
escalated correctly (SMS + voice call, P0, 16:13:12).

Two processes were the cause, both ORPHANS (parent dead, reparented to init), both started from
inline scripts days earlier, both in state R:

  PID 377634  /opt/company/.venv/bin/python -u -    elapsed 1-18:54  cpu 99.8%
              rchar 148 TB, 36.1 thousand million read syscalls, held
              /root/authority.db + -wal + -shm open with two deleted etilqs temp files
  PID 585597  /opt/company/scripts/ps_mcp_server.py  elapsed 1-16:33  cpu 99.5%
              rchar 174 TB, wchar 23.6 GB

The first one is the important one: a read transaction held open for 42 hours is what makes a
WAL unacceptable -- SQLite cannot checkpoint past the oldest reader, so `/root/authority.db-wal`
grew to 10,714,863,432 bytes (10.2 GB) on a 225 GB disk that was 91% full with 20 GB free.
`PRAGMA wal_checkpoint(TRUNCATE)` returned busy=1 while it lived and (0, 0, 0) the moment it
died. Killing the two processes, then truncating, returned 10 GB to the disk (91% -> 86%) and
/health went from a 30 s timeout to HTTP 200 in 0.16 s.

WHY A REAPER AND NOT A BETTER ALARM
-----------------------------------
`estate-monitor` HAD this. It logged `CRIT authority_wal_mb=10218.38MB` on 1048 consecutive runs
from 2026-10-27T05:24Z, roughly 35 hours, and escalated nothing -- by design, because only
`public_health_status` and `disk_free_deficit_gb` are allowed to escalate. Its alerts.jsonl was
not even written to disk. The monitor therefore watched the precursor grow for a day and a half
and told nobody, and the owner learned about it only when the API stopped answering.

An alarm on WAL size would have texted the owner 1048 times. The defect is not the threshold,
it is the orphan. Nothing on this estate reaps a process that has held a core since yesterday,
so this exists.

CRITERIA -- deliberately unambiguous, so no legitimate process can match
-----------------------------------------------------------------------
  cpu_pct >= 90 (measured over two samples 10 s apart, NOT the lifetime average)
  AND elapsed >= 6 h

Every legitimate long-lived process on this box idles: the four ps_mcp_server instances measured
0.0 / 0.0 / 0.2 / 0.0 % CPU, the API sits at 42% while serving, cron jobs finish in seconds. A
process at >=90% of a core for six straight hours is either wedged or looping; 42 hours of it
took the company down. An aggravating WARN is logged at 2 h if the process also holds the
authority database, without killing it -- a long legitimate DB job gets seen before it is reaped.

SAFETY
------
  * never touches pid 1, itself, its own parent, or systemd
  * never touches a name-protected process (sshd, systemd, tailscaled, esearch, cloudflared...)
  * never touches the company API's own ExecMainPID (it is *supposed* to be busy)
  * SIGTERM first, SIGKILL only after 20 s
  * SIGTERM on a reader destroys no data: SQLite in WAL mode is crash-safe by construction
    (the same guarantee as a power cut)
  * --dry-run reports and kills nothing
  * every action is appended to actions.jsonl and a status file records the last run, so a
    reaper that has been RUN is distinguishable from one that has been TESTED

Usage:  runaway-process-reaper.py [--dry-run] [--min-cpu 90] [--min-hours 6]
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE_DIR = os.environ.get("RUNAWAY_REAPER_DIR", "/var/lib/runaway-reaper")
STATUS_PATH = os.path.join(STATE_DIR, "status.json")
ACTIONS_PATH = os.path.join(STATE_DIR, "actions.jsonl")
CLK_TCK = os.sysconf("SC_CLK_TCK")
AUTHORITY_DB = "/root/authority.db"

# Names we will never kill, whatever their CPU. Matched as substrings of the cmdline.
PROTECTED = (
    "systemd", "sshd", "tailscaled", "cloudflared", "esearch",
    "phone-gate", "fail2ban", "systemd-resolve", "dbus", "cron",
    "uvicorn app.main:app",  # the company API: busy is its job
    "runaway-process-reaper",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def read_stat(pid: int) -> dict | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    # comm may contain spaces/parens -> split on the LAST ')'
    head, tail = raw.rsplit(")", 1)
    fields = tail.split()
    try:
        return {
            "comm": head.split("(", 1)[1],
            "state": fields[0],
            # utime=11, stime=12 in proc(5); after ')' the list starts at field 3
            "ticks": int(fields[11]) + int(fields[12]),
            "starttime": int(fields[19]),
        }
    except (IndexError, ValueError):
        return None


def cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""


def _elapsed(pid: int) -> float:
    """Uptime minus process start, both in seconds since boot."""
    with open("/proc/uptime") as fh:
        up = float(fh.read().split()[0])
    st = read_stat(pid)
    if not st:
        return 0.0
    return up - (st["starttime"] / CLK_TCK)


def holds_authority_db(pid: int) -> bool:
    fd_dir = f"/proc/{pid}/fd"
    try:
        for fd in os.listdir(fd_dir):
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if target.startswith(AUTHORITY_DB):
                return True
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    return False


def scan(protected_pids: set[int]) -> list[dict]:
    """Two-sample CPU measurement over 10 s for every process with >1s of CPU."""
    first: dict[int, tuple[int, float]] = {}
    t0 = time.time()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        st = read_stat(pid)
        if not st or st["state"] == "Z":
            continue
        first[pid] = (st["ticks"], t0)

    time.sleep(10)
    t1 = time.time()
    out = []
    for pid, (ticks0, _) in first.items():
        st = read_stat(pid)
        if not st or st["state"] == "Z" or pid in protected_pids:
            continue
        delta_ticks = st["ticks"] - ticks0
        elapsed = max(t1 - t0, 0.001)
        cpu_pct = (delta_ticks / CLK_TCK) / elapsed * 100.0
        if cpu_pct < 1.0:
            continue
        cmd = cmdline(pid)
        out.append({
            "pid": pid,
            "cpu_pct": round(cpu_pct, 1),
            "elapsed_s": round(_elapsed(pid), 0),
            "cmd": cmd[:200],
            "holds_authority_db": holds_authority_db(pid),
        })
    out.sort(key=lambda r: r["cpu_pct"], reverse=True)
    return out


def protected_pids() -> set[int]:
    pids = {1, os.getpid(), os.getppid()}
    try:
        out = subprocess.run(
            ["systemctl", "show", "company-api", "-p", "ExecMainPID", "--value"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out.isdigit():
            pids.add(int(out))
    except Exception:
        pass
    return pids


def is_protected_name(cmd: str) -> bool:
    return any(name in cmd for name in PROTECTED)


def terminate(pid: int, dry_run: bool) -> dict:
    if dry_run:
        return {"pid": pid, "action": "would-kill"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"pid": pid, "action": "already-gone"}
    except PermissionError as exc:
        return {"pid": pid, "action": "permission-denied", "error": str(exc)}
    for _ in range(20):
        time.sleep(1)
        if read_stat(pid) is None:
            return {"pid": pid, "action": "sigterm"}
    try:
        os.kill(pid, signal.SIGKILL)
        return {"pid": pid, "action": "sigkill-after-20s"}
    except ProcessLookupError:
        return {"pid": pid, "action": "sigterm"}


def passive_checkpoint() -> dict:
    """Reclaim what a killed reader was pinning.

    A read-only connection CANNOT checkpoint -- `mode=ro` returns
    `OperationalError: disk I/O error` the moment the checkpoint tries to write, which is how
    the first deployed version of this failed its own repair (measured 2026-10-28 16:22). So this
    opens read-write, runs PASSIVE first (never blocks a reader or a writer), and only runs
    TRUNCATE when PASSIVE reports nothing still busy -- which is exactly the sequence that
    returned 10.2 GB to the disk by hand.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(AUTHORITY_DB, timeout=30)
        passive = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        out = {"passive": list(passive) if passive else None}
        # (busy, log, checkpointed); busy == 0 means no reader is holding frames back
        if passive and passive[0] == 0:
            trunc = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            out["truncate"] = list(trunc) if trunc else None
        else:
            out["truncate"] = "skipped: a reader is still holding frames"
        conn.close()
        return out
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    min_cpu = float(args[args.index("--min-cpu") + 1]) if "--min-cpu" in args else 90.0
    min_hours = float(args[args.index("--min-hours") + 1]) if "--min-hours" in args else 6.0
    min_elapsed = min_hours * 3600

    os.makedirs(STATE_DIR, exist_ok=True)
    prot = protected_pids()

    try:
        procs = scan(prot)
    except Exception as exc:
        # An internal failure must be loud, not a silent "nothing found".
        status = {"at": now_iso(), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        with open(STATUS_PATH, "w") as fh:
            json.dump(status, fh, indent=1)
        print(json.dumps(status))
        return 2

    kills, warns = [], []
    for p in procs:
        if is_protected_name(p["cmd"]):
            continue
        if p["cpu_pct"] < min_cpu:
            continue
        if p["elapsed_s"] >= min_elapsed:
            result = terminate(p["pid"], dry_run)
            record = {**p, **result, "at": now_iso(), "dry_run": dry_run}
            with open(ACTIONS_PATH, "a") as fh:
                fh.write(json.dumps(record) + "\n")
            kills.append(record)
        elif p["holds_authority_db"] and p["elapsed_s"] >= 2 * 3600:
            warns.append({**p, "at": now_iso(), "why": "hot + holds authority.db for >2h"})

    checkpoint = None
    if kills and not dry_run:
        checkpoint = passive_checkpoint()

    status = {
        "at": now_iso(),
        "ok": True,
        "dry_run": dry_run,
        "min_cpu": min_cpu,
        "min_hours": min_hours,
        "scanned": len(procs),
        "killed": kills,
        "warned": warns,
        "checkpoint": checkpoint,
    }
    with open(STATUS_PATH, "w") as fh:
        json.dump(status, fh, indent=1)
    print(json.dumps({k: status[k] for k in ("at", "ok", "scanned", "killed", "warned")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
