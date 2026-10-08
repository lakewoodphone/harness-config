#!/usr/bin/env python3
"""FLAG SOURCE: work that went quiet. The thing that was missing on 2026-09-20.

THE SIGNAL
----------
Two independent ones, because "unfinished" has two shapes on this system:

  (A) THE NEWEST HANDOFF IS OLD. `~/harness-config/journal/entries/handoff/H*.md`
      highest id, its date parsed from its own metadata header. A handoff whose
      newest entry is older than DORMANT_DAYS means the record of "what is in
      flight and what is next" has not moved in that long. Either the work
      stopped, or it finished and nobody said so — and both need a session.

  (B) THE SESSION ARCHIVE HAS STOPPED ADVANCING. `~/dsh-archive/dsh-archive.db`,
      `max(updated_at)` in `dsh_sessions`. That pipeline exists so that "no
      conversation is ever only on one laptop" (its own header). When it stalls,
      every session since is single-homed and invisible to the authority, and
      NOTHING reports it — an absence that looks exactly like quiet.

WHY THIS EXISTS, IN THE OWNER'S WORDS (2026-09-20)
--------------------------------------------------
    "I don't want to ever see this level of stalling again … the whole point of
     you being truly autonomous is you being able to reactivate yourself. I don't
     want to have to keep monitoring you enforcing you back to work."

He is right, and the mechanism is specific: work was finished in-session, the
session ended, and NO FLAG WAS RAISED, so the always-on half never knew there was
anything left. `wake.py` could always have revived it; nothing told it to. This
source is the thing that tells it.

PRIORITY  normal. This is not an emergency; it is the difference between a system
that waits to be poked and one that resumes itself.

SUBJECTS  dormant-handoff:<Hid>            dedup keyed to the ENTRY IDENTITY, so
                                           one session per handoff, and the next
                                           handoff becomes a new key.
          dormant-archive:<YYYYMMDD>       keyed to the day the archive was last
                                           written, so it re-files if the stall
                                           persists but not more than once a day.

MUST NEVER
    - fire because something MIGHT be unfinished. It fires on a measured age and
      a measured absence, and the prompt tells the session to decide, with
      evidence, whether there is work — and to CLOSE the record if there is not.
    - treat a quiet journal as health. A journal nobody writes to is the failure
      this source is looking for, not the absence of one.
    - raise a flag from inside a woken session (the store refuses that itself).

RUN
    python3 sources/dormant-handoff.py [--dry-run]
    DORMANT_HANDOFF_DAYS=3          age that makes the in-flight record dormant
    DORMANT_ARCHIVE_HOURS=48        staleness that makes the archive a fault
    DORMANT_COOLDOWN_SEC=259200     re-file floor after a release (3 days)
    HARNESS_REPO                    the harness checkout (default ~/harness-config)
    DSH_ARCHIVE_DB                  the session archive (default ~/dsh-archive/dsh-archive.db)
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "dormant-handoff"
HEADER_RE = re.compile(r"<!--\s*e:([a-z]+)\|([A-Z]+\d+)\|([^|]*)\|([^|]*)\|([^-]*)-*\s*-->")
NEXT_RE = re.compile(r"\*\*NEXT\*\*(.*?)(?=\*\*[A-Z]+\*\*|\Z)", re.S)


def _num(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env) or default)
    except ValueError:
        return default


def _repo() -> Path:
    return Path(os.environ.get("HARNESS_REPO") or (Path.home() / "harness-config"))


def _parse_stamp(raw: str):
    """Parse the date out of an entry's metadata header.

    THE HEADERS ARE NOT ISO. Measured 2026-09-20: `<!-- e:handoff|H479|2026-09-17 16:15 UTC|... -->`
    carries a trailing ` UTC` that `_flag.parse_dt` does not accept, and the first version of this
    source correctly refused to guess — it printed `SIGNAL UNREADABLE` rather than treating an
    unparsed date as fresh, which is the behaviour every probe on this mesh is required to have.
    So: try the raw value, then the obvious normalisations, and return None if none parse.
    """
    for cand in (
        raw,
        raw.replace(" UTC", "Z").replace(" ", "T", 1) if raw.endswith("UTC") else raw,
        raw.replace(" UTC", "+00:00").replace(" ", "T", 1) if raw.endswith("UTC") else raw,
        raw.replace("Z", "+00:00"),
    ):
        got = _flag.parse_dt(cand)
        if got is not None:
            return got
    return None


def _newest_handoff(repo: Path):
    """The highest-numbered handoff AS OF origin/master — never the working tree.

    WHY GIT AND NOT THE DIRECTORY, and it is the same lesson that cost two patches on 2026-09-18
    (journal L2066): a clone is not the truth. The authority's own checkout is dozens of commits
    behind, and this source's first dry run duly read `H479` from 2026-09-17 as the newest handoff
    while handoffs H603 existed upstream — it would have raised a flag about the wrong work, every
    time, while looking exactly right on the machine it ran on. `origin/master` is the base.
    """
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout

    git("fetch", "origin", "-q")           # bounded; failure leaves origin/master as it was
    listing = git("ls-tree", "-r", "--name-only", "origin/master", "--", "journal/entries/handoff")
    names = [ln.strip() for ln in listing.splitlines() if ln.strip()]
    if not names:
        raise Unreadable(f"no handoff entries on origin/master in {repo}")
    best = None
    for path in names:
        m = re.search(r"/(H(\d+))\.md$", path)
        if not m:
            continue
        n = int(m.group(2))
        if best is None or n > best[0]:
            best = (n, m.group(1), path)
    if best is None:
        raise Unreadable(f"no H<n>.md entries under journal/entries/handoff on origin/master")
    n, hid, path = best
    text = git("show", f"origin/master:{path}")
    if not text.strip():
        raise Unreadable(f"origin/master:{path} is empty")
    first = text.splitlines()[0] if text else ""
    hm = HEADER_RE.match(first.strip())
    if hm is None:
        raise Unreadable(f"{hid}: metadata header not parseable: {first[:80]!r}")
    stamp = _parse_stamp(hm.group(3).strip())
    if stamp is None:
        raise Unreadable(f"{hid}: unparseable date {hm.group(3)!r}")
    nm = NEXT_RE.search(text)
    nxt = (nm.group(1).strip() if nm else "")[:1500]
    return {"id": hid, "path": path, "at": stamp, "status": hm.group(5).strip(), "next": nxt, "text": text}


def _archive_lag_hours(db: Path) -> float:
    if not db.exists():
        raise Unreadable(f"no session archive at {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT MAX(updated_at) FROM dsh_sessions").fetchone()
        n = conn.execute("SELECT COUNT(*) FROM dsh_sessions").fetchone()[0]
    finally:
        conn.close()
    if not row or not row[0]:
        raise Unreadable("dsh_sessions.updated_at is empty")
    last = _flag.parse_dt(row[0])
    if last is None:
        raise Unreadable(f"unparseable updated_at {row[0]!r}")
    return (_flag.now_utc() - last).total_seconds() / 3600.0, n, last


def collect(args) -> list[Finding]:
    findings: list[Finding] = []
    days = _num("DORMANT_HANDOFF_DAYS", 3.0)
    hours = _num("DORMANT_ARCHIVE_HOURS", 48.0)
    cooldown = int(_num("DORMANT_COOLDOWN_SEC", 259200))
    now = _flag.now_utc()

    h = _newest_handoff(_repo())
    age_days = (now - h["at"]).total_seconds() / 86400.0
    if age_days > days:
        findings.append(Finding(
            subject=f"dormant-handoff:{h['id']}",
            prompt="\n".join([
                f"The newest handoff in the journal is **{h['id']}**, dated "
                f"{h['at'].strftime('%Y-%m-%d %H:%M')}Z — **{age_days:.1f} days ago** "
                f"(declared status: `{h['status']}`), and nothing newer has been written.",
                "",
                "A handoff is the record of what was in flight and what comes next. Its own",
                "existence, unchanged for this long, means one of exactly three things, and",
                "only a session can tell which:",
                "  (a) the work stopped and nobody resumed it — RESUME IT;",
                "  (b) the work finished and nobody said so — close it with evidence;",
                "  (c) it is genuinely blocked on the owner — file it on the owner queue and say",
                "      so in one line, then close the handoff.",
                "",
                f"Its own NEXT section said:",
                "",
                h["next"] or "  (the handoff has no **NEXT** section — read it and say so.)",
                "",
                "WHAT TO DO",
                f"1. Read it in full:  python3 ~/harness-config/journal/tools/journal.py show {h['id']}",
                "2. Read the live state:  journal/state/in-flight.md  (and any PROGRAM.md spine in the",
                "   repo the work belongs to — docs/mesh/PROGRAM.md is the model).",
                "3. Take the FIRST item that is genuinely undone and DO it. Not a summary of it —",
                "   the work, with the command output that proves it.",
                "4. When you stop for any reason, write a NEW handoff. Never edit the old one.",
                "   python3 ~/harness-config/journal/tools/journal.py append handoff --title '...'",
                "5. If you did the work, say so in the new handoff and mark the old state resolved.",
                "",
                "DO NOT: report that the work is unfinished without doing any of it; write a",
                "document instead of a change; or leave this as the last thing you did.",
                "",
                "Report at the end: what you did, the evidence, and what is still open.",
            ]),
            context=(f"{SOURCE}: newest handoff {h['id']} is {age_days:.1f}d old "
                     f"(threshold {days:g}d), status={h['status']}"),
            priority="normal",
            kind="resume",
            cooldown_seconds=cooldown,
        ))

    lag_h, count, last = _archive_lag_hours(
        Path(os.environ.get("DSH_ARCHIVE_DB") or (Path.home() / "dsh-archive" / "dsh-archive.db")))
    if lag_h > hours:
        findings.append(Finding(
            subject=f"dormant-archive:{last.strftime('%Y%m%d')}",
            prompt="\n".join([
                f"The DSH session archive on the authority has not advanced in "
                f"**{lag_h:.0f} hours** — its newest `dsh_sessions.updated_at` is "
                f"**{last.strftime('%Y-%m-%d %H:%M')}Z**, and it holds {count} sessions.",
                "",
                "That archive exists for one stated reason (its own header): *so no conversation",
                "is ever only on one laptop*. While it is stalled, every session since is",
                "single-homed, invisible to the authority, and will be lost with the machine that",
                "wrote it. **Nothing else reports this**: an archive that stops looks exactly like",
                "an archive with nothing to do.",
                "",
                "WHAT TO DO",
                "1. Find where it breaks. The pipeline is `scripts/push-dsh-sessions.mjs` on each",
                "   Windows machine (ship) -> `scripts/dsh-archive-import.py` on the authority",
                "   (import), with `DSH_ARCHIVE_INCOMING` defaulting to `~/dsh-archive/incoming`.",
                "2. Check both ends and the cursor:",
                "     ls -la ~/dsh-archive/ ~/dsh-archive/incoming/",
                "     sqlite3 ~/dsh-archive/dsh-archive.db \"SELECT MAX(updated_at), COUNT(*) FROM dsh_sessions;\"",
                "   on a Windows machine: `node <repo>/scripts/push-dsh-sessions.mjs --dry-run`",
                "   (its `~/.dsh/dsh-archive-state.json` cursor is a row count plus a byte mark,",
                "   never a clock).",
                "3. Fix the CAUSE, not the symptom. Re-running the push once and declaring victory",
                "   is the failure mode this journal keeps recording — say what was broken, and",
                "   what now prevents it recurring.",
                "4. Proof is a rising `MAX(updated_at)` and a `COUNT(*)` that moved, quoted.",
                "",
                "Do not delete the archive, its cursor or its incoming batch as a 'reset'.",
            ]),
            context=(f"{SOURCE}: session archive last advanced {last.isoformat()} "
                     f"({lag_h:.0f}h ago, threshold {hours:g}h), {count} sessions"),
            priority="normal",
            kind="repair",
            cooldown_seconds=cooldown,
        ))

    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
