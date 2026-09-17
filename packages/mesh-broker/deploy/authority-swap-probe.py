#!/usr/bin/env python3
"""
O5 swap probe: WHICH pages are actually sitting in swap on the authority.

The question it answers is not "how much swap is used" (free(1) answers that) but "whose
memory is it". `VmSwap` in /proc/<pid>/status counts a process's ANONYMOUS pages that are in
swap; shmem (tmpfs) pages in swap belong to a file, not to a process, and appear in NO
process's VmSwap at all. That difference is the whole finding, so it is measured directly:

  * sum VmSwap over every process  -> process anon memory in swap
  * mincore() over every file on the tmpfs at /tmp -> how much of those files is NOT resident,
    i.e. how much of them is in swap

mincore(2) reports, per page, whether that page is resident in RAM. For a tmpfs file the
non-resident pages are exactly the swapped-out ones, so this is a measurement and not an
inference from a subtraction.

Read-only: it mmaps with ACCESS_COPY (a private, copy-on-write mapping) and never writes.

  sudo python3 o5-swap-probe.py [--root /tmp] [--min-bytes 4096] [--top 25]
"""

import argparse
import ctypes
import ctypes.util
import mmap
import os
import stat
import sys

PAGE = os.sysconf("SC_PAGE_SIZE")

libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
libc.mincore.restype = ctypes.c_int


def meminfo():
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = rest.strip()
    return out


def kb(mem, key):
    return int(mem.get(key, "0 kB").split()[0])


def process_swap():
    """{pid: (swap_kB, cmdline)} for every process that has any anonymous memory in swap."""
    rows = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/status") as fh:
                swap = 0
                for line in fh:
                    if line.startswith("VmSwap:"):
                        swap = int(line.split()[1])
                        break
            if swap <= 0:
                continue
            with open(f"/proc/{name}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            rows.append((swap, int(name), cmd[:110]))
        except (OSError, ValueError, IndexError):
            continue
    rows.sort(reverse=True)
    return rows


def residency(path):
    """(size_bytes, resident_bytes) for one regular file, or None if it cannot be mapped."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        size = os.fstat(fd).st_size
        if size <= 0:
            return None
        length = ((size + PAGE - 1) // PAGE) * PAGE
        try:
            mm = mmap.mmap(fd, size, access=mmap.ACCESS_COPY)
        except (OSError, ValueError):
            return None
        try:
            addr = ctypes.addressof(ctypes.c_char.from_buffer(mm))
            npages = (length + PAGE - 1) // PAGE
            vec = ctypes.create_string_buffer(npages)
            if libc.mincore(ctypes.c_void_p(addr), ctypes.c_size_t(length), vec) != 0:
                return None
            resident = sum(1 for i in range(npages) if vec[i] and (vec[i][0] & 1))
            return size, resident * PAGE
        finally:
            mm.close()
    finally:
        os.close(fd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp")
    ap.add_argument("--min-bytes", type=int, default=4096)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    mem = meminfo()
    print(f"=== /proc/meminfo at {__import__('datetime').datetime.utcnow().isoformat()}Z ===")
    for key in ("MemTotal", "MemFree", "MemAvailable", "Cached", "Shmem", "SwapCached",
                "SwapTotal", "SwapFree", "AnonPages"):
        print(f"  {key:14s} {kb(mem, key):>12,} kB  ({kb(mem, key) / 1024:>8.1f} MiB)")
    swap_used_kb = kb(mem, "SwapTotal") - kb(mem, "SwapFree")
    print(f"  {'SWAP USED':14s} {swap_used_kb:>12,} kB  ({swap_used_kb / 1024:>8.1f} MiB)"
          f"  = {100.0 * swap_used_kb / max(1, kb(mem, 'SwapTotal')):.1f}% of swap")

    rows = process_swap()
    total_proc = sum(r[0] for r in rows)
    print(f"\n=== process ANONYMOUS memory in swap: {total_proc:,} kB ({total_proc / 1024:.1f} MiB) "
          f"across {len(rows)} process(es) ===")
    for swap, pid, cmd in rows[:args.top]:
        print(f"  {swap:>9,} kB  pid {pid:<8} {cmd}")
    if not rows:
        print("  (none)")
    unattributed = swap_used_kb - total_proc
    print(f"\n  swap used minus process VmSwap = {unattributed:,} kB ({unattributed / 1024:.1f} MiB)"
          f"  <- this is memory NO process owns: shmem/tmpfs, or kernel")

    print(f"\n=== mincore() over every regular file >= {args.min_bytes} B under {args.root} ===")
    files = 0
    size_total = 0
    resident_total = 0
    swapped_per_file = []
    unreadable = 0
    for dirpath, _dirnames, filenames in os.walk(args.root, onerror=lambda e: None):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size < args.min_bytes:
                continue
            got = residency(path)
            if got is None:
                unreadable += 1
                continue
            size, resident = got
            files += 1
            size_total += size
            resident_total += min(resident, size)
            swapped = max(0, size - resident)
            if swapped > 0:
                swapped_per_file.append((swapped, size, path))
    swapped_per_file.sort(reverse=True)
    print(f"  files measured      : {files:,}  ({unreadable:,} could not be mapped, skipped)")
    print(f"  bytes on the tmpfs  : {size_total:,}  ({size_total / 1048576:.1f} MiB)")
    print(f"  RESIDENT in RAM     : {resident_total:,}  ({resident_total / 1048576:.1f} MiB)")
    print(f"  NOT resident (=swap): {size_total - resident_total:,}  ({(size_total - resident_total) / 1048576:.1f} MiB)")
    print(f"\n  --- the {args.top} files holding the most swapped-out pages ---")
    for swapped, size, path in swapped_per_file[:args.top]:
        print(f"  {swapped / 1048576:>8.1f} MiB swapped of {size / 1048576:>8.1f} MiB  {path}")

    print("\n=== the comparison that decides it ===")
    tmpfs_swapped = (size_total - resident_total) / 1024
    print(f"  process anon in swap      : {total_proc:>12,} kB")
    print(f"  tmpfs files in swap       : {tmpfs_swapped:>12,.0f} kB")
    print(f"  swap used (authoritative) : {swap_used_kb:>12,} kB")
    print(f"  accounted for             : {total_proc + tmpfs_swapped:>12,.0f} kB "
          f"({100.0 * (total_proc + tmpfs_swapped) / max(1, swap_used_kb):.1f}% of used swap)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
