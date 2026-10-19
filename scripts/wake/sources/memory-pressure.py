#!/usr/bin/env python3
"""FLAG SOURCE: memory pressure and OOM kills on the authority.

THE SIGNAL
----------
company-api (the company's front door, uvicorn on 127.0.0.1:8002) runs under a
MemoryMax of 12.28 GB on a 15 GB box. It repeatedly GROWS INTO that cap and is
then OOM-killed WITHIN ITS OWN CGROUP, which systemd records as a restart and
nobody ever reads.

WHAT THE MEMORY NUMBER MEANS
----------------------------
`MemoryCurrent` includes reclaimable page cache. On this host it can read above
60 percent while the service is under no pressure at all: the kernel is simply
using free RAM for file cache. The pressure that cannot be reclaimed is the
cgroup's `anon` plus `shmem` from memory.stat. The memory-high branch therefore
judges anon+shmem, not MemoryCurrent, and a cache-heavy/anon-low state is quiet.

WHY THIS SOURCE EXISTS, measured 2026-10-18
-------------------------------------------
Ten OOM kills in 24 hours, four of them inside two hours:

    Oct 18 01:21:12  company-api.service: Failed with result 'oom-kill'
    Oct 18 01:42:51  company-api.service: Failed with result 'oom-kill'
    Oct 18 02:21:49  company-api.service: Failed with result 'oom-kill'
    Oct 18 03:30:58  company-api.service: Failed with result 'oom-kill'

and the kernel's own record of each, identical to the kilobyte:

    Memory cgroup out of memory: Killed process 219223 (python)
    total-vm:22874432kB, anon-rss:12519032kB, UID:0

12,519,032 kB against a 12,884,901,888-byte cap. So this is not the machine
running out of memory -- it is the API filling its own cgroup. At idle it sits
near 4.7 GB and is flat over 80 seconds, so the growth is EPISODIC (it follows
work), and no linear leak rate is claimed here. What is certain is that it
reaches the cap and dies, and every death drops in-flight requests: a wake shift
talking to the API at that moment fails mid-item, and abandoned threads keep
SQLite locks, which is the estate's documented 'database is locked' mechanism.

THE RE-FIRE THIS SOURCE MUST NOT DO
-----------------------------------
Measured 2026-10-19: wake 1241 reported the 07:20:22 kill after the service had
already restarted at 08:14:00, and the rolling two-hour window kept that kill
visible long enough to alert on an outage that no longer existed. A kill older
than the current ExecMainStartTimestamp is covered by that restart. If the same
day's subject has already been alerted, it must not file a second flag. An
unalerted old kill is still reported once: an outage nobody saw is real work.

PRIORITY  high for an OOM kill in the window (it already happened), normal for a
          level crossing. An OOM kill is not a warning: it is an outage that has
          occurred.

SUBJECTS  memory-oom:<UTC day>     -- day-bucketed, declares its own staleness
          memory-high:<pct bucket>  -- a level that stays put must not re-file
          swap-high:<pct bucket>

MUST NEVER
    - restart, kill or reconfigure anything. This files work; the decision about
      a service belongs to the session that claims it, under RESTART-CONTRACT-V1.
    - recommend raising MemoryMax as a fix. The cap is what turned an unbounded
      leak into a predictable restart; raising it buys minutes and hides the cause.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "memory-pressure"
UNIT = os.environ.get("MEM_PRESSURE_UNIT", "company-api")
WINDOW_HOURS = float(os.environ.get("MEM_PRESSURE_WINDOW_H", "2"))
# 60 percent of the cap in anon+shmem. Kept env-overridable; the older
# MEM_PRESSURE_HIGH_PCT name is accepted for operators who already set it.
HIGH_ANON_PCT = float(
    os.environ.get(
        "MEM_PRESSURE_HIGH_ANON_PCT",
        os.environ.get("MEM_PRESSURE_HIGH_PCT", "60"),
    )
)
SWAP_PCT = float(os.environ.get("MEM_PRESSURE_SWAP_PCT", "90"))
COOLDOWN_SECONDS = 3600
CGROUP_ROOT = Path(os.environ.get("MEM_PRESSURE_CGROUP_ROOT", "/sys/fs/cgroup"))


def _sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise Unreadable("%s rc=%d: %s" % (" ".join(cmd), p.returncode,
                                           (p.stderr or "").strip()[:200]))
    return p.stdout


def _show(prop: str) -> str:
    out = _sh(["systemctl", "show", UNIT, "-p", prop, "--value"]).strip()
    return out


def _swap() -> tuple[int, int]:
    total = free = 0
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("SwapTotal:"):
                total = int(line.split()[1])
            elif line.startswith("SwapFree:"):
                free = int(line.split()[1])
    return total, free


def _exec_main_start() -> datetime | None:
    """When systemd last started the unit, or None when it is not running.

    `systemctl show -p ExecMainStartTimestamp --value` prints `n/a` for a stopped
    unit and a human timestamp like `Mon 2026-10-19 08:14:00 UTC` for a live one.
    The comparison only needs the instant, and an unparseable value must never
    suppress a kill: None means "do not apply the covered-kill rule".
    """
    raw = _show("ExecMainStartTimestamp").strip()
    if not raw or raw.lower() in {"n/a", "none", "-"}:
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z"):
        try:
            value = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return _flag.parse_dt(raw)


def _cgroup_path() -> Path:
    control = _show("ControlGroup").strip()
    if not control:
        raise Unreadable("ControlGroup is empty for %s" % UNIT)
    return CGROUP_ROOT / control.lstrip("/")


def _memory_stat() -> dict[str, int]:
    """Read the unit cgroup's memory.stat, the only place anon/shmem live."""
    path = _cgroup_path() / "memory.stat"
    try:
        text = path.read_text()
    except OSError as exc:
        raise Unreadable("cannot read %s: %s" % (path, exc)) from exc
    stats: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            stats[parts[0]] = int(parts[1])
        except ValueError:
            continue
    if "anon" not in stats or "shmem" not in stats:
        raise Unreadable("memory.stat at %s has no anon/shmem fields" % path)
    return stats


