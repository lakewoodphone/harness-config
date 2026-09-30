#!/usr/bin/env python3
"""Integrate the 2026 research findings that were never filed: turn recommendations into work.

WHY. Four research passes landed on 2026-09-30 with sources (the landscape, our own tool stack, always-on
infrastructure, memory and context economics, and self-improvement) and produced about fifty candidate
improvements. Only the audit half of them was filed. The rest sat in documents, and a recommendation in a
document is worth nothing - this system's own history is 55 improvements that piled up unapplied because
writing them was cheap and closing them was not. So each of these is a ledger item with a command-shaped
definition of done, or it does not exist.

WHAT IS ALREADY FILED AND DELIBERATELY NOT REPEATED: 150 the external dead-man switch, 152 the model id
resolved at runtime, 153 the cache-prefix and cache telemetry, 154 the headless browse path with the two
dead MCP families dropped, 143 to 145 and 161 from the autonomy audit.
"""
import re
import subprocess
import sys

WORK = "/home/zabz/bin/work.py"
SRC = "research-20260930"

ITEMS = [
    ("housekeeping", 1,
     "Cut re-sent context with a generated 2,000-token shift packet instead of a prompt that re-derives the world",
     "A script renders the packet from the ledger, the project state and the journal index, in a fixed order whose first 700 bytes are byte-identical between shifts. Measure tokens per shift for 10 shifts before and 10 after and quote both medians; the packet itself must be under 2,200 tokens, measured.",
     "Measured cost of one shift is 3 to 5 million tokens, mostly cache-hit input, and the research puts this at about 90 percent of the prefix-cost line (B4 section 4 and 6). A packet that is generated once and byte-stable also protects the cache prefix, which is where the other 30 to 60 percent sits."),

    ("housekeeping", 1,
     "Compile every new incident into one executable check, so a lesson cannot close as prose",
     "The pain journal entry shape gains a required proof_command field and a validator rejects an entry without one; a job then scaffolds a failing check from it. Prove it by filing one real pain entry with a command and showing the validator refuse one without, quoting both.",
     "Measured baseline from the self-improvement research: about 3.4 percent of removals in the technical-debt literature ever added a targeted test, and this tree carries over 300 open pain entries. Prose does not enforce itself, which is why the improvement loop has never closed (B6 section 1 and 4)."),

    ("housekeeping", 1,
     "An outcome table with pass^k, not a single success rate",
     "One row per closed item carrying exit code, the proof command and its result; a weekly report repeats identical items and reports pass^4 to pass^8. Prove it by backfilling one project and printing the report with the repeat count quoted.",
     "Single-run success rates lie: the reference benchmark shows pass^8 under 25 percent for agents that look much better on one attempt, and a rising success rate with a flat pass^k is the signature of automation gaming its own task (B6 section 7, item SI-3)."),

    ("housekeeping", 2,
     "A guard registry checked by a different process, because a self-check is not a check",
     "guards.yaml lists the guards that matter with their check commands; a separate cron job exits non-zero when one is missing, disabled or failing; changing a guard requires an owner approval record. Prove it by disabling one guard on a copy and showing the checker exit non-zero, then restoring it.",
     "The failure to design against is a self-modification that silently turns off a safety check, and the published evidence is that agents attempt exactly that. A guard verified by the same process that could disable it is not a guard (B6 section 6, item SI-5)."),

    ("housekeeping", 2,
     "Per-turn checkpointing of a shift, so a killed session resumes instead of re-paying for its tokens",
     "Append each turn's messages and tool results to a durable run_events table as they happen, and prove a resume by killing a shift mid-run and continuing it with no repeated tool call and no repeated token spend, quoting the event log across the kill.",
     "A release killed at 20 minutes currently costs the whole run, and the infrastructure research counts checkpoint-and-resume as the table stake this system lacks: the field moved to replay precisely because retry-from-scratch is unaffordable (B3 section 8 item 5, B1 table stakes)."),

    ("housekeeping", 2,
     "A persistent logged-in browser profile, and screenshots the seat can actually read",
     "Playwright runs with a persistent user-data-dir so a login survives between sessions, and a screenshot path delivers an image the seat can read. Prove it by logging into one portal by hand once, then in a new session reaching an authenticated page without logging in again, quoting both.",
     "It is our only real browser and every login currently dies with the browser, so supplier portals and seller tools are one-shot at best (B2 section 6). This is also what makes a browser on the server worth having."),

    ("housekeeping", 3,
     "Pilot Coral as a retrieval layer over our own systems, with our own benchmark and our own numbers",
     "Stand up the Apache-2.0 self-hosted build against at least two internal sources, then reproduce a bounded benchmark on 10 of our own retrieval tasks, MCP versus Coral, measuring tool calls and cost, and quote both. If it does not win on our tasks, record that and drop it.",
     "The vendor benchmark claims plus 31 percent accuracy and minus 70 percent cost on complex multi-hop tasks, run on one model in their sandbox and unreplicated, so the direction is credible and the magnitude is not. Our agent work is heavily retrieval-bound, so this is the one external tool worth a bounded test (B1 section 5, item LS-8)."),
]


def main():
    filed, tracked, failed = [], [], []
    for project, prio, title, dod, why in ITEMS:
        p = subprocess.run(["python3", WORK, "add", "--project", project, "--title", title, "--dod", dod,
                            "--why", why, "--priority", str(prio), "--source", SRC],
                           capture_output=True, text=True, timeout=120)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        m = re.search(r'"id":\s*(\d+)', out)
        if "item-filed" in out:
            filed.append((int(m.group(1)) if m else None, title))
        elif "already-filed" in out:
            tracked.append(title)
        else:
            failed.append((title[:60], (out or "no output")[:140]))
    print("filed %d, already tracked %d, failed %d" % (len(filed), len(tracked), len(failed)))
    for i, t in filed:
        print("  #%s %s" % (i, t[:84]))
    for t, o in failed:
        print("  FAILED %s :: %s" % (t, o))
    return 0


if __name__ == "__main__":
    sys.exit(main())
