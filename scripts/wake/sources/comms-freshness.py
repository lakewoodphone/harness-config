#!/usr/bin/env python3
"""FLAG SOURCE: the customer-comms pipeline is stale, or its check has died.

THE SIGNAL
----------
`~/.lpt-recon/production-comms-freshness.json`, written every 15 minutes by
~/bin/production-comms-freshness.py (crontab: 15,30,45,0). The file carries a
structured verdict: `ok` plus a `problems` list.

Two distinct findings, mutually exclusive by construction:

  A. VERDICT NOT OK. The verdict is current (checked_at within 45 min) and
     `ok` is false / `problems` is non-empty. The monitor has already decided
     something is wrong; nothing has ever acted on it, because it writes a JSON
     file and a log line and exits non-zero into a crontab nobody reads.
     What it is detecting is real and was expensive: on 2026-09-15 the website
     received no customer message for 11.5 hours and nothing noticed, because
     the only staleness signal measured the wrong clock. This check exists to
     catch that shape. The website's newest message falling >2 h behind the
     shop's own store means customers are talking to a shop that cannot see them.

  B. VERDICT DEAD. The state file has not been rewritten within 45 minutes, so
     either the check is not running or it is exiting 2 ("CANNOT MEASURE") before
     it writes anything -- which is the one failure its own file cannot report,
     because the failure IS that the file is not written. It also prints the
     reason to ~/.lpt-recon/production-freshness.log, which this source reads.

WHY THE THRESHOLDS ARE 45 MINUTES AND "ANY PROBLEM"
---------------------------------------------------
Healthy, measured on secratary 2026-09-18T03:00:01Z:

    checked_at            2026-09-18T03:00:01+00:00   (age 0.2 h)
    dialpad_calls         cursor age 0.35 h, behind_local -0.29 h
    dialpad_sms           cursor age 0.34 h, behind_local -1.07 h
    website               117729 rows, newest 0.35 h old
    problems              []          ok: true

The check's own staleness gate is `threshold_hours: 2.0`, and its cron interval
is 15 minutes, so a healthy `checked_at` is 0-15 minutes old. The threshold is 45
minutes because 45 is exactly THREE missed runs: one missed run can be a
transient (two runs overlapping a deploy, or the exit-2 refusal path), and three
consecutive misses cannot. The gate is 3x the measured cron interval, not a
number chosen for feel. For the verdict itself the threshold is zero problems --
`problems` is a list the check builds only when a measured clock is genuinely
behind, so "non-empty" IS the abnormal case and there is no rate to tune.

PRIORITY  high. Customer conversations not reaching the surfaces the shop reads.

SUBJECT  comms-freshness:<UTC day>        (finding A)
         comms-freshness-dead:<UTC day>   (finding B)
    Day-bucketed, so a pipeline that stays broken costs at most ONE session per
    day instead of one per 15-minute check. 96 checks a day must not be 96
    sessions -- that is the whole point of this workstream.

MUST NEVER
    - fire while the verdict is ok AND current (the measured healthy case)
    - fire finding A off a stale verdict (that is finding B, a different job)
    - run the monitor, or the pipeline, or repair anything itself

RUN
    python3 sources/comms-freshness.py [--dry-run]
    COMMS_FRESHNESS_STATE      default ~/.lpt-recon/production-comms-freshness.json
    COMMS_FRESHNESS_LOG        default ~/.lpt-recon/production-freshness.log
    COMMS_FRESHNESS_STALE_MIN  default 45
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "comms-freshness"
DEFAULT_STATE = "~/.lpt-recon/production-comms-freshness.json"
DEFAULT_LOG = "~/.lpt-recon/production-freshness.log"


def _state_path() -> Path:
    return Path(os.path.expanduser(
        os.environ.get("COMMS_FRESHNESS_STATE") or DEFAULT_STATE))


def _log_path() -> Path:
    return Path(os.path.expanduser(
        os.environ.get("COMMS_FRESHNESS_LOG") or DEFAULT_LOG))


def _stale_minutes() -> float:
    try:
        return float(os.environ.get("COMMS_FRESHNESS_STALE_MIN") or 45)
    except ValueError:
        return 45.0


def _log_tail(lines: int = 15) -> str:
    path = _log_path()
    if not path.is_file():
        return f"(no log at {path})"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(cannot read {path}: {exc})"
    kept = [ln for ln in text.splitlines() if ln.strip()][-lines:]
    return "\n".join(kept) if kept else "(log is empty)"


def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    path = _state_path()
    if not path.is_file():
        raise Unreadable(f"no verdict file at {path}")

    try:
        report = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        raise Unreadable(f"cannot parse {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise Unreadable(f"{path} is not a verdict object")

    checked = _flag.parse_dt(report.get("checked_at"))
    if checked is None:
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError as exc:
            raise Unreadable(f"no checked_at and cannot stat {path}: {exc}") from exc
        checked = mtime

    age_min = (now - checked).total_seconds() / 60.0
    day = now.strftime("%Y-%m-%d")

    if age_min > _stale_minutes():
        return [_dead_finding(day, path, checked, age_min, report, now)]

    problems = report.get("problems") or []
    ok = report.get("ok")
    if ok is True and not problems:
        return []
    if not isinstance(problems, list):
        problems = [str(problems)]
    return [_stale_finding(day, path, checked, age_min, report, problems, now)]


def _stale_finding(day, path, checked, age_min, report, problems, now) -> Finding:
    lines = [
        f"The customer-comms freshness check is reporting a problem as of "
        f"{checked.strftime('%Y-%m-%dT%H:%M:%SZ')} ({age_min:.0f} min ago). "
        f"Verdict file: {path}",
        "",
        f"ok = {report.get('ok')!r}",
        "problems:",
    ]
    for problem in problems:
        lines.append(f"  - {problem}")
    lines += [
        "",
        "Measured clocks from the same verdict:",
    ]
    for key in ("dialpad_calls", "dialpad_sms", "website", "local_newest_sms",
                "local_newest_call", "error"):
        if key in report:
            lines.append(f"  {key}: {json.dumps(report[key], default=str)}")
    lines += [
        "",
        "WHY THIS MATTERS",
        "This check was written after 2026-09-15, when the website received no",
        "customer message for 11.5 hours and nothing noticed, because the only",
        "staleness signal measured a clock that could not go wrong. A `problems`",
        "entry means a measured clock is genuinely behind its 2-hour gate: the",
        "website is not receiving what the shop already has, or a cursor is",
        "missing entirely. Customers are talking and the surfaces the shop reads",
        "are not seeing it.",
        "",
        "WHAT TO DO",
        "1. Reproduce by running the check yourself and reading the same file:",
        "     python3 ~/bin/production-comms-freshness.py; echo rc=$?",
        "   rc=1 is stale, rc=2 is 'could not measure' (a refusal, not health).",
        "2. Find which clock moved. The push that fills the website cursor is",
        "     /home/zabz/bin/website-comms-push-cron.sh  (crontab: 9,39 * * * *)",
        "   and the site-side ingest is /home/zabz/.fsearch/comms-refresh.py",
        "   (crontab: 7,37 * * * *). Read their logs before assuming which failed:",
        "     tail -50 /home/zabz/.lpt-recon/website-push.log",
        "     tail -20 /home/zabz/.fsearch/comms-cron.log",
        "3. Fix the cause and re-run the check until rc=0. Confirm the website's",
        "   newest message age drops back under 2 h.",
        "",
        "DO NOT: send anything to any customer; run a full backfill as a first",
        "move (the push is the thing that is behind -- find out why first); or",
        "widen the 2-hour threshold in the check to make it pass.",
        "",
        f"Recent log ({_log_path()}):",
        _log_tail(),
        "",
        "Report: which clock was behind, the root cause, the exact command output",
        "showing rc=0 and the website's newest-message age back under 2 h.",
    ]
    return Finding(
        subject=f"comms-freshness:{day}",
        prompt="\n".join(lines),
        context=f"{SOURCE}: verdict NOT ok ({len(problems)} problem(s)) at "
                f"{checked.isoformat(timespec='seconds')}",
        priority="high",
        kind="bug",
        cooldown_seconds=int(os.environ.get("COMMS_FRESHNESS_COOLDOWN_SEC") or 86400),
    )


def _dead_finding(day, path, checked, age_min, report, now) -> Finding:
    lines = [
        f"The customer-comms freshness check has not written a verdict in "
        f"{age_min:.0f} minutes. Its last verdict is stamped "
        f"{checked.strftime('%Y-%m-%dT%H:%M:%SZ')} ({path}), and it is scheduled "
        f"every 15 minutes from crontab (15,30,45,0 * * * *).",
        "",
        "Three consecutive runs have produced no verdict. The check has a second",
        "failure mode that its own file cannot report: it exits 2 ('CANNOT",
        "MEASURE') and returns BEFORE writing the file, so a check that can no",
        "longer measure anything looks exactly like a check that is not running.",
        "Either way a real 2026-09-15-shaped silence would now go unnoticed.",
        "",
        f"Last verdict content: {json.dumps(report, default=str)[:600]}",
        "",
        "WHAT TO DO",
        "1. Run it by hand and read what it says:",
        "     python3 ~/bin/production-comms-freshness.py; echo rc=$?",
        "   rc=2 prints the reason on stdout. rc=0/1 means it RUNS fine, so the",
        "   problem is the scheduling -- check the crontab line exists and check",
        "   the log for permission or path errors.",
        "2. Read the log tail below for the last thing it said.",
        "3. Fix it, then confirm a fresh `checked_at` appears in the verdict file",
        "   within one cron interval.",
        "",
        "DO NOT: write the verdict file by hand; delete the log; or widen the",
        "staleness gate to make this source quiet.",
        "",
        f"Recent log ({_log_path()}):",
        _log_tail(),
        "",
        "Report: why no verdict was written, the fix, and the fresh checked_at that",
        "proves it.",
    ]
    return Finding(
        subject=f"comms-freshness-dead:{day}",
        prompt="\n".join(lines),
        context=f"{SOURCE}: no verdict for {age_min:.0f} min (last "
                f"{checked.isoformat(timespec='seconds')})",
        priority="high",
        kind="bug",
        cooldown_seconds=int(os.environ.get("COMMS_FRESHNESS_COOLDOWN_SEC") or 86400),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
