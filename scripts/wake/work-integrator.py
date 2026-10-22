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
  * AND AGREES ABOUT CONTENT NO-OP MERGES (ledger item 322, measured 2026-10-01). Ancestry alone
    called origin/integrate/main-27/28/29 unmerged even though `git merge-tree --write-tree
    origin/main <branch>` returns origin/main's own tree exactly, so merging them changes nothing.
    The hourly cron re-filed an unfinishable item for each; four shifts were spent on the same
    already-landed change. A branch is now merged when it is an ancestor OR when a real three-way
    merge of it into base leaves base's tree byte-identical. A conflicting merge is never a no-op.
  * AGE LIMIT (`--days`, default 21). Only a branch whose tip commit is recent is a branch a SHIFT
    pushed. Old work branches are not integration debt; they are archaeology, and they stay out of
    the backlog unless asked for with --days 0.
  * ONE ITEM PER BRANCH, deduplicated by title, which `work.py add` already refuses to duplicate.
    An idempotent run files nothing the second time.
  * CHECKS THE LEDGER BEFORE IT ASKS FOR A MERGE (ledger item 1134, measured 2026-10-22).
    A branch whose commits name a ledger item is cross-checked: a running or claimed item means
    another shift owns it, and a done item that the base already carries means the branch is a
    SECOND implementation. Neither is filed as integration debt. Measured on the level-wire
    episode: origin/integrate/level-wire names ledger 1096 and main carries PRs #117/#119, so
    the generator now reports it as a duplicate instead of filing "Integrate ...". A DROPPED
    integration row also stays in the dedupe set: item 1120 was dropped with evidence at 06:13
    and the same instruction was re-filed as 1146 at 07:37, because dropped rows were invisible.
  * A REGISTRY `repo` MAY BE A SUBDIRECTORY OF A CHECKOUT (measured 2026-10-22, item 1101).
    rental-system points at apps/rentals, which has no .git of its own; the checkout is the
    parent monorepo. The old test was `(repo / ".git").exists()`, which called that a non-git
    path and skipped the project on every run - and also mis-calls a WORKTREE, where .git is a
    file. The tool now asks git for the top level, and scopes a subdirectory project to branches
    that spend a strict majority of their changed paths under it, so rentals cannot claim every
    branch in the monorepo (or a housekeeping branch that touches one rentals file).
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
DEFAULT_INCLUDE = r"^(origin/)?(agent|kf[0-9]*|integrate|rescue|item-|fix|guard)/"
# WIDENED 2026-10-18, measured. The fleet changed its branch naming and this filter never followed:
# of the 72 refs then unmerged into kosher-filter-ai's origin/main, 35 were `agent/`, 11
# `integrate/`, 2 `kf*` - but **18 were `item-<ledger id>-<slug>`** and 3 were `fix/` or `guard/`,
# i.e. 21 branches carrying finished work were invisible here. Two recent fixes were among them
# (item 404's Android MITM fail-closed, and /readyz from item 406/494). A filter that silently stops
# matching is worse than no filter: it printed "0 integration item(s) filed" every half hour, which
# reads as health. `item-` keeps the dash so a future `items/` ref cannot ride in on it.

