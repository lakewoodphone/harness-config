#!/usr/bin/env python3
"""ledger-keepalive - a wake source driven by the WORK LEDGER, not by a per-project JSON blob.

THE GAP THIS CLOSES. `project-keepalive` decides whether to file a shift by reading
`/home/zabz/.wake-projects/<id>.json` and trusting a `work_remaining` boolean. Since 2026-09-28 the
ledger is the authority for what work exists - a shift claims from it, closes into it, and files new
items in it - but the thing that DECIDES TO WAKE is still reading the blob. So a project whose blob
says `work_remaining: false` goes permanently quiet while items sit in the ledger, and a shift that
forgets to rewrite the blob silently stops its own project's loop. The daily loop must be driven by
the same store it writes to, or "self-renewing" is a coincidence.

WHAT IT DOES. For every enabled project: ask the ledger whether it has any `todo` item. If it does,
file ONE shift flag (subject `project:<id>:<utc-date>`, exactly the subject project-keepalive uses, so
the two sources cannot file two shifts for one project on one day), carrying the same ledger-driven
contract. If the project has no todo items, file nothing and say so.

WHAT IT DOES NOT DO. It never invents work: an empty project is reported as finished, not given
invented items. It never raises a flag from inside a woken session (`WAKE_SESSION` is honoured by the
store). It is capped by the store's own daily guard, read live from `wake.py stats`, so it can never
push past the ceiling the owner set.

Usage: python3 ledger-keepalive.py [--dry-run] [--project ID]
Exit: always 0 (a source that breaks its caller is worse than no source). "quiet" on stdout means
nothing to file, which is the contract every source in this directory follows.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")
WORK_DB = os.environ.get("WORK_DB") or str(Path.home() / "work" / "work.db")
WAKE_CLI = os.environ.get("WAKE_CLI") or str(Path.home() / "bin" / "wake.py")
REGISTRY = Path(os.environ.get("WORK_REGISTRY") or (HERE / "projects.json"))
SOURCE = "ledger-keepalive"


def load_contract_renderer():
    """Reuse project-keepalive's contract so both sources produce IDENTICAL shift prompts."""
    path = HERE / "project-keepalive.py"
    spec = importlib.util.spec_from_file_location("pk_contract", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pk_contract"] = mod
    spec.loader.exec_module(mod)
    return mod


def ledger_todos(project: str) -> list:
    """[(id, priority, title)] for the project's todo items, oldest-priority first."""
    if not Path(WORK_DB).exists():
        return []
    c = sqlite3.connect(WORK_DB, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT id, priority, title FROM work_item WHERE project=? AND state='todo' "
            "ORDER BY priority ASC, created_at ASC", (project,)).fetchall()
        return [(r["id"], r["priority"], r["title"]) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        c.close()


def wake_budget() -> dict:
    """The store's own numbers, read live. Never restate a cap here - that is how 4 survived 12."""
    try:
        p = subprocess.run(["python3", WAKE_CLI, "stats", "--json"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=90)
        d = json.loads(p.stdout or "{}")
        caps = d.get("caps") or {}
        return {"released": d.get("released_today"), "max_per_day": caps.get("max_per_day"),
                "spend": d.get("spend_today_usd"), "ceiling": caps.get("max_usd_per_day"),
                "ok": True}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project")
    a = ap.parse_args()

    try:
        doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as exc:
        print("error:registry-unreadable: %s: %s" % (type(exc).__name__, exc))
        return 0

    pk = load_contract_renderer()
    budget = wake_budget()
    now = datetime.datetime.now(datetime.timezone.utc)
    day = now.strftime("%Y%m%d")
    filed, empty, gated = [], [], []

    for row in doc.get("projects", []):
        pid = row.get("id")
        if not row.get("enabled") or (a.project and pid != a.project):
            continue
        todos = ledger_todos(pid)
        if not todos:
            empty.append(pid)
            continue
        if budget.get("ok") and budget.get("max_per_day"):
            if (budget.get("released") or 0) >= int(budget["max_per_day"]):
                gated.append("%s (daily backstop %s/%s)" % (pid, budget["released"], budget["max_per_day"]))
                continue
        if budget.get("ok") and budget.get("ceiling") and budget.get("spend") is not None:
            if float(budget["spend"]) >= float(budget["ceiling"]):
                gated.append("%s (spend %s >= ceiling %s)" % (pid, budget["spend"], budget["ceiling"]))
                continue
        top = ", ".join("#%d %s" % (i, t[:48]) for i, pr, t in todos[:3])
        context = ("ledger-keepalive: %s has %d todo item(s) in the ledger (%s); "
                   "system-wide released today %s" % (pid, len(todos), top, budget.get("released")))
        try:
            prompt = pk.standing_contract(row, pk.load_state(row), ["(from the ledger)"], now)
        except Exception as exc:
            print("error:contract-render: %s: %s" % (pid, exc))
            continue
        subject = "project:%s:%s" % (pid, day)
        if a.dry_run:
            filed.append("%s -> %s (%d todo)" % (pid, subject, len(todos)))
            continue
        cmd = ["python3", WAKE_CLI, "flag", "--subject", subject, "--prompt", prompt,
               "--context", context, "--kind", "project", "--source", SOURCE, "--priority", "normal"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120)
            out = (p.stdout or "").strip().splitlines()
            word = out[0] if out else "(no output)"
            filed.append("%s -> %s" % (pid, word))
        except Exception as exc:
            print("error:flag: %s: %s" % (pid, exc))

    if a.dry_run:
        for f in filed:
            print("would file %s" % f)
        for e in empty:
            print("quiet %s: no todo items in the ledger" % e)
        for g in gated:
            print("gated %s" % g)
        return 0

    for f in filed:
        print("%s %s" % (SOURCE, f))
    for g in gated:
        print("%s gated %s" % (SOURCE, g))
    if not filed:
        print("quiet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
