#!/usr/bin/env python3
"""FLAG SOURCE: a scheduled job that has stopped succeeding, and nobody can see it.

THE SIGNAL
----------
`~/.cron-status/runs.tsv`, one row per cron run written by `bin/cron-wrap.sh`:
`<ISO-8601 UTC>\t<name>\t<rc>\t<seconds>\t<stderr tail>`. This source reads the CURRENT
consecutive-failure streak per job, and any row where the wrapper itself refused to run.

WHY THIS SOURCE EXISTS, measured on the authority 2026-10-02 19:20Z (66 jobs, 25 h of runs)
--------------------------------------------------------------------------------------------
    dialpad-recording-gap     614 consecutive failures   100.0%   never succeeded once
    converge-authority        205 consecutive failures   100.0%
    audit                     102 consecutive failures   100.0%
    sync                      102 consecutive failures   100.0%
    text-channel-check         19 consecutive failures    54.3%
    lpt-recon-check            13 consecutive failures
    supplier-delivery-watch     9 consecutive failures
    monitor-hetzner-backups     9 consecutive failures   rc=2 cannot write /var/log/monitor-hetzner-backups.log
    box-health-check            2 consecutive failures   rc=2 cannot write /var/log/box-health.log
The healthy jobs in the same window: `serve-phone-2` 3.0% of 1533 runs, `sms-inbox` 3.7% of 614,
`wake-fanout` 0% of 3064. So a streak of 10 is roughly three times the worst healthy streak and
is not "a bad minute" -- it is a job that does not work.

AND ONE THAT HAD NEVER RUN AT ALL: the `pain-check` cron line was written with its command RAW
instead of base64-encoded. `cron-wrap.sh` refused it before writing any run record, so the pain
check suite had not run for 37 h, the source that watches it reported "signal unreadable" instead
of filing work, and the loop that closes fixed defects was dead with no symptom. `cron-wrap.sh`
now records its own refusal as rc=2 with `cron-wrap REFUSED:` in the stderr column, and THAT is
the second signal here: a refusal needs no streak, because the job provably never ran.

THRESHOLDS
    CONSEC >= 10 consecutive non-zero runs      healthy worst measured: 3 (serve-phone-2)
    any rc=2 row carrying "cron-wrap REFUSED"   no threshold: the job did not run
Both env-overridable (`CRON_FAIL_STREAK`, `CRON_FAIL_WINDOW_HOURS`).

SUBJECTS  cron-failing:<job>   one session per job per cooldown, not one per run
          cron-refused:<job>

MUST NEVER
    - run the failing job itself (the session that claims the flag does that, with the error in
      front of it) and never write, truncate or rotate runs.tsv -- this source is a reader;
    - treat a non-zero exit as a fault by itself: several jobs return 1 as a SIGNAL
      (`text-channel-check` returns 1 when its instruments fail), which is why the streak, not a
      single run, is the trigger;
    - file work for rc=3: this repo's word for "CONDITION, not fault" (`text-ledger-audit.py`,
      `order-feed-refresh.sh`, `mesh-hygiene.sh`, `serve-phone.sh`, `supplier-delivery-watch.py`,
      and since 2026-10-05 `ai-gateway-health.py`). rc=3 is a job WORKING and reporting an external
      condition it cannot clear, so a streak of it is not a repair job -- filing one duplicates the
      escalation and trains everyone to ignore this source;
      That rule applies to the STREAK as well: rc=3 ENDS a repair streak, because a run the
      job spent WORKING is not one of the "N in a row" the packet below counts;
    - file work for a REFUSAL whose line has since been REPAIRED. The rows stay in the record (it
      is append-only), so for WINDOW_HOURS after a wrap the source would otherwise keep filing a
      repair session for a job that is already running: measured 2026-10-05, the 01:38Z refuse rows
      for `supplier-delivery-watch` still filed at 14:34Z although `wrapped-at` recorded the
      14:20Z install and the 14:32Z run through the wrapper wrote rc=3. A refusal is only a finding
      while the live line still cannot run -- the payload is re-validated every pass, exactly as
      `bin/cron-wrap.sh` itself validates it, and a line that decodes skips the filing while saying
      so on stderr;
    - treat a missing runs.tsv as health -- it raises Unreadable and exits 1.
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "cron-failures"
RUNS = Path(os.environ.get("CRON_STATUS_RUNS") or (Path.home() / ".cron-status" / "runs.tsv"))
STREAK = int(os.environ.get("CRON_FAIL_STREAK", "10"))
WINDOW_HOURS = int(os.environ.get("CRON_FAIL_WINDOW_HOURS", "48"))
#: This repo's word for "CONDITION, not fault" (see CONDITION_EXIT in `ai-gateway-health.py`
#: and `text-ledger-audit.py`). A run that exits with this is a job WORKING, so it is not
#: part of a repair streak and must not extend one.
CONDITION_EXIT = "3"
COOLDOWN_SECONDS = int(os.environ.get("CRON_FAIL_COOLDOWN", "43200"))  # 12 h
REFUSED = "cron-wrap REFUSED"

#: JOBS WHOSE rc=1 IS A CONDITION, NOT A FAULT -- and each already escalates through another
#: source or its own owner row. A streak of rc=1 from one of these is the system reporting a
#: finding, and filing a session for it would duplicate the escalation and train everyone to
#: ignore this source. A crash from the same job (rc>=2, rc=127, a signal) still fires.
#: Measured 2026-10-02: `text-channel-check` had 19 consecutive rc=1 runs, all of them the same
#: red D3 order-feed check that already raises its own owner question.
#:
#: rc=3 IS HANDLED FOR EVERY JOB, not listed here. This repo reserves 3 for "condition, not fault"
#: (see CONDITION_EXIT in `ai-gateway-health.py` and `text-ledger-audit.py`), so a streak of rc=3 is
#: a job WORKING and reporting something only an external actor can clear -- exactly what must not be
#: filed as a repair. rc=1 stays per-job because it is ambiguous (some jobs signal with it, some
#: fault with it); rc=3 is not.
SIGNAL_EXIT_1 = {
    "text-channel-check": "returns 1 when its instruments find something; the instruments raise "
                          "their own owner row (and sources/pain-checks.py reads the same ground)",
    "pain-check": "returns 1 when entries are proven FIXED and still open; "
                  "sources/pain-checks.py escalates exactly that",
    "disk-guard": "returns 1 above the disk threshold; sources/disk-space.py escalates exactly that",
    "db-integrity-check": "returns 1 on an integrity finding; sources/db-integrity.py reads its "
                          "status file",
    "audit": "returns 1 when the four-surface verifier finds ERROR drift (its exit_code 2 means a "
             "surface was UNREACHABLE -- a real fault, and it still fires); it writes "
             "/home/zabz/.lpt-verify/four-surface.json, which owner-attention-digest.sh reads every "
             "30 min and reports as 'N drift finding(s)'",
}


def payload_runs(payload: str) -> bool:
    """True when `cron-wrap.sh` would ACCEPT this payload, i.e. the line can actually run.

    This repeats the wrapper's own test rather than guessing at it: `base64 -d` must succeed
    (the wrapper refuses otherwise with "payload ... is not valid base64") and must decode to a
    non-empty command (a payload that decodes to nothing is refused too). Never raises, and every
    doubt answers True -- FILING is the safe direction here, because this witness is only used to
    STOP filing a repair: an absent payload, an unreadable crontab, or a missing `base64` binary
    must keep the old behaviour and let the row file, never silently swallow a real refusal.
    """
    if not payload:
        return True
    try:
        p = subprocess.run(["base64", "-d"], input=payload.encode("utf-8"),
                           capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        return True
    if p.returncode != 0:
        return False
    return bool((p.stdout or b"").strip())


def _wrapped_jobs(crontab_text: str = "") -> dict:
    """The job names the LIVE crontab defines, mapped to whether their payload can run.

    A refusal row can belong to a job that no longer exists (a test row, a removed schedule), or
    to a job whose line has SINCE BEEN REPAIRED -- both file nothing. Filing for a name that is
    not in the crontab would send a session looking for a line that is not there, and filing for
    a name whose line now decodes would send it after a defect that is already fixed. Names and
    rows are never rewritten out of the record, which stays append-only. Never raises; empty on
    failure, and an empty result is treated as "cannot confirm" rather than "confirmed gone".

    `crontab_text` is a seam for tests: when given, it is parsed INSTEAD of running `crontab -l`,
    which is the only way to exercise this against a synthetic crontab on a host where the real
    one is under /var/spool and must not be touched. The default (empty) reads the live crontab.
    """
    if not crontab_text:
        try:
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        except Exception:  # noqa: BLE001
            return {}
        if p.returncode != 0:
            return {}
        crontab_text = p.stdout or ""
    jobs = {}
    for line in (crontab_text or "").splitlines():
        if "cron-wrap.sh" not in line or line.lstrip().startswith("#"):
            continue
        head, _, rest = line.partition("cron-wrap.sh")
        fields = rest.split(None, 2)
        if not fields or not fields[0]:
            continue
        payload = fields[1] if len(fields) > 1 else ""
        jobs[fields[0]] = payload_runs(payload)
    return jobs


def _wrapped_job_names() -> set:
    """Backwards-compatible view of the jobs the live crontab defines (names only)."""
    return set(_wrapped_jobs())


def collect(args, crontab_text: str = "") -> list[Finding]:
    if not RUNS.is_file():
        raise Unreadable("no run record at %s -- nothing is writing cron outcomes" % RUNS)
    try:
        text = RUNS.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not read %s: %s" % (RUNS, exc))

    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    streak: dict = collections.OrderedDict()
    total: collections.Counter = collections.Counter()
    failures: collections.Counter = collections.Counter()
    last: dict = {}
    refusals: dict = {}
    seen_rows = 0

    for line in text.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        stamp, name, rc, secs = parts[0], parts[1], parts[2], parts[3]
        err = parts[4] if len(parts) > 4 else ""
        if not name:
            continue
        seen_rows += 1
        total[name] += 1
        # A streak is COUNTED IN REPAIR-WORTHY RUNS. rc=3 is this repo's "CONDITION, not
        # fault" -- a job WORKING and reporting an external condition -- so, like rc=0, it
        # ENDS a streak instead of extending one. MEASURED 2026-10-06: counting rc=3 as a
        # failure made `ai-gateway-health` report "182 consecutive failures" when only 29 of
        # those runs were rc=1 (faults); 25 were rc=3, which this file's own contract says
        # must never be filed as repair work, and the rest predated the 2026-10-05 tri-state
        # fix and were the same, already-escalated provider condition. The inflated number is
        # what made the packet read "a job that does not work" instead of "a monitor
        # reporting a real fault".
        if rc == "0" or rc == CONDITION_EXIT:
            streak[name] = 0
        else:
            failures[name] += 1
            streak[name] = streak.get(name, 0) + 1
        last[name] = {"at": stamp, "rc": rc, "secs": secs, "err": err}
        if REFUSED in err and stamp >= since.isoformat():
            refusals[name] = {"at": stamp, "err": err}

    if not seen_rows:
        raise Unreadable("%s exists but holds no run rows -- treat as unreadable, not as clean" % RUNS)

    live = _wrapped_jobs(crontab_text)
    if not live:
        print("%s: could not read `crontab -l`, so job names cannot be confirmed; "
              "reporting whatever the run record holds" % SOURCE, file=sys.stderr)

    def _live(name: str) -> bool:
        if not live or name in live:
            return True
        print("%s: skipping %r -- no such job in the live crontab (stale or test row)"
              % (SOURCE, name), file=sys.stderr)
        return False

    def _line_runs(name: str) -> bool:
        """Whether the live line for a job that has refusal rows can now run."""
        return live.get(name, True)

    findings: list[Finding] = []

    for name, r in sorted(refusals.items()):
        if not _live(name):
            continue
        if _line_runs(name):
            print("%s: %s has a REFUSED row (%s) but its line now decodes -- the wrap was "
                  "repaired, so no repair is filed; the repair proof is the later row in "
                  "runs.tsv" % (SOURCE, name, r["at"]), file=sys.stderr)
            continue
        findings.append(Finding(
            subject="cron-refused:%s" % name,
            priority="high",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=str({"job": name, "rows": total[name], "last": last.get(name)}),
            prompt=(
                "A SCHEDULED JOB HAS NOT RUN AT ALL, AND THE WRAPPER SAID SO.\n\n"
                "    job          %s\n"
                "    last row     %s\n"
                "    the wrapper  %s\n\n"
                "`bin/cron-wrap.sh` takes a BASE64-ENCODED command as its second argument. When the\n"
                "payload does not decode it refuses before running anything -- and until 2026-10-02\n"
                "it refused SILENTLY, which is how the pain check suite went 37 h without running\n"
                "while its own watchdog reported 'signal unreadable'.\n\n"
                "WHAT TO DO\n"
                "  1. `crontab -l | grep -n %s` and look at the line. If the command after the job\n"
                "     name is not base64, the line was written by hand instead of by the installer.\n"
                "  2. Fix it with the sanctioned tool, which verifies byte-exactly and backs the old\n"
                "     crontab up first: `python3 ~/bin/wrap-crontab.py --install`.\n"
                "  3. Prove the job itself works BY HAND before trusting the schedule, and paste the\n"
                "     result. For the pain check: `/home/zabz/bin/pain-check.py --write-status`.\n"
                "  4. Confirm a new row appears in ~/.cron-status/runs.tsv for this job with rc=0.\n\n"
                "Do not edit crontab lines by hand: half-wrapped lines are how this happened."
                % (name, (last.get(name) or {}).get("at"), r["err"][:120], name))))

    for name, n in sorted(streak.items(), key=lambda kv: -kv[1]):
        if n < STREAK or not _live(name):
            continue
        info = last.get(name) or {}
        if (info.get("rc") or "") == "3":
            print("%s: %s has failed %d times in a row with rc=3 -- CONDITION, not fault; the job is "
                  "working and the condition escalates through its own source"
                  % (SOURCE, name, n), file=sys.stderr)
            continue
        if name in SIGNAL_EXIT_1 and (info.get("rc") or "") == "1":
            print("%s: %s has failed %d times in a row with rc=1 and is a SIGNAL, not a fault "
                  "(%s)" % (SOURCE, name, n, SIGNAL_EXIT_1[name]), file=sys.stderr)
            continue
        findings.append(Finding(
            subject="cron-failing:%s" % name,
            priority="normal",
            kind="repair",
            cooldown_seconds=COOLDOWN_SECONDS,
            context=str({"job": name, "streak": n, "runs": total[name],
                         "failures": failures[name], "last": info}),
            prompt=(
                "A SCHEDULED JOB HAS FAILED %d TIMES IN A ROW.\n\n"
                "    job            %s\n"
                "    consecutive    %d failures (of %d runs in the record)\n"
                "    last run       %s  rc=%s  %ss\n"
                "    last stderr    %s\n"
                "    healthy jobs in the same window: serve-phone-2 3.0%% of 1533 runs, "
                "sms-inbox 3.7%% of 614, wake-fanout 0%% of 3064 -- so %d in a row is not a bad "
                "minute, it is a job that does not work.\n\n"
                "WHAT TO DO\n"
                "  1. READ THE ERROR FIRST. `grep -P '\\t%s\\t' ~/.cron-status/runs.tsv | tail -5`\n"
                "     gives the last few stderr tails. If the error column is empty, the job exits\n"
                "     non-zero on purpose (a check that reports a finding) -- then say so and stop.\n"
                "  2. Run the job BY HAND with its own arguments (the wrapped payload is the exact\n"
                "     original command: `crontab -l | grep %s`), and read its output.\n"
                "  3. Fix the CAUSE. If it cannot be fixed tonight, make the failure HONEST: a job\n"
                "     that always exits non-zero must exit with a code that means 'condition, not\n"
                "     fault', or be removed from cron. A permanently red job trains everyone to\n"
                "     ignore the record, which is worse than the failure.\n"
                "  4. Paste a new rc=0 row from ~/.cron-status/runs.tsv as the proof, or leave the\n"
                "     row open with exactly what is blocking it.\n\n"
                "Do not delete or rotate runs.tsv and do not silence the job by removing its\n"
                "schedule unless the schedule is genuinely wrong."
                % (n, name, n, total[name], info.get("at"), info.get("rc"), info.get("secs"),
                   (info.get("err") or "(empty)")[:160], n, name, name))))

    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
