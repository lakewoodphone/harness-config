"""The endpoint built to run a subsystem on demand could not run the syncs (P149).

Measured 2026-09-15: `POST /autopilot/subsystems/{name}/run-once` advertises fourteen
subsystems, and none of them is a finance/browser sync. So the subsystems most likely to
need a human -- an expired session, an MFA wall -- were exactly the ones it could not
exercise, and the sync-alert clear hook had to be verified through a different route
(`POST /finance/{amazon,ebay}/sync`). Two attempts through the endpoint returned
`unknown_subsystem`.

This adds the eight syncs to the dispatch, using one table that also feeds the advertised
`known` list so the two cannot drift. A manual run bypasses only the once-a-day guard (an
in-memory `*_sync_run_date` attribute -- clearing it is the state the loop wakes up in on a
new day) and still respects the enable flag and the failure breaker; each reason for *not*
running is reported, because a manual trigger that silently does nothing is worse than one
that says why.
"""

from __future__ import annotations

import pathlib
import sys

AUTO = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "autopilot.py"

METHODS_ANCHOR = "    def run_subsystem_once("

METHODS = '''    def _finance_sync_specs(self) -> dict[str, tuple[str, str, str]]:
        """name -> (day-guard attribute, controller method, enable flag).

        The eight finance/browser syncs share one shape: a per-calendar-day guard, an
        enable flag, a failure breaker, and a `_record_subsystem` call at the end. One
        table serves both the manual dispatch and the advertised `known` list.
        """
        return {
            "boa_sync": (
                "_boa_sync_run_date",
                "_maybe_sync_boa_transactions",
                "boa_sync_enabled",
            ),
            "chase_sync": (
                "_chase_sync_run_date",
                "_maybe_sync_chase_transactions",
                "chase_sync_enabled",
            ),
            "amex_sync": (
                "_amex_sync_run_date",
                "_maybe_sync_amex_transactions",
                "amex_sync_enabled",
            ),
            "paypal_sync": (
                "_paypal_sync_run_date",
                "_maybe_sync_paypal_transactions",
                "paypal_sync_enabled",
            ),
            "amazon_sync": (
                "_amazon_sync_run_date",
                "_maybe_sync_amazon_transactions",
                "amazon_sync_enabled",
            ),
            "ebay_sync": (
                "_ebay_sync_run_date",
                "_maybe_sync_ebay_transactions",
                "ebay_sync_enabled",
            ),
            "plaid_sync": (
                "_plaid_sync_run_date",
                "_maybe_sync_plaid_transactions",
                "plaid_sync_enabled",
            ),
            "receipt_sync": (
                "_receipt_sync_run_date",
                "_maybe_sync_receipts",
                "receipt_sync_enabled",
            ),
        }

    def _run_finance_sync_now(self, name: str) -> dict[str, Any]:
        """Run one finance sync now, bypassing only its once-a-day guard.

        P149: the syncs were absent from this endpoint's dispatch, so a hook on them could
        not be verified on demand. The guard is an in-memory `*_sync_run_date` attribute,
        so clearing it is exactly the state the loop wakes up in on a new day; the enable
        flag and the failure breaker still apply, and every reason for *not* running is
        reported rather than returned as a silent success.
        """
        spec = self._finance_sync_specs().get(str(name or "").strip().lower())
        if spec is None:
            return {"ok": False, "error": "unknown_subsystem", "subsystem": name}
        guard_attr, method_name, flag = spec
        if not bool(getattr(self._settings, flag, True)):
            return {
                "ok": False,
                "subsystem": name,
                "error": "disabled",
                "detail": "%s is False, so this sync will not run" % flag,
            }
        if self._finance_sync_blocked_by_breaker(name):
            return {
                "ok": False,
                "subsystem": name,
                "error": "breaker_tripped",
                "detail": "the sync breaker is tripped; it clears on its own cooldown",
            }
        before_guard = getattr(self, guard_attr, None)
        before_ran = (self._subsystem_health.get(name) or {}).get("last_ran_at")
        setattr(self, guard_attr, None)
        try:
            getattr(self, method_name)()
        finally:
            if getattr(self, guard_attr, None) is None:
                # It did not run (disabled path inside the method, or nothing to do): leave
                # the day guard exactly as it was so a manual attempt cannot extend the day.
                setattr(self, guard_attr, before_guard)
        entry = self._subsystem_health.get(name) or {}
        ran = entry.get("last_ran_at") != before_ran
        return {
            "ok": bool(ran and entry.get("last_status") == "ok"),
            "subsystem": name,
            "ran": bool(ran),
            "status": entry.get("last_status"),
            "detail": str(entry.get("last_detail") or entry.get("last_error") or ""),
        }

    def run_subsystem_once('''

BRANCH_ANCHOR = '''            elif subsystem == "drn_reconciliation_monitor":
                self._maybe_run_drn_reconciliation_monitor(force=True)
                ok = True
                detail = "DRN reconciliation monitor heartbeat forced"

            else:'''

BRANCH = '''            elif subsystem == "drn_reconciliation_monitor":
                self._maybe_run_drn_reconciliation_monitor(force=True)
                ok = True
                detail = "DRN reconciliation monitor heartbeat forced"

            elif subsystem in self._finance_sync_specs():
                # P149: the syncs were missing from this dispatch, so the subsystems most
                # likely to need a human could not be exercised by the endpoint built for
                # exercising subsystems.
                result = self._run_finance_sync_now(subsystem)
                return {
                    "ok": bool(result.get("ok")),
                    "subsystem": subsystem,
                    "reason": reason,
                    **result,
                }

            else:'''

KNOWN_ANCHOR = '''                        "drn_reconciliation_monitor",
                    ],'''

KNOWN_REPLACE = '''                        "drn_reconciliation_monitor",
                        *sorted(self._finance_sync_specs()),
                    ],'''

EDITS = [
    (METHODS_ANCHOR, METHODS, "autopilot: the sync dispatch table and the on-demand runner"),
    (BRANCH_ANCHOR, BRANCH, "autopilot: dispatch the syncs"),
    (KNOWN_ANCHOR, KNOWN_REPLACE, "autopilot: advertise them"),
]


def main() -> int:
    text = AUTO.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if new in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)
        print(f"planned  {label}")
    AUTO.write_text(text, encoding="utf-8")
    print(f"WROTE {AUTO}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
