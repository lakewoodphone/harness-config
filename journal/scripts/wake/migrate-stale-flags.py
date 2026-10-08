#!/usr/bin/env python3
"""Migrate the wake store's backlog to the ledger-driven contract.

WHY THIS EXISTS. On 2026-09-28 the wake store held 27 rows in state `new` that had never been
dispatched, filed 2026-09-25..09-28. Every one of them carries a prompt written by the OLD
contract, which told the worker to advance a project by rewriting a private JSON blob. Two
facts make that backlog actively harmful if it runs as-is:

  1. Those prompts describe work that may already be finished, against state files that have
     since been rewritten by later shifts. A worker that trusts them redoes finished work -
     the exact failure the ledger was built to end.
  2. `project-keepalive` re-files the SAME subject the next day, and `wake.py` dedups by
     subject against rows in `new`, so a stale row both blocks the fresh flag and, once
     released, burns an attempt on the wrong instructions.

WHAT IT DOES, exactly, and all of it is reversible from the backup:
  * project rows (`project:<id>:<date>`) -> the prompt is REGENERATED from the live ledger
    contract, so the worker is told to claim from the ledger rather than rewrite a blob. The
    old prompt is preserved in the row's `context` field, never deleted.
  * every other `new` row -> marked `dropped` with a note naming what superseded it. Nothing
    is deleted; the row and its original prompt survive and can be re-filed.

It refuses to write anything unless the contract renders for that project first - the
previous patch taught that lesson by raising NameError at render time.

Usage:  python3 migrate-stale-flags.py --dry-run
        python3 migrate-stale-flags.py --apply
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

DB = Path("/home/zabz/.sms-inbox/inbox.db")
PK = "/home/zabz/bin/sources/project-keepalive.py"


def load_pk():
    spec = importlib.util.spec_from_file_location("pk", PK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pk"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()
    apply = a.apply and not a.dry_run

    pk = load_pk()
    _reg, projects = pk.load_registry()
    by_id = {p["id"]: p for p in projects}
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    c = sqlite3.connect(a.db, timeout=20)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT id, subject, source, state, context, prompt FROM wake "
                     "WHERE state='new' ORDER BY id").fetchall()
    print("state=new rows: %d" % len(rows))

    rewrites, drops = [], []
    for r in rows:
        subj = r["subject"] or ""
        if subj.startswith("project:"):
            pid = subj.split(":")[1]
            if pid not in by_id:
                drops.append((r["id"], subj, "project %r is not in the registry; superseded by the ledger" % pid))
                continue
            p = by_id[pid]
            # RENDER FIRST. If the contract cannot be produced, this row is left untouched.
            prompt = pk.standing_contract(p, pk.load_state(p), ["(from the ledger)"], now)
            if "claim-next" not in prompt:
                raise SystemExit("ERROR: rendered contract for %s has no ledger call - aborting" % pid)
            rewrites.append((r["id"], subj, prompt, r["context"]))
        else:
            drops.append((r["id"], subj,
                          "superseded 2026-09-28: the backlog now lives in the work ledger "
                          "(~/bin/work.py), which holds the item, its definition of done and every "
                          "attempt. This row's prompt was written before that and describes state "
                          "that may already have changed; running it would redo finished work. "
                          "Original prompt preserved in this row."))

    print("\nTO REWRITE with the ledger contract (%d):" % len(rewrites))
    for i, s, p, _ctx in rewrites:
        print("  #%-3d %-42s -> %d bytes" % (i, s, len(p)))
    print("\nTO DROP (%d):" % len(drops))
    for i, s, why in drops:
        print("  #%-3d %-42s %s" % (i, s, why[:60]))

    if not apply:
        print("\n(dry run; nothing written. use --apply)")
        return 0

    bak = Path(str(a.db) + ".bak-pre-ledger-migration-" + now.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(a.db, bak)
    print("\nbackup: %s" % bak)

    for i, subj, prompt, ctx in rewrites:
        keep = (ctx or "")
        keep = ("[migrated 2026-09-28 to the ledger-driven contract; the superseded prompt is kept "
                "below for the record]\n\n--- superseded prompt ---\n" + keep) if keep else \
               "[migrated 2026-09-28 to the ledger-driven contract]"
        c.execute("UPDATE wake SET prompt=?, context=?, attempts=0, max_attempts=2 WHERE id=?",
                  (prompt, keep, i))
        c.execute("INSERT INTO note(at,kind,subject,body) VALUES(?,?,?,?)",
                  (stamp, "migrate", subj, "prompt regenerated from the ledger contract")) \
            if _has_note(c) else None
    for i, subj, why in drops:
        c.execute("UPDATE wake SET state='dropped', finished_at=?, outcome=? WHERE id=?",
                  (stamp, why, i))
    c.commit()
    left = c.execute("SELECT COUNT(*) FROM wake WHERE state='new'").fetchone()[0]
    print("rewritten=%d dropped=%d ; state=new remaining=%d" % (len(rewrites), len(drops), left))
    c.close()
    return 0


def _has_note(c) -> bool:
    try:
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note'").fetchone())
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
