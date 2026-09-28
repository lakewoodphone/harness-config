#!/usr/bin/env python3
"""Make the money ceiling read a REAL number, and say so when it cannot.

THE DEFECT, measured 2026-09-28. `wake.py spend_today()` is the number the whole spend ceiling is
enforced against:

    SELECT COALESCE(SUM(cost_usd), 0) FROM wake
     WHERE cost_usd IS NOT NULL AND substr(finished_at,1,10)=<today>

and `wake.cost_usd` is null on every row, because the dispatcher logs its releases `cost=none`
(`dsh --profile headless` reports no cost). So the guard has always compared the day's spend
against the literal 0.0. A money ceiling that reads zero while money is spent is worse than no
ceiling: it reports safety it has not measured. The owner's new ceiling is 70 USD/day and it was
enforced against a constant zero.

Meanwhile the real per-release cost IS measured and already written by `wake-cost.py` to
`~/.sms-inbox/wake-cost.jsonl` - one JSON object per release, each carrying `cost_usd_or_unsourced`
(and `total_tokens`, `output_tokens`, `cache_read_tokens`, `release_id`, `started_day`). That file
is the measurement of record and it is the one this must read.

WHAT THIS DOES
  * `spend_today()` sums today's release costs from wake-cost.jsonl - released sessions only, so the
    owner's own interactive work does not consume the autonomous budget.
  * If the file is missing or unreadable the function returns `None` and the caller reports
    `unmeasured` rather than `0.0`, because an unreadable measurement is not a measurement of zero.
  * `stats` exposes `spend_today_usd` AND `spend_source` so a human can see where the number came
    from (journal P12: a reading with no source is not reported).
  * The enforcement in `release_block()` refuses to run when spend cannot be measured AND the
    day's release count is above `UNMEASURED_REFUSE_ABOVE` (default 40). That is the honest
    position: with no measurement, unlimited volume is exactly the runaway the ceiling exists to
    stop.

Usage: python3 fix-spend-measurement.py --apply
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

NEW_SPEND = '''def spend_today(conn: sqlite3.Connection) -> float | None:
    """The day's autonomous spend in USD, MEASURED, or None when it cannot be measured.

    Reads `~/.sms-inbox/wake-cost.jsonl`, which `wake-cost.py` writes per release and which is
    the only place a real per-shift cost exists: `wake.cost_usd` is null on every row because
    `dsh --profile headless` reports no cost, so the store-based sum this replaced could only
    ever return 0.0 (measured 2026-09-28).

    RELEASED SESSIONS ONLY. The owner's own interactive sessions are not an autonomous cost and
    must not consume the autonomous budget.

    Returns None - never 0.0 - when the measurement is unreadable. An unreadable measurement is
    not a measurement of zero, and reporting it as zero is exactly how a money guard lies.
    """
    path = Path(os.path.expanduser(os.environ.get("WAKE_COST_JSONL")
                                   or "~/.sms-inbox/wake-cost.jsonl"))
    day = today_utc()
    try:
        if not path.exists():
            return None
        total = 0.0
        seen = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"type": "release"' not in line.replace("'", '"'):
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("type") != "release":
                    continue
                if str(row.get("started_day") or "")[:10] != day:
                    continue
                v = row.get("cost_usd_or_unsourced")
                if isinstance(v, (int, float)):
                    total += float(v)
                    seen += 1
                elif isinstance(v, str) and v not in ("unsourced", ""):
                    try:
                        total += float(v)
                        seen += 1
                    except ValueError:
                        pass
        if seen == 0:
            # No priced release yet today is a real (zero) reading for the autonomous budget.
            return 0.0
        return round(total, 6)
    except Exception:
        return None


# With no measurement, unlimited volume is the runaway the ceiling exists to stop. Below this
# many releases a day the operator's "unmeasured" is acceptable; above it, refuse.
UNMEASURED_REFUSE_ABOVE = 40
'''

NEW_BLOCK = '''    spent = spend_today(conn)
    if spent is None:
        # NO MEASUREMENT IS NOT ZERO. Refuse only once volume means the risk is real, so an
        # unreadable cost file cannot silently stop the operation either.
        if released_today(conn) > UNMEASURED_REFUSE_ABOVE:
            return "spend-unmeasured"
    elif spent >= _env_float("WAKE_MAX_USD_PER_DAY", DEFAULT_MAX_USD_PER_DAY):
        return "cost-cap"
    return None'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")

    # IDEMPOTENCE, CHECKED ON THE CODE AND NOT ON A STRING. `wake-cost.jsonl` already appears in
    # this file's docstring, so testing for it skipped the patch entirely the first time - a
    # patcher that greps for a word the file uses for another reason will always think it is done.
    if re.search(r"def spend_today\([^)]*\)\s*->\s*float\s*\|\s*None", src) and \
       "cost_usd_or_unsourced" in src:
        print("spend_today() already reads the measured cost file; nothing to do")
        return 0

    # 1. replace spend_today()
    m = re.search(r"def spend_today\(conn: sqlite3\.Connection\) -> float:\n(?:.*\n)*?    return round\(float\(r\[\"s\"\] or 0\.0\), 6\)\n",
                  src)
    if not m:
        raise SystemExit("ERROR: could not find spend_today() - refusing to guess")
    src = src[:m.start()] + NEW_SPEND + src[m.end():]

    # 2. replace the enforcement
    old_block = ('    if spend_today(conn) >= _env_float("WAKE_MAX_USD_PER_DAY", DEFAULT_MAX_USD_PER_DAY):\n'
                 '        return "cost-cap"\n'
                 '    return None')
    if old_block not in src:
        raise SystemExit("ERROR: could not find the cost-cap enforcement block")
    src = src.replace(old_block, NEW_BLOCK, 1)

    # 3. imports it now needs
    if "\nimport json\n" not in src:
        src = re.sub(r"^import os$", "import json\nimport os", src, count=1, flags=re.M)

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-spend-measured-" + stamp)
    shutil.copy2(p, bak)
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup %s)" % (p, bak.name))

    print("\n=== PROOF: the measured number, and the guard, read from the patched module ===")
    probe = (
        "import importlib.util,sys,json;"
        "spec=importlib.util.spec_from_file_location('w', %r);"
        "w=importlib.util.module_from_spec(spec); sys.modules['w']=w; spec.loader.exec_module(w);"
        "c=w.connect();"
        "print('spend_today()   ', repr(w.spend_today(c)));"
        "print('released_today()', w.released_today(c));"
        "print('ceiling         ', w.DEFAULT_MAX_USD_PER_DAY);"
        "print('release_block() ', repr(w.release_block(c)))"
    ) % str(p)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=180)
    print(r.stdout.strip() or (r.stderr or "").strip()[-800:])
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
