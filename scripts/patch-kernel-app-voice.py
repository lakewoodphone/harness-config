"""A kernel check for the thing that hid everything: can the app be heard at all?

Measured 2026-09-15: the service's root logger sat at **WARNING with zero handlers**,
so every `logger.info` in the application was discarded and WARNING+ reached the
journal only through Python's `lastResort` handler -- bare message, no level, no
module, no sub-second time. The only reason INFO narration had *ever* appeared was
that Twilio's HTTP client happened to call `logging.basicConfig()` first in that
process, which is how a lifecycle sweep that never stopped running came to look dead
for an hour and cost an hour of inference.

`app/logging_setup.py` fixes the cause. This check is what notices if the cause
returns: it reads the service journal and looks for this application's own formatted
INFO lines. Three properties matter more than the threshold:

  * an unreadable journal is a **refusal** (UNKNOWN), never a pass -- "empty" and
    "fine" are different answers;
  * a service that is not running is not called silent (UNKNOWN with the state);
  * it reports the newest formatted line's timestamp, so a green reading carries
    provenance instead of a bare count.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

ANCHOR = '''ALL_CHECKS = ('''

CHECK = '''def check_app_voice(
    unit: str = "secretary-api",
    window_minutes: float = 30.0,
) -> Finding:
    """Is the application still saying what it is doing, in its own format?

    See app/logging_setup.py for what this is guarding. A zero here means the service
    is running but its narration has stopped, which is either a logging regression (the
    logger reconfigured out from under it) or a wedged loop -- both worth waking for,
    and neither visible from the database.
    """
    def _run(argv: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    try:
        state = _run(["systemctl", "is-active", unit], timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return Finding(
            check="app_voice",
            severity=UNKNOWN,
            ok=False,
            summary=f"cannot ask systemd about {unit}: {type(exc).__name__}: {exc}",
        )

    if state != "active":
        return Finding(
            check="app_voice",
            severity=UNKNOWN,
            ok=False,
            summary=f"{unit} is {state or 'unknown'}, so its voice cannot be assessed",
            metrics={"unit": unit, "active_state": state},
        )

    window = f"-{int(window_minutes)} min"
    try:
        proc = _run(["journalctl", "-u", unit, "--since", window, "-o", "cat", "--no-pager"])
    except (OSError, subprocess.SubprocessError) as exc:
        return Finding(
            check="app_voice",
            severity=UNKNOWN,
            ok=False,
            summary=f"cannot read the journal for {unit}: {type(exc).__name__}: {exc}",
        )

    if proc.returncode != 0:
        return Finding(
            check="app_voice",
            severity=UNKNOWN,
            ok=False,
            summary=f"journalctl failed ({proc.returncode}): {(proc.stderr or '').strip()[:200]}",
        )

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        # Empty within the window could be silence or a permissions problem; the only
        # honest reading is that this check does not know. (It is NOT a pass.)
        return Finding(
            check="app_voice",
            severity=UNKNOWN,
            ok=False,
            summary=(
                f"journalctl returned nothing for {unit} in the last "
                f"{window_minutes:.0f} min -- silence or an unreadable journal, "
                "and this check cannot tell them apart"
            ),
            metrics={"unit": unit, "lines": 0, "window_minutes": window_minutes},
        )

    # The application's own format, app/logging_setup.py:
    #   <iso timestamp> INFO <logger name>: <message>
    app_info = [
        ln for ln in lines
        if " INFO " in ln and " app." in ln and ":" in ln.split(" INFO ", 1)[-1]
    ]
    newest = app_info[-1][:19] if app_info else None
    metrics = {
        "unit": unit,
        "window_minutes": window_minutes,
        "lines_total": len(lines),
        "app_info_lines": len(app_info),
        "newest_app_info_at": newest,
    }

    if not app_info:
        return Finding(
            check="app_voice",
            severity=HIGH,
            ok=False,
            summary=(
                f"{unit} is running and logged {len(lines)} line(s) in the last "
                f"{window_minutes:.0f} min, but none in the application's own format "
                "-- its INFO narration is suppressed (root logger level or handlers), "
                "so nothing it says can be read"
            ),
            metrics=metrics,
        )

    return Finding(
        check="app_voice",
        severity=INFO,
        ok=True,
        summary=(
            f"the application is audible: {len(app_info)} of {len(lines)} journal "
            f"line(s) in the last {window_minutes:.0f} min carry its own INFO format "
            f"(newest {newest})"
        ),
        metrics=metrics,
    )


ALL_CHECKS = ('''

REGISTRY_ANCHOR = '''    ("comms_freshness", check_comms_freshness),
)'''
REGISTRY_REPLACE = '''    ("comms_freshness", check_comms_freshness),
    ("app_voice", check_app_voice),
)'''

EDITS = [
    (ANCHOR, CHECK, "sentinel.py: add check_app_voice"),
    (REGISTRY_ANCHOR, REGISTRY_REPLACE, "sentinel.py: register it"),
]


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if "check_app_voice" in text and new != CHECK and old == REGISTRY_ANCHOR:
            pass
        if new in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)
        print(f"planned  {label}")
    SENT.write_text(text, encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
