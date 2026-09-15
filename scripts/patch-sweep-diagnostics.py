"""Make the lifecycle sweep's silent failures audible.

Measured 2026-09-15: the service logged "Lifecycle sweep complete" 39 times in
three hours, the last at 13:30:09, and then never again -- across four restarts.
The loop was demonstrably alive and passing the call site: financial_alert_sweep
(autopilot.py:6017) recorded 14:08:10 and activity_sync (autopilot.py:6061)
recorded 14:08:38, with `_maybe_run_lifecycle_sweep()` at 6023 in between. Every
gate is open (lifecycle_sweep_enabled=True, interval=120, the monotonic gate
starts at 0.0 on a restart so the first tick must pass).

So the method was called and did nothing visible, and the reason was invisible in
exactly the way this session has already been bitten three times:

    try:
        from app.services.lifecycle_sweep import run_lifecycle_sweep
        ...                                     # logs "Lifecycle sweep complete"
    except ImportError:
        pass                                    # <- says nothing at all
    except Exception as exc:
        logger.debug("Lifecycle sweep error: %s", exc)   # <- not in the journal

A failing import and a failing sweep both look exactly like a healthy one from
outside. This patch is not cosmetic: it is the diagnostic, and the silent
swallow is the defect. Nothing here changes what the sweep does.

While lifecycle hygiene is quietly off, so are: stale step release, retry
scheduling, blocked-step reopen, goal rollup, stuck detection, draft expiry,
approval expiry, stale task close -- and the owner-message shelf life added this
session, which is the whole reason the badges stopped lying.
"""

from __future__ import annotations

import pathlib
import sys

AUTO = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "autopilot.py"

SWEEP_IMPORT_ANCHOR = '''            from app.services.lifecycle_sweep import (
                run_lifecycle_sweep,
            )

            summary = run_lifecycle_sweep(self._settings.database_url)
            if any(v > 0 for v in summary.values()):
                logger.info("Lifecycle sweep: %s", summary)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("Lifecycle sweep error: %s", exc)'''

SWEEP_IMPORT_REPLACE = '''            from app.services.lifecycle_sweep import (
                run_lifecycle_sweep,
            )

            summary = run_lifecycle_sweep(self._settings.database_url)
            if any(v > 0 for v in summary.values()):
                logger.info("Lifecycle sweep: %s", summary)
        except ImportError as exc:
            # Never `pass` here. Measured 2026-09-15: the sweep's own log line stopped
            # appearing for 40 minutes across four restarts while the loop kept running,
            # and a failing import was one of the two ways that could look like silence.
            logger.warning("Lifecycle sweep unavailable (import failed): %s", exc)
        except Exception as exc:  # noqa: BLE001
            # WARNING, not DEBUG: an error here disables every lifecycle phase at once
            # (stale claims, retries, rollup, draft expiry, the owner-message shelf life),
            # so it must be visible from the journal, not from a debug flag.
            logger.warning(
                "Lifecycle sweep failed: %s: %s", type(exc).__name__, exc
            )'''

STALE_IMPORT_ANCHOR = '''            if stale_summary.get("skipped"):
                pass  # too soon, normal
            elif any(v for k, v in stale_summary.items() if k != "skipped"):
                logger.info("Staleness sweep: %s", stale_summary)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("Staleness sweep error: %s", exc)'''

STALE_IMPORT_REPLACE = '''            if stale_summary.get("skipped"):
                pass  # too soon, normal
            elif any(v for k, v in stale_summary.items() if k != "skipped"):
                logger.info("Staleness sweep: %s", stale_summary)
        except ImportError as exc:
            logger.warning("Staleness sweep unavailable (import failed): %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Staleness sweep failed: %s: %s", type(exc).__name__, exc
            )'''

EDITS = [
    (SWEEP_IMPORT_ANCHOR, SWEEP_IMPORT_REPLACE, "lifecycle sweep: speak when it cannot run"),
    (STALE_IMPORT_ANCHOR, STALE_IMPORT_REPLACE, "staleness sweep: speak when it cannot run"),
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
        text = text.replace(old, new, 1)  # accumulate on a running copy
        print(f"planned  {label}")
    AUTO.write_text(text, encoding="utf-8")
    print(f"WROTE {AUTO}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
