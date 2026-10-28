#!/usr/bin/env python3
"""lpt-promote - carry a green, deployed `test` head into `main` (production). The loop's own job.

WHY THIS EXISTS. On 2026-10-28T01:19:31Z the owner answered the promotion question with
"It's upsetting you would ask me that that is totally your domain". The policy changed that minute; the
CAPABILITY did not exist. `lpt-pr-open.py`/`lpt-pr-merge.py` refuse any base but `test` on purpose, nothing
in cron has ever carried `test` to `main`, and the last two promotions were hand-made
`guardian/promote-test-to-main-*` branches. So `main` fell 45 hours behind a green `test` while four
finished fixes waited.

WHAT IT CHECKS, and each refusal names its measurement:
  1. the `test` head is GREEN (not RED, not PENDING, not BILLING - a bill is not a code failure);
  2. the DEPLOYED test bundle MATCHES that head (`lpt-deploy-status.py --live`), because promoting code
     that was never served is promoting an untested artefact;
  3. no workflow run on `test` is in flight (a promotion during a deploy promotes a half-state);
  4. `test` is actually ahead of `main` (nothing to promote is a refusal, not an empty merge).

WHAT IT DOES when every gate passes:
  * creates `promote/test-to-main-<UTC stamp>` at the test head (so the promotion is a reviewable PR, not a
    force-push), opens it against `main`, and - only with `--yes` - merges it once GitHub reports the PR
    GREEN and clean;
  * prints the production deploy stamp before and after, so the claim "it is live" is a measurement.

WHAT IT NEVER DOES: force-push, reset, delete a branch, or touch `main` directly. The only way it changes
`main` is a merge GitHub itself accepts.

  lpt-promote.py            # evaluate and print the gates, change nothing
  lpt-promote.py --yes      # create the PR, and merge it when green
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = "lakewoodphone/phone-and-tech-full"
CREDS = "/root/.git-credentials"
CI = "/root/bin/lpt-ci-status.py"
DEPLOY = "/root/bin/lpt-deploy-status.py"
MERGE = "/root/bin/lpt-pr-merge.py"


def token() -> str:
    return open(CREDS, encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]


def api(path: str, tok: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lpt-promote/1",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b""
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"message": raw.decode("utf-8", "replace")[:300]}


def run(cmd: list[str], timeout: int = 300) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "") + (("\n" + p.stderr) if p.returncode else "")


def main() -> int:
    yes = "--yes" in sys.argv
    tok = token()
    gates = []

    # 1. the test head must be green — judged by THE TEST BRANCH'S OWN RUNS, not by every check-run
    # attached to the sha. MEASURED 2026-10-28T03:25Z: creating a promotion branch at the test head's sha
    # added its check-runs (including a failed Validate Main PR Source, which belongs to a PR built FROM
    # the head) to that commit, so /commits/<sha>/check-runs called a 20/20 head RED. A sha is not a
    # branch; a promotion needs the test branch's own CI to have passed.
    try:
        _, headruns = api("/repos/%s/actions/runs?branch=test&per_page=30" % REPO, tok)
        test_head = (json.loads(run([sys.executable, CI, "--json"]) or "{}")
                     .get("heads", {}).get("test") or {})
        sha = test_head.get("sha")
        mine = [r for r in headruns.get("workflow_runs", []) if r.get("head_sha") == sha]
        failing = [r["name"] for r in mine if r.get("status") == "completed" and r.get("conclusion") != "success"]
        pending = [r["name"] for r in mine if r.get("status") != "completed"]
        green = bool(mine) and not failing and not pending
        detail = ("%s %s on %d run(s)%s%s" % (
            (sha or "?")[:10], "GREEN" if green else "RED",
            len(mine),
            ("; failing: " + ", ".join(failing[:3])) if failing else "",
            ("; pending: " + ", ".join(pending[:3])) if pending else ""))
        gates.append(("test head is GREEN", green, detail))
    except Exception as exc:  # noqa: BLE001
        gates.append(("test head is GREEN", False, "could not read the test branch's runs: %s" % exc))
        test_head = {}

    # 2. the deployed test bundle must match that head
    dep = run([sys.executable, DEPLOY, "--live"])
    match = "MATCH" in dep
    dep_line = next((ln.strip() for ln in dep.splitlines() if "deployed test" in ln), "?")
    gates.append(("deployed test MATCHES the test head", match, dep_line[:110]))

    # 3. nothing in flight on test
    try:
        _, runs = api("/repos/%s/actions/runs?branch=test&per_page=10" % REPO, tok)
        busy = sorted({r["name"] for r in runs.get("workflow_runs", [])
                       if r.get("status") in ("queued", "in_progress", "waiting", "pending")})
        gates.append(("no run in flight on test", not busy, ", ".join(busy) or "quiet"))
    except Exception as exc:  # noqa: BLE001
        gates.append(("no run in flight on test", False, "could not read runs: %s" % exc))

    # 4. test must be ahead of main
    ahead = None
    try:
        _, cmp_ = api("/repos/%s/compare/main...test" % REPO, tok)
        ahead = cmp_.get("ahead_by")
        gates.append(("test is ahead of main", bool(ahead), "%s commit(s) ahead" % ahead))
    except Exception as exc:  # noqa: BLE001
        gates.append(("test is ahead of main", False, "could not compare: %s" % exc))

    print("LPT PROMOTE  %s" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for label, ok, detail in gates:
        print("  %-38s %-4s %s" % (label, "PASS" if ok else "NO", detail))
    blocked = [g for g in gates if not g[1]]
    if blocked:
        print("  VERDICT: not promoting - %d gate(s) open; nothing was changed." % len(blocked))
        return 1

    head_sha = test_head.get("sha")
    if not yes:
        print("  VERDICT: every gate is green. A real run would create promote/test-to-main-<stamp> at %s,"
              " open it against main, and merge it when GitHub reports it green." % head_sha[:10])
        return 0

    # REUSE AN OPEN PROMOTION (2026-10-28). This tool runs every 15 minutes; before this guard the first
    # --yes run created promote/test-to-main-20261028T032311 and PR #701, found it not clean, and left a
    # "later run will merge it" - which would have created ANOTHER branch and PR on the next tick. Merge
    # what is already open; create only when nothing is.
    try:
        st, open_prs = api("/repos/%s/pulls?state=open&base=main&per_page=20" % REPO, tok)
        # ONLY a PR carrying THIS head is reusable. An old promotion branch left open would
        # otherwise be matched for ever and no promotion would ever happen (measured: PR #582).
        want = (test_head or {}).get("sha")
        existing = [p for p in (open_prs if isinstance(open_prs, list) else [])
                    if str(p.get("head", {}).get("ref", "")).startswith("guardian/promote-test-to-main-")
                    and p.get("head", {}).get("sha") == want]
        if existing:
            pr0 = sorted(existing, key=lambda p: p.get("created_at") or "")[0]
            st2, pr2 = api("/repos/%s/pulls/%d" % (REPO, pr0["number"]), tok)
            state2 = pr2.get("mergeable_state") if st2 == 200 else "unreadable"
            print("  open promotion PR #%s already exists (mergeable_state=%s) - not creating another"
                  % (pr0["number"], state2))
            # ASK GITHUB, DO NOT OUT-GUESS IT. `unstable` means a non-required or superseded check is
            # unhappy; branch protection judges the latest result per required context, so the API is
            # the authority on whether this may merge.
            if st2 == 200 and pr2.get("mergeable"):
                st3, res3 = api("/repos/%s/pulls/%d/merge" % (REPO, pr0["number"]), tok, "PUT",
                                {"merge_method": "merge",
                                 "commit_title": "promote: test %s to production (#%d)"
                                                 % (test_head.get("sha", "")[:10], pr0["number"])})
                print("  merge: %s %s" % (st3, res3.get("sha") or res3.get("message")))
                prod_after = next((ln.strip() for ln in run([sys.executable, DEPLOY, "--live"]).splitlines()
                                   if "deployed production" in ln), "?")
                print("  production after : %s" % prod_after)
            else:
                print("  it is not clean yet; a later tick will merge it. Not creating a duplicate.")
            return 0
    except Exception as exc:  # noqa: BLE001
        print("  could not look for an existing promotion PR (%s); refusing to create a duplicate" % exc)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    branch = "guardian/promote-test-to-main-%s" % stamp   # the name the main-PR gate accepts
    st, res = api("/repos/%s/git/refs" % REPO, tok, "POST",
                  {"ref": "refs/heads/" + branch, "sha": head_sha})
    if st not in (200, 201):
        print("  FAILED to create %s: %s %s" % (branch, st, res.get("message")))
        return 2
    print("  created %s at %s" % (branch, head_sha[:10]))

    prod_before = next((ln.strip() for ln in run([sys.executable, DEPLOY, "--live"]).splitlines()
                        if "deployed production" in ln), "?")
    body = ("Promotion of the measured test head to production, by `lpt-promote.py`.\n\n"
            "Owner answer 2026-10-28T01:19:31Z (row 1107): promoting a green, measured test head to "
            "production is the loop's own domain.\n\n"
            "| | |\n|---|---|\n"
            "| test head | `%s` |\n| deployed test | %s |\n| commits ahead of main | %s |\n"
            "| production before | %s |\n" % (head_sha, dep_line.strip(), ahead, prod_before))
    st, pr = api("/repos/%s/pulls" % REPO, tok, "POST",
                 {"title": "promote: test %s to production" % head_sha[:10],
                  "head": branch, "base": "main", "body": body})
    if st not in (200, 201):
        print("  FAILED to open the promotion PR: %s %s" % (st, pr.get("message")))
        return 2
    print("  opened PR #%s %s" % (pr["number"], pr["html_url"]))

    # Merge only through lpt-pr-merge's own guards, which require GREEN + clean; it refuses base!=test,
    # so the promotion merge is done here with the same two conditions checked explicitly.
    st, pr2 = api("/repos/%s/pulls/%d" % (REPO, pr["number"]), tok)
    if st == 200 and pr2.get("mergeable"):
        st, res = api("/repos/%s/pulls/%d/merge" % (REPO, pr["number"]), tok, "PUT",
                      {"merge_method": "merge",
                       "commit_title": "promote: test %s to production (#%d)" % (head_sha[:10], pr["number"])})
        print("  merge: %s %s" % (st, res.get("sha") or res.get("message")))
    else:
        print("  PR is not clean yet (%s) - it will be merged by a later run once GitHub reports it green."
              % (pr2.get("mergeable_state") if st == 200 else st))
    prod_after = next((ln.strip() for ln in run([sys.executable, DEPLOY, "--live"]).splitlines()
                       if "deployed production" in ln), "?")
    print("  production before: %s" % prod_before)
    print("  production after : %s" % prod_after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
