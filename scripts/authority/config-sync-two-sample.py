#!/usr/bin/env python3
"""config-sync-two-sample.py -- require a config_sync disagreement to persist across TWO
consecutive samples before escalating HIGH.

WHY (docs/mesh/170, the `config_sync` false-HIGH)
    `ck/sentinel.py`'s `check_config_sync()` escalates any `result != "clean"` to HIGH on a
    single sample. `autosync` is a 15-minute cache and the sentinel samples it whenever it
    runs, so a healthy repo whose pull is in flight -- or which just failed one pull -- is
    reported as a company-affecting HIGH that clears by the next sample. The check measures
    a transient, not a divergence.

THE FIX
    Persist the last sample's `result`/`commit` in a small state file. Escalate HIGH only when
    the CURRENT sample is non-clean AND the PREVIOUS sample was non-clean with the same
    `result`. A first non-clean sample is MEDIUM "awaiting second sample" -- visible, not an
    owner-facing alarm.

INSTALL (do NOT auto-install; read the diff first)
    The function below is a drop-in replacement for `check_config_sync` in
    `secratary-cloud:/root/ceo-kernel/ck/sentinel.py`. To see the diff, run:
        config-sync-two-sample.py --diff /path/to/sentinel.py
    It is delivered as a PATCH, not installed.

USAGE
    config-sync-two-sample.py --status <autosync.json> [--state <state.json>]
    config-sync-two-sample.py --diff <sentinel.py>
    config-sync-two-sample.py --help

EXIT
    0  sampled (a non-clean first sample exits 0 -- it is MEDIUM, not a crash)
    1  could not sample (unreadable status, bad timestamp)
    2  bad usage
"""
import argparse
import json
import os
import sys
import time

#: MEDIUM means "seen once, not yet a divergence"; HIGH means "two consecutive samples agree".
MEDIUM = "MEDIUM"
HIGH = "HIGH"
INFO = "INFO"
UNKNOWN = "UNKNOWN"


def age_seconds(value):
    """Parse an ISO-8601 timestamp to an age in seconds, or None (never guesses)."""
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        import datetime
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def check_config_sync(autosync_status, state_path, max_age_seconds=2700):
    """Two-sample config_sync verdict. Returns a dict (check, severity, ok, summary)."""
    if not os.path.exists(autosync_status):
        return _f(UNKNOWN, False, "no autosync record -- cannot tell whether config converges")
    try:
        doc = json.loads(open(autosync_status, encoding="utf-8").read())
    except (OSError, ValueError) as exc:
        return _f(UNKNOWN, False, "autosync record unreadable: %s" % exc)

    age = age_seconds(doc.get("at"))
    result = str(doc.get("result") or "unknown")
    if age is None:
        return _f(UNKNOWN, False, "autosync record carries no readable timestamp")
    if age > max_age_seconds:
        return _f(HIGH, False, "config sync has not run in %.0fs (expected every 15m)" % age)
    if result == "clean":
        _save(state_path, {"result": result, "at": doc.get("at")})
        return _f(INFO, True, "config converged %.0fs ago at %s" % (age, doc.get("commit")))

    # Non-clean. Was the PREVIOUS sample also non-clean with the same result?
    prev = _load(state_path)
    _save(state_path, {"result": result, "at": doc.get("at")})
    if prev and str(prev.get("result")) == result:
        return _f(HIGH, False,
                  "config sync was '%s' on two consecutive samples: %s" % (result, doc.get("detail")))
    return _f(MEDIUM, False,
              "first non-clean config sync ('%s'); awaiting a second sample before escalating: %s"
              % (result, doc.get("detail")))


def _f(sev, ok, summary):
    return {"check": "config_sync", "severity": sev, "ok": ok, "summary": summary}


def _load(p):
    try:
        return json.loads(open(p, encoding="utf-8").read())
    except Exception:
        return None


def _save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    os.replace(tmp, p)


def _diff(sentinel_path):
    """Print the region of sentinel.py to replace, so a human can build the patch."""
    src = open(sentinel_path, encoding="utf-8").read()
    start = src.index("def check_config_sync(")
    end = src.index("\ndef ", start + 1)
    print("# --- current check_config_sync in %s (lines %d-%d) ---"
          % (sentinel_path, src[:start].count("\n") + 1, src[:end].count("\n") + 1))
    print(src[start:end])
    print("# --- replace with the two-sample check in this file (config-sync-two-sample.py) ---")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="config-sync-two-sample.py", add_help=False)
    ap.add_argument("--help", "-h", action="store_true")
    ap.add_argument("--status")
    ap.add_argument("--state", default="/var/lib/ceo-kernel/config-sync-state.json")
    ap.add_argument("--diff")
    args, extra = ap.parse_known_args(argv)
    if args.help:
        print(__doc__)
        return 0
    if extra:
        print("config-sync-two-sample.py: unknown argument: %s" % " ".join(extra), file=sys.stderr)
        return 2
    if args.diff:
        _diff(args.diff)
        return 0
    if not args.status:
        print("config-sync-two-sample.py: need --status <autosync.json> (or --diff/--help)",
              file=sys.stderr)
        return 2
    out = check_config_sync(args.status, args.state)
    print(json.dumps(out))
    return 0 if out["severity"] != UNKNOWN else 1


if __name__ == "__main__":
    sys.exit(main())
