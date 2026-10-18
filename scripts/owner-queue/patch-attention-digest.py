#!/usr/bin/env python3
"""One-shot, idempotent patch: point owner_attention.from_owner_queue at THE one queue.

Why: the daily phone digest read `owner-queue.py list --json`, which is decisions only by design --
so every text, call, voicemail and email item the owner queue holds was invisible on the phone. Two
rankings existed: the queue's, and this script's own sort of a narrower set.

Shape of the change:
  * read `queue --json` (the one ordered working set) instead of `list --json`;
  * accept BOTH field shapes, because `list` says question/severity and `queue` says title/tier;
  * survive non-numeric ids -- the one queue also carries held app rows (`m2631`) and agent
    questions, and `int()` on those killed the whole digest on the first real run;
  * ask " Want details?" for news and " Yes?" for a decision, because the relay only opens a reply
    turn when the body ends in a question mark, and "Chase overdraft ... Yes?" is not a question
    anybody can answer.

APPLIED BY LITERAL REPLACEMENT, THEN ASSERTED. An earlier version refused to run when an earlier
replacement had already altered the text a later one looked for; it now applies whatever is present
and then proves the END STATE, which is the only thing that matters. Safe to run repeatedly.
"""
import io
import sys

PATH = "/root/personal-secretary-mvp/scripts/owner_attention.py"
src = io.open(PATH, encoding="utf-8").read()
before = src

REPLACEMENTS = [
    ('["python3", os.path.expanduser("~/bin/owner-queue.py"), "list", "--json"],',
     '["python3", os.path.expanduser("~/bin/owner-queue.py"), "queue", "--json",\n'
     '             "--limit", "2000"],'),
    ('rows = [r for r in rows if r.get("status") == "pending"]',
     'rows = [r for r in rows if r.get("status", "pending") == "pending"]'),
    ('str(r.get("question") or "")', 'str(r.get("question") or r.get("title") or "")'),
    ('r.get("severity")', 'r.get("severity") or r.get("tier")'),
    ('"blocks": str(r.get("blocks") or ""),',
     '"blocks": (str(r.get("blocks") or "") if not isinstance(r.get("blocks"), bool)'
     ' else ("blocking" if r.get("blocks") else "")),'),
    # the composer needs to know WHAT the item is before it can ask the right question
    ('"recommendation": str(r.get("recommendation") or "")[:300],',
     '"recommendation": str(r.get("recommendation") or "")[:300],\n'
     '                "kind": str(r.get("kind") or "decision"),'),
    ('-int(r.get("id") or 0)))',
     '-(int(r.get("id")) if str(r.get("id") or "").isdigit() else 0)))'),
    ('def sms_body(items: list) -> str:',
     'def _tail_q(item) -> str:\n'
     '    """The question that opens an owner turn, worded for what the item IS."""\n'
     '    if str(item.get("kind") or "decision") == "decision":\n'
     '        return " Yes?"\n'
     '    return " Want details?"\n'
     '\n'
     '\n'
     'def sms_body(items: list) -> str:'),
    ('and len(body) + len(" Yes?") <= OWNER_SMS_MAX):',
     'and len(body) + len(_tail_q(item)) <= OWNER_SMS_MAX):'),
    ('        room = max(40, len(body) - len(" Yes?"))\n'
     '        recut = _first_sentence(body, room).rstrip()\n'
     '        if recut and len(recut) < len(body) and recut[-1] in ".!?":\n'
     '            body = recut + " Yes?"\n'
     '        else:\n'
     '            body = body + " Yes?"',
     '        tail = _tail_q(item)\n'
     '        room = max(40, len(body) - len(tail))\n'
     '        recut = _first_sentence(body, room).rstrip()\n'
     '        if recut and len(recut) < len(body) and recut[-1] in ".!?":\n'
     '            body = recut + tail\n'
     '        else:\n'
     '            body = body + tail'),
]

#: The end state, independent of the order anything was applied in.
MUST_CONTAIN = [
    ('queue --json', '"queue", "--json"'),
    ('the 2000 limit', '"--limit", "2000"'),
    ('title fallback', 'r.get("question") or r.get("title")'),
    ('tier fallback', 'r.get("severity") or r.get("tier")'),
    ('safe id sort', 'if str(r.get("id") or "").isdigit() else 0'),
    ('news tail question', 'def _tail_q(item)'),
    ('kind carried to the composer', '"kind": str(r.get("kind") or "decision")'),
    ('tail used for the ceiling', 'len(_tail_q(item)) <= OWNER_SMS_MAX'),
    ('tail used for the cut', 'body = recut + tail'),
]

applied = 0
for old, new in REPLACEMENTS:
    if old in src:
        src = src.replace(old, new)
        applied += 1

missing = [label for label, needle in MUST_CONTAIN if needle not in src]
if missing:
    print("END STATE NOT REACHED — missing: %s" % ", ".join(missing))
    sys.exit(2)

if src == before:
    print("NO-OP: already in the end state (%d marker(s) verified)" % len(MUST_CONTAIN))
    sys.exit(0)

io.open(PATH + ".new", "w", encoding="utf-8", newline="").write(src)
print("wrote %s.new (%d replacement(s) this run, %d end-state marker(s) verified)"
      % (PATH, applied, len(MUST_CONTAIN)))
