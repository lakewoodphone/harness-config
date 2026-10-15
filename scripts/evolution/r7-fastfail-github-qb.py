#!/usr/bin/env python3
"""r7-fastfail-github-qb.py — make the tools sessions die on fail fast, like the repo tools now do.

THE MEASUREMENT. 827 sessions, 7 days, on /root/authority.db, overall completion 34.8%. Completion
rate by the tool a session names in its [TOOL-SIGS]:

    update_task 100% · save_memory 77.9% · list_tasks 70.4% · repo_search 47.6%
    repo_read_file 40.4% · repo_list_dir 38.8% · qb_status 35.3% · qb_snapshot 31.2%
    github_read_file **12.5%** (2 completed of 16)

The bottom of that table is where the largest failure class lives: STEP_BUDGET_EXHAUSTED, 335
sessions in 7 days, of which 85% produce a sub-3 KB trace. The absent-repo half of this was fixed on
2026-10-15 (`_NON_FATAL_CB_FAILURE_PATTERNS` + the three resolver messages, commit `d43a75a37`) and
this is the same fix for the two families it did not reach.

WHAT IS ACTUALLY WRONG, measured from the logs:

* `qb_status`, `qb_snapshot`, `qb_query`, `qb_search`, `qb_accounts`, `qb_vendors`,
  `qb_reconciliation` — **have NO entry in `_NON_FATAL_CB_FAILURE_PATTERNS` at all.** Every failure
  counts toward the action's circuit breaker, so ten of them disable the action and the session then
  retries a disabled tool until its step budget is gone. Their emitted failures include the SAME
  resolver message the repo tools now treat as non-fatal:
      "Repo 'quickbooks-agent' has no local checkout on this host (tried /home/zabz/repos/...)"
      "QB agent not available (failed after 3 attempts)"
* `github_read_file` (and its three siblings) list only `Missing "repo"` / `Missing "path"` — nothing
  for the 404 the tool actually returns:
      'GitHub read failed: 404 {"message": "Not Found", "documentation_url": "..."}'

DELIBERATELY NARROW, because the controls matter: a 503, a rate limit or a transient network fault on
these same tools IS retryable, so nothing here matches those. Only a definite "this cannot succeed"
answer is added — a missing repo, a missing QB agent, and a GitHub 404.

USAGE
    python3 r7-fastfail-github-qb.py            # measure only
    python3 r7-fastfail-github-qb.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("/opt/company/app/chat_action_resilience.py")
BACKUP_DIR = Path("/root/work/r6")

QB_ACTIONS = ("qb_status", "qb_snapshot", "qb_reconciliation", "qb_query", "qb_search",
              "qb_accounts", "qb_vendors")

# the resolver's three messages (already used for repo_*) plus the QB agent's own
QB_PATTERNS = (
    '        "has no local checkout on this host",\n'
    '        "Path does not exist on this host",\n'
    '        "Repo not available locally",\n'
    '        "QB agent not available",\n'
)

# The literal the file needs, built as a STRING rather than hand-escaped. The first attempt wrote
# `'\\'"message": "Not Found"\\''` and py_compile refused it with "unterminated string literal" --
# a manual escape of a quote inside a quote inside a triple-quoted constant. Build the characters.
GH_LINE = "        '\"message\": \"Not Found\"',\n"


def add_before_close(block: str, line: str) -> str:
    """Insert `line` as the last tuple member of a dict-entry block."""
    idx = block.rfind("\n    ),")
    if idx < 0:
        raise SystemExit(f"! cannot find the closing of this block:\n{block[:120]}")
    return block[:idx + 1] + line + block[idx + 1:]


OLD_GITHUB = '''    "github_read_file": (
        'Missing "repo"',
        "Missing repo",
        'Missing "path"',
    ),'''
NEW_GITHUB = add_before_close(OLD_GITHUB, GH_LINE)

OLD_PR_LIST = '''    "github_list_prs": (
        'Missing "repo"',
        "Missing repo",
    ),'''
NEW_PR_LIST = add_before_close(OLD_PR_LIST, GH_LINE)

QB_BLOCK = "".join(
    f'    "{a}": (\n' + QB_PATTERNS + '    ),\n' for a in QB_ACTIONS
)

anchor = "_NON_FATAL_CB_FAILURE_PATTERNS: dict[str, tuple[str, ...]] = {\n"
QB_NOTE = ('    # qb_* had NO entry at all until 2026-10-15, so every failure counted toward the breaker\n'
           '    # and the session retried a disabled tool until its step budget ran out. Six of the\n'
           '    # seven are the "no local checkout on this host" condition the repo tools already treat\n'
           '    # as non-fatal. Measured: qb_status completes 35.3% of the time, qb_snapshot 31.2%,\n'
           '    # against 34.8% overall -- and 335 sessions in 7 days die at the step budget.\n')

PROBES = [
    ("qb_status", "Repo 'quickbooks-agent' has no local checkout on this host (tried /home/zabz/repos/quickbooks-agent)", False),
    ("qb_snapshot", "QB agent not available (failed after 3 attempts)", False),
    ("qb_query", "Repo not available locally for 'qb_query'", False),
    ("github_read_file", 'GitHub read failed: 404 {"message": "Not Found", "documentation_url": "https://x"}', False),
    ("qb_status", "rate limit exceeded, retry later", True),                 # control
    ("github_read_file", "GitHub read failed: 503 Service Unavailable", True),  # control
    ("github_read_file", "connection reset by peer", True),                 # control
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not TARGET.is_file():
        print(f"! {TARGET} not found", file=sys.stderr)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    print(f"target {TARGET}  sha256 {sha(TARGET)}")

    steps = [(OLD_GITHUB, NEW_GITHUB, "github_read_file 404"),
             (OLD_PR_LIST, NEW_PR_LIST, "github_list_prs 404")]
    new_text = text
    for old, new, label in steps:
        c = new_text.count(old)
        print(f"[1] {label}: anchor occurs {c} time(s)")
        if c != 1:
            print(f"! refusing: anchor for {label} is not unique", file=sys.stderr)
            return 1
        new_text = new_text.replace(old, new, 1)

    if new_text.count(anchor) != 1:
        print("! refusing: cannot locate the patterns-dict opening uniquely", file=sys.stderr)
        return 1
    new_text = new_text.replace(anchor, anchor + QB_NOTE + QB_BLOCK, 1)
    print(f"[2] added pattern lists for {len(QB_ACTIONS)} qb_* actions, at the head of the dict")

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    stage = BACKUP_DIR / "r7-files7" / "chat_action_resilience.py"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(new_text, encoding="utf-8")
    print(f"[3] staged -> {stage}  sha256 {sha(stage)}")
    print("    python syntax check:", end=" ")
    try:
        py_compile.compile(str(stage), doraise=True)
        print("OK")
    except py_compile.PyCompileError as exc:
        print(f"FAILED\n{exc}")
        return 1

    stamp = subprocess.run(["date", "-u", "+%Y%m%dT%H%M%SZ"], capture_output=True,
                           text=True).stdout.strip()
    backup = BACKUP_DIR / f"backups-fastfail-{stamp}" / "chat_action_resilience.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, backup)
    print(f"[4] backup -> {backup}  sha256 {sha(backup)}")

    shutil.copy2(stage, TARGET)
    print(f"[5] installed  sha256 {sha(TARGET)}")
    if sha(TARGET) != sha(stage):
        print("! did not land byte-for-byte -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    cmp: identical to the staged file")

    print("\n[6] PROOF -- the predicate itself, in the run-time interpreter:")
    probe_py = "/opt/company/.venv/bin/python3"
    if not Path(probe_py).is_file():
        probe_py = sys.executable
    code = (
        "import sys, json; sys.path.insert(0,'/opt/company');"
        "from app.chat_action_resilience import _should_retry_action_failure as f;"
        "cases = json.load(sys.stdin);"
        "print(json.dumps([[a, d, f(a, d), w] for a, d, w in cases]))"
    )
    # The data crosses as JSON on STDIN, not as Python source. The first version interpolated
    # json.dumps output INTO the -c program, so Python was asked to parse `false` and raised
    # NameError -- and the script, correctly, rolled the install back rather than leaving an
    # unproven change in place.
    pr = subprocess.run([probe_py, "-c", code],
                        input=json.dumps([[a, d, w] for a, d, w in PROBES]),
                        capture_output=True, text=True)
    if pr.returncode != 0:
        print(f"      probe FAILED rc={pr.returncode}: {(pr.stderr or '')[-300:]}")
        print("! restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    bad = 0
    for a, d, got, want in json.loads(pr.stdout):
        ok = got == want
        bad += 0 if ok else 1
        print(f"      retryable={str(got):5} want={str(want):5} {'ok ' if ok else 'FAIL'}  {a:17} {d[:56]}")
    if bad:
        print(f"! {bad} probe(s) failed -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    all probes hold")
    print(f"\n    rollback: cp -p {backup} {TARGET}")
    print("    NOT restarted. company-api.service must be restarted for this to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
