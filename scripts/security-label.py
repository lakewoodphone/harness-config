#!/usr/bin/env python3
"""security-label — record what actually happened on an episode.

This is the only way a training example is created, and it is deliberately manual. The rules that make it
safe (research/D-learning-loop.md §3.3):

  * A label needs EVIDENCE. `--evidence` is required and must be one of credential / camera_frame /
    owner_statement / keypad_slot / none / NO_ANSWER. `disarm` is accepted but recorded as the weak class it
    is, and a DISARM_ONLY label may never by itself close a proposal.
  * Labels are append-only. Relabelling writes a NEW row with `supersedes_id` set; nothing is edited.
  * Confidence is required, because "the owner is pretty sure" and "a credential says so" are different
    facts and a learner that cannot tell them apart will average them.

Usage:
  security-label.py --list 7
  security-label.py --episode shop_door@2026-10-26T22:01:44Z --label courier \
      --evidence camera_frame --confidence 0.8 --basis "R2 frame 22:01:50 shows a parcel" --by owner
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

LABELS = ("owner", "parent", "wife", "guest", "tenant", "customer", "passer_by", "courier",
          "worker", "drill", "unknown", "infrastructure_false", "DISARM_ONLY")
EVIDENCE = ("credential", "camera_frame", "owner_statement", "keypad_slot", "disarm", "none", "NO_ANSWER")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--list", type=int, metavar="DAYS", help="show unlabelled episodes from the last N days")
    ap.add_argument("--episode")
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--evidence", choices=EVIDENCE)
    ap.add_argument("--confidence", type=float)
    ap.add_argument("--basis")
    ap.add_argument("--by", default="owner")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")

    if args.list:
        for r in conn.execute("""
            SELECT d.episode_id, MIN(d.created_at) AS first_seen,
                   MAX(CASE WHEN d.decided_by='fallback:shadow' THEN d.decision END) AS rule,
                   MAX(CASE WHEN d.decided_by LIKE 'agent%' THEN d.decision END) AS agent,
                   (SELECT label FROM security_label l WHERE l.episode_id = d.episode_id
                     ORDER BY l.id DESC LIMIT 1) AS label
            FROM security_decision d
            WHERE d.episode_id IS NOT NULL AND d.created_at > datetime('now', ?)
            GROUP BY d.episode_id ORDER BY first_seen DESC
        """, (f"-{args.list} days",)):
            status = r["label"] or "UNLABELLED"
            print(f"{r['first_seen'][:19]}  {r['episode_id'][:46]:46s}  rule={r['rule'] or '-':9s} "
                  f"agent={r['agent'] or '-':9s}  {status}")
        return 0

    if not (args.episode and args.label and args.evidence and args.confidence is not None):
        print("need --episode --label --evidence --confidence (or --list N)", file=sys.stderr)
        return 2
    if args.evidence == "none" and args.label not in ("unknown", "infrastructure_false"):
        print("refused: evidence 'none' may only support 'unknown' or 'infrastructure_false'", file=sys.stderr)
        return 2
    if not (0.0 <= args.confidence <= 1.0):
        print("refused: confidence must be 0..1", file=sys.stderr)
        return 2
    known = conn.execute("SELECT 1 FROM security_decision WHERE episode_id = ? LIMIT 1",
                         (args.episode,)).fetchone()
    if not known:
        print(f"refused: no episode {args.episode!r} in the record", file=sys.stderr)
        return 2

    prev = conn.execute("SELECT id FROM security_label WHERE episode_id = ? ORDER BY id DESC LIMIT 1",
                        (args.episode,)).fetchone()
    conn.execute(
        "INSERT INTO security_label (episode_id, label, evidence_class, confidence, basis, labelled_by, "
        "supersedes_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (args.episode, args.label, args.evidence, args.confidence, args.basis or "",
         args.by, prev["id"] if prev else None, utcnow()),
    )
    print(f"labelled {args.episode} -> {args.label} "
          f"(evidence={args.evidence}, confidence={args.confidence}"
          f"{', supersedes #' + str(prev['id']) if prev else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
