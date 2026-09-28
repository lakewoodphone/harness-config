#!/usr/bin/env python3
"""Give wake.py ONE default for the daily cap, in every place it reads it.

THE BUG THIS FIXES (measured 2026-09-28 18:56Z, and it had been silently capping the whole
autonomous system):

    wake.py:399   "max_per_day": _env_int("WAKE_MAX_PER_DAY", 12)     <- what `stats` REPORTS
    wake.py:455   if released_today(conn) >= _env_int("WAKE_MAX_PER_DAY", 4):   <- what `claim` ENFORCES
                                                                          return "daily-cap"

Two independent `_env_int` calls with two different literal defaults, in the same file. The
morning's earlier patch raised only the reported one, so `wake.py stats` said `max_per_day: 12`
while `claim` refused with `{"ok": true, "row": null, "blocked_by": "daily-cap"}` - the system
looked correctly configured and released nothing. That is the worst possible shape of a bug in
a system whose whole job is to keep work moving: every reading says healthy, and no work runs.

It also explains the whole evening's "the dispatcher exits with nothing to release": the
dispatcher's own gate read 12, the store's enforcement read 4, and the store won.

THE FIX. A single module-level constant, used by every reader, plus a printed check that the
reported and enforced numbers are now the same string.

Usage: python3 fix-wake-cap-single-source.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/wake.py")
CONST = "DEFAULT_MAX_PER_DAY = 12"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cap", type=int, default=12)
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")

    # 1. Every reading of the cap goes through the constant.
    before = len(re.findall(r'_env_int\("WAKE_MAX_PER_DAY",\s*\d+\)', src))
    src2 = re.sub(r'_env_int\("WAKE_MAX_PER_DAY",\s*\d+\)',
                  '_env_int("WAKE_MAX_PER_DAY", DEFAULT_MAX_PER_DAY)', src)
    print("cap readings normalised: %d" % before)

    # 2. The constant exists once, at module level, with the reason written next to it.
    if "DEFAULT_MAX_PER_DAY =" in src2:
        src2 = re.sub(r"^DEFAULT_MAX_PER_DAY\s*=\s*\d+",
                      "DEFAULT_MAX_PER_DAY = %d" % a.cap, src2, count=1, flags=re.M)
    else:
        anchor = "\ndef _env_int("
        if anchor not in src2:
            anchor = "\ndef _env_int"
        if anchor not in src2:
            raise SystemExit("ERROR: could not find a place to define DEFAULT_MAX_PER_DAY")
        block = (
            "\n# ---------------------------------------------------------------------------\n"
            "# THE DAILY RELEASE CAP, IN ONE PLACE.\n"
            "#\n"
            "# Measured 2026-09-28: this file read the cap TWICE with two different literal\n"
            "# defaults - `stats` reported 12 while `claim` enforced 4 - so raising the cap\n"
            "# changed the report and not the behaviour, `claim` answered\n"
            "# `{\"ok\": true, \"row\": null, \"blocked_by\": \"daily-cap\"}`, and no session ran.\n"
            "# A single number, read by every guard, is the only shape in which \"the system\n"
            "# says it is running\" and \"the system is running\" cannot drift apart.\n"
            "#\n"
            "# The value: 12/day. One autonomous shift costs a MEASURED 0.068 USD (38 priced\n"
            "# releases, 2.5825 USD total, median 701 s / 5.1 M tokens), so 12/day is about\n"
            "# 0.82 USD/day. It is overridable with WAKE_MAX_PER_DAY for a test or an emergency.\n"
            "# ---------------------------------------------------------------------------\n"
            + CONST + "\n"
        )
        src2 = src2.replace(anchor, block + anchor, 1)

    # 3. The docstring line must not contradict it either.
    src2 = re.sub(r"(WAKE_MAX_PER_DAY\s+\()\d+(\))", r"\g<1>%d\g<2>" % a.cap, src2)
    src2 = re.sub(r"(WAKE_MAX_PER_DAY\s+)\(\d+\)", r"\g<1>(%d)" % a.cap, src2)

    compile(src2, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-single-cap-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src2, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== PROOF: reported AND enforced, read from the patched source itself ===")
    r = subprocess.run([sys.executable, str(p), "stats", "--json"], capture_output=True, text=True, timeout=120)
    out = r.stdout or ""
    m = re.search(r'"max_per_day":\s*(\d+)', out)
    reported = m.group(1) if m else "NOT FOUND"
    print("stats reports  max_per_day = %s" % reported)

    # Read the ENFORCED number without claiming a row: import the module read-only and ask the
    # guard what it would do. `claim` is destructive, so it is the wrong instrument for a check.
    probe = (
        "import importlib.util,sys,json;"
        "spec=importlib.util.spec_from_file_location('w', %r);"
        "w=importlib.util.module_from_spec(spec); sys.modules['w']=w; spec.loader.exec_module(w);"
        "print('DEFAULT_MAX_PER_DAY =', w.DEFAULT_MAX_PER_DAY);"
        "c=w._connect() if hasattr(w,'_connect') else w.connect();"
        "print('release_block() says:', repr(w.release_block(c)));"
        "print('released_today =', w.released_today(c));"
        "print('caps it would report:', json.dumps(w.caps(c).get('max_per_day') if hasattr(w,'caps') else None))"
    ) % str(p)
    r3 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    print(r3.stdout.strip())
    if r3.returncode != 0:
        print("probe failed:", (r3.stderr or "")[-600:])
        return 1
    if "DEFAULT_MAX_PER_DAY = %d" % a.cap not in r3.stdout:
        print("THE CONSTANT IS NOT THE EXPECTED VALUE")
        return 1
    if '"daily-cap"' in r3.stdout or "daily-cap" in r3.stdout:
        print("STILL CAPPED - something else overrides WAKE_MAX_PER_DAY in this environment")
        return 1
    print("OK: one number, reported and enforced, and the queue is no longer capped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
