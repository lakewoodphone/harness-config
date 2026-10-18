#!/usr/bin/env python3
"""FLAG SOURCE: memory pressure and OOM kills on the authority.

THE SIGNAL
----------
company-api (the company's front door, uvicorn on 127.0.0.1:8002) runs under a
MemoryMax of 12.28 GB on a 15 GB box. It repeatedly GROWS INTO that cap and is
then OOM-killed WITHIN ITS OWN CGROUP, which systemd records as a restart and
nobody ever reads.

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

The estate already watches DISK (sources/disk-space.py, added after two near
fills). Nothing watched MEMORY, so ten restarts in a day were invisible. That is
the gap this file closes, and it is the same shape as every other entry in
docs/mesh/178: a failure whose only evidence was a line in a log nobody read.

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
HIGH_PCT = float(os.environ.get("MEM_PRESSURE_HIGH_PCT", "80"))
SWAP_PCT = float(os.environ.get("MEM_PRESSURE_SWAP_PCT", "90"))
COOLDOWN_SECONDS = 3600


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


def _oom_kills(since_hours: float) -> list[str]:
    """Every oom-kill line for the unit in the window. Empty list is a real negative."""
    out = _sh(["journalctl", "-u", UNIT, "--since", "-%d min" % int(since_hours * 60),
               "--no-pager"])
    return [ln for ln in out.splitlines() if "oom-kill" in ln]


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
    except Unreadable as exc:
        raise Unreadable("cannot read the unit's memory: %s" % exc)

    # A running service always has resident memory. Zero means the read failed, not
    # that the service is using nothing.
    if cur <= 0:
        raise Unreadable("MemoryCurrent read as 0 for %s -- a failed read, not a low value" % UNIT)

    kills = _oom_kills(WINDOW_HOURS)
    swap_total, swap_free = _swap()
    swap_used_pct = (100.0 * (swap_total - swap_free) / swap_total) if swap_total else 0.0
    mem_pct = (100.0 * cur / mx) if mx else 0.0

    pct_bucket = int(mem_pct // 5) * 5
    swap_bucket = int(swap_used_pct // 5) * 5
    day = datetime.now(timezone.utc).strftime("%Y%m%d")

    findings = []

    if kills:
        findings.append(Finding(
            subject="memory-oom:%s" % day,
            priority="high",
            kind="repair",
            defer_on_cooldown=False,
            cooldown_seconds=COOLDOWN_SECONDS,
            context=json.dumps({"unit": UNIT, "kills": len(kills), "window_h": WINDOW_HOURS,
                                "memory_current": cur, "memory_max": mx,
                                "last": kills[-1][:200]}),
            prompt=(
                "COMPANY-API WAS OOM-KILLED. %d occurrence(s) in the last %g h on %s.\n\n"
                "THE KERNEL'S OWN RECORD OF WHAT HAPPENED (last line):\n"
                "    %s\n\n"
                "MEASURED NOW\n"
                "    MemoryCurrent %d bytes (%.1f%% of MemoryMax %d)\n"
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
                    len(kills), WINDOW_HOURS, UNIT, kills[-1][:300],
                    cur, mem_pct, mx, swap_total - swap_free, swap_total, swap_used_pct,
                    UNIT, UNIT),
        ))

    if mem_pct >= HIGH_PCT:
        findings.append(Finding(
            subject="memory-high:%d" % pct_bucket,
            priority="normal",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=json.dumps({"unit": UNIT, "memory_current": cur, "memory_max": mx,
                                "pct": round(mem_pct, 1)}),
            prompt=(
                "%s IS AT %.1f%% OF ITS MEMORY CAP.\n\n"
                "    MemoryCurrent %d bytes of MemoryMax %d\n"
                "    swap %d/%d kB used (%.1f%%)\n"
                "    OOM kills in the last %g h: %d\n\n"
                "At this level the next spike is an outage rather than a warning. It is currently "
                "approaching its own cap, not the machine's: measured 2026-10-18 it reaches ~12.5 GB "
                "and is killed inside its cgroup, ten times in 24 h.\n\n"
                "WHAT TO DO: read `journalctl -u %s --since '-20 min' --no-pager | tail -60` and name "
                "the caller that is growing it. Then decide between (a) a bounded fix in that caller, "
                "or (b) a deliberate restart under RESTART-CONTRACT-V1 recorded on a ledger item. Do "
                "not raise the cap to make this line go away.") % (
                    UNIT, mem_pct, cur, mx, swap_total - swap_free, swap_total, swap_used_pct,
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
