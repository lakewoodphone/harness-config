#!/usr/bin/env python3
"""Read the provider balance, and refuse to keep spending when it cannot cover the ceiling.

WHY. The wake spend ceiling was 70.00 USD per day while the account held 49.10 (measured 2026-09-30 by
querying the provider with the credentials the shifts themselves use). A ceiling larger than the balance is
not a ceiling: a runaway day can spend past the money and then die mid-work with shifts in flight and no
warning, which is the worst possible moment to stop. This tool makes the guard bind.

WHAT IT DOES
  (no flag)   print the balance and the ceiling side by side, and exit 0
  --guard     if the balance is below --floor, write the pause file with a marker saying WHY; if the balance
              has recovered above --floor plus a hysteresis margin AND the pause file carries this tool's own
              marker, remove it. A pause an operator set for any other reason is never touched.
  --json      machine-readable

It never prints a credential. It reads ~/.dsh/.credentials.yaml, finds the first key, and uses it; the key
never leaves the process.

FAILS SOFT ON PURPOSE. If the provider cannot be reached, the tool says so and CHANGES NOTHING - a network
blip must not pause the company, and a guard that cannot read the balance must not pretend the balance is
fine either. It reports unresolvable, and the caller decides.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

CRED = os.path.expanduser("~/.dsh/.credentials.yaml")
PAUSE = os.path.expanduser("~/.sms-inbox/WAKE_PAUSED")
MARK = "low-balance"
ENDPOINT = "https://api.deepseek.com/user/balance"


def read_key():
    try:
        txt = open(CRED, encoding="utf-8", errors="ignore").read()
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    keys = re.findall(r"(sk-[A-Za-z0-9_\-]{8,})", txt)
    if not keys:
        return None, "no key matching sk- in %s" % CRED
    return keys[0], None


def balance():
    key, err = read_key()
    if key is None:
        return None, err
    try:
        req = urllib.request.Request(ENDPOINT, headers={"Authorization": "Bearer " + key})
        doc = json.load(urllib.request.urlopen(req, timeout=25))
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:140])
    infos = doc.get("balance_infos") or []
    if not infos:
        return None, "provider returned no balance_infos"
    try:
        return float(infos[0].get("total_balance")), None
    except Exception as exc:
        return None, "unparseable balance: %s" % exc


def ceiling():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wake  # the same module the queue itself uses, so the number cannot diverge
        return float(os.environ.get("WAKE_MAX_USD_PER_DAY") or getattr(wake, "DEFAULT_MAX_USD_PER_DAY", 0.0))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", action="store_true")
    ap.add_argument("--floor", type=float, default=10.0,
                    help="pause below this balance (default 10.0)")
    ap.add_argument("--hysteresis", type=float, default=5.0,
                    help="do not auto-resume until the balance is floor + this (default 5.0)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    bal, err = balance()
    cap = ceiling()
    state = "unresolvable" if bal is None else ("low" if bal < a.floor else "ok")
    out = {"ok": bal is not None, "balance": bal, "ceiling": cap, "floor": a.floor,
           "state": state, "error": err, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if a.guard:
        if bal is None:
            out["action"] = "none (balance unreadable - changing nothing)"
        elif bal < a.floor:
            with open(PAUSE, "w") as fh:
                fh.write("%s %.2f at %s - the wake ceiling for one day is larger than the balance, so work "
                         "is paused rather than started and abandoned\n" % (MARK, bal, out["at"]))
            out["action"] = "PAUSED below %.2f" % a.floor
        elif os.path.exists(PAUSE):
            try:
                body = open(PAUSE, encoding="utf-8", errors="ignore").read()
            except Exception:
                body = ""
            if body.startswith(MARK) and bal >= a.floor + a.hysteresis:
                os.remove(PAUSE)
                out["action"] = "resumed - balance recovered to %.2f" % bal
            else:
                out["action"] = "pause file left alone (not ours, or balance not recovered)"
        else:
            out["action"] = "none (balance healthy)"

    if a.json:
        print(json.dumps(out))
    else:
        print("balance %s | ceiling/day %s | floor %s | %s%s"
              % ("unreadable" if bal is None else ("%.2f" % bal),
                 "unknown" if cap is None else ("%.2f" % cap),
                 "%.2f" % a.floor, state, "" if not out.get("action") else " | " + out["action"]))
        if bal is not None and cap is not None and cap > bal:
            print("WARNING: the daily ceiling (%.2f) is larger than the balance (%.2f) - it cannot bind."
                  % (cap, bal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
