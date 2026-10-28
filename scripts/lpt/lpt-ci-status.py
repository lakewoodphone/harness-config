#!/usr/bin/env python3
"""lpt-ci-status - is the LPT website's integration pipeline green, right now?

READ-ONLY. Answers the question every website shift needs first and used to answer by
re-deriving it (or by trusting yesterday's ledger item):

  * the test head and MAIN head, with their commit subject and age
  * for each head, the aggregate check state GitHub reports for that sha
  * every open PR into test, whether it is mergeable, and whether it is GREEN
  * the recent workflow runs on test, with conclusion and sha

Credential: the same /root/.git-credentials token lpt-deploy-status.py uses.
Nothing here writes to GitHub or to any store.

  lpt-ci-status.py            the summary
  lpt-ci-status.py --json     the same facts as JSON
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

REPO = "lakewoodphone/phone-and-tech-full"
CREDS = "/root/.git-credentials"
UA = "lpt-ci-status/1"


def token() -> str:
    raw = open(CREDS, encoding="utf-8").read().strip()
    # https://x-access-token:<token>@github.com
    return raw.split(":", 2)[2].split("@", 1)[0]


def api(path: str, tok: str):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "Bearer " + tok,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read() or b"{}")


def age(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        when = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "?"
    h = (datetime.now(timezone.utc) - when).total_seconds() / 3600.0
    return "%.1fh" % h


def head(tok: str, branch: str) -> dict:
    d = api("/repos/%s/commits/%s" % (REPO, branch), tok)
    return {"sha": d["sha"], "subject": d["commit"]["message"].splitlines()[0][:92],
            "when": d["commit"]["committer"]["date"], "age": age(d["commit"]["committer"]["date"])}


def head_checks(tok: str, branch: str, sha: str) -> dict:
    """The state of a BRANCH HEAD, from the workflow runs recorded on that branch.

    A commit sha is not a branch. Pull requests built from a commit attach their own check-runs to it -
    cancelled shards, gates that only mean something for a PR into another branch - and reading those as
    the head's own state made a 20/20 green `test` head look red (2026-10-28T03:51Z).
    """
    out = {"total": 0, "failed": [], "pending": [], "passed": 0, "state": "none"}
    try:
        runs = api("/repos/%s/actions/runs?branch=%s&per_page=40" % (REPO, branch), tok).get("workflow_runs", [])
    except Exception as exc:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    mine = [r for r in runs if r.get("head_sha") == sha]
    out["total"] = len(mine)
    for r in mine:
        if r.get("status") != "completed":
            out["pending"].append(r.get("name"))
        elif r.get("conclusion") in ("success", "neutral", "skipped"):
            out["passed"] += 1
        else:
            out["failed"].append("%s=%s" % (r.get("name"), r.get("conclusion")))
    if not mine:
        out["state"] = "none"
    elif out["failed"]:
        out["state"] = "RED"
    elif out["pending"]:
        out["state"] = "PENDING"
    else:
        out["state"] = "GREEN"

    # Billing, still distinguished. Only when every failing run is billing-attributed is the state
    # BILLING; otherwise it stays RED and the note rides alongside (L13559).
    if out["state"] == "RED":
        billing = 0
        note = ""
        for r in mine:
            if r.get("conclusion") in ("success", "neutral", "skipped") or r.get("status") != "completed":
                continue
            try:
                suite = api("/repos/%s/check-suites/%s/check-runs" % (REPO, r.get("check_suite_id")), tok)
            except Exception:  # noqa: BLE001
                continue
            is_billing = False
            for cr in suite.get("check_runs", []):
                if cr.get("conclusion") in ("success", "neutral", "skipped", None):
                    continue
                try:
                    ann = api("/repos/%s/check-runs/%s/annotations" % (REPO, cr.get("id")), tok)
                except Exception:  # noqa: BLE001
                    continue
                for a in ann if isinstance(ann, list) else []:
                    m = (a.get("message") or "")
                    if "payments have failed" in m or "spending limit" in m:
                        is_billing = True
                        note = note or m[:160]
            billing += 1 if is_billing else 0
        if billing and billing == len(out["failed"]):
            out["state"] = "BILLING"
            out["billing_note"] = note
        elif billing:
            out["billing_note"] = note
            out["state_note"] = "%d of %d failing run(s) are billing-refused; the rest are real failures" % (
                billing, len(out["failed"]))
    return out


def checks(tok: str, sha: str) -> dict:
    """Aggregate over BOTH surfaces: check-runs (Actions) and legacy statuses."""
    out = {"total": 0, "failed": [], "pending": [], "passed": 0, "state": "none"}
    try:
        runs = api("/repos/%s/commits/%s/check-runs?per_page=100" % (REPO, sha), tok)
        # LATEST PER CONTEXT (2026-10-28). A re-run creates NEW check-runs for the same context, and branch
        # protection judges the latest result per context - so counting every historical attempt reports a
        # failure GitHub no longer holds (measured on PR #694 after a re-run).
        latest = {}
        for r in runs.get("check_runs", []):
            name = r.get("name")
            stamp = r.get("completed_at") or r.get("started_at") or ""
            prev = latest.get(name)
            if prev is None or stamp > (prev.get("completed_at") or prev.get("started_at") or ""):
                latest[name] = r
        for r in latest.values():
            out["total"] += 1
            name = r.get("name")
            concl = r.get("conclusion")
            if concl in ("success", "neutral", "skipped"):
                out["passed"] += 1
            elif concl in (None, "queued", "in_progress"):
                out["pending"].append(name)
            else:
                out["failed"].append("%s=%s" % (name, concl))
    except Exception as exc:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    try:
        st = api("/repos/%s/commits/%s/status" % (REPO, sha), tok)
        out["contexts"] = st.get("total_count")
        out["combined_status"] = st.get("state")
    except Exception:  # noqa: BLE001
        pass
    # BILLING IS NOT A CODE FAILURE (2026-10-28). GitHub answers "The job was not started because
    # recent account payments have failed or your spending limit needs to be increased" with a
    # check-run FAILURE, so a red head can mean the pipeline never ran - and this estate has now hit
    # that three times (owner rows 940, 1028, and again tonight). Reading it as RED sends the next
    # session hunting a code defect that does not exist, which is exactly what nearly happened.
    if out["failed"]:
        out["state"] = "RED"
        try:
            # EVERY failed run, not the first three: with a per-run annotation call this is what makes
            # "all of them are billing" a fact rather than a sample.
            failed_runs = [r for r in runs.get("check_runs", [])
                           if r.get("conclusion") not in ("success", "neutral", "skipped", None)]
            ids = [r.get("id") for r in failed_runs]
            notes = []
            for cid in ids:
                ann = api("/repos/%s/check-runs/%s/annotations" % (REPO, cid), tok)
                for a in ann if isinstance(ann, list) else []:
                    msg = (a.get("message") or "")
                    if "payments have failed" in msg or "spending limit" in msg:
                        notes.append(msg[:160])
            if notes:
                # A BILLING BLOCK MUST NOT HIDE A CODE FAILURE (2026-10-28). The first version set
                # state=BILLING whenever ANY failed check-run carried the billing annotation, which
                # masked a real red: head cf2da5af failed Test Frontend (Shard 4/4) on a genuine
                # assertion while two OTHER jobs were refused for money. A reading that cannot tell
                # "the pipeline never ran" from "the code is broken" is the defect this session exists
                # to remove, so: BILLING only when EVERY failure is billing; otherwise RED, with the
                # billing note carried alongside so both facts survive.
                billing_failed = set()
                for cid in ids:
                    try:
                        ann = api("/repos/%s/check-runs/%s/annotations" % (REPO, cid), tok)
                    except Exception:  # noqa: BLE001
                        continue
                    for a in ann if isinstance(ann, list) else []:
                        m = (a.get("message") or "")
                        if "payments have failed" in m or "spending limit" in m:
                            billing_failed.add(cid)
                # every failed run we could attribute to billing -> BILLING; otherwise RED
                out["billing_note"] = notes[0]
                all_billing = bool(failed_runs) and len(billing_failed) == len(failed_runs)
                out["state"] = "BILLING" if all_billing else "RED"
                if not all_billing:
                    out["state_note"] = ("%d of %d failing check(s) are billing-refused; the rest are "
                                         "real code failures" % (len(billing_failed), len(out["failed"])))
        except Exception as exc:  # noqa: BLE001
            out["billing_check_error"] = "%s: %s" % (type(exc).__name__, exc)
    elif out["pending"]:
        out["state"] = "PENDING"
    elif out["total"]:
        out["state"] = "GREEN"
    return out


def main() -> int:
    tok = token()
    want_json = "--json" in sys.argv
    data = {"repo": REPO, "heads": {}, "prs": [], "runs": []}
    for br in ("test", "main"):
        h = head(tok, br)
        # by BRANCH, not by sha: see head_checks (2026-10-28)
        h["checks"] = head_checks(tok, br, h["sha"])
        data["heads"][br] = h

    prs = api("/repos/%s/pulls?state=open&base=test&per_page=30" % REPO, tok)
    for p in prs:
        c = checks(tok, p["head"]["sha"])
        data["prs"].append({
            "number": p["number"], "title": p["title"][:96], "branch": p["head"]["ref"],
            "sha": p["head"]["sha"][:10], "mergeable": p.get("mergeable"),
            "merge_state": p.get("mergeable_state"), "age": age(p["created_at"]),
            "checks": c["state"], "failed": c["failed"][:4], "pending": c["pending"][:4],
        })

    runs = api("/repos/%s/actions/runs?branch=test&per_page=12" % REPO, tok)
    for r in runs.get("workflow_runs", []):
        data["runs"].append({"id": r["id"], "name": r["name"][:40], "event": r["event"],
                             "conclusion": r["conclusion"], "sha": r["head_sha"][:10],
                             "when": r["created_at"], "age": age(r["created_at"])})

    if want_json:
        print(json.dumps(data, indent=1))
        return 0

    print("LPT CI STATUS  (%s)" % REPO)
    for br, h in data["heads"].items():
        c = h["checks"]
        print("  %-5s %s  %-9s %-8s passed %d/%d  %s" % (
            br, h["sha"][:10], h["age"], c["state"], c["passed"], c["total"], h["subject"]))
        if c["failed"]:
            print("        FAILED: " + ", ".join(c["failed"][:8]))
        if c["pending"]:
            print("        pending: " + ", ".join(c["pending"][:6]))
    print("  open PRs into test: %d" % len(data["prs"]))
    for p in data["prs"]:
        print("    #%s %-8s %-9s mergeable=%s/%s  %s" % (
            p["number"], p["age"], p["checks"], p["mergeable"], p["merge_state"], p["title"]))
        if p["failed"]:
            print("        FAILED: " + ", ".join(p["failed"]))
    print("  recent runs on test:")
    for r in data["runs"][:8]:
        print("    #%-6s %-9s %-26s %-9s %s" % (r["id"], r["conclusion"], r["name"],
                                                r["sha"], r["age"] + " ago"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
