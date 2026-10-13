#!/usr/bin/env python3
"""FLAG SOURCE: the accounting backlog is not finished, so a shift must run.

THE SIGNAL
----------
`~/.cfo/scoreboard.json`, written by `~/bin/cfo-scoreboard.py` -- the single measure
of the CFO backfill program (schema frozen in
`/home/zabz/phone/cfo-program-2026-10-02/20-brief-score.md`). Two facts are read from it:

    totals.unexplained        the backlog: non-duplicate transactions with no
                              `transaction_categories` row. Measured 2026-10-02:
                              1,959 of 7,951 in the last 24 months.
    at                        when the measurement was taken (provenance).

and one fact from the shift record, `~/.cfo/shifts.jsonl` (one JSON line per shift,
appended by `~/bin/cfo-shift.py`):

    retired_transactions      of the LAST shift. 0 means the loop is stalled.

WHY THIS SOURCE EXISTS
----------------------
The program is a loop -- scoreboard -> trigger -> shift -> resolver -> sanctioned
writer -> scoreboard -- and every part of it is being built tonight except the thing
that FEEDS it. Without a source, the loop is idle: measured 2026-10-02, the `cfo`
work ledger held 18 done, 4 blocked and **0 todo**, so nothing had anything to claim
and the 1,959-transaction backlog simply sat there. A program nobody starts is a
script. This is the starter.

THE TWO FINDINGS, and why the second one is not optional
--------------------------------------------------------
A. BACKLOG. `totals.unexplained > CFO_BACKFILL_MIN_UNEXPLAINED` (default 25). The
   threshold is a floor below which a session is not worth a whole release: one
   shift retires whole clusters, and the measured backlog is 1,959, so 25 is ~0.1 %
   of the job -- normal noise, not a reason to wake a machine. Any number above it
   fires, and the day-bucket in the subject keeps it to ONE session per day however
   large the backlog is.
B. STALL. The newest shift OUTCOME in `~/.cfo/shifts.jsonl` has
   `retired_transactions == 0`. That is the failure this program is most likely to
   die of: a shift that runs, resolves nothing, and reports success-shaped output.
   Silence would then look like progress -- a silent stall becomes a silent month.
   This finding fires even when the backlog number looks healthy, because a
   zero-retirement shift means the number is not moving.

   A line that declares itself a REHEARSAL (`"dry_run": true` or `"apply": false`,
   which is what `cfo-shift.py --dry-run` appends) is skipped, because a rehearsal
   retired nothing by definition and firing a stall off one would wake a real session
   to investigate a loop that was never running. Measured 2026-10-02 20:50Z: the live
   shift log held exactly one line and it was a rehearsal.

An ABSENT shift log is not a stall (no shift has ever run -- the backlog signal
covers that). A PRESENT but unreadable shift log is a fault, and it is reported:
`cfo-shift.py` appends whole lines, so a torn last line means a shift was killed
mid-write. If the backlog is over the threshold the source still fires and names the
broken log in the prompt; if the backlog is under it, the source raises Unreadable
and exits 1, because then the stall signal is the only thing that could feed the
loop and it cannot be read. (A stderr-only note would be invisible: the runner logs
nothing for a source that exits 0 saying `quiet`.)

THRESHOLDS -- env-overridable, all read at call time
    CFO_BACKFILL_MIN_UNEXPLAINED   (25)    the floor described above
    CFO_BACKFILL_MAX_AGE_HOURS     (30)    a scoreboard older than this is NOT a
                                           backlog reading. 30 h is the scoreboard's
                                           own cadence (the program runs a shift a
                                           day) plus a shift's slack: one missed day
                                           is still a reading, a day and a half is a
                                           dead instrument. A stale or missing
                                           scoreboard is Unreadable -> exit 1, never
                                           `quiet` and never a finding.
    CFO_BACKFILL_COOLDOWN_SEC      (86400) the store-side half of "one per day".

SUBJECT  cfo-backfill:<UTC day>   -- day-bucketed, so an unfinished program costs at
    most ONE session per UTC day, not one per run of the 15-minute source loop
    (`run-wake-sources.sh`). The backlog size is deliberately NOT in the subject:
    1,959 today and 1,940 tomorrow is the same work, and a count in the key would
    make every shift file a new row on a job that is already running.

PRIORITY `normal`, KIND `task`. `normal` because the night gate is where "night by
night" happens -- a `low` row is held from 03:00 to 13:00 UTC and this work is the
owner's stated day-and-night loop, so it must not be special-cased silent.

MUST NEVER
    * run a shift, or the scoreboard, or the resolver -- this is a sensor, it reads
      two files and files at most one row;
    * open the accounting ledger, or write anywhere except through the frozen `flag`
      CLI (`wake.py`), which is the store's own writer;
    * fire on a stale scoreboard (a stale measurement is not a backlog), or fire
      while the program is finished (`unexplained <= threshold` and the last shift
      retired something);
    * send anything to anyone. The shift's ONE owner question goes through
      `~/bin/owner-queue.py`, and the prompt says so;
    * raise a wake flag from inside a woken session -- the store refuses that itself.

RUN
    python3 sources/cfo-backfill.py [--dry-run]
    CFO_SCOREBOARD    default ~/.cfo/scoreboard.json
    CFO_SHIFT_LOG     default ~/.cfo/shifts.jsonl
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

SOURCE = "cfo-backfill"

DEFAULT_SCOREBOARD = "~/.cfo/scoreboard.json"
DEFAULT_SHIFT_LOG = "~/.cfo/shifts.jsonl"
DEFAULT_MIN_UNEXPLAINED = 25
DEFAULT_MAX_AGE_HOURS = 30.0
DEFAULT_COOLDOWN_SEC = 86400

PROGRAM_DOC = "/home/zabz/phone/cfo-program-2026-10-02/00-PROGRAM.md"
INGEST_DOC = "/home/zabz/phone/cfo-program-2026-10-02/10-INGEST.md"
SHIFT_COMMAND = "python3 ~/bin/cfo-shift.py --once --apply"
SCOREBOARD_COMMAND = "python3 ~/bin/cfo-scoreboard.py"
LEDGER = "/home/zabz/accounting-data/live/accounting.db"
LEDGER_WRITER = ("~/repos/quickbooks-agent/src/localfirst/storage.ts (the quickbooks-agent "
                 "storage layer) or app/services/auto_categorize.py")
OWNER_QUEUE = "python3 ~/bin/owner-queue.py"


# --------------------------------------------------------------------------- #
# settings -- read at call time, never cached
# --------------------------------------------------------------------------- #
def _env_path(name: str, default: str) -> Path:
    return Path(os.path.expanduser(os.environ.get(name) or default))


def scoreboard_path() -> Path:
    return _env_path("CFO_SCOREBOARD", DEFAULT_SCOREBOARD)


def shift_log_path() -> Path:
    return _env_path("CFO_SHIFT_LOG", DEFAULT_SHIFT_LOG)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def min_unexplained() -> int:
    return _env_int("CFO_BACKFILL_MIN_UNEXPLAINED", DEFAULT_MIN_UNEXPLAINED)


def max_age_hours() -> float:
    return _env_float("CFO_BACKFILL_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS)


def cooldown_seconds() -> int:
    return _env_int("CFO_BACKFILL_COOLDOWN_SEC", DEFAULT_COOLDOWN_SEC)


def subject_for(when: datetime) -> str:
    """The dedup key: ONE row per UTC day, whatever the backlog size.

    Exposed because the day bucket is the whole reason a months-long program does not
    become a session factory, and the test asserts it directly at two different days.
    """
    day = when.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"{SOURCE}:{day}"


# --------------------------------------------------------------------------- #
# reading -- two files, nothing else
# --------------------------------------------------------------------------- #
def _read_json(path: Path, what: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unreadable(f"cannot read the {what} at {path}: {exc}") from exc
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise Unreadable(f"the {what} at {path} is not readable JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise Unreadable(f"the {what} at {path} is not a JSON object")
    return doc


def _number(value) -> int | None:
    """An integer, or None. `True` is not a number here (bool is an int subclass)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def read_scoreboard(now: datetime) -> tuple[dict, Path, datetime, float, str, int]:
    """(doc, path, measured_at, age_hours, age_source, unexplained). Raises Unreadable."""
    path = scoreboard_path()
    if not path.is_file():
        # A missing scoreboard is the program not being measured, NOT an empty
        # backlog. Reporting it as `quiet` would be the exact failure this source
        # exists to prevent, one level down.
        raise Unreadable(
            f"no scoreboard at {path} -- the backlog cannot be measured, and an "
            f"unmeasured backlog is not an empty one (run `{SCOREBOARD_COMMAND}`)")

    doc = _read_json(path, "scoreboard")

    measured = _flag.parse_dt(doc.get("at"))
    age_source = "the scoreboard's own `at`"
    if measured is None:
        # No `at` is a defect in the measurement, but the file is here and its mtime
        # is a real fact -- so the age is read from it and SAID, rather than either
        # inventing an age or refusing to look at a file that exists. Nothing here
        # is guessed: the number still comes from the scoreboard itself.
        try:
            measured = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError as exc:
            raise Unreadable(
                f"scoreboard {path} carries no readable `at` and cannot be stat-ed: {exc}"
            ) from exc
        age_source = ("the file's mtime, because the scoreboard carries no readable `at`")
        print(f"{SOURCE}: {path} has no readable `at`; measuring the age from the "
              f"file mtime ({measured.isoformat(timespec='seconds')}) instead",
              file=sys.stderr)

    age_hours = (now - measured).total_seconds() / 3600.0
    if age_hours > max_age_hours():
        raise Unreadable(
            f"scoreboard {path} was measured at {measured.isoformat(timespec='seconds')}"
            f", {age_hours:.1f} h ago -- older than CFO_BACKFILL_MAX_AGE_HOURS="
            f"{max_age_hours():g}. A stale measurement is not a backlog: this source "
            f"will not turn yesterday's number into today's session "
            f"(re-run `{SCOREBOARD_COMMAND}`)")

    totals = doc.get("totals")
    if not isinstance(totals, dict):
        raise Unreadable(f"scoreboard {path} has no `totals` object -- cannot read the backlog")
    unexplained = _number(totals.get("unexplained"))
    if unexplained is None:
        raise Unreadable(
            f"scoreboard {path} has no numeric totals.unexplained -- cannot read the backlog")

    return doc, path, measured, age_hours, age_source, unexplained


