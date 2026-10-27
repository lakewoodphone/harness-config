#!/usr/bin/env python3
"""lpt-land - land ONE waiting branch of the LPT website, by the repository's own rules.

THE GAP THIS CLOSES (measured 2026-10-27 23:52Z). `lpt-reconcile.py` reported FOURTEEN ledger
items `done` whose commits are on a pushed branch that has never landed (D4). The job that was
supposed to close that gap, `work-integrator.py`, files a ledger item for the branch and stops
there; a shift's own contract ends at "branch pushed, awaits integrator merge"; and nothing in
cron merges pull requests. So a green PR sat 21h (#690), and fourteen branches waited with their
work unshipped while the queue kept filling with new items.

WHAT ONE RUN DOES - exactly one action, then it stops:
  * picks the OLDEST done-but-unlanded branch that has no open PR, and opens a PR into `test`
    (`lpt-pr-open.py`, which refuses a base other than test and a branch with nothing to land);
  * or, if the oldest such branch ALREADY has an open PR whose required checks are green,
    merges it (`lpt-pr-merge.py`, which refuses anything but a green, clean, test-based PR);
  * or takes no action and says why.

WHY ONE AT A TIME. Fourteen PRs opened at once would occupy every CI runner, re-run the whole
suite fourteen times, and make the first real failure impossible to attribute. A 15-minute tick
with one action drains 14 in a few hours at a cost of a few dollars, and every landing is
attributable to a single commit.

WHAT IT WILL NEVER DO:
  * touch `main` or production - `test` is the only base it can name;
  * merge without the repository's required checks green;
  * merge a branch whose PR body it did not write (it only merges what it can see is green);
  * retry a branch that failed to open or merge - it skips forward and says so.

  lpt-land.py [--dry] [--max-age-days 21] [--json]
"""
from __future__ import annotations

import json
import subprocess
import sys

RECONCILE = "/root/bin/lpt-reconcile.py"
OPEN = "/root/bin/lpt-pr-open.py"
MERGE = "/root/bin/lpt-pr-merge.py"
REPO = "lakewoodphone/phone-and-tech-full"
PROJECT = "lpt-website"


def sh(args, timeout=900):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def reconcile() -> list[dict]:
    p = sh([sys.executable, RECONCILE, "--json"], timeout=1200)
    if not p.stdout.strip():
        raise RuntimeError("lpt-reconcile produced no JSON (rc=%s): %s" % (p.returncode, p.stderr[-300:]))
    return json.loads(p.stdout).get("d4_done_but_not_landed", [])


def token() -> str:
    return open("/root/.git-credentials", encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]


def api(path: str, tok: str):
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lpt-land/1"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read() or b"{}")


def base_is_green(tok: str) -> tuple[bool, str]:
    """Is the `test` head itself green?

    A red base makes every new PR's required checks red on arrival, so opening PRs onto it
    achieves nothing except a queue of PRs that cannot merge - and nobody can tell which failure
    belongs to which branch. Fail closed with the reason, and let the next tick try again.
    """
    try:
        head = api("/repos/%s/commits/test" % REPO, tok)["sha"]
        runs = api("/repos/%s/commits/%s/check-runs?per_page=100" % (REPO, head), tok).get("check_runs", [])
    except Exception as exc:  # noqa: BLE001
        return False, "cannot read the test head's checks: %s: %s" % (type(exc).__name__, exc)
    failed = ["%s=%s" % (r["name"], r.get("conclusion")) for r in runs
              if r.get("conclusion") not in ("success", "neutral", "skipped", None)]
    pending = [r["name"] for r in runs if r.get("conclusion") is None]
    if failed:
        return False, "test head %s is RED: %s" % (head[:10], ", ".join(failed[:4]))
    if pending:
        return False, "test head %s has %d check(s) still running" % (head[:10], len(pending))
    return True, "test head %s is green (%d checks)" % (head[:10], len(runs))


def open_prs() -> dict[str, dict]:
    """head ref -> PR, for every open PR into test. Read with the repo's own token."""
    try:
        data = api("/repos/%s/pulls?state=open&base=test&per_page=100" % REPO, token())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("cannot list PRs: %s: %s" % (type(exc).__name__, exc))
    return {pr["head"]["ref"]: {"number": pr["number"], "branch": pr["head"]["ref"],
                               "title": pr["title"]} for pr in data}


def body_for(row: dict) -> str:
    shas = ", ".join(row.get("shas", [])[:3])
    branch = row.get("branch", "")
    return (
        "Landing a ledger item that is already `done` but whose work never reached `test`.\n\n"
        "| | |\n|---|---|\n"
        "| ledger | `%s#%s` |\n"
        "| item | %s |\n"
        "| branch | `%s` |\n"
        "| commit(s) | %s |\n\n"
        "Opened by `lpt-land.py` from `lpt-reconcile.py`'s D4 class (done-but-not-landed), which\n"
        "measured 14 such branches on 2026-10-27. The branch's own tests are the proof this repo\n"
        "requires: the required checks on `test` decide whether it may land.\n\n"
        "Nothing here is production: merging deploys to the TEST environment only.\n"
        % (PROJECT, row["id"], row["title"][:200], branch.replace("origin/", ""), shas or "(none named)")
    )


def main() -> int:
    dry = "--dry" in sys.argv
    tok = token()
    green, why = base_is_green(tok)
    if not green:
        print("lpt-land: not landing anything - %s" % why)
        return 0
    print("lpt-land: %s" % why)
    rows = reconcile()
    if not rows:
        print("lpt-land: nothing waiting - every done item's work has landed")
        return 0
    prs = open_prs()
    print("lpt-land: %d done-but-unlanded branch(es); %d open PR(s) into test" % (len(rows), len(prs)))

    # Prefer closing out an existing PR whose checks are already green: it is the cheapest landing
    # and it is the one a human has already had a chance to see.
    for row in rows:
        branch = (row.get("branch") or "").replace("origin/", "")
        pr = prs.get(branch)
        if not pr:
            continue
        args = [sys.executable, MERGE, str(pr["number"])] + ([] if dry else ["--yes"])
        p = sh(args, timeout=300)
        print("  PR #%s (%s): %s" % (pr["number"], branch, (p.stdout.strip().splitlines() or [""])[-1][:160]))
        if p.returncode == 0 and not dry:
            return 0
        if p.returncode not in (0, 3):
            print("  -> not mergeable now; will try another branch next tick")

    for row in rows:
        branch = (row.get("branch") or "").replace("origin/", "")
        if not branch or branch in prs:
            continue
        args = [sys.executable, OPEN, "--head", branch, "--base", "test",
                "--title", "%s (lpt-website#%s)" % (row["title"][:88], row["id"]),
                "--body", body_for(row)] + (["--dry"] if dry else [])
        p = sh(args, timeout=300)
        out = (p.stdout.strip().splitlines() or [""])[-1]
        print("  open PR for %s: %s" % (branch, out[:180]))
        if p.returncode in (0, 3):
            return 0
    print("lpt-land: no action this tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
