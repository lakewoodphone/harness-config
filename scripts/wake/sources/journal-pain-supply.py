#!/usr/bin/env python3
"""LEDGER SOURCE: file OPEN journal pain entries as ledger items, capped per run.

THE SIGNAL
----------
    python3 ~/harness-config/journal/tools/journal.py list --kind pain --status open \
        --limit 5000 --json
measured 2026-09-30: 276 open pain entries. That is the machine's own written backlog.

WHY THIS EXISTS
---------------
The dispatcher idles on an empty todo queue while 276 open pain entries sit unread. Those two
facts are the same fact: nothing turned the journal's pains into work a shift can claim. This
source is the reader. It is the largest available increase in work supply that needs no new
discovery -- the machine already wrote down what hurts.

USAGE
-----
    journal-pain-supply.py                       # DRY RUN: list candidates, file nothing
    journal-pain-supply.py --apply               # file at most --cap (default 5)
    journal-pain-supply.py --apply --cap 1
    journal-pain-supply.py --json

WHY A SECOND --apply FILES NONE
-------------------------------
Two independent brakes, because a supply source that floods the ledger is a different failure
from an empty one:
  1. WINDOW BUDGET. At most --cap items are filed per --window-seconds (default 86400, a day).
     A second apply inside the window has nothing left to spend (=the same brake
     checkout-health.py uses, "at most one row per project per UTC day").
  2. IDENTITY. ~/.journal-pain-supply/filed.json remembers every pain id this source has already
     turned into work, and the ledger itself is scanned for the [journal-pain P<ID>] marker, so
     losing the state file does not refile. A pain whose normalized heading matches one already
     filed is skipped even under a NEW id: P2799 and P2798 are the same money-plane defect filed
     twice, and two identical ledger items is exactly the duplicate work work.py's own dedupe
     exists to refuse.

WHAT IT DOES NOT DO
-------------------
    - run the pain checks or resolve journal entries. It only files work.
    - file more than --cap in one run, on purpose. 276 items at once is not supply, it is noise.

Exit codes: 0 ran (even if it filed nothing) - 2 cannot read the journal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

JOURNAL = os.environ.get(
    "JOURNAL_PY", "/home/zabz/harness-config/journal/tools/journal.py")
WORK = os.environ.get("WORK_CLI", "/home/zabz/bin/work.py")
STATE = Path(os.environ.get(
    "JOURNAL_PAIN_STATE", str(Path.home() / ".journal-pain-supply" / "filed.json")))
DEFAULT_PROJECT = os.environ.get("JOURNAL_PAIN_PROJECT", "housekeeping")
DEFAULT_CAP = int(os.environ.get("JOURNAL_PAIN_CAP", "5"))
DEFAULT_PRIORITY = int(os.environ.get("JOURNAL_PAIN_PRIORITY", "5"))
DEFAULT_WINDOW = int(os.environ.get("JOURNAL_PAIN_WINDOW_SECONDS", "86400"))
SOURCE = "journal-pain-supply"
MARKER_RE = re.compile(r"\[journal-pain\s+(P\d{1,4})\]", re.I)
TITLE_CAP = 110


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact(text: str, limit: int = TITLE_CAP) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def short_heading(entry: dict) -> str:
    """`## P2817 -- A real reminder...` -> `A real reminder...` (one line, capped)."""
    h = entry.get("heading") or entry.get("title") or entry.get("id") or ""
    h = re.sub(r"^#+\s*", "", h.strip())
    h = re.sub(r"^%s\b\s*[-\u2013\u2014:]*\s*" % re.escape(entry.get("id") or ""), "", h)
    h = h.replace("`", "").replace("*", "")
    return compact(h) or ("open pain entry %s" % entry.get("id"))


def heading_key(entry: dict) -> str:
    h = re.sub(r"^#+\s*", "", (entry.get("heading") or "").strip())
    h = re.sub(r"^%s\b\s*[-\u2013\u2014:]*\s*" % re.escape(entry.get("id") or ""), "", h)
    h = re.sub(r"\s+", " ", h).strip().lower()
    return hashlib.sha1(h.encode("utf-8", "replace")).hexdigest() if h else ""


def title_for(entry: dict) -> str:
    return compact("[journal-pain %s] %s" % (entry["id"], short_heading(entry)))


def dod_for(entry: dict) -> str:
    """The proving command for one pain item -- and it must FAIL CLOSED.

    The first version was two-valued: it read the OPEN list once and used a shell
    `grep -q` with a `||` fallback, so a grep MISS printed the resolved word. That
    reads a DELETED pain id as RESOLVED: `grep` fails both for a pain that was
    properly fixed and for one that VANISHED, and the fallback cannot tell the two
    apart. Measured 2026-10-09: item 232's own DoD printed RESOLVED for P2797 only
    because the P2797 entry file was deleted in the 2026-10-07 collided-id cleanup
    (commit 3863c577); there was no resolve row and no resolution commit. A stripped
    record is not a fix.

    The command below checks EVERY status (journal.py list with no --status returns
    open, done, superseded and retracted together) and separates three outcomes:

        open in the journal          -> STILL-OPEN          exit 1
        present, not open (resolved) -> RESOLVED            exit 0
        absent from the journal      -> GHOST-RECORD-LOST   exit 1

    A vanished entry can never again be read as done.
    """
    pid = (entry.get("id") or "").upper()
    program = (
        "import json,subprocess,sys; "
        "p=subprocess.run([sys.executable,'%s','list','--kind','pain','--limit','5000',"
        "'--json'],capture_output=True,text=True); "
        "es=[e for e in (json.loads(p.stdout or '{}').get('entries') or []) "
        "if (e.get('id') or '').upper()=='%s']; "
        "st=(es[0].get('status') or 'open') if es else None; "
        "print('GHOST-RECORD-LOST' if st is None else "
        "('STILL-OPEN' if st=='open' else 'RESOLVED')); "
        "sys.exit(0 if (st and st!='open') else 1)"
        % (JOURNAL, pid)
    )
    return 'python3 -c "%s"' % program


def load_state() -> dict:
    if not STATE.is_file():
        return {"filed": {}, "headings": {}, "window": {}}
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("WARN: state file %s is not JSON (%s); treating as empty"
              % (STATE, exc), file=sys.stderr)
        return {"filed": {}, "headings": {}, "window": {}}
    d.setdefault("filed", {})
    d.setdefault("headings", {})
    d.setdefault("window", {})
    return d


def save_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE)


def open_pain(limit: int) -> list:
    cmd = [sys.executable, JOURNAL, "list", "--kind", "pain", "--status", "open",
           "--limit", str(limit), "--json"]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if p.returncode != 0:
        raise RuntimeError("journal list rc=%s: %s"
                           % (p.returncode, (p.stderr or p.stdout or "").strip()[-300:]))
    data = json.loads(p.stdout or "{}")
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        raise RuntimeError("journal list returned no entries list")
    return entries


def ledger_pain_ids(project: str) -> set:
    """Pain ids already carried by a ledger item title -- the ledger's own memory."""
    try:
        p = subprocess.run([sys.executable, WORK, "list", "--project", project,
                            "--limit", "5000", "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        if p.returncode != 0:
            return set()
        data = json.loads(p.stdout or "[]")
    except Exception:  # noqa: BLE001
        return set()
    rows = data if isinstance(data, list) else (
        data.get("items") or data.get("work_items") or data.get("rows") or [])
    ids = set()
    for r in rows:
        r = r or {}
        # Only NON-TERMINAL items count as already carrying the pain. A dropped/done row is
        # history, not coverage: treating it as filed would suppress a still-open pain for good.
        if r.get("state") not in (None, "todo", "running", "blocked"):
            continue
        m = MARKER_RE.search(str(r.get("title") or ""))
        if m:
            ids.add(m.group(1).upper())
    return ids


def file_item(entry: dict, project: str, priority: int) -> dict:
    p = subprocess.run(
        [sys.executable, WORK, "add", "--project", project,
         "--title", title_for(entry), "--dod", dod_for(entry),
         "--why", "open journal pain %s (filed %s): the machine's own written backlog, read by "
                  "journal-pain-supply as ledger supply" % (entry["id"], entry.get("date") or "?"),
         "--priority", str(priority), "--source", SOURCE],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    # work.py speaks `<status> {json}` on one line (`item-filed {"id": 219, ...}`), NOT bare JSON.
    # Parsing the whole line as JSON silently turned every successful filing into a failure and
    # left the window/identity state unwritten -- measured 2026-09-30, item 146 attempt 421.
    text = (p.stdout or "").strip()
    line = text.splitlines()[-1] if text else ""
    head, _, rest = line.partition(" ")
    if head in ("item-filed", "already-filed"):
        try:
            obj = json.loads(rest)
        except Exception:  # noqa: BLE001
            return {"status": head, "raw": line[-300:]}
        obj["status"] = head
        return obj
    return {"status": head or "error:no-output", "raw": text[-300:],
            "stderr": (p.stderr or "")[-300:]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually file items (default: dry run, files nothing)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP, help="max items per window")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--priority", type=int, default=DEFAULT_PRIORITY)
    ap.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    apply_ = a.apply and not a.dry_run

    try:
        entries = open_pain(a.limit)
    except Exception as exc:  # noqa: BLE001
        print("journal-pain-supply: cannot read the open pain list: %s" % exc, file=sys.stderr)
        return 2

    st = load_state()
    filed_ids = {k.upper(): v for k, v in (st.get("filed") or {}).items()}
    have_headings = dict(st.get("headings") or {})
    ledger_ids = ledger_pain_ids(a.project)

    candidates, skipped, seen_here = [], [], set()
    for e in entries:
        pid = (e.get("id") or "").upper()
        if not pid:
            continue
        h = heading_key(e)
        if pid in filed_ids:
            skipped.append((pid, "already-filed-by-this-source"))
        elif pid in ledger_ids:
            skipped.append((pid, "already-on-the-ledger"))
        elif h and h in have_headings:
            skipped.append((pid, "same-heading-as-%s" % have_headings[h]))
        elif h and h in seen_here:
            skipped.append((pid, "same-heading-as-%s-this-run" % have_headings.get(h, "?")))
        else:
            if h:
                seen_here.add(h)
            candidates.append(e)

    w = st.get("window") or {}
    started = float(w.get("started_epoch") or 0.0)
    spent = int(w.get("filed") or 0)
    if a.window_seconds and (time.time() - started) >= a.window_seconds:
        started, spent = time.time(), 0
    remaining = max(0, a.cap - spent)

    to_file = candidates[:remaining] if apply_ else []
    filed, failed = [], []
    for e in to_file:
        res = file_item(e, a.project, a.priority)
        status = res.get("status")
        if status in ("item-filed", "already-filed"):
            filed.append({"pain": e["id"], "item": res.get("id"), "status": status})
            filed_ids[e["id"].upper()] = {"item": res.get("id"), "at": now()}
            h = heading_key(e)
            if h:
                have_headings[h] = e["id"]
            spent += 1
            st["filed"] = filed_ids
            st["headings"] = have_headings
            st["window"] = {"started_epoch": started, "filed": spent}
            save_state(st)
        else:
            failed.append({"pain": e["id"], "result": res})

    would = candidates[:remaining]
    left = max(0, a.cap - spent)
    result = {
        "mode": "apply" if apply_ else "dry-run",
        "at": now(), "source": SOURCE, "project": a.project,
        "open_pain_entries": len(entries), "already_filed": len(filed_ids),
        "candidates": len(candidates), "window_cap": a.cap,
        "window_spent": spent, "window_remaining": left,
        "files": len(filed), "filed": filed, "failed": failed,
        "would_file": [{"pain": e["id"], "title": title_for(e)} for e in would],
        "skipped": [{"pain": p, "why": y} for p, y in skipped[:25]],
    }
    if a.json:
        print(json.dumps(result, indent=2))
        return 0

    print("journal-pain-supply %s mode=%s project=%s" % (result["at"], result["mode"], a.project))
    print("  open pain entries : %d" % result["open_pain_entries"])
    print("  already filed     : %d" % result["already_filed"])
    print("  candidates        : %d" % result["candidates"])
    print("  window budget     : %d/%d spent, %d remaining (window %ss)"
          % (spent, a.cap, left, a.window_seconds))
    label = "would file" if not apply_ else "filed"
    for e in would if not apply_ else to_file:
        print("  %s            : %s  %s" % (label, e["id"], title_for(e)))
    for f in filed:
        print("  filed             : %s -> ledger item %s (%s)"
              % (f["pain"], f["item"], f["status"]))
    for f in failed:
        print("  FAILED            : %s -> %s" % (f["pain"], f["result"]), file=sys.stderr)
    print("  files             : %d" % len(filed))
    if apply_ and not to_file:
        print("  reason            : %s" % (
            "window budget spent" if remaining == 0 else "no unfiled candidates"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
