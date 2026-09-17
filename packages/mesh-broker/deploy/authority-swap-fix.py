#!/usr/bin/env python3
"""
O5 swap fix: get the authority's swap off 100% WITHOUT deleting anything and without touching
any process. Read-only with respect to every byte of data on the machine.

WHAT IT DOES, AND WHY THIS AND NOT SOMETHING ELSE

The probe found that ~4.1 GiB of the authority's 4,095 MiB of used swap is tmpfs pages under
/tmp that were evicted to swap long ago and never faulted back, plus 69 MiB of process
anonymous memory. Nothing is currently swapping (si/so ~= 0).

There are three ways to reclaim it, and only one of them is safe here:

  1. DELETE the stale /tmp scratch. The durable fix, and NOT performed by this script: it is
     other streams' and other sessions' scratch, `rm -rf` is forbidden without a per-action yes,
     and the files include live browser profiles the phone gate is using this minute.
  2. swapoff / mkswap / swapon. Reclaims everything, but it must allocate all 4 GiB at once and
     it removes the memory outlet entirely for the duration. On the company's authoritative
     server, at night, that is a risk with no upside over (3).
  3. READ the files back in. Faulting a swapped-out tmpfs page in frees its swap slot and puts
     the page back in RAM. It is incremental, it is interruptible, it cannot OOM-kill a service
     (the pages it pulls in stay reclaimable), and it destroys nothing. THIS IS WHAT RUNS.

Then it lowers `vm.swappiness` (60 -> 10), because the reason the kernel chose cold tmpfs pages
over the 10.9 GiB of clean page cache sitting beside them is that its default is tuned for a
desktop. It is persisted in /etc/sysctl.d so it survives a reboot, and it is reversible with one
`sysctl -w`.

  sudo python3 o5-swap-fix.py [--root /tmp] [--swappiness 10] [--dry-run]

Prints before/after numbers and the delta attributable to the read-back.
"""

import argparse
import os
import stat
import sys
import time

CHUNK = 1 << 20


def meminfo():
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = rest.strip()
    return out


def kb(mem, key):
    return int(mem.get(key, "0 kB").split()[0])


def snapshot(label):
    mem = meminfo()
    swap_used = kb(mem, "SwapTotal") - kb(mem, "SwapFree")
    print(f"{label}: swap used {swap_used:,} kB ({swap_used / 1024:.1f} MiB) of {kb(mem, 'SwapTotal'):,} kB"
          f"  |  MemFree {kb(mem, 'MemFree') / 1024:.0f} MiB  MemAvailable {kb(mem, 'MemAvailable') / 1024:.0f} MiB"
          f"  |  Shmem {kb(mem, 'Shmem') / 1024:.0f} MiB")
    return swap_used


def read_swappiness():
    with open("/proc/sys/vm/swappiness") as fh:
        return int(fh.read().strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp")
    ap.add_argument("--swappiness", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("run me with sudo: it reads files owned by other users and writes /etc/sysctl.d", file=sys.stderr)
        return 2

    print(f"at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}  root={args.root}")
    mem = meminfo()
    avail_mib = kb(mem, "MemAvailable") / 1024
    swap_used_mib = (kb(mem, "SwapTotal") - kb(mem, "SwapFree")) / 1024
    # The read-back must fault about `swap_used` MiB back into RAM. Refuse if the machine does not
    # have several times that available: this runs on the company's authoritative server and the
    # whole point is to make it MORE able to absorb a spike, not less.
    need_mib = swap_used_mib * 2
    if avail_mib < max(4096, need_mib):
        print(f"REFUSING: MemAvailable is {avail_mib:.0f} MiB and this would fault ~{swap_used_mib:.0f} MiB "
              f"back in; I want at least {max(4096, need_mib):.0f} MiB available first. Nothing changed.",
              file=sys.stderr)
        return 3
    print(f"guard: MemAvailable {avail_mib:.0f} MiB, swap to reclaim ~{swap_used_mib:.0f} MiB - proceeding")
    before_swap = snapshot("before")

    files = 0
    bytes_read = 0
    failed = 0
    started = time.time()
    for dirpath, _dirnames, filenames in os.walk(args.root, onerror=lambda e: None):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            # Regular files only: a FIFO would block forever and a device is not scratch.
            if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                continue
            try:
                with open(path, "rb", buffering=0) as fh:
                    while True:
                        block = fh.read(CHUNK)
                        if not block:
                            break
                        bytes_read += len(block)
                files += 1
            except OSError:
                failed += 1
                continue
    elapsed = time.time() - started
    print(f"read {bytes_read / 1048576:.0f} MiB from {files:,} file(s) under {args.root} in {elapsed:.1f} s"
          f" ({failed:,} unreadable, skipped). Nothing was written and nothing was deleted.")
    if args.dry_run:
        print("--dry-run: stopping before the sysctl change")
        return 0

    # Let the kernel finish the page-ins it started before reading the counter again.
    time.sleep(1.0)
    after_swap = snapshot("after ")
    freed = before_swap - after_swap
    print(f"REclaimed by faulting the pages back in: {freed:,} kB ({freed / 1024:.1f} MiB)")

    current = read_swappiness()
    print(f"\nvm.swappiness is {current}; setting it to {args.swappiness}")
    print("  why: with 10.9 GiB of clean page cache on this host, a swappiness of 60 makes the")
    print("  kernel evict cold tmpfs pages to swap before dropping reclaimable cache. That is the")
    print("  mechanism that filled a 4 GiB swap area with files nobody was reading.")
    if current != args.swappiness:
        with open("/proc/sys/vm/swappiness", "w") as fh:
            fh.write(str(args.swappiness))
        print(f"  live value now: {read_swappiness()}")
    conf = "/etc/sysctl.d/99-mesh-authority-swap.conf"
    with open(conf, "w") as fh:
        fh.write("# Written by stream O5 of the overnight mesh program, 2026-09-17.\n"
                 "# docs/mesh/86-authority.md §2.\n"
                 "#\n"
                 "# The authority's 4 GiB swap area was 100% full of cold tmpfs pages (/tmp is a\n"
                 "# 12 GiB tmpfs holding ~5.9 GiB of scratch) while 10.9 GiB of clean page cache sat\n"
                 "# unused, because the kernel's default swappiness prefers to evict shmem. The broker\n"
                 "# reads mem.swapUsedPct and halves a swapping node's slots, so a full swap area made\n"
                 "# the authority rank as 1 slot instead of 3 - correctly, but for a reason that was a\n"
                 "# tuning artefact rather than memory pressure. Nothing is currently swapping.\n"
                 "#\n"
                 "# Reversible:  sudo sysctl -w vm.swappiness=60   ;   sudo rm " + conf + "\n"
                 "vm.swappiness = " + str(args.swappiness) + "\n")
    print(f"  persisted in {conf}: vm.swappiness = {args.swappiness}")

    time.sleep(1.0)
    final = snapshot("final ")
    print(f"\nnet swap change from start: {before_swap - final:,} kB "
          f"({(before_swap - final) / 1024:.1f} MiB); swap is now "
          f"{100.0 * final / max(1, kb(meminfo(), 'SwapTotal')):.1f}% used")
    print("WHAT THIS DOES NOT FIX: /tmp is still a 12 GiB tmpfs holding gigabytes of stale scratch.")
    print("Deleting that scratch is the durable fix and is the OWNER'S call - it is other sessions'")
    print("work and it is destruction. See docs/mesh/86-authority.md §2.5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
