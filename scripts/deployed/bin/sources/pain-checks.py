#!/usr/bin/env python3
"""FLAG SOURCE: open pain entries that a check proves are fixed, and checks that stopped working.

THE SIGNAL
----------
`~/bin/pain-check.py --json --write-status` runs the executable check suite over the open pain
entries and writes `~/.pain-check/status.json`.

WHY THIS SOURCE EXISTS
----------------------
The audit of 2026-09-30 verified 297 open pain entries against the live systems and found **52 that
were already fixed**. They were open because nothing closes an entry when its cause is removed
(journal P4, P58). The suite is the mechanism; this source is the thing that makes somebody act on
it. Without a reader, a perfect check suite is another artefact nobody opens.

TWO SIGNALS, and they are different in kind:
  1. FIXED AND STILL OPEN. There is evidence in hand and the record disagrees with it. Left alone
     this is the debt that grew to 52 entries in one afternoon. Filed as a repair item whose prompt
     says exactly how to close them (`pain-check.py --close`) and what to check first.
  2. THE SUITE ITSELF STOPPED. A status older than the ceiling raises Unreadable rather than a
     finding, because a suite that has not run has not found anything -- and "we ran the checks and
     all is well" must never be what a stale file means (journal P167's lesson, P52's alarm fatigue).

PRIORITY  normal. This is book-keeping about the record, not an outage.

SUBJECTS  pain-checks:fixed-open:<n>    count-bucketed, so a change in the debt re-files
          pain-checks:broken:<n>

MUST NEVER
    - run the suite. One pass takes minutes and the sources loop wraps a source in `timeout 90`;
      the first version of the db-integrity source made exactly this mistake and would have been
      killed at 90 s on every pass, forever.
    - report a stale status as healthy.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "pain-checks"
STATUS = Path(os.environ.get("PAIN_CHECK_STATE", str(Path.home() / ".pain-check"))) / "status.json"
MAX_AGE_HOURS = float(os.environ.get("PAIN_CHECK_MAX_AGE_HOURS", "36"))
COOLDOWN_SECONDS = int(os.environ.get("PAIN_CHECK_COOLDOWN", "21600"))


def _status() -> tuple:
    """(data, stale_hours_or_None, never_ran).

    STALENESS IS WORK, and it is filed as work. Until 2026-10-02 a stale status raised Unreadable,
    which exits 1 and leaves one red line in sources.log -- so when the pain-check cron line turned
    out to carry a corrupt wrapper payload, the suite went 37.3 h without running and NOTHING asked
    anybody to look. The suite is the mechanism that closes fixed defects (journal P4/P58); a
    stopped mechanism is a repair item, not a quiet reading. The reasoning that a stale file must
    not be read as "all checks passed" still holds, which is why the fixed-open findings are not
    produced from a stale file -- only the staleness finding is.
    """
    if not STATUS.is_file():
        return {}, None, True
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("the status file is not JSON: %s" % exc)
    at = data.get("at") or ""
    try:
        when = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        raise Unreadable("the status file carries no usable timestamp (at=%r)" % at)
    age_h = (datetime.now(timezone.utc) - when).total_seconds() / 3600.0
    return data, (age_h if age_h > MAX_AGE_HOURS else None), False


def _stale_finding(stale_h, never_ran: bool, at: str) -> Finding:
    bucket = 0 if (never_ran or MAX_AGE_HOURS <= 0) else int(stale_h // MAX_AGE_HOURS)
    return Finding(
        subject="pain-checks:suite-stale:%d" % bucket,
        priority="high",
        kind="repair",
        cooldown_seconds=COOLDOWN_SECONDS,
        context=json.dumps({"stale_hours": None if stale_h is None else round(stale_h, 1),
                            "never_ran": never_ran, "status_at": at, "status": str(STATUS)}),
        prompt=(
            "THE MECHANISM THAT CLOSES FIXED DEFECTS HAS STOPPED RUNNING.\n\n"
            "    the check suite last completed : %s\n"
            "    stale by                       : %s (ceiling %.0f h)\n"
            "    its status file                : %s\n\n"
            "`~/bin/pain-check.py --write-status` runs the executable check suite over the open pain\n"
            "entries -- the only thing that can prove an entry's cause is gone, and the reason the\n"
            "open count is a measurement rather than a mood (journal P4, P58). It is scheduled at\n"
            "`20 6 * * *` through cron-wrap.sh. The healthy value is a fresh status file: measured\n"
            "2026-10-02 it had gone 37.3 h without updating because the cron line carried its command\n"
            "RAW instead of base64-encoded and cron-wrap refused it before writing a run record --\n"
            "so a whole class of defect-closing work was dead with no symptom.\n\n"
            "WHAT TO DO\n"
            "  1. `grep -P '\\tpain-check\\t' ~/.cron-status/runs.tsv | tail -5` -- is there a row at\n"
            "     all? No row means the job never ran: read the crontab line and re-wrap it with\n"
            "     `python3 ~/bin/wrap-crontab.py --install` (it verifies byte-exactly).\n"
            "  2. Otherwise read the last row's rc and stderr tail -- the suite itself is failing.\n"
            "  3. Run it BY HAND and let it finish: `/home/zabz/bin/pain-check.py --write-status`\n"
            "     (about 6 minutes; C1.sh alone is ~285 s). Paste the tail.\n"
            "  4. Confirm a fresh `at` in the status file and a new rc=0 row, and report the\n"
            "     FIXED-but-OPEN count you find -- that backlog is the next thing to close.\n\n"
            "Do not hand-write the status file: the point is that the checks actually ran."
            % (at or "(never)", ("never ran" if never_ran else "%.1f h" % stale_h),
               MAX_AGE_HOURS, STATUS)))


def collect(args) -> list[Finding]:
    d, stale_h, never_ran = _status()
    if never_ran or stale_h is not None:
        return [_stale_finding(stale_h, never_ran, d.get("at") or "")]
    findings = []

    fixed_open = d.get("fixed_and_still_open") or []
    if fixed_open:
        bucket = (len(fixed_open) // 10) * 10
        prompt = (
            "THE RECORD DISAGREES WITH THE EVIDENCE: %d open pain entries are proven fixed by their\n"
            "own checks.\n\n"
            "  %s\n\n"
            "Each of those ids has an executable check that ran on this machine and reported FIXED,\n"
            "while the journal still lists it open. That gap is the defect this source exists to\n"
            "close: on 2026-09-30 an audit found 52 entries in exactly this state, and that is why\n"
            "the open count was not a measurement (journal P4, P58).\n\n"
            "WHAT TO DO:\n"
            "  1. Run `python3 ~/bin/pain-check.py` and read the FIXED-but-OPEN count. Confirm it is\n"
            "     the same number as above -- if it has moved, that is a check moving and worth a\n"
            "     look before you act.\n"
            "  2. Spot-check ONE of them by hand: read the entry, run its check, and satisfy yourself\n"
            "     that FIXED means what it says. A check that closes a real defect silently is worse\n"
            "     than a stale open entry, so this step is the one that matters.\n"
            "  3. Then `python3 ~/bin/pain-check.py --close`, which resolves exactly the ids whose\n"
            "     own check reports FIXED and records the check's reason in each resolution.\n"
            "  4. Report which ids closed and which check file was wrong if the spot-check failed.\n\n"
            "Do not close an entry by hand from this list: the point is that the evidence closes it."
        ) % (len(fixed_open), ", ".join(fixed_open[:40]))
        findings.append(Finding(
            subject="pain-checks:fixed-open:%d" % bucket,
            prompt=prompt, priority="normal", kind="task",
            context=json.dumps({"fixed_and_still_open": fixed_open,
                                "open_pain_entries": d.get("open_pain_entries"),
                                "at": d.get("at")}),
            cooldown_seconds=COOLDOWN_SECONDS,
        ))

    broken = d.get("broken_check_files") or []
    if broken:
        names = [b.get("file") for b in broken][:20]
        prompt = (
            "%d check file(s) in the pain-check suite are BROKEN -- they exited non-zero or printed\n"
            "no findings, so nothing they were supposed to decide was decided.\n\n"
            "  %s\n\n"
            "Details: %s\n\n"
            "A broken check is not a finding, and confusing the two is how a suite becomes decoration:\n"
            "'the checks ran and everything is fine' must never be what a crashed check means.\n\n"
            "WHAT TO DO: run `bash /home/zabz/bin/pain-checks/<file>` by hand, read the error, fix the\n"
            "check (not the entry), and prove it by re-running `python3 ~/bin/pain-check.py --only\n"
            "<tag>` and pasting the line for one id it decides."
        ) % (len(broken), ", ".join(names), json.dumps(broken)[:600])
        findings.append(Finding(
            subject="pain-checks:broken:%d" % len(broken),
            prompt=prompt, priority="normal", kind="repair",
            context=json.dumps({"broken": broken, "at": d.get("at")}),
            cooldown_seconds=COOLDOWN_SECONDS,
        ))

    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
