"""The endpoint that runs a subsystem on demand must know the syncs (P149).

Measured 2026-09-15: `POST /autopilot/subsystems/{name}/run-once` advertised fourteen
subsystems and none of them was a finance/browser sync, so the subsystems most likely to
need a human -- an expired session, an MFA wall -- could not be exercised by the endpoint
built for exercising subsystems. Two attempts returned `unknown_subsystem`, and the
sync-alert clear hook had to be verified through `POST /finance/{amazon,ebay}/sync` instead.

The first fix was incomplete in an instructive way: clearing the in-memory day guard was not
enough, because each sync also checks a *persisted* `last_ran_at` and the scheduled hour. The
force now clears all three and restores them when the run did not happen.
"""

from __future__ import annotations

import pathlib
import re

AUTO = pathlib.Path(__file__).resolve().parents[1] / "app" / "autopilot.py"
SRC = AUTO.read_text(encoding="utf-8")


def test_the_dispatch_table_covers_every_finance_sync():
    table = SRC.split("def _finance_sync_specs", 1)[1].split("def _run_finance_sync_now", 1)[0]
    names = set(re.findall(r'"([a-z]+_sync)": \(', table))
    assert names == {
        "boa_sync",
        "chase_sync",
        "amex_sync",
        "paypal_sync",
        "amazon_sync",
        "ebay_sync",
        "plaid_sync",
        "receipt_sync",
    }, names


def test_every_sync_in_the_table_is_a_real_method_with_a_real_guard():
    table = SRC.split("def _finance_sync_specs", 1)[1].split("def _run_finance_sync_now", 1)[0]
    for guard, method, flag in re.findall(r'\("(_[a-z_]+)",\s*"(_[a-z_]+)",\s*"([a-z_]+)"\)', table):
        assert f"def {method}(" in SRC, method
        assert f"self.{guard}" in SRC, guard
        assert flag in SRC, flag


def test_the_syncs_are_advertised_and_dispatched():
    assert "elif subsystem in self._finance_sync_specs():" in SRC
    assert "*sorted(self._finance_sync_specs())," in SRC, (
        "the known list must be derived from the same table, or the two drift apart"
    )


def test_a_manual_run_clears_all_three_gates_and_restores_them():
    body = SRC.split("def _run_finance_sync_now", 1)[1].split("def run_subsystem_once", 1)[0]
    # 1. the in-memory day guard
    assert "setattr(self, guard_attr, None)" in body
    # 2. the persisted marker the restart-safe guard reads
    assert 'self._subsystem_health.setdefault(name, {})["last_ran_at"] = None' in body
    # 3. the scheduled hour, and the restore that keeps the daily schedule intact
    assert 'setattr(self._settings, time_flag, "00:00")' in body
    assert "setattr(self._settings, time_flag, before_time)" in body
    assert "self._subsystem_health[name] = entry_before" in body


def test_a_refusal_says_which_gate_refused():
    """Disabled and breaker-tripped must be reported, never a silent no-op."""
    body = SRC.split("def _run_finance_sync_now", 1)[1].split("def run_subsystem_once", 1)[0]
    assert '"error": "disabled"' in body
    assert '"error": "breaker_tripped"' in body
    assert '"error": "unknown_subsystem"' in body
