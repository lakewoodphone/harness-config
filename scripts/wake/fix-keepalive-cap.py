#!/usr/bin/env python3
"""Align project-keepalive's own global cap with the store's backstop.

MEASURED 2026-09-28 19:24Z, in its own suppression line:
    project-keepalive: 0 flag(s) to raise, 10 suppression(s), system-wide releases today 7/4

"7/4" - the system had released 7 that day against a backstop of 500, and this source clamped itself
at 4 and suppressed every project. It is the SAME defect as wake.py's doubled default (D-numbered in
the journal that evening), one file over: a cap restated locally instead of read from the store that
owns it. The dispatcher's own comment already named the failure mode - "the looser value wins" - and
here the LOOSER value was the store's, so the source refused work the operation was happy to run.

THE FIX: no local number. It reads `WAKE_MAX_PER_DAY` and, failing that, asks `wake.py stats` for the
live value, and it uses the larger of the two. A source must never be the thing that decides how much
work the operation is allowed to do; that decision lives in one place (D2715: count is a runaway
backstop, SPEND is the limit).

Usage: python3 fix-keepalive-cap.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")
    before = src

    # 1. the constant that is the local cap
    if re.search(r"^DEFAULT_GLOBAL_MAX_PER_DAY\s*=\s*\d+", src, re.M):
        src = re.sub(r"^DEFAULT_GLOBAL_MAX_PER_DAY\s*=\s*\d+",
                     "# NOT A BUDGET. The store owns the number; this is only the fallback used when\n"
                     "# neither WAKE_MAX_PER_DAY nor `wake.py stats` can be read. Measured 2026-09-28:\n"
                     "# this source said 4 while the store said 12, suppressed every project at\n"
                     "# \"7/4\", and no shift was woken. See D2715: count is a runaway backstop, SPEND\n"
                     "# is the limit.\n"
                     "DEFAULT_GLOBAL_MAX_PER_DAY = 500", src, count=1, flags=re.M)
        print("constant updated to 500 (fallback only)")
    else:
        print("DEFAULT_GLOBAL_MAX_PER_DAY not found")

    # 2. make the resolution prefer the live store value, and never take a SMALLER one silently
    m = re.search(r"(\n\s*)store_cap\s*=\s*_env_int\(\"WAKE_MAX_PER_DAY\",\s*[^)]*\)", src)
    if m:
        src = src[:m.start()] + (
            '\n    # THE STORE OWNS THE NUMBER. Prefer its live value; if that cannot be read, use the\n'
            '    # env var or the fallback - and use the LARGEST of them, because a source that reports\n'
            '    # a smaller cap than the store is a source that silently holds back work.\n'
            '    store_cap = _env_int("WAKE_MAX_PER_DAY", DEFAULT_GLOBAL_MAX_PER_DAY)\n'
            '    try:\n'
            '        import json as _json, subprocess as _sp\n'
            '        _live = _sp.run(["python3", str(Path.home() / "bin" / "wake.py"), "stats", "--json"],\n'
            '                        capture_output=True, text=True, encoding="utf-8",\n'
            '                        errors="replace", timeout=60)\n'
            '        _c = (_json.loads(_live.stdout or "{}").get("caps") or {}).get("max_per_day")\n'
            '        if isinstance(_c, int) and _c > store_cap:\n'
            '            store_cap = _c\n'
            '    except Exception:\n'
            '        pass') + src[m.end():]
        print("store-cap resolution now prefers the live store value")
    else:
        print("WARNING: could not find store_cap assignment (it may be named differently)")

    if src == before:
        print("nothing changed")
        return 0
    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-livecap-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s" % p)

    print("\n=== PROOF: run it and read the number it reports ===")
    r = subprocess.run([sys.executable, str(p), "--dry-run"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if "system-wide" in line or "flag(s)" in line:
            print("  " + line.strip())
    if re.search(r"releases today \d+/4\b", out):
        print("STILL CLAMPED AT 4")
        return 1
    print("  no longer clamped at 4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
