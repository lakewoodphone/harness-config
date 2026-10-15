#!/usr/bin/env python3
"""r7-revert-paused-ceiling.py — undo the give-up-ceiling change, keep the retry-context change.

WHAT WAS CHANGED AND WHY IT WAS WRONG. Round 6 amended `count_recent_failed_work_sessions` so that a
task reaches its 3-attempt ceiling on `status IN ('failed', 'paused')` instead of `status = 'failed'`.
The reasoning was that `paused` was invisible to the ceiling, so a task whose attempts kept pausing was
re-attempted without limit. **The post-deploy check refutes it.**

Measured on the authority 2026-10-15 ~15:3xZ, 30 days, per task:

    tasks that paused 3+ times : 13   of which 5 went on to COMPLETE   (38 %)
    tasks that failed 3+ times : 482  of which 9 went on to COMPLETE   (1.9 %)

and the decisive single case, task 28625, eight sessions in order:

    78754 paused  20:16:32      78768 paused  22:34:21
    78756 paused  20:24:16      78771 paused  23:32:42
    78759 paused  20:41:24      78778 failed  02:28:45
    78763 paused  22:05:53      78779 COMPLETED 02:44:44

The amended predicate reaches 3 at session 78759 and refuses the task there. It would have abandoned,
four attempts early, work that finished.

WHY THE DISTINCTION IS PRINCIPLED and not just empirical: round 4's own `PROGRAM.md` §2 records that a
`paused` session is `[BUDGET-PAUSED: agent_soft_cap]` and says in terms that it is **not a loop
failure**. Counting it as a strike makes "ran out of room" indistinguishable from "cannot be done".

WHAT SURVIVES: the useful half of the same change is untouched. `PRIOR_ATTEMPT_STATUSES` still includes
`paused`, so a retry still inherits its predecessor's context -- proven by observed sessions (three
sessions created after the deploy, all with a paused predecessor, all carrying the attempt). And
`completed_at` is still set for a terminal `paused`, matching `failed`.

USAGE
    python3 r7-revert-paused-ceiling.py                # measure only
    python3 r7-revert-paused-ceiling.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("/opt/company/app/database.py")
BACKUP_DIR = Path("/root/work/r6")

LIVE_PREDICATE = "\"WHERE task_id = ? AND status IN ('failed', 'paused') AND started_at >= ?\","
WANT_PREDICATE = "\"WHERE task_id = ? AND status = 'failed' AND started_at >= ?\","

NEW_COMMENT = '''        # `paused` is deliberately NOT counted here. Measured on the authority
        # 2026-10-15 after a change that DID count it: of 13 tasks that paused 3+ times
        # in 30 d, **5 went on to COMPLETE** (38 %), against 9 of 482 for `failed`
        # (1.9 %). Task 28625 paused six consecutive times (78754, 78756, 78759, 78763,
        # 78768, 78771), failed once, then completed (78779) -- counting `paused` would
        # have refused it at the third pause (78759), four attempts before it finished.
        # A budget pause means the session ran out of room, not that the work is
        # hopeless, and round 4's own notes call it "not a loop failure". Retry CONTEXT
        # still inherits a paused attempt (attempt_context.PRIOR_ATTEMPT_STATUSES);
        # that is a different question and it is proven by observed sessions.
'''


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

    n = text.count(LIVE_PREDICATE)
    print(f"[1] the amended predicate occurs {n} time(s) (must be exactly 1)")
    if n != 1:
        print("! refusing: the anchor is not unique", file=sys.stderr)
        return 1

    lines = text.splitlines(keepends=True)
    idx = next(i for i, ln in enumerate(lines) if LIVE_PREDICATE in ln)
    # The comment block sits above the `"SELECT count(*) ..."` CONTINUATION line, not directly above
    # the predicate, so walking back from the predicate over comments finds nothing (measured: "0
    # chars, lines 9768-9767"). Walk back over the statement's own continuation lines first, then over
    # the comments above them.
    stmt_start = idx
    while stmt_start > 0 and not lines[stmt_start - 1].lstrip().startswith("#") \
            and lines[stmt_start - 1].strip():
        stmt_start -= 1
    cmt_start = stmt_start
    while cmt_start > 0 and lines[cmt_start - 1].lstrip().startswith("#"):
        cmt_start -= 1
    removed = "".join(lines[cmt_start:stmt_start])
    if "paused" not in removed:
        print(f"! refusing: the comment block I would remove does not mention `paused`: "
              f"{removed[:120]!r}", file=sys.stderr)
        return 1
    print(f"[2] removing the comment block this change added: {len(removed)} chars, "
          f"lines {cmt_start + 1}-{stmt_start}")

    lines[idx] = lines[idx].replace(LIVE_PREDICATE, WANT_PREDICATE)
    new_text = (
        "".join(lines[:cmt_start]) + NEW_COMMENT + "".join(lines[stmt_start:])
    )

    before_body = text.count(WANT_PREDICATE)
    print(f"[3] the restored predicate now occurs {new_text.count(WANT_PREDICATE)} time(s) "
          f"(was {before_body})")
    if new_text.count(WANT_PREDICATE) != before_body + 1:
        print("! refusing: the restore did not land exactly once", file=sys.stderr)
        return 1
    if "status IN ('failed', 'paused')" in new_text:
        leftovers = [ln.strip() for ln in new_text.splitlines()
                     if "status IN ('failed', 'paused')" in ln]
        print(f"! refusing: the amended predicate survives in {len(leftovers)} place(s): {leftovers}",
              file=sys.stderr)
        return 1

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    stage = BACKUP_DIR / "r7-files3" / "database.py"
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
    backup = BACKUP_DIR / f"backups-revert-{stamp}" / "database.py"
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
    print(f"\n    rollback: cp -p {backup} {TARGET}")
    print("    NOT restarted. company-api.service must be restarted for this to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
