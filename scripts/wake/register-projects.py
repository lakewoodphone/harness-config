#!/usr/bin/env python3
"""Register every project the owner named, so each one gets a daily shift.

MEASURED 2026-09-28: `~/bin/sources/projects.json` held THREE projects - kosher-ai-filter,
lpt-website, and `waste-system` (which is disabled and does not exist) - while the owner named
at least nine in the same breath. The other six therefore had NO source that would ever start a
shift for them, which is exactly why "the CFO has to be run" and "the LPT syncing system has to
be constantly worked on" never happened: nothing was looking at them.

The shift contract now reads its work from the ledger (`~/bin/work.py`), so a project entry
here means "file one shift per day that claims from the ledger for this id". I add an entry for
each named project, and set `ledger_only: true` on the ones that have no per-project state file
yet, so nobody later mistakes a shared pointer for a real file.

It is safe to run repeatedly: existing ids are left exactly as they are.

Usage: python3 register-projects.py --dry-run | --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REG = Path("/home/zabz/bin/sources/projects.json")
STATE_DIR = "/home/zabz/.wake-projects"

# id -> (title, repo, state_file basename or None, note)
NEW = {
    "lpt-sync": (
        "LPT sync chain: Dialpad -> LPT hub -> production database -> website",
        "/home/zabz/repos/lpt-hub",
        None,
        "The owner names this repeatedly ('the LPT syncing system between dialpad, LPT hub, the "
        "production database and more needs to be constantly worked on and actually synced'). "
        "Ledger-driven: its items live in ~/bin/work.py under project 'lpt-sync'. No per-project "
        "state file - the ledger is the state.",
    ),
    "cfo": (
        "CFO / QuickBooks: the books, the close, and the finance audits",
        "/home/zabz/repos/quickbooks-agent",
        None,
        "Owner: 'let's say there's a CFO that has to be run'. quickbooks-agent is the real repo "
        "(/home/zabz/repos/quickbooks-agent). Ledger-driven.",
    ),
    "personality-system": (
        "Personality test system",
        "/home/zabz/repos",
        None,
        "Owner: 'the personality test system that we were doing needs to be constantly worked on'. "
        "The live AI calls in this system failed for over a week on a hardcoded model name "
        "(docs/dsh-at-scale/60-cost-audit.md and the models-resolve-at-runtime rule), so the "
        "standing item is that a model is resolved from the gateway catalog at runtime. Ledger-driven.",
    ),
    "rental-system": (
        "Rental system",
        "/home/zabz/repos",
        None,
        "Owner named it. REPO NOT YET ESTABLISHED - the first shift's job is to find the real "
        "codebase and record its path in the ledger; if it cannot be found, file ONE owner-queue "
        "row asking for the path, exactly as waste-system was handled.",
    ),
    "chumash": (
        "Bible codes / chumash timeline",
        "/home/zabz/repos",
        None,
        "Owner: 'the Bible codes that we were writing, that whole project needs to be worked on'. "
        "Repo not established (candidates exist on this machine); first shift finds it. Ledger-driven.",
    ),
    "prod-db-sync": (
        "Production database: truth, syncing and freshness",
        "/home/zabz/personal-secretary-mvp",
        None,
        "Owner: 'the production database and more needs to be constantly worked on and actually "
        "synced and set up'. The authoritative DB is 12.37 GB with a 128 MB WAL on a control "
        "plane - size, truth and freshness are all open. Ledger-driven.",
    ),
    "housekeeping": (
        "AI company housekeeping and evolution",
        "/home/zabz/personal-secretary-mvp",
        STATE_DIR + "/housekeeping.json",
        "Owner: 'a lot of times they're a unique standard housekeeping and evolution for the AI "
        "company to begin with'. This is the project the wake/tuner/authority items belong to.",
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    apply = a.apply and not a.dry_run

    doc = json.loads(REG.read_text(encoding="utf-8"))
    have = {p["id"] for p in doc["projects"]}
    added = []
    for pid, (title, repo, state, note) in NEW.items():
        if pid in have:
            print("present: %s" % pid)
            continue
        row = {
            "id": pid,
            "title": title,
            "enabled": True,
            "repo": repo,
            "case": pid,
            "state_file": state or (STATE_DIR + "/%s.json" % pid),
            "cooldown_seconds": 43200,
            "max_flags_per_day": 1,
            "budget_note": ("Owner decision 2026-09-20: 4 autonomous releases/day system-wide, 1 "
                            "per project per day. The system-wide cap was RAISED to 12/day on "
                            "2026-09-28 with the measured cost written into "
                            "harness-config/scripts/wake/patch-wake-cap.py (mean 0.068 USD per "
                            "shift, so 12/day is under 1 USD/day). Each project still gets 1."),
            "notes": note,
        }
        if state is None:
            row["ledger_only"] = True
            row["ledger_only_note"] = (
                "Set 2026-09-28: this project has no per-project state file yet, and it does not "
                "need one - the shift contract reads and writes the work ledger (~/bin/work.py). "
                "The state_file field above is a pointer for continuity only; the ledger is "
                "authoritative and a disagreement between them resolves in the ledger's favour.")
        added.append(row)
        print("ADD: %-20s %s" % (pid, title[:60]))

    if not apply:
        print("\n(dry run: %d to add; use --apply)" % len(added))
        return 0
    if not added:
        print("nothing to add")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(REG, REG.with_name("projects.json.bak-register-%s" % stamp))
    doc["projects"].extend(added)
    doc["caps"]["global_max_flags_per_day"] = 12
    doc["caps"]["owner_decision"] = (
        "2026-09-20: owner was asked how many autonomous wake-ups per day to allow and answered "
        "\"whatever you think, and you can change it over time if needed\". 2026-09-28: raised "
        "from 4 to 12 on measurement - every day 09-20..09-28 hit the 4/4 cap (by 04:17Z from "
        "09-25) while 27 rows sat undispatched, and one shift costs a measured 0.068 USD "
        "(38 priced releases, 2.5825 USD total), so 12/day is about 0.82 USD/day.")
    doc["caps"]["enforcement"] = (
        "global_max_flags_per_day is clamped by the source to wake.py's own WAKE_MAX_PER_DAY "
        "(now 12, aligned with wake-dispatch.sh's MAX_PER_DAY so the looser value cannot win).")
    REG.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %s (+%d projects, cap %s)" % (REG, len(added), doc["caps"]["global_max_flags_per_day"]))

    # SEED A STATE FILE FOR EACH LEDGER-ONLY PROJECT.
    #
    # Without this the source refuses to file anything for them: measured 2026-09-28, the very
    # first dry run after registering all seven came back `SIGNAL UNREADABLE -- no state file at
    # /home/zabz/.wake-projects/lpt-sync.json`. That refusal is CORRECT for a project that is
    # meant to keep its own state, and it is the wrong answer for one whose state is the ledger:
    # it would leave six of the owner's nine projects permanently silent while looking properly
    # configured. So the seed file states exactly that, and nothing more.
    for row in added:
        if not row.get("ledger_only"):
            continue
        sf = Path(row["state_file"])
        if sf.exists():
            print("state file already present: %s" % sf)
            continue
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({
            "project": row["id"],
            "work_remaining": True,
            "remaining": ["not yet seeded: the first shift claims its item from the ledger"],
            "ledger_only": True,
            "note": ("The authoritative state for this project is the work ledger "
                     "(python3 ~/bin/work.py list --project %s). This file exists so the "
                     "keepalive source has a signal to read; it does not own the work." % row["id"]),
            "seeded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, indent=2) + "\n", encoding="utf-8")
        print("seeded state file: %s" % sf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
