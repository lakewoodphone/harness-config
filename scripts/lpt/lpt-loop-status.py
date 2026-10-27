#!/usr/bin/env python3
"""lpt-loop-status - ONE reading of the LPT website's autonomy loop, end to end.

The loop is: a source raises a flag -> wake.py stores it -> wake-dispatch turns it into a
headless DSH session on the desktop -> the session claims a ledger item, does it, and writes
back -> the branch is pushed -> a PR is merged into `test` -> the deploy workflow publishes ->
`main` is promoted -> production serves it. Six links. Until 2026-10-27 no single command
answered "is this loop working", so every session re-derived it, and the day the runner could
not start a session the summary still read `releases today: 44 | failed 7` with no verdict.

Each section is a MEASURED reading with its provenance, and the last section is the only
opinion in the file: the links that are actually broken, named.

READ-ONLY: it opens the wake store and the ledger read-only and only GETs GitHub.
  lpt-loop-status.py [--json]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/root/bin")
import wake  # noqa: E402

LEDGER = "/root/work/work.db"
DISPATCH_LOG = "/root/.sms-inbox/wake-dispatch.log"
SOURCES_LOG = "/root/.sms-inbox/sources.log"
PROJECT = "lpt-website"


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - when).total_seconds() / 3600.0, 2)


def ledger() -> dict:
    out = {"ok": False}
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % LEDGER, uri=True)
        conn.row_factory = sqlite3.Row
        # work_item's status column is `state` (MEASURED 2026-10-27: id, project, title, why,
        # dod, state, priority, owner_row, blocked_on, revisit_at, created_at, updated_at,
        # claimed_by, lease_until, done_at, source). Asking for `status` raised
        # "no such column" and the whole section silently printed nothing.
        rows = list(conn.execute(
            "SELECT id,state,priority,created_at,claimed_by,title FROM work_item WHERE project=?",
            (PROJECT,)))
        out["ok"] = True
        out["by_state"] = {}
        for r in rows:
            out["by_state"][r["state"]] = out["by_state"].get(r["state"], 0) + 1
        todo = [r for r in rows if r["state"] == "todo"]
        blocked = [r for r in rows if r["state"] == "blocked"]
        out["todo"] = len(todo)
        out["blocked"] = len(blocked)
        out["running"] = [{"id": r["id"], "by": r["claimed_by"], "title": r["title"][:70]}
                          for r in rows if r["state"] == "running"]
        oldest = min((r["created_at"] for r in todo if r["created_at"]), default=None)
        out["oldest_todo"] = oldest
        out["oldest_todo_age_h"] = _age_hours(oldest)
        out["done_24h"] = conn.execute(
            "SELECT COUNT(*) FROM work_item WHERE project=? AND state='done' "
            "AND done_at >= datetime('now','-1 day')", (PROJECT,)).fetchone()[0]
        # A todo whose own text names a commit is a claim about a moment; if that commit is
        # older than a day it may already be resolved. These are CANDIDATES to re-measure,
        # never a verdict - the item's own dod is the measurement.
        out["sha_todos"] = [{"id": r["id"], "sha": m.group(1), "title": r["title"][:60]}
                            for r in todo
                            for m in [re.search(r"\b([0-9a-f]{9})\b", r["title"] or "")] if m][:8]
        out["priority_mix"] = {}
        for r in todo:
            out["priority_mix"][str(r["priority"])] = out["priority_mix"].get(str(r["priority"]), 0) + 1
    except Exception as exc:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def wake_section() -> dict:
    conn = wake.connect()
    caps = wake.caps_now()
    today = wake.today_utc()
    releases_today = conn.execute(
        "SELECT COUNT(*) FROM wake WHERE claimed_at >= ?", (today,)).fetchone()[0]
    failed_today = conn.execute(
        "SELECT COUNT(*) FROM wake WHERE finished_at >= ? AND state='failed'", (today,)).fetchone()[0]
    last = conn.execute(
        "SELECT id, subject, finished_at, state FROM wake WHERE finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1").fetchone()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, subject, state, attempts, max_attempts, not_before, claimed_at "
        "FROM wake WHERE subject LIKE ? ORDER BY id DESC LIMIT 6", ("%:" + PROJECT + ":%",))]
    gated = wake._candidates_gated(conn)
    cands = [{"id": r["id"], "subject": r["subject"]} for r in wake._candidates(conn)]
    return {
        "paused": caps["paused"], "in_session": caps["in_session"],
        "releases_today": releases_today, "failed_today": failed_today,
        "max_per_day": caps["max_per_day"], "spend_today_usd": wake.spend_today(conn),
        "max_usd_per_day": caps["max_usd_per_day"],
        "release_block": wake.release_block(conn),
        "last_release_age_min": round((_age_hours(last["finished_at"]) or 0) * 60, 1) if last else None,
        "last_release": dict(last) if last else None,
        "project_rows": rows,
        "claimable": cands,
        "gated": gated,
    }


def dispatch_section() -> dict:
    out = {"last_lines": [], "failed_today": 0, "released_today": 0, "supply_lines": []}
    today = wake.today_utc()
    try:
        with open(DISPATCH_LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        rel = [ln for ln in lines if " released " + today + " wake #" in ln]
        out["released_today"] = len(rel)
        out["failed_today"] = sum(1 for ln in rel if " failed " in ln)
        out["last_lines"] = [ln.rstrip()[:150] for ln in rel[-3:]]
        # WHEN the last good release was, so a failure count can be read as history or as
        # "broken now" - the difference the owner has had to ask for before.
        ok = [ln[:20] for ln in rel if " failed " not in ln]
        bad = [ln[:20] for ln in rel if " failed " in ln]
        out["last_success"] = max(ok) if ok else None
        out["last_failure"] = max(bad) if bad else None
        # A release that never started a session is a fleet fault, not a work fault.
        out["never_started_today"] = sum(
            1 for ln in lines if ln.startswith(today) and "the session never started" in ln)
    except Exception as exc:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    # The supply tick's own verdict for THIS project is the single most useful line in the
    # system when the queue looks empty: "flagged" / "suppressed:attempts" / "quiet: ledger
    # is finished" are three different states that all look like nothing happening.
    try:
        with open(SOURCES_LOG, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip() for ln in fh if PROJECT in ln]
        out["supply_lines"] = lines[-3:]
    except OSError as exc:
        out["supply_error"] = str(exc)
    try:
        out["sources_tick_age_min"] = round(
            (datetime.now(timezone.utc).timestamp() - os.path.getmtime(SOURCES_LOG)) / 60.0, 1)
    except OSError:
        out["sources_tick_age_min"] = None
    return out


def pipeline_section() -> dict:
    """CI heads, the deploy match and the PR queue - shelling out to the two tools that own
    each fact rather than re-deriving them here (one source of truth per thing)."""
    out = {}
    for key, cmd in (("ci", ["/root/bin/lpt-ci-status.py", "--json"]),
                     ("deploy", ["/root/bin/lpt-deploy-status.py", "--live"])):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            out[key + "_rc"] = p.returncode
            out[key] = p.stdout if key == "deploy" else json.loads(p.stdout or "{}")
            if p.returncode != 0:
                out[key + "_stderr"] = (p.stderr or "")[-300:]
        except Exception as exc:  # noqa: BLE001
            out[key + "_error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def verdict(wk: dict, dp: dict, led: dict, pipe: dict) -> list[str]:
    problems = []
    if wk.get("paused"):
        problems.append("the wake store is PAUSED (the pause file exists) - nothing will be released")
    if wk.get("release_block"):
        problems.append("release_block: %s" % wk["release_block"])
    if (wk.get("failed_today") or 0) >= 3 and (wk.get("releases_today") or 0):
        rate = 100.0 * wk["failed_today"] / wk["releases_today"]
        # A failure count with no time attached reads as "it is broken NOW" even when every
        # failure predates the last successful release. Say which it is.
        last_fail = dp.get("last_failure") or ""
        last_done = dp.get("last_success") or ""
        if last_done and last_fail and last_done > last_fail:
            problems.append("%d of %d rows claimed today failed (%.0f%%) - HISTORICAL: the last "
                            "release since then succeeded at %s" % (
                                wk["failed_today"], wk["releases_today"], rate, last_done))
        else:
            problems.append("%d of %d rows claimed today failed (%.0f%%), last failure %s" % (
                wk["failed_today"], wk["releases_today"], rate, last_fail or "?"))
    if dp.get("never_started_today"):
        problems.append("%d release(s) today never started a session (launcher fault, attempts refunded)"
                        % dp["never_started_today"])
    supply = " ".join(dp.get("supply_lines") or [])
    if led.get("ok") and led.get("todo") and not wk.get("claimable"):
        if "suppressed:cooldown" in supply:
            problems.append("supply is GATED, not dead: %d todo item(s) and the project source says "
                            "suppressed:cooldown (the family was released recently and will re-file)"
                            % led["todo"])
        elif "suppressed:" in supply:
            problems.append("supply is SUPPRESSED: %d todo item(s) and the source says %s - this "
                            "needs a human" % (led["todo"], supply[supply.find("suppressed:"):][:90]))
        else:
            problems.append("the ledger holds %d todo item(s) but the wake queue has no claimable "
                            "row and the source named no reason" % led["todo"])
    ci = pipe.get("ci") or {}
    heads = ci.get("heads") or {}
    for br in ("test", "main"):
        st = (heads.get(br) or {}).get("checks", {}).get("state")
        if st and st != "GREEN":
            problems.append("%s head is %s" % (br, st))
    prs = ci.get("prs") or []
    green_waiting = [p for p in prs if p.get("checks") == "GREEN"]
    if green_waiting:
        problems.append("%d green PR(s) waiting to merge into test: %s" % (
            len(green_waiting), ", ".join("#%s" % p["number"] for p in green_waiting)))
    dep = pipe.get("deploy") or ""
    if "MATCH" not in dep and dep:
        problems.append("the deployed test bundle does not MATCH the test head")
    mt, mn = heads.get("test", {}), heads.get("main", {})
    if mt.get("age") and mn.get("age"):
        try:
            # main's age minus test's age: a main head OLDER than test's is how far behind it is.
            behind = float(mn["age"].rstrip("h")) - float(mt["age"].rstrip("h"))
            if behind > 24:
                problems.append("main is %.1fh behind test (D1-3 requires under 24h)" % behind)
        except ValueError:
            pass
    return problems


def main() -> int:
    wk = wake_section()
    dp = dispatch_section()
    led = ledger()
    pipe = pipeline_section()
    probs = verdict(wk, dp, led, pipe)
    data = {"wake": wk, "dispatch": dp, "ledger": led, "pipeline": pipe,
            "problems": probs, "at": wake.now()}
    if "--json" in sys.argv:
        print(json.dumps(data, indent=1, default=str))
        return 0

    print("LPT LOOP STATUS  %s" % data["at"])
    print(" WAKE     release events today %s (failed %s) | rows claimed today %s | spend %s/%s"
          % (dp.get("released_today"), dp.get("failed_today"), wk["releases_today"],
             round(wk["spend_today_usd"] or 0, 3), wk["max_usd_per_day"]))
    print("          paused=%s block=%s last release %s min ago (%s)" % (
        wk["paused"], wk["release_block"], wk["last_release_age_min"],
        (wk["last_release"] or {}).get("subject")))
    print(" SUPPLY   claimable now: %s" % (
        ", ".join("#%s %s" % (c["id"], c["subject"]) for c in wk["claimable"]) or "none"))
    g = wk["gated"] or {}
    print("          gated: not_before=%s night_quiet=%s source_cap=%s selftest=%s" % (
        g.get("not_before"), g.get("night_quiet"), g.get("source_hourly_cap"), g.get("selftest_rows")))
    print("          sources tick %s min ago" % dp.get("sources_tick_age_min"))
    for ln in dp.get("supply_lines") or []:
        print("          " + ln[:148])
    if led.get("ok"):
        print(" LEDGER   %s: todo %s  blocked %s  running %s  done<24h %s  oldest todo %sh" % (
            PROJECT, led["todo"], led["blocked"], len(led["running"] or []),
            led.get("done_24h"), led.get("oldest_todo_age_h")))
        print("          by state: %s | todo by priority: %s" % (
            ", ".join("%s %s" % (k, v) for k, v in sorted(led["by_state"].items())),
            ", ".join("p%s %s" % (k, v) for k, v in sorted(led["priority_mix"].items()))))
        for r in led.get("running") or []:
            print("          RUNNING #%s by %s: %s" % (r["id"], r["by"], r["title"]))
    else:
        print(" LEDGER   UNREADABLE: %s" % led.get("error"))
    ci = pipe.get("ci") or {}
    for br, h in (ci.get("heads") or {}).items():
        print(" CI       %-5s %s %-8s %s  passed %d/%d" % (
            br, h["sha"][:10], h["age"], h["checks"]["state"],
            h["checks"]["passed"], h["checks"]["total"]))
    for p in ci.get("prs") or []:
        print("          PR #%s %-8s %-8s %s" % (p["number"], p["age"], p["checks"], p["title"][:60]))
    dep = (pipe.get("deploy") or "")
    for line in dep.splitlines():
        if any(k in line for k in ("gate", "deployed", "MATCH", "drift", "last deploy")):
            print(" DEPLOY   " + line.strip()[:120])
    print(" PROBLEMS")
    for p in probs:
        print("   - " + p)
    if not probs:
        print("   none - every link measured clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
