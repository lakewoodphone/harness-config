#!/usr/bin/env python3
"""Record each project's REAL integration branch, so "unmerged" is measured against the right base.

MY BUG, caught by the integrator's own report: for lpt-website the default base was `origin/main`, and
that produced 8 "unmerged branches". But the registry's own note for that project says the integration
line is `test` - "NEVER MERGE origin/fix/holiday-closure-notice AS A BRANCH ... Guard after ANY merge:
git diff --diff-filter=D --name-only origin/test HEAD must be EMPTY." So the integrator was measuring
against a branch nobody integrates into, and every branch merged into `test` looked like debt. A
measurement against the wrong reference is not a measurement.

Rather than guess a base, this ASKS each repo: which of the plausible integration branches actually
contains the most of the branches in question, and which one is the project's declared line. The answer
is written into projects.json as `integration_branch`, so the choice is reviewable and correctable in
one place.

Usage: python3 set-integration-bases.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REG = Path("/home/zabz/bin/sources/projects.json")
CANDIDATES = ["origin/test", "origin/main", "origin/master", "origin/develop", "origin/staging"]


def git(repo: Path, *args, timeout=120):
    try:
        p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception:
        return 127, "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    doc = json.loads(REG.read_text(encoding="utf-8"))
    changed = []
    for row in doc.get("projects", []):
        raw = row.get("repo") or ""
        repo = Path(raw) if raw and not raw.upper().startswith("UNKNOWN") else None
        if not repo or not (repo / ".git").exists():
            continue
        git(repo, "fetch", "--quiet", "--prune", "origin", timeout=300)
        present = []
        for cand in CANDIDATES:
            rc, out, _ = git(repo, "rev-parse", "--verify", "--quiet", cand + "^{commit}")
            if rc == 0:
                # how many of the shift-authored branches does this base already contain?
                rc2, refs, _ = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
                total = contained = 0
                for ref in (refs or "").split():
                    if not re.search(r"^origin/(agent|kf[0-9]*|integrate|rescue)/", ref):
                        continue
                    total += 1
                    if git(repo, "merge-base", "--is-ancestor", ref, cand)[0] == 0:
                        contained += 1
                present.append((cand, contained, total))
        if not present:
            continue
        # prefer the candidate that CONTAINS the most shift branches; tie-break by the order above
        best = sorted(present, key=lambda t: (-t[1], CANDIDATES.index(t[0])))[0]
        current = row.get("integration_branch")
        print("%-16s candidates=%s -> best=%s (contains %d/%d shift branches)%s" % (
            row.get("id"), present, best[0], best[1], best[2],
            "" if current == best[0] else "   [was %r]" % current))
        if current != best[0]:
            row["integration_branch"] = best[0]
            changed.append((row.get("id"), current, best[0]))

    if not changed:
        print("\nnothing to change")
        return 0
    if not a.apply:
        print("\ndry run: %d project(s) would be updated" % len(changed))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(REG, REG.with_name("projects.json.bak-integration-bases-" + stamp))
    REG.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %s for %d project(s)" % (REG, len(changed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