def read_last_shift() -> tuple[dict | None, int, str, bool]:
    """(newest shift OUTCOME or None, rehearsals skipped, why, broken).

    The newest line that is a shift OUTCOME. A line that declares itself a rehearsal
    (`"dry_run": true` or `"apply": false` -- what `cfo-shift.py --dry-run` writes) is
    not a shift: it retired nothing because it APPLIED nothing, and firing a stall
    finding off a rehearsal would wake a real session to investigate a loop that was
    never running. Measured 2026-10-02 20:50Z: the live `~/.cfo/shifts.jsonl` held
    exactly one line, a rehearsal, with `retired_transactions: 0` -- under the literal
    reading this source would have filed a stall for every dry run anybody ran.
    A record carrying neither key is an outcome, so the frozen schema's own shape
    still fires exactly as contracted.

    `broken` is separate from "absent" on purpose: no log means no shift has run yet
    (the backlog signal covers that), while a log whose LAST line cannot be read is a
    fault -- a killed shift leaves a torn trailing line. Never raises: the caller
    decides what a broken record means, because a broken record over a real backlog is
    still work, and a broken record under the threshold is not something to go quiet
    about.
    """
    path = shift_log_path()
    if not path.is_file():
        return None, 0, f"no shift has recorded a line in {path} yet", False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, 0, f"the shift log {path} could not be read: {exc}", True
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None, 0, f"the shift log {path} exists but holds no shift line", True

    def parse(line: str, where: str) -> tuple[dict | None, str]:
        try:
            row = json.loads(line)
        except ValueError as exc:
            return None, (f"the {where} line of {path} is not a complete JSON record "
                          f"({exc}) -- a shift was probably killed mid-write")
        if not isinstance(row, dict):
            return None, f"the {where} line of {path} is not a shift object"
        return row, ""

    newest, why = parse(lines[-1], "last")
    if newest is None:
        return None, 0, why, True

    rehearsals = 0
    row = newest
    for offset, line in enumerate(reversed(lines)):
        if offset:
            row, why = parse(line, "%dth-from-last" % (offset + 1))
            if row is None:
                # An unparseable line that is not the last one cannot be attributed to a
                # killed writer with confidence; say so and stop scanning back.
                print(f"{SOURCE}: {why}", file=sys.stderr)
                break
        if row.get("dry_run") is True or row.get("apply") is False:
            rehearsals += 1
            continue
        return row, rehearsals, ("" if not rehearsals else
                                 f"the newest {rehearsals} line(s) of {path} are dry "
                                 f"runs, not outcomes, and were skipped"), False

    return None, rehearsals, (f"every line of {path} is a dry run ({rehearsals}) -- "
                              f"no shift has ever recorded an outcome"), False


