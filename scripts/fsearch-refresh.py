#!/usr/bin/env python3
"""refresh — keep the search indexes current, and say so when they are not.

WHY THIS EXISTS. An index is only worth having if it is current, and the failure
mode here is the fleet's most expensive habit: something runs, fails silently, and
looks healthy (L160, L167, P51). The indexes are incremental, so a refresh is
seconds to minutes — but nothing was running them, and nothing checked that they
had run.

WHAT IT REFRESHES, all incremental
  fsearch     file name + content index over the host's code and document trees
  names.db    the small trigram path index that makes `find` instant
  chatindex   conversation history (VS Code Copilot sessions, agent sessions)
  commsindex  SMS, calls, transcripts and voicemails (on the authority)

It records `last_success` (or a readable failure reason) in a state file, retries
once on a transient `database is locked`, and exits non-zero on real failure so a
scheduler can see it.

USAGE
  refresh.py                 refresh everything, print a one-line summary
  refresh.py --check         do not refresh; report staleness, exit 1 if stale
  refresh.py --roots A B     override the file-index roots
  refresh.py --json          machine-readable
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
FSEARCH_DIR = os.path.join(HOME, ".fsearch")
STATE = os.path.join(FSEARCH_DIR, "refresh-state.json")

FSEARCH = os.path.join(FSEARCH_DIR, "fsearch.py")
CHATINDEX = os.path.join(FSEARCH_DIR, "chatindex.py")
COMMSINDEX = os.path.join(FSEARCH_DIR, "commsindex.py")
COMMS_DB = os.path.join(FSEARCH_DIR, "comms.db")
CHAT_DB = os.path.join(FSEARCH_DIR, "chats.db")
INDEX_DB = os.path.join(FSEARCH_DIR, "index.db")
NAMES_DB = os.path.join(FSEARCH_DIR, "names.db")

# A refresh older than this means the automation is not working: two missed hourly
# runs, the same "two missed windows" rule used for the archive alarm.
STALE_AFTER_MIN = 150

ROOTS_DEFAULT = [
    os.path.join(HOME, "Code"),
    os.path.join(HOME, "code"),
    os.path.join(HOME, "repos"),
    os.path.join(HOME, "personal-secretary-mvp"),
    os.path.join(HOME, "harness-config"),
    os.path.join(HOME, "ceo-kernel"),
]


def _python() -> str:
    return sys.executable or "python3"


def run(cmd, timeout: int = 3600):
    """Run a child and return (rc, tail). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "")[-800:] + (p.stderr or "")[-400:]).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


def rebuild_name_index(db_path: str, out_path: str):
    """Rebuild the trigram path index that makes filename search instant.

    Measured: without it `find` scanned 919,873 rows (2.795 s); with it, 0.000 s on
    the same query, and it also matches mid-path fragments.
    """
    import sqlite3
    if not os.path.exists(db_path):
        return 1, f"no file index at {db_path}"
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=300)
        dst = sqlite3.connect(out_path, timeout=300)
        dst.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE names (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL,
                name_rev TEXT NOT NULL, ext TEXT, size INTEGER, mtime REAL);
            CREATE INDEX idx_names_rev ON names(name_rev);
            CREATE VIRTUAL TABLE path_fts USING fts5(
                path, id UNINDEXED, tokenize='trigram');
        """)
        rows = src.execute(
            "SELECT id, path, name, ext, size, mtime FROM files").fetchall()
        dst.executemany(
            "INSERT INTO names(id, path, name, name_rev, ext, size, mtime) "
            "VALUES(?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], (r[2] or "")[::-1].lower(), r[3], r[4], r[5])
             for r in rows])
        dst.executemany("INSERT INTO path_fts(path, id) VALUES(?, ?)",
                        [(r[1], r[0]) for r in rows])
        dst.commit()
        dst.execute("INSERT INTO path_fts(path_fts) VALUES('optimize')")
        dst.commit()
        src.close()
        dst.close()
        return 0, f"names.db rebuilt: {len(rows):,} rows"
    except sqlite3.Error as exc:
        return 1, f"name index rebuild failed: {exc}"


def _last_line(text) -> str:
    """The last non-empty line of a subprocess tail, or '' if there is none.

    Never raises: this is used while REPORTING a failure, and a reporter that
    crashes replaces the real error with its own.
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:120] if lines else ""


