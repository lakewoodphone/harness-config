"""What does the Bank of America sync actually return when it is allowed to run?

Read-only in intent: it calls the system's own sync function, which is exactly what
the 03:00 schedule does. It writes nothing itself; the sync may ingest transactions
if it succeeds, which is its normal documented behaviour and six weeks overdue.

Why: the breaker wedged this sync on 2026-07-21 and it has not been attempted once
in 55 days, so its real failure has never been visible. `_maybe_run_boa_sync` treats
`needs_mfa` as a distinct outcome and the code comments say that alert is suppressed
("Owner SMS suppressed per 2026-07-02"), which would make an MFA wall another silent
failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback

sys.path.insert(0, ".")


def main() -> int:
    from app.services.boa_bank_service import sync_boa_transactions

    try:
        result = asyncio.run(asyncio.wait_for(sync_boa_transactions(), timeout=240))
    except asyncio.TimeoutError:
        print("RESULT: timed out after 240s (browser automation hung)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"RESULT: raised {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3)
        return 0

    if not isinstance(result, dict):
        print(f"RESULT: unexpected type {type(result).__name__}: {str(result)[:300]}")
        return 0

    print("RESULT keys:", sorted(result.keys()))
    for key in ("status", "message", "transactions_ingested", "accounts", "error"):
        if key in result:
            print(f"  {key}: {str(result[key])[:400]}")
    print("\nfull (truncated):")
    print(json.dumps(result, default=str)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
