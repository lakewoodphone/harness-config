#!/usr/bin/env python3
"""LEDGER SOURCE: file attention-needing CEO-kernel sentinel findings as ledger items, once each.

THE SIGNAL
    The always-on kernel (secratary; cron every 5 min via scripts/run-sentinel.sh) senses the
    outcome of the company's work and reports findings through `python3 -m ck status --json`.
    A finding with needs_attention=true is the machine saying "something is wrong". Before this
    source existed nothing read that verdict into the work ledger: measured 2026-09-30,
    `grep -rln wake.py work.py ~/ceo-kernel/` returned nothing, so the biggest producer of
    "the machine noticed something" had no path to it being fixed (work_item 147).

WHAT IT DOES
    Runs the sentinel and keeps the findings that need attention, then files at most --cap of
    them as ledger items in --project. Reads the sentinel in-process (`ck.sentinel.run_all`) so
    a check name can be handed straight through; `--findings FILE` reads a captured JSON report
    instead (used to plant a condition when proving the path).

WHY A SECOND RUN FILES NONE -- three independent brakes
    1. LEDGER MARKER. Every item this source files carries `[sentinel <check>]` in its title. A
       non-terminal ledger item carrying that marker means the check is already covered and is
       skipped. The ledger is the memory, so losing local state cannot cause a refile. A
       dropped/done item is history, not coverage: the check can file again when it recurs.
    2. work.py's OWN DEDUPE. work.py refuses a second open item with the same title and returns
       the existing id as `already-filed`; this source counts that as covered too.
    3. WINDOW BUDGET. At most --cap items per --window-seconds (default 86400). Filing every
       finding a bad day produces is noise, not supply.

USAGE
    sentinel-supply.py                                     # DRY RUN: show what would be filed
    sentinel-supply.py --apply                             # file at most --cap
    sentinel-supply.py --apply --only model_failover --cap 1
    sentinel-supply.py --findings /tmp/report.json --json

Exit codes: 0 ran (even if it filed nothing) - 2 the sentinel could not be read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KERNEL_DIR = os.environ.get("CEO_KERNEL_DIR", "/home/zabz/ceo-kernel")
WORK = os.environ.get("WORK_CLI", "/home/zabz/bin/work.py")
STATE = Path(os.environ.get(
    "SENTINEL_SUPPLY_STATE", str(Path.home() / ".sentinel-supply" / "filed.json")))
DEFAULT_PROJECT = os.environ.get("SENTINEL_SUPPLY_PROJECT", "housekeeping")
DEFAULT_CAP = int(os.environ.get("SENTINEL_SUPPLY_CAP", "3"))
DEFAULT_WINDOW = int(os.environ.get("SENTINEL_SUPPLY_WINDOW_SECONDS", "86400"))
SOURCE = "sentinel-supply"
TITLE_CAP = 110
MARKER_RE = re.compile(r"\[sentinel\s+([A-Za-z0-9_]+)\]")
# Severity -> ledger priority (1 is most urgent). CRITICAL is what a shift should take first.
PRIORITY = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact(text: str, limit: int = TITLE_CAP) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def load_findings(a: argparse.Namespace) -> list:
    """The sentinel's findings, as plain dicts. Never guesses: a failed read raises."""
    if a.findings:
        raw = json.loads(Path(a.findings).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else (raw.get("findings") or [])
        out = []
        for f in items:
            if not isinstance(f, dict):
                continue
            sev = str(f.get("severity") or "unknown")
            ok = bool(f.get("ok"))
            na = f.get("needs_attention")
            if na is None:
                na = (not ok) and sev in ("critical", "high")
            row = dict(f)
            row.update({
                "check": str(f.get("check") or "?"),
                "severity": sev,
                "ok": ok,
                "needs_attention": bool(na),
                "summary": str(f.get("summary") or ""),
            })
            out.append(row)
        return out

    sys.path.insert(0, KERNEL_DIR)
    from ck import sentinel  # noqa: E402  (path is only known at runtime)

    only = [c.strip() for c in (a.only or "").split(",") if c.strip()] or None
    return [f.to_dict() for f in sentinel.run_all(only=only)]


def ledger_checks(project: str) -> set:
    """Checks already carried by a NON-TERMINAL ledger item -- the ledger's own memory."""
    try:
        p = subprocess.run(
            [sys.executable, WORK, "list", "--project", project, "--limit", "5000", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if p.returncode != 0:
            return set()
        data = json.loads(p.stdout or "[]")
    except Exception:  # noqa: BLE001
        return set()
    rows = data if isinstance(data, list) else (
        data.get("items") or data.get("work_items") or data.get("rows") or [])
    covered = set()
    for r in rows:
        r = r or {}
        if r.get("state") not in (None, "todo", "running", "blocked"):
            continue
        m = MARKER_RE.search(str(r.get("title") or ""))
        if m:
            covered.add(m.group(1))
    return covered


def load_state() -> dict:
    if not STATE.is_file():
        return {"window": {}}
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("WARN: state file %s is not JSON; treating as empty" % STATE, file=sys.stderr)
        return {"window": {}}
    d.setdefault("window", {})
    return d


def save_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE)


def title_for(f: dict) -> str:
    return compact("[sentinel %s] %s" % (f["check"], f["summary"] or f["check"]))


def dod_for(check: str) -> str:
    """Done when that check stops needing attention. Runnable by a later shift as-is."""
    return (
        "cd %s && python3 -m ck status --json | python3 -c "
        "'import json,sys;d=json.load(sys.stdin);"
        "fs=[f for f in d[\"findings\"] if f[\"check\"]==\"%s\"];"
        "print(\"CLEAR\" if fs and not any(f.get(\"needs_attention\") for f in fs) "
        "else \"STILL-FIRING\")'" % (KERNEL_DIR, check))


def file_item(f: dict, project: str, priority: int, note: str) -> dict:
    check = f["check"]
    why = ("CEO-kernel sentinel finding %s (severity %s, read %s): %s"
           % (check, f["severity"], now(), f["summary"]))
    if note:
        why += " | " + note
    p = subprocess.run(
        [sys.executable, WORK, "add", "--project", project,
         "--title", title_for(f), "--dod", dod_for(check), "--why", why,
         "--priority", str(priority), "--source", SOURCE],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    # work.py speaks `<status> {json}` on one line (`item-filed {"id": 219, ...}`), not bare JSON.
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
    ap.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--only", default="",
                    help="comma-separated sentinel check names (default: all)")
    ap.add_argument("--findings", default="",
                    help="read findings from this JSON report instead of running the sentinel")
    ap.add_argument("--note", default="", help="extra text recorded in each item's why")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    apply_ = a.apply and not a.dry_run

    try:
        findings = load_findings(a)
    except Exception as exc:  # noqa: BLE001
        print("sentinel-supply: cannot read the sentinel: %s" % exc, file=sys.stderr)
        return 2

    attention = [f for f in findings if f.get("needs_attention")]
    covered = ledger_checks(a.project)

    candidates, skipped, seen = [], [], set()
    for f in attention:
        c = f["check"]
        if c in covered:
            skipped.append((c, "already-on-the-ledger"))
        elif c in seen:
            skipped.append((c, "same-check-this-run"))
        else:
            seen.add(c)
            candidates.append(f)

    st = load_state()
    w = st.get("window") or {}
    started = float(w.get("started_epoch") or 0.0)
    spent = int(w.get("filed") or 0)
    if a.window_seconds and (time.time() - started) >= a.window_seconds:
        started, spent = time.time(), 0
    remaining = max(0, a.cap - spent)
    to_file = candidates[:remaining] if apply_ else []

    filed, failed = [], []
    for f in to_file:
        res = file_item(f, a.project, PRIORITY.get(f["severity"], 4), a.note)
        status = res.get("status")
        if status in ("item-filed", "already-filed"):
            filed.append({"check": f["check"], "item": res.get("id"), "status": status})
            covered.add(f["check"])
            spent += 1
            st["window"] = {"started_epoch": started, "filed": spent}
            save_state(st)
        else:
            failed.append({"check": f["check"], "result": res})

    result = {
        "mode": "apply" if apply_ else "dry-run", "at": now(), "source": SOURCE,
        "project": a.project, "findings": len(findings), "attention": len(attention),
        "covered_on_ledger": sorted(covered), "candidates": len(candidates),
        "window_cap": a.cap, "window_spent": spent, "window_remaining": max(0, a.cap - spent),
        "filed": filed, "failed": failed,
        "would_file": [{"check": f["check"], "title": title_for(f)} for f in candidates[:remaining]],
        "skipped": [{"check": c, "why": y} for c, y in skipped],
    }
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print("sentinel-supply %s mode=%s project=%s" % (result["at"], result["mode"], a.project))
        print("  findings read     : %d  (attention: %d)" % (len(findings), len(attention)))
        print("  already on ledger : %s" % (", ".join(sorted(covered)) or "-"))
        print("  candidates        : %d" % len(candidates))
        print("  window budget     : %d/%d spent, %d remaining (window %ss)"
              % (spent, a.cap, result["window_remaining"], a.window_seconds))
        label = "would file" if not apply_ else "filed"
        for f in (candidates[:remaining] if not apply_ else to_file):
            print("  %s        : %s -> %s" % (label, f["check"], title_for(f)))
        for x in filed:
            print("  filed             : %s -> ledger item %s (%s)"
                  % (x["check"], x["item"], x["status"]))
        for x in failed:
            print("  FAILED            : %s -> %s" % (x["check"], x["result"]), file=sys.stderr)
        print("  files             : %d" % len(filed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
