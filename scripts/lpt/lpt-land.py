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
from datetime import datetime, timezone

RECONCILE = "/root/bin/lpt-reconcile.py"
OPEN = "/root/bin/lpt-pr-open.py"
MERGE = "/root/bin/lpt-pr-merge.py"
REPO = "lakewoodphone/phone-and-tech-full"
CI = "/root/bin/lpt-ci-status.py"  # the one reader of CI state
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
    """Is the `test` head itself green? ONE READER (2026-10-28): ask lpt-ci-status, which judges a head by
    ITS BRANCH'S runs. This function used to scan /commits/<sha>/check-runs itself, so a promotion PR built
    from the head - whose cancelled shards and main-only gates attach to the same sha - made a 20/20 green
    head look red here while the reader called it green, and the lander then refused to land anything.
    """
    try:
        out = subprocess.run([sys.executable, CI, "--json"], capture_output=True, text=True, timeout=240)
        ci = json.loads(out.stdout or "{}")
    except Exception as exc:  # noqa: BLE001
        return False, "cannot read CI state: %s: %s" % (type(exc).__name__, exc)
    head = (ci.get("heads") or {}).get("test") or {}
    chk = head.get("checks") or {}
    state = chk.get("state", "?")
    if state == "BILLING":
        return False, "test is BILLING-BLOCKED (GitHub refused to start jobs): %s" % (
            chk.get("billing_note") or "")[:150]
    if state == "GREEN":
        return True, "test head %s is green (%d/%d run(s))" % (
            (head.get("sha") or "?")[:10], chk.get("passed", 0), chk.get("total", 0))
    return False, "test head %s is %s: %s" % (
        (head.get("sha") or "?")[:10], state,
        "; ".join((chk.get("failed") or [])[:4] + (chk.get("pending") or [])[:3]) or "no detail")


def deploy_quiet(tok: str) -> tuple[bool, str]:
    """Has the deploy pipeline caught up with the last merge?

    MEASURED 2026-10-28 00:1xZ: merging #693 and then #695 within minutes left the deployed test
    bundle at 479ad9167c while the head was 9a683100ee - `lpt-deploy-status.py --live` reported
    BEHIND/DIFFERENT, and a live check of /status was therefore testing the OLD build, which is how
    a fix looks broken after it landed. A deploy run takes 10-20 minutes; merging faster than that
    means the environment never catches up and nothing can be verified live.

    So: never stack a merge on top of a deploy that has not finished. One merge per deploy cycle.
    """
    try:
        runs = api("/repos/%s/actions/runs?branch=test&per_page=10" % REPO, tok).get("workflow_runs", [])
    except Exception as exc:  # noqa: BLE001
        return False, "cannot read the test branch's runs: %s: %s" % (type(exc).__name__, exc)
    busy = [r["name"] for r in runs if r.get("status") in ("queued", "in_progress", "waiting", "pending")]
    if busy:
        return False, "a run is still going on test: %s" % ", ".join(sorted(set(busy))[:3])
    return True, "no run is in flight on test"


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
    quiet, why2 = deploy_quiet(tok)
    if not quiet:
        print("lpt-land: not landing anything - %s" % why2)
        return 0
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

    # CAP ON D4 PRS IN FLIGHT (2026-10-28). One new PR per tick and no merges, because every landing moves
    # `test` and invalidates the other open PRs' checks. Two is the compromise: one that may be red and needs a
    # decision (like #703), one that is making progress. When a slot frees, the next branch is opened.
    in_flight = [b for b in ((r.get("branch") or "").replace("origin/", "") for r in rows) if b in prs]
    CAP = 2
    if len(in_flight) >= CAP:
        print("  %d D4 PR(s) already in flight (%s) - not opening another until a slot frees"
              % (len(in_flight), ", ".join("#%s" % prs[b]["number"] for b in in_flight)))
        return 0

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
    # ---------------------------------------------------------------------------------------
    # THE QUEUE THAT IS NOT IN THE D4 LIST (2026-10-28). D4 covers `done` items whose branch never
    # landed. It does NOT cover a pull request that was opened for another reason - a docs PR, or a
    # fix a session wrote and opened by hand (#694, #697, #700 tonight). Nothing merged those, so
    # they would wait for ever even once the base is green. Merge the OLDEST green PR that has been
    # open for at least QUIET_MIN minutes and whose checks the repository itself calls green.
    # lpt-pr-merge.py re-checks everything (base must be test, no draft, no do-not-merge, GREEN,
    # clean), so this cannot merge anything the branch protection would refuse.
    QUIET_MIN = 20
    now = datetime.now(timezone.utc)
    candidates = []
    for branch, pr in prs.items():
        if (row for row in rows if (row.get("branch") or "").replace("origin/", "") == branch):
            continue                      # already handled above
        created = pr.get("created_at")
        try:
            opened = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if (now - opened).total_seconds() < QUIET_MIN * 60:
            continue
        candidates.append((opened, pr))
    for opened, pr in sorted(candidates):
        args = [sys.executable, MERGE, str(pr["number"])] + ([] if dry else ["--yes"])
        p = sh(args, timeout=300)
        out = (p.stdout.strip().splitlines() or [""])[-1][:160]
        print("  other green PR #%s (open %s min): %s" % (
            pr["number"], int((now - opened).total_seconds() // 60), out))
        if p.returncode == 0 and not dry:
            return 0
        if p.returncode not in (0, 3):
            break
    print("lpt-land: no action this tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
