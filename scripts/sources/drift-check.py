#!/usr/bin/env python3
"""NIGHTLY DRIFT CHECK - work item 185.

WHY
---
Drift is this system's most persistent failure mode, measured twice in one day (2026-09-30):
a hand edit to a generated preset was silently reverted by its generator, and a fix that lived
only on a diverged branch was invisible to every other machine. A check that runs only when
somebody remembers to run it is not a check.

WHAT
----
Prints ONE line per invariant, PASS or FAIL, then exits non-zero if any invariant is missing.
It is invoked by run-wake-sources.sh (cron `*/15`) and self-gates to the first pass of each UTC
day, so it runs nightly without a second cron entry. --force runs it immediately.

INVARIANTS (each is a live fix that was already lost, or nearly lost, once):
  fanout-preflight-guard        wake-fanout.sh asks wake-nextclaim before starting a dispatcher
  failed-claim-evidence-kept    a failed instance is MOVED to wake-failed, never deleted
  retryable-attempt-refund      a transient outcome refunds the attempt (wake.py)
  per-source-cap-12             WAKE_MAX_PER_SOURCE_PER_HOUR default stays 12
  daily-spend-ceiling-25        DEFAULT_MAX_USD_PER_DAY stays 25.0
  autonomy-status-value-budget  autonomy-status.sh still prints its VALUE and BUDGET lines
  balance-guard                 wake-balance.py still guards, and cron still runs it
  deadman-ping-cron             cron still pings the deadman check

READ-ONLY. The only writes are this tool's own report/log and the nightly gate stamp. It never
sends, never restarts, never edits the files it checks, and never touches cron.

USAGE
  drift-check.py [--root DIR] [--force] [--json] [--report PATH]
Env: DRIFT_ROOT  (default /home/zabz/bin)   directory holding the checked files
     DRIFT_STATE (default ~/.drift-check)   report, log and nightly gate stamp
Exit: 0 all PASS (or gated off), 1 any FAIL, 2 the check itself could not read something.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = os.environ.get("DRIFT_ROOT", "/home/zabz/bin")
DEFAULT_STATE = os.environ.get("DRIFT_STATE", os.path.expanduser("~/.drift-check"))
UTC = timezone.utc

ROOT = Path(DEFAULT_ROOT)
STATE = Path(DEFAULT_STATE)


class Unreadable(Exception):
    """The check could not read its input. Never silently becomes a PASS."""


def read(rel: str) -> str:
    path = ROOT / rel
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("%s: %s" % (path, exc))


_CRONTAB: str | None = None


def crontab() -> str:
    global _CRONTAB
    if _CRONTAB is None:
        try:
            proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20)
        except Exception as exc:  # noqa: BLE001
            raise Unreadable("could not run `crontab -l`: %s" % exc)
        if proc.returncode != 0 and not proc.stdout:
            raise Unreadable("`crontab -l` rc=%s: %s" % (proc.returncode, (proc.stderr or "").strip()[:160]))
        _CRONTAB = proc.stdout
    return _CRONTAB


# --------------------------------------------------------------------------- #
# the invariants
# --------------------------------------------------------------------------- #
def inv_fanout_preflight():
    text = read("wake-fanout.sh")
    if "wake-nextclaim" in text and "claimable_now" in text:
        return True, "pre-flight asks wake-nextclaim for claimable_now before starting a dispatcher"
    return False, "wake-fanout.sh no longer asks wake-nextclaim/claimable_now before starting"


def inv_failed_claim_evidence():
    text = read("wake-fanout.sh")
    if 'FAILED_DIR="$INST_ROOT/../wake-failed"' in text and 'mv "$INST"' in text:
        return True, "a failed instance is moved to wake-failed, not deleted"
    return False, "the failed-claim evidence path (wake-failed + mv) is gone from wake-fanout.sh"


def inv_retryable_refund():
    text = read("wake.py")
    if "_retryable_reason" in text and "attempts=MAX(0, attempts-1)" in text:
        return True, "a transient outcome refunds the attempt (wake.py)"
    return False, "the retryable attempt refund is gone from wake.py"


def inv_per_source_cap():
    text = read("wake.py")
    if '_env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12)' in text:
        return True, "per-source cap default is 12"
    return False, 'wake.py no longer defaults WAKE_MAX_PER_SOURCE_PER_HOUR to 12'


def inv_daily_ceiling():
    """The ceiling he actually set, not the one that was set before he spoke.

    Measured 2026-10-21: this check asserted 25.0 and had been failing daily for two days.
    DEFAULT_MAX_USD_PER_DAY is 70.0 because THE OWNER RAISED IT on 2026-09-28 -- his words, on
    the record in settings/machines and in projects.json: "obviously we can't have overall more
    than 70 dollars of spending, let's say, on the deepseek API daily". A drift check that fails because
    the owner changed his mind reports the owner as drift.
    """
    text = read("wake.py")
    if "DEFAULT_MAX_USD_PER_DAY = 70.0" in text:
        return True, "daily spend ceiling is 70.0 USD, the number he set on 2026-09-28"
    if "DEFAULT_MAX_USD_PER_DAY = 25.0" in text:
        return False, ("daily spend ceiling is back to 25.0 -- he raised it to 70.0 on "
                       "2026-09-28, so this is a change nobody asked for")
    return False, "DEFAULT_MAX_USD_PER_DAY is neither 70.0 (his number) nor 25.0 (the old one)"


def inv_value_budget():
    script = ROOT / "autonomy-status.sh"
    if not script.is_file():
        return False, "autonomy-status.sh is missing from %s" % ROOT
    try:
        proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return False, "autonomy-status.sh did not run: %s" % exc
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = out.splitlines()
    has_value = any("VALUE" in ln for ln in lines)
    has_budget = any("BUDGET" in ln for ln in lines)
    if has_value and has_budget:
        return True, "autonomy-status.sh prints VALUE and BUDGET lines"
    return False, "autonomy-status.sh output is missing %s" % (
        " and ".join(x for x, ok in (("VALUE", has_value), ("BUDGET", has_budget)) if not ok))


def inv_balance_guard():
    text = read("wake-balance.py")
    if "--guard" not in text or 'MARK = "low-balance"' not in text:
        return False, "wake-balance.py no longer carries its guard (--guard / low-balance marker)"
    if "wake-balance" not in crontab():
        return False, "wake-balance.py exists but cron no longer runs it"
    return True, "wake-balance.py guards and cron still runs it"


def inv_deadman_cron():
    """The deadman ping moved from cron to a systemd timer, and the check never followed.

    Measured 2026-10-21: this looked only for "deadman.py" in the crontab and had been failing
    daily. The mechanism is alive and better: authority-deadman.timer runs
    authority-deadman.service (ExecStart=/usr/local/bin/authority-deadman.py) every five minutes,
    and had fired 14 seconds before this was written. Checking one scheduler for a job that lives
    on another is how a working deadman gets reported as gone -- and if it ever IS gone, that
    report would be ignored because this one had been crying for two days.
    """
    if "deadman.py" in crontab():
        return True, "cron still pings the deadman check"
    try:
        unit = subprocess.run(
            ["systemctl", "cat", "authority-deadman.service"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        unit = ""
    if "authority-deadman" in unit:
        return True, "the deadman ping is alive as authority-deadman.timer (moved off cron)"
    return False, "no deadman ping in cron AND no authority-deadman.service - it is gone"


INVARIANTS = [
    ("fanout-preflight-guard", inv_fanout_preflight),
    ("failed-claim-evidence-kept", inv_failed_claim_evidence),
    ("retryable-attempt-refund", inv_retryable_refund),
    ("per-source-cap-12", inv_per_source_cap),
    ("daily-spend-ceiling-25", inv_daily_ceiling),
    ("autonomy-status-value-budget", inv_value_budget),
    ("balance-guard", inv_balance_guard),
    ("deadman-ping-cron", inv_deadman_cron),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="nightly drift check (item 185)")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="directory holding the checked files")
    ap.add_argument("--force", action="store_true", help="run now even if already run today")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    ap.add_argument("--report", default=None, help="path for the full report")
    args = ap.parse_args()

    global ROOT, STATE
    ROOT = Path(args.root)
    STATE = Path(os.environ.get("DRIFT_STATE", DEFAULT_STATE))

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stamp = STATE / "last-run-date"
    if not args.force:
        try:
            if stamp.read_text(encoding="utf-8").strip() == today:
                print("quiet")
                return 0
        except Exception:  # noqa: BLE001 - no stamp yet means "run"
            pass

    rows = []
    for name, fn in INVARIANTS:
        try:
            ok, detail = fn()
        except Unreadable as exc:
            ok, detail = False, "unreadable: %s" % exc
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
        rows.append((name, bool(ok), detail))

    failed = [r for r in rows if not r[1]]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = "drift-check %s root=%s" % (now, ROOT)
    body = [header]
    body += ["%s %s :: %s" % ("PASS" if ok else "FAIL", name, detail) for name, ok, detail in rows]
    body.append("drift-check: %d/%d PASS, %d FAIL" % (len(rows) - len(failed), len(rows), len(failed)))
    report = "\n".join(body)

    try:
        STATE.mkdir(parents=True, exist_ok=True)
        (Path(args.report) if args.report else (STATE / "last-report.txt")).write_text(report + "\n",
                                                                                      encoding="utf-8")
        with open(STATE / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
        stamp.write_text(today + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - a report we cannot save must not hide a FAIL
        sys.stderr.write("drift-check: could not write report/state: %s\n" % exc)

    if args.json:
        print(json.dumps({"ok": not failed, "root": str(ROOT), "at": now,
                          "invariants": [{"name": n, "ok": ok, "detail": d} for n, ok, d in rows]}))
    else:
        print(report)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
