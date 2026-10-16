"""Tests for /root/bin/premise-check.py - the premise-freshness engine.

Run:  /opt/company/.venv/bin/python -m pytest /root/bin/tests/test_premise_check.py -q
  or: /usr/bin/python3 /root/bin/tests/test_premise_check.py      (bare, no pytest needed)

WHAT THESE TESTS ARE FOR. Two bugs in this engine's first hour were worse than having no engine:
a loose flag pattern read the prose "6.625 percent = 1,700.76" as a flag named PERCENT, and a
merchant/balance heuristic reported the AI credit balance on a family-tuition row and on a Chase
card row. Both produced a confident, true, IRRELEVANT answer - the failure mode this whole system
exists to remove. So most of what follows pins the SHAPE rules, not the happy path.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("premise_check", "/root/bin/premise-check.py")
pc = importlib.util.module_from_spec(_spec)
sys.modules["premise_check"] = pc
_spec.loader.exec_module(pc)

USING_PYTEST = "pytest" in sys.modules
if not USING_PYTEST:
    import types
    pytest = types.SimpleNamespace(raises=lambda *a, **k: __import__("contextlib").nullcontext(),
                                   mark=types.SimpleNamespace(parametrize=lambda *a, **k: (lambda f: f)))


def row(q, c=""):
    return {"id": 1, "question": q, "context": c, "blocks": "", "recommendation": "",
            "options_json": ""}


# ------------------------------------------------------------------ the flag shape rules
def test_prose_with_a_bare_word_and_a_number_is_not_a_flag():
    """The exact string that produced a false 'changed' on row 465."""
    v, d, *_ = pc.run_probe("flag", row("tax at 6.625 percent = 1,700.76 on the quarter"))
    assert v == "unprobed", (v, d)


def test_a_capitalised_settings_name_is_not_a_flag():
    """The exact string that produced a false 'changed' on row 448."""
    v, d, *_ = pc.run_probe("flag", row("MemoryHigh = 12884901888 and MemoryMax = infinity"))
    assert v == "unprobed", (v, d)


def test_a_real_flag_citation_is_read():
    v, d, *_ = pc.run_probe("flag", row("GOOGLE_VOICE_SECRETARY_ENABLED=false was set"))
    assert v in ("fresh", "changed")
    assert "GOOGLE_VOICE_SECRETARY_ENABLED" in d


def test_a_partial_number_is_not_a_flag_value():
    v, d, *_ = pc.run_probe("flag", row("SOME_FLAG=12 is set"))
    assert v == "unprobed", (v, d)


# ------------------------------------------------------------------ the elapsed shape rule
def test_elapsed_recomputes_a_stated_day_count():
    """The #492 shape: correct when filed, wrong every day after."""
    due = (dt.date.today() - dt.timedelta(days=100)).isoformat()
    v, d, *_ = pc.run_probe("elapsed", row(f"the return was due {due} and is 75 days late"))
    assert v == "changed", (v, d)
    assert "100" in d and "75" in d


def test_elapsed_agrees_when_the_count_is_right():
    due = (dt.date.today() - dt.timedelta(days=75)).isoformat()
    v, d, *_ = pc.run_probe("elapsed", row(f"due {due} and is 75 days late"))
    assert v == "fresh", (v, d)


def test_elapsed_needs_both_a_date_and_a_count():
    # Call the PROBE, not run_probe: run_probe deliberately turns a probe's None ("this probe
    # does not apply") into the verdict 'unprobed', so asserting None against run_probe would be
    # asserting the wrong function's contract.
    probe = pc.PROBES["elapsed"][0]
    assert probe(row("this is 75 days late")) is None
    assert probe(row("due 2026-07-30 with no count")) is None
    assert probe(row("due 2026-07-30 and 75 days late")) is not None


# ------------------------------------------------------------------ the deadline shape rule
def test_deadline_reports_days_remaining():
    soon = (dt.date.today() + dt.timedelta(days=4)).isoformat()
    v, d, *_ = pc.run_probe("deadline", row(f"form ST-50 is due {soon}"))
    assert v == "fresh" and "in 4 day(s)" in d, d


def test_deadline_reports_overdue():
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    v, d, *_ = pc.run_probe("deadline", row(f"the return was due {past}"))
    assert "3 day(s) OVERDUE" in d, d


# ------------------------------------------------------------------ the auto/explicit split
def test_external_lookup_probes_do_not_fire_automatically():
    """A heuristic that answers a neighbouring question looks like evidence and is not."""
    for name in ("provider", "merchant", "balance", "repo-citation", "flag"):
        assert pc.PROBES[name][2] is False, name
    for name in ("elapsed", "deadline"):
        assert pc.PROBES[name][2] is True, name


def test_an_explicit_tag_fires_an_external_probe():
    r = row("the balance is low", "please re-check [probe:balance] before acting")
    assert "balance" in pc.match_probes(r)


def test_a_tilde_row_matches_nothing_automatically():
    """A family tuition balance must NOT be measured by the AI-credit balance probe."""
    r = row("The Fall 2026 Felician balance is 5,758 after aid. Who owns paying it.")
    assert pc.match_probes(r) == [], pc.match_probes(r)


def test_prose_mentioning_stripe_does_not_reach_the_merchant_probe():
    """Row 465's real miss: it matched 'stripe' and reported Stripe's last charge."""
    r = row("Stripe card charges 20,161.17 less refunds; tax due 2026-10-20")
    assert "merchant" not in pc.match_probes(r)


def test_a_recurring_charge_row_does_match_the_merchant_probe_when_tagged():
    r = row("T-Mobile is still billing 85 a month", "[probe:merchant]")
    assert "merchant" in pc.match_probes(r)


# ------------------------------------------------------------------ verdict semantics
def test_not_found_is_unknown_never_changed():
    """Absence from the repositories a checker can see is not proof a citation is wrong."""
    r = row("see commit 0000000deadbeef and docs/nonexistent/path-that-is-not-real.md")
    v, d, *_ = pc.run_probe("repo-citation", r)
    assert v in ("unknown", "fresh"), (v, d)
    assert v != "changed"


def test_check_row_returns_a_verdict_in_the_allowed_set():
    v, d, budget, probe = pc.check_row(row("nothing in particular here"))
    assert v in pc.VERDICTS
    assert isinstance(budget, int)


def test_an_unknown_probe_name_in_a_tag_is_ignored():
    r = row("something", "[probe:not-a-real-probe] tax due 2026-12-01")
    assert "not-a-real-probe" not in pc.match_probes(r)


def test_every_probe_never_raises_on_a_hostile_row():
    hostile = {"id": 1, "question": None, "context": None, "blocks": None,
               "recommendation": None, "options_json": None}
    for name in pc.PROBE_ORDER:
        v, d, *_ = pc.run_probe(name, hostile)
        assert v in pc.VERDICTS, (name, v)


if __name__ == "__main__":
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("ok   %s" % k)
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print("FAIL %s: %r" % (k, exc))
    print("\n%d failure(s)" % fails)
    sys.exit(1 if fails else 0)
