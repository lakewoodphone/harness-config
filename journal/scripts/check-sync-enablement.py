"""Are the four dead syncs blocked by the breaker, or disabled by config?

This decides whether the round-11 cooldown fix actually restores anything. The
enabled check runs BEFORE the breaker check in every one of these subsystems, so a
subsystem disabled in config never reaches the breaker at all -- and the cooldown
would be a correct fix for a latent bug that is not the cause of the outage.

Read-only: prints the live settings and the order of the guards.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402

PAIRS = [
    ("boa_sync", "boa_sync_enabled"),
    ("amazon_sync", "amazon_sync_enabled"),
    ("ebay_sync", "ebay_sync_enabled"),
    ("spending_report", "spending_report_enabled"),
]


def main() -> int:
    print("== live settings ==")
    for subsystem, setting in PAIRS:
        value = getattr(settings, setting, "<attribute absent>")
        print(f"  {subsystem:<18} {setting:<28} = {value!r}")

    print("\n== .env overrides (KEY NAMES ONLY -- never values) ==")
    # This section printed whole matching lines on its first run, which included
    # BOA_PASSWORD in clear, and this session's transcript is ingested into the
    # authority's session archive. Never print a value from a secrets file; a
    # diagnostic that answers a boolean question must not echo credentials.
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if re.match(r"^(BOA|AMAZON|EBAY|SPENDING_REPORT)", key):
                print(f"  {key} is set")
    else:
        print("  (no .env)")

    print("\n== guard order in the autopilot (enabled first, then breaker) ==")
    src = Path("app/autopilot.py").read_text(encoding="utf-8", errors="replace").split("\n")
    for subsystem, setting in PAIRS:
        # find the first line mentioning <subsystem>_enabled, print its neighbourhood
        for i, line in enumerate(src):
            if setting in line and "getattr" in line:
                window = src[i: i + 14]
                order = []
                for w in window:
                    if "enabled" in w and "getattr" in w:
                        order.append("enabled-check")
                    if "_finance_sync_blocked_by_breaker" in w:
                        order.append("BREAKER-CHECK")
                    if "return" in w and not order:
                        pass
                print(f"  {subsystem:<18} {' -> '.join(order) if order else 'order not found'}")
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
