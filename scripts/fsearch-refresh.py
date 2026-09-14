#!/usr/bin/env python3
"""refresh — keep the search indexes current, and say so when they are not.

WHY THIS EXISTS. An index is only worth having if it is current, and the failure
mode here is already the fleet's most expensive habit: something runs, fails
silently, and looks healthy (L160, L167, P51). `fsearch`/`chatindex` are
incremental, so a refresh is seconds, not minutes — but nothing was *running*
them, and nothing was checking that they had run.

WHAT IT DOES
  1. refreshes both indexes incrementally (cheap: unchanged files are skipped),
  2. records when it last succeeded, in a state file,
  3. is safe to run from cron: exits non-zero and writes a reason on failure,
     rather than dying quietly.

Authored to run on Windows (Task Scheduler) and Linux (cron) with the same file.
Per-host roots are declared below; a root that does not exist is skipped, so the
same file works on every machine in the fleet.

USAGE
  refresh.py                 # refresh everything, print a one-line summary
  refresh.py --check         # do not refresh; report staleness and exit 1 if stale
  refresh.py --roots A B     # override the roots
  refresh.py --json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
FSEARCH_DIR = os.path.join(HOME, ".fsearch")
STATE = os.path.join(FSEARCH_DIR, "refresh-state.json")

FSEARCH = os.path.join(FSEARCH_DIR, "fsearch.py")
CHATINDEX = os.path.join(FSEARCH_DIR, "chatindex.py")

# A refresh older than this means the automation is not working. Two missed
# hourly runs; the same "two missed windows" rule used for the archive alarm.
STALE_AFTER_MIN = 150

ROOTS_DEFAULT = [
    os.path.join(HOME, "Code"),
    os.path.join(HOME, "code"),
    os.path.join(HOME, "repos"),
    os.path.join(HOME, "personal-secretary-mvp"),
    os.path.join(HOME, "harness-config"),
    os.path.join(HOME, "ceo-kernel"),
]


def _python() -> str:
    return sys.executable or "python3"


def run(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    """Run a child and return (rc, tail of output). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        tail = (p.stdout or "")[-800:] + (p.stderr or "")[-400:]
        return p.returncode, tail.strip()
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


def load_state() -> dict:
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(FSEARCH_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, STATE)


def staleness(state: dict, now: float) -> float | None:
    """Minutes since the last successful refresh, or None if never."""
    last = state.get("last_success")
    if not last:
        return None
    try:
        t = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.fromtimestamp(now, dt.timezone.utc) - t).total_seconds() / 60.0


def do_check(as_json: bool) -> int:
    now = time.time()
    state = load_state()
    age = staleness(state, now)
    if age is None:
        msg = "SEARCH INDEX STALE: no successful refresh has ever been recorded"
        stale = True
    elif age > STALE_AFTER_MIN:
        msg = f"SEARCH INDEX STALE: last successful refresh {age:.0f} min ago (limit {STALE_AFTER_MIN})"
        stale = True
    else:
        msg = f"search index fresh: refreshed {age:.0f} min ago"
        stale = False
    if as_json:
        print(json.dumps({"ok": not stale, "age_min": age, "message": msg,
                          "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                         indent=2))
    else:
        print(msg)
        if stale:
            print("  -> run: python ~/.fsearch/refresh.py")
    return 1 if stale else 0


def do_refresh(roots: list[str], as_json: bool, verbose: bool) -> int:
    started = dt.datetime.now(dt.timezone.utc)
    state = load_state()
    results = {}

    real_roots = [r for r in roots if os.path.isdir(r)]
    skipped = [r for r in roots if not os.path.isdir(r)]

    if os.path.exists(FSEARCH) and real_roots:
        cmd = [_python(), FSEARCH, "index"]
        for r in real_roots:
            cmd += ["--root", r]
        if verbose:
            cmd.append("--verbose")
        rc, out = run(cmd)
        results["fsearch"] = {"rc": rc, "tail": out}
    else:
        results["fsearch"] = {"rc": 1, "tail": f"missing script or no roots (skipped {skipped})"}

    if os.path.exists(CHATINDEX):
        cmd = [_python(), CHATINDEX, "index"]
        if verbose:
            cmd.append("--verbose")
        rc, out = run(cmd, timeout=5400)
        results["chatindex"] = {"rc": rc, "tail": out}
    else:
        results["chatindex"] = {"rc": 1, "tail": "missing script"}

    ok = all(v["rc"] == 0 for v in results.values())
    finished = dt.datetime.now(dt.timezone.utc)
    state.update({
        "last_run": finished.isoformat(),
        "last_seconds": round((finished - started).total_seconds(), 1),
        "roots": real_roots,
        "skipped_roots": skipped,
        "results": results,
    })
    if ok:
        state["last_success"] = finished.isoformat()
        state.pop("last_failure_reason", None)
    else:
        state["last_failure"] = finished.isoformat()
        state["last_failure_reason"] = "; ".join(
            f"{k}: rc={v['rc']}" for k, v in results.items() if v["rc"] != 0)
    save_state(state)

    if as_json:
        print(json.dumps({"ok": ok, "seconds": state["last_seconds"],
                          "results": results}, indent=2))
    else:
        for name, v in results.items():
            mark = "ok  " if v["rc"] == 0 else "FAIL"
            print(f"  {mark} {name}: {v['tail'].splitlines()[-1] if v['tail'] else ''}")
        print(f"  {'refreshed' if ok else 'FAILED'} in {state['last_seconds']}s"
              + (f"; skipped missing roots {skipped}" if skipped else ""))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report staleness only")
    ap.add_argument("--roots", nargs="*", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.check:
        return do_check(a.json)
    return do_refresh(a.roots if a.roots else ROOTS_DEFAULT, a.json, a.verbose)


if __name__ == "__main__":
    sys.exit(main())
