#!/usr/bin/env python3
"""Derive each integration item's verification from the REPO, instead of one template for all.

THE WEAKNESS, found by asking whether the definition of done is satisfiable: every integration item
filed by `work-integrator.py` says "re-run the project's own tests and quote the result line". Measured
2026-09-28 on lpt-hub: it has NO package.json, no pyproject, no Makefile, no pytest.ini, no top-level
test directory - it is a docs-and-research repo with two small tool test dirs
(`tools/case-index/tests`, `tools/customer/tests`). So the instruction is either unsatisfiable or
meaningless there, and an item whose definition of done cannot be met is an item that gets closed on a
shrug or abandoned. That is exactly the "definition of done as a wish" failure this system has already
recorded once.

WHAT THIS DOES: for each open integration item, look at the repo and pick the verification that is
actually available, in this order:
  1. a declared test command (package.json "test" script, pyproject/pytest config, Makefile test
     target) -> name it verbatim;
  2. otherwise, if test directories exist -> name them and say to run what they provide;
  3. otherwise -> say plainly that there is NO test suite and that the proof is (a) the merge-introduced
     deletion guard being empty, (b) the tree still parsing/linting if a linter is configured, and
     (c) an explicit statement that tests were not run because none exist.
The third case matters most: for a docs repo, "no tests exist" is the honest, quotable result, and a
shift should be told it is allowed to say so rather than invent a green line.

Usage: python3 fix-integration-dod.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/home/zabz/work/work.db")
REG = Path("/home/zabz/bin/sources/projects.json")


def repo_for(pid: str) -> Path | None:
    try:
        doc = json.loads(REG.read_text(encoding="utf-8"))
    except Exception:
        return None
    for row in doc.get("projects", []):
        if row.get("id") == pid:
            raw = row.get("repo") or ""
            if raw and not raw.upper().startswith("UNKNOWN"):
                p = Path(raw)
                if (p / ".git").exists():
                    return p
    return None


def detect(repo: Path) -> tuple:
    """(kind, verification_text). Never guesses: absence is reported as absence."""
    # 1. a declared test command
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            d = json.loads(pkg.read_text(encoding="utf-8"))
            t = (d.get("scripts") or {}).get("test")
            if t:
                return "declared", "run the repo's own declared test command and quote its result line:\n" \
                                   "      `npm test`   (package.json scripts.test = %r)" % t
        except Exception:
            pass
    for f in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"):
        p = repo / f
        if p.exists():
            try:
                if re.search(r"pytest|\[tool\.pytest", p.read_text(encoding="utf-8", errors="replace")):
                    return "declared", "run the repo's pytest suite and quote the summary line, e.g.\n" \
                                       "      `python -m pytest -q 2>&1 | tail -n 5`"
            except Exception:
                pass
    mk = repo / "Makefile"
    if mk.exists():
        try:
            if re.search(r"^test:", mk.read_text(encoding="utf-8", errors="replace"), re.M):
                return "declared", "run the repo's own test target and quote its result line:\n" \
                                   "      `make test`"
        except Exception:
            pass
    # 2. test directories
    dirs = []
    for pat in ("test", "tests", "__tests__", "spec"):
        for p in repo.rglob(pat):
            if p.is_dir() and "node_modules" not in str(p) and len(str(p)) < 120:
                dirs.append(p.relative_to(repo))
        if len(dirs) >= 4:
            break
    if dirs:
        return "dirs", ("this repo declares no single test command, but holds test directories: %s.\n"
                        "      Run what they provide and quote the result line; if they need a runner "
                        "that is NOT installed, say so explicitly and name the missing tool."
                        % ", ".join(str(d) for d in dirs[:4]))
    # 3. no tests at all - say it out loud
    return "none", ("THIS REPO HAS NO TEST SUITE (checked: package.json scripts.test, pyproject/"
                    "pytest/tox/setup.cfg, a Makefile test target, and test directories - none "
                    "present).\n"
                    "      Do NOT invent a green line. The proof for this item is: (a) the "
                    "merge-introduced deletion guard is EMPTY, (b) the tree still opens/parses if this "
                    "repo has a linter or index tool - run it and quote the result, "
                    "(c) an explicit sentence: \\\"no tests were run because this repo declares none\\\".")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(str(DB), timeout=20)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT id, project, title, dod FROM work_item "
                     "WHERE source='integrator' AND state IN ('todo','running') ORDER BY id").fetchall()
    changed = []
    cache = {}
    for r in rows:
        repo = repo_for(r["project"])
        if not repo:
            continue
        if str(repo) not in cache:
            cache[str(repo)] = detect(repo)
        kind, verify = cache[str(repo)]
        dod = r["dod"] or ""
        # replace the generic instruction wherever it appears
        new_dod = re.sub(
            r"4\) RE-RUN the project's own tests and quote the result line;",
            "4) VERIFICATION FOR THIS REPO - " + verify.replace("\n", " ") + ";", dod)
        if new_dod == dod:
            new_dod = re.sub(r"4\) run the tests ON THE DESKTOP[^;]*;",
                             "4) VERIFICATION FOR THIS REPO - " + verify.replace("\n", " ") + ";", dod)
        changed.append((r["id"], r["project"], kind, str(repo)))
        if a.apply:
            c.execute("UPDATE work_item SET dod=?, updated_at=? WHERE id=?",
                      (new_dod, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), r["id"]))
    if a.apply:
        c.commit()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(DB, str(DB) + ".bak-dod-" + stamp)
        print("backup: %s.bak-dod-%s" % (DB, stamp))
    c.close()

    print("%-5s %-18s %-9s %s" % ("item", "project", "verifies", "repo"))
    for i, p, k, repo in changed:
        print("%-5d %-18s %-9s %s" % (i, p, k, repo))
    counts = {}
    for _, _, k, _ in changed:
        counts[k] = counts.get(k, 0) + 1
    print("\n%d item(s) %s | by kind: %s" % (
        len(changed), "updated" if a.apply else "would be updated", counts))
    if counts.get("none"):
        print("NOTE: %d repo(s) have NO test suite - their items now say so instead of demanding one."
              % counts["none"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
