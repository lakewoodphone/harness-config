"""Does the cooldown un-wedge the real, persisted breaker state?

The behavioural test passes on synthetic entries. This one runs the deployed
predicate against the authority's actual `data/autopilot_state.json`, which is what
decides whether tomorrow's 03:00 run happens. Read-only: it reads state and calls
the predicate; it writes nothing and runs no sync.

Context: before the fix these four entries were permanent locks --
boa_sync consec=114 with last_ran 2026-07-21 (55 days), amazon_sync and ebay_sync
42 each since 09-06, spending_report 38 since 09-03.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, ".")

from app.autopilot import AutopilotController  # noqa: E402

STATE = pathlib.Path("data/autopilot_state.json")
SYNCS = ("boa_sync", "amazon_sync", "ebay_sync", "spending_report")


class _Stub:
    """Just enough of the controller for the predicate, wired to real state."""

    def __init__(self, subsystem_health: dict) -> None:
        self._subsystem_health = subsystem_health
        self._SYNC_BREAKER_THRESHOLD = 3
        self._SYNC_BREAKER_COOLDOWN_MIN = 360
        self._sync_breaker_alerted = set()

    def _enqueue_owner_nudge(self, name: str, detail: str) -> None:  # noqa: D401
        print(f"    (would nudge the owner about {name})")


def main() -> int:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    health = state.get("subsystem_health", {})
    print(f"state file: {STATE}  ({len(health)} subsystems)\n")
    print(f"{'sync':<18} {'consec':>7} {'last attempt':<34} {'blocked now?':>13}")
    unwedged = 0
    for name in SYNCS:
        entry = health.get(name) or {}
        stub = _Stub({name: entry})
        blocked = AutopilotController._finance_sync_blocked_by_breaker(stub, name)
        if not blocked:
            unwedged += 1
        print(
            f"{name:<18} {str(entry.get('consecutive_failures', '-')):>7} "
            f"{str(entry.get('last_ran_at', '-')):<34} "
            f"{('BLOCKED' if blocked else 'will probe'):>13}"
        )
    print(f"\n{unwedged} of {len(SYNCS)} would now get a probe attempt.")
    print("Before the cooldown fix, all four were permanent locks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
