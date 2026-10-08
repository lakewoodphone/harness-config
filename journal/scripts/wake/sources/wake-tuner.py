#!/usr/bin/env python3
"""FLAG SOURCE: the wake-cost watchdog. Once a day, judge the wake algorithm itself.

OWNER'S WORDS (2026-09-20, work order `wake.py list --json` row id 12)
---------------------------------------------------------------------
    "it's great that dormant chats can keep getting reactivated, but it can be
     abused. We can't waste hundreds or thousands of dollars on stuff that don't
     need to happen ... there should also be a watchdog that once [a day] goes
     through everything and fixes up the algorithm for what gets activated and
     what not."

THE SIGNAL
----------
Three records, all on the authority, all read-only:

  (1) THE RELEASE HISTORY is the `wake` table in `~/.sms-inbox/inbox.db`: one row
      per subject ever filed, with `claimed_at` (the release), `finished_at`,
      `state` and `outcome`. This is the ONLY place a release exists; nothing
      else in the mesh records one.

  (1b) THE PER-RELEASE STREAM is `~/.sms-inbox/wake-dispatch.log`, written once
      per release by `wake-dispatch.sh`. It has to be read, because THE STORE
      CANNOT ANSWER "consecutive": `wake.subject` is UNIQUE, so a subject that is
      released five times is five claim events on ONE row whose `outcome` is only
      the latest one. The log is the only per-release history that exists, and
      each release there carries its own `exit=` and `outcome:` text -- so an
      empty release is measured from the release, not reconstructed from the
      row. If that log cannot be read, this source is `Unreadable` (rule R6): a
      streak of zero because the history is missing is the exact false-clear this
      whole deliverable exists to prevent.

  (2) THE SPEND RECORD is the JSONL written by `~/bin/wake-cost.py`
      (default `~/.sms-inbox/wake-cost.jsonl`): one object per release carrying
      the session it started, the session's real token totals, and either a
      sourced `cost_usd` or the string `unsourced`. THIS SOURCE DOES NOT DERIVE A
      PRICE ITSELF, and it never invents one (the spec's one hard prohibition).

      A MISSING JSONL IS NOT "no spend" -- it is a signal that was never
      written, and this source says so in the digest rather than reporting $0.

WHAT IT CHANGES, AND WHY IT IS ALLOWED TO
-----------------------------------------
The tuner writes NOTHING to the wake store. `wake.py` owns that table and the
frozen `flag` CLI is the only write path a source is allowed (sources/README.md:
"they write nothing anywhere except through the frozen `flag` CLI"). So every
change below is (a) computed from the record, (b) persisted in the tuner's own
state file `~/.sms-inbox/wake-tuner-state.json`, (c) given to `flag` as a
per-subject `--cooldown-seconds`, and (d) printed in the owner digest WITH the
rule that produced it. What is NOT auto-applied is stated as not-auto-applied:
`wake.py flag --cooldown-seconds` is the only per-subject cooldown lever that
exists today (there is no per-subject cooldown column on the `wake` table), so a
DISABLE is recorded and flagged, not written, until `wake.py` grows a
`not_before`/disable setter -- `wake-dispatch.sh` is another workstream's file
and is not touched here.

THE RULES (each one names its own threshold and its own reason)
---------------------------------------------------------------
  R1  EMPTY RELEASE, measured per release off the dispatcher's own log line and
      its `outcome:` text: a release whose exit code is non-zero, or whose exit
      was 0 with no outcome text at all, produced nothing. Measured on the live
      log 2026-09-20 (9 release lines): #1/#3 (exit 0, no outcome) and
      #8/#9/#10 (exit 1, runner_code=124 -- the ssh hop timed out) are empty by
      this rule, #2/#6 are not (exit 0, ~600 chars of proof). An empty release is
      the unit of waste this whole deliverable exists to find.
      ONE EXCEPTION, and it was measured: a row whose dispatcher verdict is
      `failed` but whose mapped session really burned tokens is NOT empty. All
      three of 2026-09-20's "failed" releases (#8/#9/#10, rc=124 ssh timeouts)
      have a session in the DSH store with 5.3M-9.7M tokens in it -- the session
      ran and did work, the ssh hop lost the answer. Calling that "empty" would
      mute a subject for the network's fault, so `log_event_empty()` checks the
      spend record first and says which it is. When the spend record is missing, a
      `failed` release is empty on the dispatcher verdict alone and the digest
      names the missing signal.
  R2  RAISE (back off). The subject's consecutive empty releases N raise the
      proposed cooldown to `BASE * (N+1)`, capped at
      `WAKE_TUNER_MAX_COOLDOWN_SEC` (604800 = 7 d). Calibrated against the
      measured history: three of three subject families that ever repeated,
      repeated at the dispatcher's 5-minute tick, i.e. far faster than the
      store's own 1800 s cooldown -- so doubling is the smallest step that is
      still visible.
  R3  DISABLE, NAMING IT. `N >= WAKE_TUNER_EMPTY_DISABLE_N` (default 3)
      consecutive empty releases disables the subject: it is named on stdout, in
      the digest, and in the state file, with the cooldown set to the cap.
      Three because the store already gives every subject `WAKE_MAX_ATTEMPTS=2`
      attempts per row; a third empty release is past the store's own patience.
  R4  SHORTEN. A released row that produced REAL work -- a non-empty outcome of
      at least `WAKE_TUNER_REAL_WORK_CHARS` (200) characters, or a mapped session
      proven to have made a model call (`output_tokens > 0`) -- resets the
      cooldown to the base once the subject has no empties in its last
      `WAKE_TUNER_LOOKBACK` (5) releases. Evidence for 200 chars: release #6's
      recorded outcome is ~1040 chars of commands and results, the self-test rows
      are under 40; a one-line "done" is not work.
  R5  CAPS. Releases attributed to each source in the last hour are compared with
      `WAKE_MAX_PER_SOURCE_PER_HOUR` and the day's releases with
      `WAKE_MAX_PER_DAY`, both read live from `wake.py stats --json`, never
      hard-coded here. A source at or over its hourly cap is named.
  R6  NO HEALTH CLAIM WITHOUT A RECORD. If the `wake` table cannot be read, or the
      spend JSONL exists and is malformed, this source raises `_flag.Unreadable`
      and exits 1 -- it never prints `quiet` as if the algorithm were fine.

SUBJECTS
    wake-cost-digest:<YYYYMMDD>   the once-a-day owner digest. One per UTC day, so
                                  a 15-minute cron or a hand-run cannot spam.
    wake-cost-tune:<subject>      filed only when a threshold actually changed
                                  for that subject, so the session gets the
                                  change and its rule, not a report.

MUST NEVER
    - invent a rate, or report a cost it could not source (it prints
      `unsourced` and says which releases are unpriced);
    - write the wake store, `wake.py`, `wake-dispatch.sh` or any cron;
    - report healthy because a signal is missing: a missing JSONL is named as a
      missing signal, a missing table is `Unreadable`;
    - fire from inside a woken session (the store refuses that itself).

SCHEDULING
    DAILY, not on the 15-minute source tick: run-wake-sources.sh carries a fixed
    source list owned by another workstream and is deliberately NOT edited here.
    The line to add (owner/manager action, with the manager's cron file):

        7 3 * * * /usr/bin/python3 /home/zabz/bin/sources/wake-tuner.py >> /home/zabz/.sms-inbox/sources.log 2>&1

    03:07 UTC: after the day's wake releases (which cluster 01:45-02:45 UTC here)
    and before the 05:00 app jobs, so the digest describes a settled day.
    `WAKE_TUNER_CRON=1` makes a second run in the same UTC day a no-op even
    without the state file.

RUN
    python3 ~/bin/sources/wake-tuner.py [--dry-run] [--force] [--print-digest]
    WAKE_TUNER_STATE          state file (default ~/.sms-inbox/wake-tuner-state.json)
    WAKE_COST_JSONL           the spend record (default ~/.sms-inbox/wake-cost.jsonl)
    WAKE_TUNER_BASE_COOLDOWN_SEC          1800  the store's own default
    WAKE_TUNER_MAX_COOLDOWN_SEC          604800 a week; nothing is ever fully muted
    WAKE_TUNER_EMPTY_DISABLE_N                3 consecutive empties -> disable
    WAKE_TUNER_REAL_WORK_CHARS              200 characters of outcome = real work
    WAKE_TUNER_LOOKBACK                       5 releases considered per subject
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "wake-tuner"


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def _int(env: str, default: int) -> int:
    try:
        return int(float(os.environ.get(env) or default))
    except (TypeError, ValueError):
        return default


def state_path() -> Path:
    return Path(os.environ.get("WAKE_TUNER_STATE")
                or (Path.home() / ".sms-inbox" / "wake-tuner-state.json"))


def cost_jsonl() -> Path:
    return Path(os.environ.get("WAKE_COST_JSONL")
                or (Path.home() / ".sms-inbox" / "wake-cost.jsonl"))


def dispatch_log() -> Path:
    return Path(os.environ.get("WAKE_DISPATCH_LOG")
                or (Path.home() / ".sms-inbox" / "wake-dispatch.log"))


def inbox_db() -> Path:
    return _flag.inbox_db()


def read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unreadable(f"{path} is not readable JSON: {exc}") from exc


# --------------------------------------------------------------------------- #
# (1) the release history
# --------------------------------------------------------------------------- #
def read_releases() -> list[dict]:
    """Every released wake row, oldest first. Unreadable is raised, never zeroed."""
    db = inbox_db()
    if not db.is_file():
        raise Unreadable(f"no wake store at {db}")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise Unreadable(f"cannot open {db}: {exc}") from exc
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                            " AND name='wake'").fetchone():
            raise Unreadable(f"{db} has no `wake` table -- no release history")
        rows = [dict(r) for r in conn.execute(
            "SELECT id, subject, source, kind, priority, state, created_at,"
            " claimed_at, finished_at, attempts, max_attempts, outcome, not_before"
            " FROM wake WHERE claimed_at IS NOT NULL ORDER BY id").fetchall()]
    except sqlite3.Error as exc:
        raise Unreadable(f"cannot read `wake` in {db}: {exc}") from exc
    finally:
        conn.close()
    return rows


_RELEASE_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T[\d:.+-]+Z)\s+released\s+(\S+)\s+wake\s+#(\d+)\s+"
    r"(?P<verdict>.*?)\s*exit=(\S+)(?:\s+runner_code=(\S+))?\s+cost=(\S+)"
    r"\s+dur=(\S+)s\s+subject=\"(?P<subject>.*)\"")
# The dispatcher writes the outcome line with its own ISO timestamp now
# ("2026-09-21T00:38:51Z   outcome: ..."); older lines are whitespace-
# indented. Match both, or every exit=0 release reads as "no outcome" and
# is charged a raise (R2) that the record does not support.
_OUTCOME_LINE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}T[\d:.+-]+Z\s+)?\s*outcome:\s?(?P<text>.*)$")


def read_dispatch_log() -> list[dict]:
    """One entry per release, oldest first, from the dispatcher's own log.

    This is what makes "CONSECUTIVE empty releases" measurable: `wake.subject` is
    UNIQUE, so the store keeps one row per subject and only the latest `outcome`,
    while the log keeps every release with its own `exit=` and `outcome:`. A log
    that exists but yields no release lines is Unreadable (rule R6) -- an empty
    streak there would be a false clear, not a quiet week.
    """
    path = dispatch_log()
    if not path.is_file():
        raise Unreadable(f"no dispatch log at {path} -- no per-release history")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unreadable(f"cannot read {path}: {exc}") from exc
    events: list[dict] = []
    unparsed = 0
    pending: dict | None = None
    for line in text.splitlines():
        match = _RELEASE_LINE.match(line.strip())
        if match:
            if pending:
                events.append(pending)
            verdict = (match.group("verdict") or "").strip()
            pending = {
                "at": match.group(1),
                "host": match.group(2),
                "release_id": int(match.group(3)),
                "verdict": verdict,
                "exit": match.group(5),
                "runner_code": match.group(6),
                "cost": match.group(7),
                "dur_s": match.group(8),
                "subject": match.group("subject"),
                "outcome": "",
            }
            continue
        if "released" in line and "wake #" in line:
            # A release line this parser cannot read is a COUNTED GAP: the
            # dispatcher is killed mid-write on a timeout, so the last line of the
            # log really can be truncated (measured 2026-09-20: #11's line ends at
            # `exit=`). Report the count rather than dropping it silently.
            unparsed += 1
        if pending is not None:
            omatch = _OUTCOME_LINE.match(line)
            if omatch:
                pending["outcome"] = omatch.group("text")
    if pending:
        events.append(pending)
    if not events:
        raise Unreadable(f"{path} holds no parseable release lines (checked"
                         f" {len(text.splitlines())} line(s))")
    if unparsed:
        events.append({"unreadable_lines": unparsed})
    return events


def subject_of(event: dict, by_id: dict[int, dict]) -> str:
    """The subject a logged release belonged to.

    The log's own `subject="..."` field is authoritative for that release (a row
    may since have been re-filed under a new id); the store is the fallback for
    older log lines that predate the field.
    """
    if event.get("subject"):
        return str(event["subject"])
    row = by_id.get(int(event.get("release_id") or 0)) or {}
    return str(row.get("subject") or f"wake#{event.get('release_id')}")


def cost_index() -> tuple[dict[int, dict], list[str]]:
    """release_id -> cost row, plus the names of the signals that were missing.

    A malformed line is `Unreadable`: this is the spend record, and a spend
    record that half-parses is worse than one that is absent.
    """
    path = cost_jsonl()
    gaps: list[str] = []
    if not path.is_file():
        gaps.append(f"spend record MISSING at {path} (run ~/bin/wake-cost.py)")
        return {}, gaps
    index: dict[int, dict] = {}
    for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError as exc:
            raise Unreadable(f"{path} line {number} is malformed JSON: {exc}") from exc
        if payload.get("type") == "release" and payload.get("release_id") is not None:
            index[int(payload["release_id"])] = payload
    if not index:
        gaps.append(f"spend record at {path} holds no release rows yet "
                    "(run ~/bin/wake-cost.py)")
    return index, gaps


# --------------------------------------------------------------------------- #
# (2) judgement
# --------------------------------------------------------------------------- #
def is_real_work(row: dict, spend: dict | None, chars: int) -> tuple[bool, str]:
    """Whether the newest release of a subject produced something worth keeping.

    Read from the row (its `outcome` is the newest release's outcome) and from the
    spend record, which can prove work even when the row's text says otherwise.
    """
    outcome = (row.get("outcome") or "").strip()
    if len(outcome) >= chars:
        return True, f"outcome {len(outcome)} chars >= {chars}"
    tokens = int((spend or {}).get("total_tokens") or 0)
    if tokens > 0:
        return True, (f"session {(spend or {}).get('session_id')} burned {tokens} "
                      f"token(s) ({int((spend or {}).get('output_tokens') or 0)} output)")
    return False, f"outcome {len(outcome)} chars < {chars} and no session tokens"


def per_source_last_hour(releases: list[dict]) -> dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    counts: dict[str, int] = defaultdict(int)
    for row in releases:
        claimed = _flag.parse_dt(row.get("claimed_at"))
        if claimed is not None and claimed >= cutoff:
            counts[row.get("source") or "manual"] += 1
    return dict(counts)


def log_event_empty(event: dict, costs: dict[int, dict]) -> tuple[bool, str]:
    """Whether a LOGGED release produced nothing.

    Measured from the release itself, not from the subject's current row: the
    log line carries its own dispatcher exit code and its own `outcome:` text.
    The spend record can still overturn it -- a release whose ssh hop reported a
    timeout but whose session burned tokens did work (measured 2026-09-20 on
    releases #8/#9/#10, all rc=124 with 5.3M-9.7M tokens in their sessions).
    """
    spend = costs.get(int(event.get("release_id") or 0)) or {}
    tokens = int(spend.get("total_tokens") or 0)
    if tokens > 0:
        return False, (f"exit={event.get('exit')} but session {spend.get('session_id')}"
                       f" burned {tokens} token(s)")
    outcome = (event.get("outcome") or "").strip()
    try:
        exit_code = int(str(event.get("exit") or "0").strip())
    except ValueError:
        exit_code = 0
    # A RELEASE THE RUNNER'S OWN BOUND KILLED IS COULD NOT ASK ABOUT THE SUBJECT.
    # `runner_code=124` is GNU timeout / the runner self-bound: the session was
    # SEVERED MID-WORK, which is not evidence that the subject is worthless.
    # Charging it to the subject would back off -- and eventually disable -- the
    # best work on the system, and it did precisely that on 2026-09-20, raising
    # the cooldown of `dormant-archive` and others for releases cut at 843s by a
    # bound that has since been raised to 2100s. The bound is fixed; the RULE
    # must not repeat the mistake if it recurs. This is the same distinction the
    # rest of this mesh is built on: a timeout is a fact about the bound, never
    # about the thing being measured.
    if str(event.get("runner_code") or "").strip() == "124":
        return False, ("COULD NOT ASK: the runner\'s own bound killed the session "
                       f"(runner_code=124, {len(outcome)} char(s) of output) - not evidence "
                       "about the subject, so holding instead of raising")

    # THE DISPATCHER'S OWN SELF-KILL IS ALSO NOT A VERDICT ABOUT THE SUBJECT.
    # Measured 2026-09-28 (release #77, project:rental-system:20260928): the
    # dispatcher's lease heartbeat failed three times on `database is locked`
    # contention, so wake-dispatch.sh killed the session itself and recorded
    # `exit=124 runner_code=?`. The RUNNER never returned a code, so the
    # runner_code=124 exemption above cannot see it, and the release was charged
    # as empty -- doubling the subject's cooldown for the dispatcher's fault.
    # The session was alive at 211s when it was killed and the spend record was
    # unmapped (AMBIGUOUS, 4 candidate sessions), which is a cost-mapping
    # failure, not evidence about the subject. Same doctrine as rc=124 above:
    # never charge the bound -- here the dispatcher's own lease -- to the subject.
    # The outcome text is wake-dispatch.sh's own self-kill verdict.
    if "lease heartbeat" in outcome.lower() and "killed" in outcome.lower():
        return False, ("COULD NOT ASK: the dispatcher's own lease heartbeat was lost "
                       f"and it killed the session ({len(outcome)} char(s) of output) - "
                       "not evidence about the subject, so holding instead of raising")

    if exit_code != 0:
        return True, (f"exit={event.get('exit')} (runner_code="
                      f"{event.get('runner_code')}), outcome {len(outcome)} char(s)")
    if not outcome:
        return True, "exit=0 but the release recorded no outcome at all"
    return False, f"exit=0, outcome {len(outcome)} char(s)"


def judge(releases: list[dict], costs: dict[int, dict],
          events: list[dict]) -> dict:
    """The tuner's whole decision, as data -- so the digest can print it."""
    base = _int("WAKE_TUNER_BASE_COOLDOWN_SEC", 1800)
    cap = _int("WAKE_TUNER_MAX_COOLDOWN_SEC", 604800)
    disable_n = _int("WAKE_TUNER_EMPTY_DISABLE_N", 3)
    chars = _int("WAKE_TUNER_REAL_WORK_CHARS", 200)
    lookback = _int("WAKE_TUNER_LOOKBACK", 5)

    by_id = {int(row["id"]): row for row in releases}
    last_row: dict[str, dict] = {}
    for row in releases:
        last_row[str(row.get("subject"))] = row            # releases are id-ordered

    unreadable_log_lines = sum(int(e.get("unreadable_lines") or 0)
                               for e in events if "unreadable_lines" in e)
    real_events = [e for e in events if "release_id" in e]

    # THE RELEASE STREAM is the log: one entry per release, oldest first, each
    # with its own verdict. This is the only place "consecutive" is knowable.
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for event in real_events:
        by_subject[subject_of(event, by_id)].append(event)

    subjects: dict[str, dict] = {}
    for subject, stream in sorted(by_subject.items()):
        stream = sorted(stream, key=lambda e: e.get("at") or "")
        streak = 0
        for event in reversed(stream):
            empty, _why = log_event_empty(event, costs)
            if not empty:
                break
            streak += 1
        window = stream[-lookback:]
        empties_in_window = sum(
            1 for event in window if log_event_empty(event, costs)[0])
        newest = stream[-1]
        newest_empty, newest_why = log_event_empty(newest, costs)
        newest_id = int(newest.get("release_id") or 0)
        spend = costs.get(newest_id)
        current_row = by_id.get(newest_id) or last_row.get(subject) or {}
        real, real_why = is_real_work(current_row, spend, chars)
        current = min(base * (streak + 1) if streak else base, cap)

        action, rule, reason = "hold", "R0", "inside the base cooldown; nothing changed"
        if streak >= disable_n:
            action, rule = "disable", "R3"
            reason = (f"{streak} consecutive empty releases >= WAKE_TUNER_EMPTY_DISABLE_N="
                      f"{disable_n}; newest: {newest_why}")
        elif streak:
            action, rule = "raise", "R2"
            reason = (f"{streak} consecutive empty release(s) (newest: {newest_why});"
                      f" cooldown {base}s -> {current}s = base*(N+1), cap {cap}s")
        elif newest_empty:
            action, rule, reason = "hold", "R1", f"newest release empty: {newest_why}"
        elif real and empties_in_window == 0 and len(stream) >= 2:
            action, rule = "shorten", "R4"
            reason = (f"real work ({real_why}); 0 empties in the last {len(window)} "
                      f"release(s); cooldown back to the base {base}s")
        elif real:
            action, rule, reason = "hold", "R4", (
                f"real work ({real_why}) but {empties_in_window} empty release(s) "
                f"in the last {len(window)}; nothing to shorten yet")

        subjects[subject] = {
            "releases_in_log": len(stream),
            "empty_streak": streak,
            "empties_in_last_lookback": empties_in_window,
            "current_cooldown_sec": current,
            "proposed_cooldown_sec": cap if action == "disable" else current,
            "action": action,
            "rule": rule,
            "reason": reason,
            "newest_release_logged_at": newest.get("at"),
            "newest_state": current_row.get("state"),
            "disabled": action == "disable",
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    todays = [row for row in releases
              if (_flag.parse_dt(row.get("claimed_at")) or datetime.min.replace(
                  tzinfo=timezone.utc)).strftime("%Y-%m-%d") == today]
    spend_rows = [costs.get(int(r["id"])) for r in todays]
    priced = [s for s in spend_rows if s and isinstance(
        s.get("cost_usd_or_unsourced"), (int, float))]
    unsourced = [s for s in spend_rows if s and s.get("cost_usd_or_unsourced") == "unsourced"]

    top = sorted(
        [s for s in spend_rows if s],
        key=lambda s: (int(s.get("total_tokens") or 0)), reverse=True)[:3]

    # The dispatcher's verdict versus the session's actual work. Measured
    # 2026-09-20: releases #8/#9/#10 are all `failed` with rc=124 on the ssh hop,
    # and all three sessions burned 5.3M-9.7M tokens. This is an ssh/desktop
    # fault; it must be named so nobody mutes a subject for the network's fault.
    faults = []
    for row in releases:
        if (row.get("state") or "") not in ("failed", "expired"):
            continue
        spend = costs.get(int(row["id"])) or {}
        tokens = int(spend.get("total_tokens") or 0)
        if tokens > 0:
            faults.append({"release_id": row["id"], "subject": row.get("subject"),
                           "state": row.get("state"), "tokens": tokens,
                           "session_id": spend.get("session_id")})

    return {
        "day": today,
        "releases_total": len(releases),
        "releases_logged": len(real_events),
        "unreadable_log_lines": unreadable_log_lines,
        "releases_today": len(todays),
        "tokens_today": sum(int((s or {}).get("total_tokens") or 0) for s in spend_rows),
        "cost_today": ("unsourced" if (unsourced and not priced)
                       else round(sum(float(s.get("cost_usd_or_unsourced") or 0.0)
                                      for s in priced), 6)),
        "priced_today": len(priced),
        "unsourced_today": len(unsourced),
        "failed_with_real_work": faults,
        "top_spenders": [{
            "release_id": s.get("release_id"),
            "subject": s.get("subject"),
            "tokens": int(s.get("total_tokens") or 0),
            "cost_usd_or_unsourced": s.get("cost_usd_or_unsourced"),
            "cost_confidence": (s.get("cost_confidence") or "")[:120],
        } for s in top],
        "per_source_last_hour": per_source_last_hour(releases),
        "subjects": subjects,
        "thresholds": {
            "base_cooldown_sec": base, "max_cooldown_sec": cap,
            "empty_disable_n": disable_n, "real_work_chars": chars,
            "lookback": lookback,
        },
    }


def changed_subjects(judgement: dict, previous: dict) -> list[dict]:
    """Subjects whose ACTION moved since the last run.

    `hold` transitions never appear: on a first run every subject is "new" and
    reporting nine holds would be nine sessions for no change at all. A change is
    a raise, a shorten or a disable -- something a person or a session must read.
    """
    before = ((previous or {}).get("subjects") or {})
    out = []
    for subject, state in sorted(judgement["subjects"].items()):
        old = before.get(subject) or {}
        if state["action"] == "hold":
            continue
        if (state["action"] != old.get("action")
                or state["proposed_cooldown_sec"] != old.get("proposed_cooldown_sec")):
            out.append({"subject": subject, "from": old.get("action", "(first run)"),
                        "to": state["action"], "rule": state["rule"],
                        "proposed_cooldown_sec": state["proposed_cooldown_sec"],
                        "reason": state["reason"]})
    return out


def _merge_changes(carried: list, current: list) -> list:
    """Every change that has not yet been reported, oldest first, ONE entry per subject.

    A subject that moved twice before either movement was reported is reported once, with its
    LATEST state - reporting the intermediate step would be noise, and reporting both would be the
    same mistake this fix exists to end.
    """
    out: dict = {}
    for change in list(carried) + list(current):
        if isinstance(change, dict) and change.get("subject"):
            out[change["subject"]] = change
    return [out[k] for k in sorted(out)]


def _changes_section(changes: list) -> str:
    """The carried changes, rendered for the ONE daily digest instead of N separate sessions."""
    if not changes:
        return ""
    lines = ["", "", "THRESHOLD CHANGES SINCE THE LAST DIGEST", "-" * 40,
             f"{len(changes)} subject(s) moved. Each is applied through the state file; this is",
             "the review, not the change:"]
    for c in changes:
        lines += [
            "",
            f"  {c['subject']}",
            f"    rule ............... {c.get('rule')}",
            f"    action ............. {c.get('from')} -> {c.get('to')}",
            f"    proposed cooldown .. {c.get('proposed_cooldown_sec')}s",
            f"    why ................ {c.get('reason')}",
        ]
    lines += [
        "",
        "FOR EACH: confirm it against `~/.sms-inbox/wake-cost.jsonl` and the `wake` table",
        "(`sqlite3 -readonly ~/.sms-inbox/inbox.db \"select id,subject,state,claimed_at,",
        "substr(outcome,1,80) from wake\"`). If a DISABLE is correct, say so in one line and",
        "leave the record; if the emptiness was the DISPATCHER's fault rather than the subject's,",
        "say that instead and do not mute the subject.",
        "Do NOT edit wake.py / wake-dispatch.sh / run-wake-sources.sh / cron.",
    ]
    return "\n".join(lines)


def digest_text(judgement: dict, changes: list[dict], caps: dict, gaps: list[str]) -> str:
    lines = [f"WAKE COST DIGEST — {judgement['day']} (UTC)",
             "=" * 58,
             f"releases today ...... {judgement['releases_today']} "
             f"(store rows: {judgement['releases_total']}, "
             f"logged releases: {judgement['releases_logged']})",
             f"tokens today ........ {judgement['tokens_today']}",
             f"cost today .......... "
             + ("unsourced" if judgement["cost_today"] == "unsourced"
                else f"${judgement['cost_today']:.6f}")
             + f"  ({judgement['priced_today']} priced, "
               f"{judgement['unsourced_today']} unsourced)"]
    # WHICH COST IS WHICH. Two numbers for one day existed on 2026-09-29 and nothing said
    # which to believe: this digest read its own periodic snapshot (0.997373 over 37 priced
    # releases) while the live sum over the per-release rows read 1.224594 over 41. The gap
    # is staleness, not arithmetic - and two independent sums of one file is how they drifted
    # apart, so the fix is to NAME THE AUTHORITY rather than add a third sum here.
    lines.append("cost source ....... the wake-cost.py snapshot row for this day, AS OF when that"
                 " row was last written - a periodic snapshot, not a live figure")
    lines.append("AUTHORITATIVE ..... the live sum over the per-release rows is what the 70"
                 " USD/day cap enforces: `python3 ~/bin/wake.py stats --json` ->"
                 " spend_today_usd. Never quote either without naming which.")
    if gaps:
        lines.append("MISSING SIGNAL ...... " + "; ".join(gaps))
    if judgement.get("unreadable_log_lines"):
        lines.append(f"PARTIAL SIGNAL ...... {judgement['unreadable_log_lines']} release"
                     " line(s) in wake-dispatch.log could not be parsed (the"
                     " dispatcher truncates its last line when it is killed), so the"
                     " streak counts below may understate by that many releases")
    if not judgement["top_spenders"]:
        lines.append("top spenders ........ (none: no release today has a cost row)")
    else:
        lines.append("top spenders (by tokens):")
        for i, entry in enumerate(judgement["top_spenders"], 1):
            cost = entry["cost_usd_or_unsourced"]
            shown = f"${cost:.6f}" if isinstance(cost, (int, float)) else "unsourced"
            lines.append(f"  {i}. #{entry['release_id']} {str(entry['subject'])[:34]:<34} "
                         f"{entry['tokens']:>9} tok  {shown}")
    lines.append("")
    lines.append(f"thresholds .......... base cooldown {caps.get('cooldown_sec')}s, "
                 f"max/day {caps.get('max_per_day')}, "
                 f"max/source/hour {caps.get('max_per_source_per_hour')}, "
                 f"max/attempts {caps.get('max_attempts')}, "
                 f"night quiet {caps.get('night_quiet')}")
    over = [f"{src} {n}/{caps.get('max_per_source_per_hour')}"
            for src, n in sorted(judgement["per_source_last_hour"].items())
            if caps.get("max_per_source_per_hour")
            and n >= int(caps["max_per_source_per_hour"])]
    lines.append("caps ............... " + ("; ".join(over) if over
                                           else "no source at its hourly cap"))
    if not over and judgement["per_source_last_hour"]:
        lines.append("                     last hour: " + ", ".join(
            f"{k}={v}" for k, v in sorted(judgement["per_source_last_hour"].items())))
    lines.append("")
    if not changes:
        lines.append("thresholds changed .. none (every subject is where the record says it should be)")
    else:
        lines.append("thresholds changed:")
        for change in changes:
            lines.append(f"  {change['subject']}")
            lines.append(f"      {change['from']} -> {change['to']} "
                         f"(rule {change['rule']}, cooldown "
                         f"{change['proposed_cooldown_sec']}s)")
            lines.append(f"      why: {change['reason']}")
    held = [s for s, st in sorted(judgement["subjects"].items()) if st["action"] == "hold"]
    if held:
        lines.append(f"held ................ {len(held)} subject(s) unchanged")
    dispatcher_faults = judgement.get("failed_with_real_work") or []
    if dispatcher_faults:
        lines.append("")
        lines.append("DISPATCHER FAULT (not the subject's): these releases are recorded")
        lines.append("`failed` by the dispatcher, yet their sessions really ran and burned")
        lines.append("tokens -- the ssh hop lost the answer, so backing the subject off")
        lines.append("would hide the fault instead of fixing it:")
        for entry in dispatcher_faults:
            lines.append(f"  #{entry['release_id']} {str(entry['subject'])[:38]:<38} "
                         f"{entry['tokens']:>9} tok  state={entry['state']}")
    lines.append("")
    disabled = [s for s, st in sorted(judgement["subjects"].items()) if st["disabled"]]
    lines.append("disabled subjects ... " + (", ".join(disabled) if disabled else "none"))
    if judgement["unsourced_today"] and not judgement["priced_today"]:
        lines.append("")
        lines.append("NOTE: every release today is UNPRICED. The token totals above are")
        lines.append("real; the dollars are not claimable, because no record on this mesh")
        lines.append("says which (provider, model) a wake session ran on, and the two pipes")
        lines.append("for the same model differ 5.5x. Bind a rate in")
        lines.append("~/.sms-inbox/wake-cost-prices.json or run wake-cost.py with")
        lines.append("--rate-from-ledger to price them from the app's own billing ledger.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# (3) the source
# --------------------------------------------------------------------------- #
def collect(args) -> list[Finding]:
    releases = read_releases()
    events = read_dispatch_log()
    costs, gaps = cost_index()
    caps = _caps()
    judgement = judge(releases, costs, events)
    previous = read_json(state_path(), {})
    force = bool(getattr(args, "force", False))
    already = (previous or {}).get("digest_day")
    changes = changed_subjects(judgement, previous)
    # EVERYTHING UNREPORTED, not just this run: see _merge_changes. The tuner runs every 15
    # minutes and persist() absorbs each movement immediately, so a movement is visible to
    # exactly one run - without this carry, anything moving after the day's digest would
    # never be reported at all.
    pending = _merge_changes((previous or {}).get("changes_unreported") or [], changes)

    if getattr(args, "print_digest", False) or force or already != judgement["day"]:
        text = digest_text(judgement, changes, caps, gaps)
        print(text)
    else:
        print(f"wake-tuner: digest for {judgement['day']} already emitted "
              f"(state {state_path()})", file=sys.stderr)

    if not force and already == judgement["day"]:
        # ONE RELEASE PER DAY. This used to still emit one flag per changed subject, which
        # is how one day cost 13 sessions. If the day's digest has gone out, this run emits
        # nothing; whatever moved is carried in the state file and reported in tomorrow's
        # digest. Nothing is lost, because the change itself is already applied through the
        # state file - the flag is only the REVIEW.
        return []

    findings: list[Finding] = []
    digest = digest_text(judgement, changes, caps, gaps)
    findings.append(Finding(
        subject=f"wake-cost-digest:{judgement['day'].replace('-', '')}",
        prompt="\n".join([
            "The daily wake-cost watchdog ran. This is the whole owner-readable",
            "digest it produced, verbatim:",
            "",
            "```",
            digest,
            "```",
            "",
            "WHAT TO DO (this is a judgement task, not a formatting task)",
            "1. Read `~/.sms-inbox/wake-cost.jsonl`. A release whose",
            "   `cost_usd_or_unsourced` is the string `unsourced` means the rate OR",
            "   the (provider, model) the turn ran on could not be sourced. DO NOT",
            "   invent a rate. If the operator can bind a price, write",
            "   `~/.sms-inbox/wake-cost-prices.json` with provider, model,",
            "   input_usd_per_mtok, output_usd_per_mtok and a `source` string, then",
            "   re-run `python3 ~/bin/wake-cost.py`.",
            "2. For every subject the tuner DISABLED (named in the digest): the",
            "   disable is recorded in this state file, not written to the store.",
            "   Decide with evidence whether the subject deserves a third chance or",
            "   a permanent mute, and say which and why.",
            "3. For every R1/R2 raise: check whether the emptiness is the SUBJECT's",
            "   fault or the DISPATCHER's (releases #8/#9/#10 on 2026-09-20 were",
            "   rc=124 ssh timeouts with no session at all -- that is an ssh/desktop",
            "   fault, not a bad subject, and backing the subject off would hide it).",
            "4. Report spend in ONE line and one change you made, with its proof.",
            "",
            "Do NOT edit `wake.py`, `wake-dispatch.sh`, `run-wake-sources.sh` or",
            "cron from that session. Do NOT contact the owner or any customer.",
            "Report at the end: what the record shows, what you changed, what is",
            "still unpriced.",
        ]) + _changes_section(pending),
        context=(f"{SOURCE}: {judgement['releases_today']} release(s) today, "
                 f"{judgement['tokens_today']} token(s), "
                 f"cost={'unsourced' if judgement['cost_today'] == 'unsourced' else judgement['cost_today']}, "
                 f"{len(changes)} threshold change(s), "
                 f"{judgement['unsourced_today']} unsourced"),
        priority="normal",
        kind="repair",
        cooldown_seconds=_int("WAKE_TUNER_MAX_COOLDOWN_SEC", 604800),
    ))

    # NO PER-SUBJECT FINDINGS. This loop used to emit one `wake-cost-tune:<subject>` flag per
    # changed subject, and a flag is a whole headless session: 12 of them on 2026-09-29. The
    # changes are carried into the single daily digest by _changes_section(pending) above.
    return findings


def _caps() -> dict:
    """The caps actually in force, from the live CLI. Never hard-coded here."""
    import subprocess
    cli = _flag.wake_cli()
    if not cli.is_file():
        return {"readable": False, "why": f"no wake CLI at {cli}"}
    try:
        proc = subprocess.run([sys.executable, str(cli), "stats", "--json"],
                              capture_output=True, text=True, timeout=60)
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
        caps = dict(payload.get("caps") or {})
        caps["released_today"] = payload.get("released_today")
        caps["spend_today_usd"] = payload.get("spend_today_usd")
        caps["caps_in_force"] = payload.get("caps_in_force")
        return caps
    except Exception as exc:                                       # noqa: BLE001
        return {"readable": False, "why": f"{type(exc).__name__}: {exc}"}


def persist(judgement: dict, changes: list[dict], dry_run: bool,
            unreported: list | None = None) -> Path | None:
    """Remember the day and the last judgement, so a re-run changes nothing."""
    if dry_run:
        return None
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_json(path, {})
    payload = {
        "version": 1,
        "digest_day": judgement["day"],
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thresholds": judgement["thresholds"],
        "releases_total": judgement["releases_total"],
        "subjects": judgement["subjects"],
        "changes_this_run": changes,
        # What the digest has NOT yet told anyone. Reported in the next digest rather than
        # in a session of its own.
        "changes_unreported": list(unreported or []),
        "history": (previous.get("history") or [])[-30:] + [{
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "day": judgement["day"],
            "changes": changes,
            "releases_today": judgement["releases_today"],
            "tokens_today": judgement["tokens_today"],
            "cost_today": judgement["cost_today"],
            "unsourced_today": judgement["unsourced_today"],
        }],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=f"wake source: {SOURCE}")
    parser.add_argument("--dry-run", action="store_true",
                        help="print findings; write nothing (no flag, no state)")
    parser.add_argument("--force", action="store_true",
                        help="emit the digest even if it was already emitted today")
    parser.add_argument("--print-digest", action="store_true",
                        help="print the digest to stdout whatever else happens")
    parser.add_argument("--json", action="store_true",
                        help="print the judgement as JSON instead")
    args = parser.parse_args(argv)

    if args.json:
        try:
            releases = read_releases()
            events = read_dispatch_log()
            costs, gaps = cost_index()
        except Unreadable as exc:
            print(json.dumps({"ok": False, "error": "unreadable", "why": str(exc)}))
            return 1
        judgement = judge(releases, costs, events)
        print(json.dumps({"ok": True, "gaps": gaps, "judgement": judgement,
                          "caps": _caps()}, indent=2, sort_keys=True))
        return 0

    try:
        findings = collect(args)
    except Unreadable as exc:
        print(f"{SOURCE}: SIGNAL UNREADABLE -- {exc}", file=sys.stderr)
        return 1
    except Exception as exc:                                   # noqa: BLE001
        print(f"{SOURCE}: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    landed = 0
    for finding in findings:
        result = _flag.flag(finding, SOURCE, dry_run=args.dry_run)
        if result in ("filed", "deduped", "dry-run"):
            print(f"flagged {finding.subject}")
            landed += 1
        if result not in ("filed", "dry-run"):
            print(f"({finding.subject}: {result})", file=sys.stderr)

    # Persist AFTER the flags land: a state file that claimed a day the store
    # never heard about would silence tomorrow's digest for no reason.
    try:
        releases = read_releases()
        events = read_dispatch_log()
        costs, _gaps = cost_index()
        judgement = judge(releases, costs, events)
        previous = read_json(state_path(), {})
        changes = changed_subjects(judgement, previous)
        # The same decision collect() makes, recomputed here because main() re-derives the
        # judgement independently: if the digest went out this run, its carried set is spent;
        # if it did not, everything unreported stays carried for tomorrow.
        _pending = _merge_changes(previous.get("changes_unreported") or [], changes)
        _emitted = (bool(getattr(args, "force", False))
                    or previous.get("digest_day") != judgement["day"])
        written = persist(judgement, changes, args.dry_run,
                          unreported=[] if _emitted else _pending)
        if written:
            print(f"state: {written}", file=sys.stderr)
    except Unreadable as exc:
        print(f"{SOURCE}: state not persisted -- {exc}", file=sys.stderr)
        return 1

    if not landed:
        print("quiet")
    if args.dry_run:
        print(f"(dry-run: {len(findings)} finding(s), nothing written)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
