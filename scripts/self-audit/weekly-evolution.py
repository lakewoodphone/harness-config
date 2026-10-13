#!/usr/bin/env python3
"""weekly-evolution -- a wake source that files the weekly self-audit as WORK.

WHAT IT IS
----------
The measurement (`weekly-evolution-audit.py`, sibling) turns "how did we wildly
evolve this week" into numbers. This file is the JUDGE: it decides whether those
numbers mean there is work a live session must do, and if so files exactly one
wake row, deduped by a stable subject.

THE SIGNAL, AND WHY IT IS ABNORMAL
----------------------------------
The signal is *material change in the last 7 days vs the previous run*. On a
healthy estate the week DOES change -- commits land, journal entries accrue,
capabilities are added -- and a weekly audit is the work. The thing that must
never happen is the OPPOSITE: a week in which NOTHING measurable moved while
agents claim to be "wildly evolving". That is the abnormal case the brief names.

But there is a second, more important abnormality, and it is the one this source
is built around: a metric that used to be measurable and is now `COULD NOT ASK`.
A store that went dark is not "no change" -- it is a broken instrument, and the
audit must say so out loud rather than print a smaller number.

So it files when EITHER:
  * a previous run exists and something measurable CHANGED (the normal weekly
    audit, one session per ISO week), OR
  * a metric regressed from `measured` to `COULD NOT ASK` (the instrument broke).
It stays `quiet` when a previous run exists and every measured value is
identical AND no instrument went dark.

THE CADENCE AND THE DEDUP (both are the store's job, not ours)
--------------------------------------------------------------
subject = `self-audit:<ISO-year>-W<ISO-week>` -- stable for the whole week, so
the store's own subject dedup makes a second file attempt in the same week a
`deduped`, never a second session. It also carries `cooldown_seconds=604800`
(7 days) as belt-and-braces. No source keeps state; the store is the only state.

Usage: python3 weekly-evolution.py [--dry-run]
Exit: 0 always for a read signal (filed or quiet); 1 when the signal itself
      could not be read. Stdout is exactly `quiet` or `flagged <subject>`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = "weekly-evolution"
WINDOW_DAYS = int(os.environ.get("SELF_AUDIT_WINDOW_DAYS") or 7)
STATE_DIR = Path(os.environ.get("SELF_AUDIT_OUT") or (Path.home() / ".self-audit" / "runs"))


def load_flag():
    """Load the FROZEN plumbing from wherever the authority installed it.

    The source lives in the repo and is installed by the orchestrator; _flag.py
    lives next to it in the live sources dir. We refuse to guess: if the frozen
    plumbing is not found, that is an unreadable signal, not a licence to
    hand-roll a second flag path.
    """
    cands = [os.environ.get("WAKE_SOURCES_DIR"),
             str(HERE),
             str(Path.home() / "bin" / "sources"),
             "/root/bin/sources"]
    for cand in cands:
        if not cand:
            continue
        p = Path(cand) / "_flag.py"
        if p.is_file():
            spec = importlib.util.spec_from_file_location("_flag", str(p))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["_flag"] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


def iso_week_subject(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    y, w, _ = now.isocalendar()
    return f"self-audit:{y}-W{w:02d}"


def iso_week_of(generated_at) -> str | None:
    """The 'YYYY-Www' of a record's generated_at, or None if unparseable."""
    try:
        dt = datetime.strptime(str(generated_at), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def latest_record() -> dict | None:
    p = STATE_DIR / "latest.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def already_measured_this_week() -> bool:
    """True when latest.json is a record from the current ISO week.

    THE CADENCE IS THE POINT. `run-wake-sources.sh` calls this source every 30
    minutes (cron :07/:37), and collect() used to measure on every call. That
    wrote a run-*.json every 30 minutes, so `load_previous()` always diffed
    against a half-hour-old record and the "weekly" audit was really a
    30-minute audit reading a directory filling at ~48 files/day. Measured
    2026-10-13 (item self-audit:2026-W42): the baseline and the corrected run
    are 23 minutes apart. The week's measurement is taken once; later passes in
    the same ISO week are quiet without touching the store, so the next diff is
    a real week against the last real measurement.
    """
    prev = latest_record()
    if prev is None:
        return False
    return iso_week_of(prev.get("generated_at")) == iso_week_subject().split(":", 1)[1]


def measure() -> dict:
    """Run the measurement into STATE_DIR and return its record. Read-only: the
    measurement only ever reads the estate's stores; it writes its own JSON.

    THE REPO IS PASSED EXPLICITLY, AND THAT IS THE FIX FOR A MEASURED DEFECT
    (2026-10-13, item self-audit:2026-W42). The audit's git/journal/capability
    collectors all resolve paths against `--repo`, which defaults to the CWD.
    run-wake-sources.sh `cd /root/bin/sources` before calling this source, and
    /root/bin/sources is NOT a git repository and has no journal/tools/. The
    first weekly run therefore produced `commits_landed` COULD NOT ASK, a
    `journal_entries_by_kind` COULD NOT ASK, and FIVE false zeros for the
    new-capability buckets -- numbers that looked like "nothing was added" but
    were the absence of a measurement. The instrument now names the repo it
    measures; if the repo is wrong or missing the audit says COULD NOT ASK
    rather than reporting a zero.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    script = HERE / "weekly-evolution-audit.py"
    repo = (os.environ.get("SELF_AUDIT_REPO") or os.environ.get("HARNESS_REPO")
            or "/root/code/harness-config")
    cmd = [sys.executable, str(script), "--json-only", "--out", str(STATE_DIR),
           "--window-days", str(WINDOW_DAYS), "--repo", repo]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"measurement failed rc={proc.returncode}: {proc.stderr[:300]}")
    return json.loads(proc.stdout)


def numeric(record: dict) -> dict:
    flat = {}

    def walk(prefix, obj):
        if isinstance(obj, dict):
            if obj.get("status") == "measured" and isinstance(obj.get("value"), (int, float)):
                flat[prefix] = obj["value"]
            else:
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)
    walk("", record)
    return flat


def unmeasured(record: dict) -> list[str]:
    out = []

    def walk(prefix, obj):
        if isinstance(obj, dict):
            if obj.get("status") == "COULD NOT ASK":
                out.append(prefix)
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
    walk("", record)
    return out


def collect(args, flagmod):
    """Return [] for quiet, or [Finding] to file. May raise flagmod.Unreadable."""
    previous_path = STATE_DIR / "latest.json"
    previous = None
    if previous_path.is_file():
        try:
            previous = json.loads(previous_path.read_text())
        except (OSError, ValueError):
            previous = None

    if already_measured_this_week():
        return []          # this ISO week already has its measurement

    record = measure()
    now = numeric(record)
    broken_now = set(unmeasured(record))

    if previous is None:
        reason = ("no previous run: this is the baseline measurement, so the first "
                  "weekly audit has real work to do (read the numbers, name the "
                  "changes, find what is not moving).")
    else:
        prev = numeric(previous)
        changed = {k: v - prev[k] for k, v in now.items()
                   if k in prev and isinstance(prev[k], (int, float)) and v != prev[k]}
        broken_prev = set(unmeasured(previous))
        newly_broken = sorted(broken_now - broken_prev)
        if newly_broken:
            reason = ("an instrument went dark this week (was measurable, now "
                      "COULD NOT ASK): " + ", ".join(newly_broken[:8]))
        elif changed:
            top = ", ".join(f"{k} {v:+d}" for k, v in list(sorted(changed.items()))[:10])
            reason = f"measurable change since {previous.get('run_id')}: {top}"
        else:
            return []          # NOTHING CHANGED -- this is the quiet path

    week = iso_week_subject()
    body = json.dumps(record, sort_keys=True)
    finding = flagmod.Finding(
        subject=week,
        prompt=(
            "WEEKLY SELF-EVOLUTION AUDIT. Read the measurement record at "
            f"{STATE_DIR/'latest.json'} and the human digest; produce the week's "
            "evolution audit as a real artefact, not prose. " + reason +
            "\n\nThe record's every number carries its source and freshness. Report "
            "what changed, what did not move, and every COULD NOT ASK cell as a "
            "broken instrument rather than a small number. Do not re-measure by "
            "reading files: run scripts/self-audit/weekly-evolution-audit.py."
        ),
        priority="normal",
        kind="task",
        context=(f"measurement={record.get('run_id')} subject={week} "
                 f"commit={record.get('repo',{}).get('head','?')[:12]} "
                 f"broken={len(broken_now)}")[:900],
        cooldown_seconds=604800,
    )
    return [finding]


def main() -> int:
    flagmod = load_flag()
    if flagmod is None:
        print("weekly-evolution: SIGNAL UNREADABLE -- the frozen _flag.py plumbing "
              "was not found in WAKE_SOURCES_DIR, ~/bin/sources or /root/bin/sources",
              file=sys.stderr)
        return 1
    # --dry-run is parsed by the frozen run(); we pass argv straight through.
    return flagmod.run(SOURCE, lambda args: collect(args, flagmod))


if __name__ == "__main__":
    sys.exit(main())
