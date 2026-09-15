"""The application must be able to say what it is doing -- without saying its secrets.

Measured 2026-09-15 on the authority: root logger level WARNING, zero root handlers.
`logger.info` was discarded app-wide and WARNING+ reached the journal only through
Python's lastResort handler (bare message, no level, no logger name). Whether INFO
narration appeared at all depended on a third-party library calling
`logging.basicConfig()` first -- which is how a live scheduled sweep came to look
dead for an hour.

Because this codebase logs provider URLs and OAuth flows at INFO, turning INFO on is
only half the fix: the handler redacts credential-shaped values first. The journal is
on disk and rotated by size, not by secrecy.
"""

from __future__ import annotations

import importlib
import logging

from app.logging_setup import _MARKER, configure_logging, scrub


def _our_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, _MARKER, False)]


def test_it_installs_a_formatted_root_handler_at_info():
    root = configure_logging(force=True)
    assert root.level == logging.INFO
    ours = _our_handlers()
    assert len(ours) == 1, "exactly one of our handlers, so lines cannot double"
    fmt = ours[0].formatter._fmt
    assert "%(levelname)s" in fmt and "%(name)s" in fmt and "%(asctime)s" in fmt


def test_the_handler_carries_the_redaction_filter():
    configure_logging(force=True)
    filters = [type(f).__name__ for f in _our_handlers()[0].filters]
    assert "_RedactSecrets" in filters, filters


def test_an_info_record_from_a_service_logger_is_now_emitted():
    """The exact failure: this record used to be dropped on the floor."""
    configure_logging(force=True)
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):  # noqa: D102 - test double
            seen.append(self.format(record))

    cap = Capture()
    cap.setFormatter(logging.Formatter("%(levelname)s|%(name)s|%(message)s"))
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        logging.getLogger("app.services.lifecycle_sweep").info(
            "Lifecycle sweep complete: %s", {"owner_messages_expired": 0}
        )
    finally:
        root.removeHandler(cap)

    assert any(
        line.startswith("INFO|app.services.lifecycle_sweep|Lifecycle sweep complete")
        for line in seen
    ), seen


def test_credentials_are_redacted_before_they_reach_the_journal():
    assert "s3cr3t-value" not in scrub("Authorization: Bearer s3cr3t-value--long")
    assert "ya29.abcdefghijklmnop" not in scrub(
        "GET https://oauth2.googleapis.com/token?access_token=ya29.abcdefghijklmnop"
    )
    assert "abcd1234abcd1234" not in scrub('config: {"api_key": "abcd1234abcd1234"}')
    assert "sk-livekeyvalue1234567890" not in scrub("using sk-livekeyvalue1234567890 now")
    assert scrub("password=hunter2000").endswith("<redacted>")
    # Found by hand-testing the scrubber: the first key list only had the underscore
    # form, and the header spelling is hyphenated.
    assert "abcd1234efgh" not in scrub("X-Api-Key=abcd1234efgh")
    assert "abcd1234efgh" not in scrub("apiKey: abcd1234efgh")
    # "Bearer" must not be treated as the value, or the token after it survives.
    out = scrub("Authorization: Bearer ya29.A0ARrdaM-xyz123456789")
    assert out == "Authorization: Bearer <redacted>", out


def test_ordinary_diagnostics_are_not_mangled():
    """A line that *mentions* a token is not a line that leaks one."""
    for line in (
        "autopilot: Gmail token health - 4/4 ok, 0 need reauth: []",
        "Activity sync: created=0 updated=0 skipped=0",
        "Tiered tools: 42/111 loaded for message",
    ):
        assert scrub(line) == line, line


def test_it_is_idempotent_so_importing_twice_does_not_double_every_line():
    configure_logging(force=True)
    before = len(_our_handlers())
    configure_logging()
    configure_logging()
    assert len(_our_handlers()) == before == 1


def test_the_level_comes_from_LOG_LEVEL(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    try:
        root = configure_logging(force=True)
        assert root.level == logging.WARNING
        assert not logging.getLogger("app.autopilot").isEnabledFor(logging.INFO)
    finally:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        configure_logging("INFO", force=True)


def test_importing_the_app_configures_logging_without_being_asked():
    """The wiring, not just the function: main.py must call it before the app logs."""
    import app.main  # noqa: F401 - the import is the behaviour under test

    logging.getLogger().setLevel(logging.NOTSET)  # pretend something reset it
    importlib.reload(importlib.import_module("app.main"))
    assert logging.getLogger().level == logging.INFO
    assert _our_handlers(), "app.main must leave a configured root logger behind"

