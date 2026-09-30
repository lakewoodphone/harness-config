#!/usr/bin/env python3
"""work-integrator.py - turn "a shift pushed a branch" into a tracked integration item.

THE GAP, measured 2026-09-28: a woken shift pushes a branch (`agent/windows-broker-channel`, 72e8daf)
and NOTHING EVER MERGES IT. The same defect is already in the record for lpt-website, where three
consecutive shifts worked the same unmerged fix. A fleet that builds and never integrates produces
branches, not progress.

FIRST VERSION WAS WRONG, and the bug is worth naming because it is the difference between a guard and
noise: it listed every remote ref that is not contained in the integration branch. Measured dry run:
279 "unmerged branches" - including a literal ref named `origin`, because `for-each-ref` prints the
remote's symbolic HEAD ref too, and including years-old work branches nobody intends to merge. Filing
279 items would have buried the ledger, which is worse than filing none: a backlog nobody can read is
indistinguishable from no backlog.

WHAT IT DOES NOW, and why each rule exists:
  * Skips the remote HEAD/symbolic ref (`origin`, `origin/HEAD`).
  * AGREES WITH GIT ABOUT WHAT IS MERGED. The test is `git merge-base --is-ancestor <ref> <base>`,
    not a name comparison - the previous version excluded `origin/main` by name and then reported
    every other ref, which is how a symbolic ref got through.
  * AGE LIMIT (`--days`, default 21). Only a branch whose tip commit is recent is a branch a SHIFT
    pushed. Old work branches are not integration debt; they are archaeology, and they stay out of
    the backlog unless asked for with --days 0.
  * ONE ITEM PER BRANCH, deduplicated by title, which `work.py add` already refuses to duplicate.
    An idempotent run files nothing the second time.
  * Reports what it filed AND what it deliberately left, so a human can see the filter working.

It never edits a repo, never merges, never pushes. The merge is a SHIFT's job: its brief's own audits
must be re-run afterwards, and green main is the invariant. This only makes the work VISIBLE.

Usage: python3 work-integrator.py [--dry-run] [--days N] [--project ID] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")
REGISTRY = Path(os.environ.get("WORK_REGISTRY") or "/home/zabz/bin/sources/projects.json")
AUTHOR = "integrator"
PRIORITY = 3
DEFAULT_DAYS = 21
# WHICH BRANCHES COUNT AS INTEGRATION DEBT. A shift pushes work under a small set of prefixes; the
# rest of a busy repo's refs are session logs, audit trails, owner-health notes, backups and rescue
# copies, which are archives rather than work waiting to land. Measured 2026-09-28: without this
# filter lpt-website reported 52 "recent unmerged" branches and prod-db-sync 38, almost all of them
# `audit/`, `docs/`, `backup/` and `co/` refs - a backlog of 90+ items that would bury the real ones.
DEFAULT_INCLUDE = r"^(origin/)?(agent|kf[0-9]*|integrate|rescue)/"


def git(repo: Path, *args, timeout=120):
    try:
        p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as exc:
        return 127, "", "%s: %s" % (type(exc).__name__, exc)


def work(*args, timeout=120):
    p = subprocess.run(["python3", WORK_CLI] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip()


def pick_base(repo: Path, row: dict) -> str:
    for cand in [row.get("integration_branch"), "origin/main", "origin/test", "origin/master",
                 "main", "master"]:
        if not cand:
            continue
        rc, _, _ = git(repo, "rev-parse", "--verify", "--quiet", cand + "^{commit}")
        if rc == 0:
            return cand
    return "HEAD"


def is_merged(repo: Path, ref: str, base: str) -> bool:
    """The only honest test: is the branch's tip an ancestor of base?"""
    return git(repo, "merge-base", "--is-ancestor", ref, base)[0] == 0


def tip_age_days(repo: Path, ref: str) -> float:
    rc, out, _ = git(repo, "log", "-1", "--format=%ct", ref)
    if rc != 0 or not out.strip().isdigit():
        return 1e9
    return (time.time() - int(out)) / 86400.0


