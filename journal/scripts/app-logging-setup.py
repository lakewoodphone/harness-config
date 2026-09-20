"""Configure the application's logging, once, explicitly.

Measured 2026-09-15 on the authority: `logging.getLogger().level` was **WARNING**
with **no handlers** in the running service. So every `logger.info(...)` in the
application was discarded, and WARNING and above reached the journal only through
Python's `lastResort` handler -- which prints the bare message with no timestamp,
no level and no logger name. Two consequences, both measured:

* `INFO Lifecycle sweep complete` appeared 39 times in three hours and then never
  again after the 13:35 restart, because the only reason INFO had *ever* reached the
  journal was that a third-party library (Twilio's HTTP client) called
  `logging.basicConfig()` at import in that process. Nothing in this codebase
  configured logging, so whether the system could narrate itself depended on import
  order. That made a live sweep look dead for an hour.
* A `logger.warning` from the autopilot was indistinguishable in the journal from a
  library message: no level, no module, no sub-second time.

Turning INFO on app-wide is only half a fix, because this codebase logs provider
URLs and OAuth flows at INFO. So the handler carries a redaction filter: key/value
pairs whose key names a credential, `Bearer <token>`, `sk-`/`rk-`/`pk-` keys, and
credential query parameters are replaced before the record is written. The journal
is on disk, readable by anything with journal access, and rotated by size rather
than by secrecy.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"
_MARKER = "_psmvp_logging_handler"

# Third-party loggers that would otherwise drown the journal at INFO. The app's own
# loggers are never capped -- that is the point of this module.
_QUIET = ("httpx", "httpcore", "urllib3", "asyncio", "charset_normalizer", "PIL")

# Credential names, as regex fragments so the separator can vary: this codebase writes
# `api_key`, `apiKey`, `X-Api-Key` and `API-KEY`. The first version of this list only
# had the underscore form and let `X-Api-Key=abcd1234efgh` straight through -- caught by
# testing the scrubber by hand instead of trusting it.
_SECRET_KEYS = (
    r"authorization",
    r"api[-_ ]?key",
    r"access[-_ ]?token",
    r"refresh[-_ ]?token",
    r"id[-_ ]?token",
    r"client[-_ ]?secret",
    r"client[-_ ]?id",
    r"auth[-_ ]?token",
    r"password",
    r"passwd",
    r"secret",
    r"session[-_ ]?token",
    r"sapisid",
    r"cookie",
    r"private[-_ ]?key",
)

_KV = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_KEYS) + r")\b(\"?\s*[:=]\s*\"?)"
    # Two lookaheads: an already-redacted value is not re-matched (which produced
    # "Authorization: <redacted> <redacted>"), and the word "Bearer" is not itself a
    # value (the token after it is handled by _BEARER, and redacting only the word
    # would have left the real token in the line).
    r"(?!(?:<redacted>|bearer\b))([^\s\"',;&\)]{4,})"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SK = re.compile(r"\b(?:sk|rk|pk|ghp|ghs|xox[baprs])-[A-Za-z0-9_\-]{12,}\b")
_QS = re.compile(
    r"(?i)([?&](?:token|access_token|refresh_token|api_key|key|secret|code|signature)=)"
    r"[^&\s]+"
)
_REDACTED = "<redacted>"


def scrub(text: str) -> str:
    """Remove credential-shaped values from a log line.

    Deliberately narrow: only shapes that are unambiguously a credential, so ordinary
    diagnostics survive. A line that merely *mentions* a token is untouched, which is
    why "Gmail token health 4/4 ok" still reads correctly.
    """
    if not text:
        return text
    out = _BEARER.sub("Bearer " + _REDACTED, text)
    out = _KV.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", out)
    out = _SK.sub(_REDACTED, out)
    out = _QS.sub(lambda m: m.group(1) + _REDACTED, out)
    return out


class _RedactSecrets(logging.Filter):
    """Scrub a record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record must still be logged
            return True
        clean = scrub(message)
        if clean != message:
            record.msg = clean
            record.args = ()
        return True


def _desired_level() -> int:
    raw = str(os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = logging.getLevelName(raw)
    return level if isinstance(level, int) else logging.INFO


def configure_logging(level: int | str | None = None, *, force: bool = False) -> logging.Logger:
    """Install one root handler with a real format, redaction, and the level.

    Idempotent: a second call is a no-op unless `force`, so importing this from a
    module that is imported twice (uvicorn's reload, tests) cannot double every line.
    A pre-existing root handler is replaced -- silently adding ours beside it is how
    the same line ends up in the journal twice, and leaving a bare formatter in place
    is how a message loses its level.
    """
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, _MARKER, False)]
    if ours and not force:
        root.setLevel(level if level is not None else _desired_level())
        return root

    resolved = (
        level
        if isinstance(level, int)
        else (logging.getLevelName(str(level).upper()) if level else None)
    )
    if not isinstance(resolved, int):
        resolved = _desired_level()

    # Under pytest the logging plugin owns the root handlers, and closing one mid-suite
    # breaks `caplog` for every test after this module. In a real process a stray
    # handler is exactly the duplicate line this function exists to remove.
    if "pytest" not in sys.modules:
        for handler in list(root.handlers):
            if not getattr(handler, _MARKER, False):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001 - a broken handler must not stop us
                    pass

    if not ours:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        handler.addFilter(_RedactSecrets())
        setattr(handler, _MARKER, True)
        root.addHandler(handler)

    root.setLevel(resolved)
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
    return root