# ATTEMPT BRANCHES ARE NOT INTEGRATION DEBT. Every integration item that needs a safety branch
# pushes `integrate/<base>-<item>` or `...-<item>b` alongside the real `integrate/<base>`. Those are
# snapshots of one attempt, not work waiting to land: measured 2026-10-01, `integrate/master-32-286`
# (e7b4fe7c) is the superseded first attempt at the merge that landed as ba731dd6, yet the generator
# kept filing it and two shifts (ledger items 296 and 298) re-adjudicated the same dead branch.
# ATTEMPT BRANCHES ARE NOT INTEGRATION DEBT. Every integration item that needs a safety branch
# pushes a snapshot of one attempt alongside the real integration branch. Those snapshots are not
# work waiting to land: measured 2026-10-01, `integrate/master-32-286` (e7b4fe7c) is the superseded
# first attempt at the merge that landed as ba731dd6, yet the generator kept filing it and two
# shifts (ledger items 296 and 298) re-adjudicated the same dead branch.
# Two attempt shapes are skipped:
#   * integrate/<base>-<generation>-<item>  e.g. prod-db-sync integrate/master-32-286 (item 297)
#   * integrate/<base>-<item>               e.g. kosher-ai-filter integrate/main-156 (item 299)
# The single-number shape is skipped PER PROJECT. It is skipped only for the registered
# non-generation bases below, and only for projects where that base was MEASURED attempt-only.
# `master` is deliberately absent: prod-db-sync names its real integration branches
# integrate/master-<gen> (30/31/32/33) and item 297's verification pins those as KEEP -
# treating master-<n> as an attempt would hide the next generation. A bare integrate/<base> with
# no trailing number stays real: ATTEMPT_REF matches origin/integrate/main-156 but not
# origin/integrate/main.
#
# WHY PER PROJECT (measured 2026-10-01, ledger item 300): item 299 added `test` fleet-wide, but
# lpt-website's integration branch IS origin/test and its origin/integrate/test-<n> refs are
# REAL promotion branches (ledger items 266/270/271/272/275/276/277/279) - a fleet-wide `test`
# silently skipped them and never filed them. A project whose real promotion branches use the
# integrate/<base>-<item> shape MUST map that base away below.
ATTEMPT_BASES = ("main", "test")  # fleet default for the single-number shape
ATTEMPT_BASES_BY_PROJECT = {
    "lpt-website": (),  # integrate/test-<n> are real promotion debt, not attempt snapshots
    # WHY lpt-sync (measured 2026-10-01, ledger item 301): lpt-hub IS the lpt-sync repo, its
    # integration branch is origin/main, and it names its real integration branches
    # integrate/main-<item> (27..33, tips 2026-09-28..30). All seven are UNMERGED against
    # origin/main (merge-base --is-ancestor rc=1) and their subjects are real ledger work
    # (lpt-sync items 29/131/163/211/239). The fleet-default `main` skip added for kosher
    # (item 299) hid all seven, exactly as it hid lpt-website integrate/test-<n> (item 300).
    "lpt-sync": (),
}
# THE TRAILING NUMBER IS A LEDGER ITEM ID, NOT A DATE (measured 2026-10-22, item 1110).
# origin/integrate/rentals-93-94-20261022 is a REAL landing branch - base rentals, PRs 93 and 94,
# dated 2026-10-22 - but the old unbounded `-\d+$` read 20261022 as an item number and skipped it,
# hiding the rebuilt PR93/94 candidate (7d743b05e) from the integrator entirely. Ledger item ids are
# 1-4 digits; a date is at least six. Capping the item keeps every true snapshot
# (integrate/master-32-286) skipped and lets a dated branch through.
TWO_NUMBER_ATTEMPT_REF = re.compile(r"^(?:origin/)?integrate/.+-\d+-\d{1,4}[a-z]?$")


def attempt_ref_re(project):
    """Compiled attempt-branch matcher for one project (None = the fleet default)."""
    bases = ATTEMPT_BASES_BY_PROJECT.get(project, ATTEMPT_BASES)
    parts = [TWO_NUMBER_ATTEMPT_REF.pattern]
    if bases:
        parts.append(r"^(?:origin/)?integrate/(?:%s)-\d+[a-z]?$"
                     % "|".join(re.escape(b) for b in bases))
    return re.compile("|".join(parts))


def is_attempt_ref(project, ref):
    """True when the live generator skips `ref` as a one-attempt snapshot for `project`."""
    return bool(attempt_ref_re(project).match(ref))


ATTEMPT_REF = attempt_ref_re(None)  # fleet-default matcher, kept for importing tooling

