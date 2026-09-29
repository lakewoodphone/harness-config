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

  (B) THE SESSION ARCHIVE HAS A REAL GAP. The authoritative archive is
      `secretary.db`, written by the company's own route
      `POST /api/v1/owner/dsh-sessions/ingest`. This source DOES NOT OPEN A
      DATABASE, and in particular it never opens the retired interim store
      `~/dsh-archive/dsh-archive.db` — frozen by design since 2026-09-11 19:16,
      when the HTTP path went live (journal D42, L158b: "a second copy of a thing
      is not a second reading of it"). It asks the one definition of "is the
      archive current", `scripts/server/check-dsh-freshness.py`, which reads the
      authoritative store and distinguishes "local work exists and did not
      arrive" (a fault) from "the machine had nothing to say" (correct; journal
      L167/P52).

      WHY THIS IS THE WHOLE POINT OF (B). On 2026-09-20 01:44 the first version
      of this source read the retired store directly and tested `MAX(updated_at)`
      against 48 h. The copy had been frozen for 199 h, so it filed a
      `dormant-archive:20260911` flag at 01:45 and the dispatcher woke a session
      at 02:15 to repair an outage that did not exist — while the authoritative
      archive was minutes fresh and the owner digest on the same host already said
      "nothing unarchived". A false alarm is not a neutral error: it teaches the
      reader to ignore the alarm (P52, P6). This source therefore delegates; it
      never ages a copy.

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
          dormant-archive:<YYYYMMDD>       filed only when the authoritative
                                           checker reports a real, unarchived
                                           gap; keyed to the day, so a persistent
                                           fault re-files at most once a day.

MUST NEVER
    - fire because something MIGHT be unfinished. It fires on a measured age and
      a measured absence, and the prompt tells the session to decide, with
      evidence, whether there is work — and to CLOSE the record if there is not.
    - treat a quiet journal as health. A journal nobody writes to is the failure
      this source is looking for, not the absence of one.
    - read a session database itself, or age any store. There are two DSH session
      stores; only `secretary.db` has a writer, and only `check-dsh-freshness.py`
      is allowed to say whether it is current (D42, L158b, L167, P52).
    - raise a flag from inside a woken session (the store refuses that itself).

RUN
    python3 sources/dormant-handoff.py [--dry-run]
    DORMANT_HANDOFF_DAYS=3          age that makes the in-flight record dormant
    DORMANT_COOLDOWN_SEC=259200     re-file floor after a release (3 days)
    DORMANT_ARCHIVE_HOURS           retained for compatibility; the checker owns
                                    the threshold now (its UNSHIPPED_GRACE_MIN)
    HARNESS_REPO                    the harness checkout (default ~/harness-config)
    DSH_ARCHIVE_FRESHNESS           the authoritative freshness checker
                                    (default ~/personal-secretary-mvp/scripts/server/check-dsh-freshness.py)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
    import subprocess as _sp

    def git(*args: str) -> str:
        return _sp.run(
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


def _freshness_checker() -> Path:
    """The ONE place allowed to decide whether the archive is current."""
    return Path(os.environ.get("DSH_ARCHIVE_FRESHNESS")
                or (Path.home() / "personal-secretary-mvp" / "scripts" / "server"
                    / "check-dsh-freshness.py"))


def _archive_verdict() -> dict:
    """Ask the authoritative freshness checker. Never open a database here.

    The checker owns the definition because it can tell the two situations apart:
    local work that was not archived (a fault, rc=1) versus a machine with nothing
    to say (not a fault, rc=0). It reads `secretary.db`; the retired `scp` store is
    not a source of truth and this source must never read it (D42, L158b, L167, P52).
    A refusal (rc=2) is raised, never reported as healthy.
    """
    checker = _freshness_checker()
    if not checker.exists():
        raise Unreadable(f"no archive freshness checker at {checker}")
    proc = subprocess.run(
        [sys.executable, str(checker), "--json"],
        capture_output=True, text=True, timeout=90,
    )
    if proc.returncode == 2:
        raise Unreadable(
            "freshness checker refused (its inputs could not be read): "
            + (proc.stdout or proc.stderr).strip()[:300]
        )
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        raise Unreadable(
            f"freshness checker returned unparseable output: {proc.stdout[:200]!r}"
        )
    return {"rc": proc.returncode, "payload": payload}


def collect(args) -> list[Finding]:
    findings: list[Finding] = []
    days = _num("DORMANT_HANDOFF_DAYS", 3.0)
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

    verdict = _archive_verdict()
    if verdict["rc"] == 1:
        payload = verdict["payload"]
        archive = str(payload.get("archive") or "the authoritative archive")
        real = [f for f in (payload.get("findings") or [])
                if str(f.get("severity")) == "stale"]
        detail = "; ".join(f"{f.get('machine')}: {f.get('detail')}" for f in real) \
            or "the authoritative checker reported a stale archive"
        findings.append(Finding(
            subject=f"dormant-archive:{now.strftime('%Y%m%d')}",
            prompt="\n".join([
                "The DSH session archive has a REAL gap: a machine holds local work that was",
                "never archived. This is measured against the authoritative store by",
                f"`check-dsh-freshness.py` ({archive}) — not by the age of a copy.",
                "",
                f"Finding: {detail}",
                "",
                "The archive exists for one stated reason: *so no conversation is ever only",
                "on one laptop*. A machine whose shipper has stopped is single-homed until",
                "this is fixed.",
                "",
                "WHAT TO DO",
                "1. Reproduce and read the detail:",
                "     python3 ~/personal-secretary-mvp/scripts/server/check-dsh-freshness.py",
                "2. The authoritative store is `secretary.db` via",
                "   `POST /api/v1/owner/dsh-sessions/ingest`; the shipper is",
                "   `scripts/push-dsh-sessions.mjs` (Windows tasks and the authority cron).",
                "   Do NOT read `~/dsh-archive/dsh-archive.db` — it is the retired `scp`",
                "   interim, frozen by design since 2026-09-11 19:16 (D42, L158b).",
                "3. Fix the CAUSE, not the symptom. Re-running the push once and declaring",
                "   victory is the failure mode this journal keeps recording — say what was",
                "   broken, and what now prevents it recurring.",
                "4. Proof is a rising `MAX(updated_at)` and a `COUNT(*)` that moved, quoted.",
                "",
                "Do not delete the archive, its cursor or its incoming batch as a 'reset'.",
            ]),
            context=(f"{SOURCE}: check-dsh-freshness.py rc=1 against {archive}: {detail}"),
            priority="normal",
            kind="repair",
            cooldown_seconds=cooldown,
        ))

    return findings


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
