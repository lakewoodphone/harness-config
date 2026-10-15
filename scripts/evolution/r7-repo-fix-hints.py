#!/usr/bin/env python3
"""r7-repo-fix-hints.py — stop telling the agent to change an argument that is not the problem.

THE REMAINING HALF of the TOOL_LOOP_DEADLOCK fix. `r7-deadlock-nonfatal.py` stopped an absent repo
from being retried and from counting toward the action's circuit breaker. But `_get_fix_hint` is
keyed on the ACTION NAME only, so the agent is still handed a static remedy beside the resolver's own
hint:

    FIX: Use repo_path alias (e.g. personal-secretary, phone-and-tech)

On the authority an alias resolves through `resolve_managed_repo_path` to the blueprint's canonical
WINDOWS path and then to `~/repos/<repo>` — neither exists — so the alias is exactly as unavailable
as the path was. The agent is told to change the argument, complies, and dies. The resolver already
computes the right instruction and returns it as `hint`:

    Repo 'x' has no local checkout on this host ... Use github_* tools against 'owner/repo', or
    bootstrap a clone with: scripts/repo-bootstrap.sh x

This replaces the five `repo_*` FIX strings with ones that lead with the PERMANENT condition, so the
static line stops contradicting the dynamic one. No control flow; string data only.

USAGE
    python3 r7-repo-fix-hints.py            # measure only
    python3 r7-repo-fix-hints.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("/opt/company/app/chat_action_resilience.py")
BACKUP_DIR = Path("/root/work/r6")

TAIL = (
    " If the repo has no checkout on THIS host, do not change the argument again -- "
    "call github_* tools, or bootstrap a clone with scripts/repo-bootstrap.sh <alias>."
)

REPLACEMENTS: list[tuple[str, str]] = [
    (
        '''    "repo_read_file": (
        "FIX: Use full path for repo_path (e.g. "
        "C:/Users/ezabz/Code/phone-and-tech-full) "
        "or use a repo alias like phone-and-tech."
    ),''',
        '''    "repo_read_file": (
        "FIX: Use a full path or a repo alias for repo_path (e.g. phone-and-tech, lpt-hub)." + _REPO_ABSENT_TAIL
    ),''',
    ),
    (
        '    "repo_list_dir": "FIX: Use full path or alias for repo_path.",',
        '    "repo_list_dir": "FIX: Use a full path or alias for repo_path." + _REPO_ABSENT_TAIL,',
    ),
    (
        '''    "repo_run_command": (
        "FIX: Use full path or alias for repo_path. " "Only safe commands are allowed."
    ),''',
        '''    "repo_run_command": (
        "FIX: Use a full path or alias for repo_path. Only safe commands are allowed."
        + _REPO_ABSENT_TAIL
    ),''',
    ),
    (
        '''    "repo_map": (
        "FIX: Use repo_path alias (e.g. personal-secretary, "
        "phone-and-tech). Optional: depth=N, pattern=*.py"
    ),''',
        '''    "repo_map": (
        "FIX: Use repo_path alias (e.g. personal-secretary, phone-and-tech). "
        "Optional: depth=N, pattern=*.py" + _REPO_ABSENT_TAIL
    ),''',
    ),
    (
        '''    "repo_search": (
        "FIX: Use repo_path alias + query=SEARCH_TEXT. "
        "Optional: pattern=*.py, limit=N"
    ),''',
        '''    "repo_search": (
        "FIX: Use repo_path alias + query=SEARCH_TEXT. Optional: pattern=*.py, limit=N"
        + _REPO_ABSENT_TAIL
    ),''',
    ),
]

DEFINITION = '''_REPO_ABSENT_TAIL = (
    " If the repo has no checkout on THIS host, do not change the argument again -- "
    "call github_* tools, or bootstrap a clone with scripts/repo-bootstrap.sh <alias>."
)

_FIX_HINTS: dict[str, str] = {'''

PROBE_ACTIONS = ("repo_read_file", "repo_list_dir", "repo_map", "repo_search", "repo_run_command")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not TARGET.is_file():
        print(f"! {TARGET} not found", file=sys.stderr)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    print(f"target {TARGET}  sha256 {sha(TARGET)}")

    if "_REPO_ABSENT_TAIL" in text:
        print("[0] _REPO_ABSENT_TAIL is already present -- treating this as a re-run; "
              "all replacements must already be in place or this refuses")
    anchor = "\n_FIX_HINTS: dict[str, str] = {"
    print(f"[1] the _FIX_HINTS anchor occurs {text.count(anchor)} time(s) (must be exactly 1)")
    if text.count(anchor) != 1:
        print("! refusing: cannot locate _FIX_HINTS uniquely", file=sys.stderr)
        return 1

    new_text = text.replace(anchor, "\n" + DEFINITION, 1)
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        c = new_text.count(old)
        print(f"[2.{i}] anchor for {old.strip().splitlines()[0].strip()!r}: {c} match(es)")
        if c != 1:
            print(f"! refusing: replacement {i} is not unique", file=sys.stderr)
            return 1
        new_text = new_text.replace(old, new, 1)

    if "_REPO_ABSENT_TAIL" in new_text:
        uses = new_text.count("+ _REPO_ABSENT_TAIL")
        print(f"[3] the tail is now referenced by {uses} repo_* hint(s) (expect 5)")
        if uses != 5:
            print(f"! refusing: expected 5 references, found {uses}", file=sys.stderr)
            return 1

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    stage = BACKUP_DIR / "r7-files5" / "chat_action_resilience.py"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(new_text, encoding="utf-8")
    print(f"[4] staged -> {stage}  sha256 {sha(stage)}")
    print("    python syntax check:", end=" ")
    try:
        py_compile.compile(str(stage), doraise=True)
        print("OK")
    except py_compile.PyCompileError as exc:
        print(f"FAILED\n{exc}")
        return 1

    stamp = subprocess.run(["date", "-u", "+%Y%m%dT%H%M%SZ"], capture_output=True,
                           text=True).stdout.strip()
    backup = BACKUP_DIR / f"backups-fixhint-{stamp}" / "chat_action_resilience.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, backup)
    print(f"[5] backup -> {backup}  sha256 {sha(backup)}")

    shutil.copy2(stage, TARGET)
    print(f"[6] installed  sha256 {sha(TARGET)}")
    if sha(TARGET) != sha(stage):
        print("! did not land byte-for-byte -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    cmp: identical to the staged file")

    print("\n[7] PROOF -- the hint the agent is actually handed, per action:")
    sys.path.insert(0, "/opt/company")
    import importlib
    import app.chat_action_resilience as R
    importlib.reload(R)
    bad = 0
    for a in PROBE_ACTIONS:
        h = R._get_fix_hint(a)
        ok = "no checkout on THIS host" in h
        bad += 0 if ok else 1
        print(f"      {'ok ' if ok else 'FAIL'}  {a:18} {h[:110]}")
    if bad:
        print(f"! {bad} hint(s) missing the tail -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    all five carry the permanent-condition advice")
    print(f"\n    rollback: cp -p {backup} {TARGET}")
    print("    NOT restarted. company-api.service must be restarted for this to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
