#!/usr/bin/env python3
"""Reconcile the owner's ANSWERS into the journal, so nothing he said is lost.

THE GAP, measured 2026-10-13. `owner_decision_queue` is the single source of truth for what is
waiting on the owner — and it is a **mutable table**. `owner-queue.py answer` writes his words into
the `answer` column and `resolve` writes `resolution`; a later `amend` can overwrite either. The
journal — append-only, one file per entry — is the only durable record this estate has.

Nothing connects the two. So:

    a decision the owner has given survives only as a column in a table that can be edited,
    and is lost exactly when the agent that recorded it forgets to write the journal entry.

That is the memory spec's gap (a) — "never lose an owner decision" — and it is a *silent* loss:
the row still reads `answered`, so every check says the answer is recorded.

WHAT THIS DOES. For every queue row that carries an answer, find out whether the journal already
holds it (any entry whose body mentions the row id). Report the ones it does not — and with
`--apply`, write a `decisions` entry for each through the sanctioned `journal.py append`, which
allocates the id, updates the cache and touches every git ref.

SAFETY
  * DRY RUN BY DEFAULT. It reports and writes nothing without `--apply`.
  * It NEVER writes to `owner_decision_queue`. The queue is read-only here.
  * It writes only through `journal.py append`, never by editing an entry.
  * A row that already has a decision is skipped, so re-running is idempotent.

USAGE
  python3 journal/tools/reconcile-owner-answers.py                 # report
  python3 journal/tools/reconcile-owner-answers.py --json
  python3 journal/tools/reconcile-owner-answers.py --apply [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOURNAL = HERE / "journal.py"
ROOT = HERE.parent.parent  # the repo root that holds journal/

# The authority. `owner-queue.py` lives there and nowhere else (P47).
AUTHORITY = os.environ.get("OWNER_QUEUE_HOST", "secratary-cloud")
QUEUE = os.environ.get("OWNER_QUEUE_PATH", "/root/bin/owner-queue.py")

# Statuses that mean "he has spoken". `answered` is a decision awaiting implementation;
# `resolved` is one that has been; both carry words worth keeping.
ANSWERED = {"answered", "resolved"}


def queue_rows() -> tuple[list[dict], str]:
    """The queue, read from wherever it is reachable. Returns (rows, provenance)."""
    local = Path(os.path.expanduser("~/bin/owner-queue.py"))
    if local.exists():
        cmd = ["python3", str(local), "list", "--all", "--json"]
        prov = f"local {local}"
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", AUTHORITY,
               f"python3 {QUEUE} list --all --json"]
        prov = f"ssh {AUTHORITY}:{QUEUE}"
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=90)
    if out.returncode != 0 or not (out.stdout or "").lstrip().startswith("["):
        raise SystemExit(f"could not read the queue via {prov} (rc={out.returncode}): "
                         f"{(out.stderr or '')[:300]}")
    return json.loads(out.stdout), prov


def rows_already_in_the_journal() -> tuple[set[int], int]:
    """Every queue-row id that any journal entry already mentions.

    Deliberately generous: a decision entry, a handoff or a win that says "row #451" counts as
    holding it. The question this answers is "would anything be lost if the row vanished", not
    "is there a perfectly formed decision entry".
    """
    ids: set[int] = set()
    files = 0
    pat = re.compile(r"(?:row|queue|#)\s*#?(\d{1,5})\b", re.I)
    for path in (ROOT / "journal" / "entries").rglob("*.md"):
        files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(text):
            try:
                ids.add(int(m.group(1)))
            except ValueError:
                pass
    return ids, files


def body_for(row: dict) -> str:
    q = (row.get("question") or "").strip()
    a = (row.get("answer") or "").strip()
    res = (row.get("resolution") or "").strip()
    parts = [
        f"Recovered from `owner_decision_queue` row #{row.get('id')} by",
        "`journal/tools/reconcile-owner-answers.py`. The row is a mutable table column; this entry",
        "is the append-only copy. If the two ever disagree, the row was edited and this is the record.",
        "",
        f"**Asked** ({row.get('asked_at') or 'date unknown'}): {q}",
        "",
        f"**His answer** ({row.get('answered_at') or 'date unknown'}): {a or '(none recorded)'}",
    ]
    if res:
        parts += ["", f"**Resolution**: {res}"]
    rec = (row.get("recommendation") or "").strip()
    if rec:
        parts += ["", f"**What was recommended**: {rec}"]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the missing decisions (default: report)")
    ap.add_argument("--limit", type=int, default=0, help="cap how many are written")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows, prov = queue_rows()
    answered = [r for r in rows if (r.get("status") or "") in ANSWERED and (r.get("answer") or "").strip()]
    known, nfiles = rows_already_in_the_journal()
    missing = [r for r in answered if r.get("id") not in known]

    report = {
        "queue_source": prov,
        "rows_read": len(rows),
        "rows_with_an_answer": len(answered),
        "journal_entry_files_scanned": nfiles,
        "row_ids_the_journal_already_mentions": len(known),
        "answers_with_NO_journal_copy": len(missing),
        "ids": [r.get("id") for r in missing],
        "applied": [],
    }

    if a.json and not a.apply:
        print(json.dumps(report, indent=2))
        return 0

    print(f"queue        : {prov}")
    print(f"rows read    : {len(rows)}")
    print(f"with an answer: {len(answered)}")
    print(f"journal scan : {nfiles} entry files, {len(known)} distinct row ids mentioned")
    print(f"**answers with NO journal copy: {len(missing)}**")
    if missing:
        print()
        for r in missing[:20]:
            q = re.sub(r"\s+", " ", (r.get("question") or ""))[:96]
            ans = re.sub(r"\s+", " ", (r.get("answer") or ""))[:60]
            print(f"  #{r.get('id'):>4}  {r.get('status'):<9} {r.get('severity',''):<8} {q}")
            print(f"        his words: {ans}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")

    if not a.apply:
        print()
        print("DRY RUN — nothing written. Pass --apply to write them.")
        return 0

    if not JOURNAL.exists():
        raise SystemExit(f"journal.py not found at {JOURNAL}")
    todo = missing[:a.limit] if a.limit else missing
    for r in todo:
        title = "Owner answer, queue row #%s: %s" % (
            r.get("id"), re.sub(r"\s+", " ", (r.get("question") or ""))[:80])
        cmd = [sys.executable, str(JOURNAL), "append", "decisions",
               "--title", title, "--body", body_for(r), "--quiet", "--no-fetch",
               "--tags", "owner-answer,reconciled",
               "--refs", "owner_decision_queue#%s" % r.get("id")]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120, cwd=str(ROOT))
        ok = out.returncode == 0
        report["applied"].append({"id": r.get("id"), "ok": ok,
                                  "out": (out.stdout or out.stderr or "").strip()[:120]})
        print(("  wrote " if ok else "  FAILED ") + f"#{r.get('id')}  "
              + (out.stdout or out.stderr or "").strip()[:90])

    wrote = sum(1 for x in report["applied"] if x["ok"])
    print()
    print(f"applied: {wrote} of {len(todo)}")
    if a.json:
        print(json.dumps(report, indent=2))
    return 0 if wrote == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