# DELETIONS AN INTEGRATION MUST NOT UNDO. master-33 (commit 012f8a35, item 287) intentionally
# untracked 17 credential files, so a correct integration shows 17 deletions against its parent and
# the old "deletion diff is empty" clause could never be met again. The DoD now names these as the
# only paths an integration may delete.
CREDENTIAL_EXEMPT = ("*_token.json", "*tokens*.env", ".env.vogel", "*tunnel-token*.md")


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


# LEDGER CROSS-CHECK (ledger item 1134, measured 2026-10-22).
# The level-wire episode: a shift built ledger 1096 a second time on
# origin/integrate/level-wire, whose tip commit names "ledger 1096"; 1096 was already done
# through PRs #117 and #119 on main. This generator then filed
# "Integrate origin/integrate/level-wire into origin/main" - an instruction to merge the
# losing implementation, which would have put a second, contradictory mechanism for the same
# setting into the tree. A branch that NAMES a ledger item is making a claim we can check
# before asking anyone to merge it:
#   * running / claimed -> another shift owns that item; do not ask for a second build.
#   * done AND the base already carries a commit naming it -> the base holds the winning
#     implementation; the branch is a duplicate, not integration debt.
# Anything else stays integration debt, but an item that cites a done item is told to state
# WHICH implementation wins before it merges.
LEDGER_REF_RE = re.compile(r"(?i)\b(?:ledger|item)[\s#:-]*(\d{2,5})\b")


def ledger_ids_in(subject: str) -> set:
    """Ledger ids a branch SUBJECT claims. Subject only: a body may cite unrelated items."""
    return {int(n) for n in LEDGER_REF_RE.findall(subject or "")}


def ref_ledger_ids(repo: Path, base: str, ref: str) -> set:
    """Ids named by the branch's commit subjects, plus item-<id>-slugs in its own name."""
    ids = set()
    m = re.match(r"^(?:origin/)?item-(\d+)-", ref)
    if m:
        ids.add(int(m.group(1)))
    rc, out, _ = git(repo, "log", "--format=%s", "%s..%s" % (base, ref), timeout=120)
    if rc == 0:
        for line in (out or "").splitlines():
            ids |= ledger_ids_in(line)
    return ids


def ledger_state(item_id: int):
    """(state, title) from the work ledger, or (None, '') when it cannot be read."""
    rc, out = work("show", str(item_id), "--json")
    if rc != 0 or not (out or "").strip():
        return None, ""
    try:
        doc = json.loads(out)
    except ValueError:
        return None, ""
    return doc.get("state"), doc.get("title") or ""


def base_names_item(repo: Path, base: str, item_id: int) -> str:
    """The base commit that already names this ledger item, or '' if none does."""
    rc, out, _ = git(repo, "log", "-1", "--format=%h %s", base,
                     "--grep", r"\b%d\b" % item_id, "-E", timeout=120)
    return (out or "").strip() if rc == 0 else ""


def pick_base(repo: Path, row: dict) -> str:
    for cand in [row.get("integration_branch"), "origin/main", "origin/test", "origin/master",
                 "main", "master"]:
        if not cand:
            continue
        rc, _, _ = git(repo, "rev-parse", "--verify", "--quiet", cand + "^{commit}")
        if rc == 0:
            return cand
    return "HEAD"


def merge_tree_of(repo: Path, base: str, ref: str):
    """The tree a clean merge of `ref` into `base` would produce, or None.

    `git merge-tree --write-tree` (git >= 2.38) performs a real three-way merge without
    touching the worktree, the index or any ref. It exits non-zero when the merge conflicts;
    a conflicted merge is WORK, not a no-op, so that case returns None.
    """
    rc, out, _ = git(repo, "merge-tree", "--write-tree", base, ref, timeout=300)
    if rc != 0 or not out:
        return None
    tree = out.splitlines()[0].strip()
    return tree if re.fullmatch(r"[0-9a-fA-F]{40,64}", tree) else None


