#!/usr/bin/env python3
"""Have two shifts ever run at the same time on the SAME project's checkout?

WHY THIS MATTERS. Every woken release works in one git checkout - lpt-website's is
/root/repos/phone-and-tech-full, a 1.6 GB tree with 25 linked worktrees - and the estate's own rule is
"one owner per shared resource per fleet". Two sessions in that tree at once is how a checkout gets a
half-applied edit, a stash nobody asked for, or a branch switch under someone's feet. The fan-out
deliberately runs several releases concurrently (wake-fanout.sh, per-instance stage dirs and locks), so
this is a real question, not a theoretical one.

READ-ONLY. It reads wake-dispatch.log and prints the overlaps it finds.

  where-are-shifts-overlapping.py [--days 3]
"""
import re
import sys
from datetime import datetime, timedelta

LOG = "/root/.sms-inbox/wake-dispatch.log"
RELEASE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\s+releasing wake #(\d+) \(([^)]*)\)")
DONE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\s+wake #(\d+).*?dur=(\d+)s", re.I)


def project_of(subject: str) -> str | None:
    """The project a subject belongs to: `project:<id>:...`, `<source>:<id>:...`, else the prefix."""
    parts = subject.split(":")
    if len(parts) >= 2 and parts[1]:
        return parts[1] if parts[0] in ("project", "checkout-health", "ledger", "sms-desk") else parts[0]
    return parts[0] or None


def main() -> int:
    days = 3
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = datetime.utcnow() - timedelta(days=days)
    starts = {}
    spans = []
    for line in open(LOG, encoding="utf-8", errors="replace"):
        m = RELEASE.match(line)
        if m:
            when = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
            starts[m.group(2)] = (when, m.group(3))
            continue
        m = DONE.match(line)
        if m:
            # the completion line names the id; the start time comes from the release line
            rid = m.group(2)
            if rid in starts:
                begin, subject = starts.pop(rid)
                dur = int(m.group(3))
                spans.append({"id": rid, "subject": subject, "project": project_of(subject),
                              "begin": begin, "end": begin + timedelta(seconds=dur)})
    for rid, (begin, subject) in starts.items():          # still running or killed
        spans.append({"id": rid, "subject": subject, "project": project_of(subject),
                      "begin": begin, "end": begin + timedelta(seconds=3600)})
    spans = [s for s in spans if s["begin"] >= since]
    spans.sort(key=lambda s: s["begin"])
    print("releases in the last %d day(s): %d" % (days, len(spans)))

    overlaps = []
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            if b["begin"] >= a["end"]:
                break
            if a["project"] and a["project"] == b["project"] and a["id"] != b["id"]:
                overlaps.append((a, b))
    if not overlaps:
        print("SAME-PROJECT OVERLAP: none - no two releases of one project have shared the window")
        return 0
    print("SAME-PROJECT OVERLAPS: %d" % len(overlaps))
    for a, b in overlaps[-12:]:
        secs = int((min(a["end"], b["end"]) - b["begin"]).total_seconds())
        print("  %s  #%s(%s) overlapped #%s(%s) by %ss  [%s]" % (
            b["begin"].strftime("%Y-%m-%dT%H:%M:%SZ"), a["id"], a["subject"][:34],
            b["id"], b["subject"][:34], secs, a["project"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
