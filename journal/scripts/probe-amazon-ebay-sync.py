"""Do the Amazon and eBay syncs actually work once unblocked?

The cooldown fix lets them probe again, but that only helps if the underlying sync
works. Neither has run since 2026-09-06 (42 consecutive failures each), so their
real error has been invisible -- exactly as boa_sync's was, where the answer turned
out to be `npm error Missing script: "boa:download"` rather than anything about the
bank.

This calls each service's own entry point, which is what the 04:00 / 04:15 schedule
does. Read-only in intent: it prints status and message only, and never a
credential.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

TARGETS = [
    ("amazon_sync", "app.services.amazon_bank_service", "sync_amazon_transactions"),
    ("ebay_sync", "app.services.ebay_bank_service", "sync_ebay_transactions"),
]


def run_one(name: str, module: str, func: str) -> None:
    print(f"=== {name} ===")
    try:
        mod = __import__(module, fromlist=[func])
    except Exception as exc:  # noqa: BLE001
        print(f"  import failed: {type(exc).__name__}: {exc}")
        return
    fn = getattr(mod, func, None)
    if fn is None:
        print(f"  {module}.{func} absent")
        return
    try:
        result = asyncio.run(asyncio.wait_for(fn(), timeout=240))
    except asyncio.TimeoutError:
        print("  timed out after 240s (browser automation hung)")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"  raised {type(exc).__name__}: {str(exc)[:300]}")
        return
    if not isinstance(result, dict):
        print(f"  unexpected type {type(result).__name__}: {str(result)[:200]}")
        return
    for key in ("status", "message", "transactions_ingested", "accounts",
                "download_rc", "ingest_rc"):
        if key in result:
            print(f"  {key}: {str(result[key])[:300]}")


if __name__ == "__main__":
    for name, module, func in TARGETS:
        run_one(name, module, func)
    print("\n(no credential is printed by this probe, by design)")
