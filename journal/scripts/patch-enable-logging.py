"""Turn the application's logging on, before anything in the package logs.

Inserted at app/main.py:47, immediately before the first `from app.` import, so every
app module's import-time log record is captured too.

Why (measured 2026-09-15 on the authority): the running service had
`logging.getLogger().level == WARNING` and **zero root handlers**. `logger.info` was
therefore discarded app-wide, and WARNING+ survived only through Python's
`lastResort` stream, which prints the bare message -- no timestamp, no level, no
logger name. `INFO Lifecycle sweep complete` had appeared 39 times in three hours and
then never again after the 13:35 restart, because INFO had only ever reached the
journal when Twilio's HTTP client happened to call `logging.basicConfig()` first in
that process. Whether this system could narrate itself depended on import order, and
I spent an hour proving a live scheduled sweep was dead because of it.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path.home() / "personal-secretary-mvp"
MAIN = REPO / "app" / "main.py"
SETUP = REPO / "app" / "logging_setup.py"

ANCHOR = "from app.config import Settings, settings"
CALL = '''# Logging must be configured before any module in this package can log. Measured
# 2026-09-15: without this the root logger sat at WARNING with no handlers, so every
# logger.info in the application was discarded and WARNING and above reached the
# journal only through Python's lastResort handler -- with no level, no logger name and
# no timestamp. INFO narration appearing at all depended on a third-party library
# calling logging.basicConfig() first.
from app.logging_setup import configure_logging

configure_logging()

from app.config import Settings, settings'''


def main() -> int:
    setup_src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if setup_src is None or not setup_src.exists():
        print("REFUSE: pass the path to the staged app/logging_setup.py as argv[1]")
        return 2

    text = MAIN.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if "configure_logging" in text:
        print("REFUSE: already applied")
        return 2

    SETUP.write_text(setup_src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"WROTE {SETUP}")
    MAIN.write_text(text.replace(ANCHOR, CALL, 1), encoding="utf-8")
    print(f"WROTE {MAIN}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
