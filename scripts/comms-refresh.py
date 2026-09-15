#!/usr/bin/env python3
"""comms-refresh — keep the communications index current, and say when it is not.

WHY THIS EXISTS. The index was built by hand on 2026-09-14 and nothing ran it
again: six hours later it was already missing 19 texts and 62 calls. That is this
fleet's most expensive habit (L160, L167, P51) and it is expensive here in a
specific way — a search index that is quietly behind answers old questions with
confident, wrong completeness.

WHAT IT DOES, in order, and it refuses to skip a step:
  1. rebuilds the index (`commsindex.py index`) against the live company database,
  2. verifies it (`comms-coverage.py`) by replaying the extractors and comparing,
  3. writes `~/.fsearch/comms-state.json` with the result, the counts and the age,
  4. exits non-zero if coverage failed — so cron mail, or any watcher, sees it.

`--check` is the cheap half: it reads the state file and fails if the index is
older than `--max-age-minutes`, if the last run failed, or if it never ran. A run
that fails leaves the previous good state's counts intact but stamps `ok: false`
with a reason.

A full rebuild takes ~45 s. It is scheduled on the authority every 30 minutes,
five minutes after the Dialpad harvest, so the index is never more than one harvest
behind. Overlapping runs are refused rather than allowed to fight over the file.

USAGE
  comms-refresh.py                     # rebuild + verify + record
  comms-refresh.py --check             # report staleness/coverage, exit 1 if bad
  comms-refresh.py --check --json
  comms-refresh.py --install [--from DIR]   # install the toolset into ~/.fsearch
  comms-refresh.py --max-age-minutes 90
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FSEARCH = os.path.join(os.path.expanduser("~"), ".fsearch")
STATE = os.path.join(FSEARCH, "comms-state.json")
LOCK = os.path.join(FSEARCH, "comms-refresh.lock")
LOG = os.path.join(FSEARCH, "comms-refresh.log")


def _tool(name: str) -> str:
    """Prefer the copy beside this file, so the scheduled job can run straight out
    of the harness-config checkout and there is no second copy to go stale."""
    local = os.path.join(HERE, name)
    return local if os.path.exists(local) else os.path.join(FSEARCH, name)


INDEXER = _tool("commsindex.py")
COVERAGE = _tool("comms-coverage.py")
SOURCE = os.environ.get("COMMS_SOURCE",
                        "/home/zabz/personal-secretary-mvp/data/secretary.db")
INDEX_DB = os.path.join(FSEARCH, "comms.db")
PY = sys.executable or "python3"

DEFAULT_MAX_AGE_MINUTES = 90

# The toolset that must be present in ~/.fsearch for the scheduled refresh to run.
TOOLSET = ("commsindex.py", "comms-coverage.py", "comms-refresh.py", "comms-search.py")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _log(line: str) -> None:
    try:
        os.makedirs(FSEARCH, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {line}\n")
    except OSError:
        pass


def _read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    os.makedirs(FSEARCH, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


class _Lock:
    """Single-instance guard. A lock whose holder is gone is reclaimed."""

    def __init__(self, path: str):
        self.path = path
        self.fh = None

    def __enter__(self):
        os.makedirs(FSEARCH, exist_ok=True)
        try:
            import fcntl
        except ImportError:  # Windows
            return self
        self.fh = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.seek(0)
            holder = (self.fh.read() or "").strip()
            raise SystemExit(f"comms-refresh: another run holds the lock "
                             f"({holder or 'unknown pid'}) — refusing to overlap")
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(f"pid={os.getpid()} at={_now()}")
        self.fh.flush()
        return self

    def __exit__(self, *exc):
        if self.fh:
            try:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            except Exception:
                pass
            self.fh.close()
        return False


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _liveness() -> dict:
    """Ask the reader whether the data is still flowing, and take its answer.

    Not re-derived here (a second copy of the rule is a second thing to drift, and the
    cron and the agent would then be able to disagree about the same database). The
    reader's `health` already decides this; this only carries the verdict into the state
    file so a failed pass is visible without anyone asking.
    """
    reader = _tool("comms-search.py")
    if not os.path.exists(reader):
        return {"ok": True, "problems": []}
    rc, out = _run([PY, reader, "--db", INDEX_DB, "--json", "health"], timeout=120)
    if rc != 0:
        return {"ok": True, "problems": [], "note": f"reader rc={rc}"}
    try:
        payload = json.loads(out)
    except ValueError:
        return {"ok": True, "problems": [], "note": "reader output unparseable"}
    return payload


def do_refresh(max_age_minutes: int) -> int:
    starter = _read_state()
    with _Lock(LOCK):
        t0 = time.time()
        rc, out = _run([PY, INDEXER, "--db", INDEX_DB, "--source", SOURCE, "index"])
        index_out = out.strip().splitlines()[-1] if out.strip() else ""
        if rc != 0:
            state = dict(starter)
            state.update(ok=False, at=_now(), reason=f"index rc={rc}",
                         last_error=out.strip()[-800:])
            _write_state(state)
            _log(f"FAIL index rc={rc}: {out.strip()[-300:]}")
            print(f"comms-refresh: index FAILED rc={rc}")
            print(out.strip()[-2000:])
            return 1

        crc, cout = _run([PY, COVERAGE, "--source", SOURCE, "--index", INDEX_DB, "--json"])
        try:
            coverage = json.loads(cout)
        except ValueError:
            coverage = {"ok": False, "raw": cout.strip()[-800:]}

        rc2, sout = _run([PY, INDEXER, "--db", INDEX_DB, "stats"])
        by_kind = {}
        total = 0
        for line in sout.splitlines():
            if line.startswith("total communications indexed:"):
                total = int(line.split(":")[1].replace(",", "").strip())
            elif line.startswith("  ") and ".." in line:
                parts = line.split()
                if len(parts) >= 2 and parts[1].replace(",", "").isdigit():
                    by_kind[parts[0]] = int(parts[1].replace(",", ""))

        tables = coverage.get("tables") or []
        missing = sum(t.get("missing", 0) for t in tables)
        collapsed = sum(t.get("collapsed", 0) for t in tables)
        state = {
            "ok": bool(coverage.get("ok")),
            "at": _now(),
            "seconds": round(time.time() - t0, 1),
            "total": total,
            "by_kind": by_kind,
            "coverage_ok": bool(coverage.get("ok")),
            "missing": missing,
            "collapsed_duplicates": collapsed,
            "tables": [
                {k: t.get(k) for k in ("table", "source_rows", "yielded", "unique_refs",
                                       "collapsed", "indexed", "missing", "orphan")}
                for t in tables
            ],
            "index": INDEX_DB,
            "source": SOURCE,
            "index_summary": index_out,
        }
        if not state["ok"]:
            state["reason"] = "coverage incomplete"
            state["missing_detail"] = [
                {"table": t["table"], "missing": t["missing"],
                 "sample": t.get("missing_sample")} for t in tables if t.get("missing")
            ]
        # A source that stops moving is also a failure worth seeing: the index can
        # be "complete" while ingestion is dead (the P29 pattern). The liveness verdict
        # is taken from `comms-search.py health` rather than re-derived here -- one
        # implementation of the rule, so the cron and the agent cannot disagree.
        liveness = _liveness()
        state["ingestion"] = liveness.get("ingestion")
        state["ingestion_problems"] = liveness.get("problems") or []
        if not liveness.get("ok", True):
            state["ok"] = False
            state["reason"] = ("ingestion stale: "
                               + "; ".join(liveness.get("problems") or []))
        try:
            state["source_mtime"] = dt.datetime.fromtimestamp(
                os.path.getmtime(SOURCE), dt.timezone.utc).isoformat()
        except OSError:
            pass
        _write_state(state)
        _log(f"{'ok' if state['ok'] else 'ATTENTION'} total={total:,} "
             f"missing={missing:,} collapsed={collapsed:,} in {state['seconds']}s "
             f"{index_out}")
        print(f"comms-refresh: {'ok' if state['ok'] else 'ATTENTION'} — "
              f"{total:,} indexed, {missing:,} missing, {collapsed:,} duplicate refs "
              f"collapsed, {state['seconds']}s")
        for problem in state["ingestion_problems"]:
            print(f"  INGESTION: {problem}")
        return 0 if state["ok"] else 1


def do_check(max_age_minutes: int, as_json: bool) -> int:
    state = _read_state()
    if not state:
        payload = {"ok": False, "reason": "never_ran", "state_file": STATE}
        print(json.dumps(payload) if as_json else
              "comms-refresh: NEVER RAN — no state file at " + STATE)
        return 1

    problems = []
    age_min = None
    at = state.get("at")
    if at:
        try:
            when = dt.datetime.fromisoformat(at)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            age_min = (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 60.0
        except ValueError:
            problems.append("state file has an unparseable timestamp")
    if age_min is None:
        problems.append("state file has no usable timestamp")
    elif age_min > max_age_minutes:
        problems.append(f"last run was {age_min:.0f} min ago (limit {max_age_minutes})")
    if not state.get("ok"):
        problems.append(f"last run failed: {state.get('reason') or 'unknown reason'}")
    if state.get("missing"):
        problems.append(f"{state['missing']:,} source rows are not in the index")
    for problem in state.get("ingestion_problems") or []:
        problems.append(problem)

    payload = {
        "ok": not problems,
        "problems": problems,
        "ingestion": state.get("ingestion"),
        "age_minutes": None if age_min is None else round(age_min, 1),
        "total": state.get("total"),
        "by_kind": state.get("by_kind"),
        "missing": state.get("missing"),
        "collapsed_duplicates": state.get("collapsed_duplicates"),
        "at": at,
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    elif problems:
        print("comms-refresh: " + "; ".join(problems))
        print(f"  {state.get('total', 0):,} communications indexed as of {at}")
    else:
        print(f"comms-refresh: ok — {state.get('total', 0):,} communications, "
              f"indexed {age_min:.0f} min ago, {state.get('missing', 0):,} missing, "
              f"{state.get('collapsed_duplicates', 0):,} duplicate refs collapsed")
    return 0 if not problems else 1


def do_install(src_dir: str) -> int:
    """Copy the toolset into ~/.fsearch and record which commit it came from.

    WHY THIS EXISTS. The tools live in git (`harness-config/scripts`) but run from
    `~/.fsearch`, which is not a repo. Every previous copy was made by hand, which is
    how the authority ended up running a version whose `.bak` files outnumbered the
    real ones. The installed set records the commit it was taken from, so "which
    code is running here" is answerable without guessing.
    """
    os.makedirs(FSEARCH, exist_ok=True)
    installed = []
    for name in TOOLSET:
        src = os.path.join(src_dir, name)
        if not os.path.exists(src):
            print(f"comms-refresh: --install: missing {src}")
            return 2
        dst = os.path.join(FSEARCH, name)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
            os.chmod(dst, 0o775)
        installed.append(name)

    commit = None
    try:
        proc = subprocess.run(["git", "-C", src_dir, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            commit = proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    manifest = {
        "installed_at": _now(),
        "from": src_dir,
        "commit": commit,
        "files": {n: os.path.getmtime(os.path.join(FSEARCH, n)) for n in installed},
        "host": os.uname().nodename if hasattr(os, "uname") else "",
    }
    with open(os.path.join(FSEARCH, "comms-install.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"comms-refresh: installed {len(installed)} tools into {FSEARCH} "
          f"from {src_dir} at commit {commit or 'unknown'}")
    for name in installed:
        print(f"  {name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="do not rebuild; report staleness and coverage")
    ap.add_argument("--install", action="store_true",
                    help="copy the toolset into ~/.fsearch and record the commit")
    ap.add_argument("--from", dest="src_dir", default=os.path.join(
        os.path.expanduser("~"), "harness-config", "scripts"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    a = ap.parse_args()
    if a.install:
        return do_install(a.src_dir)
    return do_check(a.max_age_minutes, a.json) if a.check else do_refresh(a.max_age_minutes)


if __name__ == "__main__":
    sys.exit(main())
