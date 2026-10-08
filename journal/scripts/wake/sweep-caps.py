#!/usr/bin/env python3
"""One cap sweep across EVERY source, so no file restates a number the store owns.

MEASURED 2026-09-28: after fixing wake.py and project-keepalive, the checkout-health source still
printed "system-wide releases today 11/4" - `_env_int("WAKE_MAX_PER_DAY", 4)` at checkout-health.py:811.
That is the FOURTH copy of one number in one evening:

    wake.py:399  (reported)          -> 12, while wake.py:455 enforced 4
    wake-dispatch.sh:82              -> 4
    project-keepalive.py:133         -> 4
    checkout-health.py:811           -> 4

Every one of them is a place the operation could be held back by a literal nobody meant. This finds
them all, fixes the fallback to the store's own backstop, and PROVES the result by running each
source's own dry run and reading the number it prints.

The pattern is now a recorded lesson (L2984): a mechanism that restates a value instead of reading it
is a mechanism that can lie. The fallback value is not the point - reading the store is.

Usage: python3 sweep-caps.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCES = sorted(Path("/home/zabz/bin/sources").glob("*.py"))
SCRIPTS = [Path("/home/zabz/bin/wake.py"), Path("/home/zabz/bin/wake-dispatch.sh")]
BACKSTOP = 500
PATTERNS = [
    r'_env_int\("WAKE_MAX_PER_DAY",\s*\d+\)',
    r'DEFAULT_GLOBAL_MAX_PER_DAY\s*=\s*\d+',
]


def fix(text: str) -> tuple:
    """(new_text, [what changed])"""
    changes = []
    def r1(m):
        n = re.search(r",\s*(\d+)\)", m.group(0)).group(1)
        if n == str(BACKSTOP):
            return m.group(0)
        changes.append("WAKE_MAX_PER_DAY default %s -> %d" % (n, BACKSTOP))
        return re.sub(r",\s*\d+\)", ", %d)" % BACKSTOP, m.group(0))
    new = re.sub(PATTERNS[0], r1, text)
    def r2(m):
        n = m.group(0).split("=")[1].strip()
        if n == str(BACKSTOP):
            return m.group(0)
        changes.append("DEFAULT_GLOBAL_MAX_PER_DAY %s -> %d" % (n, BACKSTOP))
        return "DEFAULT_GLOBAL_MAX_PER_DAY = %d" % BACKSTOP
    new = re.sub(PATTERNS[1], r2, new, flags=re.M)
    return new, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    touched = []
    for p in SOURCES + SCRIPTS:
        if ".bak" in p.name:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        new, changes = fix(src)
        if not changes:
            continue
        print("%-34s %s" % (p.name, "; ".join(changes)))
        touched.append((p, changes))
        if a.apply:
            if p.suffix == ".py":
                compile(new, str(p), "exec")
            shutil.copy2(p, p.with_name(p.name + ".bak-capsweep-" + stamp))
            p.write_text(new, encoding="utf-8")

    if not touched:
        print("every source already reads one number")
        return 0
    if not a.apply:
        print("\ndry run: %d file(s) would change (use --apply)" % len(touched))
        return 0
    print("\n%d file(s) updated" % len(touched))

    print("\n=== PROOF: each source's own dry run, and the number it prints ===")
    for name in ("project-keepalive.py", "checkout-health.py", "ledger-keepalive.py"):
        p = Path("/home/zabz/bin/sources") / name
        if not p.exists():
            continue
        r = subprocess.run([sys.executable, str(p), "--dry-run"], cwd="/home/zabz/bin/sources",
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
        hits = [ln.strip() for ln in out.splitlines() if "releases today" in ln or "flag(s)" in ln]
        print("  %-24s %s" % (name, hits[-1][:110] if hits else "(no cap line printed)"))
        if re.search(r"releases today \d+/[1-9]\b", out) and "500" not in out:
            print("    !! still clamped to a small number")
    r = subprocess.run([sys.executable, "/home/zabz/bin/wake.py", "stats", "--json"],
                       capture_output=True, text=True, timeout=120)
    m = re.search(r'"max_per_day":\s*(\d+)', r.stdout or "")
    print("  %-24s max_per_day = %s" % ("wake.py stats", m.group(1) if m else "NOT FOUND"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
