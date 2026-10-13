#!/usr/bin/env python3
"""finance-freshness -- a wake source: no finance source may go quietly stale.

WHY (finance fleet 2026-10-13, slug `money-clock`)
  A staleness number nobody computes is not a check. `finance_source_registry.py`
  names every source the owner's books depend on, each with its own
  `expected_max_age_days`, and on 2026-10-13 NOTHING turned that number into a
  verdict — while three sources sat 68-210 days behind and four automated pulls
  (paypal, amazon, ebay, stripe) were dead on the cloud authority. The Stripe one
  had been dead since the 2026-10-11 cutover and by 2026-10-13 Stripe held
  charges worth over a thousand dollars that the ledger did not have, and no job on
  this host said a word. This turns `finance-freshness` into a wake flag: only a
  process that KNOWS there is work may raise a flag, and money that is behind IS
  work.

WHAT IT ALARMS ON — two independent axes, because the measured failures were on both
  * verdict STALE / NEVER / COULD NOT ASK   — what we HOLD is too old, or cannot be
    judged at all (an unjudgeable source is never OK).
  * pull_state failed / unscheduled         — the thing that FEEDS the source is
    broken or was never put on a clock, even while the ledger row it produced is
    still inside its window. This is the case the age axis cannot see: on
    2026-10-13 `lpt_ebay` read OK at 4.9 days old while `ebay_sync` had failed on
    every run for two days.

CONTRACT (same as every source in this directory)
  quiet            -> nothing to file
  any other stdout -> a flag was filed (or deduped); run-wake-sources.sh logs the line
  exit 0 always    -> a source that breaks its caller is worse than no source.

Read-only apart from the single flag it files. It never runs a pull, never writes the
ledger, and never sends anything to a human.

Usage:
  finance-freshness.py [--dry-run] [--selftest] [--cli PATH] [--wake PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DEFAULT_CLI = "/opt/company/scripts/finance-freshness.py"
DEFAULT_PYTHON = "/opt/company/.venv/bin/python"
WAKE = HOME / "bin" / "wake.py"
SUBJECT = "finance-source-not-fresh"

ALARM_VERDICTS = {"STALE", "NEVER", "COULD NOT ASK"}
ALARM_PULL_STATES = {"failed", "unscheduled"}


def run_cli(cli: str, python: str, extra: list[str] | None = None) -> tuple[list[dict], str]:
    """Run the check; -> (parsed rows, error string). Never raises."""
    cmd = [python, cli, "--json"] + (extra or [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return [], "the check did not run: %s: %s" % (type(exc).__name__, exc)
    rows: list[dict] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            return [], "the check produced a line that is not JSON: %.200r" % line
        if isinstance(obj, dict):
            rows.append(obj)
    if not rows:
        return [], "the check produced no rows (rc=%s): %s" % (
            proc.returncode, (proc.stderr or "").strip()[:300])
    return rows, ""


def select(rows: list[dict]) -> list[dict]:
    """The sources this source exists to shout about, worst first."""
    alarms = []
    for row in rows:
        if row.get("archived"):
            continue
        verdict = str(row.get("verdict") or "")
        pull = str(row.get("pull_state") or "")
        if verdict in ALARM_VERDICTS or pull in ALARM_PULL_STATES:
            alarms.append(row)

    def rank(row: dict) -> tuple:
        verdict = str(row.get("verdict") or "")
        pull = str(row.get("pull_state") or "")
        return (
            0 if verdict == "STALE" else 1,
            0 if pull == "unscheduled" else (1 if pull == "failed" else 2),
            -(row.get("age_hours") or 0.0),
        )

    alarms.sort(key=rank)
    return alarms


def build_prompt(alarms: list[dict]) -> str:
    lines = [
        "Finance freshness: %d source(s) the owner's books depend on are not current."
        % len(alarms),
        "",
        "source_id | verdict | pull_state | age_hours | why",
    ]
    for row in alarms[:12]:
        age = row.get("age_hours")
        lines.append(
            "%s | %s | %s | %s | %s"
            % (
                row.get("source_id"),
                row.get("verdict"),
                row.get("pull_state"),
                "-" if age is None else "%.1f" % age,
                (row.get("note") or row.get("pull_detail") or "")[:160],
            )
        )
    lines += [
        "",
        "Reproduce with: /opt/company/.venv/bin/python "
        "/opt/company/scripts/finance-freshness.py --verbose",
        "and the one-row-per-source table: finance-freshness",
        "",
        "A STALE verdict means what we HOLD is older than the source's own"
        " expected_max_age_days. A failed/unscheduled pull_state means the thing that"
        " FEEDS the source is broken or was never put on a clock, which the age alone"
        " cannot see. Fix the pull against the DEPLOYED tree; do not edit the ledger"
        " by hand, and send nothing to anyone.",
    ]
    return "\n".join(lines)


def file_flag(wake: str, prompt: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["/usr/bin/python3", wake, "flag",
         "--subject", SUBJECT, "--prompt", prompt,
         "--kind", "finance-stale", "--source", "finance-freshness",
         "--priority", "high"],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def selftest(args) -> int:
    cases = [
        ("all-fresh", [
            {"source_id": "a", "verdict": "OK", "pull_state": "ok", "age_hours": 1.0},
            {"source_id": "b", "verdict": "ARCHIVED", "pull_state": "n/a", "age_hours": 999.0},
            {"source_id": "c", "verdict": "OK", "pull_state": "no-heartbeat"},
        ], 0),
        ("verdict-stale", [
            {"source_id": "a", "verdict": "OK", "pull_state": "ok"},
            {"source_id": "t", "verdict": "STALE", "pull_state": "no-heartbeat", "age_hours": 1635.0},
        ], 1),
        ("pull-failed-but-row-fresh", [
            {"source_id": "lpt_ebay", "verdict": "OK", "pull_state": "failed", "age_hours": 4.9},
        ], 1),
        ("pull-unscheduled", [
            {"source_id": "lpt_stripe", "verdict": "OK", "pull_state": "unscheduled", "age_hours": 1.0},
        ], 1),
        ("could-not-ask", [
            {"source_id": "x", "verdict": "COULD NOT ASK", "pull_state": "unknown"},
        ], 1),
    ]
    failures = 0
    for name, rows, expect in cases:
        got = len(select(rows))
        ok = got == expect
        failures += 0 if ok else 1
        print("  %-26s expect=%d got=%d %s" % (name, expect, got, "ok" if ok else "FAIL"))
    print("SELFTEST %s (%d failure(s))" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cli", default=DEFAULT_CLI)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--wake", default=str(WAKE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args)

    rows, error = run_cli(args.cli, args.python)
    if error:
        # An unreadable check is never "fresh" — it is a flag, with the reason.
        alarms = []
        prompt = (
            "Finance freshness CANNOT ANSWER. %s\n\nThe one command that answers"
            " 'is the money current?' is /opt/company/scripts/finance-freshness.py."
            " Fix it, then confirm it prints a table with a verdict column." % error
        )
        if args.dry_run:
            print("WOULD-FILE %s: %s" % (SUBJECT, error))
            return 0
        rc, out, err = file_flag(args.wake, prompt)
        print("finance-freshness flag-failed rc=%s %s" % (rc, (out.splitlines() or [err[:160]])[0]))
        return 0

    alarms = select(rows)
    if not alarms:
        print("quiet")
        return 0

    prompt = build_prompt(alarms)
    if args.dry_run:
        print("WOULD-FILE %s (%d source(s)):\n%s" % (SUBJECT, len(alarms), prompt))
        return 0

    rc, out, err = file_flag(args.wake, prompt)
    first = out.splitlines()[0] if out else ""
    print("finance-freshness %s alarm(s)=%d rc=%s %s"
          % ("flagged" if rc == 0 else "flag-failed", len(alarms), rc, first or err[:160]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a source that breaks its caller is worse than none
        print("finance-freshness source FAULT: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        raise SystemExit(0)
