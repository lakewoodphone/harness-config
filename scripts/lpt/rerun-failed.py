#!/usr/bin/env python3
"""Re-run the failed jobs of ONE workflow run, and report what failed in another.

Why: the frontend shard that failed on test head 9a683100 failed with
"Error: Worker exited unexpectedly" - a crashed vitest worker on the runner, not an assertion. A
re-run is the honest response to a flake; changing code to satisfy a crash would be a lie.

  rerun-failed.py rerun <run-id>
  rerun-failed.py jobs  <run-id>
"""
import json
import sys
import urllib.error
import urllib.request

REPO = "lakewoodphone/phone-and-tech-full"
TOK = open("/root/.git-credentials", encoding="utf-8").read().strip().split(":", 2)[2].split("@", 1)[0]


def call(path: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "rerun/1",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"message": (exc.read() or b"").decode("utf-8", "replace")[:300]}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, run = sys.argv[1], sys.argv[2]
    if cmd == "rerun":
        st, res = call("/repos/%s/actions/runs/%s/rerun-failed-jobs" % (REPO, run), "POST", {})
        print("rerun %s -> %s %s" % (run, st, (res.get("message") or "")[:160] if isinstance(res, dict) else ""))
        return 0 if st in (200, 201, 202) else 1
    st, data = call("/repos/%s/actions/runs/%s/jobs" % (REPO, run))
    if st != 200:
        print("cannot read run %s: %s %s" % (run, st, data.get("message")), file=sys.stderr)
        return 1
    for job in data.get("jobs", []):
        print("%-9s %-9s %s" % (job["status"], job.get("conclusion"), job["name"]))
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                print("     FAILED STEP: %s" % step["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
