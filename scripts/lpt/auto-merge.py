#!/usr/bin/env python3
"""Enable auto-merge on a PR, so a landing costs ONE check cycle instead of two.

Measured 2026-10-28T05:45Z: PR #705 was GREEN, but merging moved `test`, so the PR had to be updated onto the
new base and its checks re-run - and only a LATER lander tick could merge it. Each landing therefore costs two
full check cycles (~25 minutes) for one commit, which is why thirteen branches would take hours.

GitHub can do the waiting: enable auto-merge and it merges the PR itself the instant the required checks pass.
That is the same gate branch protection already enforces - no extra permission, no faster rules - just no idle
tick in the middle.

  auto-merge.py 705        # enable
  auto-merge.py 705 --off  # disable
"""
import json
import sys
import urllib.error
import urllib.request

TOK = open("/root/.git-credentials", encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]
REPO = "lakewoodphone/phone-and-tech-full"


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body, method="POST",
        headers={"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
                 "User-Agent": "automerge", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: auto-merge.py <pr-number> [--off]")
        return 2
    num = int(sys.argv[1])
    off = "--off" in sys.argv
    owner, name = REPO.split("/")
    st, data = gql("query($o:String!,$n:String!,$num:Int!){repository(owner:$o,name:$n)"
                   "{pullRequest(number:$num){id autoMergeRequest{enabledAt}}}}",
                   {"o": owner, "n": name, "num": num})
    pr = (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {})
    if not pr:
        print("could not read PR #%d: %s" % (num, str(data)[:200]))
        return 3
    if off:
        st, res = gql("mutation($id:ID!){disablePullRequestAutoMerge(input:{pullRequestId:$id})"
                      "{clientMutationId}}", {"id": pr["id"]})
        print("disable:", st, str(res.get("errors") or "ok")[:160])
        return 0
    st, res = gql("mutation($id:ID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,"
                  "mergeMethod:MERGE}){pullRequest{number autoMergeRequest{enabledAt}}}}", {"id": pr["id"]})
    err = (res.get("errors") or [{}])[0].get("message")
    print("enable:", st, err or "armed - GitHub will merge it when the required checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
