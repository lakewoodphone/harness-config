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


def checks(tok: str, sha: str) -> dict:
    """Aggregate over BOTH surfaces: check-runs (Actions) and legacy statuses."""
    out = {"total": 0, "failed": [], "pending": [], "passed": 0, "state": "none"}
    try:
        runs = api("/repos/%s/commits/%s/check-runs?per_page=100" % (REPO, sha), tok)
        for r in runs.get("check_runs", []):
            out["total"] += 1
            name = r.get("name")
            concl = r.get("conclusion")
            stat = r.get("status")
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
            ids = [r.get("id") for r in runs.get("check_runs", [])
                   if r.get("conclusion") not in ("success", "neutral", "skipped", None)][:3]
            notes = []
            for cid in ids:
                ann = api("/repos/%s/check-runs/%s/annotations" % (REPO, cid), tok)
                for a in ann if isinstance(ann, list) else []:
                    msg = (a.get("message") or "")
                    if "payments have failed" in msg or "spending limit" in msg:
                        notes.append(msg[:160])
            if notes:
                out["state"] = "BILLING"
                out["billing_note"] = notes[0]
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
        h["checks"] = checks(tok, h["sha"])
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
