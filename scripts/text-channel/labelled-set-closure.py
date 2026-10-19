#!/usr/bin/env python3
"""labelled-set-closure.py - every one of the 151 labelled turns against the gate as it is now.

The labelled set is the only part of the corpus with his REACTION attached (`answered_at`,
`answer_body`, `reason`). It is what the audit was built from, so closing the objective means being
able to say, for each turn, what the gate would do with it today and whether that is the right
answer.

Four outcomes per turn:
    REFUSED   the gate would refuse it - correct when the body was never a message to him
    REWRITTEN the gate would rescue it - correct when it was a reminder carrying scaffolding
    SENT      it would go out - correct when it was a readable message
    DUP       the same sid already appeared (the double-row defect, 29 of 151)

And for every one of them, whether his recorded reaction says it worked: `answered` with a real
reply, or `answered_code` naming a defect.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
turn = [json.loads(l) for l in open("data/turn.jsonl", encoding="utf-8")]

defect_codes = {"test_artefact_removed", "artefact_removed", "stale-no-question",
                "duplicate-row", "probe_closed_by_config_session", "stop_request"}
seen_sids = set()
rows = []
for t in turn:
    sid = t.get("sid") or ""
    dup = sid in seen_sids
    seen_sids.add(sid)
    body = t.get("body") or ""
    out, note = R._rescue_reminder(body, OWNER, "cron")
    rescued = bool(note and "rewritten" in str(note))
    refused = bool(R.internal_prose(out) or R.credential_request(out))
    verdict = "DUP" if dup else ("REFUSED" if refused else ("REWRITTEN" if rescued else "SENT"))
    rows.append({
        "id": t["id"], "reason": t.get("reason") or "", "verdict": verdict,
        "answered": bool((t.get("answer_body") or "").strip()),
        "code": t.get("answered_code") or "",
        "body": " ".join(body.split())[:70],
    })

print("labelled turns: %d" % len(rows))
print()
print("== what the gate would do today")
for k, n in Counter(r["verdict"] for r in rows).most_common():
    print("   %-10s %3d" % (k, n))
print()
print("== by reason (the producer), with the verdict mix")
by_reason = {}
for r in rows:
    by_reason.setdefault(r["reason"], Counter())[r["verdict"]] += 1
for reason, mix in sorted(by_reason.items(), key=lambda kv: -sum(kv[1].values())):
    print("   %-26s %s" % (reason[:26], dict(mix)))
print()
print("== turns the gate refuses that he ANSWERED (the real cost)")
n = 0
for r in rows:
    if r["verdict"] == "REFUSED" and r["answered"]:
        n += 1
        print("   [%d] %-26s %s" % (r["id"], r["reason"][:26], r["body"]))
print("   total: %d" % n)
print()
print("== turns carrying a defect code in the ledger (the double-row class)")
for r in rows:
    if r["code"] in defect_codes:
        print("   [%d] %-24s %s" % (r["id"], r["code"][:24], r["body"]))
