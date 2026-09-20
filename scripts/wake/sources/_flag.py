#!/usr/bin/env python3
"""Shared plumbing for the wake sources. Stdlib only.

WHAT A SOURCE IS
----------------
A source is a judge. It reads ONE signal on the authority and decides whether
that signal means there is work a live agent session must do. It then calls the
frozen `flag` CLI (see ../CONTRACT.md section 5) or it stays quiet.

Every source is a potential session factory, so the bar is not "does it detect
something" but "does it detect something ABNORMAL". A source that fires on the
normal, healthy case has failed even if it works.

THE OUTPUT CONTRACT (section 7 of the contract)
-----------------------------------------------
stdout is exactly one of:
    quiet                       -- this source filed nothing
    flagged <subject>           -- one line per flag the store accepted
Nothing else is ever written to stdout. Everything diagnostic goes to stderr,
so a cron line like `python3 sources/x.py >> log 2>&1` keeps a clean channel.

`quiet` means "this source filed nothing", NOT "the world is healthy". If the
signal was abnormal but the wake store refused the row (a cap, the pause file,
the cooldown), stdout says `quiet` and stderr names the refusal -- `wake.py
stats` is where caps are read. That is the one place this vocabulary is lossy,
and it is deliberate: the two words above are frozen and three other workstreams
grep for them.

EXIT CODES
----------
    0   the signal was read and a decision was made (filed or quiet)
    1   the signal could NOT be read (missing DB, no journalctl, no permission)

Exit 1 exists so a broken signal can never masquerade as a healthy one. It is
still cron-safe: one line on stderr, never a traceback.

ENVIRONMENT
-----------
    WAKE_PY            path to the frozen flag CLI   (default ~/bin/wake.py)
    SMS_INBOX_DB       the text store                (default ~/.sms-inbox/inbox.db)
    SMS_INBOX_APP_DB   the app's database            (default the mvp path)
    OWNER_QUEUE_DB     overrides SMS_INBOX_APP_DB for the queue sources
    SECRETARY_API_UNIT systemd unit for the app      (default secretary-api)

Every threshold in every source is env-overridable too, with the measured
default documented in that source's header.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class Unreadable(Exception):
    """The signal could not be read at all. Never silently becomes 'quiet'."""


# --------------------------------------------------------------------------- #
# paths and settings
# --------------------------------------------------------------------------- #
def wake_cli() -> Path:
    return Path(os.environ.get("WAKE_PY") or (HOME / "bin" / "wake.py"))


def inbox_db() -> Path:
    return Path(os.environ.get("SMS_INBOX_DB")
                or (HOME / ".sms-inbox" / "inbox.db"))


def app_db() -> Path:
    """The app database, honouring the name owner-queue.py already uses."""
    return Path(os.environ.get("OWNER_QUEUE_DB")
                or os.environ.get("SMS_INBOX_APP_DB")
                or (HOME / "personal-secretary-mvp" / "data" / "secretary.db"))


def app_unit() -> str:
    return os.environ.get("SECRETARY_API_UNIT") or "secretary-api"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# reading, read-only, always
# --------------------------------------------------------------------------- #
def ro_connect(path: Path) -> sqlite3.Connection:
    """Open a database strictly read-only.

    Read-only on purpose: a source is a sensor, and a sensor that can write the
    thing it watches is a sensor that can corrupt it. uri mode=ro also means a
    missing or locked database is an error here rather than a surprise write.
    """
    if not path.is_file():
        raise Unreadable(f"no database at {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise Unreadable(f"cannot open {path}: {exc}") from exc


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def parse_dt(raw: str | None) -> datetime | None:
    """Parse the several timestamp shapes this system really writes.

    Seen in the wild: '2026-09-14T15:46:26.942714+00:00',
    '2026-09-15T17:17:28' (naive), 'Fri, 18 Sep 2026 03:03:12 +0000'
    (Twilio's RFC-2822 form) and journalctl's `+0000` (no colon, which
    `fromisoformat` only learned to accept in Python 3.11). A naive value is read
    as UTC.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            value = parsedate_to_datetime(text)
        except Exception:                                     # noqa: BLE001
            return None
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def unit_exists(unit: str) -> bool:
    """Whether systemd knows this unit at all.

    Needed because `journalctl` cannot tell "no matching entries" from "no such
    unit" on its own: measured on secratary 2026-09-18, BOTH return rc=1, empty
    stderr, and either empty stdout or `-- No entries --`. A source that
    mistook a typo'd unit name for a quiet signal would report a false all-clear,
    which is the one thing a sensor must never do. `LoadState` answers `loaded`
    or `not-found` for both cases, with rc=0 either way.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "show", "-p", "LoadState", "--value", unit],
            capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True          # cannot tell: never turn a working host into an error
    state = (proc.stdout or "").strip()
    return state != "not-found"


# Markers that mean journalctl could not READ, as opposed to found nothing.
_JOURNAL_UNREADABLE = ("No journal files", "Permission denied", "Access denied",
                       "Failed to open", "Cannot open", "Not permitted")


def journal_grep(unit: str, since: datetime, pattern: str,
                 timeout: int = 60) -> list[str]:
    """Lines from the unit's journal matching `pattern`, newest last.

    `--grep` is used rather than reading the whole journal into Python and
    filtering: the measured cost of `--grep` on a 24 h window here is 381 ms,
    against 18 MB / 128k lines for the unfiltered read.

    An empty list is the healthy answer, and journalctl signals it with rc=1 --
    so rc=1 is NOT an error here. Only a genuine read failure raises.
    """
    if not unit_exists(unit):
        raise Unreadable(f"systemd unit {unit} is not loaded (LoadState=not-found)")
    cmd = ["journalctl", "-u", unit, "--no-pager", "-o", "short-iso", "--utc",
           "--since", since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
           "--grep", pattern]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise Unreadable(f"journalctl not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise Unreadable(f"journalctl timed out after {timeout}s") from exc
    if proc.returncode != 0:
        blob = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        for marker in _JOURNAL_UNREADABLE:
            if marker in blob:
                raise Unreadable(
                    f"journalctl could not read {unit}'s journal: {marker}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


_JOURNAL_STAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
)


def journal_stamp(line: str) -> datetime | None:
    """The leading timestamp of a `short-iso` journal line, as UTC."""
    match = _JOURNAL_STAMP.match(line)
    if not match:
        return None
    date_part, time_part, offset = match.groups()
    text = f"{date_part}T{time_part}{offset or '+00:00'}"
    if offset == "Z":
        text = f"{date_part}T{time_part}+00:00"
    return parse_dt(text)


# --------------------------------------------------------------------------- #
# the flag call
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    """One thing this source believes deserves a session."""
    subject: str
    prompt: str
    priority: str = "normal"
    kind: str = "task"
    context: str = ""
    cooldown_seconds: int | None = None


def flag(finding: Finding, source: str, dry_run: bool = False) -> str:
    """Call the frozen `flag` CLI and return its word.

    Returns one of `filed` / `deduped` / `suppressed:<reason>` / `capped`, or
    `dry-run` when nothing was written. A flag call that cannot be made at all
    (no CLI yet, a usage error, a traceback) returns `suppressed:error` -- it
    NEVER raises, because a flag must not be able to break its caller.
    """
    if dry_run:
        return "dry-run"
    cli = wake_cli()
    if not cli.is_file():
        print(f"wake cli not found at {cli} (set WAKE_PY)", file=sys.stderr)
        return "suppressed:error"
    cmd = [sys.executable or "python3", str(cli), "flag",
           "--subject", finding.subject,
           "--prompt", finding.prompt,
           "--kind", finding.kind,
           "--source", source,
           "--priority", finding.priority,
           "--context", finding.context,
           "--json"]
    if finding.cooldown_seconds is not None:
        cmd += ["--cooldown-seconds", str(int(finding.cooldown_seconds))]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:                                   # noqa: BLE001
        print(f"flag call failed: {exc}", file=sys.stderr)
        return "suppressed:error"
    raw = (proc.stdout or "").strip()
    if raw:
        try:
            payload = json.loads(raw.splitlines()[-1])
            result = str(payload.get("result") or "")
            if result:
                return result
        except Exception:                                      # noqa: BLE001
            # A CLI that does not speak --json yet still prints the bare word.
            word = raw.splitlines()[-1].strip()
            if word in ("filed", "deduped", "capped") or word.startswith("suppressed"):
                return word
    detail = (proc.stderr or "").strip().splitlines()
    print("flag call returned nothing usable (rc=%s)%s"
          % (proc.returncode, ": " + detail[-1][:200] if detail else ""),
          file=sys.stderr)
    return "suppressed:error"


# --------------------------------------------------------------------------- #
# the runner every source uses
# --------------------------------------------------------------------------- #
def run(source: str, collect) -> int:
    """Parse argv, gather findings, file them, print the frozen one-liner(s).

    `collect(args)` returns a list of Finding. It may raise Unreadable.
    """
    parser = argparse.ArgumentParser(
        description=f"wake source: {source}",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be flagged; change nothing")
    args = parser.parse_args()

    try:
        findings = collect(args)
    except Unreadable as exc:
        print(f"{source}: SIGNAL UNREADABLE -- {exc}", file=sys.stderr)
        return 1
    except Exception as exc:                                   # noqa: BLE001
        print(f"{source}: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    landed = 0
    for finding in findings:
        result = flag(finding, source, dry_run=args.dry_run)
        if result in ("filed", "deduped", "dry-run"):
            print(f"flagged {finding.subject}")
            landed += 1
        if result not in ("filed", "dry-run"):
            # stdout stays frozen to the two words the contract allows; the
            # store's own decision is reported on stderr so an operator can see
            # the difference between "I filed it" and "it was already there".
            print(f"({finding.subject}: {result})", file=sys.stderr)

    if not landed:
        print("quiet")
    if args.dry_run:
        print(f"(dry-run: {len(findings)} finding(s), nothing written)",
              file=sys.stderr)
    return 0