def load_state() -> dict:
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(FSEARCH_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, STATE)


def staleness(state: dict, now: float):
    last = state.get("last_success")
    if not last:
        return None
    try:
        t = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.fromtimestamp(now, dt.timezone.utc) - t).total_seconds() / 60.0


def do_check(as_json: bool) -> int:
    now = time.time()
    age = staleness(load_state(), now)
    if age is None:
        msg = "SEARCH INDEX STALE: no successful refresh has ever been recorded"
        stale = True
    elif age > STALE_AFTER_MIN:
        msg = (f"SEARCH INDEX STALE: last successful refresh {age:.0f} min ago "
               f"(limit {STALE_AFTER_MIN})")
        stale = True
    else:
        msg = f"search index fresh: refreshed {age:.0f} min ago"
        stale = False
    if as_json:
        print(json.dumps({"ok": not stale, "age_min": age, "message": msg,
                          "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                         indent=2))
    else:
        print(msg)
        if stale:
            print("  -> run: python ~/.fsearch/refresh.py")
    return 1 if stale else 0


def _pid_looks_alive(pid_text: str) -> bool:
    """Best-effort liveness check for a pid string, with no optional dependency."""
    try:
        n = int(str(pid_text).strip())
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        import subprocess
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {n}", "/NH"],
                                 capture_output=True, text=True, timeout=15).stdout
            return str(n) in (out or "")
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(n, 0)
        return True
    except OSError:
        return False


def _acquire_lock() -> str | None:
    """Take the single-instance lock, or return a reason we refused.

    MEASURED: a full pass takes ~10 min and the schedule is hourly, so overlap is
    unlikely -- but a manual run beside a scheduled one produced
    `sqlite3.OperationalError: database is locked` and killed the whole refresh.
    One lock file is cheaper than making every write resilient to contention, and
    it turns a corrupted run into a clear refusal.
    """
    lock = os.path.join(FSEARCH_DIR, "refresh.lock")
    pid = str(os.getpid())
    try:
        if os.path.exists(lock):
            with open(lock, "r", encoding="utf-8") as fh:
                held = fh.read().strip()
            age_min = (time.time() - os.path.getmtime(lock)) / 60.0
            if _pid_looks_alive(held) and age_min < 45:
                return (f"another refresh is already running (pid {held}, started "
                        f"{age_min:.0f} min ago); refusing to overlap")
            os.remove(lock)                      # stale lock from a dead run
        os.makedirs(FSEARCH_DIR, exist_ok=True)
        with open(lock, "w", encoding="utf-8") as fh:
            fh.write(pid)
        return None
    except OSError as exc:
        print(f"  warning: could not manage the refresh lock ({exc})")
        return None


def _release_lock() -> None:
    lock = os.path.join(FSEARCH_DIR, "refresh.lock")
    try:
        if os.path.exists(lock):
            with open(lock, "r", encoding="utf-8") as fh:
                if fh.read().strip() == str(os.getpid()):
                    os.remove(lock)
    except OSError:
        pass


def do_refresh(roots, as_json: bool, verbose: bool) -> int:
    refusal = _acquire_lock()
    if refusal:
        if as_json:
            print(json.dumps({"ok": False, "skipped": True, "reason": refusal}))
        else:
            print("  " + refusal)
        return 0
    try:
        return _do_refresh_body(roots, as_json, verbose)
    finally:
        _release_lock()


def _do_refresh_body(roots, as_json: bool, verbose: bool) -> int:
    started = dt.datetime.now(dt.timezone.utc)
    state = load_state()
    results = {}
    real_roots = [r for r in roots if os.path.isdir(r)]
    skipped = [r for r in roots if not os.path.isdir(r)]

    fsearch_cmd = []
    if os.path.exists(FSEARCH) and real_roots:
        fsearch_cmd = [_python(), FSEARCH, "--db", INDEX_DB, "index"]
        for r in real_roots:
            fsearch_cmd += ["--root", r]
        if verbose:
            fsearch_cmd.append("--verbose")
        rc, out = run(fsearch_cmd)
        results["fsearch"] = {"rc": rc, "tail": out}
    else:
        results["fsearch"] = {
            "rc": 1, "tail": f"missing script or no roots (skipped {skipped})"}

    rc, out = rebuild_name_index(INDEX_DB, NAMES_DB)
    results["names"] = {"rc": rc, "tail": out}

    if os.path.exists(CHATINDEX):
        rc, out = run([_python(), CHATINDEX, "--db", CHAT_DB, "index"], timeout=5400)
        results["chatindex"] = {"rc": rc, "tail": out}
    else:
        results["chatindex"] = {"rc": 1, "tail": "missing chatindex.py"}

    if os.path.exists(COMMSINDEX):
        rc, out = run([_python(), COMMSINDEX, "--db", COMMS_DB, "index"], timeout=1800)
        keep = [ln for ln in (out or "").splitlines() if "TOTAL" in ln]
        results["comms"] = {"rc": rc, "tail": (keep[0] if keep else (out or "")[-200:])}
    else:
        results["comms"] = {"rc": 0, "tail": "commsindex.py absent (not this host)"}

    # One retry for a TRANSIENT lock. A moment of contention is not a broken
    # index, and the state file cannot tell the difference afterwards.
    def retry(name: str, cmd: list) -> None:
        tail = (results.get(name, {}).get("tail") or "").lower()
        if "locked" not in tail:
            return
        time.sleep(20)
        rc, out = run(cmd, timeout=5400)
        results[name] = {"rc": rc, "tail": out[-800:], "retried": True}

    if fsearch_cmd:
        retry("fsearch", fsearch_cmd)
    if os.path.exists(COMMSINDEX):
        retry("comms", [_python(), COMMSINDEX, "--db", COMMS_DB, "index"])

    ok = all(v["rc"] == 0 for v in results.values())
    finished = dt.datetime.now(dt.timezone.utc)
    state.update({
        "last_run": finished.isoformat(),
        "last_seconds": round((finished - started).total_seconds(), 1),
        "roots": real_roots,
        "skipped_roots": skipped,
        "results": results,
    })
    if ok:
        state["last_success"] = finished.isoformat()
        state.pop("last_failure_reason", None)
    else:
        state["last_failure"] = finished.isoformat()
        # A step that produced no output must not break the error report. The
        # previous version did `splitlines()[-1]` unguarded here, so an empty tail
        # raised IndexError and the ORIGINAL failure was replaced by a crash while
        # describing it -- the failure was hidden by the code meant to explain it.
        state["last_failure_reason"] = "; ".join(
            f"{k}: rc={v['rc']} {_last_line(v.get('tail'))}"
            for k, v in results.items() if v["rc"] != 0) or "a step failed with no output"
    save_state(state)

    if as_json:
        print(json.dumps({"ok": ok, "seconds": state["last_seconds"],
                          "results": results}, indent=2))
    else:
        for name, v in results.items():
            mark = "ok  " if v["rc"] == 0 else "FAIL"
            print(f"  {mark} {name}: {_last_line(v.get('tail'))}")
        print(f"  {'refreshed' if ok else 'FAILED'} in {state['last_seconds']}s"
              + (f"; skipped missing roots {skipped}" if skipped else ""))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--roots", nargs="*", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.check:
        return do_check(a.json)
    return do_refresh(a.roots if a.roots else ROOTS_DEFAULT, a.json, a.verbose)


if __name__ == "__main__":
    sys.exit(main())