def _unexplained_clusters(doc: dict, limit: int = 5) -> list[dict]:
    """The scoreboard's own priority order (transactions desc, total_cents desc)."""
    rows = doc.get("clusters")
    if not isinstance(rows, list):
        return []
    kept = [r for r in rows if isinstance(r, dict)]
    return kept[:limit]


def _usd(cents) -> str:
    n = _number(cents)
    if n is None:
        return "amount unreadable"
    return "USD %.2f" % (n / 100.0)


def _cluster_lines(doc: dict) -> list[str]:
    rows = _unexplained_clusters(doc)
    if not rows:
        return ["    (the scoreboard names no clusters)"]
    out = []
    for i, row in enumerate(rows, 1):
        label = row.get("display") or row.get("merchant_key") or "(unnamed merchant)"
        n = _number(row.get("transactions"))
        out.append("      %d. %s -- %s transaction(s), %s"
                   % (i, str(label)[:70],
                      "?" if n is None else n, _usd(row.get("total_cents"))))
    return out


def _shift_lines(row: dict | None, note: str, rehearsals: int = 0) -> list[str]:
    if row is None:
        return [f"    {note}"]
    retired = _number(row.get("retired_transactions"))
    at = row.get("at") or row.get("ended") or row.get("started") or "(no timestamp)"
    when = _flag.parse_dt(at)
    age = "age unknown"
    if when is not None:
        hours = (_flag.now_utc() - when).total_seconds() / 3600.0
        age = f"{hours:.1f} h ago"
    lines = [
        f"    recorded at       {at}  ({age})",
        (f"    retired           {retired} transaction(s)  <-- STALLED: the loop "
         f"retired nothing" if retired == 0 else
         f"    retired           {'unreadable' if retired is None else retired} "
         f"transaction(s)"),
        f"    clusters/applied  {row.get('clusters_considered', '?')} considered, "
        f"{row.get('applied', '?')} applied",
    ]
    if rehearsals:
        lines.append(f"    skipped           {rehearsals} newer dry-run line(s) at the "
                     f"end of the log -- a rehearsal is not an outcome")
    unclear = row.get("unclear")
    if isinstance(unclear, list) and unclear:
        names = [str(u.get("merchant_key") or u) if isinstance(u, dict) else str(u)
                 for u in unclear[:5]]
        lines.append(f"    left unclear      {len(unclear)}: " + "; ".join(names))
    errors = row.get("errors")
    if errors:
        lines.append(f"    errors            "
                     f"{str(errors)[:200]}")
    if note:
        lines.append(f"    note              {note}")
    return lines


