#!/usr/bin/env python3
"""DEPLOYMENT DRIFT CHECK — is the code actually running the code we think it is?

WHY THIS EXISTS
On 2026-10-07 the checkout on this host was 199 commits behind origin/master and 89 ahead of
it, on a feature branch. A one-line cursor bug had been fixed, tested and pushed two days
earlier, and the fix was NOT being run — so the bug kept losing customer messages while the
fix sat on a branch. Nobody noticed, because nothing compared the running tree against master.

That is the failure this closes: a fix that is written but not running looks exactly like a fix
that works. A green test suite on a branch proves nothing about the process serving traffic.

WHAT IT REPORTS
  * the commit the working tree is on, and whether the tree is dirty
  * how many origin/master commits the running tree does NOT contain, and their names
  * the same in reverse: local commits master does not have (work that could be lost)
  * when the long-running services last started, so a stale process is visible
  * a verdict: IN SYNC / BEHIND / DIVERGED

EXIT CODE (tri-state, this repo's contract):
    0                 IN SYNC, or AHEAD with unpushed work (nothing master has is missing from
                      the running tree);
    CONDITION_EXIT(3) BEHIND or DIVERGED: a real FINDING this read-only check cannot clear. The
                      running tree does not contain commits that are on origin/master, and the
                      remedy is a DEPLOY decision (`lpt-deploy.sh --check` / `--merge`), not a
                      repair of this code. `bin/sources/cron-failures.py` honours rc=3 for EVERY
                      job as "condition, not fault", so a streak is not filed as a broken job --
                      which is what rc=1 did: measured 2026-10-07, ten consecutive rc=1 runs were
                      filed as a failed job while the check was working perfectly;
    1 / 2             a FAULT in this check (no checkout, git unavailable, evidence that could not
                      be gathered). A fault always wins.
The cause is echoed to stderr, so a reader of the job's own log sees the condition named rather
than having to infer it from the exit code.

READ-ONLY. It never changes the checkout, never fetches destructively, never restarts anything.

PORTED TO THE CLOUD AUTHORITY, 2026-10-11 (workstream 135)
----------------------------------------------------------
WHAT THE OFFICE COPY GOT WRONG FOR THIS BOX, and why the DEAD verdict is not the whole story:
  * `REPO = ~/personal-secretary-mvp`. On the cloud box that directory does not exist; the app is
    at `/opt/company`. Unchanged, this check would exit 1 ("No git checkout") every hour.
  * `SERVICES = secretary-api.service, secretary-dashboard.service, dialpad-sms-ws.service`. The
    first two DO NOT EXIST on the cloud box (the API is `company-api.service`) and the third does
    not exist anywhere any more. Unchanged, every service row would read `unknown`, and the
    report's whole point -- "is the process older than the commit" -- would be unanswerable.
  * It wrote state to `~/.lpt-ops/...`, which does not exist here.
So the two literal lists are now environment-overridable with the OFFICE values as defaults, and
the cloud cron line names them explicitly. The QUESTION this job asks -- "is the code that is
running the code we think it is" -- is exactly as valuable on the new authority as it was on the
old one, and MORE so immediately after a cutover that moved the app between machines by hand.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.environ.get("LPT_REPO") or os.path.expanduser("~/personal-secretary-mvp")
_DEFAULT_SERVICES = "secretary-api.service,secretary-dashboard.service,dialpad-sms-ws.service"
SERVICES = [s for s in os.environ.get("LPT_DEPLOY_SERVICES", _DEFAULT_SERVICES).split(",") if s]
STATE = os.environ.get("LPT_DEPLOY_STATE") or os.path.expanduser(
    "~/.lpt-ops/dialpad/deploy-state.json")

#: This repo's word for "condition, not fault" (ai-gateway-health.py, text-ledger-audit.py,
#: supplier-delivery-watch.py; `bin/sources/cron-failures.py` honours it for EVERY job). A drift
#: finding is an external state this READ-ONLY check cannot clear -- the running tree is on a
#: feature branch that does not contain origin/master -- and the remedy is a deploy, not a repair
#: of this code. Only a fault below still exits 1.
CONDITION_EXIT = 3


def sh(args: list[str], cwd: str = REPO) -> tuple[int, str]:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "").strip()


def main() -> int:
    if not os.path.isdir(os.path.join(REPO, ".git")):
        print(f"No git checkout at {REPO}")
        return 1

    out: dict = {"checked_at": datetime.now(timezone.utc).isoformat(), "repo": REPO}

    _, branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _, head = sh(["git", "rev-parse", "--short", "HEAD"])
    _, head_full = sh(["git", "rev-parse", "HEAD"])
    dirty = sh(["git", "status", "--porcelain"])[1]
    out.update(branch=branch, head=head, head_full=head_full,
               dirty_files=len([l for l in dirty.splitlines() if l.strip()]))

    # fetch is best-effort: a network failure must not make the check lie about what it knows
    fetched = sh(["git", "fetch", "-q", "origin"])[0] == 0
    out["fetched"] = fetched

    _, master = sh(["git", "rev-parse", "--short", "origin/master"])
    out["origin_master"] = master

    _, behind_raw = sh(["git", "rev-list", "--count", "HEAD..origin/master"])
    _, ahead_raw = sh(["git", "rev-list", "--count", "origin/master..HEAD"])
    try:
        behind = int(behind_raw)
    except ValueError:
        behind = -1
    try:
        ahead = int(ahead_raw)
    except ValueError:
        ahead = -1
    out.update(behind_master=behind, ahead_of_master=ahead)

    missing = sh(["git", "log", "--oneline", "HEAD..origin/master"])[1].splitlines()
    out["missing_master_commits"] = missing[:40]
    out["missing_master_commit_count"] = len(missing)

    local_only = sh(["git", "log", "--oneline", "origin/master..HEAD"])[1].splitlines()
    out["local_only_commits"] = local_only[:40]

    # when did the long-running processes actually start
    svc = {}
    for unit in SERVICES:
        rc, started = sh(["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit])
        svc[unit] = started if rc == 0 and started else "unknown"
    out["service_started"] = svc

    # verdict. BEHIND and DIVERGED are a CONDITION (rc=3), not a fault: the finding is real,
    # this code is working, and clearing it is a deploy decision a READ-ONLY check must not make.
    # A git that could not count (behind/ahead parsed as -1) is the opposite -- a FAULT in this
    # check -- and a fault always wins over a condition.
    if behind < 0 or ahead < 0:
        verdict = "UNKNOWN (git could not count commits behind/ahead)"
        code = 1
    elif behind == 0 and ahead == 0:
        verdict = "IN SYNC"
        code = 0
    elif behind > 0 and ahead == 0:
        verdict = "BEHIND"
        code = CONDITION_EXIT
    elif behind == 0 and ahead > 0:
        verdict = "AHEAD (running unpushed/unmerged work)"
        code = 0
    else:
        verdict = "DIVERGED"
        code = CONDITION_EXIT
    out["verdict"] = verdict
    if code == CONDITION_EXIT:
        # Name the condition on stderr. bin/cron-wrap.sh records the first 160 chars of stderr in
        # ~/.cron-status/runs.tsv when the cron payload does not swallow fd 2 itself.
        sys.stderr.write(
            "lpt-deploy-drift: rc=%d CONDITION, not fault -- %s: %s @ %s is %d commit(s) behind "
            "origin/master and %d commit(s) only here; remedy is a deploy decision, not a code "
            "repair\n" % (CONDITION_EXIT, verdict, branch, head, behind, ahead))
    elif code != 0:
        sys.stderr.write(
            "lpt-deploy-drift: rc=%d FAULT -- %s: %s @ %s; git could not count commits behind "
            "origin/master (behind=%d ahead=%d)\n" % (code, verdict, branch, head, behind, ahead))

    print("=" * 78)
    print("DEPLOYMENT DRIFT CHECK")
    print("=" * 78)
    print(f"  checkout        : {REPO}")
    print(f"  branch          : {branch}  @ {head}")
    print(f"  origin/master   : {master}")
    print(f"  dirty files     : {out['dirty_files']}"
          f"{'  <-- unpushed local edits' if out['dirty_files'] else ''}")
    print(f"  behind master   : {behind} commits")
    print(f"  ahead of master : {ahead} commits")
    print(f"  fetch succeeded : {fetched}")
    print()
    print(f"  VERDICT: {verdict}")
    if missing:
        print()
        print(f"  Running code does NOT contain {len(missing)} commit(s) that ARE on master.")
        print("  A fix that is merged but not deployed is not a fix. First 12:")
        for line in missing[:12]:
            print(f"     {line}")
    if local_only:
        print()
        print(f"  {len(local_only)} commit(s) exist ONLY here and not on master"
              f" - work at risk if this tree is replaced. First 5:")
        for line in local_only[:5]:
            print(f"     {line}")
    print()
    print("  long-running services (start time; older than the newest commit = not restarted):")
    for unit, started in svc.items():
        print(f"     {unit:30} {started}")
    print()

    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
    except OSError as exc:
        print(f"  (could not write state: {exc})")
    return code


if __name__ == "__main__":
    sys.exit(main())
