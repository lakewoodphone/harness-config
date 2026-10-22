#!/usr/bin/env python3
"""Regression check for work-integrator.py's ledger cross-check (ledger item 1134).

Run: python3 /root/bin/work-integrator-ledger-dedupe-check.py
Exit 0 only when the level-wire episode yields NO integrate item and the control still files.

The fixture is a throwaway git repository whose main already carries a commit naming ledger
1096 and whose origin/integrate/level-wire branch names ledger 1096 in its subject - the
measured shape of the episode that produced ledger item 1120. A stub work.py answers the
ledger reads, so no live ledger row is created or changed.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

INTEGRATOR = "/root/bin/work-integrator.py"

STUB = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
ledger = json.loads(os.environ.get("STUB_LEDGER") or "{}")
if args and args[0] == "show" and len(args) > 1:
    state = ledger.get(args[1])
    if state:
        print(json.dumps({"id": int(args[1]), "state": state, "title": "stub item %s" % args[1]}))
        sys.exit(0)
    sys.exit(1)
if args and args[0] == "list":
    print(os.environ.get("STUB_TITLES") or "[]")
    sys.exit(0)
sys.exit(1)
'''


def run(cwd, *args, check=True):
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise SystemExit("FAILED %s: %s\n%s" % (" ".join(args), p.stdout, p.stderr))
    return p


def commit(repo, subject, filename, text):
    (Path(repo) / filename).write_text(text, encoding="utf-8")
    run(repo, "git", "add", filename)
    run(repo, "git", "commit", "-m", subject)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="wi1134-"))
    origin = tmp / "origin.git"
    work = tmp / "work"
    run(tmp, "git", "init", "--bare", "-q", str(origin))
    run(tmp, "git", "clone", "-q", str(origin), str(work))
    run(work, "git", "config", "user.email", "check@example.invalid")
    run(work, "git", "config", "user.name", "check")
    run(work, "git", "checkout", "-q", "-b", "main")
    commit(work, "base", "base.txt", "base\n")
    run(work, "git", "push", "-q", "origin", "main")
    run(work, "git", "branch", "-q", "--set-upstream-to=origin/main", "main")

    # THE LEVEL-WIRE SHAPE: the branch claims ledger 1096; main has already landed 1096.
    run(work, "git", "checkout", "-q", "-b", "integrate/level-wire")
    commit(work, "feat(level): carry the household level (ledger 1096)", "wire.txt", "level\n")
    run(work, "git", "push", "-q", "origin", "integrate/level-wire")

    run(work, "git", "checkout", "-q", "-b", "integrate/running-work", "main")
    commit(work, "feat: work another shift owns (ledger 8888)", "running.txt", "x\n")
    run(work, "git", "push", "-q", "origin", "integrate/running-work")

    run(work, "git", "checkout", "-q", "-b", "integrate/new-work", "main")
    commit(work, "feat: untracked ledger work (ledger 7777)", "new.txt", "y\n")
    run(work, "git", "push", "-q", "origin", "integrate/new-work")

    # A DROPPED ROW IS A DECISION: the same title must not be re-filed (item 1120 -> 1146).
    run(work, "git", "checkout", "-q", "-b", "integrate/dropped-work", "main")
    commit(work, "feat: a merge a shift already judged and dropped", "dropped.txt", "z\n")
    run(work, "git", "push", "-q", "origin", "integrate/dropped-work")

    run(work, "git", "checkout", "-q", "main")
    commit(work, "feat: the server half (ledger 1096)", "server.txt", "done\n")
    run(work, "git", "push", "-q", "origin", "main")

    registry = tmp / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "id": "kosher-ai-filter", "enabled": True, "repo": str(work),
        "integration_branch": "origin/main"}]}), encoding="utf-8")
    stub = tmp / "work_stub.py"
    stub.write_text(STUB, encoding="utf-8")

    env = dict(os.environ)
    env["WORK_REGISTRY"] = str(registry)
    env["WORK_CLI"] = str(stub)
    env["STUB_LEDGER"] = json.dumps({"1096": "done", "8888": "running", "7777": "todo"})
    env["STUB_TITLES"] = json.dumps([{
        "title": "Integrate origin/integrate/dropped-work into origin/main", "state": "dropped"}])
    p = subprocess.run([sys.executable, INTEGRATOR, "--dry-run", "--project", "kosher-ai-filter",
                        "--days", "30", "--limit", "10", "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        print("integrator rc=%d\nstdout:\n%s\nstderr:\n%s" % (p.returncode, p.stdout, p.stderr))
        return 1
    report = json.loads(p.stdout)
    filed = {f["branch"]: f["item"] for f in report[0]["filed"]}

    cases = [
        ("origin/integrate/level-wire", "duplicate: ledger 1096", "level-wire episode files NO item"),
        ("origin/integrate/running-work", "in-flight: ledger 8888", "claimed item is not rebuilt"),
        ("origin/integrate/new-work", "would-file", "control still files real debt"),
        ("origin/integrate/dropped-work", "already tracked", "a dropped row is not re-filed"),
    ]
    failed = 0
    for branch, expected, label in cases:
        got = str(filed.get(branch, "MISSING"))
        ok = got.startswith(expected)
        failed += 0 if ok else 1
        print("%-5s %-34s got=%-70s %s" % (
            "OK" if ok else "FAIL", branch, got[:70], label))
    print("level_wire_item=%s" % filed.get("origin/integrate/level-wire"))
    print("regression_failures=%d" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
