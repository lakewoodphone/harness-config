#!/usr/bin/env python3
"""Patch project-keepalive.py's standing_contract() to the ledger-driven shift contract.

WHY THIS PATCH EXISTS. The old contract ended by telling the worker to rewrite a per-project
JSON blob (`/home/zabz/.wake-projects/<id>.json`) with a `remaining` list. Measured failures of
that shape, 2026-09-28: 27 wake rows filed and never run; the same lpt-website fix pushed by
three consecutive shifts and merged by none; and no record anywhere of what a shift actually
tried, so the next shift re-derived it from scratch. The ownership of "what is left" was the
state file, which the worker rewrote wholesale, non-transactionally, with no history.

The new contract routes ALL durable state through `~/bin/work.py` (the work ledger, WAL, on the
authority): the backlog, the claim, the attempt record with its proving command and result, and
what is left. The worker no longer owns a private blob; it appends to a ledger every later shift
and the manager can read.

Usage:  python3 patch-contract.py --apply
        python3 patch-contract.py --verify
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")
LEDGER = "python3 ~/bin/work.py"

NEW_FUNC = '''def standing_contract(project: dict, state: dict, items: list[str],
                      now: datetime) -> str:
    """The prompt every woken project session gets: the LEDGER-driven shift contract.

    Rewritten 2026-09-28. The old contract told the worker to rewrite a per-project JSON
    blob with a `remaining` list; that blob was the only record of what was left, it was
    rewritten wholesale by each shift, and nothing recorded what a shift had tried. The
    measured result: 27 filed rows never run, an identical lpt-website fix pushed by three
    shifts and merged by none, and every shift re-deriving the backlog from scratch.

    Now the ledger (`~/bin/work.py`, WAL, on the authority) owns the backlog, the claim, the
    attempt with its proving command and result, and what is left. The state file is still
    mentioned for continuity, but it is no longer where work lives.
    """
    pid = project["id"]
    title = str(project.get("title") or pid)
    where = str(project.get("repo") or project.get("case") or "UNKNOWN")
    state_file = str(state_path(project))
    notes = str(project.get("notes") or "").strip()

    return "\\n".join(filter(None, [
        f"PROJECT SHIFT - {title} (`{pid}`). You are a woken session with no history of"
        " this project, and no memory of any previous shift. Everything you need is in the"
        " LEDGER named below; do not look for a summary of it anywhere else.",
        "",
        "THE PROJECT",
        f"  id            {pid}",
        f"  repo          {where}",
        f"  legacy state  {state_file}   (history only - the ledger is authoritative now)",
        f"  woken at      {now.strftime('%Y-%m-%d %H:%M')}Z by the project-keepalive source",
        ("  notes: " + notes) if notes else "",
        "",
        "STEP 1 - FIND OUT IF YOU ARE EVEN NEEDED.",
        f"  Run:  {LEDGER} claim-next --project {pid} --by keepalive-{pid} --lease 5400",
        "",
        "  * `claimed {{...}}` -> YOU OWN THAT ITEM NOW. Do it. (The item id, its title and",
        "    its definition of done are in the JSON on that line; `--json` is implied.)",
        "  * `already-yours` -> a previous shift died mid-item. Do it, then close it.",
        "  * `held-by-other` -> another shift is on it. Take the next one with",
        f"    `{LEDGER} claim-next --project {pid} --by keepalive-{pid} --lease 5400` again,",
        "    and if every item is held, run `work.py reap` once and retry.",
        "  * `nothing-todo` -> THE PROJECT IS FINISHED OR EXHAUSTED. Do not invent work.",
        "    Record why nothing is left and stop.",
        "",
        "STEP 2 - READ WHAT IS KNOWN BEFORE YOU TOUCH ANYTHING.",
        f"  {LEDGER} show <item-id>      # every previous attempt: what was tried, the",
        "                              # proving command, its OUTPUT, and what was left over",
        "  The attempt history is the memory you do not have. If a previous shift already",
        "  proved something, you do NOT need to re-prove it - build on it. If a previous",
        "  shift recorded a MEASURED blocker, do not rediscover it; either it is still true",
        "  (say so, move on) or you have new information that falsifies it.",
        "",
        "STEP 3 - DO THE ITEM, AND PROVE IT.",
        '  DONE requires THE COMMAND THAT PROVES IT, quoted with its output: the test run,',
        "  the curl, the diff, the exit code. \\"I changed it\\" is not done. If the item's",
        "  `dod` names a command, run THAT command and quote its result line.",
        "",
        "STEP 4 - WRITE BACK BEFORE YOU FINISH. THIS IS THE STEP THAT MAKES THE SYSTEM WORK;",
        "  a shift that does the work and does not write it down has cost money and taught",
        "  the next shift nothing. One call, always, including when you failed:",
        "",
        f"    {LEDGER} close <item-id> --by keepalive-{pid} \\\\",
        "        --did '<what you actually did, one or two lines>' \\\\",
        "        --proof '<the exact command you ran>' \\\\",
        "        --result '<its output, quoted, at least the result line>' \\\\",
        "        --left '<what is still open in this item, or empty if finished>'",
        "",
        "  Add `--state done` when it is finished (the default is `todo`: work remains).",
        "  `--state blocked --blocked-on '<who or what>'` when only a person or an external",
        "  thing can unblock it - and then TAKE ANOTHER ITEM IN THIS SAME SHIFT.",
        "  A close with no --proof and --result is RECORDED AS NOT DONE, on purpose.",
        "",
        "STEP 5 - IF YOU FIND NEW WORK, FILE IT. The ledger is the backlog, and a shift that",
        "  discovered real work is the best source of items:",
        f"    {LEDGER} add --project {pid} --title '<one line>' \\\\",
        "        --dod '<the command that will prove it>' --priority <1-9> \\\\",
        "        --why '<why it matters, one line>'",
        "  `--priority 1` is a blocker, `5` is normal, `9` is nice-to-have. Do NOT file items",
        "  to keep a loop alive; an item with no provable definition of done is not an item.",
        "",
        "STEP 6 - THE LEGACY STATE FILE. You may bring it current (it is what a human reads",
        f"  first), but it is NOT where work is tracked:  {state_file}",
        "  Keep `work_remaining` true only if real work remains, and describe it in terms the",
        "  ledger agrees with. If the two disagree, THE LEDGER IS RIGHT.",
        "",
        "STEP 7 - TELL HIM, IF YOU ASKED HIM ANYTHING. If you filed an owner-queue row (step",
        "  (b) below), the owner will NOT see it until something reaches his phone, and a",
        "  question he never sees is a question he never answers. So after filing it, send him",
        "  ONE short text with the question and your recommendation. This is the only outbound",
        "  message a shift may send, it may go ONLY to the owner, and it must be short:",
        "",
        "    printf '%s' 'THE QUESTION IN ONE LINE. I recommend <what you would do>.' > /tmp/reply.txt",
        "    python3 ~/bin/textsend.py send --to +18483897895 --body-file /tmp/reply.txt --send",
        "",
        "  (Create the file with a heredoc or printf, then send it - never put a body with",
        "  quotes or newlines on the command line.) The send is gated: the owner's own number",
        "  is OPEN by construction, and anything else is refused. Read the result line back and",
        "  quote it. Never write a price, a date, a commitment or a legal posture into it.",
        "",
        "STOPPING. Stop for exactly one of three reasons, and say which:",
        "  (a) DONE - quote the proving command and its output, and name what is next.",
        "  (b) BLOCKED-ON-OWNER - it needs a decision only a person can make. File ONE row",
        "      and only one, then MOVE ON to the next item in this same shift:",
        "        python3 ~/bin/owner-queue.py add \\\\",
        "          --question '<the exact question, in one line>' \\\\",
        "          --recommendation '<what you would do if it were yours>' \\\\",
        "          --options '<option a>|<option b>|<option c>'",
        "      Do not wait for the answer, do not ask again, do not stop.",
        "  (c) NOTHING-LEFT - the ledger has no todo item for this project. Say so and stop.",
        "  A SHIFT MAY NEVER END WITH WORK IT DID NOT START BECAUSE IT WAS WAITING FOR A",
        "  PERSON. Waiting is not a status; it is a reason to start the next thing. In the",
        '  owner\\'s words: "if they run into problems or any decisions they should add them',
        '  to the owner queue and I\\'ll get to them and then they should move on to the next',
        '  thing while they\\'re waiting for me to respond."',
        "",
        "HARD LIMITS",
        "  * Do NOT contact the owner or any customer: no email, no SMS, no call. The owner",
        "    queue is the only channel to him, and a shift never sends anything outbound.",        "  * Do NOT raise a wake flag. The dispatcher sets WAKE_SESSION=1 and the store",
        "    refuses; raising one would start a session that starts a session.",
        "  * Do NOT touch cron, and do not restart production services.",
        "  * Do NOT commit to main, never force-push, never `git reset --hard`, never",
        "    `rm -rf`. Work on a branch and leave it pushed for the integrator.",
        "  * Do NOT mark done what you did not do, and do not report a number you did not",
        "    read. An honest \\"not verified\\" is worth more than a confident guess.",
        "",
        "REPORT AT THE END: the item id, what you did, the command that proves it with its",
        "output, and what the ledger now says about this item and this project.",
    ]))
'''


def find_func(text: str):
    start = text.find("def standing_contract(")
    if start < 0:
        raise SystemExit("ERROR: standing_contract() not found - refusing to guess")
    # the function ends at the next top-level comment banner after it
    m = re.compile(r"\n\n\n# -{3,} #\n# the source").search(text, start)
    if not m:
        raise SystemExit("ERROR: could not find the end of standing_contract()")
    return start, m.start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)
    src = p.read_text(encoding="utf-8")
    if a.verify:
        ok = "PROJECT SHIFT - " in src and "close <item-id>" in src and "claim-next" in src
        print("contract=%s" % ("LEDGER-DRIVEN" if ok else "OLD"))
        return 0 if ok else 1
    start, end = find_func(src)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = p.with_suffix(".py.bak-ledger-contract-%s" % stamp)
    shutil.copy2(p, bak)
    new = src[:start] + NEW_FUNC + src[end:]
    compile(new, str(p), "exec")          # never write a file that cannot even parse
    if a.apply:
        p.write_text(new, encoding="utf-8")
        print("patched %s (backup %s)" % (p, bak.name))
    else:
        print("dry run ok: %d bytes -> %d bytes (use --apply)" % (len(src), len(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
