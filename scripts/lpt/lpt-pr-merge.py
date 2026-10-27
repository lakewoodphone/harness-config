#!/usr/bin/env python3
"""lpt-pr-merge - land ONE pull request into `test`, and say what it refused to do.

WHY THIS EXISTS (2026-10-27). The loop's integration link had no mechanism. Measured that
evening: PR #690 ("a customer reads their own repair status without a login", ledger
lpt-website#946) had been open 21 hours, its own checks were GREEN 44/44, and NOTHING merges
pull requests anywhere in this estate - `work-integrator.py` turns an unmerged branch into a
ledger item and stops there. A green PR that nothing merges is work that was built and never
shipped, and the branch rots: by the next day it is `behind` and its checks no longer satisfy
the branch protection rule, which is exactly what GitHub answered when a plain merge was tried
(405 "3 of 3 required status checks are expected").

WHAT IT REFUSES, and why each refusal is a sentence and not a silent skip:
  * a base that is not `test` - this tool lands test work only. Production is the owner's.
  * a draft, or a PR carrying the `do-not-merge` label.
  * `mergeable_state: dirty` - a conflicting PR is not integration debt, it is debris; say so
    and name the files if GitHub will.
  * a PR whose checks are not GREEN - and it prints the failing check names.
  * `behind` - it UPDATES the branch instead (merging test into the head), prints the new
    head sha, and exits 3 so the caller knows the merge did not happen yet. Checks re-run;
    call again when they are green. Never force the merge past the protection rule.

It takes an explicit PR number, always. There is no sweep mode: an automatic merger that walks
the queue is a machine that ships unreviewed work while nobody is looking, and that is the one
thing this estate cannot afford in the repository that serves customers.

READ-ONLY except for the one merge / one branch update it is asked to perform.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

REPO = "lakewoodphone/phone-and-tech-full"
CREDS = "/root/.git-credentials"
BASE = "test"


def token() -> str:
    raw = open(CREDS, encoding="utf-8").read().strip()
    return raw.split(":", 2)[2].split("@", 1)[0]


def call(path: str, tok: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lpt-pr-merge/1",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b""
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"message": raw.decode("utf-8", "replace")[:400]}


def check_state(tok: str, sha: str) -> tuple[str, list[str], list[str]]:
    _, runs = call("/repos/%s/commits/%s/check-runs?per_page=100" % (REPO, sha), tok)
    failed, pending, passed = [], [], 0
    for r in runs.get("check_runs", []):
        concl = r.get("conclusion")
        if concl in ("success", "neutral", "skipped"):
            passed += 1
        elif concl in (None, "queued", "in_progress"):
            pending.append(r.get("name", "?"))
        else:
            failed.append("%s=%s" % (r.get("name"), concl))
    total = len(runs.get("check_runs", []))
    if failed:
        return "RED", failed, pending
    if pending:
        return "PENDING", failed, pending
    return ("GREEN" if total else "NONE"), failed, pending


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: lpt-pr-merge.py <pr-number> [--yes]", file=sys.stderr)
        return 2
    num = int(sys.argv[1])
    yes = "--yes" in sys.argv
    tok = token()
    st, pr = call("/repos/%s/pulls/%d" % (REPO, num), tok)
    if st != 200:
        print("lpt-pr-merge: cannot read PR #%d: %s %s" % (num, st, pr.get("message")), file=sys.stderr)
        return 2
    base = pr["base"]["ref"]
    head_sha = pr["head"]["sha"]
    labels = [l["name"] for l in pr.get("labels", [])]
    state, failed, pending = check_state(tok, head_sha)
    print("PR #%d  base=%s  head=%s  draft=%s  mergeable=%s/%s  checks=%s  files=%d  age_open" % (
        num, base, head_sha[:10], pr["draft"], pr["mergeable"], pr["mergeable_state"],
        state, pr["changed_files"]))
    print("  title: %s" % pr["title"][:100])

    refusals = []
    if base != BASE:
        refusals.append("base is '%s', not '%s' - this tool only lands test work" % (base, BASE))
    if pr["draft"]:
        refusals.append("draft PR")
    if "do-not-merge" in labels:
        refusals.append("carries the do-not-merge label")
    if state == "RED":
        refusals.append("checks are RED: %s" % ", ".join(failed[:6]))
    if pr["mergeable_state"] == "dirty":
        refusals.append("mergeable_state=dirty (CONFLICTING) - resolve or close it; a conflicting "
                        "branch is debris, not integration debt")
    if refusals:
        for r in refusals:
            print("  REFUSED: " + r)
        return 1

    if pr["mergeable_state"] == "behind":
        if not yes:
            print("  WOULD update the head branch (it is behind %s). Re-run with --yes." % BASE)
            return 3
        st, res = call("/repos/%s/pulls/%d/update-branch" % (REPO, num), tok, "PUT", {})
        print("  updated head branch: %s %s" % (st, (res.get("message") or "")[:160]))
        if st not in (200, 201, 202):
            return 2
        print("  not merged: checks must re-run on the updated head. Call again when GREEN.")
        return 3

    if state != "GREEN":
        print("  REFUSED: checks are %s%s" % (state, (": " + ", ".join(pending[:6])) if pending else ""))
        return 1

    if not yes:
        print("  WOULD merge (checks GREEN %d, clean). Re-run with --yes." % (len(failed) + 0))
        return 3

    st, res = call("/repos/%s/pulls/%d/merge" % (REPO, num), tok, "PUT",
                   {"merge_method": "merge",
                    "commit_title": "%s (#%d)" % (pr["title"][:80], num),
                    "commit_message": "Landed by lpt-pr-merge 2026-10-27 after %d failed checks and "
                                      "a GREEN run; see the PR body for the ledger item." % len(failed)})
    print("  merge: %s %s" % (st, res.get("sha") or res.get("message")))
    return 0 if st == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
