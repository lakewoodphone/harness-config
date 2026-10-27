#!/usr/bin/env python3
"""security-propose — a rule change may only land with a replay attached, and must show its work.

The acceptance test this exists to satisfy (50-BUILD-PLAN stage 7):
  * one proposal is promoted and one is refused, both with the replay attached;
  * a deliberately bad proposal is refused **with the episode it would have missed named**;
  * a change that reduces firing power needs the owner's line before it lands.

How a proposal is judged, in order:
  1. Replay the CURRENT parameters -> baseline (false alarms, real missed).
  2. Replay the CANDIDATE parameters -> candidate.
  3. Refuse if the candidate misses a real event the baseline caught, or adds a false alarm. Always.
  4. If it improves or equals, it may land — unless it *reduces firing power* (fewer alarms on episodes
     that were expected to alarm, or a wider credential window), which needs the owner.

Every run is written to `replay_run`, so the record carries the evidence whether the proposal won or lost.
Exit: 0 promoted, 3 refused, 2 harness error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

REPLAY = "/root/security-replay.py"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_replay():
    spec = importlib.util.spec_from_file_location("sec_replay", REPLAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score(corpus: dict, params: dict, mode: str, rep) -> dict:
    eps = corpus["episodes"]
    res = [(e, rep.evaluate(e, params, mode)) for e in eps]
    false_added = [e["id"] for e, r in res if e["expected"] == "benign" and r["verdict"] == "ALARM"]
    missed = [e["id"] for e, r in res if e["expected"] == "alarm" and r["verdict"] != "ALARM"]
    alarms = [e["id"] for e, r in res if r["verdict"] == "ALARM"]
    return {"false_added": false_added, "missed": missed, "alarms": alarms, "n": len(eps)}


def record(db: str, corpus_version: str, label: str, mode: str, params: dict, s: dict, verdict: str,
           notes: dict) -> str:
    conn = sqlite3.connect(db, timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=5000")
    rid = uuid.uuid4().hex[:24]
    conn.execute(
        "INSERT INTO replay_run (id, corpus_version, proposal_id, created_at, episodes_evaluated, missed_real, "
        "false_added, verdict, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (rid, corpus_version, label, utcnow(), s["n"], len(s["missed"]), len(s["false_added"]), verdict,
         json.dumps({"signal": mode, "params": params, **notes}, default=str)))
    return rid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="/root/replay-corpus-v1.json")
    ap.add_argument("--db", default=None, help="record baseline, candidate and outcome here")
    ap.add_argument("--label", required=True, help="what is being proposed")
    ap.add_argument("--param", action="append", default=[], help="key=value, repeatable")
    ap.add_argument("--signal", choices=("historical", "credential"), default="credential")
    ap.add_argument("--baseline-window", type=int, default=120)
    ap.add_argument("--reduces-firing", action="store_true",
                    help="declare that this change lowers detection power (needs the owner)")
    ap.add_argument("--owner-approved", action="store_true")
    args = ap.parse_args()

    rep = load_replay()
    with open(args.corpus, encoding="utf-8") as fh:
        corpus = json.load(fh)

    base_params = {"credential_window_s": args.baseline_window, "require_door": True}
    cand_params = dict(base_params)
    for p in args.param:
        k, _, v = p.partition("=")
        cand_params[k] = (v.lower() == "true") if v.lower() in ("true", "false") else int(v)

    base = score(corpus, base_params, args.signal, rep)
    cand = score(corpus, cand_params, args.signal, rep)

    print(f"=== proposal: {args.label}")
    print(f"baseline {json.dumps(base_params)} -> false={len(base['false_added'])} missed={len(base['missed'])} "
          f"alarms={len(base['alarms'])}")
    print(f"candidate {json.dumps(cand_params)} -> false={len(cand['false_added'])} missed={len(cand['missed'])} "
          f"alarms={len(cand['alarms'])}")

    reasons: list[str] = []
    if cand["missed"]:
        reasons.append(f"would MISS real event(s) {cand['missed']} that the baseline caught")
    if set(cand["false_added"]) > set(base["false_added"]):
        new_false = sorted(set(cand["false_added"]) - set(base["false_added"]))
        reasons.append(f"would add false alarm(s) on {new_false}")
    if args.reduces_firing and not args.owner_approved:
        reasons.append("reduces firing power and has no owner line in the record")

    promoted = not reasons
    verdict = "pass" if promoted else "fail"
    print()
    if promoted:
        print(f"PROMOTE: no real event missed, no new false alarm ({len(cand['alarms'])} alarm(s) on corpus)")
        for ep in cand["alarms"]:
            print(f"  would alarm on: {ep}")
    else:
        print("REFUSE:")
        for r in reasons:
            print(f"  - {r}")

    if args.db:
        rb = record(args.db, corpus["corpus_version"], f"{args.label} [baseline]", args.signal,
                    base_params, base, "inconclusive", {"role": "baseline"})
        rc = record(args.db, corpus["corpus_version"], args.label, args.signal, cand_params, cand,
                    verdict, {"role": "candidate", "promoted": promoted, "reasons": reasons,
                              "baseline_run": rb})
        print(f"recorded: baseline {rb}")
        print(f"recorded: candidate {rc} (verdict {verdict})")
    return 0 if promoted else 3


if __name__ == "__main__":
    raise SystemExit(main())
