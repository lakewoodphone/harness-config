#!/usr/bin/env python3
"""FLAG SOURCE: a crontab entry whose program does not exist.

THE SIGNAL
----------
`~/bin/cron-target-guard.py --json` reads `crontab -l` and checks that every path a job calls is
present, readable, and (for a shell script) executable. It exits 0 clean, 1 on a broken target,
2 when the crontab itself cannot be read.

Measured 2026-09-30 on the authority: FIVE cron jobs called files that did not exist -- the
Dialpad call harvest, the Dialpad SMS harvest, the voicemail recording gap filler, the call
transcript gap filler, and the Home Assistant security-absence alarm -- because the scripts lived
only in the deployed working tree and a checkout switch removed them. The call harvest had been
dead for 28 hours and the shop's calls were not being fetched; nothing said so, because cron
writes one line into a log nobody reads and `sh: not found` is indistinguishable from silence.
A second pass by the same guard found two more, dead for weeks: the site uptime check (no execute
bit since 2026-09-06) and the API startup guard (since 2026-08-04).

This source exists so that class cannot recur silently: the guard is a MONITOR, and this is its
route into the work ledger.

WHY A SOURCE AND NOT A CRON MAIL
--------------------------------
The system's own contract is that "the machine noticed something" becomes a ledger item; a cron
mail does not exist on this host (`command -v mail` finds nothing -- see journal P167, where a
database-corruption alarm was found to have no transport at all). A source is the existing,
working escalation path.

PRIORITY  high. A dead scheduled job is an ABSENCE, and an absence has no symptom until someone
          needs the thing that stopped.

SUBJECTS  cron-targets:<sha1 of the sorted missing paths> -- keyed to the SET of broken targets,
          so repairing one and leaving another re-files under a new key rather than being
          deduped away.

MUST NEVER
    - fire because the guard could not parse something (that is `unreadable`, and this source
      raises Unreadable so the sources log says FAILED rather than filing a false flag);
    - report a target as missing that the guard did not measure.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "cron-targets"
GUARD = Path(os.environ.get("CRON_TARGET_GUARD", str(Path.home() / "bin" / "cron-target-guard.py")))
COOLDOWN_SECONDS = int(os.environ.get("CRON_TARGETS_COOLDOWN", "21600"))  # 6 h


def _guard_report() -> dict:
    if not GUARD.is_file():
        raise Unreadable("the guard itself is missing at %s" % GUARD)
    try:
        proc = subprocess.run(
            [sys.executable or "python3", str(GUARD), "--json", "--write-status"],
            capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not run the guard: %s" % exc)
    raw = (proc.stdout or "").strip()
    if not raw:
        raise Unreadable("the guard printed nothing (rc=%s, stderr=%s)"
                         % (proc.returncode, (proc.stderr or "").strip()[:200]))
    try:
        # `--json` prints one pretty-printed object as the whole of stdout, so the
        # WHOLE of it is the document. Slicing the last line reaches `}` and dies
        # with "Expecting value: line 1 column 1" -- measured 2026-09-30, the first
        # run of this source.
        report = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("the guard output is not JSON: %s" % exc)
    if proc.returncode == 2:
        raise Unreadable("the crontab could not be read")
    return report


def collect(args) -> list[Finding]:
    report = _guard_report()
    missing = [m["path"] for m in report.get("missing", [])]
    unreadable = [m["path"] for m in report.get("unreadable", [])]
    noexec = [m["path"] for m in report.get("not_executable", [])]
    crlf = [m["path"] for m in report.get("crlf", [])]
    broken = sorted(set(missing + unreadable + noexec + crlf))
    if not broken:
        return []

    key = hashlib.sha1("\n".join(broken).encode("utf-8")).hexdigest()[:10]
    lines = []
    for m in report.get("missing", []):
        lines.append("MISSING      %s\n             <= %s" % (m["path"], m["line"]))
    for m in report.get("unreadable", []):
        lines.append("UNREADABLE   %s\n             <= %s" % (m["path"], m["line"]))
    for m in report.get("not_executable", []):
        lines.append("NO EXEC BIT  %s\n             <= %s" % (m["path"], m["line"]))
    for m in report.get("crlf", []):
        lines.append("CRLF SHELL   %s\n             <= %s" % (m["path"], m["line"]))

    prompt = (
        "A scheduled job on the authority calls a program that is not there. The crontab is not\n"
        "under version control, so a job whose file disappeared keeps running the schedule and\n"
        "failing into a log nobody reads -- the failure looks exactly like silence.\n\n"
        "%s\n\n"
        "WHAT TO DO, in this order:\n"
        "  1. For each path above, find the newest surviving copy. The preserved live trees are\n"
        "     the first place to look: `ls -dt /home/zabz/_verify* /home/zabz/_worktrees/*` and\n"
        "     the preserve branch `git -C /home/zabz/personal-secretary-mvp log --all --oneline\n"
        "     --source -1 -- <path>`. Verify with sha256sum against the tree you restored from.\n"
        "  2. Copy it back with its mode (`cp -p`), then COMMIT it in the checkout that runs it,\n"
        "     so the next checkout switch cannot drop it again.\n"
        "  3. If the file exists nowhere, do not invent the program: the schedule is calling\n"
        "     something that was deleted deliberately or lost for good, and the honest fix is to\n"
        "     remove or correct the crontab line and record why.\n"
        "  4. Run the restored job once by hand and paste its first successful output line.\n"
        "     A restored file that has never run is not a fixed job.\n\n"
        "Then re-run `python3 ~/bin/cron-target-guard.py` and paste the clean output. A cron\n"
        "target that cannot be proven to run is the exact class this source exists to catch.") \
        % "\n".join(lines)

    return [Finding(
        subject="cron-targets:%s" % key,
        prompt=prompt,
        priority="high",
        kind="repair",
        context=json.dumps({"broken": broken, "checked": report.get("checked"),
                            "at": report.get("at")}),
        cooldown_seconds=COOLDOWN_SECONDS,
    )]


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
