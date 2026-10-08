#!/usr/bin/env python3
"""Make `wake.py claim` say WHY it claimed nothing, instead of answering `blocked_by: null`.

THE DEFECT, measured 2026-09-28 19:56Z. With 15 rows waiting, `wake.py claim` answered:

    {"ok": true, "row": null, "blocked_by": null}

which reads as "nothing is wrong and there is nothing to do". The truth was the opposite: there were
plenty of rows, and every one of them was gated. `_candidates()` skips a row when

    * `not_before` is in the future (a cooldown), or
    * the row is priority `low` during night-quiet, or
    * its SOURCE has already released 3 times in the last hour (`WAKE_MAX_PER_SOURCE_PER_HOUR`).

The store's own stats showed the gate (`source_cap: project-keepalive 3/3 in the last hour`), but the
claim path - the one a dispatcher and a woken session actually call - said null. A caller that cannot
tell "no work" from "work is gated" will either burn context investigating or, worse, conclude the
system is idle. That is the same failure shape this session has now recorded five times: A READING THAT
CANNOT DISTINGUISH TWO DIFFERENT STATES IS NOT A READING.

WHAT THIS DOES: when `_candidates` comes back empty and no whole-queue guard is in force, `cmd_claim`
now reports the reason per count - how many rows were refused by `not_before`, by night-quiet, and by
each source's hourly cap - e.g.

    {"ok": true, "row": null, "blocked_by": "row-gates",
     "gated": {"not_before": 0, "night_quiet": 0, "source_hourly_cap": 15,
               "by_source": {"project-keepalive": 8, "checkout-health": 7}, "new_rows": 15}}

`blocked_by` keeps its existing meaning for the WHOLE-QUEUE guards (daily-cap, cost-cap, paused), so
nothing that reads the old field breaks; the new field only fills the case that used to return null.

Usage: python3 fix-claim-explains.py [--apply]
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

GATED_FN = '''

def _candidates_gated(conn: sqlite3.Connection) -> dict:
    """Why `_candidates` returned nothing, counted per reason. Never raises.

    Exists because the claim path used to answer `blocked_by: null` when the queue was FULL of rows
    that were merely gated - a reading that cannot distinguish "no work" from "work is gated".
    """
    quiet = night_quiet_active()
    per_source = _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 3)
    when = now_dt()
    out = {"not_before": 0, "night_quiet": 0, "source_hourly_cap": 0,
           "by_source": {}, "new_rows": 0}
    try:
        rows = conn.execute(
            "SELECT * FROM wake WHERE state='new' AND attempts < max_attempts").fetchall()
        out["new_rows"] = len(rows)
        seen: dict[str, int] = {}
        for r in rows:
            nb = parse_dt(r["not_before"])
            if nb is not None and nb > when:
                out["not_before"] += 1
                continue
            if r["priority"] == "low" and quiet:
                out["night_quiet"] += 1
                continue
            if per_source > 0:
                src = r["source"] or "manual"
                if src not in seen:
                    seen[src] = source_releases_last_hour(conn, src)
                if seen[src] >= per_source:
                    out["source_hourly_cap"] += 1
                    out["by_source"][src] = out["by_source"].get(src, 0) + 1
                    continue
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "_candidates_gated" in src:
        print("already present")
        return 0

    # 1. add the helper right after _candidates
    m = re.search(r"\ndef _candidates\(conn: sqlite3\.Connection\):\n(?:.*\n)*?    return out\n", src)
    if not m:
        raise SystemExit("ERROR: could not find _candidates() - refusing to guess")
    src = src[:m.end()] + GATED_FN + src[m.end():]

    # 2. make cmd_claim report the per-row gates when nothing was claimable
    old = '''        cands = _candidates(conn)
        if not cands:
            low_only = conn.execute(
                "SELECT COUNT(*) FROM wake WHERE state='new' AND attempts < max_attempts"
            ).fetchone()[0]
            payload = {
                "ok": True,
                "row": None,
                "blocked_by": "night-quiet" if (low_only and night_quiet_active()) else None,
            }
            sys.stdout.write(json.dumps(payload) + "\\n")
            return 0'''
    new = '''        cands = _candidates(conn)
        if not cands:
            # NOTHING CLAIMABLE IS NOT THE SAME AS NOTHING GATED. Measured 2026-09-28 19:56Z: with 15
            # rows waiting the claim path answered `blocked_by: null`, which reads as "the queue is
            # empty" - while in truth every row was refused by the per-source hourly cap or a
            # not-before cooldown. A caller that cannot tell those two states apart either burns
            # context investigating or concludes the system is idle.
            gated = _candidates_gated(conn)
            payload = {
                "ok": True,
                "row": None,
                "blocked_by": "night-quiet" if (gated.get("new_rows") and night_quiet_active()
                                                and not gated.get("source_hourly_cap"))
                             else ("row-gates" if gated.get("new_rows") else None),
                "gated": gated,
            }
            sys.stdout.write(json.dumps(payload) + "\\n")
            return 0'''
    if old in src:
        src = src.replace(old, new, 1)
        print("patched the claim path")
    else:
        # tolerate a small shape difference by finding the row-is-None branch
        m2 = re.search(r'(\n(\s+)row = _pick\(conn\)\n\2if row is None:\n)(\2\s+return _print\(\{"ok": True, "row": None[^\n]*\n)', src)
        if not m2:
            raise SystemExit("ERROR: could not find the row-is-None branch in cmd_claim")
        indent = m2.group(2)
        replacement = (m2.group(1) +
                       indent + "    gated = _candidates_gated(conn)\n" +
                       indent + "    return _print({\"ok\": True, \"row\": None,\n" +
                       indent + "                   \"blocked_by\": blocked or (\"row-gates\" if gated.get(\"new_rows\") else None),\n" +
                       indent + "                   \"gated\": gated}, args)\n")
        src = src[:m2.start()] + replacement + src[m2.end():]
        print("patched the claim path (loose match)")

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-claimgated-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s" % p)

    print("\n=== PROOF: the claim path now explains itself ===")
    r = subprocess.run([sys.executable, str(p), "claim", "--by", "probe-explain", "--json"],
                       capture_output=True, text=True, timeout=120)
    print("  " + (r.stdout or r.stderr or "").strip()[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
