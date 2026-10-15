#!/usr/bin/env python3
"""r7-deadlock-nonfatal.py — a repo that is not on this host must not be retried or counted.

THE MEASUREMENT (2026-10-15, `/root/authority.db` read-only, 7 days): 176 sessions carry
`TOOL_LOOP_DEADLOCK`; **36** of them name an action that is `temporarily disabled` and **28** a
`file not found`. Session **78859** read in full shows the mechanism: the agent calls `repo_map` /
`repo_read_file` with a `repo_path` that does not exist ON THE AUTHORITY, the action is
circuit-broken after 10 consecutive failures, and the session then spends its whole budget on
thirteen consecutive "I'll stop re-probing and take the mutating action now" turns, none of them an
action.

WHY THE EXISTING GUARD MISSES IT. `_NON_FATAL_CB_FAILURE_PATTERNS` drives BOTH
`_should_record_circuit_breaker_failure` and `_should_retry_action_failure` -- they are the same
predicate -- and the `repo_*` entries already list `Missing "repo_path"`, `File not found:` and
`Not a directory:`. But `resolve_managed_repo_path` (`app/chat_action_repos.py:92`) reports a repo
that is absent from THIS host with different words:

    Repo 'phone-and-tech' has no local checkout on this host (tried ...)
    Path does not exist on this host: C:/Users/ezabz/Code/...
    Repo not available locally for 'repo_map'          (the fallback)

None of those three strings appears in any pattern list, so the failure is counted, the action is
disabled at ten strikes, and the identical-failure guard spends three strikes on something that can
never succeed. The resolver ALSO returns the correct remedy as `hint` (use `github_*` tools, or
`scripts/repo-bootstrap.sh <repo>`), which the agent is handed -- next to a static `FIX:` line
telling it to change the argument, which cannot help.

WHAT THIS CHANGES: three strings, added to the five `repo_*` pattern tuples. No control flow, no new
predicate. Being listed there means "this failure is deterministic, so do not retry it and do not
count it toward the breaker" -- which is exactly true of a repo that is not present.

USAGE
    python3 r7-deadlock-nonfatal.py            # measure only
    python3 r7-deadlock-nonfatal.py --apply
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

NEW_PATTERNS = (
    '        "has no local checkout on this host",\n'
    '        "Path does not exist on this host",\n'
    '        "Repo not available locally",\n'
)

OLD_BLOCK = '''    "repo_read_file": (
        'Missing "repo_path"',
        'Missing "repo_path" or "path"',
        "File not found:",
        "Not a file:",
        "Not a directory:",
    ),
    "repo_list_dir": (
        'Missing "repo_path"',
        'Missing "repo_path" or "path"',
        "Not a directory:",
    ),
    "repo_map": (
        'Missing "repo_path"',
        "Not a directory:",
    ),
    "repo_search": ('Missing "repo_path"',),
    "repo_run_command": ('Missing "repo_path" or "command"',),
'''

NOTE = '''# NOTE (2026-10-15). A repo that is NOT PRESENT on this host is permanent for the session: no
# alias, no retry and no argument change can make it resolve. `resolve_managed_repo_path`
# (app/chat_action_repos.py:92) says so in words this dict did not know -- "has no local checkout on
# this host", "Path does not exist on this host", "Repo not available locally" -- so such failures
# were counted toward the circuit breaker, the action was disabled at ten strikes, and the
# identical-failure guard then spent three strikes on it. Measured 7 days: 176 sessions carry
# TOOL_LOOP_DEADLOCK, 36 of them via an action disabled this way. Both predicates below read THIS
# dict, so listing the strings here is the whole fix.
'''

NEW_BLOCK = '''    "repo_read_file": (
        'Missing "repo_path"',
        'Missing "repo_path" or "path"',
        "File not found:",
        "Not a file:",
        "Not a directory:",
''' + NEW_PATTERNS + '''    ),
    "repo_list_dir": (
        'Missing "repo_path"',
        'Missing "repo_path" or "path"',
        "Not a directory:",
''' + NEW_PATTERNS + '''    ),
    "repo_map": (
        'Missing "repo_path"',
        "Not a directory:",
''' + NEW_PATTERNS + '''    ),
    "repo_search": (
        'Missing "repo_path"',
''' + NEW_PATTERNS + '''    ),
    "repo_run_command": (
        'Missing "repo_path" or "command"',
''' + NEW_PATTERNS + '''    ),
'''

PROBES = [
    # (detail, expected_retryable)
    ("Path does not exist on this host: C:/Users/ezabz/Code/phone-and-tech", False),
    ("Repo 'phone-and-tech' has no local checkout on this host (tried C:/Users/ezabz/Code/phone-and-tech)",
     False),
    ("Repo not available locally for 'repo_map'", False),
    ("Missing \"repo_path\" for repo_map. Pass a local path or a managed repo alias", False),
    ("Connection reset by peer", True),            # control: must stay retryable
    ("Permission denied", True),                   # control
]


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

    n = text.count(OLD_BLOCK)
    print(f"[1] the five repo_* pattern tuples occur {n} time(s) (must be exactly 1)")
    if n != 1:
        print("! refusing: the anchor is not unique", file=sys.stderr)
        return 1

    anchor = "_NON_FATAL_CB_FAILURE_PATTERNS: dict[str, tuple[str, ...]] = {\n"
    if text.count(anchor) != 1:
        print("! refusing: cannot locate the dict opening", file=sys.stderr)
        return 1

    new_text = text.replace(OLD_BLOCK, NEW_BLOCK, 1)
    new_text = new_text.replace(anchor, anchor + NOTE, 1)

    for probe in ("has no local checkout on this host",
                  "Path does not exist on this host",
                  "Repo not available locally"):
        c = new_text.count(probe)
        print(f"[2] {probe!r} now occurs {c} time(s) (expect 5 + 1 in the note)")

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    stage = BACKUP_DIR / "r7-files4" / "chat_action_resilience.py"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(new_text, encoding="utf-8")
    print(f"[3] staged -> {stage}  sha256 {sha(stage)}")
    print("    python syntax check:", end=" ")
    try:
        py_compile.compile(str(stage), doraise=True)
        print("OK")
    except py_compile.PyCompileError as exc:
        print(f"FAILED\n{exc}")
        return 1

    stamp = subprocess.run(["date", "-u", "+%Y%m%dT%H%M%SZ"], capture_output=True,
                           text=True).stdout.strip()
    backup = BACKUP_DIR / f"backups-nonfatal-{stamp}" / "chat_action_resilience.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, backup)
    print(f"[4] backup -> {backup}  sha256 {sha(backup)}")

    shutil.copy2(stage, TARGET)
    print(f"[5] installed  sha256 {sha(TARGET)}")
    if sha(TARGET) != sha(stage):
        print("! did not land byte-for-byte -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    cmp: identical to the staged file")

    print("\n[6] PROOF -- the predicate itself, on the real message strings:")
    sys.path.insert(0, "/opt/company")
    import importlib
    import app.chat_action_resilience as R
    importlib.reload(R)
    bad = 0
    for detail, want in PROBES:
        got = R._should_retry_action_failure("repo_map", detail)
        ok = (got == want)
        bad += 0 if ok else 1
        print(f"      retryable={str(got):5} (want {str(want):5}) {'ok ' if ok else 'FAIL'}  {detail[:62]}")
    if bad:
        print(f"! {bad} probe(s) failed -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    all probes hold")
    print(f"\n    rollback: cp -p {backup} {TARGET}")
    print("    NOT restarted. company-api.service must be restarted for this to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
