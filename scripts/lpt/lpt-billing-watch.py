#!/usr/bin/env python3
"""lpt-billing-watch - turn a GitHub Actions billing block into ONE owner row, automatically.

WHY THIS EXISTS (2026-10-28). The website pipeline has now been stopped three times by the same
thing: GitHub refuses to start hosted jobs with

    The job was not started because recent account payments have failed or your
    spending limit needs to be increased.

and it presents as a CHECK FAILURE, so the head looks red for a code reason. Owner rows 940
(2026-10-21), 1028 (2026-10-25) and 1108 (2026-10-28) were all filed by a human noticing. Tonight I
nearly hunted it as a defect in code I had just written. A stall that only a human notices is how it
went unnoticed twice.

WHAT IT DOES. Reads `lpt-ci-status.py --json`. If any head or PR is `BILLING`, it looks for a pending
owner row that already asks about GitHub Actions billing and, if there is none, files exactly one.
Then it prints one line either way, every time it runs, so `sources.log` shows the state without
anyone re-deriving it.

It never raises a wake flag: a session cannot pay a bill, and a flag would spend money to say so.

  lpt-billing-watch.py [--dry] [--json]
"""
from __future__ import annotations

import json
import subprocess
import sys

CI = "/root/bin/lpt-ci-status.py"
QUEUE = "/root/bin/owner-queue.py"
AUTHORITY = "/root/authority.db"

QUESTION = ("GitHub Actions is refusing to start jobs - the account payment or spending limit is "
            "exhausted, and every merge into the website repo is blocked until it is raised.")
RECOMMENDATION = (
    "Raise the GitHub Actions spending limit (or clear the payment). The exact annotation is: The job "
    "was not started because recent account payments have failed or your spending limit needs to be "
    "increased. This is the third time it has stopped the pipeline (rows 940, 1028, and now). The "
    "durable alternative is to move the three hosted jobs (Detect Changed Files, Check for Phantom "
    "Dependencies, Build image and assert the sha label) onto the self-hosted runners, so a billing "
    "block can never stop the pipeline again.")
OPTIONS = "Raise the limit now|Move the hosted jobs to self-hosted runners|Hold until you decide"


def ci_state() -> dict:
    p = subprocess.run([sys.executable, CI, "--json"], capture_output=True, text=True, timeout=240)
    if p.returncode != 0 or not p.stdout.strip():
        return {"error": (p.stderr or p.stdout)[-200:]}
    return json.loads(p.stdout)


def pending_billing_row() -> int | None:
    """The pending owner row that already asks this, if any. Read-only."""
    import sqlite3
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % AUTHORITY, uri=True)
        row = conn.execute(
            "SELECT id FROM owner_decision_queue WHERE status IN ('pending','held','deferred') "
            "AND (question LIKE '%GitHub Actions%' OR question LIKE '%Actions spending%') "
            "AND (question LIKE '%payment%' OR question LIKE '%spending limit%' OR question LIKE '%budget%') "
            "ORDER BY id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    dry = "--dry" in sys.argv
    data = ci_state()
    if "error" in data:
        print("lpt-billing-watch: could not read CI state: %s" % data["error"])
        return 0

    states = {}
    for br, head in (data.get("heads") or {}).items():
        states["head:" + br] = (head.get("checks") or {}).get("state")
    for pr in data.get("prs") or []:
        states["pr:#%s" % pr["number"]] = pr.get("checks")
    blocked = {k: v for k, v in states.items() if v == "BILLING"}
    if not blocked:
        print("lpt-billing-watch: no billing block (%s)" % ", ".join(
            "%s=%s" % (k, v) for k, v in sorted(states.items())[:4]))
        return 0

    note = ""
    for br, head in (data.get("heads") or {}).items():
        note = note or ((head.get("checks") or {}).get("billing_note") or "")
    existing = pending_billing_row()
    if existing:
        print("lpt-billing-watch: BILLING on %s - already asked (owner row #%s): %s" % (
            ", ".join(sorted(blocked)), existing, note[:120]))
        return 0
    if dry:
        print("lpt-billing-watch: BILLING on %s - WOULD file one owner row (%s)" % (
            ", ".join(sorted(blocked)), note[:100]))
        return 0
    p = subprocess.run([sys.executable, QUEUE, "add", "--question", QUESTION,
                        "--recommendation", RECOMMENDATION, "--options", OPTIONS,
                        "--severity", "high",
                        "--source", "lpt-billing-watch: check-run annotations %s" % note[:160]],
                       capture_output=True, text=True, timeout=180)
    out = (p.stdout or p.stderr or "").strip().splitlines()
    print("lpt-billing-watch: BILLING on %s - filed owner row: %s" % (
        ", ".join(sorted(blocked)), (out[-1] if out else "no output")[:160]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