def _prompt(doc: dict, path: Path, measured: datetime, age_hours: float,
            age_source: str, row: dict | None, note: str, unexplained: int,
            stalled: bool, rehearsals: int = 0) -> str:
    totals = doc.get("totals") or {}
    window = doc.get("window") or {}
    ledger = doc.get("ledger") or {}
    at_txt = measured.astimezone(timezone.utc).isoformat(timespec="seconds")

    if stalled:
        headline = ("THE ACCOUNTING BACKLOG IS NOT MOVING. THE LAST SHIFT RETIRED "
                    "NOTHING.\nThe program is unfinished and the loop has stalled, so "
                    "this session exists to find out why it stopped retiring work.")
    else:
        headline = ("THE ACCOUNTING BACKLOG IS NOT FINISHED.\n"
                    "This program is the owner's books made 100% clear -- explained, "
                    "reconciled, and every exception named. It is measured, not guessed, "
                    "and the measurement says there is work.")

    lines = [
        headline,
        "",
        "WHAT THE SCOREBOARD SAYS (its own numbers, its own timestamp -- not my summary):",
        f"    scoreboard        {path}",
        f"    measured at       {at_txt}  ({age_hours:.1f} h ago, from {age_source})",
        f"    ledger            {ledger.get('path', LEDGER)}"
        + (f"  sha256 {str(ledger.get('sha256'))[:16]}..." if ledger.get("sha256") else ""),
        f"    window            {window.get('from', '?')} .. {window.get('to', '?')}"
        f"  ({window.get('months', '?')} months)",
        f"    transactions      {totals.get('transactions', '?')}"
        f"  (non-duplicate {totals.get('non_duplicate', '?')})",
        f"    UNEXPLAINED       {unexplained}   <-- the number this program exists to reduce",
        f"    THIN              {totals.get('thin', '?')}   (categorised, no justification "
        f"and no evidence: a guess with a label)",
        f"    EVIDENCED         {totals.get('evidenced', '?')}",
        f"    pct_clear         {totals.get('pct_clear', '?')}"
        f"  (target: everything, backlog_target "
        f"{totals.get('backlog_target', 0)})",
        "",
        "    biggest unexplained clusters, in the scoreboard's own priority order:",
    ]
    lines += _cluster_lines(doc)
    lines += [
        "",
        "THE LAST SHIFT IN THE RECORD:",
    ]
    lines += _shift_lines(row, note, rehearsals)
    lines += [
        "",
        "DO THIS NOW -- ONE BOUNDED SHIFT, IN THIS EXACT SHAPE",
        f"  1. READ FIRST: {PROGRAM_DOC}",
        "     It is the contract: the three buckets (UNEXPLAINED / THIN / EVIDENCED), the",
        "     evidence ladder in order, the sanctioned writers, the budget, and what must",
        f"     never happen. {INGEST_DOC} beside it holds the measured state.",
        f"  2. RUN THE SHIFT:  {SHIFT_COMMAND}",
        "     That is the exact command. Its bounds are one batch:",
        "       CFO_SHIFT_BATCH    40 clusters, or 120 transactions, whichever comes first",
        "       CFO_SHIFT_SECONDS  900 s",
        "     A shift is ONE bounded batch. Stop when a bound is reached, checkpoint as you",
        "     go, and let the next shift pick up the rest -- a shift that overruns gets",
        "     killed and teaches nothing. `--dry-run` first is allowed; the apply is the job.",
        "     Prefer a RULE: N charges from one merchant are ONE decision that retires all",
        "     N. Most specific first -- amount + merchant + method beats merchant alone.",
        "  3. WRITE ONLY THROUGH THE SANCTIONED WRITER.",
        f"     The ledger is {LEDGER}. Open it `mode=ro` unless you are applying through",
        f"     {LEDGER_WRITER},",
        "     and take a `VACUUM INTO` copy before the first write of the session. Never a",
        "     fresh INSERT from a new script unless that is the only reachable path -- and",
        "     then it must mirror the sanctioned column set and id scheme, use",
        "     INSERT OR IGNORE/upsert semantics, and say so loudly in its own docstring.",
        "     Every decision and its reason lands in ~/.cfo/resolutions.jsonl.",
        f"  4. AT MOST ONE OWNER QUESTION, IN WORDS. Only when a cluster is genuinely",
        "     blocked on a fact only the owner has:",
        f"       {OWNER_QUEUE} add ...",
        "     One human sentence naming the merchant, the amount and the missing fact. No",
        "     paths, no script names, no machine instructions. Never a text, never an",
        "     email, never SQL on the queue. Most clusters need no question at all -- the",
        "     evidence ladder answers them.",
        "  5. WRITE THE SHIFT RECORD. `cfo-shift.py` appends one line to",
        "     ~/.cfo/shifts.jsonl (at, started, ended, seconds, clusters_considered,",
        "     resolved, applied, retired_transactions, unclear, owner_questions_filed,",
        "     errors, scoreboard_before, scoreboard_after). If it could not write it, say",
        "     so and why -- that line is the only thing that tells the next shift, and this",
        "     source, whether the loop is moving.",
        "  6. NOTHING OUTBOUND. No text, no email, no call to anyone, ever. Do not raise a",
        "     wake flag, do not release a wake, do not touch cron, do not delete anything.",
        "",
        "THEN: report the scoreboard before -> after, the clusters resolved, the",
        "transactions retired, what is still unclear, and the next best clusters.",
        "",
        f"WHY ONE ROW PER DAY: this source files at most one session per UTC day whatever",
        f"the backlog size. The work is measured in months; one bounded shift a day (and",
        f"the same row can be released again if it fails) is the unit, not a burst.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the decision
# --------------------------------------------------------------------------- #
def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    doc, path, measured, age_hours, age_source, unexplained = read_scoreboard(now)

    row, rehearsals, note, broken_record = read_last_shift()
    retired = None if row is None else _number(row.get("retired_transactions"))
    stalled = (retired == 0)

    if note:
        print(f"{SOURCE}: {note}", file=sys.stderr)

    over_threshold = unexplained > min_unexplained()

    if not over_threshold and not stalled:
        if broken_record:
            # Nothing would feed the loop except the stall signal, and its record is
            # broken. An unreadable signal is never healthy -- so this is exit 1, not
            # `quiet` (which the runner would not even log).
            raise Unreadable(
                f"the backlog ({unexplained}) is at or under CFO_BACKFILL_MIN_UNEXPLAINED="
                f"{min_unexplained()}, so the stall signal is the only thing that could "
                f"feed this loop -- and {note}")
        return []

    subject = subject_for(now)
    prompt = _prompt(doc, path, measured, age_hours, age_source, row, note,
                     unexplained, stalled, rehearsals)
    if row is None:
        shift_summary = f"last shift: {note}"
    else:
        shift_summary = (f"last shift retired "
                         f"{'unreadable' if retired is None else retired}"
                         + (f" ({note})" if note else ""))
    context = (
        f"{SOURCE}: {unexplained} unexplained at "
        f"{measured.astimezone(timezone.utc).isoformat(timespec='seconds')} "
        f"({age_hours:.1f} h old, {path}); {shift_summary}")

    return [Finding(
        subject=subject,
        prompt=prompt,
        priority="normal",
        kind="task",
        cooldown_seconds=cooldown_seconds(),
        context=context,
    )]


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
