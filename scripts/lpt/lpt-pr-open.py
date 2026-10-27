#!/usr/bin/env python3
"""lpt-pr-open - open ONE pull request into `test` for a branch that is waiting to land.

WHY THIS EXISTS (2026-10-27). 14 ledger items for the LPT website are `done` and their work is
sitting on a pushed branch that nobody opened a pull request for: `lpt-reconcile.py`'s D4 class,
measured at 23:52Z. A shift's contract ends at "branch pushed, awaits integrator merge", and the
integrator (`work-integrator.py`) only FILES a ledger item for the branch - so the loop's last
link was a human remembering. This opens the PR so the branch becomes mergeable by the rules
the repository already enforces (required checks on `test`).

WHAT IT REFUSES, each with a sentence:
  * a base that is not `test` - production promotion is the owner's, never this tool's;
  * a head branch that is not strictly ahead of the base (nothing to land);
  * a branch which already has an open PR - it prints that PR's number instead of making a second;
  * an empty title.
It never merges anything: merging is `lpt-pr-merge.py`, which also refuses without green checks.

  lpt-pr-open.py --head BRANCH --title "..." [--body-file PATH] [--body "..."] [--base test] [--dry]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

REPO = "lakewoodphone/phone-and-tech-full"
CREDS = "/root/.git-credentials"


def token() -> str:
    raw = open(CREDS, encoding="utf-8").read().strip()
    return raw.split(":", 2)[2].split("@", 1)[0]


def call(path: str, tok: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lpt-pr-open/1",
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


def arg(name: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> int:
    head = arg("--head")
    title = arg("--title")
    base = arg("--base", "test")
    body = arg("--body", "") or ""
    body_file = arg("--body-file")
    if body_file:
        body = open(body_file, encoding="utf-8").read()
    if not head or not title:
        print("usage: lpt-pr-open.py --head BRANCH --title TEXT [--body-file PATH] [--base test] [--dry]",
              file=sys.stderr)
        return 2
    if base != "test":
        print("REFUSED: base must be 'test'; production is promoted by the owner, not by this tool",
              file=sys.stderr)
        return 1
    tok = token()

    st, prs = call("/repos/%s/pulls?state=open&head=lakewoodphone:%s&base=%s" % (REPO, head, base), tok)
    if st == 200 and prs:
        print("already open: PR #%s %s" % (prs[0]["number"], prs[0]["title"][:70]))
        return 0

    st, cmp_ = call("/repos/%s/compare/%s...%s" % (REPO, base, head), tok)
    if st != 200:
        print("REFUSED: cannot compare %s...%s: %s %s" % (base, head, st, cmp_.get("message")),
              file=sys.stderr)
        return 2
    ahead = cmp_.get("ahead_by", 0)
    files = len(cmp_.get("files", []) or [])
    print("compare: %s is %s commit(s) ahead of %s, touching %s file(s)" % (head, ahead, base, files))
    if not ahead:
        print("REFUSED: nothing to land - the branch has no commits the base does not already have",
              file=sys.stderr)
        return 1
    if "--dry" in sys.argv:
        print("would open PR: %s -> %s" % (head, base))
        return 3

    st, pr = call("/repos/%s/pulls" % REPO, tok, "POST",
                  {"title": title, "head": head, "base": base, "body": body})
    if st not in (200, 201):
        print("FAILED to open the PR: %s %s" % (st, pr.get("message")), file=sys.stderr)
        return 2
    print("opened PR #%s  %s" % (pr["number"], pr["html_url"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
