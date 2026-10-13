#!/usr/bin/env python3
"""apply-ledger-seed.py - register the nine wake projects and load the ledger seed into a WORK ledger.

THE TWO STEPS, IN ORDER (measured 2026-10-13: `work.py add` returns
`error:unknown-project` for a project that is not in the `project` table first):

  1. register every enabled project from projects.json (`work.py project add`);
  2. append each seed item (`work.py add`).

SAFETY, ON PURPOSE
------------------
The ledger is the store a woken shift claims from. The orchestrator restoring the wake loop
owns the live store exclusively, so this script:

  * is DRY-RUN by default and prints exactly what it would add;
  * refuses to touch the live default DB unless --allow-live is also passed;
  * is idempotent: projects already in the `project` table are skipped, and an item whose title
    is already open is skipped, so running it twice does not file duplicates (a proof script on
    this estate once filed three duplicate real ledger items);
  * only appends; it never updates or deletes an item;
  * FAILS LOUDLY: any `work.py` non-zero exit counts as a failure and makes the script exit 1.

Usage:
    python3 apply-ledger-seed.py                       # dry-run against the live DB path (no write)
    cp /root/work/work.db /tmp/work-seed-test.db       # throwaway copy
    python3 apply-ledger-seed.py --db /tmp/work-seed-test.db --apply
    python3 apply-ledger-seed.py --db /tmp/work-seed-test.db --apply   # idempotent second run
    rm -f /tmp/work-seed-test.db /tmp/work-seed-test.db-wal /tmp/work-seed-test.db-shm
    # the orchestrator's install step (its call, not this brief's):
    python3 apply-ledger-seed.py --db /root/work/work.db --apply --allow-live
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = HERE / "ledger-seed-2026-10-13.json"
REGISTRY = HERE / "projects.json"
LIVE_DB = "/root/work/work.db"
WORK_CLI = os.environ.get("WORK_CLI", "/root/bin/work.py")


def run(work_db: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, WORK_CLI, "--db", work_db, *args],
                          capture_output=True, text=True, timeout=120)


def registered_ids(work_db: str) -> set:
    try:
        c = sqlite3.connect("file:%s?mode=ro" % work_db, uri=True, timeout=20)
        try:
            return {r[0] for r in c.execute("SELECT id FROM project")}
        finally:
            c.close()
    except sqlite3.Error:
        return set()


def open_titles(work_db: str) -> set:
    try:
        c = sqlite3.connect("file:%s?mode=ro" % work_db, uri=True, timeout=20)
        try:
            return {r[0] for r in c.execute(
                "SELECT title FROM work_item WHERE state IN ('todo','running')")}
        finally:
            c.close()
    except sqlite3.Error:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=LIVE_DB)
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--allow-live", action="store_true", help="permit writing the live default DB")
    a = ap.parse_args()

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    projects = [p for p in reg["projects"] if p.get("enabled")]

    items = seed["items"]
    enabled_ids = {p["id"] for p in projects}
    bad = sorted({i["project"] for i in items} - enabled_ids)
    if bad:
        print("REFUSING: seed names projects not enabled in projects.json: %s" % ", ".join(bad))
        return 2
    missing = [pid for pid in enabled_ids if not any(i["project"] == pid for i in items)]
    if missing:
        print("REFUSING: enabled projects with no seed item: %s" % ", ".join(sorted(missing)))
        return 2

    live = os.path.abspath(a.db) == os.path.abspath(LIVE_DB)
    if a.apply and live and not a.allow_live:
        print("REFUSING to write the live ledger %s without --allow-live." % LIVE_DB)
        return 3
    if a.apply and not Path(a.db).exists():
        print("REFUSING: --db %s does not exist (copy the store first)." % a.db)
        return 3

    already = registered_ids(a.db) if Path(a.db).exists() else set()
    titles = open_titles(a.db) if Path(a.db).exists() else set()
    failures = 0

    for p in projects:
        pid = p["id"]
        if pid in already:
            print("skip (project registered): %s" % pid)
            continue
        cmd = ["project", "add", "--id", pid, "--title", p["title"]]
        if p.get("repo"):
            cmd += ["--repo", str(p["repo"])]
        if p.get("definition_of_done"):
            cmd += ["--dod", p["definition_of_done"]]
        if not a.apply:
            print("would register project: %s" % pid)
            continue
        r = run(a.db, *cmd)
        ok = r.returncode == 0
        failures += 0 if ok else 1
        print("register project: %s -> rc=%d %s" % (pid, r.returncode,
              (r.stdout or r.stderr or "").strip().splitlines()[:1]))

    added = skipped = 0
    for it in items:
        if it["title"] in titles:
            print("skip (already open): [%s] %s" % (it["project"], it["title"]))
            skipped += 1
            continue
        if not a.apply:
            print("would add: [%s] %s" % (it["project"], it["title"]))
            added += 1
            continue
        r = run(a.db, "add", "--project", it["project"], "--title", it["title"],
                "--dod", it["dod"], "--why", it["why"],
                "--priority", str(it.get("priority", 5)), "--source", it["source"])
        line = (r.stdout or r.stderr or "").strip().splitlines()
        failures += 0 if r.returncode == 0 else 1
        print("add: [%s] %s -> rc=%d %s" % (it["project"], it["title"], r.returncode,
              line[0] if line else "(no output)"))
        added += 1

    print("\n%s: %d item(s), %d skipped, %d project(s), %d failure(s)"
          % ("APPLIED" if a.apply else "DRY-RUN", added, skipped, len(projects), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