def _oom_kills(since_hours: float) -> list[tuple[datetime | None, str]]:
    """Every oom-kill line for the unit in the window, with its timestamp.

    journalctl is asked for short-iso timestamps so the kill can be compared with
    ExecMainStartTimestamp. Empty list is a real negative.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    lines = _flag.journal_grep(UNIT, since, "oom-kill")
    # Some deployed copies of _flag.py predate the journal-status filter and
    # return `-- No entries --` as if it were a record. A status banner is not a
    # kill: counting it would file an OOM finding on a clean window.
    real = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("-- ") and stripped.endswith(" --"):
            continue
        if "oom-kill" in line:
            real.append((_flag.journal_stamp(line), line))
    return real


def _as_int(raw: str) -> int:
    """systemd reports MemoryMax as the literal `infinity` on an unbounded unit.

    int("infinity") raises ValueError, which is NOT Unreadable, so it would escape this
    source's error contract and surface as "unexpected ValueError". An unbounded unit is a
    real state, not a read failure, and it is reported as 0 here so the % test is skipped.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _already_alerted(subject: str) -> bool:
    """Whether the wake store already has a row for this subject.

    The store is the record of what a human or a shift was told. A read failure is
    NOT evidence that no alert exists, but it also must not turn a live outage into
    an unreadable signal; the conservative action here is to report the kill again
    rather than silently suppress it. That is why an unreadable/missing store
    returns False.
    """
    db = _flag.inbox_db()
    if not db.is_file():
        return False
    try:
        conn = _flag.ro_connect(db)
        try:
            row = conn.execute(
                "SELECT 1 FROM wake WHERE subject = ? LIMIT 1", (subject,)
            ).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, Unreadable, OSError):
        return False
    return row is not None


def _kill_is_covered(
    kills: list[tuple[datetime | None, str]],
    start: datetime | None,
    subject: str,
) -> bool:
    """True when every kill predates the current run and was already alerted.

    A restart after the kill means the outage has ended. If no row exists, the
    kill has not been reported and still deserves one flag; if a newer kill
    happened after the start, the service is not merely recovering from an old
    outage and this returns False.
    """
    if not kills or start is None:
        return False
    stamped = [(ts, line) for ts, line in kills if ts is not None]
    if not stamped:
        return False
    last_ts = max(ts for ts, _line in stamped)
    return last_ts < start and _already_alerted(subject)


