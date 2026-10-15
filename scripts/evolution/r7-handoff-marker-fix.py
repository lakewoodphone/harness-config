#!/usr/bin/env python3
"""r7-handoff-marker-fix.py — make the completion markers recognisable to `_handoff_left`.

THE MEASURED DEFECT. `_HANDOFF_TERMINAL_MARKER_RE` (app/autopilot.py:85) lists sixteen markers a
session's own trace can use to say how it ended, and the completion path's OWN tokens are not among
them: it writes `[COMPLETED: evidence=...]` (line ~4345) and `[TASK-CLOSED-BY-SESSION: ...]`
(line ~4144) and tests for `[WORK_DONE]`, and none of the three is in the regex.

`_handoff_left` uses the caller's `terminal_marker` FIRST and falls back to `accumulated_output` only
when the caller's marker contains nothing it recognises. So a caller that names its own completion
marker is not recognised, the field falls back into the log, and it quotes an older
`[OUT-OF-TURNS: ... the session is still open]` -- the field that exists to tell the next reader what
was left says the session was still open after it had closed.

Measured on the authority 2026-10-15 by calling the live function, before this change:

    _handoff_left(log_with_OUT-OF-TURNS, result="partial", terminal_marker=...)
      ""                                  -> [OUT-OF-TURNS: ... still open]   (correct: nothing named)
      "[COMPLETED: evidence=[TASK-CLOSED-BY-SESSION] ...]" -> [OUT-OF-TURNS: ...]  WRONG
      "[TASK-CLOSED-BY-SESSION]"          -> [OUT-OF-TURNS: ...]              WRONG
      "[BLOCKED: ...]"                    -> [BLOCKED: ...]                   correct
      "[STEP_BUDGET_EXHAUSTED: ...]"      -> [STEP_BUDGET_EXHAUSTED: ...]     correct

WHAT CHANGES: two alternatives added to that one regex, and nothing else. `_HANDOFF_TERMINAL_MARKER_RE`
has exactly one reader (`_handoff_left`, lines 3567/3569) and no reader anywhere else in `app/` or
`tests/`, verified by grep, so the blast radius is that one field.

DELIBERATELY NOT ADDED: `WORK_DONE`. It is a fourth completion token in the same neighbourhood, and
adding it is a judgement call with no measurement behind it -- a bare mention of the token in a trace
could then become the reported ending. Add it when a session is measured needing it.

USAGE
    python3 r7-handoff-marker-fix.py                 # measure only; writes nothing
    python3 r7-handoff-marker-fix.py --apply         # stage, compile, prove, install, cmp
"""
from __future__ import annotations

import argparse
import hashlib
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("/opt/company/app/autopilot.py")
STAGE = Path("/root/work/r6/r7-files2/app/autopilot.py")
BACKUP_DIR = Path("/root/work/r6")

OLD = '    r"OUT-OF-TURNS|ALREADY-CLOSED|FORCE-EXPIRED|COMPLETION BLOCKED)[^\\]]*\\]"'
NEW = ('    r"OUT-OF-TURNS|ALREADY-CLOSED|FORCE-EXPIRED|COMPLETION BLOCKED|"\n'
       '    r"COMPLETED|TASK-CLOSED-BY-SESSION)[^\\]]*\\]"')

MUST_MATCH = [
    "[COMPLETED: evidence=[TASK-CLOSED-BY-SESSION] at 12; ...]",
    "[TASK-CLOSED-BY-SESSION: task=441 at position 30]",
]
MUST_STILL_MATCH = [
    "[OUT-OF-TURNS: the session used its turn allowance]",
    "[STEP_BUDGET_EXHAUSTED: the step allowance ran out]",
    "[BLOCKED: needs the owner]",
    "[HARD-CEILING: 240 steps]",
    "[COMPLETION BLOCKED: no proof]",
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract_regex(text: str) -> str:
    """Pull the _HANDOFF_TERMINAL_MARKER_RE alternation back out of an autopilot.py."""
    m = re.search(r"_HANDOFF_TERMINAL_MARKER_RE = re\.compile\(\n(.*?)\n\)", text, re.S)
    if not m:
        raise SystemExit("! could not find _HANDOFF_TERMINAL_MARKER_RE in the file")
    return m.group(1)


def behaviour(regex_src: str) -> None:
    """Prove what the regex does, by running it -- not by reading it."""
    ns: dict = {}
    exec(compile("import re\nR = re.compile(" + regex_src + ")\n", "<probe>", "exec"), ns)
    R = ns["R"]
    print("    the regex as staged:")
    for s in MUST_MATCH:
        print(f"      MATCH EXPECTED  {R.findall(s) != []!s:5}  {s[:56]}")
    for s in MUST_STILL_MATCH:
        print(f"      MATCH EXPECTED  {R.findall(s) != []!s:5}  {s[:56]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not TARGET.is_file():
        print(f"! {TARGET} not found", file=sys.stderr)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    before = sha(TARGET)
    print(f"target  {TARGET}  sha256 {before}")

    print("\n[1] the regex BEFORE this change, as it behaves")
    behaviour(extract_regex(text))

    n = text.count(OLD)
    print(f"\n[2] the exact line to replace occurs {n} time(s) (must be exactly 1)")
    if n != 1:
        print("! refusing to edit: the anchor is not unique", file=sys.stderr)
        return 1

    staged_text = text.replace(OLD, NEW, 1)
    print("\n[3] the regex AFTER this change, as it behaves")
    behaviour(extract_regex(staged_text))

    ns: dict = {}
    # The extracted source is the INSIDE of a `re.compile(...)` call, so its continuation lines carry
    # leading indentation. That is legal inside the parentheses and an IndentationError at module
    # level -- the first version of this check put it at module level and failed on its own harness
    # rather than on the change. Wrap it the same way the file does.
    exec(compile("import re\nR = re.compile(\n" + extract_regex(staged_text) + "\n)\n", "<new>", "exec"), ns)
    R = ns["R"]
    missing = [s for s in MUST_MATCH if not R.findall(s)]
    broke = [s for s in MUST_STILL_MATCH if not R.findall(s)]
    if missing or broke:
        print(f"! the staged regex is wrong: missing={missing} broke={broke}", file=sys.stderr)
        return 1
    print("    all five expectations hold")

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    STAGE.write_text(staged_text, encoding="utf-8")
    print(f"\n[4] staged -> {STAGE}  sha256 {sha(STAGE)}")
    print("    python syntax check:", end=" ")
    try:
        py_compile.compile(str(STAGE), doraise=True)
        print("OK")
    except py_compile.PyCompileError as exc:
        print(f"FAILED\n{exc}")
        return 1

    stamp = subprocess.run(["date", "-u", "+%Y%m%dT%H%M%SZ"], capture_output=True,
                           text=True).stdout.strip()
    backup = BACKUP_DIR / f"backups-markerfix-{stamp}" / "autopilot.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, backup)
    print(f"[5] backup -> {backup}  sha256 {sha(backup)}")

    shutil.copy2(STAGE, TARGET)
    print(f"[6] installed  sha256 {sha(TARGET)}")
    if sha(TARGET) != sha(STAGE):
        print("! did not land byte-for-byte -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    cmp: identical to the staged file")
    print(f"\n    the live regex now matches [COMPLETED: ...] : "
          f"{re.compile(extract_regex(TARGET.read_text(encoding='utf-8'))).findall(MUST_MATCH[0]) != []}")
    print(f"    rollback: cp -p {backup} {TARGET}")
    print("\n    NOT restarted. company-api.service must be restarted for this to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
