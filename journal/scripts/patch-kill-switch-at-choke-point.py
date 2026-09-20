#!/usr/bin/env python3
"""A kill switch that callers must remember to check is not a kill switch.

MEASURED on secratary 2026-09-15. `data/OWNER_SMS_KILL_SWITCH` exists and its own text says:

    # Created 2026-07-14 by Copilot per owner request.
    # While this file exists, ALL owner SMS are blocked.
    # The CEO was stuck in a loop sending 28+ "URGENT" texts.

It is checked in exactly three places -- `autopilot._maybe_flush_owner_message_queue`,
`services/notification_manager`, and `chat_action_owner` -- while `send_message` is called from
more than a dozen (chat_action_gmail, chat_action_runtime, main.py x3, tool_factory,
anomaly_detector, the sms_service wrappers, ...). So "ALL owner SMS are blocked" was not true:
two urgent owner messages went out at 00:59 on 2026-09-15 with the switch in place.

`send_message` ALREADY calls itself "the central choke point -- catches ALL paths", and it
already computes the owner's recognised numbers there for the daily quota. The kill switch
belongs in the same place, for the same reason, and now uses the same owner detection.

SCOPED TO THE OWNER. The switch is about his phone; customer SMS must keep working, because the
business texts customers for real. That is why the check sits inside the existing owner-number
branch rather than at the top of the function.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_IMPORT = "import logging\nimport re\nimport time"
NEW_IMPORT = "import logging\nimport re\nimport time\nfrom pathlib import Path"

HELPER = '''_OWNER_SMS_KILL_SWITCH_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "OWNER_SMS_KILL_SWITCH"
)


def owner_sms_kill_switch_active(path: str | Path | None = None) -> bool:
    """True when owner SMS are switched off.

    The file is created and removed by hand, and its own contents say why it exists ("the CEO
    was stuck in a loop sending 28+ URGENT texts"). `path` exists so the check can be tested
    without touching the live switch.
    """
    try:
        return Path(path if path is not None else _OWNER_SMS_KILL_SWITCH_PATH).exists()
    except Exception:  # noqa: BLE001 - an unreadable path is not a reason to send
        return False


def _error_response(to: str, body: str | None, error: str) -> dict[str, Any]:'''

OLD_BRANCH = '''        if owner_numbers and _normalize_phone(to_normalized) in owner_numbers:
            from app.database import get_db_connection'''

NEW_BRANCH = '''        if owner_numbers and _normalize_phone(to_normalized) in owner_numbers:
            # ── Owner kill switch, enforced where every send passes ──
            # Its file says "ALL owner SMS are blocked" and it was checked at three call sites
            # while send_message is called from more than a dozen, so measured 2026-09-15 two
            # urgent owner messages went out at 00:59 with the switch in place. Customer SMS is
            # unaffected by design: this sits inside the owner-number branch.
            if owner_sms_kill_switch_active():
                log.warning(
                    "Owner SMS blocked by kill switch: %s (send to %s suppressed)",
                    _OWNER_SMS_KILL_SWITCH_PATH,
                    to_normalized,
                )
                return _error_response(
                    to=to_normalized,
                    body=resolved_body,
                    error=(
                        "Blocked by OWNER_SMS_KILL_SWITCH: owner SMS are disabled "
                        f"({_OWNER_SMS_KILL_SWITCH_PATH})"
                    ),
                )

            from app.database import get_db_connection'''

TEST = '''"""The owner kill switch must be enforced where every send passes.

Its own file says "ALL owner SMS are blocked" (created 2026-07-14 because the CEO was sending
28+ URGENT texts), but it was checked at three call sites while send_message is called from more
than a dozen -- so on 2026-09-15 two urgent owner messages went out at 00:59 with the switch in
place. send_message already calls itself the central choke point for the owner daily quota; the
switch now lives there too.
"""

import pathlib

from app.sms_service import owner_sms_kill_switch_active


def test_the_switch_reads_the_file_it_is_given(tmp_path):
    p = tmp_path / "OWNER_SMS_KILL_SWITCH"
    assert owner_sms_kill_switch_active(p) is False
    p.write_text("blocked\\n", encoding="utf-8")
    assert owner_sms_kill_switch_active(p) is True


def test_an_absent_path_is_not_active(tmp_path):
    assert owner_sms_kill_switch_active(tmp_path / "nope") is False


def test_the_live_switch_is_where_the_code_says_it_is():
    """The path matters: I first looked for it under ~/.personal-secretary and found nothing."""
    import app.sms_service as svc

    assert svc._OWNER_SMS_KILL_SWITCH_PATH.name == "OWNER_SMS_KILL_SWITCH"
    assert svc._OWNER_SMS_KILL_SWITCH_PATH.parent.name == "data"


def test_send_message_consults_the_switch():
    """Wiring, asserted structurally: the defect was a missing check at the choke point."""
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "sms_service.py"
    src = path.read_text(encoding="utf-8")
    assert "if owner_sms_kill_switch_active():" in src
    # and it is inside the owner-number branch, so customers are unaffected
    owner_branch = src.index("if owner_numbers and _normalize_phone(to_normalized) in owner_numbers:")
    kill = src.index("if owner_sms_kill_switch_active():")
    quota = src.index("Owner SMS quota reached", kill)
    assert owner_branch < kill < quota, "the switch must precede the quota check"
'''


def main() -> int:
    p = pathlib.Path("app/sms_service.py")
    src = p.read_text(encoding="utf-8")

    assert src.count(OLD_IMPORT) == 1, f"import: {src.count(OLD_IMPORT)}"
    assert src.count("def _error_response(to: str, body: str | None, error: str)") == 1
    assert src.count(OLD_BRANCH) == 1, f"branch: {src.count(OLD_BRANCH)}"
    assert "owner_sms_kill_switch_active" not in src

    backup = BACKUPS / f"sms_service.py.{STAMP}.bak20"
    if not backup.exists():
        shutil.copy("app/sms_service.py", backup)

    src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)
    src = src.replace(
        "def _error_response(to: str, body: str | None, error: str) -> dict[str, Any]:",
        HELPER + " -> dict[str, Any]:",
        1,
    )
    src = src.replace(OLD_BRANCH, NEW_BRANCH)
    p.write_text(src, encoding="utf-8")
    print("patched app/sms_service.py: the kill switch is enforced at the choke point")

    pathlib.Path("tests/test_owner_sms_kill_switch.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_owner_sms_kill_switch.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
