#!/usr/bin/env python3
"""patch-137-outcome-monitor.py — one exact, idempotent, verifiable patch.

WHY. app/services/company_outcome_monitor.py reads the true `database is locked`
count from `journalctl -u secretary-api`. That unit exists on the office box and
NOT on the authority, where the company runs as `company-api.service`. Measured
on secratary-cloud 2026-10-11 before the patch:

    lock_contention_7d: journal_events = 0, undercount_factor = 0.0,
                        journal_provenance = `journalctl -u secretary-api ...` -> 0 matching lines

while `journalctl -u company-api --since '7 days ago'` held 2,499 lines. A monitor
that reports a zero it never read is the exact defect family this estate has paid
for twice, so the port carries a fix rather than a translation.

The patch makes the unit RESOLVED AT RUNTIME (env override, then host probe) and
never assumed. Where `secretary-api` genuinely is the unit (the office box), the
behaviour is unchanged.

Run:  python3 patch-137-outcome-monitor.py [--apply]
Without --apply it only reports what it would change.
"""
import difflib
import os
import shutil
import sys

PATH = "/opt/company/app/services/company_outcome_monitor.py"
BACKUP = PATH + ".before-137"

OLD_CONST = '''JOURNAL_LOCK_COMMAND = (
    "journalctl -u secretary-api --since '{days} days ago' --no-pager -o cat"
)'''

NEW_CONST = '''# PATCHED 2026-10-11 (workstream 137). The unit name used to be the literal
# `secretary-api`, which exists on the office box and NOT on the authority, where the
# company runs as `company-api.service`. Measured on secratary-cloud before this patch:
# `journal_events = 0`, `undercount_factor = 0.0` while 2,499 journal lines sat in
# company-api. The unit is now resolved at runtime and never assumed, because a monitor
# that reports a zero it never read is worse than one that reports that it could not look.
JOURNAL_LOCK_UNIT_CANDIDATES = ("secretary-api", "company-api")
JOURNAL_LOCK_COMMAND = (
    "journalctl -u {unit} --since '{days} days ago' --no-pager -o cat"
)'''

OLD_FN = '''def journal_lock_command(days: int) -> str:
    return JOURNAL_LOCK_COMMAND.format(days=int(days))'''

NEW_FN = '''def journal_lock_unit() -> tuple[str | None, str]:
    """The systemd unit whose journal holds the true `database is locked` count.

    PATCHED 2026-10-11 (workstream 137). Resolution order: the
    `COMPANY_OUTCOME_JOURNAL_UNIT` environment variable, then
    JOURNAL_LOCK_UNIT_CANDIDATES in order, and the first that systemd can actually
    show. `None` means none of them exists on this host, which the caller reports as
    UNREADABLE — deliberately never as zero.
    """
    import shutil
    import subprocess

    override = (os.environ.get("COMPANY_OUTCOME_JOURNAL_UNIT") or "").strip()
    candidates = ([override] if override else []) + [
        u for u in JOURNAL_LOCK_UNIT_CANDIDATES if u != override]
    if not candidates:
        return None, "no candidate journal unit configured"
    if shutil.which("systemctl") is None:
        # No systemd to ask. Attempt the first candidate anyway and let its own
        # failure be reported honestly rather than pre-empting it with a zero.
        return candidates[0], "no systemctl on this host; guessing the first candidate"
    for unit in candidates:
        try:
            proc = subprocess.run(["systemctl", "cat", unit], capture_output=True,
                                  text=True, timeout=10, check=False)
        except Exception:
            continue
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return unit, f"resolved by `systemctl cat {unit}`"
    return None, ("none of the candidate journal units exists on this host: "
                  + ", ".join(candidates))


def journal_lock_command(days: int, unit: str = "secretary-api") -> str:
    return JOURNAL_LOCK_COMMAND.format(days=int(days), unit=unit)'''

OLD_CALL = '''    cmd = journal_lock_command(days)
    if shutil.which("journalctl") is None:'''

NEW_CALL = '''    unit, unit_provenance = journal_lock_unit()
    if unit is None:
        # UNREADABLE, and reported as unreadable. Never a fabricated zero.
        return None, unit_provenance
    cmd = journal_lock_command(days, unit)
    if shutil.which("journalctl") is None:'''

OLD_HITS = '''    return hits, f"`{cmd}` -> {hits} matching lines"'''

NEW_HITS = '''    return hits, f"`{cmd}` -> {hits} matching lines ({unit_provenance})"'''

OLD_LABEL = '''    err_newest = db.newest("error_log", "created_at")
    sec = _section(f"lock_contention_{days}d",
                   "systemd journal (secretary-api) + error_log floor", err_newest)'''

NEW_LABEL = '''    err_newest = db.newest("error_log", "created_at")
    _unit, _unit_provenance = journal_lock_unit()
    sec = _section(f"lock_contention_{days}d",
                   f"systemd journal ({_unit or 'NO CANDIDATE UNIT ON THIS HOST'}) "
                   f"+ error_log floor", err_newest)'''

OLD_SRC = '''    sec["journal_source"] = "systemd journal: secretary-api unit"
    sec["journal_command"] = journal_lock_command(days)'''

NEW_SRC = '''    sec["journal_source"] = f"systemd journal: {_unit or 'NO CANDIDATE UNIT'} unit"
    sec["journal_unit_provenance"] = _unit_provenance
    sec["journal_command"] = journal_lock_command(days, _unit or "secretary-api")'''

PATCHES = [
    ("JOURNAL_LOCK_COMMAND const", OLD_CONST, NEW_CONST),
    ("journal_lock_command()", OLD_FN, NEW_FN),
    ("_journal_lock_events() unit resolution", OLD_CALL, NEW_CALL),
    ("_journal_lock_events() provenance", OLD_HITS, NEW_HITS),
    ("lock_contention section label", OLD_LABEL, NEW_LABEL),
    ("lock_contention source + command", OLD_SRC, NEW_SRC),
]


def main() -> int:
    apply = "--apply" in sys.argv
    with open(PATH) as f:
        src = f.read()

    if "PATCHED 2026-10-11 (workstream 137)" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            print(f"REFUSING: anchor {name!r} occurs {n} times (expected exactly 1). "
                  f"The deployed file is not the revision this patch was written "
                  f"against; nothing was changed.")
            return 2
        out = out.replace(old, new, 1)
        print(f"ok  {name}: 1 replacement")

    if out == src:
        print("no change")
        return 0

    print("---- diff ----")
    for line in difflib.unified_diff(src.splitlines(), out.splitlines(),
                                     "company_outcome_monitor.py.before-137",
                                     "company_outcome_monitor.py", lineterm="", n=2):
        print(line)

    if not apply:
        print("---- dry run; pass --apply to write ----")
        return 0

    if not os.path.exists(BACKUP):
        shutil.copy2(PATH, BACKUP)
        print(f"backed up -> {BACKUP}")
    with open(PATH, "w") as f:
        f.write(out)
    print(f"WROTE {PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
