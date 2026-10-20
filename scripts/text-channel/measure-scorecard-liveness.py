#!/usr/bin/env python3
"""Before/after on the SAME live rows: does the scorecard target a retired family?

This is the repeatable measurement for the 2026-10-20 liveness change (ledger item
733). It loads the scorecard as it was at `--before` from git, loads the current
one, judges the same `--days` of `sms_log`, and prints which family each would send
a wake session after.

Read-only: every store is opened `mode=ro`; the only write is a temporary file that
holds the old script. It never sends a text and never files a flag.

RUN
    cd /root/code/harness-config
    python3 scripts/text-channel/measure-scorecard-liveness.py --before 2dde8d07^
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REL = "scripts/text-channel/owner-text-scorecard.py"
LIVE_FAMILY_H = 48.0


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def age(hours):
    if hours is None:
        return "?"
    return "%.1fd" % (hours / 24.0) if hours >= 48 else "%.1fh" % hours


def newest_age_h(judged, family, reference):
    times = []
    for row in judged:
        if row.get("family") != family:
            continue
        try:
            text = str(row.get("at") or "").replace("Z", "+00:00")
            when = datetime.fromisoformat(text)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        times.append(when)
    if not times:
        return None
    return (reference - max(times)).total_seconds() / 3600.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", default="2dde8d07^",
                    help="git revision whose scorecard is the BEFORE (default: the commit before the fix)")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--reply-window", type=float, default=6.0)
    args = ap.parse_args(argv)

    got = subprocess.run(["git", "-C", str(REPO), "show", "%s:%s" % (args.before, REL)],
                         capture_output=True, text=True)
    if got.returncode != 0:
        print("cannot read %s:%s -- %s" % (args.before, REL,
                                           (got.stderr or "").strip()[:300]), file=sys.stderr)
        return 2

    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    try:
        handle.write(got.stdout)
        handle.close()
        old = load(handle.name, "scorecard_before_liveness")
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    new = load(HERE / "owner-text-scorecard.py", "scorecard_after_liveness")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    rows, why = new.load_sms(since)
    if rows is None:
        print("CANNOT READ: %s" % why, file=sys.stderr)
        return 2

    old_result = old.judge(rows, since, now, args.reply_window)
    old_summary = old.summarise(old_result)
    new_result = new.judge(rows, since, now, args.reply_window)
    new_summary = new.summarise(new_result, args.reply_window)

    old_worst = old_summary["worst_families"][0] if old_summary["worst_families"] else None
    live = new_summary.get("worst_live_family")
    hist = new_summary.get("historical_worst_family")

    before_age = (newest_age_h(old_result["judged"], old_worst["family"], now)
                  if old_worst else None)
    before_retired = int(before_age is not None and
                         before_age > max(args.reply_window, LIVE_FAMILY_H))

    print("BEFORE  worst named: %s (%d dead of %d, newest %s old) -- no liveness"
          % (old_worst["family"] if old_worst else "(none)",
             old_worst["dead"] if old_worst else 0,
             old_worst["n"] if old_worst else 0,
             age(before_age)))
    print("AFTER   worst LIVE family: %s (%d dead of %d, newest %s old)"
          % (live["family"] if live else "(none)",
             live["dead"] if live else 0,
             live["n"] if live else 0,
             age(live.get("newest_age_h")) if live else "-"))
    print("AFTER   historical family: %s (%d dead of %d, newest %s old, drops below 2 rows %s)"
          % (hist["family"] if hist else "(none)",
             hist["dead"] if hist else 0,
             hist["n"] if hist else 0,
             age(hist.get("newest_age_h")) if hist else "-",
             (hist.get("retires_below_two_at") or "?")[:10] if hist else "-"))
    print("COUNT   wake target is a retired family: %d -> 0" % before_retired)
    print("COUNT   live dead texts the old reader could not distinguish: %d"
          % new_summary.get("live_dead", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
