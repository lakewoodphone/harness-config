#!/usr/bin/env python3
"""Define DEFAULT_MAX_USD_PER_DAY for real.

MY OWN BUG, caught by the proof step of the patch that created it: patch-cap-to-spend.py replaced
`_env_float("WAKE_MAX_USD_PER_DAY", 3.0)` with `... DEFAULT_MAX_USD_PER_DAY)` but its second edit -
the one that was supposed to DEFINE that constant - matched nothing and silently did nothing (it
looked for the literal text of a replacement that had already been rewritten). The result was a
file that imported cleanly and then raised
    NameError: name 'DEFAULT_MAX_USD_PER_DAY' is not defined
the first time anything read the caps. Two lessons, both already in the journal's idiom: a patcher
must verify each edit landed, and a patch to a running guard must be exercised, not merely written.

Usage: python3 fix-usd-constant.py --apply
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
BLOCK = '''DEFAULT_MAX_PER_DAY = 500

# THE ACTUAL LIMIT: the owner's 70 USD/day of DeepSeek API spend.
# He set the ceiling himself on 2026-09-28: "obviously we can't have overall more than $70 of
# spending, let's say, on the deepseek API daily. But it's not like how many times."
# At the MEASURED 0.068 USD per autonomous shift (38 priced releases, 2.5825 USD total in
# ~/.sms-inbox/wake-cost.jsonl) that is roughly 1,029 shifts/day, so this binds only when
# something is pathological - which is precisely what it is for. Volume is not the limit;
# waste is.
DEFAULT_MAX_USD_PER_DAY = 70.0'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")

    if re.search(r"^DEFAULT_MAX_USD_PER_DAY\s*=", src, re.M):
        src = re.sub(r"^DEFAULT_MAX_USD_PER_DAY\s*=\s*[\d.]+", "DEFAULT_MAX_USD_PER_DAY = 70.0",
                     src, count=1, flags=re.M)
        print("constant existed; value pinned to 70.0")
    else:
        if not re.search(r"^DEFAULT_MAX_PER_DAY\s*=\s*\d+", src, re.M):
            raise SystemExit("ERROR: DEFAULT_MAX_PER_DAY not found - refusing to guess")
        # replace the constant line AND the single explanatory line above it, if present
        src = re.sub(r"(?:^#.*\n)*?^DEFAULT_MAX_PER_DAY\s*=\s*\d+", BLOCK, src, count=1, flags=re.M)

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0

    # EVERY EDIT IS VERIFIED. This is the check the previous patcher lacked, and its absence
    # cost a working guard: the file must define BOTH constants and must import cleanly.
    if not re.search(r"^DEFAULT_MAX_USD_PER_DAY\s*=\s*70\.0", src, re.M):
        raise SystemExit("ERROR: the USD constant did not land - aborting before writing")
    if not re.search(r"^DEFAULT_MAX_PER_DAY\s*=\s*500", src, re.M):
        raise SystemExit("ERROR: the count backstop did not land - aborting before writing")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-usdconst-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== PROOF: import it, read both constants, and ask the guard ===")
    probe = (
        "import importlib.util,sys,json;"
        "spec=importlib.util.spec_from_file_location('w', %r);"
        "w=importlib.util.module_from_spec(spec); sys.modules['w']=w; spec.loader.exec_module(w);"
        "print('count backstop  ', w.DEFAULT_MAX_PER_DAY);"
        "print('spend ceiling   ', w.DEFAULT_MAX_USD_PER_DAY);"
        "c=w.connect();"
        "print('release_block() ', repr(w.release_block(c)));"
        "print('caps_now()      ', json.dumps({k: w.caps_now()[k] for k in ('max_per_day','max_usd_per_day')}))"
    ) % str(p)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or (r.stderr or "").strip()[-800:])
    if r.returncode != 0:
        print("\nFAILED - rolling back")
        shutil.copy2(bak, p)
        return 1
    r2 = subprocess.run([sys.executable, str(p), "stats", "--json"], capture_output=True, text=True, timeout=120)
    m = re.search(r'"max_usd_per_day":\s*([\d.]+)', r2.stdout or "")
    print("stats reports      max_usd_per_day = %s" % (m.group(1) if m else "NOT FOUND"))
    return 0 if m and m.group(1).startswith("70") else 1


if __name__ == "__main__":
    sys.exit(main())