def collect(args) -> list:
    # A MISSING UNIT IS NOT A HEALTHY ONE. `systemctl show <bogus> -p MemoryCurrent`
    # exits 0 and prints an empty line, so without this check the source reports
    # "quiet" while measuring nothing -- which is the precise defect docs/mesh/178
    # section 1 is about, and this source nearly shipped with it (caught by its own
    # negative test on a bogus unit).
    if not _flag.unit_exists(UNIT):
        raise Unreadable("unit %s does not exist on this host" % UNIT)

    try:
        cur = _as_int(_show("MemoryCurrent"))
        mx = _as_int(_show("MemoryMax"))
        start = _exec_main_start()
        stat = _memory_stat()
    except Unreadable:
        raise
    except Exception as exc:  # noqa: BLE001 - one unreadable field is one signal
        raise Unreadable("cannot read the unit's memory: %s" % exc) from exc

    # A running service always has resident memory. Zero means the read failed, not
    # that the service is using nothing.
    if cur <= 0:
        raise Unreadable("MemoryCurrent read as 0 for %s -- a failed read, not a low value" % UNIT)

    anon_shmem = int(stat["anon"]) + int(stat["shmem"])
    if anon_shmem <= 0:
        raise Unreadable("anon+shmem read as 0 for %s -- a failed read, not a low value" % UNIT)

    kills = _oom_kills(WINDOW_HOURS)
    swap_total, swap_free = _swap()
    swap_used_pct = (100.0 * (swap_total - swap_free) / swap_total) if swap_total else 0.0
    mem_pct = (100.0 * cur / mx) if mx else 0.0
    anon_pct = (100.0 * anon_shmem / mx) if mx else 0.0
    last_kill = max((ts for ts, _line in kills if ts is not None), default=None)

    pct_bucket = int(anon_pct // 5) * 5
    swap_bucket = int(swap_used_pct // 5) * 5
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    oom_subject = "memory-oom:%s" % day
    covered = _kill_is_covered(kills, start, oom_subject)

    if getattr(args, "dry_run", False):
        print(
            "memory-pressure: current=%d (%.1f%%) anon+shmem=%d (%.1f%%) "
            "max=%d start=%s kills=%d covered=%s"
            % (cur, mem_pct, anon_shmem, anon_pct, mx, start.isoformat() if start else "n/a",
               len(kills), covered),
            file=sys.stderr,
        )

    findings = []

    if kills and not covered:
        findings.append(Finding(
            subject=oom_subject,
            priority="high",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=json.dumps({
                "unit": UNIT,
                "kills": len(kills),
                "window_h": WINDOW_HOURS,
                "memory_current": cur,
                "memory_max": mx,
                "anon_shmem": anon_shmem,
                "anon_pct": round(anon_pct, 1),
                "exec_main_start": start.isoformat() if start else None,
                "last_kill": last_kill.isoformat() if last_kill else None,
                "last": kills[-1][1][:200],
            }),
            prompt=(
                "COMPANY-API WAS OOM-KILLED. %d occurrence(s) in the last %g h on %s.\n\n"
                "THE KERNEL'S OWN RECORD OF WHAT HAPPENED (last line):\n"
                "    %s\n\n"
                "MEASURED NOW\n"
                "    MemoryCurrent %d bytes (%.1f%% of MemoryMax %d; includes reclaimable cache)\n"
                "    anon+shmem %d bytes (%.1f%% of the cap; the pressure that cannot be reclaimed)\n"
                "    swap %d/%d kB used (%.1f%%)\n\n"
                "WHAT THIS IS. uvicorn grows until it fills its own cgroup and the kernel kills it. "
                "The signature repeated ten times in 24 h on 2026-10-18, each at anon-rss ~12.5 GB "
                "against a 12.88 GB cap -- this is NOT the box running out of memory, it is the "
                "service reaching its own limit. At idle it sits near 4.7 GB and is flat over 80 s, "
                "so the growth is episodic and follows work.\n\n"
                "WHY IT MATTERS BEYOND THE OUTAGE. Each kill drops every in-flight request: a wake "
                "shift talking to the API at that moment fails mid-item, and abandoned threads hold "
                "SQLite locks, which is this estate's documented 'database is locked' mechanism. It "
                "is a plausible cause of a share of the failed wake rows.\n\n"
                "WHAT TO DO, in this order, and nothing here is a sweep:\n"
                "  1. Confirm the restart is clean: `systemctl is-active %s`, "
                "`curl -s -o /dev/null -w '%%{http_code}' http://127.0.0.1:8002/v1/models` -> 200.\n"
                "  2. Record what was running at the moment of the kill: "
                "`journalctl -u %s --since '-15 min' --no-pager | tail -40`. An episodic spike has a "
                "caller, and the caller is in that tail.\n"
                "  3. DO NOT raise MemoryMax as the fix. The cap is what converted an unbounded "
                "leak into a predictable restart; raising it buys minutes and hides the cause. File "
                "a ledger item for the leak with the spike's caller named, and let a dedicated shift "
                "profile it.\n"
                "  4. If the restart did not come back clean, that is an outage: say so in the "
                "conversation, not only in the ledger.\n"
                "  5. Prove: quote the `systemctl is-active` and the HTTP code.") % (
                    len(kills), WINDOW_HOURS, UNIT, kills[-1][1][:300],
                    cur, mem_pct, mx, anon_shmem, anon_pct,
                    swap_total - swap_free, swap_total, swap_used_pct,
                    UNIT, UNIT),
        ))

    if anon_pct >= HIGH_ANON_PCT:
        findings.append(Finding(
            subject="memory-high:%d" % pct_bucket,
            priority="normal",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=json.dumps({
                "unit": UNIT,
                "memory_current": cur,
                "memory_max": mx,
                "anon_shmem": anon_shmem,
                "anon_pct": round(anon_pct, 1),
                "current_pct": round(mem_pct, 1),
            }),
            prompt=(
                "%s'S ANON+SHMEM MEMORY IS AT %.1f%% OF ITS CAP.\n\n"
                "    MemoryCurrent %d bytes of MemoryMax %d (%.1f%%; page cache included)\n"
                "    anon+shmem %d bytes (%.1f%%; non-reclaimable pressure)\n"
                "    swap %d/%d kB used (%.1f%%)\n"
                "    OOM kills in the last %g h: %d\n\n"
                "At this level the next spike is an outage rather than a warning. It is currently "
                "approaching its own cap, not the machine's: measured 2026-10-18 it reaches ~12.5 GB "
                "and is killed inside its cgroup, ten times in 24 h. The memory-high branch now "
                "judges anon+shmem, not MemoryCurrent, so a cache-heavy but pressure-free service "
                "does not wake a shift.\n\n"
                "WHAT TO DO: read `journalctl -u %s --since '-20 min' --no-pager | tail -60` and name "
                "the caller that is growing it. Then decide between (a) a bounded fix in that caller, "
                "or (b) a deliberate restart under RESTART-CONTRACT-V1 recorded on a ledger item. Do "
                "not raise the cap to make this line go away.") % (
                    UNIT, anon_pct, cur, mx, mem_pct, anon_shmem, anon_pct,
                    swap_total - swap_free, swap_total, swap_used_pct,
                    WINDOW_HOURS, len(kills), UNIT),
        ))

    if swap_used_pct >= SWAP_PCT:
        findings.append(Finding(
            subject="swap-high:%d" % swap_bucket,
            priority="normal",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=json.dumps({"swap_used_pct": round(swap_used_pct, 1),
                                "swap_total_kb": swap_total, "swap_free_kb": swap_free}),
            prompt=(
                "THE AUTHORITY IS AT %.1f%% SWAP USED (%d of %d kB free).\n\n"
                "When swap is this full, the kernel's reclaim path slows every process and SQLite "
                "writes become waits; this estate has already seen `database is locked` storms "
                "produced by that mechanism rather than by a code defect. Measured 2026-10-18: "
                "8 GB swap with ~4.6 GB in use.\n\n"
                "WHAT TO DO: identify the resident set that is swapped out -- "
                "`for p in /proc/[0-9]*; do ...` is too slow; use `ps aux --sort=-rss | head` for the "
                "live consumers and `smem -t -k -c pss,command 2>/dev/null | head` when available. "
                "Then file what is growing. Do not drop caches and call it fixed.") % (
                    swap_used_pct, swap_free, swap_total),
        ))

    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
