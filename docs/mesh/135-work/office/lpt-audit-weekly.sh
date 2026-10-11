#!/usr/bin/env bash
# lpt-audit-weekly.sh - the recurring production hygiene pass, on the authority.
#
# WHY THIS EXISTS: the owner asked for a periodic dedup and sync pass over production work
# orders that he is shown. An audit nobody runs is a decoration, and this system has a
# recorded history of jobs that ran, exited 0 and produced nothing. So this one keeps a
# dated report, keeps a latest copy, and writes a journal note ONLY when the finding count
# changes - silence means "same as last week", not "not checked".
set -uo pipefail
REPO="$HOME/code/lpt-ops"
OUT="$HOME/.lpt-ops/audit"
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
cd "$REPO" || { echo "lpt-audit: no checkout at $REPO" >&2; exit 2; }

# ---- STALE-CHECKOUT GUARD -------------------------------------------------------------------
# MEASURED 2026-10-06: this script ran from a checkout that was SIX COMMITS BEHIND origin and
# never pulled, so every scheduled audit reported the verdicts of code from days earlier - and a
# fixed check would never have reached the weekly run at all. A scheduled job whose behaviour is
# decided by whatever happens to be on disk is not a schedule, it is a hope.
#
# The pull is best-effort on purpose: a network failure must not stop the audit. What must never
# happen is a STALE run being read as a CURRENT one, so the commit it ran at is printed and
# stored, and a failed pull says so in the log instead of being silent.
if git fetch -q origin 2>/dev/null && git pull -q --ff-only 2>/dev/null; then
  :
else
  echo "lpt-audit: WARNING - could not fast-forward the checkout; this run uses whatever is on disk"
fi
HEAD_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
echo "lpt-audit: running from $HEAD_SHA"


python3 bin/lpt-audit --json --limit 1000 > "$OUT/$STAMP.json" 2>"$OUT/$STAMP.err"
RC=$?
python3 bin/lpt-audit --limit 1000 > "$OUT/latest.txt" 2>&1
cp -f "$OUT/latest.txt" "$OUT/$STAMP.txt"

python3 - "$OUT" "$STAMP" "$RC" <<'PY'
import json, pathlib, subprocess, sys, os
out, stamp, rc = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
def total(f):
    try:
        d = json.loads(f.read_text())
    except Exception:
        return None
    n = 0
    for c in (d.get("checks") or []):
        n += len(c.get("findings") or [])
    return n
now = total(out / f"{stamp}.json")
prev_files = sorted(p for p in out.glob("*.json") if p.name != f"{stamp}.json")
prev = total(prev_files[-1]) if prev_files else None
state = out / "state.json"
state.write_text(json.dumps({"at": stamp, "findings": now, "previous": prev,
                             "exit": rc, "report": str(out / f"{stamp}.txt")}, indent=1))
if now is None:
    print("lpt-audit: the audit produced no readable JSON (exit %d) - reported as unmeasured" % rc)
    sys.exit(0)
if prev is None or now != prev:
    body = (f"Automated production hygiene pass, {stamp} (exit {rc}).\n\n"
            f"Findings now: {now}. Previous run: {prev if prev is not None else 'none on record'}.\n\n"
            f"The full ranked report is at {out}/{stamp}.txt and the JSON at {out}/{stamp}.json.\n"
            f"Run `lpt audit --limit 200` for the whole list, or read the latest at {out}/latest.txt.\n"
            f"Nothing here writes to production; every check is a SELECT.\n")
    p = pathlib.Path.home() / "code/harness-config/journal/tools/journal.py"
    if p.exists():
        subprocess.run(["python3", str(p), "append", "handoff",
                        "--title", f"lpt audit weekly pass {stamp}: {now} finding(s)",
                        "--body", body], check=False)
        print(f"lpt-audit: findings {prev} -> {now}; journal note written")
    else:
        print(f"lpt-audit: findings {prev} -> {now}; no journal.py to record it")
else:
    print(f"lpt-audit: findings unchanged at {now}")
PY

# ---- SURFACE TO THE OWNER ---------------------------------------------------------------------
# MEASURED 2026-10-07: this script computed and ranked 319 findings and told NOBODY. It wrote a
# dated report and a journal note; the report sits on the authority and the note lands in a journal
# branch a laptop session cannot read (L3356). `bin/lpt-audit-surface.py` existed to be that channel
# and had no caller anywhere in either repository. A finding nobody is shown is not a finding.
#
# Called unconditionally, on purpose: it is silent when nothing changed, and it compares NAMED
# findings rather than a total, so the shop being busy is not reported as the data getting worse
# (L3364). It queues ONE row naming the top three, never a row per finding.
echo "lpt-audit: surfacing to the owner queue"
python3 bin/lpt-audit-surface.py 2>&1 | sed 's/^/lpt-audit: /'

echo "lpt-audit: report $OUT/$STAMP.txt"
exit 0