# A MERGE THAT ONLY ADDS ABANDONED ARTIFACTS IS NOT INTEGRATION DEBT (measured 2026-10-08,
# item 567). `rescue/` and `agent/` branches are safety snapshots of a working tree: they carry
# *.bak-<tag>-<ts> copies, stray SQLite -shm/-wal files and firmware .pio gitlinks that must
# NEVER be merged, alongside the real edit. When base already contains the real edit, the
# three-way merge still differs from base by those artifacts, so the content no-op test above
# says "unmerged" and the hourly cron re-files an item that can never be finished. Measured:
# origin/rescue/secratary-worktree-20261007T160715Z (672877a8) was filed as items 562, 565 and
# 567 in nine hours; all 15 of its substantive source/doc/test files are already byte-identical
# to origin/master and every path left is an artifact.
ARTIFACT_EXEMPT = re.compile(
    r"(?:^|/)\.pio/|\.bak$|\.bak[-.]|\.db-(?:shm|wal)$|\.orig$|~$")


def changes_are_only_artifacts(repo: Path, base: str, merged_tree: str) -> bool:
    """True when base -> merged_tree touches nothing but abandoned artifacts.

    A file whose MODE changed but whose blob is identical is not content either (measured: the
    rescue branch carries one 0-line 100755 bit on scripts/dialpad-call-fresh.py). Conservative
    by construction: any substantive path, or any unparseable diff record, returns False.
    """
    rc, out, _ = git(repo, "diff", "--raw", "-z", base + "^{tree}", merged_tree, timeout=120)
    if rc != 0 or not out:
        return False
    toks = out.split("\0")
    i = 0
    changed = False
    while i < len(toks):
        rec = toks[i]
        if not rec.startswith(":"):
            i += 1
            continue
        parts = rec[1:].split()
        path = toks[i + 1] if i + 1 < len(toks) else ""
        i += 2
        if len(parts) < 5 or not path:
            return False
        changed = True
        if parts[2] == parts[3]:      # mode/type bit only, blob identical
            continue
        if ARTIFACT_EXEMPT.search(path):
            continue
        return False                  # real content -> genuine integration debt
    return changed


