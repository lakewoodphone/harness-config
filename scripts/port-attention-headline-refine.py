"""Refine the attention-debt headlines: rank what is actionable, and disambiguate.

First attempt (applied, then inspected) produced a useless line:

    waiting: Critical security alert | Critical security alert

Two findings, because it queried only the highest-urgency held rows and the two
top rows are Google security alerts for two DIFFERENT accounts
(ezabz68@gmail.com and lakewoodphoneandtech@gmail.com) -- the (reason, body) dedup
was right to keep both, since their bodies differ in the Acct line. The headline
was wrong: it took only the Subject, which is identical.

Also visible in the data: six of the eight top rows are `owner_briefing_*` from
2026-08-06..08-21, weeks-old briefings counted as `critical` urgency. Naming a
stale briefing as "what is waiting" is noise; the count already covers it.

So this ranks by what the owner can act on (urgent_email first), disambiguates by
account, and drops duplicate headlines.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("ck/sentinel.py")
BACKUP = Path(".runtime/deploy-backups/handport-attention-headline2.py.pre")

ORDER_OLD = '''    held_samples = sources.rows(
        "SELECT urgency, reason, body FROM owner_message_queue WHERE status='held' "
        "ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
        "WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT 3",
        name="held_samples",
    )
'''
ORDER_NEW = '''    held_samples = sources.rows(
        "SELECT urgency, reason, body FROM owner_message_queue WHERE status='held' "
        "ORDER BY CASE WHEN reason = 'urgent_email' THEN 0 "
        "WHEN reason LIKE 'sync_breaker%' THEN 2 ELSE 1 END, "
        "CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
        "WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT 4",
        name="held_samples",
    )
'''

HEAD_OLD = '''    text = str(body or "").replace("\\r", "")
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
HEAD_NEW = '''    text = str(body or "").replace("\\r", "")
    lines = [ln.strip() for ln in text.split("\\n") if ln.strip()]
    subj = frm = acct = ""
    for ln in lines:
        low = ln.lower()
        if low.startswith("subj:"):
            subj = ln[5:].strip()
        elif low.startswith("from:"):
            frm = ln[5:].strip()
        elif low.startswith("acct:"):
            acct = ln[5:].strip()
    pick = subj
    if not pick and lines:
        if lines[0].lower().startswith("urgent email") and len(lines) > 1:
            pick = lines[1]
        else:
            pick = lines[0]
    # Two different alerts routinely share a subject ("Critical security alert"
    # for two Google accounts), so carry the discriminator that makes it unique.
    tag = acct or (frm.split("<")[0].strip() if frm else "")
    if tag:
        pick = f"{pick} ({tag})" if pick else tag
    if len(pick) > limit:
        pick = pick[: limit - 3].rstrip() + "..."
    return pick
'''

DEDUP_OLD = '''    held_headlines = [
        _headline(r.get("body") or "")
        for r in (dict(x) for x in (held_samples.value or []))
    ]
    held_headlines = [h for h in held_headlines if h][:2]
'''
DEDUP_NEW = '''    seen_headlines: set[str] = set()
    held_headlines: list[str] = []
    for r in (dict(x) for x in (held_samples.value or [])):
        line = _headline(r.get("body") or "")
        if line and line not in seen_headlines:
            seen_headlines.add(line)
            held_headlines.append(line)
        if len(held_headlines) == 2:
            break
'''

EDITS = [
    ("rank-actionable-first", ORDER_OLD, ORDER_NEW),
    ("disambiguate-headline", HEAD_OLD, HEAD_NEW),
    ("drop-duplicate-headlines", DEDUP_OLD, DEDUP_NEW),
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

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    before = hashlib.sha256(text.encode()).hexdigest()

    new = text
    for _n, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    checks = [
        ("ranks actionable first", "WHEN reason = 'urgent_email' THEN 0" in new),
        ("disambiguates by account", "tag = acct or" in new),
        ("dedupes headlines", "seen_headlines" in new),
        ("still names content in the summary", '"waiting: " + " | ".join(held_headlines)' in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
