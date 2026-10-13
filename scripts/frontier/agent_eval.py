#!/usr/bin/env python3
"""agent_eval.py - an evaluation harness that measures whether this estate's agents are
actually getting better, and FAILS LOUDLY when they get worse.

WHY THIS FILE EXISTS
--------------------
The owner's charge (2026-10-13) is that the estate is "lagging 2025" and late in 2026.
The only way to answer that with evidence rather than enthusiasm is to *measure* agent
output over time and gate on regression. This estate had no harness that could answer
"is this week's agent work better than last week's" with a number.

Two things are measured here:

  A. A verifiable task suite (JSONL). Each task names a verifying command; a task PASSES
     only if that command exits with the expected status AFTER the agent command ran.
     Scorecard: pass rate, per-task deltas, wall time, and an explicit REGRESSION list.
     `--fail-on-regression` makes the harness exit 5 when a previously-passing task fails.

  B. The estate's own autonomous output, from git history (`--from-git`): commits per ISO
     week, how many name a work id (brief/journal id), files touched, and the week-over-week
     direction. This is the number that answers "how much real work happens while the owner
     is not talking".

Exit contract:
  0  measured, no regression
  2  usage / environment error
  3  NOTHING measured (never a silent pass)
  5  REGRESSION detected (a previously-passing task now fails)

Usage:
  python3 scripts/frontier/agent_eval.py --self-test
  python3 scripts/frontier/agent_eval.py --from-git --repo . --weeks 8
  python3 scripts/frontier/agent_eval.py --suite tasks.jsonl --agent-cmd ./myagent.sh \
      --history .eval-history --run-id 2026-10-13 --fail-on-regression
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOTHING_MEASURED = 3
EXIT_REGRESSION = 5

WORK_ID_RE = re.compile(r"\b(?:W\d+-[A-Z0-9-]+|[A-Z]\d{3,4}[a-z]?)\b")


# ------------------------------------------------------------------- task suite / runner


def load_suite(path: Path):
    tasks = []
    for lineno, line in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rec = json.loads(line)
        except ValueError as e:
            raise SystemExit("agent_eval: %s:%d is not JSON: %s" % (path, lineno, e))
        if not rec.get("id") or "verify" not in rec:
            raise SystemExit("agent_eval: %s:%d needs 'id' and 'verify'" % (path, lineno))
        rec.setdefault("prompt", "")
        rec.setdefault("expect_exit", 0)
        rec.setdefault("timeout_s", 120)
        tasks.append(rec)
    return tasks


def run_one(task, agent_cmd: str, workdir: Path):
    """Run the agent command, then the verifier. PASS is decided by the verifier only."""
    started = time.time()
    env = dict(os.environ)
    env["AGENT_EVAL_TASK_ID"] = str(task["id"])
    env["AGENT_EVAL_PROMPT"] = str(task.get("prompt", ""))
    agent_out, agent_rc = "", None
    if agent_cmd:
        cmd = agent_cmd
        if "{prompt}" in cmd:
            cmd = cmd.replace("{prompt}", shlex.quote(str(task.get("prompt", ""))))
        try:
            p = subprocess.run(cmd, shell=True, cwd=str(workdir), env=env,
                               capture_output=True, text=True, timeout=task["timeout_s"])
            agent_out, agent_rc = (p.stdout + p.stderr)[-2000:], p.returncode
        except subprocess.TimeoutExpired:
            return {"id": task["id"], "pass": False, "reason": "agent timeout",
                    "agent_rc": None, "verify_rc": None,
                    "seconds": round(time.time() - started, 2)}
    try:
        v = subprocess.run(str(task["verify"]), shell=True, cwd=str(workdir), env=env,
                           capture_output=True, text=True, timeout=task["timeout_s"])
        verify_rc = v.returncode
    except subprocess.TimeoutExpired:
        verify_rc = None
    expected = int(task.get("expect_exit", 0))
    passed = verify_rc == expected
    return {"id": task["id"], "pass": passed,
            "reason": "ok" if passed else "verifier exit %s != %s" % (verify_rc, expected),
            "agent_rc": agent_rc, "verify_rc": verify_rc,
            "seconds": round(time.time() - started, 2)}


def scorecard(run_id: str, results, extra=None) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r["pass"])
    card = {
        "run_id": run_id,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tasks": n,
        "passed": passed,
        "failed": n - passed,
        "pass_rate": round(passed / n, 4) if n else None,
        "seconds": round(sum(r.get("seconds") or 0 for r in results), 2),
        "results": results,
    }
    if extra:
        card.update(extra)
    return card


def previous_card(history: Path):
    f = Path(history) / "scorecards.jsonl"
    if not f.exists():
        return None
    cards = [json.loads(l) for l in f.read_text("utf-8").splitlines() if l.strip()]
    return cards[-1] if cards else None


def compare(prev, cur):
    if not prev:
        return {"baseline": True, "regressions": [], "improvements": [], "pass_rate_delta": None}
    pm = {r["id"]: r["pass"] for r in prev.get("results", [])}
    cm = {r["id"]: r["pass"] for r in cur.get("results", [])}
    regressions = sorted(i for i in cm if i in pm and pm[i] and not cm[i])
    improvements = sorted(i for i in cm if i in pm and not pm[i] and cm[i])
    d = None
    if prev.get("pass_rate") is not None and cur.get("pass_rate") is not None:
        d = round(cur["pass_rate"] - prev["pass_rate"], 4)
    return {"baseline": False, "regressions": regressions, "improvements": improvements,
            "pass_rate_delta": d}


# ---------------------------------------------------------------- the estate's own output


def week_of(iso_date: str) -> str:
    y, m, d = (int(x) for x in iso_date.split("-"))
    iy, iw, _ = dt.date(y, m, d).isocalendar()
    return "%04d-W%02d" % (iy, iw)


def from_git(repo: Path, weeks: int):
    fmt = "%H\x1f%ad\x1f%s"
    try:
        raw = subprocess.run(
            ["git", "-C", str(repo), "log", "--no-merges", "--date=short",
             "--format=" + fmt],
            capture_output=True, text=True, timeout=120)
    except Exception as e:
        raise SystemExit("agent_eval: git log failed: %s" % e)
    if raw.returncode != 0:
        raise SystemExit("agent_eval: git log failed: %s" % (raw.stderr or "").strip())
    buckets = {}
    for line in raw.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, date, subj = parts
        w = week_of(date)
        b = buckets.setdefault(w, {"week": w, "commits": 0, "id_commits": 0, "samples": []})
        b["commits"] += 1
        if WORK_ID_RE.search(subj):
            b["id_commits"] += 1
            if len(b["samples"]) < 3:
                b["samples"].append(subj[:110])
    ordered = [buckets[w] for w in sorted(buckets)][-weeks:]
    for i, b in enumerate(ordered):
        b["commit_delta"] = None if i == 0 else b["commits"] - ordered[i - 1]["commits"]
        b["id_ratio"] = round(b["id_commits"] / b["commits"], 3) if b["commits"] else None
    return ordered


# ----------------------------------------------------------------------------- self-test

SELF_TEST_SUITE = [
    {"id": "T1-scaffold", "prompt": "create ok.txt",
     "verify": "test -f ok.txt"},
    {"id": "T2-math", "prompt": "create answer.txt holding 42",
     "verify": "grep -qx 42 answer.txt"},
    {"id": "T3-regress", "prompt": "create gone.txt", "verify": "test -f gone.txt"},
]

# A reference agent that passes T1 and T2 and fails T3 -- i.e. a real partial result.
REF_AGENT_OK = ("sh -c 'touch ok.txt; printf 42 > answer.txt'")
# The SAME agent after an injected regression: T2 now writes the wrong number.
REF_AGENT_REGRESSED = ("sh -c 'touch ok.txt; printf 41 > answer.txt'")


def self_test(history: Path):
    history = Path(history)
    history.mkdir(parents=True, exist_ok=True)
    hist_file = history / "scorecards.jsonl"
    if hist_file.exists():
        hist_file.unlink()
    suite_file = history / "selftest-suite.jsonl"
    suite_file.write_text("\n".join(json.dumps(t) for t in SELF_TEST_SUITE) + "\n", "utf-8")
    tasks = load_suite(suite_file)

    fails = []

    # Run 1: the baseline reference agent.
    with tempfile.TemporaryDirectory() as wd:
        r1 = [run_one(t, REF_AGENT_OK, Path(wd)) for t in tasks]
    c1 = scorecard("selftest-baseline", r1)
    hist_file.write_text(json.dumps(c1) + "\n", "utf-8")

    # Run 2: the same suite, agent regressed on T2.
    with tempfile.TemporaryDirectory() as wd:
        r2 = [run_one(t, REF_AGENT_REGRESSED, Path(wd)) for t in tasks]
    c2 = scorecard("selftest-regressed", r2)
    cmp2 = compare(c1, c2)
    c2["comparison"] = cmp2
    with hist_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(c2) + "\n")

    if c1["pass_rate"] != round(2 / 3, 4):
        fails.append("baseline pass_rate %s != 0.6667" % c1["pass_rate"])
    if cmp2["baseline"]:
        fails.append("second run was treated as a baseline (history not read)")
    if cmp2["regressions"] != ["T2-math"]:
        fails.append("expected regression ['T2-math'], got %s" % cmp2["regressions"])
    if cmp2["pass_rate_delta"] != round(c2["pass_rate"] - c1["pass_rate"], 4):
        fails.append("pass_rate_delta %s unexpected" % cmp2["pass_rate_delta"])
    # T3 must fail in BOTH runs and must NOT be reported as a regression.
    if "T3-regress" in cmp2["regressions"]:
        fails.append("a task that never passed was called a regression")
    prev = previous_card(history)
    if not prev or prev["run_id"] != "selftest-regressed":
        fails.append("scorecard history did not persist the last run")

    print("self-test: %s" % ("PASS" if not fails else "FAIL"))
    for f in fails:
        print("  FAIL %s" % f)
    print("  baseline pass_rate=%s (2/3), regressed pass_rate=%s, delta=%s"
          % (c1["pass_rate"], c2["pass_rate"], cmp2["pass_rate_delta"]))
    print("  regressions=%s improvements=%s" % (cmp2["regressions"], cmp2["improvements"]))
    return EXIT_OK if not fails else EXIT_REGRESSION


# ---------------------------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="agent evaluation harness")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--suite", help="JSONL task suite")
    ap.add_argument("--agent-cmd", default="", help="shell command under test; {prompt} is substituted")
    ap.add_argument("--history", default=".eval-history", help="directory holding scorecards.jsonl")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--fail-on-regression", action="store_true")
    ap.add_argument("--from-git", action="store_true", help="score the estate's own commit output")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test(Path(tempfile.mkdtemp(prefix="agent-eval-selftest-")))

    if args.from_git:
        weeks = from_git(Path(args.repo), args.weeks)
        if not weeks:
            print("agent_eval: NOTHING MEASURED - git history yielded no weeks", file=sys.stderr)
            return EXIT_NOTHING_MEASURED
        out = {"weeks": weeks,
               "trend": ("up" if len(weeks) > 1 and (weeks[-1]["commits"] or 0) > (weeks[-2]["commits"] or 0)
                         else "down" if len(weeks) > 1 else "single-week")}
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print("%-9s %8s %10s %8s  %s" % ("week", "commits", "id-commits", "id-ratio", "delta"))
            for w in weeks:
                print("%-9s %8d %10d %8s  %s" % (w["week"], w["commits"], w["id_commits"],
                                                 w["id_ratio"], w["commit_delta"]))
            print("trend: %s" % out["trend"])
        return EXIT_OK

    if not args.suite:
        ap.print_usage(sys.stderr)
        print("agent_eval: give --suite, --self-test or --from-git", file=sys.stderr)
        return EXIT_USAGE

    tasks = load_suite(Path(args.suite))
    if not tasks:
        print("agent_eval: NOTHING MEASURED - the suite has no tasks", file=sys.stderr)
        return EXIT_NOTHING_MEASURED

    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history = Path(args.history)
    prev = previous_card(history)
    with tempfile.TemporaryDirectory() as wd:
        results = [run_one(t, args.agent_cmd, Path(wd)) for t in tasks]
    card = scorecard(run_id, results)
    cmp_ = compare(prev, card)
    card["comparison"] = cmp_

    history.mkdir(parents=True, exist_ok=True)
    with (history / "scorecards.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(card) + "\n")

    if args.json:
        print(json.dumps(card, indent=2))
    else:
        for r in results:
            print("%-4s %-24s %6.1fs  %s" % ("PASS" if r["pass"] else "FAIL", r["id"],
                                             r.get("seconds") or 0, r["reason"]))
        print("pass_rate=%s (%d/%d)  run=%s" % (card["pass_rate"], card["passed"], card["tasks"], run_id))
        if cmp_["baseline"]:
            print("baseline recorded (no previous scorecard)")
        else:
            print("delta=%s regressions=%s improvements=%s"
                  % (cmp_["pass_rate_delta"], cmp_["regressions"], cmp_["improvements"]))

    if args.fail_on_regression and cmp_["regressions"]:
        print("REGRESSION: %s" % ", ".join(cmp_["regressions"]), file=sys.stderr)
        return EXIT_REGRESSION
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