def mode_only_conflict_merge_tree(repo: Path, base: str, ref: str):
    """The merge tree when a merge conflicts ONLY about a file mode.

    `is_merged` treats a conflicting merge as real debt, and normally that is right. One
    measured exception (2026-10-08, item 567): a rescue snapshot can carry the SAME blob as base
    and disagree only about the executable bit. Git still reports that as an add/add conflict
    (measured: scripts/dialpad-call-fresh.py, both stages c7d6a438, 100644 vs 100755), so the
    no-op test returned None and the hourly cron re-filed an unfinishable item. Returns the tree
    only when every conflicted path has one blob across all stages; a single content difference
    returns None and the branch stays debt.
    """
    rc, out, _ = git(repo, "merge-tree", "--write-tree", base, ref, timeout=180)
    lines = [l for l in (out or "").splitlines() if l.strip()]
    if not lines:
        return None
    tree = lines[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", tree):
        return None
    stages = {}
    saw_stage = False
    for line in lines[1:]:
        m = re.match(r"^\d{6} ([0-9a-fA-F]{40,64}) \d+\t(.*)$", line)
        if not m:
            continue
        saw_stage = True
        stages.setdefault(m.group(2), set()).add(m.group(1))
    if not saw_stage or not stages:
        return None
    if any(len(shas) > 1 for shas in stages.values()):
        return None          # a real content conflict -> genuine integration debt
    return tree


def is_merged(repo: Path, ref: str, base: str) -> bool:
    """True when `ref` has nothing left to integrate into `base`.

    ANCESTRY IS NOT THE WHOLE TEST (measured 2026-10-01, ledger item 322). `merge-base
    --is-ancestor` answers "is this exact commit in base's history", which is false whenever
    the work landed by a different route (cherry-pick, rebase, a squash, or an equivalent
    edit made elsewhere). Measured: origin/integrate/main-27/28/29 are NOT ancestors of
    origin/main, yet `git merge-tree --write-tree origin/main <branch>` returns exactly
    origin/main's own tree 694add9954 - merging any of them changes no content, so every
    merge attempt must fail or be a no-op. The old ancestry-only test called them unmerged
    and the hourly cron filed an unfinishable "Integrate ..." item for each: four shifts
    (304, 307, 312, 319) were spent re-adjudicating one already-landed change, and items
    320/321 were queued for the same defect.

    So a branch counts as merged when its tip is an ancestor of base, OR when a real merge
    of base and that branch produces base's tree unchanged. A merge that conflicts is never
    a no-op, and neither is one whose result differs from base by a single byte.
    """
    if git(repo, "merge-base", "--is-ancestor", ref, base)[0] == 0:
        return True
    merged_tree = merge_tree_of(repo, base, ref)
    if merged_tree is None:
        # A conflict is normally real debt; a mode-only conflict on identical content is not.
        merged_tree = mode_only_conflict_merge_tree(repo, base, ref)
        if merged_tree is None:
            return False
    rc, base_tree, _ = git(repo, "rev-parse", base + "^{tree}")
    if rc == 0 and merged_tree == (base_tree or "").strip():
        return True
    # ONLY ARTIFACTS LEFT: nothing a shift could integrate, so not integration debt.
    return changes_are_only_artifacts(repo, base, merged_tree)


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
    # A DROPPED ROW IS A DECISION, NOT AN ABSENCE (ledger item 1134, measured 2026-10-22).
    # Item 1120 was dropped at 06:13 with the evidence that it asked for the losing level-wire
    # implementation; the next hourly run filed the identical instruction as item 1146 at 07:37.
    # Re-filing a rejected merge every half hour is how a decision gets undone by a cron.
    return {(r.get("title") or "").strip().lower()
            for r in rows if r.get("state") in ("todo", "running", "blocked", "dropped")}


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


def resolve_checkout(registered: Path) -> tuple:
    """(git_root, scope) for a registry repo that may be a monorepo subdirectory.

    Measured 2026-10-22 (ledger item 1101): rental-system's registry repo is
    /home/zabz/personal-secretary-mvp/apps/rentals, which exists but has no .git of its own -
    the checkout is the parent monorepo (/opt/company/.git via the symlink). The old
    `(repo / ".git").exists()` test called that "not a git checkout" and skipped the project
    on every run, so unmerged rentals branches were never filed as integration debt. That test
    is also wrong for a git WORKTREE, where .git is a file rather than a directory.

    scope is the registered path relative to the checkout root ("apps/rentals/"), so a
    subdirectory project is judged only on branches that change something under it. "" means
    the whole checkout. Returns (None, "") when the path is not inside a git checkout.
    """
    rc, out, _ = git(registered, "rev-parse", "--show-toplevel", timeout=30)
    if rc != 0 or not out.strip():
        return None, ""
    root = Path(out.strip())
    try:
        rel = registered.resolve().relative_to(root.resolve())
    except ValueError:
        return root, ""
    scope = "" if str(rel) in (".", "") else rel.as_posix().rstrip("/") + "/"
    return root, scope


def branch_touches_scope(project: str, repo: Path, base: str, ref: str, scope: str) -> bool:
    """True when `ref` is a branch FOR the subdirectory `scope`, not a branch that grazes it.

    A subdirectory project's debt is only the branches that touch that subdirectory. Without
    this, resolving rental-system to the monorepo root would make it report - and file - the
    housekeeping and prod-db-sync branches under the rentals project.

    Touching ONE file under the scope is not enough (measured 2026-10-22, item 1101): on the
    monorepo, origin/fix/status-vocabularies changes 47 paths, 1 of them under apps/rentals, and
    origin/fix/dialpad-backfill-cursor-20261006 changes 203, 92 under apps/rentals - a
    cross-cutting branch is housekeeping's debt, and filing it here too duplicates the work.
    So the branch must spend a STRICT MAJORITY of its changed paths under the scope. The real
    rentals branch, origin/integrate/rentals-node24-ci-20261022, is 2 of 3 (the third is
    .github/workflows/rentals-ci.yml) and passes.

    Fail OPEN: an unreadable diff must not hide a branch, because an invisible branch is the
    defect this tool exists to prevent. A failure is printed loudly and the ref stays a candidate.
    """
    if not scope:
        return True
    rc, out, err = git(repo, "diff", "--name-only", "%s...%s" % (base, ref), timeout=180)
    if rc != 0:
        print("%-18s SCOPE UNKNOWN for %s (%s) - counted in-scope" % (
            project, ref, (err or out)[:120]), file=sys.stderr)
        return True
    paths = [p for p in (out or "").splitlines() if p.strip()]
    if not paths:
        return False
    scope_dir = scope.rstrip("/")
    inside = sum(1 for p in paths if p == scope_dir or p.startswith(scope))
    return inside > 0 and inside * 2 > len(paths)


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
        # NO UPSTREAM IS ITS OWN STATE, NOT A KIND OF DIRTY (ledger item 302, measured
        # 2026-10-01). The fast-forward path below can never run without an upstream, so
        # uncommitted files here cannot be overwritten by this function - yet the old `dirty`
        # label made main() SKIP THE WHOLE PROJECT. Measured cost: lpt-hub shared clone sits
        # mid-rebase about 11 of every 15 minutes (a scheduled rebase of integrate/main-32 onto
        # origin/main; the reflog shows start/abort pairs every 15 minutes all day), and while it
        # does, lpt-sync named no upstream, so its seven unmerged origin/integrate/main-27..33
        # refs were never even looked at. A checkout that is mid-rebase or detached is owned by
        # another process; the refs stay readable, so evaluate them read-only instead of
        # reporting nothing. The real fast-forward case still refuses to run over local work.
        if dirty:
            return "no-upstream", ("no upstream tracking branch (HEAD detached or mid-rebase, "
                                   "%d uncommitted/conflicted file(s))" % len((out or "").splitlines()))
        return "no-upstream", "no upstream tracking branch"
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
        # AN ABSENT CHECKOUT MUST BE LOUD, NOT INVISIBLE. Measured 2026-10-18: kosher-ai-filter's
        # registry `repo` was /home/zabz/repos/kosher-filter-ai, which did not exist on this box
        # (its own repo_declared_note says so), so this `continue` dropped the project from every
        # report - the tool printed "0 integration item(s) filed" twelve times in a row and nothing
        # anywhere named the cause. The whole point of this file is to make unmerged work VISIBLE; a
        # skip that prints nothing is the failure it exists to prevent.
        if not raw or raw.upper().startswith("UNKNOWN") or not Path(raw).exists():
            why = ("registry repo %r does not exist on this host" % (raw or ""))
            report.append({"project": pid, "repo": raw or "", "skipped": "no-repo", "why": why,
                           "base": None, "recent_unmerged": 0, "older_unmerged": 0, "merged": 0,
                           "merged_refs": [], "filed": [], "older_sample": []})
            print("%-18s SKIPPED (no-repo): %s" % (pid, why), file=sys.stderr)
            continue
        registered = Path(raw)
        repo, scope = resolve_checkout(registered)
        if repo is None:
            why = ("%r exists but is not inside a git checkout: `git rev-parse "
                   "--show-toplevel` failed" % raw)
            report.append({"project": pid, "repo": raw, "skipped": "no-git", "why": why,
                           "base": None, "recent_unmerged": 0, "older_unmerged": 0, "merged": 0,
                           "merged_refs": [], "filed": [], "older_sample": []})
            print("%-18s SKIPPED (no-git): %s" % (pid, why), file=sys.stderr)
            continue
        real = str(repo.resolve())
        # The KEY IS (checkout, scope), not the checkout alone. rental-system, housekeeping and
        # prod-db-sync all resolve into /opt/company, but rental-system is scoped to
        # apps/rentals/ and must still be reported; keying on the checkout alone would silently
        # drop whichever of them ran second (the same class of invisibility as the no-git skip).
        if (real, scope) in seen_repos:
            # two registry rows can point at one repo AND scope (housekeeping and prod-db-sync
            # both point at personal-secretary-mvp); integrating the same branch twice is
            # duplicate work
            continue
        seen_repos.add((real, scope))
        base = pick_base(repo, row)
        state, detail = sync_clone(repo)
        # A SHALLOW CLONE CANNOT ANSWER "IS THIS BRANCH MERGED", SO IT MUST NOT GUESS.
        # Measured 2026-10-18, filed as ledger item 545 by a shift against this tool: the checkout was
        # shallow (.git/shallow cut master at cd6ca1c1f), so `merge-base --is-ancestor` returned FALSE
        # for origin/integrate/master-34 even though that branch is master 4026431c9's DIRECT PARENT
        # and 0 ahead, and `merge-tree` could not help either. So item 533 was filed as unmerged work
        # and a whole shift was spent proving it was a no-op; items 533-537 shared the risk.
        # Truncated history is not evidence. Skipping is the honest answer, and it is loud.
        _src, _sout, _ = git(repo, "rev-parse", "--is-shallow-repository", timeout=30)
        if (_sout or "").strip() == "true":
            state = "shallow"
            detail = ("git history is shallow (.git/shallow): ancestry and merge-tree cannot be "
                      "trusted here, so NO branch in this repo can be called unmerged")
        if state in ("diverged", "dirty", "error", "shallow"):
            # EVERY KEY THE PRINTER READS MUST BE PRESENT. The first version of this record lacked
            # recent_unmerged/older_unmerged/merged, so the summary loop raised KeyError and dumped a
            # traceback into the report - the one output a human reads.
            report.append({"project": pid, "repo": real, "skipped": state, "why": detail,
                           "base": None, "recent_unmerged": 0, "older_unmerged": 0, "merged": 0,
                           "merged_refs": [], "filed": [], "older_sample": []})
            print("%-18s SKIPPED (%s): %s" % (pid, state, detail), file=sys.stderr)
            continue
        git(repo, "fetch", "--quiet", "--prune", "origin", timeout=300)
        recent, old, merged = [], [], []
        inc = None if a.all_branches else re.compile(a.include)
        allrefs = candidate_refs(repo)
        for ref in allrefs:
            if is_attempt_ref(pid, ref):
                continue
            if inc and not inc.search(ref):
                continue
            if is_merged(repo, ref, base):
                # Scope is applied to DEBT, not to the merged tally: a merged ref's
                # base...ref diff is empty by definition, so testing it for subdir changes
                # would report merged=0 for every scoped project.
                merged.append(ref)
                continue
            if not branch_touches_scope(pid, repo, base, ref, scope):
                continue
            age = tip_age_days(repo, ref)
            (recent if (a.days == 0 or age <= a.days) else old).append((ref, round(age, 1)))
        # ANCESTOR SUPERSESSION (ledger item 329, measured 2026-10-01). A ref that is an ancestor
        # of another unmerged ref is carried along by merging the descendant, so it is NOT separate
        # integration debt. Measured: origin/integrate/main-30, -31, -32, -33 and -37 are ALL
        # ancestors of origin/integrate/main-38, yet the generator had already tracked items
        # 323/324/325 for three of them and would file two more: five unfinishable items for the
        # single owner-blocked act of advancing origin/main to main-38. Keep only the maximal refs.
        # Two different ref names for the SAME commit are not treated as superseding each other.
        revs = {}
        for _r, _a in recent:
            _rc, _out, _ = git(repo, "rev-parse", _r, timeout=30)
            revs[_r] = (_out or "").strip()
        superseded = set()
        for _r in revs:
            for _s in revs:
                if _r == _s or revs[_r] == revs[_s]:
                    continue
                _rc, _, _ = git(repo, "merge-base", "--is-ancestor", _r, _s, timeout=60)
                if _rc == 0:
                    superseded.add(_r)
                    break
        # A PUSHED integrate/* BRANCH IS A CARRIER TOO (item 638, measured 2026-10-10). The
        # attempt-ref filter above drops integrate/<base>-<item> from the candidate list, so a
        # source branch merged only into such a pushed integration branch looked unmerged and
        # the hourly cron re-filed it: origin/kf535/ios-fail-closed-config (542dd32) is an
        # ancestor of pushed integrate/main-611 (6d71e3e) and integrate/main-632 (31778fe),
        # the identical merge, yet it was filed five times (items 611/632/641/653/656) and each
        # re-file cost a shift a full merge+test cycle for zero new content. Merging that pushed
        # integration branch carries the source branch, so it is not separate integration debt.
        # Carriers are consulted SEPARATELY from the pairwise test above so the deliberate
        # attempt-ref skip is not widened: the candidate set is unchanged.
        carriers = {}
        for _c in allrefs:
            if not _c.startswith("origin/integrate/"):
                continue
            _rc, _out, _ = git(repo, "rev-parse", _c, timeout=30)
            if _rc == 0 and (_out or "").strip():
                carriers[_c] = _out.strip()
        for _r in revs:
            if _r in superseded:
                continue
            for _s, _sv in carriers.items():
                if revs[_r] == _sv:
                    continue
                _rc, _, _ = git(repo, "merge-base", "--is-ancestor", _r, _s, timeout=60)
                if _rc == 0:
                    superseded.add(_r)
                    break
        if superseded:
            recent = [(r, a) for (r, a) in recent if r not in superseded]
        filed = []
        have = open_titles(pid)
        for ref, age in sorted(recent):
            if filed_run >= a.limit:
                filed.append({"branch": ref, "age_days": age, "item": "deferred (per-run limit)"})
                continue
            # BEFORE ASKING FOR A MERGE, CHECK THE CLAIM THE BRANCH MAKES (item 1134).
            skip = None
            conflict = ""
            for iid in sorted(ref_ledger_ids(repo, base, ref)):
                st, ititle = ledger_state(iid)
                if st in ("running", "claimed"):
                    skip = ("in-flight: ledger %d is %s (%s) - another shift owns it"
                            % (iid, st, ititle[:60]))
                    break
                if st == "done":
                    where = base_names_item(repo, base, iid)
                    if where:
                        skip = ("duplicate: ledger %d is already done on %s (%s); the base "
                                "implementation wins, this branch is the second one"
                                % (iid, base, where))
                        break
                    conflict = ("TWO IMPLEMENTATIONS OF LEDGER %d: branch commits name it and "
                                "the ledger calls it done, but %s names no commit for it. State "
                                "WHICH implementation wins and why before merging. " % (iid, base))
            if skip:
                filed.append({"branch": ref, "age_days": age, "item": skip})
                continue
            title = "Integrate %s into %s" % (ref, base)
            if title.strip().lower() in have:
                filed.append({"branch": ref, "age_days": age, "item": "already tracked"})
                continue
            dod = ("%s contains %s and the project's own tests pass afterwards with their result "
                   "lines quoted; `git diff --diff-filter=D --name-only %s HEAD` is empty EXCEPT "
                   "paths matching the intentional credential-removal patterns %s "
                   "(master-33 commit 012f8a35, item 287)" %
                   (base, ref, base, ", ".join(CREDENTIAL_EXEMPT)))
            why = (conflict + "a shift pushed this branch %s day(s) ago and nothing merges it; an unmerged "
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
        report.append({"project": pid, "repo": str(registered.resolve()), "git_root": real,
                       "scope": scope, "base": base,
                       "recent_unmerged": len(recent), "older_unmerged": len(old),
                       "merged": len(merged), "merged_refs": sorted(merged), "filed": filed,
                       "older_sample": [r for r, _ in old[:5]]})

    if a.json:
        print(json.dumps(report, indent=2))
        return 0
    to_file = 0
    for r in report:
        # In --dry-run every entry is the string "would-file", so an int-only count printed
        # "0 integration item(s) would be filed" directly under the branch it had just listed
        # (measured 2026-10-22, item 1110). Count the dry-run marker too.
        newly = [f for f in r["filed"]
                 if isinstance(f["item"], int) or f["item"] == "would-file"]
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
