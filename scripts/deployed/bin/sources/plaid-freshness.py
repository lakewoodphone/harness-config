#!/usr/bin/env python3
"""plaid-freshness -- a wake source: the nightly money pull must not go quiet unnoticed.

WHY (journal pain P2926 part 1; housekeeping item 231)
  Measured 2026-09-30: 6 of the last 8 nightly Plaid runs failed and NOTHING alerted.
  plaid-freshness-guard.py already judges ~/.plaid-sync-status.json (FRESH / STALE /
  FAILED / UNVERIFIABLE) but nothing invoked it, so a dead pull stayed silent. This
  turns the guard's verdict into a wake flag: only a process that KNOWS there is work
  may raise a flag, and a money pull that has been dead past its ceiling is work.

CONTRACT (same as every source in this directory)
  quiet            -> nothing to file
  any other stdout -> a flag was filed (or deduped); run-wake-sources.sh logs the line
  exit 0 always    -> a source that breaks its caller is worse than no source.

Read-only apart from the single flag it files. It never runs the pull and never sends
anything to a human.
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
GUARD = HOME / "bin" / "plaid-freshness-guard.py"
WAKE = HOME / "bin" / "wake.py"
SUBJECT = "plaid-pull-not-fresh"


def run_guard(guard, status_file=None, now=None, ceiling=None):
    cmd = ["/usr/bin/python3", str(guard), "--json"]
    if status_file:
        cmd += ["--status-file", status_file]
    if now:
        cmd += ["--now", now]
    if ceiling:
        cmd += ["--max-age-hours", str(ceiling)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "UNVERIFIABLE",
                "reason": "guard did not run: %s: %s" % (type(exc).__name__, exc)}
    try:
        return json.loads(proc.stdout)
    except Exception:  # noqa: BLE001
        return {"verdict": "UNVERIFIABLE",
                "reason": "guard produced no parsable JSON (rc=%s): %s"
                          % (proc.returncode, (proc.stderr or "").strip()[:200])}


def build_prompt(verdict, reason):
    return ("The nightly Plaid money pull is not fresh: %s - %s. (journal pain P2926 "
            "part 1). Read ~/.plaid-sync-status.json and the nightly-plaid-sync log, fix "
            "the pull against the DEPLOYED tree, and confirm the next run writes ok=true. "
            "Reproduce with: python3 %s --json "
            "(36h ceiling)." % (verdict, reason, GUARD))


def file_flag(wake, prompt):
    proc = subprocess.run(
        ["/usr/bin/python3", str(wake), "flag",
         "--subject", SUBJECT, "--prompt", prompt,
         "--kind", "plaid-stale", "--source", "plaid-freshness", "--priority", "high"],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def selftest(args):
    now = "2026-10-09T16:00:00+00:00"
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        def write(name, obj):
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(obj, handle)
            return path
        cases.append(("fresh", write("fresh.json",
                     {"at": "2026-10-09T12:00:00+00:00", "ok": True}), "quiet"))
        cases.append(("stale", write("stale.json",
                     {"at": "2026-10-08T00:00:00+00:00", "ok": True}), "WOULD-FILE"))
        cases.append(("failed", write("failed.json",
                     {"at": "2026-10-09T12:00:00+00:00", "ok": False,
                      "failed_steps": ["plaid"]}), "WOULD-FILE"))
        cases.append(("absent", os.path.join(tmp, "nope.json"), "WOULD-FILE"))
        failures = 0
        for name, path, expect in cases:
            verdict = run_guard(args.guard, path, now, None)
            got = "quiet" if verdict.get("verdict") == "FRESH" else "WOULD-FILE"
            ok = got == expect
            failures += 0 if ok else 1
            print("  %-7s expect=%-11s got=%-11s verdict=%-13s %s"
                  % (name, expect, got, verdict.get("verdict"), "ok" if ok else "FAIL"))
    print("SELFTEST %s (%d failure(s))" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status-file")
    parser.add_argument("--now")
    parser.add_argument("--max-age-hours", type=float)
    parser.add_argument("--guard", default=str(GUARD))
    parser.add_argument("--wake", default=str(WAKE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args)

    verdict = run_guard(args.guard, args.status_file, args.now, args.max_age_hours)
    if verdict.get("verdict") == "FRESH":
        print("quiet")
        return 0

    prompt = build_prompt(verdict.get("verdict"), verdict.get("reason"))
    if args.dry_run:
        print("WOULD-FILE %s: %s" % (SUBJECT, verdict.get("reason")))
        return 0

    rc, out, err = file_flag(args.wake, prompt)
    first = out.splitlines()[0] if out else ""
    print("plaid-freshness %s verdict=%s rc=%s %s"
          % ("flagged" if rc == 0 else "flag-failed",
             verdict.get("verdict"), rc, (first or err[:160])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