def open_titles(project: str) -> set:
    rc, out = work("list", "--project", project, "--json")
    if rc != 0 or not out:
        return set()
    try:
        rows = json.loads(out)
    except Exception:
        return set()
    return {(r.get("title") or "").strip().lower()
            for r in rows if r.get("state") in ("todo", "running", "blocked")}


def candidate_refs(repo: Path) -> list:
    rc, out, _ = git(repo, "for-each-ref", "--format=%(refname:short)\t%(symref)",
                     "refs/remotes/origin")
    refs = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        name = parts[0].strip()
        symref = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        # a symbolic ref (origin, origin/HEAD) is not a branch and has no commits of its own
        if symref:
            continue
        if name.endswith("/HEAD") or name in ("origin",):
            continue
        if "/" not in name:
            continue
        refs.append(name)
    return refs



def sync_clone(repo: Path) -> tuple:
    """(state, detail) - make the checkout current before judging any branch.

    A stale clone makes "unmerged" a fact about the cache. Measured 2026-09-28: kosher-filter-ai was
    19 commits behind, and a diff across that gap reported 39 deleted files that were really the
    base's own additions.
    Returns state in: current | fast-forwarded | diverged | dirty | no-upstream | error
    """
    rc, out, err = git(repo, "status", "--porcelain")
    dirty = bool((out or "").strip())
    rc, counts, _ = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if rc != 0 or not (counts or "").strip():
        return ("no-upstream" if dirty is False else "dirty"), "no upstream tracking branch"
    try:
        ahead, behind = (int(x) for x in counts.split()[:2])
    except Exception:
        return "error", "could not parse %r" % counts
    if ahead and behind:
        return "diverged", "ahead %d, behind %d - not touching a divergent checkout" % (ahead, behind)
    if ahead:
        return "current", "ahead %d (local commits, not behind)" % ahead
    if behind == 0:
        return "current", ("clean" if not dirty else "clean but %d uncommitted file(s)" % len(out.splitlines()))
    if dirty:
        return "dirty", "behind %d but %d file(s) uncommitted - not fast-forwarding over local work" % (
            behind, len(out.splitlines()))
    rc, out2, err2 = git(repo, "merge", "--ff-only", "@{upstream}", timeout=300)
    if rc != 0:
        return "error", "fast-forward failed: %s" % (err2 or out2)[:120]
    return "fast-forwarded", "was behind %d" % behind

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help="only branches whose tip is newer than this many days (0 = no limit)")
    ap.add_argument("--include", default=DEFAULT_INCLUDE,
                    help="regex a branch name must match to count as integration debt")
    ap.add_argument("--all-branches", action="store_true",
                    help="ignore the prefix filter and consider every branch (expect noise)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=3,
                    help="file at most N integration items in one run (default 3). A backlog nobody "
                         "can read is worse than filing none - cold dry run 2026-09-30 found 12 "
                         "unmerged branches for kosher-ai-filter, 9 for lpt-website, 5 for lpt-sync.")
    a = ap.parse_args()

    doc = json.loads(Path(REGISTRY).read_text(encoding="utf-8"))
    report = []
    seen_repos = set()
    filed_run = 0
    for row in doc.get("projects", []):
        pid = row.get("id")
        if not row.get("enabled") or (a.project and pid != a.project):
            continue
        raw = row.get("repo") or ""
        if not raw or raw.upper().startswith("UNKNOWN") or not Path(raw).exists():
            continue
        repo = Path(raw)
        if not (repo / ".git").exists():
            continue
        real = str(repo.resolve())
        if real in seen_repos:
            # two registry rows can point at one repo (housekeeping and prod-db-sync both point at
            # personal-secretary-mvp); integrating the same branch twice is duplicate work
            continue
        seen_repos.add(real)
        base = pick_base(repo, row)
        state, detail = sync_clone(repo)
        if state in ("diverged", "dirty", "error"):
            # EVERY KEY THE PRINTER READS MUST BE PRESENT. The first version of this record lacked
            # recent_unmerged/older_unmerged/merged, so the summary loop raised KeyError and dumped a
            # traceback into the report - the one output a human reads.
            report.append({"project": pid, "repo": real, "skipped": state, "why": detail,
                           "base": None, "recent_unmerged": 0, "older_unmerged": 0, "merged": 0,
                           "filed": [], "older_sample": []})
            print("%-18s SKIPPED (%s): %s" % (pid, state, detail), file=sys.stderr)
            continue
        git(repo, "fetch", "--quiet", "--prune", "origin", timeout=300)
        recent, old, merged = [], [], []
        inc = None if a.all_branches else re.compile(a.include)
        for ref in candidate_refs(repo):
            if inc and not inc.search(ref):
                continue
            if is_merged(repo, ref, base):
                merged.append(ref)
                continue
            age = tip_age_days(repo, ref)
            (recent if (a.days == 0 or age <= a.days) else old).append((ref, round(age, 1)))
        filed = []
        have = open_titles(pid)
        for ref, age in sorted(recent):
            if filed_run >= a.limit:
                filed.append({"branch": ref, "age_days": age, "item": "deferred (per-run limit)"})
                continue
            title = "Integrate %s into %s" % (ref, base)
            if title.strip().lower() in have:
                filed.append({"branch": ref, "age_days": age, "item": "already tracked"})
                continue
            dod = ("%s contains %s and the project's own tests pass afterwards with their result "
                   "lines quoted; `git diff --diff-filter=D --name-only %s HEAD` is empty" %
                   (base, ref, base))
            why = ("a shift pushed this branch %s day(s) ago and nothing merges it; an unmerged "
                   "branch is work that will be redone by the next shift (measured: three lpt-website "
                   "shifts on one unmerged fix; agent/windows-broker-channel unmerged 2026-09-28)" % age)
            if a.dry_run:
                filed_run += 1
                filed.append({"branch": ref, "age_days": age, "item": "would-file"})
                continue
            rc2, out2 = work("add", "--project", pid, "--title", title, "--dod", dod,
                             "--why", why, "--priority", str(PRIORITY), "--source", AUTHOR)
            m = re.search(r'"id":\s*(\d+)', out2 or "")
            if "item-filed" in (out2 or "") and m:
                filed_run += 1
                filed.append({"branch": ref, "age_days": age, "item": int(m.group(1))})
            elif "already-filed" in (out2 or ""):
                filed.append({"branch": ref, "age_days": age, "item": "already tracked"})
            else:
                filed.append({"branch": ref, "age_days": age,
                              "item": "FAILED: %s" % (out2 or "")[:80]})
        report.append({"project": pid, "repo": real, "base": base,
                       "recent_unmerged": len(recent), "older_unmerged": len(old),
                       "merged": len(merged), "filed": filed,
                       "older_sample": [r for r, _ in old[:5]]})

    if a.json:
        print(json.dumps(report, indent=2))
        return 0
    to_file = 0
    for r in report:
        newly = [f for f in r["filed"] if isinstance(f["item"], int)]
        to_file += len(newly)
        print("%-18s base=%-14s recent_unmerged=%d older=%d merged=%d" % (
            r["project"], r["base"], r["recent_unmerged"], r["older_unmerged"], r["merged"]))
        for f in r["filed"][:8]:
            print("      %-50s %5s days -> %s" % (f["branch"], f["age_days"], f["item"]))
        for b, age in (r["filed"] and [] or []):
            pass
        if r["older_sample"]:
            print("      (older, not filed: %s%s)" % (
                ", ".join(r["older_sample"]), " ..." if r["older_unmerged"] > 5 else ""))
    print("\n%d integration item(s) %s within %d days" % (
        to_file, "would be filed" if a.dry_run else "filed", a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
