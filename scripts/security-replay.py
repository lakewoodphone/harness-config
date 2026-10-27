#!/usr/bin/env python3
"""security-replay — evaluate a rule change against every episode ever recorded.

This is the gate. A proposed change is not an improvement until it can show what it would have done
differently on every past episode, and the list of REAL events it would have missed must be empty
(research/D-learning-loop.md §4.3).

Two modes, and the difference between them is a finding rather than a setting:

  --signal=historical   the building as it actually was: no credential signal existed at all
  --signal=credential   the building after the keypad is switched back on, ASSUMING an entitled entrant
                        would have used a credential at about the time they were credited

The second is an assumption and is printed as one. It exists because the corpus's "human credited" column
is *presence* credit - the broken signal - and letting that count as a credential would make every rule
look perfect for the wrong reason.

Exit code: 0 = gate passed, 1 = gate failed, 2 = the harness itself could not run.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

DEFAULTS = {"credential_window_s": 120, "require_door": True}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def evaluate(ep: dict, params: dict, mode: str) -> dict:
    if ep.get("expected") == "drill":
        return {"verdict": "SUPPRESSED", "why": "drill"}
    door = ep.get("door_offset_s")
    if door is None:
        if params["require_door"]:
            return {"verdict": "SILENT", "why": "no door edge"}
        # a rule that does not require a door is exactly the rule that produced 13 false alarms:
        # it alarms on presence alone. Kept in the harness so that proposal can be REFUSED with evidence.
        return {"verdict": "ALARM", "why": "no door edge, but this rule does not require one"}
    cred = None
    why_cred = "no credential signal exists in the historical record"
    if mode == "credential":
        credit = ep.get("presence_credit_offset_s")
        if credit is not None:
            cred = credit
            why_cred = f"ASSUMED credential at +{cred}s (the time the entrant was credited)"
    if cred is not None and abs(cred - door) <= params["credential_window_s"]:
        return {"verdict": "SILENT", "why": why_cred}
    if params.get("treat_missing_credential_as_benign"):
        # The most tempting wrong rule, and the reason the metric pair exists: it takes false alarms to zero
        # by declaring that an unbadged entry is probably a customer. It is in the harness so that a proposal
        # of this shape can be REFUSED with the real event it would have missed, named.
        return {"verdict": "SILENT", "why": "no credential, treated as benign (the unlearning rule)"}
    return {"verdict": "ALARM", "why": f"door at +{door}s, {why_cred}"}


def run(corpus_path: str, mode: str, params: dict, db: str | None, label: str) -> int:
    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    episodes = corpus["episodes"]
    results = [(ep, evaluate(ep, params, mode)) for ep in episodes]

    false_added = [(e, r) for e, r in results if e["expected"] == "benign" and r["verdict"] == "ALARM"]
    missed_real = [(e, r) for e, r in results if e["expected"] == "alarm" and r["verdict"] != "ALARM"]
    caught = [e for e, r in results if e["expected"] == "alarm" and r["verdict"] == "ALARM"]

    print(f"=== replay {corpus['corpus_version']} · signal={mode} · {json.dumps(params)}")
    print(f"{'ep':5s} {'label':22s} {'expected':9s} {'verdict':10s} why")
    for ep, r in results:
        mark = "  " if (ep["expected"] == "benign" and r["verdict"] != "ALARM") or \
                      (ep["expected"] == "alarm" and r["verdict"] == "ALARM") or ep["expected"] == "drill" else "!!"
        print(f"{mark}{ep['id']:3s} {ep.get('label',''):22s} {ep['expected']:9s} {r['verdict']:10s} {r['why'][:78]}")

    print(f"\nfalse alarms on benign episodes : {len(false_added)} of "
          f"{sum(1 for e in episodes if e['expected'] == 'benign')}")
    print(f"real events missed              : {len(missed_real)} of "
          f"{sum(1 for e in episodes if e['expected'] == 'alarm')}")
    passed = (len(false_added) == 0 and len(missed_real) == 0)
    verdict = "pass" if passed else ("fail" if missed_real else "inconclusive")
    print(f"GATE: {'PASS' if passed else 'FAIL'}  (verdict recorded as '{verdict}')")
    if false_added and not missed_real:
        print("note: no real event is missed, but the rule would cry wolf. 'inconclusive' is not 'passed'.")

    if db:
        try:
            conn = sqlite3.connect(db, timeout=10.0, isolation_level=None)
            conn.execute("PRAGMA busy_timeout=5000")
            rid = uuid.uuid4().hex[:24]
            conn.execute(
                "INSERT INTO replay_run (id, corpus_version, proposal_id, created_at, episodes_evaluated, "
                "missed_real, false_added, verdict, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, corpus["corpus_version"], label, utcnow(), len(episodes), len(missed_real),
                 len(false_added), verdict,
                 json.dumps({"signal": mode, "params": params,
                             "false_added_ids": [e["id"] for e, _ in false_added],
                             "missed_ids": [e["id"] for e, _ in missed_real]})),
            )
            for ep, r in results:
                conn.execute(
                    "INSERT INTO replay_episode (run_id, episode_id, expected, actual, missed_real) "
                    "VALUES (?,?,?,?,?)",
                    (rid, ep["id"], ep["expected"], r["verdict"],
                     1 if ep["expected"] == "alarm" and r["verdict"] != "ALARM" else 0))
            print(f"recorded: replay_run {rid}")
        except sqlite3.Error as exc:
            print(f"WARNING: could not record the run: {exc}", file=sys.stderr)
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="/root/replay-corpus-v1.json")
    ap.add_argument("--signal", choices=("historical", "credential"), default="historical")
    ap.add_argument("--credential-window", type=int, default=DEFAULTS["credential_window_s"])
    ap.add_argument("--allow-no-door", action="store_true", help="do not require a door edge")
    ap.add_argument("--db", default=None, help="record the run into this database")
    ap.add_argument("--label", default="unnamed proposal")
    args = ap.parse_args()
    params = {"credential_window_s": args.credential_window, "require_door": not args.allow_no_door}
    return run(args.corpus, args.signal, params, args.db, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
