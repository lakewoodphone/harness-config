#!/usr/bin/env python3
"""Tests for owner-text-scorecard.py -- no live database, no network, no wake store.

The defect under test is ledger item 733: the 36-item wall stopped sending on 10-15,
but its three rows stayed in the 14-day scorecard window until 10-27. The scorecard
kept naming that retired family as "worst", so the weekly --flag re-woke a defect
that item 720 had already fixed. A retired family and a live one must not score the
same.

Fixture: three old dead rows in one family and one NEW dead row in another. The
new one must be the wake target; the old one must still print with its age and the
date it stops qualifying.

Run with:
    python3 test-owner-text-scorecard.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "owner-text-scorecard.py"

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAYS = 14.0
REPLY_H = 6.0

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED.append(name)
        print(f" FAIL {name}{(' -- ' + detail) if detail else ''}")


def eq(name: str, got, want) -> None:
    check(name, got == want, f"got {got!r}, want {want!r}")


def load_scorecard():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("owner_text_scorecard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sc = load_scorecard()


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def row(sid: str, body: str, at: datetime, direction: str = "outbound",
        status: str = "delivered") -> dict:
    return {"id": abs(hash(sid)) % 100000, "twilio_sid": sid,
            "direction": direction, "status": status, "agent_id": "test",
            "created_at": stamp(at), "body": body}


OLD = "10-13 02:24 UTC  36 items, 26 urgent\n- Your AI text line is not answering your own texts."
NEW = "Can you approve the three invoices waiting on you?"

OLD_FAMILY = sc.family_of(OLD)
NEW_FAMILY = sc.family_of(NEW)


def fixture(include_new: bool = True):
    rows = [
        row("OLD1", OLD, NOW - timedelta(days=12)),
        row("OLD2", OLD, NOW - timedelta(days=11)),
        row("OLD3", OLD, NOW - timedelta(days=10)),
    ]
    if include_new:
        rows.append(row("NEW1", NEW, NOW - timedelta(days=1)))
    rows.append(row("IN1", "ok", NOW - timedelta(hours=1), direction="inbound",
                    status="received"))
    result = sc.judge(rows, NOW - timedelta(days=DAYS), NOW, REPLY_H)
    return result, sc.summarise(result, REPLY_H)


def capture_report(result, summary) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sc.report(result, summary, DAYS, REPLY_H)
    return out.getvalue()


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)

        class Done:
            returncode = 0
            stdout = "flag owner-text:scorecard:test -> filed\n"
            stderr = ""

        return Done()


def main() -> int:
    print("fixture: three old dead rows + one new dead row")
    result, summary = fixture(include_new=True)

    eq("four judged texts", summary["measurable"], 4)
    eq("dead-text rate is 100%", summary["dead_text_rate"], 1.0)

    old = summary["worst_families"][0]
    eq("the old wall is still the largest family", old["family"], OLD_FAMILY)
    eq("the old wall is HISTORICAL", old["live"], False)
    check("the old wall's newest text is 10 days old",
          abs(old["newest_age_h"] - 240.0) < 0.1, repr(old["newest_age_h"]))
    check("the old wall has a retirement date",
          bool(old["retires_below_two_at"]), repr(old))

    live = summary["worst_live_family"]
    check("a live family is named", live is not None)
    eq("the new dead row is the live target", live["family"], NEW_FAMILY)
    eq("the live family is LIVE", live["live"], True)
    eq("one live dead text", summary["live_dead"], 1)
    eq("the historical worst family is the old wall",
       summary["historical_worst_family"]["family"], OLD_FAMILY)

    text = capture_report(result, summary)
    check("report calls the old wall HISTORICAL", "[HISTORICAL]" in text)
    check("report prints the old wall's age", "newest 10.0d old" in text)
    check("report names the new worst LIVE family",
          "worst LIVE family" in text and NEW_FAMILY in text)
    retire = (NOW - timedelta(days=11) + timedelta(days=DAYS)).date().isoformat()
    check("report prints when the old family drops below 2 rows", retire in text, text)

    print()
    print("live breach: --flag must target the new family")
    fake = FakeRun()
    original = sc.subprocess.run
    sc.subprocess.run = fake
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sc.file_flag(summary, DAYS)
    finally:
        sc.subprocess.run = original
    eq("--flag returns 0", rc, 0)
    eq("one wake flag filed", len(fake.calls), 1)
    prompt = ""
    if fake.calls:
        cmd = fake.calls[0]
        prompt = cmd[cmd.index("--prompt") + 1]
    check("prompt names the live family", NEW_FAMILY in prompt, prompt[:200])
    check("prompt says Worst LIVE family", "Worst LIVE family" in prompt)
    check("prompt still contains the bounded instruction", "DO ONE BOUNDED THING" in prompt)

    print()
    print("historical-only breach: --flag must file nothing and name the age-out date")
    result2, summary2 = fixture(include_new=False)
    check("no live family", summary2["worst_live_family"] is None, repr(summary2["worst_live_family"]))
    eq("the historical family is the old wall",
       summary2["historical_worst_family"]["family"], OLD_FAMILY)
    eq("no live dead texts", summary2["live_dead"], 0)
    text2 = capture_report(result2, summary2)
    check("report still prints the historical family with its age",
          "[HISTORICAL]" in text2 and "newest 10.0d old" in text2)
    check("report says there is no live family", "worst LIVE family      none" in text2)

    fake2 = FakeRun()
    sc.subprocess.run = fake2
    try:
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            rc2 = sc.file_flag(summary2, DAYS)
    finally:
        sc.subprocess.run = original
    written = out2.getvalue()
    eq("--flag returns 0", rc2, 0)
    eq("NO wake flag filed for a historical breach", len(fake2.calls), 0)
    check("the refusal says HISTORICAL", "HISTORICAL" in written, written)
    check("the refusal names the old family and its age-out date",
          OLD_FAMILY in written and retire in written, written)

    print()
    if FAILED:
        print("RESULT: FAIL (%d passed, %d failed)" % (PASSED, len(FAILED)))
        for name in FAILED:
            print("  - " + name)
        return 1
    print("RESULT: PASS (%d checks)" % PASSED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
