#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finance-reconciliation -- a wake source: the reconciliation's own verdict must
be able to wake someone up.

WHY (CFO anchors lane, 2026-10-16)
  `finance-reconcile.sh` has run since 2026-10-13 and writes
  `/root/.cfo/balances-live.json` and `/root/.cfo/reconciliation-worklist.md`,
  and NOTHING ON THIS BOX READS EITHER.  Measured 2026-10-16:

      grep -rln 'reconciliation-worklist|balances-live' \
          /root/bin /usr/local/bin /root/ceo-kernel/scripts /opt/company/scripts

  returns only `finance-reconcile.sh` itself -- the writer.  So the program's own
  documented SECOND completion condition ("every account-month is explained,
  reconciled, and carries no unnamed exception") produced 68 open disagreements
  and raised nothing.  A verdict nobody reads is not a check.

WHAT IT ALARMS ON
  disagreements > 0 in the file `finance-reconcile.sh` wrote last.  That is the
  condition the program defines as UNRECONCILED, so it is abnormal by definition
  and firing on it cannot be a false alarm.

  It does NOT alarm on staleness.  The producer runs weekly (`23 6 * * 0` today),
  so a file up to seven days old is the NORMAL case and a staleness alarm would
  fire every week on a healthy system.  The age is computed and printed in the
  prompt instead, so a reader can judge it.

  It does NOT alarm when the file cannot be read: exit 1 and a line on stderr,
  the contract's "signal unreadable" -- never a silent all-clear.

CONTRACT (same as every source in this directory)
  stdout is exactly one of `quiet` or `flagged <subject>`.
  exit 0 when the signal was read; exit 1 when it could not be read.
  Everything diagnostic goes to stderr.

  `--dry-run` prints the prompt instead of filing.

Usage
  finance-reconciliation.py [--dry-run] [--selftest]
                            [--report PATH] [--wake PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DEFAULT_REPORT = HOME / ".cfo" / "balances-live.json"
DEFAULT_WAKE = HOME / "bin" / "wake.py"
SOURCE = "finance-reconciliation"
SUBJECT = "finance-reconciliation-disagrees"


class Unreadable(Exception):
    """The signal could not be read at all.  Never becomes `quiet`."""


def now_utc():
    return datetime.now(timezone.utc)


def parse_stamp(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_verdict(path):
    """(verdict, error).  Never raises; an unreadable file is an error."""
    p = Path(path)
    if not p.is_file():
        return None, "no reconciliation file at %s" % p
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s: %s" % (p, type(exc).__name__, exc)
    totals = blob.get("totals")
    if not isinstance(totals, dict) or "disagreements" not in totals:
        return None, "%s carries no totals.disagreements" % p
    at = parse_stamp(blob.get("at"))
    age_hours = None
    if at is not None:
        age_hours = (now_utc() - at).total_seconds() / 3600.0
    return {
        "path": str(p),
        "at": blob.get("at"),
        "age_hours": age_hours,
        "window": blob.get("window") or {},
        "totals": totals,
        "ledger": blob.get("ledger") or {},
        "accounts": blob.get("accounts") or [],
    }, ""


def worst_disagreements(verdict, limit=10):
    """The dated rows behind the count: (abs_delta, account, month, delta, note)."""
    rows = []
    for acct in verdict.get("accounts") or []:
        for dis in acct.get("disagreements") or []:
            note = dis.get("note") or ""
            witness = dis.get("export_witness") or {}
            if witness.get("verdict"):
                note = "%s [export witness: %s]" % (note, witness["verdict"])
            rows.append((abs(dis.get("delta_cents") or 0), acct.get("account_id"),
                         dis.get("month"), dis.get("delta_cents"), note))
    rows.sort(reverse=True)
    return rows[:limit]


def build_prompt(verdict):
    t = verdict["totals"]
    age = verdict.get("age_hours")
    lines = [
        "Reconciliation: the ledger does not tie to the account balances.",
        "",
        "%d account-month(s) disagree, out of %s account-months; anchored %s, "
        "derived %s, unknown %s."
        % (t.get("disagreements"), t.get("account_months"), t.get("anchored"),
           t.get("derived"), t.get("unknown")),
        "Of the disagreements, %s open on an anchor the tool itself warns about "
        "and %s are paired (one defect counted twice)."
        % (t.get("disagreements_from_warned_anchor"),
           t.get("disagreements_paired")),
        "",
        "measured at %s (%s)"
        % (verdict.get("at"),
           "unknown age" if age is None else "%.1f h ago" % age),
        "window %s .. %s" % ((verdict.get("window") or {}).get("from"),
                             (verdict.get("window") or {}).get("to")),
        "ledger sha256 %s" % (verdict.get("ledger") or {}).get("sha256"),
        "",
        "worst rows (absolute delta):",
    ]
    for _abs, acct, month, delta, note in worst_disagreements(verdict):
        lines.append("  %s %s  delta %+d cents  %s" % (acct, month, delta or 0, note[:200]))
    lines += [
        "",
        "Reproduce with: /usr/bin/python3 /root/bin/cfo-balances.py --build --months 24 "
        "--out /root/.cfo/balances-live.json",
        "then read /root/.cfo/reconciliation-worklist.md (written by "
        "/usr/local/bin/finance-reconcile.sh).",
        "",
        "Do not edit any balance by hand. Where a bank activity export disagrees with "
        "the ledger, the export is the institution's own record and is the authority; "
        "/root/bin/cfo-anchors.py holds that evidence per window.",
    ]
    return "\n".join(lines)


def selftest(args):
    cases = [
        ("clean", {"at": now_utc().isoformat(), "totals": {"disagreements": 0}},
         "quiet"),
        ("one-disagreement", {"at": "2026-10-16T01:00:00+00:00",
                              "totals": {"disagreements": 1}}, "WOULD-FILE"),
        ("stale-but-zero", {"at": "2026-09-01T00:00:00+00:00",
                            "totals": {"disagreements": 0}}, "quiet"),
        ("no-totals", {"at": "2026-10-16T01:00:00+00:00"}, "UNREADABLE"),
        ("missing", None, "UNREADABLE"),
        ("not-json", "not json at all", "UNREADABLE"),
    ]
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, blob, expect in cases:
            path = os.path.join(tmp, name + ".json")
            if blob is not None:
                with open(path, "w", encoding="utf-8") as fh:
                    if isinstance(blob, str):
                        fh.write(blob)
                    else:
                        json.dump(blob, fh)
            verdict, error = read_verdict(path)
            if error:
                got = "UNREADABLE"
            else:
                got = "WOULD-FILE" if verdict["totals"].get("disagreements") else "quiet"
            ok = got == expect
            failures += 0 if ok else 1
            print("  %-18s expect=%-11s got=%-11s %s"
                  % (name, expect, got, "ok" if ok else "FAIL"))
    print("SELFTEST %s (%d failure(s))" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


def file_flag(wake, prompt):
    proc = subprocess.run(
        ["/usr/bin/python3", str(wake), "flag",
         "--subject", SUBJECT, "--prompt", prompt,
         "--kind", "finance-unreconciled", "--source", SOURCE, "--priority", "high"],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--wake", default=str(DEFAULT_WAKE))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest(args)

    verdict, error = read_verdict(args.report)
    if error:
        # An unreadable reconciliation is NEVER a healthy one.
        print("%s: SIGNAL UNREADABLE -- %s" % (SOURCE, error), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(verdict, default=str))

    if not verdict["totals"].get("disagreements"):
        print("quiet")
        return 0

    prompt = build_prompt(verdict)
    if args.dry_run:
        print("WOULD-FILE %s (%s disagreement(s)):\n%s"
              % (SUBJECT, verdict["totals"]["disagreements"], prompt))
        return 0

    rc, out, err = file_flag(args.wake, prompt)
    first = (out.splitlines() or [""])[0]
    # stdout is frozen to the contract's two words: `quiet`, or `flagged <subject>`.
    # The store's own decision (filed / deduped / capped / suppressed:*) is on
    # stderr, so an operator can tell "I filed it" from "it was already there".
    if rc == 0:
        print("flagged %s" % SUBJECT)
    else:
        print("quiet")
    print("(%s: %s disagreements=%s rc=%s)"
          % (SUBJECT, verdict["totals"]["disagreements"], first or err[:160], rc),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:                                        # noqa: BLE001
        print("%s FAULT: %s: %s" % (SOURCE, type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
