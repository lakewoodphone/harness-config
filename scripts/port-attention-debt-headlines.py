"""Make the attention-debt check name WHAT is waiting, not just how much.

The badge renders only `finding.summary` (assets/phone-badge.js:315) -- not
`metrics`. So the owner's badge currently tells him:

    attention_debt | critical | owner-attention debt: 7 critical message(s)
                              held; 38 urgent message(s) held; oldest question 134d old

He learns that 45 messages are held and never what they are. The bodies are in
the database and in the payload's metrics; nothing puts them in front of him.

This adds a second query for the highest-urgency held messages and names up to
two of them in the summary, so the one line the badge shows carries the content:

    ... ; waiting: [Netlify] Action needed: ableTelSolutions has used ... | ...

No change to the badge, no outbound message, and the check's severity/ok logic is
untouched. Gated like the other ports: every anchor must match exactly once.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("ck/sentinel.py")
BACKUP = Path(".runtime/deploy-backups/handport-attention-debt.py.pre")

HEADLINE_FN = '''

def _headline(body: str, limit: int = 52) -> str:
    """One short human line from a queued owner message body.

    Owner-queue bodies are multi-line ("URGENT EMAIL\\nFrom: ...\\nSubj: ..."). The
    Subject is the part that says what the thing is, so prefer it; otherwise the
    first meaningful line. Truncated with an ASCII ellipsis so the summary stays a
    single readable line on a phone.
    """
    text = str(body or "").replace("\\r", "")
    lines = [ln.strip() for ln in text.split("\\n") if ln.strip()]
    pick = ""
    for ln in lines:
        if ln.lower().startswith("subj:"):
            pick = ln[5:].strip()
            break
    if not pick and lines:
        pick = lines[1] if lines[0].lower().startswith("urgent email") and len(lines) > 1 else lines[0]
    if len(pick) > limit:
        pick = pick[: limit - 3].rstrip() + "..."
    return pick

'''

QUERY_OLD = '''    held = sources.rows(
        "SELECT status, urgency, COUNT(*) AS n FROM owner_message_queue "
        "WHERE status='held' GROUP BY status, urgency ORDER BY n DESC",
        name="held_messages",
    )
'''

QUERY_NEW = '''    held = sources.rows(
        "SELECT status, urgency, COUNT(*) AS n FROM owner_message_queue "
        "WHERE status='held' GROUP BY status, urgency ORDER BY n DESC",
        name="held_messages",
    )
    # What is actually waiting, not just how much: the badge renders only
    # `summary`, so the content has to reach this check to reach the owner.
    held_samples = sources.rows(
        "SELECT urgency, reason, body FROM owner_message_queue WHERE status='held' "
        "ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
        "WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT 3",
        name="held_samples",
    )
'''

REFUSE_OLD = """    refusals = [r for p in (pending, oldest, held) for r in p.refusals]
    prov = [_pkt_note(p) for p in (pending, oldest, held)]
"""
REFUSE_NEW = """    refusals = [r for p in (pending, oldest, held, held_samples) for r in p.refusals]
    prov = [_pkt_note(p) for p in (pending, oldest, held, held_samples)]
"""

METRICS_OLD = '''    metrics = {
        "pending_questions": int(pending.value or 0),
'''
METRICS_NEW = '''    held_headlines = [
        _headline(r.get("body") or "")
        for r in (dict(x) for x in (held_samples.value or []))
    ]
    held_headlines = [h for h in held_headlines if h][:2]

    metrics = {
        "pending_questions": int(pending.value or 0),
        "held_headlines": held_headlines,
'''

PROBLEM_OLD = '''    if urgent:
        problems.append(f"{urgent} urgent message(s) held")
'''
PROBLEM_NEW = '''    if urgent:
        problems.append(f"{urgent} urgent message(s) held")
    if held_headlines:
        # The one line the badge shows now says what is waiting.
        problems.append("waiting: " + " | ".join(held_headlines))
'''

NOTE_OLD = "def _pkt_note(pkt: pv.Packet) -> str:\n    return pkt.brief()\n"
NOTE_NEW = "def _pkt_note(pkt: pv.Packet) -> str:\n    return pkt.brief()\n" + HEADLINE_FN

EDITS = [
    ("headline-helper", NOTE_OLD, NOTE_NEW),
    ("held-samples-query", QUERY_OLD, QUERY_NEW),
    ("refusals-provenance", REFUSE_OLD, REFUSE_NEW),
    ("metrics-headlines", METRICS_OLD, METRICS_NEW),
    ("summary-names-content", PROBLEM_OLD, PROBLEM_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  anchor {name!r} matched {n} time(s), need exactly 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text
    for _n, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    checks = [
        ("helper defined", "def _headline(" in new),
        ("samples queried", "held_samples = sources.rows(" in new),
        ("samples in refusals", "held, held_samples)" in new),
        ("headlines in metrics", '"held_headlines": held_headlines' in new),
        ("summary names content", '"waiting: " + " | ".join(held_headlines)' in new),
        ("severity logic untouched", "sev = CRITICAL if critical else HIGH" in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 before: {before}")
    print(f"sha256 after:  {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"bytes: {len(text)} -> {len(new)}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
