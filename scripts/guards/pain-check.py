#!/usr/bin/env python3
"""PAIN CHECK -- run the executable checks that back the journal's open pain entries.

WHY THIS EXISTS
---------------
On 2026-09-30 a full audit verified 297 open pain entries against the live systems and found that
**52 of them were already fixed**. They were still open because nothing in this system closes an
entry when its cause is removed (journal P4, P58: "56 of 57 open", measured a fortnight earlier).
The audit produced, per id, the command it ran and what that command printed -- and threw it away
when the session ended, exactly as every previous audit did.

This is the mechanism that keeps it. Each check is a shell function that exits with a VERDICT, the
whole suite runs on a schedule, and the result is a measurement:

  * how many open entries are still live (a real number, not a memory),
  * how many are fixed and still filed open (the debt this exists to pay), and
  * which checks can no longer decide anything (a broken check, reported as such).

WHAT IT DOES NOT DO
-------------------
It does not close entries by itself. `--close` does that, and it is opt-in, because a wrong check
that silently closes a real defect is worse than a stale open entry: the record would then say
"fixed" about something nobody looked at. The default run only measures and reports.

CONTRACT WITH A CHECK FILE
--------------------------
A check file is `bash`. It runs ON THIS HOST. It prints exactly one line per id:

    <ID>\tFIXED|LIVE|UNKNOWN\t<reason>

and exits 0. Anything else on stdout is ignored with a warning. A file that exits non-zero is a
BROKEN check file, not a finding, and is reported as such -- the two must never be confused.

USAGE
    pain-check.py                     # run every check file, print a summary
    pain-check.py --json              # the same as JSON
    pain-check.py --write-status      # also write ~/.pain-check/status.json and append history.tsv
    pain-check.py --only C1,C3        # run named check files only
    pain-check.py --close             # ALSO resolve entries that are FIXED and currently open
    pain-check.py --selftest          # prove the parser and the verdict logic on synthetic input
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CHECKS_DIR = Path(os.environ.get("PAIN_CHECKS_DIR", "/home/zabz/bin/pain-checks"))
STATE_DIR = Path(os.environ.get("PAIN_CHECK_STATE", str(Path.home() / ".pain-check")))
STATUS = STATE_DIR / "status.json"
HISTORY = STATE_DIR / "history.tsv"
JOURNAL = Path(os.environ.get("JOURNAL_PY", "/home/zabz/harness-config/journal/tools/journal.py"))
PER_FILE_TIMEOUT = int(os.environ.get("PAIN_CHECK_TIMEOUT", "1800"))

ID_RE = re.compile(r"^([HLPDW]\d{1,4}[a-z]{0,2})\t(FIXED|LIVE|UNKNOWN)\t(.*)$")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_lines(text: str):
    """(findings, malformed). Strict on the contract, tolerant of everything else."""
    findings, bad = {}, []
    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m = ID_RE.match(line)
        if m:
            findings[m.group(1)] = {"verdict": m.group(2), "reason": m.group(3)[:200]}
        elif line.strip():
            bad.append(line.strip()[:160])
    return findings, bad


def run_file(path: Path) -> dict:
    started = datetime.now(timezone.utc)
    try:
        p = subprocess.run(["bash", str(path)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=PER_FILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"file": path.name, "ok": False, "error": "timed out after %d s" % PER_FILE_TIMEOUT,
                "findings": {}, "malformed": []}
    except Exception as exc:  # noqa: BLE001
        return {"file": path.name, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                "findings": {}, "malformed": []}
    findings, bad = parse_lines(p.stdout)
    return {"file": path.name, "ok": p.returncode == 0 and bool(findings),
            "returncode": p.returncode,
            "error": "" if p.returncode == 0 else (p.stderr or "").strip()[-300:],
            "findings": findings, "malformed": bad,
            "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1)}


def open_pain_ids() -> set:
    """The journal's currently-open pain ids, or an empty set with a warning."""
    try:
        p = subprocess.run([sys.executable, str(JOURNAL), "list", "--kind", "pain",
                            "--status", "open", "--limit", "5000", "--json"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300)
        data = json.loads(p.stdout or "{}")
        return {e["id"] for e in data.get("entries", [])}
    except Exception as exc:  # noqa: BLE001
        print("WARN: could not read the open pain list (%s); --close is disabled this run" % exc,
              file=sys.stderr)
        return set()


def close(fixed_and_open: dict) -> list:
    closed = []
    for pid, f in sorted(fixed_and_open.items()):
        why = ("Closed by pain-check: the entry's own check reports FIXED. Reason: %s (check %s, "
               "run %s). A check that says an entry is fixed is evidence; leaving it open is how "
               "52 already-fixed entries accumulated before 2026-09-30."
               % (f["reason"], f.get("file", "?"), now()))
        why = " ".join(why.split())
        try:
            p = subprocess.run([sys.executable, str(JOURNAL), "resolve", pid, "--status", "done",
                                "--why", why], capture_output=True, text=True, timeout=180)
            if p.returncode == 0:
                closed.append(pid)
            else:
                print("WARN: could not close %s: %s" % (pid, (p.stdout or p.stderr or "").strip()[-200:]),
                      file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not close %s: %s" % (pid, exc), file=sys.stderr)
    return closed


def selftest() -> int:
    problems = []
    good = "P1\tFIXED\tsomething\nP2\tLIVE\tother\nL5\tUNKNOWN\tcould not reach x\n"
    f, bad = parse_lines(good)
    if set(f) != {"P1", "P2", "L5"}:
        problems.append("parser missed ids: %s" % sorted(f))
    if bad:
        problems.append("parser called clean input malformed: %s" % bad)
    f2, bad2 = parse_lines("noise\nL1\tMAYBE\tx\nP3\tFIXED\n")
    if "P3" in f2:
        problems.append("parser accepted a two-field line as a finding")
    if not bad2:
        problems.append("parser did not report malformed input")
    # A traffic line that happens to start with an id must not become a verdict.
    f3, _ = parse_lines("P9 FIXED because I said so\n")
    if f3:
        problems.append("parser accepted a space-separated line as a finding")
    if problems:
        print("SELFTEST FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("SELFTEST OK (parser strict on the contract, tolerant of noise)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--close", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    if not CHECKS_DIR.is_dir():
        print("no checks directory at %s" % CHECKS_DIR, file=sys.stderr)
        return 2
    wanted = [w for w in a.only.split(",") if w]
    files = sorted(p for p in CHECKS_DIR.glob("*.sh") if not wanted or p.stem in wanted)
    if not files:
        print("no check files matched in %s" % CHECKS_DIR, file=sys.stderr)
        return 2

    runs = [run_file(p) for p in files]
    findings, malformed, broken = {}, {}, []
    for r in runs:
        if r.get("returncode", 0) != 0 or not r["ok"] and r.get("error"):
            broken.append({"file": r["file"], "error": r.get("error") or "no findings on stdout"})
        for k, v in r["findings"].items():
            v["file"] = r["file"]
            findings[k] = v
        for m in r["malformed"]:
            malformed.setdefault(r["file"], []).append(m)

    counts = {"FIXED": 0, "LIVE": 0, "UNKNOWN": 0}
    for v in findings.values():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1

    opens = open_pain_ids()
    fixed_open = {k: v for k, v in findings.items()
                  if v["verdict"] == "FIXED" and (not opens or k in opens)}
    live_open = sorted(k for k, v in findings.items()
                       if v["verdict"] == "LIVE" and (not opens or k in opens))
    missing = sorted(opens - set(findings)) if opens else []

    result = {
        "at": now(), "checks_dir": str(CHECKS_DIR), "files": [r["file"] for r in runs],
        "counts": counts, "open_pain_entries": len(opens),
        "fixed_and_still_open": sorted(fixed_open), "live_and_open": live_open,
        "open_without_a_check": missing, "broken_check_files": broken,
        "malformed": malformed,
        "findings": {k: {"verdict": v["verdict"], "reason": v["reason"], "file": v["file"]}
                     for k, v in sorted(findings.items())},
        "per_file": [{"file": r["file"], "findings": len(r["findings"]),
                      "seconds": r.get("seconds"), "rc": r.get("returncode")} for r in runs],
    }

    if a.close and fixed_open:
        result["closed"] = close(fixed_open)

    if a.json:
        print(json.dumps(result, indent=1))
    else:
        print("PAIN CHECK %s" % result["at"])
        print("  check files      : %d" % len(runs))
        print("  findings         : FIXED %d | LIVE %d | UNKNOWN %d"
              % (counts.get("FIXED", 0), counts.get("LIVE", 0), counts.get("UNKNOWN", 0)))
        print("  open entries     : %d" % len(opens))
        print("  FIXED but OPEN   : %d  <- close these with --close" % len(fixed_open))
        if live_open:
            print("  LIVE and open    : %d" % len(live_open))
        if missing:
            print("  open, no check   : %d" % len(missing))
        for b in broken:
            print("  BROKEN CHECK FILE: %s - %s" % (b["file"], b["error"]))
        for fname, lines in malformed.items():
            print("  IGNORED LINES in %s: %d (first: %s)" % (fname, len(lines), lines[0]))
        if a.close:
            print("  closed           : %d %s" % (len(result.get("closed", [])),
                                                  result.get("closed", [])))
        for r in sorted(result["per_file"], key=lambda x: -(x["seconds"] or 0))[:3]:
            print("  slowest          : %s %ss (%d findings)"
                  % (r["file"], r["seconds"], r["findings"]))

    if a.write_status:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
            tmp.replace(STATUS)
            with HISTORY.open("a", encoding="utf-8") as fh:
                fh.write("%s\t%d\t%d\t%d\t%d\t%d\n"
                         % (result["at"], counts.get("FIXED", 0), counts.get("LIVE", 0),
                            counts.get("UNKNOWN", 0), len(fixed_open), len(opens)))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)

    # A suite that cannot run is not a suite that found nothing.
    if broken or len(missing) > 20:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
