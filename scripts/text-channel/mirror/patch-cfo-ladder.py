#!/usr/bin/env python3
"""Wire `preask` — the due-diligence ladder — into cfo-ask.py before it composes.

WHY THIS PATCH EXISTS
---------------------
`preask.py` is 708 lines implementing the owner's rule of 2026-10-16, verbatim:

    "Remember, before you give me a charge, you have to exhaust all of the resources for
     exploring it. And then, if you still don't know, give me all the details you found."

Measured on the authority 2026-10-19: `preask.py` was **absent from /root/bin** and the
literal string "preask" appeared **0 times** in cfo-ask.py, owner-ask.py, card-due-watch.py,
owner_text_relay.py, charge_msg.py and sms-responder.py. The ladder had never been deployed
and nothing called it. cfo-ask DOES run `merchant_resolve` — but that reads the LEDGER only,
and his sentence names email and the case files. preask's rungs are `owner_answer`, `ledger`,
`comms` (the whole mail/text archive), `docs` and `web`.

Three insertions:
  1. a defensive import (a partial deploy must degrade, never crash an asker cron runs)
  2. helper functions before `try_resolve`
  3. the ladder inside the resolve loop, before the break that composes a question

    python3 patch-cfo-ladder.py /root/bin/cfo-ask.py --check
"""
import io
import sys

IMPORT = '''
try:
    import preask
except ImportError:                                        # pragma: no cover
    preask = None

#: How many extra evidence clauses the ladder may add to an ask. The owner's rule says
#: "give me all the details you found", but a body over the ceiling is truncated and then
#: he has neither the question nor the detail. Two clauses is what fits beside the charge.
LADDER_EVIDENCE_MAX = 2
'''

HELPERS = '''
def run_ladder(rec: dict):
    """Walk preask's ladder for this charge. Returns (Receipt|None, why).

    Never raises and never blocks an ask: a missing module or a rung fault must leave the
    asker exactly as it was before this existed. Each rung is independently failable inside
    preask itself, and a receipt that is `incomplete` still says which sources it could not
    read, so the composer can avoid claiming them.
    """
    if preask is None:
        print("preask not importable; asking after the ledger check only", file=sys.stderr)
        return None, "preask absent"
    try:
        return preask.resolve(
            "charge",
            amount=(rec.get("max_cents") or 0) / 100.0,
            merchant=rec.get("merchant") or "",
            date=rec.get("dated") or rec.get("newest") or "",
            subject=rec.get("merchant") or "",
        ), "ran"
    except Exception as exc:  # noqa: BLE001
        print(f"preask ladder failed ({exc}); asking after the ledger check only", file=sys.stderr)
        return None, f"error: {exc}"


def ladder_evidence(receipt) -> list:
    """The clauses the ask should CARRY: what was looked for and what was found."""
    if receipt is None:
        return []
    out = []
    for rung in getattr(receipt, "rungs", []) or []:
        status = getattr(rung, "status", "")
        text = (getattr(rung, "sentence", "") or getattr(rung, "detail", "") or "").strip()
        if not text or status not in ("solved", "not_found"):
            continue
        out.append(f"{getattr(rung, 'name', '?')}: {text}")
        if len(out) >= LADDER_EVIDENCE_MAX:
            break
    return out


def record_ladder_answered(rec: dict, receipt) -> int:
    """Record a question the LADDER answered, in the same ledger row shape as an auto-resolve.

    Reusing `record_auto_resolved` is deliberate: one place decides what a "we answered it
    ourselves" row looks like, and the daily cap must not be spent on a text nobody received.
    """
    res = receipt.resolution or {}
    return record_auto_resolved(rec, {
        "solved": True,
        "entity": res.get("detail") or "",
        "category": res.get("rung") or "preask",
        "confidence": 0.99,
        "source": "preask",
        "method": res.get("rung") or "preask",
        "evidence": list(res.get("keys") or []) + [res.get("detail") or ""],
        "merchant_key": rec.get("merchant_key"),
        "checked": [f"{r.name}: {r.status}" for r in (receipt.rungs or [])],
    })
'''

LOOP = '''        resolution = try_resolve(rec)

        # ── THE LADDER (added 2026-10-19) ────────────────────────────────────────
        # `try_resolve` reads the LEDGER. The owner's rule is wider than the ledger -- he
        # named email and the case files -- so preask walks his own past answers, the
        # ledger, the whole comms archive, the documents and the web. A rung that solves it
        # must stop the question being composed at all; a rung that finds nothing leaves
        # evidence the question has to carry, which is the second half of his sentence:
        # "if you still don't know, give me all the details you found."
        #
        # Placed BEFORE the resolved_enough break so the ladder is consulted even when the
        # ledger is silent, and only when the ledger has not already answered the question.
        if not resolved_enough(resolution):
            ladder, ladder_why = run_ladder(rec)
            if ladder is not None:
                ladder_verdict, ladder_reason = preask.may_ask(ladder)
                print(f"ladder: verdict={ladder.verdict} ({ladder_why}) -> {ladder_verdict} "
                      f"[{ladder_reason}]")
                for _r in ladder.rungs:
                    print(f"   {_r.name:12s} {_r.status:9s} {_r.ms:5d}ms  {(_r.sentence or _r.detail)[:96]}")
                if ladder_verdict == "do_not_ask":
                    rid = record_ladder_answered(rec, ladder)
                    print_resolution(rec, (ladder.resolution or {}), rid, verbose=args.why)
                    walked.add(rec["merchant_key"])
                    rec, why, detail = next_question(reason=args.why, skip=walked)
                    if rec is not None:
                        print(f"\\nnext candidate after the ladder answered one: {rec['merchant']}")
                    continue
                extra = ladder_evidence(ladder)
                if extra:
                    resolution = dict(resolution or {})
                    resolution["evidence"] = list(resolution.get("evidence") or []) + extra

        if not resolved_enough(resolution):
            break
'''

ANCHORS = [
    ("import", "try:\n    import merchant_resolve\nexcept ImportError:                                        # pragma: no cover\n    merchant_resolve = None\n",
     "try:\n    import merchant_resolve\nexcept ImportError:                                        # pragma: no cover\n    merchant_resolve = None\n" + IMPORT),
    ("helpers", "\ndef try_resolve(rec: dict) -> dict | None:", HELPERS + "\ndef try_resolve(rec: dict) -> dict | None:"),
    ("loop", "        resolution = try_resolve(rec)\n        if not resolved_enough(resolution):\n            break\n", LOOP),
]


def main(argv):
    path = argv[1]
    check = "--check" in argv[2:]
    src = io.open(path, encoding="utf-8").read()
    for label, old, _new in ANCHORS:
        n = src.count(old)
        if n != 1:
            print("REFUSED %s: anchor found %d time(s)" % (label, n))
            return 2
    for label, old, new in ANCHORS:
        src = src.replace(old, new, 1)
        print("anchored %s" % label)
    if check:
        print("check only; nothing written")
        return 0
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("written: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
