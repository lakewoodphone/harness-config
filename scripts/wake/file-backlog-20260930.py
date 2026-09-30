#!/usr/bin/env python3
"""File the 2026-09-30 capability-backlog items that have a command-shaped definition of done.

WHY THIS EXISTS. The audit produced 38 topics. Hand-coding them one at a time is single-thread work and it
is what the owner has been asking to stop: he should not have to tell the machine what to do next. The
ledger is the machine's own work queue, and a woken shift claims one item and proves it. So the backlog
becomes items.

WHAT IS DELIBERATELY NOT FILED. Every item here carries a definition of done that is a COMMAND whose
output a reviewer can read. Topics whose finish line is a judgement ("adopt a pilot", "reconsider the
sandbox vendor") stay in the doc, because a ledger item without a proving command is how a queue fills with
things that can never be closed.

Deduplication is work.py's own: it refuses a second open item with the same title, and this script reports
per item whether it filed or found one already tracked. Dry run by default; `--apply` to write.

Usage:
    file-backlog-20260930.py             show what would be filed
    file-backlog-20260930.py --apply     file it
"""
import argparse
import json
import re
import subprocess
import sys

WORK = "/home/zabz/bin/work.py"

ITEMS = [
    ("housekeeping", 1,
     "Wake: commit the result before releasing the lease, so a killed child cannot lose its outcome",
     "A release whose child has written its output file and is then killed still lands a non-empty outcome "
     "that is NOT the ssh banner: prove on a deliberately killed run with "
     "`sqlite3 -readonly ~/.sms-inbox/inbox.db \"select outcome from wake where id=ID\"` and quote it.",
     "16 all-time failed rows carry the ssh post-quantum banner as their outcome, and 5 of 20 are the "
     "work-ran/answer-was-lost class. Every one consumed an attempt and burned tokens."),

    ("housekeeping", 1,
     "Wake: run shifts on the authority itself, with the desktop as a peer node",
     "One real ledger item is closed by a shift that ran on the authority: `wake-dispatch.log` names the "
     "authority as the node for that release and the item carries a proof. Quote both lines.",
     "Proven feasible 2026-09-30: `node .../dsh/lib/bin.js --profile headless` on the authority exited 0 "
     "with LOCAL_SHIFT_OK. Every current release crosses an ssh hop to a desktop, which is where answers "
     "get lost and the only reason a sleeping machine stops the whole company."),

    ("housekeeping", 1,
     "Ledger: a blocked item carries a typed blocker and a revisit time, and a source ages them",
     "`sqlite3 -readonly ~/work/work.db \"select count(*) from work_item where state='blocked' and "
     "(blocked_on is null or revisit_at is null)\"` returns 0, and a source prints every blocked item whose "
     "revisit time has passed. Quote both.",
     "11 of the 15 non-done items are blocked and nothing in the system ever moves one out: the state has "
     "no transition. Four of them wait on a merge role that was never scheduled."),

    ("housekeeping", 1,
     "Supply: a source that files open journal pain entries as ledger items, capped per run",
     "A dry run lists candidates and files nothing; an apply files at most 5 items; a second apply run "
     "files none. Quote all three runs.",
     "304 open pain entries are the machine's own written backlog and no source reads them, while the "
     "dispatcher idles on an empty todo queue. This is the largest available increase in work supply."),

    ("housekeeping", 2,
     "Supply: the CEO kernel sentinel can file exactly one ledger item, deduplicated",
     "A planted sentinel condition produces exactly one ledger item, and a second run produces none. Quote "
     "the two runs and the item id.",
     "`grep -rln wake.py work.py ~/ceo-kernel/` returns nothing: the always-on company cannot create a "
     "single item, so the biggest producer of 'the machine noticed something' has no path to it being fixed."),

    ("housekeeping", 2,
     "Wake: one reconciled budget, printed as one line, from one source",
     "The digest prints the harness spend-guard figures and the wake daily ceiling together with their "
     "sources, and `grep -c` of the raw ceiling constants across the two owners returns 0 copies of a "
     "second number. Quote the digest line.",
     "The harness guard holds 35/80/150 and the wake store holds 70 per day: two different numbers for one "
     "budget, neither visible in one place. A cap that reads a different measurement than the thing it caps "
     "is how this system has failed before."),

    ("housekeeping", 2,
     "Wake: value metering - items closed with a proof, and dollars per closed item",
     "The digest prints both numbers and each matches a hand-computed SQL count for the same day. Quote "
     "the line and the two queries.",
     "`wake.py stats` already warns that a release is a session started and not work done (133 releases "
     "over 41 distinct ids on 2026-09-29). Without this line no change in this backlog can be judged."),

    ("housekeeping", 2,
     "Wake: an external dead-man switch that fires when both heartbeats stop",
     "A checker exits non-zero when either heartbeat is older than twice its interval, proven against a "
     "copy holding a stale value; the alert send stays gated on the owner's approval. Quote the non-zero "
     "run.",
     "Both heartbeats exist and nothing off the authority reads them: if the authority dies, its own health "
     "checks die with it. This is the only mechanism that turns a silent stop into a loud one."),

    ("housekeeping", 2,
     "Wake: one writer for the wake store, or WAL plus a generous busy timeout everywhere",
     "A 24-hour window contains zero 'database is locked' lines across the wake logs. Quote the count and "
     "the window.",
     "Eight or more writers contend on inbox.db, and a heartbeat that cannot write kills the session so it "
     "cannot be double-run: row 125 was killed at 655 seconds for exactly that, and today's log has a lock "
     "storm from 00:07Z to 00:40Z."),

    ("personality-system", 1,
     "Resolve the model at runtime: remove the literal model id from the seat and every headless profile",
     "No literal model id remains in ~/.dsh/settings.yaml or anywhere in the wake path, and a woken shift "
     "records which model actually served it. Quote the config and the recorded line.",
     "`agent-default-model: {provider: deepseek-official, model: deepseek-flash}` is what every headless "
     "shift boots with. This is the documented time bomb that already broke the personality system for over "
     "a week behind a plausible-looking fallback, and the gateway already offers runtime aliases."),

    ("housekeeping", 2,
     "Cost: a byte-stable cached prefix in the shift prompt, plus cache-read telemetry per shift",
     "Twenty consecutive shifts log cache_read_pct and the median is above 80%, with the prefix hash "
     "recorded. Quote the median and one raw line.",
     "Cache reads cost roughly a tenth of writes, so one changed byte above the cache breakpoint re-bills "
     "the whole prefix. Measured shape gives 30-60% off input cost for a change that touches no behaviour."),

    ("housekeeping", 2,
     "Headless workers get a browse path, and the two unused MCP families are dropped",
     "A mesh child can call a search tool and reach ps_* , and the preset shows exactly two fewer MCP rows; "
     "quote the child's tool call and the before/after row count.",
     "Headless children get no MCP tools at all, so the fleet cannot scrape, cannot drive a logged-in "
     "browser and cannot query the company database. Meanwhile mcp-fetch and mcp-context7 cost about 2,196 "
     "tokens on every request for 5 and 1 uses across 1,611 sessions."),

    ("rental-system", 1,
     "Integrate origin/fix/rentals-origin-master-race-90 into master",
     "master contains the branch and the project's own tests pass afterwards with their result lines "
     "quoted; `git diff --diff-filter=D --name-only master HEAD` is empty.",
     "A reviewed fix for a live SQLite race sits unmerged. Merging is now authorized for integration items "
     "(decision D2841), so the only thing missing was a scheduled integrator, which now exists."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    filed, tracked, failed = [], [], []
    for project, prio, title, dod, why in ITEMS:
        args = ["python3", WORK, "add", "--project", project, "--title", title, "--dod", dod,
                "--why", why, "--priority", str(prio), "--source", "backlog-20260930"]
        if not a.apply:
            print("WOULD FILE [%s p%d] %s" % (project, prio, title[:88]))
            continue
        # NOTE: work.py's add subcommand has no --json. Passing it made every call die with an argparse
        # error on stderr while stdout stayed empty, which this script reported as 13 silent failures.
        # Capture stderr too, and classify on the words the tool actually prints.
        p = subprocess.run(args, capture_output=True, text=True, timeout=120)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        m = re.search(r'"id":\s*(\d+)', out)
        if "item-filed" in out:
            filed.append((int(m.group(1)) if m else None, title))
        elif "already-filed" in out:
            tracked.append(title)
        else:
            failed.append((title, (out or "no output at all")[:160]))
    if a.apply:
        print("filed %d, already tracked %d, failed %d" % (len(filed), len(tracked), len(failed)))
        for i, t in filed:
            print("  #%s %s" % (i, t[:88]))
        for t, o in failed:
            print("  FAILED %s :: %s" % (t[:60], o))
    return 0


if __name__ == "__main__":
    sys.exit(main())
