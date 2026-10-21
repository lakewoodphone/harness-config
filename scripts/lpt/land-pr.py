#!/usr/bin/env python3
"""land-pr.py - update a PR branch with `test`, wait for the three REQUIRED contexts, then merge it.

WHY THIS EXISTS. Branch protection on `test` is `strict: true` with three required contexts
(`CI Validation (PR Pre-Check)`, `Check for Phantom Dependencies`, `Build image and assert the sha
label`). A branch that is one commit behind cannot merge, and GitHub words that refusal as
"3 of 3 required status checks are expected" - the same sentence it uses when a check is genuinely
missing - so a human reads "checks are expected" while every check has passed. The fix is not to
bypass protection: it is to do the update-then-merge dance in one place, in the right order, and to
print the two facts separately (behind=, required=) so the next reader can tell which one refused.

Usage: land-pr.py <head-branch> [--base test|main] [--timeout-min 30]
Exit: 0 merged, 1 not merged (with the reason), 2 could not read GitHub.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "lakewoodphone/phone-and-tech-full"
WORK = "/root/repos/phone-and-tech-full"
REQUIRED = ("CI Validation (PR Pre-Check)", "Check for Phantom Dependencies",
            "Build image and assert the sha label")


def token():
    raw = open("/root/.git-credentials", encoding="utf-8").read()
    m = re.search(r"https://([^:]+):([^@]+)@github\.com", raw)
    if not m:
        raise SystemExit("no github credential")
    return m.group(2)


def api(path, tok, method="GET", body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "land-pr")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def git(*args, cwd=WORK):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)


def update_branch(head, base):
    """Merge origin/<base> into the branch, in a worktree, and push. Returns (ok, note)."""
    git("fetch", "-q", "origin")
    git("worktree", "remove", "--force", "/root/repos/_wtland")
    subprocess.run(["rm", "-rf", "/root/repos/_wtland"], capture_output=True)
    p = git("worktree", "add", "--detach", "/root/repos/_wtland", "origin/%s" % head)
    if p.returncode != 0:
        return False, "worktree failed: %s" % p.stderr.strip()[:200]
    behind = git("rev-list", "--count", "HEAD..origin/%s" % base, cwd="/root/repos/_wtland")
    if behind.stdout.strip() == "0":
        git("worktree", "remove", "--force", "/root/repos/_wtland")
        return True, "already up to date with %s" % base
    m = git("-c", "user.email=zabz@lpt", "-c", "user.name=zabz", "merge", "--no-edit",
            "origin/%s" % base, cwd="/root/repos/_wtland")
    if m.returncode != 0:
        conflicts = m.stdout.count("CONFLICT") + m.stderr.count("CONFLICT")
        git("merge", "--abort", cwd="/root/repos/_wtland")
        git("worktree", "remove", "--force", "/root/repos/_wtland")
        return False, "%d conflict(s) merging origin/%s" % (conflicts, base)
    push = git("push", "-q", "origin", "HEAD:refs/heads/%s" % head, cwd="/root/repos/_wtland")
    head_sha = git("rev-parse", "--short", "HEAD", cwd="/root/repos/_wtland").stdout.strip()
    git("worktree", "remove", "--force", "/root/repos/_wtland")
    if push.returncode != 0:
        return False, "push failed: %s" % push.stderr.strip()[:200]
    return True, "updated to %s (was %s behind)" % (head_sha, behind.stdout.strip())


def main():
    head = sys.argv[1]
    base = "main" if "--base-main" in sys.argv else "test"
    timeout_min = 30
    for i, a in enumerate(sys.argv):
        if a == "--timeout-min":
            timeout_min = int(sys.argv[i + 1])
    tok = token()
    if head in ("test", "main"):
        # A promotion's head IS the protected source branch: pushing to refs/heads/test is refused
        # by protection (GH006 "3 of 3 required status checks are expected"), and there is nothing
        # to merge into it anyway. Poll and merge; never push.
        note = "head is the protected branch itself - nothing to update"
    else:
        ok, note = update_branch(head, base)
        if not ok:
            print("update: %s" % note)
            return 1
    print("update: %s" % note)
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        st, prs = api("/repos/%s/pulls?state=open&head=lakewoodphone:%s&base=%s" % (REPO, head, base), tok)
        if st != 200 or not prs:
            print("no open PR for %s -> %s" % (head, base))
            return 2
        pr = prs[0]
        sha = pr["head"]["sha"]
        git("fetch", "-q", "origin")
        behind = git("rev-list", "--count", "%s..origin/%s" % (sha, base)).stdout.strip()
        st2, chk = api("/repos/%s/commits/%s/check-runs" % (REPO, sha), tok)
        runs = {c["name"]: c for c in chk.get("check_runs", [])} if st2 == 200 else {}
        req_state = {n: (runs.get(n, {}).get("conclusion") or runs.get(n, {}).get("status") or "absent")
                     for n in REQUIRED}
        print("  behind=%s required=%s" % (behind, req_state))
        if behind == "0" and all(v == "success" for v in req_state.values()):
            st3, res = api("/repos/%s/pulls/%s/merge" % (REPO, pr["number"]), tok, "PUT",
                           {"merge_method": "merge", "commit_title": pr["title"]})
            print("merge: HTTP %s merged=%s sha=%s %s"
                  % (st3, res.get("merged"), (res.get("sha") or "")[:9], res.get("message", "")))
            if res.get("merged"):
                return 0
        time.sleep(30)
    print("timed out after %d min without a merge" % timeout_min)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
