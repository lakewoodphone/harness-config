#!/usr/bin/env python3
"""Get it to them, and know that it went. (module: SEND)

THE ONE RULE THAT OVERRIDES EVERYTHING
--------------------------------------
Nothing is sent to a third party without the send gate being explicitly open.
Default is closed. That is not a comment, it is the first thing `send()` does,
and it is re-checked inside `send()` even though the caller already asked - a
caller that forgets to ask must not be able to speak to the owner's father.

Why this module exists (audit `docs/ai-text-line-audit-2026-09-20.md`):

  * **B9** - the model's output was validated by one regex in `classify()`.
    There was no signature enforcement on the auto path, no length check against
    SMS segments, no gate that a model's text has to pass before a human sees it.
    This module is the safe mouth: whatever the decision layer produced, it is
    checked HERE, at the last moment, by code that cannot be talked out of it.
    A refusal is a returned value, never an exception - an exception in a sender
    is how a text either goes out twice or never goes out and nobody knows.
  * **L1976** - every message the secretary sends is signed `- Daniel`, on its own
    last line. Until now the only enforcement was a `print()` inside the manual
    script `send-from-ai-line.py`, i.e. a warning to a human who was already
    careful. It is a refusal here.
  * The owner is NOT texted by this path for notifications. There is a live kill
    switch (`OWNER_SMS_KILL_SWITCH`, created 2026-07-14 after the CEO sent 28+
    "URGENT" texts); owner notifications go to the app's own queue over HTTP.

WHAT IT REUSES (do not re-invent)
---------------------------------
  * `.env` credential reading: `sms-inbox.py`'s `env()` - the same file, the same
    parse, minus the `sys.exit` when the file is absent (a missing file is a
    degraded deployment here, not a reason to kill the process).
  * the Twilio REST send shape and the `messages` INSERT column list:
    `send-from-ai-line.py`.
  * the store: `textstore.connect()` / `textstore.DB_PATH`, unmodified.

CONTRACT (`docs/ai-text-line-contracts.md`, frozen 2026-09-20)

    can_send_to(phone, ctx, config) -> tuple[bool, str]
    send(to, body, *, config=None, dry_run=True) -> dict
    notify_owner(body, *, config=None, dry_run=True) -> dict
    sender_number(config=None) -> str
    history(db_path, limit=20) -> list[dict]

Every dict is `{ok, sid, error, channel, dry_run, detail}`. `dry_run=True` is the
default everywhere; `--send` is required to actually send anything.

CONFIG

    config=None resolves from the environment, then from the `.env` file, then
    from the built-in defaults (closed). An explicit `config` mapping wins over
    both. Keys are the environment names, so what an operator sets in `.env` and
    what a caller passes are the same vocabulary:

        OWNER_PHONE_NUMBER              the owner's own number; always sendable
        TWILIO_PHONE_NUMBER             the AI line (from number)
        TWILIO_ACCOUNT_SID/_AUTH_TOKEN  Twilio credentials
        AITEXT_ALLOW_THIRD_PARTY_SENDS  "1" opens third-party sending. DEFAULT CLOSED
        AITEXT_ALLOW_UNSIGNED           "1" allows an unsigned body (B9 hatches)
        SMS_INBOX_DB                    the store (else textstore.DB_PATH)
        SECRETARY_API_BASE              app base URL for owner notifications
        OWNER_NOTIFY_URL                the owner-notify endpoint, in full
        OWNER_SMS_KILL_SWITCH           path whose existence blocks owner SMS

CLI - for an operator, and for a live proof that never guesses:

    python3 textsend.py check  --to +18485257897 --allow auto
    python3 textsend.py send   --to +17325691594 --body-file /tmp/b.txt [--send]
    python3 textsend.py notify --body-file /tmp/b.txt [--send]
    python3 textsend.py history --limit 20
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

# --------------------------------------------------------------------------- #
# Constants. Twilio's own limits, not our preference: 1600 characters is the
# hard cap on a message body; 6 concatenated segments is where a personal text
# stops being a text (~930 chars) and becomes a wall.
# --------------------------------------------------------------------------- #
HARD_LIMIT = 1600
SOFT_LIMIT = 930
SIGNATURE = "- Daniel"
AI_LINE_DEFAULT = "+17324447361"
DEFAULT_NOTIFY_URL = "http://127.0.0.1:8002/tools/notify-owner"
DEFAULT_KILL_SWITCH = "/home/zabz/personal-secretary-mvp/data/OWNER_SMS_KILL_SWITCH"
DEFAULT_ENV_FILE = HOME / "personal-secretary-mvp" / ".env"
DEFAULT_DB = HOME / ".sms-inbox" / "inbox.db"

CHANNEL_LINE = "twilio-ai-line"
CHANNEL_OWNER = "owner-notify"

# Env names we resolve. Anything else only exists if a caller passes it.
ENV_KEYS = (
    # The owner's own rate limit. Listed HERE because `_config()` only copies the keys
    # in this tuple out of the .env file, so a setting absent from this list silently
    # does nothing -- measured 2026-10-09: with the key added to .env and absent from
    # this tuple, `min_gap_minutes` still returned the 20.0 default.
    "OWNER_TEXT_MIN_GAP_MINUTES",
    "OWNER_PHONE_NUMBER", "TWILIO_PHONE_NUMBER", "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN", "AITEXT_ALLOW_THIRD_PARTY_SENDS", "AITEXT_ALLOW_UNSIGNED",
    "SMS_INBOX_DB", "SMS_INBOX_ENV", "SECRETARY_API_BASE", "OWNER_NOTIFY_URL",
    "OWNER_SMS_KILL_SWITCH",
)


# --------------------------------------------------------------------------- #
# Sibling modules. Both are optional: a partially deployed tree degrades, it
# does not crash. `sms-inbox.py` has a dash in its name, so it is loaded by path
# exactly the way `send-from-ai-line.py` already does it.
# --------------------------------------------------------------------------- #
def _load_sibling(name: str, filename: str):
    path = HERE / filename
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
try:
    import textstore as store
except Exception:  # pragma: no cover - only when the tree is partial
    store = _load_sibling("textstore", "textstore.py")

inbox = _load_sibling("sms_inbox", "sms-inbox.py")

# THE FLOOD BRAKE. Owned by `owner_flood_guard.py`, one module over, and deliberately
# optional: a partially deployed tree degrades (the brake is not consulted) rather than
# crashing the sender. Measured 2026-10-01: 911 identical owner-bound rows were refused
# with `too_long` and re-fired every ~60 s for seven hours, because nothing in either
# half of this system counted an attempt.
try:
    import owner_flood_guard as flood
except Exception:  # pragma: no cover - only when the tree is partial
    flood = _load_sibling("owner_flood_guard", "owner_flood_guard.py")

#: The app's own one-text ceiling, from the module that defines it, with a literal
#: fallback so a partially deployed tree still fits rather than refuses.
APP_OWNER_TEXT_CEILING = int(getattr(flood, "APP_OWNER_TEXT_MAX_CHARS", 320) or 320)

# --------------------------------------------------------------------------- #
# THE OWNER-TEXT RELAY (`owner_text_relay.py`) - policy only, it does NOT transmit.
#
# Every door to his phone submits an intent and obeys the verdict; the transport
# (credentials, the notify-URL fallback, the kill switch) stays HERE. The relay is
# another builder's file and, measured 2026-10-14, `/root/bin/owner_text_relay.py`
# and `/root/.owner-text/` did not exist yet. So it is OPTIONAL and FAIL-SOFT: if it
# cannot be imported, or it raises, the send proceeds exactly as it did before the
# relay existed and ONE line naming the failure goes to stderr. A relay outage may
# never stop his texts, and may never be silent.
# --------------------------------------------------------------------------- #
_RELAY = None                      # None = untried, False = unavailable, else the module
_RELAY_LOGGED = False

#: The one `class_hint` the relay's FLOOR (its rule 5) exempts besides
#: `urgency in {"urgent","critical"}`: a message that ANSWERS something the owner just
#: said is SOLICITED, and holding his answer for 20 minutes is the silence he is
#: complaining about.  This is the relay's own `owner_text_relay.REPLY_CLASS`, carried
#: here as a literal because this door must not import the relay at import time (the
#: relay is optional and fail-soft) -- if the two ever disagree, the relay's constant
#: wins and this door simply sends without the exemption, which is a FLOOR, not a loss.
REPLY_CLASS = "reply"


def _relay_log_once(message: str) -> None:
    """One line per process, in this module's own log convention (`file=sys.stderr`)."""
    global _RELAY_LOGGED
    if _RELAY_LOGGED:
        return
    _RELAY_LOGGED = True
    try:
        print("textsend: owner_text_relay %s - sending WITHOUT the relay "
              "(fail-soft, not fail-silent)" % message, file=sys.stderr)
    except Exception:
        pass


def _relay_module():
    """The relay module, or None. Imported once; a failure is logged once."""
    global _RELAY
    if _RELAY is False:
        return None
    if _RELAY is None:
        mod = None
        err = ""
        try:
            import owner_text_relay as mod        # a sibling of this file
        except Exception as exc:
            err = "%s: %s" % (type(exc).__name__, exc)
        if mod is None:
            mod = _load_sibling("owner_text_relay", "owner_text_relay.py")
        if mod is None:
            _RELAY = False
            sys.modules.pop("owner_text_relay", None)
            _relay_log_once("unavailable (%s)"
                            % (err or "%s not importable" % (HERE / "owner_text_relay.py")))
            return None
        _RELAY = mod
    return _RELAY


def _relay_ref(body) -> str:
    """The `ask-<n>` / `q<n>` token a caller put on the wire, if there is one."""
    for pattern in (r"\[(ask-\d+)\]", r"#(ask-\d+)\b", r"\b(ask-\d{6,})\b", r"\[(q\d+)\]"):
        found = re.search(pattern, str(body or ""), re.I)
        if found:
            return found.group(1).lower()
    return ""


def _relay_subsystem(reason, body="") -> str:
    """Who owns this message: the caller's `reason` when it names something.

    `_GENERIC_TURN_REASONS` is this module's own list of reasons that name nothing
    (`aitext-responder`, `send_message`, ...), so for those the subsystem is derived
    from the body's shape by the same function the turn ledger ranks by - and when
    that says nothing either, `""` is reported rather than an invented name.
    """
    key = str(reason or "").strip()
    if key and key.casefold() not in _GENERIC_TURN_REASONS:
        return key
    return effective_turn_reason(reason, body) or ""


def _relay_refusal(res: dict, verdict: dict, door: str) -> dict:
    """A non-SEND verdict as this module's own refusal shape (`_blank()`'s six keys).

    `ok=False`, `error` = the verdict itself (`DEDUPE`, `FLOOR`, `COALESCE`,
    `SUPPRESS`) and `detail` = the relay's own sentence, so a caller can match the
    verdict exactly the way `cfo-ask.py` already matches on `error` text. A refusal is
    a returned value with exit 1 - never a traceback.
    """
    verdict = verdict or {}
    res["ok"] = False
    res["sid"] = None
    res["error"] = str(verdict.get("verdict") or "SUPPRESS")
    res["detail"] = ("refused by the owner-text relay (%s/%s): %s"
                     % (res["error"], str(verdict.get("reason") or "-"),
                        str(verdict.get("detail") or "")))
    res["relay"] = {"door": door, "verdict": res["error"],
                    "reason": verdict.get("reason"),
                    "attempt_id": verdict.get("attempt_id")}
    return res


def _relay_gate(res: dict, body, *, reason=None, urgency: str = "normal", ref=None,
                class_hint=None):
    """Ask the relay about ONE owner-bound send.

    Returns `(attempt_id, refusal, body_to_send)`. The third element is the body the
    relay JUDGED, fitted to its owner ceiling if it was over -- the caller MUST post
    that and not the body it passed in, or the text that was judged and the text
    that goes out are two different messages (measured 2026-10-14).

    `(None, None)` means "send it": either the relay is unavailable (fail-soft, see
    `_relay_module`) or it said SEND. Called from exactly ONE place - the transmit path
    of `send()`, below every refusal that already existed and below the dry-run return,
    so a dry run can never write an attempt row and a gate refusal stays that refusal.

    `ref` is the ask token the CALLER put on the wire, captured before the
    classification gate could strip it out of the body (it strips a leading `[qNNN]`
    reference and drops reference-only sentences): the ask ledger must be keyed on what
    the asker named, not on what survived the display trim.

    `class_hint` is the relay's own class of message (`reply` is the one the relay's
    FLOOR exempts). It is passed straight through; `None` means "no class".
    """
    mod = _relay_module()
    if mod is None:
        return None, None, body

    # THE BYTES JUDGED ARE THE BYTES POSTED -- and nothing else touches `body` here.
    #
    # Why there is no owner-ceiling fit in this function (manager, 2026-10-14). There
    # was one, and it worked: `submit` was handed 270 chars and the wire carried 270.
    # But the relay's row still recorded the caller's 636-char body, because two module
    # instances of `owner_text_relay` are in play and the one that wrote the attempt was
    # not the one this function resolved. So the record of what the owner was told
    # disagreed with what he was actually sent.
    #
    # A relay whose record of the conversation can be wrong is worse than one that
    # permits a long text: every later conclusion -- the dedupe, the retry cap, the ask
    # ledger, the "what did we decide not to tell him" view -- is drawn from that
    # record. `wrong-data` is the measured number-one failure in this estate. So the
    # rule is: hand the relay EXACTLY what will be posted, `fitted` from
    # `fit_to_segments`, and let the record be true.
    #
    # The 320-char owner ceiling is still enforced by the relay (`too-long` is recorded
    # when a door exceeds it) and by the door that can enforce it exactly: the app door
    # fits through `relay.fit()` before it submits. textsend's own owner ceiling,
    # `fit_owner_body`/`OWNER_TEXT_MAX_CHARS`, remains available to callers; the
    # transport fit below is the one that governs this path. Unifying the two is a
    # separate, tested change -- see the handoff.
    try:
        verdict = mod.submit(
            door="textsend",
            subsystem=_relay_subsystem(reason, body),
            body=body,
            reason=str(reason or ""),
            urgency=str(urgency or "normal"),
            class_hint=(str(class_hint).strip() or None) if class_hint else None,
            ref=str(ref) if ref else (_relay_ref(body) or None),
            opens_ask=bool(_QUESTION_RE.search(str(body or ""))),
        )
    except Exception as exc:
        _relay_log_once("submit failed (%s: %s)" % (type(exc).__name__, exc))
        return None, None, body
    if not isinstance(verdict, dict):
        _relay_log_once("submit returned %r, not a verdict dict" % (verdict,))
        return None, None, body
    if str(verdict.get("verdict") or "").upper() == "SEND":
        return verdict.get("attempt_id"), None, body
    return None, _relay_refusal(res, verdict, "textsend"), body


def _relay_record_sent(attempt_id, *, sid: str = "", status: str = "sent", body=None) -> bool:
    """Tell the relay that a real POST came back. Never raises."""
    mod = _relay_module()
    if mod is None or attempt_id is None:
        return False
    try:
        mod.record_sent(attempt_id, sid=str(sid or ""), status=str(status or "sent"), body=body)
        return True
    except Exception as exc:
        _relay_log_once("record_sent failed (%s: %s)" % (type(exc).__name__, exc))
        return False


def _relay_record_failed(attempt_id, *, error: str = "", status: str = "failed") -> bool:
    """Tell the relay that the POST did not deliver. Never raises."""
    mod = _relay_module()
    if mod is None or attempt_id is None:
        return False
    try:
        mod.record_failed(attempt_id, error=str(error or ""), status=str(status or "failed"))
        return True
    except Exception as exc:
        _relay_log_once("record_failed failed (%s: %s)" % (type(exc).__name__, exc))
        return False



def _guard_store(cfg: dict, *, write: bool = False):
    """A connection to the channel's attempt ledger: read-only unless we are recording.

    Read-only by default on purpose - this sender must not migrate a store just by
    looking at it, and a write that fails must not take the send down with it.
    """
    if flood is None:
        return None
    path = _db_path(cfg)
    try:
        return flood.connect(path) if write else flood.ro_connect(path)
    except Exception:
        return None


def _guard_app(cfg: dict):
    """Read-only handle on the app's own `sms_log`, which is where the OTHER half of
    this system's attempts to reach the owner are recorded. A suppressed row there is
    an attempt, and the brake has to see it."""
    if flood is None:
        return None
    try:
        return flood.ro_connect(app_db_path(cfg))
    except Exception:
        return None


def _flood_verdict(cfg: dict, to_e164: str, body, res: dict):
    """Consult the brake before an owner-bound send. None means 'no objection'."""
    if flood is None:
        return None
    try:
        verdict = flood.decide(to_e164, body, app_conn=_guard_app(cfg))
    except Exception:
        return None                       # a brake that raises must not block a real send
    guard_state = {"code": verdict.code, "attempts_last_hour": verdict["attempts_last_hour"],
                   "detail": verdict.detail}
    if verdict.allowed:
        # NONE means "no objection": the caller returns only on a non-None value, and an
        # allowed verdict returned as a value silently refused every owner-bound send.
        res["flood_guard"] = guard_state
        return None
    res["flood_guard"] = guard_state
    res["error"] = ("flood guard (%s): %s" % (verdict.code, verdict.detail))
    res["detail"] = (
        "refused before any network call. One identical message to the owner is not "
        "retried on a tick: it backs off exponentially per (recipient, body), and after "
        "%d identical attempts inside %d minutes the brake stops the retrying and raises "
        "ONE owner-queue question instead of a silent loop. See owner_flood_guard.py."
        % (getattr(flood, "BREAKER_ATTEMPTS_PER_HOUR", 5),
           getattr(flood, "ATTEMPT_WINDOW_MINUTES", 60)))
    return dict(guard_state)


def _flood_note(cfg: dict, to_e164: str, body, outcome: str, code: str = "",
                detail: str = "") -> dict:
    """Record the attempt, and let the brake trip exactly one question if it crossed."""
    if flood is None:
        return {}
    try:
        return flood.note(to_e164, body, outcome, code=code, detail=detail,
                          conn=_guard_store(cfg, write=True), app_conn=_guard_app(cfg))
    except Exception:
        return {}


def _norm_owner_body(body) -> str:
    """The canonical form of a body for duplicate comparison.

    `owner_flood_guard.normalise` is the ONE definition of "the same message" in this
    system -- `text-health.py` C2 asserts the instrument and the brake agree on it -- so
    it is used here rather than a third spelling. The local fallback is byte-identical in
    behaviour, for a partially deployed tree.
    """
    if flood is not None:
        return flood.normalise(body)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(body or "").lower()).split())[:160]


def _parse_owner_stamp(value):
    """A datetime for either stamp format this store writes, or None. Never raises."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "," in text or text[:3].isalpha():          # RFC 2822, from Twilio
            from email.utils import parsedate_to_datetime
            got = parsedate_to_datetime(text)
        else:                                           # ISO 8601, from our own sender
            got = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    except Exception:
        return None


#: How long an identical owner-bound body counts as already sent. The audit that keeps
#: this channel honest (`sources/owner-question-audit.py`) treats two identical bodies
#: inside its 24 h window as a repeat, because the second copy has no reader left: the
#: owner already read it. Measured 2026-10-08: the same library result was sent at
#: 23:14:03 and again at 23:15:17, and his reply was "I got the freaking message. You
#: texted me three times already." This is the sender-side half of that rule.
OWNER_DUP_WINDOW_HOURS = float(os.environ.get("AITEXT_OWNER_DUP_HOURS", "24") or 24)


def owner_body_seen_recently(cfg: dict, to_e164, body, *, hours=None, store_path=None):
    """`{sid, at}` when this exact body was already SENT to this recipient recently.

    READ-ONLY and advisory: it returns the prior send or None, and never raises, so a
    caller can refuse loudly or merely report. It is deliberately NOT called from
    `send()` -- the flood brake, not a flat duplicate rule, owns `send()`'s retry
    semantics -- but the second transport (`send-from-ai-line.py`) and the replay
    harness call it so the composer that actually repeated stops repeating.
    """
    key = _norm_owner_body(body)
    if not key:
        return None
    try:
        span = float(hours if hours is not None else OWNER_DUP_WINDOW_HOURS)
    except (TypeError, ValueError):
        span = OWNER_DUP_WINDOW_HOURS
    path = Path(store_path) if store_path else _db_path(cfg or {})
    conn = _ro_connect(path)
    if conn is None:
        return None
    try:
        rows = conn.execute(
            "SELECT sid, body, to_number, first_seen, date_sent FROM messages "
            "WHERE direction='outbound' ORDER BY rowid DESC LIMIT 800").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=span)
    for r in rows:
        try:
            to, raw, sid = r["to_number"], r["body"], r["sid"]
            first_seen, date_sent = r["first_seen"], r["date_sent"]
        except (TypeError, IndexError, KeyError):
            continue
        if not _same(to, to_e164) or _norm_owner_body(raw) != key:
            continue
        when = _parse_owner_stamp(date_sent) or _parse_owner_stamp(first_seen)
        if when is None or when >= cutoff:
            return {"sid": sid, "at": str(date_sent or first_seen or "")}
    return None


def fit_owner_body(body, limit: int | None = None, *, cfg: dict | None = None) -> tuple:
    """`(fitted_body, detail)`. An owner-bound body is FITTED, never refused for length.

    THE RULE (journal P2817, P2819, owner-queue #235): a body that does not fit one text
    is a formatting problem, never a reason for silence. Measured 2026-10-01: the same
    811-character Topgolf reminder was handed to the app's 320-character gate 290 times
    in seven hours; every attempt was suppressed and every attempt was reported to its
    caller as a success. The cut happens at a sentence boundary, the same way
    `fit_to_segments` cuts for Twilio, and the trim is REPORTED - a truncated message
    that does not say it was truncated is a lie to whoever reads the log.
    """
    text = str(body or "").strip()
    if limit is None:
        limit = (flood.owner_text_ceiling(cfg) if flood is not None
                 else APP_OWNER_TEXT_CEILING)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = APP_OWNER_TEXT_CEILING
    if limit <= 0 or len(text) <= limit:
        return text, ""
    head, sig = _split_signature(text)
    tail = ("\n" + sig) if sig else ""
    room = max(limit - len(tail), 40)
    fitted = (_truncate_at_sentence(head[:room]) + tail).strip()
    detail = ("fitted from %d to %d chars at a sentence boundary for the owner's "
              "%d-char one-text ceiling (the full body stays in the record)"
              % (len(text), len(fitted), limit))
    return fitted, detail


def _app_notify_verdict(answer: str) -> tuple:
    """`(reached_him, why)`. Did the app's own answer say it HELD the message?

    THE DEFECT THIS CLOSES. `POST /tools/notify-owner` -> `send_owner_update` returns
    HTTP 200 with `{"ok": true, "suppressed": true, "held": true, "reason": "too_long"}`
    for a body the owner's gate refuses, and the old code here read the HTTP status and
    called that "delivered to the owner's notification queue". Measured 2026-10-01: 911
    rows written to `sms_log` with `status='suppressed'` and no `twilio_sid`, every one
    of them an attempt nobody looked at, while the sending code reported success.
    """
    text = str(answer or "")
    data = None
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if isinstance(data, dict):
        if data.get("suppressed") or data.get("held"):
            return False, str(data.get("reason") or data.get("reason_class") or "held")
        if data.get("ok") is False:
            return False, str(data.get("error") or data.get("reason") or "not ok")
        return True, ""
    low = text.lower()
    if re.search(r'"(suppressed|held)"\s*:\s*(true|1)', low):
        why = re.search(r'"reason"\s*:\s*"([^"]{0,60})"', text)
        return False, (why.group(1) if why else "held")
    return True, ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truthy(value) -> bool:
    """The only values that mean yes. Anything else - including None, '' and
    'maybe' - is closed, because the gate's failure mode must be silence."""
    return str(value if value is not None else "").strip().lower() in (
        "1", "true", "yes", "on", "y", "t")


def _digits(phone) -> str:
    return re.sub(r"\D", "", str(phone or ""))


def _e164(phone) -> str:
    """Best effort, and honest about it: no country guessing beyond +1."""
    s = str(phone or "").strip()
    d = _digits(s)
    if not d:
        return ""
    if s.startswith("+"):
        return "+" + d
    if len(d) == 10:
        return "+1" + d
    return "+" + d


def _same(a, b) -> bool:
    """Compare on the last ten digits, the way every query in this system does,
    so +1 845 555 0100 and 8455550100 are the same person."""
    da, db = _digits(a), _digits(b)
    return bool(da) and bool(db) and da[-10:] == db[-10:]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _parse_env_file(path) -> dict:
    out: dict = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def app_env() -> dict:
    """The app's `.env`, via the sensor's own reader when it is available.

    `sms-inbox.py:env()` calls `sys.exit()` when the file is missing. In a sensor
    run that is right; inside a sender it would turn "no credentials configured"
    into a process death, so SystemExit is caught here and the same file is
    parsed locally instead. Same file, same parse, no exit.
    """
    if inbox is not None:
        try:
            return dict(inbox.env())
        except (SystemExit, Exception):
            pass
    path = os.environ.get("SMS_INBOX_ENV") or DEFAULT_ENV_FILE
    return _parse_env_file(path)


def _config(config=None) -> dict:
    """Environment, then the `.env` file, then the caller. Later wins; explicit
    config wins over everything. The result is always closed by default."""
    cfg: dict = {}
    for k, v in app_env().items():
        if v not in (None, ""):
            cfg[k] = v
    for k in ENV_KEYS:
        v = os.environ.get(k)
        if v not in (None, ""):
            cfg[k] = v
    if config:
        for k, v in dict(config).items():
            cfg[k] = v
    return cfg


def _get(cfg: dict, *names, default=None):
    for n in names:
        v = cfg.get(n)
        if v not in (None, ""):
            return v
    return default


def _db_path(cfg: dict) -> Path:
    v = _get(cfg, "db_path", "SMS_INBOX_DB", "AITEXT_DB")
    if v:
        return Path(v)
    if store is not None and getattr(store, "DB_PATH", None):
        return Path(store.DB_PATH)
    return Path(os.environ.get("SMS_INBOX_DB") or DEFAULT_DB)


def _kill_switch(cfg: dict) -> Path:
    return Path(_get(cfg, "kill_switch", "OWNER_SMS_KILL_SWITCH",
                     default=DEFAULT_KILL_SWITCH))


def _notify_url(cfg: dict) -> str:
    explicit = _get(cfg, "notify_url", "OWNER_NOTIFY_URL")
    if explicit:
        return str(explicit)
    base = str(_get(cfg, "SECRETARY_API_BASE", "api_base",
                     default="http://127.0.0.1:8002")).rstrip("/")
    return base + "/tools/notify-owner"


def _ro_connect(path) -> sqlite3.Connection | None:
    """Read-only, or nothing. The sender never needs to write a permission."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


# --------------------------------------------------------------------------- #
# Identity: the owner, and nobody else
# --------------------------------------------------------------------------- #
def owner_numbers(config=None) -> list:
    """Every number we would treat as the owner's: the env one, plus any
    `permissions` row whose relationship says owner."""
    cfg = _config(config)
    out = []
    env_owner = _get(cfg, "owner_phone", "OWNER_PHONE_NUMBER")
    if env_owner:
        out.append(str(env_owner))
    conn = _ro_connect(_db_path(cfg))
    if conn is not None:
        try:
            for r in conn.execute(
                    "SELECT phone FROM permissions WHERE lower(trim(relationship))='owner'"):
                if r[0]:
                    out.append(str(r[0]))
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return out


def _is_owner(phone, cfg: dict) -> tuple:
    """(True, which source) or (False, ''). Only two sources, both deliberate:
    `OWNER_PHONE_NUMBER` and a `permissions` row with relationship='owner'.
    The caller's `ctx` is NOT trusted here - a context that merely claims
    'owner' must not be able to open the gate for a third party."""
    if not phone:
        return False, ""
    env_owner = _get(cfg, "owner_phone", "OWNER_PHONE_NUMBER")
    if env_owner and _same(phone, env_owner):
        return True, "OWNER_PHONE_NUMBER"
    conn = _ro_connect(_db_path(cfg))
    if conn is not None:
        try:
            for r in conn.execute(
                    "SELECT phone FROM permissions WHERE lower(trim(relationship))='owner'"):
                if r[0] and _same(phone, r[0]):
                    return True, f"permissions row relationship=owner ({r[0]})"
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return False, ""


# --------------------------------------------------------------------------- #
# THE OWNER'S CONVERSATION LEDGER, which this sender did not used to consult
# --------------------------------------------------------------------------- #
#
# WHY THIS EXISTS. `app/owner_text.py` holds the owner's own ruling: "you send me one
# text at a time ... You have to respond back or address what I say." Its `gate()` is
# enforced at three call sites in the app, and this module -- the path the owner
# actually hears from -- was not one of them. So a question this sender was waiting on
# did not block the app, and a question the app was waiting on did not block this
# sender: two conversations, one phone. Measured 2026-09-30: the app's gate refused 38
# of its last 50 owner sends with `awaiting_reply`, while 118 texts went out to him in
# seven days against 14 replies from him.
#
# The ledger is a table in the app's own database, `owner_text_turn`: one row per
# outbound message, `answered_at` set when he answers. Both sides already open that
# database, and this module opens it read-only for `permissions` on every check. An
# open row IS the one-at-a-time rule, so consulting it here is the whole fix -- there is
# no second rule to keep in sync, and nothing to reconcile later.

#: Urgencies that may interrupt an open turn, copied verbatim from the app's own
#: gate (`app/owner_text.py` INTERRUPTING_URGENCIES). This sender did not have them,
#: so it was STRICTER than the contract it was written to enforce: measured
#: 2026-09-30, nothing on this path could interrupt an open turn -- not the car
#: whose insurance lapsed, not a payment deadline -- while the app would have let
#: the same message through. A rule enforced on one of two paths is not a rule.
INTERRUPTING_URGENCIES = frozenset({"urgent", "critical", "stuck"})

#: A message that asks nothing must not consume the one-at-a-time channel. The rule
#: is "one QUESTION at a time"; an acknowledgement is not a question. Measured
#: 2026-09-30: "Got it - noted that she confirmed privately she'll handle it."
#: opened a turn at 16:13 and held the channel for twelve hours, as did
#: "Remembered." and a probe reading "if you see this, the gate failed". The
#: predicate is the same one `app/owner_text.count_asks` uses, so the two sides
#: cannot disagree about what a question is.
_QUESTION_RE = __import__("re").compile(r"[?\uFF1F]")

#: How long one unanswered text holds the channel, when neither the environment nor the
#: app sets it. Matches `app/owner_text.DEFAULT_REPLY_WINDOW_HOURS`: twelve hours is
#: overnight, so an evening question is still the only open question in the morning.
LIVE_TURN_WINDOW_HOURS = 12.0

#: Where the app keeps its own database when NOTHING names one -- not the environment,
#: not the app's own configuration. A LAST RESORT, not the answer.
#:
#: The live app writes `/root/authority.db`: its `.env` says
#: `DATABASE_URL=sqlite:////root/authority.db` (line 533 of
#: `/root/personal-secretary-mvp/.env`, which is a SYMLINK to `/opt/company/.env` --
#: one file, sha256 cd0396799326908a100a477dcefb477b006bc7ab47adf26034a2c989e0396f8d).
#: The path below is the PRE-`authority.db` copy: measured 2026-10-13, 1.8 MB,
#: `sms_log = 0` and `owner_text_turn = 1` -- and that single 03:30 row is why it looked
#: healthy for a day (W2756 read it and concluded the one-at-a-time rule "fires
#: correctly"). The ledger lives in the app's database, not in this module's store:
#: `_db_path` resolves to `~/.sms-inbox/inbox.db`, which holds `permissions` and the
#: message log but has no `owner_text_turn`.
DEFAULT_APP_DB = HOME / "personal-secretary-mvp" / "data" / "secretary.db"

#: The app itself. `/root/personal-secretary-mvp` is a symlink to `/opt/company`, and the
#: service runs from there -- `systemctl show company-api -p WorkingDirectory` ->
#: `/opt/company`, `ExecStart=... -m uvicorn app.main:app`, and NO `EnvironmentFile=`:
#: the app reads its own `.env` through pydantic `Settings`.
APP_ROOT = Path("/opt/company")
APP_ENV_FILES = (APP_ROOT / ".env", APP_ROOT / ".env.local")

#: Environment names that can name the app's database. Same list, same order, as the loop
#: that has always been here; `DATABASE_URL` is the one the live app actually sets.
APP_DB_ENV_KEYS = ("SECRETARY_DB", "SECRETARY_DATABASE_URL", "DATABASE_URL", "SMS_APP_DB")

#: One-element cache for `_app_resolved_db()`. That probe imports a large package, and a
#: resolution asked for on every send must not re-import it.
_APP_DB_CACHE: list = []


def _app_resolved_db() -> str:
    """What the LIVE app resolves its database to, using THE APP'S OWN CODE.

    `app.config.Settings` is the class the running service instantiates (pydantic
    `BaseSettings`, `env_file=(".env", ".env.local")`) and `app.database._db_file_path` is
    that app's own URL->path conversion. Importing them is preferred over re-implementing
    either, and the app's `.env` files are named explicitly so the answer cannot depend on
    the caller's working directory.

    It CANNOT be a hard import. This file is run by `/usr/bin/python3` from cron, where the
    app's virtualenv packages are absent -- measured 2026-10-13,
    `/usr/bin/python3 -c "import pydantic_settings"` -> ModuleNotFoundError, while
    `/opt/company/.venv/bin/python` imports it. So this is a best-effort, cached probe;
    `""` means "could not ask the app", and the caller then reads the app's `.env`, which is
    the same file. `test_stdb.py` fails if those two ever disagree about the live value.
    """
    if _APP_DB_CACHE:
        return _APP_DB_CACHE[0]
    resolved = ""
    try:
        import importlib
        try:
            config = importlib.import_module("app.config")
            database = importlib.import_module("app.database")
        except ImportError:
            # Not importable as this interpreter is set up: the app root is where the
            # service imports it from, so try there once before giving up.
            if str(APP_ROOT) not in sys.path:
                sys.path.insert(0, str(APP_ROOT))
            config = importlib.import_module("app.config")
            database = importlib.import_module("app.database")
        settings_cls = getattr(config, "Settings", None)
        env_files = tuple(str(p) for p in APP_ENV_FILES if p.exists())
        if settings_cls is not None:
            settings = settings_cls(_env_file=env_files) if env_files else settings_cls()
            raw = str(getattr(settings, "database_url", "") or "").strip()
            to_path = getattr(database, "_db_file_path", None)
            resolved = str(to_path(raw)).strip() if (raw and to_path is not None) else raw
    except Exception:
        resolved = ""
        # A failed `import app.config` can leave a half-initialised `app` package in
        # sys.modules. Drop it, so a later import in this same process is not served a
        # broken module by OUR probe.
        for name in [n for n in list(sys.modules) if n == "app" or n.startswith("app.")]:
            sys.modules.pop(name, None)
    _APP_DB_CACHE.append(resolved)
    return resolved


def app_db_reference(cfg: dict | None = None) -> str:
    """The app's database as a string, resolved with the APP'S OWN PRECEDENCE.

    Order, and why each step sits where it does:

      1. the ENVIRONMENT (`DATABASE_URL` & co). The app's `Settings` reads environment
         variables ABOVE its `.env`, and this keeps that order -- which is also what
         preserves the property the 2026-09-30 note below was protecting: a caller that
         exports `DATABASE_URL` pointing at a throwaway ledger still gets the throwaway.
      2. an explicitly passed `cfg["DATABASE_URL"]`, because a caller's mapping wins over
         everything else in this module. When `cfg` came from `_config()` this is the
         app's own `.env` value.
      3. THE APP'S OWN RESOLVER, when this interpreter can import it.
      4. the app's `.env` through this module's own reader (`_config()`) -- the same file
         -- for the cron interpreter that step 3 could not answer.
      5. `""`, and then `app_db_path()` falls back to `DEFAULT_APP_DB`.
    """
    for key in APP_DB_ENV_KEYS:
        raw = str(os.environ.get(key) or "").strip()
        if raw:
            return raw
    if cfg:
        raw = str(cfg.get("DATABASE_URL") or "").strip()
        if raw:
            return raw
    raw = _app_resolved_db()
    if raw:
        return raw
    return str(_config().get("DATABASE_URL") or "").strip()


def app_db_path(cfg: dict | None = None) -> Path:
    """The app's database: an explicit caller override, then the app's own resolution.

    FIXED 2026-10-13 (WS-STDB). This function used to stop at the environment and then
    return `DEFAULT_APP_DB`, deliberately: the 2026-09-30 note below is why the merged
    config's `DATABASE_URL` was ignored. That note is right about the HAZARD and wrong
    about the CURE. The hazard is an environment override losing to a `.env` value, and
    the cure is ORDER -- environment first, `.env` second -- not blindness. What the
    blindness cost, measured on the authority:

        /usr/bin/python3 -c "import sys;sys.path.insert(0,'/root/bin');import textsend;\\
                             print(textsend.app_db_path())"
        -> /root/personal-secretary-mvp/data/secretary.db   1.8 MB, sms_log=0,
                                                            owner_text_turn=1
        the live app's own resolver -> /root/authority.db   26 GB, sms_log=4103,
                                                            owner_text_turn=92

    So every policy layer in this module -- the 20-minute rate floor, the one-at-a-time
    turn check, the quota, the `sms_log` flood brake -- was reading an EMPTY STALE COPY
    while the app wrote a different database. A stale copy of a database, read and
    believed. 2026-09-30 note, kept because the hazard it records is real:

        Deliberately does NOT look at the merged config's `DATABASE_URL`. That config is
        the app's `.env`, which always names the app's own production database, so reading
        it here would make the value immune to `DATABASE_URL` in the environment --
        measured 2026-09-30, when a test that pointed `DATABASE_URL` at a throwaway ledger
        was served the production database instead and wrote a test turn into it.

    An explicit `app_db`/`app_db_path` key still wins over everything, unchanged.
    """
    cfg = cfg or {}
    for key in ("app_db", "app_db_path"):
        raw = str(cfg.get(key) or "").strip()
        if raw:
            return _as_path(raw)
    raw = app_db_reference(cfg)
    if raw:
        return _as_path(raw)
    return DEFAULT_APP_DB


def _as_path(raw: str) -> Path:
    """One `sqlite:///`, `file:` or plain path, as a filesystem path.

    The app's own `app.database._db_file_path` does this strip and NOTHING else, leaving a
    relative result to be resolved by `sqlite3` against the process's working directory --
    which for the service is `/opt/company` (`systemctl show company-api -p
    WorkingDirectory`). Anchoring a relative result there explicitly is what makes this
    module agree with the app from ANY cwd instead of only from the app's own. Every live
    value is absolute, so this changes nothing on the authority today and removes one more
    way for the two to diverge.
    """
    text = str(raw or "").strip()
    if text.startswith("sqlite:///"):
        text = text[len("sqlite:///"):]
    elif text.startswith("sqlite://"):
        text = text[len("sqlite://"):]
    elif text.startswith("file:"):
        text = text[len("file:"):].split("?")[0]
    path = Path(text)
    if text and not path.is_absolute():
        path = APP_ROOT / path
    return path


#: A store that holds the app's turn ledger has at least one row. ZERO is the signature of
#: the stale copy: measured 2026-10-13, `/root/personal-secretary-mvp/data/secretary.db`
#: had `owner_text_turn = 1` / `sms_log = 0` while `/root/authority.db` had 92 / 4103.
DOCTOR_MIN_TURNS = 1


def _count_rows(path, table: str):
    """`(count, error)`. `count` is None when the answer could not be read."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]), ""
        finally:
            conn.close()
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _same_file(a, b) -> bool:
    """True when two paths are the same file. A missing file is never the same file."""
    try:
        if str(a) == str(b):
            return True
        sa, sb = os.stat(a), os.stat(b)
        return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)
    except OSError:
        return False


def doctor(path=None, *, min_turns: int = DOCTOR_MIN_TURNS, cfg: dict | None = None) -> dict:
    """`doctor` / `--doctor`: is this sender reading the store the LIVE APP writes?

    READ ONLY: two `COUNT(*)`s over read-only connections. It sends nothing, writes
    nothing, and restarts nothing -- it is safe to run on the production box, which is the
    only place the answer matters.

    It reports BOTH PATHS and BOTH ROW COUNTS, because either fact alone reads as a clean
    bill of health: the right path with 0 turns is the stale copy, and 92 turns counted in
    the wrong file is the same defect wearing the right number.

    `ok` is False when: the store is missing; the ledger cannot be read; `owner_text_turn`
    is below `min_turns`; or -- when no explicit `path` was given -- the path this module
    resolves is not the file the app resolves. An empty `sms_log` is reported as a WARNING
    rather than a failure, because a genuinely fresh store has one too.

    Pass `path` to check some other store (a backup, a copy, a candidate); the divergence
    requirement is then not applied, and both paths are still reported side by side.
    """
    cfg = cfg or {}
    resolved = Path(path) if path else app_db_path(cfg)
    app_own = _as_path(app_db_reference({}))
    turns, turns_err = _count_rows(resolved, "owner_text_turn")
    logged, logged_err = _count_rows(resolved, "sms_log")
    same = _same_file(resolved, app_own)

    warnings = []
    if logged == 0:
        warnings.append("sms_log is empty here: a brand-new store looks like this, and so "
                        "does the stale copy")
    if logged_err:
        warnings.append(f"sms_log unreadable: {logged_err}")

    if not resolved.exists():
        ok, detail = False, f"NO STORE at {resolved}"
    elif turns is None:
        ok, detail = False, f"cannot read owner_text_turn in {resolved}: {turns_err}"
    elif turns < min_turns:
        ok, detail = False, (
            f"{resolved} has owner_text_turn = {turns} (minimum {min_turns}): that is the "
            f"shape of a stale copy, not the app's live store")
    elif not path and not same:
        ok, detail = False, (
            f"DIVERGENCE: this sender reads {resolved} while the app resolves {app_own}")
    else:
        ok, detail = True, "this sender and the live app are reading the same store"

    return {"ok": ok, "detail": detail, "textsend_db": resolved, "app_db": app_own,
            "same_file": same, "exists": resolved.exists(), "owner_text_turn": turns,
            "sms_log": logged, "min_turns": min_turns, "warnings": warnings,
            "explicit_path": bool(path)}


def _doctor_report(path=None, *, min_turns: int = DOCTOR_MIN_TURNS) -> int:
    """Print the doctor's verdict as text. Exit 0 = ok, 1 = not ok. Sends nothing."""
    r = doctor(path, min_turns=min_turns)
    host = __import__("socket").gethostname()
    print(f"ws-stdb doctor  host={host}")
    print(f"  textsend reads  : {r['textsend_db']}"
          f"{'' if r['exists'] else '   (MISSING)'}")
    print(f"  app resolves    : {r['app_db']}")
    print(f"  same file       : {'YES' if r['same_file'] else 'NO'}"
          + ("   (not required: an explicit --db was given)" if r["explicit_path"] else ""))
    print(f"  owner_text_turn : {r['owner_text_turn']}   (minimum {r['min_turns']})")
    print(f"  sms_log         : {r['sms_log']}")
    for w in r["warnings"]:
        print(f"  warning         : {w}")
    print(f"  verdict         : {'OK - ' if r['ok'] else 'FAIL - '}{r['detail']}")
    return 0 if r["ok"] else 1


def _parse_stamp(value):
    """A tolerant ISO-8601 parse. Returns an aware datetime or None, never raises."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _reply_window_hours(cfg: dict) -> float:
    raw = _get(cfg, "reply_window_hours", "OWNER_TEXT_REPLY_WINDOW_HOURS")
    try:
        return float(raw) if raw not in (None, "") else LIVE_TURN_WINDOW_HOURS
    except (TypeError, ValueError):
        return LIVE_TURN_WINDOW_HOURS


#: The owner's own rate limit, 2026-10-09, verbatim: "Just in general, text me, let's
#: say once every 20 minutes at most." Mirrors `app/owner_text.py`'s
#: `ENV_MIN_GAP_MINUTES`, and reads the SAME ledger, so the live sender and the app
#: gate cannot disagree about when he was last texted.
ENV_MIN_GAP_MINUTES = "OWNER_TEXT_MIN_GAP_MINUTES"
DEFAULT_MIN_GAP_MINUTES = 20.0


def min_gap_minutes(cfg: dict) -> float:
    """How long after one owner text the next may go. 0 disables the floor."""
    raw = _get(cfg, "min_gap_minutes", ENV_MIN_GAP_MINUTES)
    try:
        return max(0.0, float(raw)) if raw not in (None, "") else DEFAULT_MIN_GAP_MINUTES
    except (TypeError, ValueError):
        return DEFAULT_MIN_GAP_MINUTES


def last_owner_send_at(cfg: dict | None = None):
    """When the owner was last texted, from the ledger of DELIVERED texts.

    `owner_text_turn`, not the decision log: a refusal costs him nothing and must not
    add up to a floor. None FAILS OPEN, deliberately, exactly as `open_owner_turn`
    does -- this is the path the owner actually hears from, and an unreadable ledger
    must not silence him; the app's own gate fails closed on its side.
    """
    try:
        cfg = _config(cfg)
        db = app_db_path(cfg)
        if not db.exists():
            return None
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        try:
            row = conn.execute(
                "SELECT sent_at FROM owner_text_turn ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None                      # pre-migration database: no ledger yet
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return _parse_stamp(row[0])


def rate_floor_verdict(cfg: dict, *, now=None):
    """`(refused, detail)` for the owner's floor. Never raises, never sends.

    Checked BEFORE the turn ledger, because the floor is a limit on the PHONE rather
    than a judgement about importance: it applies to every owner text, including one
    that outranks an open turn. That is deliberate -- it is his own instruction. A
    caller's deliberate `interrupt` for a person or property in danger is handled in
    `send()` itself, not here.
    """
    gap = min_gap_minutes(cfg)
    if gap <= 0:
        return False, ""
    last = last_owner_send_at(cfg)
    if last is None:
        return False, ""
    now = now or datetime.now(timezone.utc)
    age_min = (now - last).total_seconds() / 60.0
    if age_min >= gap:
        return False, ""
    retry_at = last + timedelta(minutes=gap)
    return True, (
        "the owner's rate limit: he was texted %.0f minute(s) ago and asked for at most "
        "one text every %.0f minutes. Queued, not dropped -- it may go at %s."
        % (age_min, gap, retry_at.isoformat())
    )


def open_owner_turn(cfg: dict | None = None) -> dict | None:
    """The owner's unanswered message, if the channel is currently held by one.

    None means the channel is open (no unanswered text, the last one is older than the
    reply window, or the ledger cannot be read). The last case is a deliberate choice:
    an unreadable ledger must not silence the owner, and the app's own `gate()` already
    fails closed on its side, so failing open HERE cannot produce a message the app
    would not also have allowed.

    The row is returned WITH its `reason` and `urgency`, because the caller needs both
    to decide whether the waiting message outranks it (see `may_supersede_open_turn`).
    Selected by column NAME rather than position: this ledger is written by two
    programs in different repositories, and a positional SELECT would silently read
    the wrong column the first time either one adds a field.
    """
    try:
        cfg = _config(cfg)
        db = app_db_path(cfg)
        if not db.exists():
            return None
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        try:
            cur = conn.execute(
                "SELECT * FROM owner_text_turn "
                "WHERE answered_at IS NULL ORDER BY id DESC LIMIT 1"
            )
            cols = [d[0] for d in (cur.description or [])]
            raw = cur.fetchone()
            row = dict(zip(cols, raw)) if raw is not None else None
        except sqlite3.Error:
            return None                      # pre-migration database: no ledger yet
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    sent = _parse_stamp(row.get("sent_at"))
    if sent is None:
        return None
    age_h = (datetime.now(timezone.utc) - sent).total_seconds() / 3600.0
    if age_h >= _reply_window_hours(cfg):
        return None                          # the window has passed; he is not answering
    return {"id": row.get("id"), "sent_at": row.get("sent_at"),
            "body": str(row.get("body") or ""), "reason": str(row.get("reason") or ""),
            "urgency": str(row.get("urgency") or "normal"), "age_hours": round(age_h, 2)}


# ── WHAT MAY SUPERSEDE AN OPEN TURN ───────────────────────────────────────
#
# THIS IS A MIRROR of `app/owner_text.py`'s `owner_text_priority` /
# `_supersedes_open_turn`, and it is here because this sender is a SEPARATE
# PROGRAM with its own copy of the one-at-a-time rule -- `cfo-ask.py` and
# `owner-ask.py` reach the owner through this module, not through the app. Keeping
# only one side fixed is how the 2026-10-06 defect survived its first repair.
#
# MEASURED, the night this was written: the app's email-triage notice labels itself
# `urgent_email`, `urgent` was in `INTERRUPTING_URGENCIES` below, so every triage
# notice skipped the one-at-a-time rule and opened a turn -- and the CFO's question,
# refused here, could not get a word in. 17 consecutive dry runs from
# 2026-10-05T02:00Z, each: "owner conversation open: he has not answered the message
# sent 1.42h ago (turn #54); one at a time". Meanwhile the class being starved is
# the one he actually answers: over the 654 texts that reached his phone since
# 2026-09-01, CFO/money 10 of 16 = 62%, machine alerts 3 of 37 = 8%.
#
# The rule: the waiting message must OUTRANK the open turn. `urgent` is the
# sender's opinion of itself and cannot buy the floor. Lower is more important;
# bands are ten apart so urgency moves a message inside its band by at most one
# step and can never cross into another.
PRIORITY_MONEY = 0        # the owner's own decisions and his money
PRIORITY_OBLIGATION = 1   # an obligation he asked us to hold him to
PRIORITY_OWNER = 2        # a result of work he asked for
PRIORITY_MACHINE = 3      # the company's reading of its own machinery and mail
_BAND_STEP = 10

_MONEY_REASON_MARKERS = (
    "cfo", "owner_ask", "owner-ask", "decision", "approval", "money", "finance",
    "payment", "invoice", "charge", "refund", "payroll", "tax", "bank",
)
_OBLIGATION_REASON_MARKERS = (
    "reminder", "deadline", "obligation", "legal", "contract", "security",
    "intrusion", "alarm", "insurance", "license", "permit", "court", "collection",
)
_MACHINE_REASON_MARKERS = (
    "proactive_update", "urgent_email", "email", "briefing", "mesh", "watchdog",
    "heartbeat", "self_heal", "lifecycle", "tick",
)


def owner_text_priority(reason, urgency: str = "normal") -> int:
    """How important an owner-bound message is. Lower is more important.

    An unrecognised reason is `PRIORITY_OWNER`: burying a new kind of owner message
    silently is the wrong direction of error -- a suppressed CFO question is
    invisible, an extra reminder is merely early.
    """
    key = str(reason or "").casefold()
    band = PRIORITY_OWNER
    if any(m in key for m in _MONEY_REASON_MARKERS):
        band = PRIORITY_MONEY
    elif any(m in key for m in _OBLIGATION_REASON_MARKERS):
        band = PRIORITY_OBLIGATION
    elif any(m in key for m in _MACHINE_REASON_MARKERS):
        band = PRIORITY_MACHINE
    level = str(urgency or "normal").strip().lower()
    # Inside the MACHINE band urgency reorders nothing: one machine notice is not
    # more deserving of the floor than another, and letting a louder one jump a
    # quieter one is the same self-promotion at a smaller scale. Machinery queues in
    # arrival order.
    if band == PRIORITY_MACHINE:
        return band * _BAND_STEP + 1
    return band * _BAND_STEP + (0 if level in ("critical", "stuck", "urgent") else 1)


#: Reasons so generic they say nothing about what a message IS. A turn recorded
#: under one of these is ranked by its BODY instead, because the producer that
#: opened it passed a transport word rather than a class -- measured 2026-10-06:
#: turn #54 is an email-triage notice stored as reason `send_message`, which would
#: otherwise rank it as an owner-facing message and let a routine reminder jump it.
#: ADDED 2026-10-13: `aitext-responder`. It is this sender's own DEFAULT reason when a
#: caller names none (`_get(cfg, "reason", default="aitext-responder")`), so every
#: unlabelled message was ranked by that transport word instead of by what it is.
#: Measured consequence: the CFO's own question, body `CFO [ask-1791862240]: what was
#: 362.51 at newegg ...`, was stored as reason `aitext-responder` - a MACHINE-band label -
#: while `cfo-ask` ranks in the money band. So each new CFO question outranked the
#: unanswered one and took the floor: a second question was sent at 05:00 while the 03:30
#: one was still open, which is the opposite of the owner's one-at-a-time rule and exactly
#: the failure this set exists to prevent. With the label generic, `infer_turn_reason`
#: reads the body's `CFO [ask-` shape and ranks it as the money question it is.
_GENERIC_TURN_REASONS = frozenset(
    {"", "send_message", "owner_update", "notify", "notify_owner", "sms", "auto",
     "aitext-responder"}
)


def effective_turn_reason(reason, body="") -> str:
    """The reason to RANK a turn by: the label if it says something, else its shape."""
    key = str(reason or "").strip().casefold()
    if key in _GENERIC_TURN_REASONS:
        derived = infer_turn_reason(body)
        if derived:
            return derived
    return str(reason or "")


def may_supersede_open_turn(
    held: dict, *, reason, urgency: str = "normal", direct_request: bool = False
) -> tuple:
    """``(True, why)`` when this message may be sent while ``held`` is unanswered."""
    if direct_request:
        return True, "he asked for this message himself (direct_request)"
    # `critical`/`stuck` interrupt on their own -- they are not the label that caused
    # the 2026-10-06 defect, and they are the words a real emergency already uses.
    # `urgent` does not: that is the sender's opinion of itself, and `urgent_email`
    # proved what a sender does with it when it can.
    level = str(urgency or "normal").strip().lower()
    if level in ("critical", "stuck"):
        return True, "urgency '%s' interrupts an open turn by definition" % level
    incoming = owner_text_priority(reason, urgency)
    current = owner_text_priority(
        effective_turn_reason(held.get("reason"), held.get("body")), held.get("urgency")
    )
    if incoming < current:
        return True, (
            "this message outranks the open turn #%s (priority %d vs %d)"
            % (held.get("id"), incoming, current)
        )
    return False, ""


#: The reason shapes this sender already recognises in a body, so a caller that
#: does not name a reason is still ranked correctly. Derived rather than required
#: because the two askers reach this module as a SUBPROCESS through the `send`
#: subcommand, and a missing `--reason` must not silently demote the CFO's money
#: question to an unclassified one. Explicit `reason=` always wins.
_BODY_REASON_SHAPES = (
    ("cfo_ask", re.compile(r"\bCFO\b|\[ask-\d+\]|#ask-\d+\b")),
    ("owner_ask", re.compile(r"^\s*\[q\d+\]")),
    ("reminder", re.compile(r"Reminder\s*[:\-]", re.I)),
    ("urgent_email", re.compile(r"\bemailed about\b", re.I)),
)


def infer_turn_reason(body) -> str:
    """The reason band a body belongs to, from its own shape. `''` when unknown.

    `''` ranks as `PRIORITY_OWNER` -- a message nobody has classified is treated as
    something someone thought worth sending, because burying a new kind of owner
    message silently is the expensive direction of error.
    """
    text = str(body or "")
    for name, pattern in _BODY_REASON_SHAPES:
        if pattern.search(text):
            return name
    return ""


def record_owner_turn(cfg: dict, body: str, *, reason: str, sid: str) -> bool:
    """Open a turn for a text THIS sender just delivered.

    Without this the app's gate would never see this sender's messages, so its
    "one at a time" would be enforced against the wrong history. Returns True when the
    row is written; False is reported by the caller rather than hidden, because a
    silent failure here is exactly the defect this whole mechanism exists to close.
    """
    try:
        db_path = app_db_path(_config(cfg))
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path), timeout=20)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS owner_text_turn ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, sent_at TEXT NOT NULL, body TEXT,"
                "reason TEXT, urgency TEXT, sid TEXT, answered_at TEXT, answer_body TEXT,"
                "answered_code TEXT)"
            )
            conn.execute(
                "INSERT INTO owner_text_turn (sent_at, body, reason, urgency, sid) "
                "VALUES (?, ?, ?, 'normal', ?)",
                (datetime.now(timezone.utc).isoformat(),
                 str(body or "")[:2000], str(reason or "aitext-responder"), str(sid or "")),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def _private_ask_allowlist(cfg: dict) -> set:
    """The named people the owner has authorised a 1:1 question to, on the AI line.

    WHY A NAMED LIST AND NOT A GLOBAL SWITCH (incident 2026-10-18)
        A CFO question about an Audible charge was sent to the owner's wife through
        `app/family_chat/twilio_client.send_message`, so it left from the FAMILY CHAT
        hub number (+17328009174) -- the same number every family message arrives
        from. On her phone it sat in the family thread, and she could not answer it
        privately because a reply looked like it would reach the whole family
        (`sms_log` 4284, sid SM6ec485e94cb83e4db3b757dfb443045a, agent_id
        `family_chat.owner_leg`). The CFO's own questions to the owner come from THIS
        AI line, so the answer she was asked for belonged on this AI line too.

        `can_send_to` already opens for a third party when
        `AITEXT_ALLOW_THIRD_PARTY_SENDS=1` AND the ledger says `allow=auto`. Turning
        that on is a GLOBAL widen: it would also open every number already sitting at
        `allow=auto` (a family line, a brother, a delegate) for outbound. A name-by-name
        list is strictly narrower, and it grants OUTBOUND only -- her inbound stays
        `allow=queue`, so the assistant still does not chat with her on its own. That is
        the whole difference between "the CFO may ask her a question" and "the AI may
        talk to her whenever it likes".
    """
    raw = _get(cfg, "private_ask_allow", "AITEXT_PRIVATE_ASK_ALLOW", default="")
    out = set()
    for part in str(raw or "").replace(";", ",").split(","):
        digits = _digits(part)
        if len(digits) >= 10:
            out.add(digits[-10:])
    return out


def _ledger_allow(phone, cfg: dict) -> str:
    """The ledger's `allow` for a phone, or the honest default. Absence of a row
    is not permission: an unknown number is `queue`, never `auto`."""
    conn = _ro_connect(_db_path(cfg))
    if conn is not None:
        try:
            tail = _digits(phone)[-10:]
            row = conn.execute(
                "SELECT allow FROM permissions WHERE substr(replace(replace(replace("
                "phone,'+',''),'-',''),' ',''),-10)=?", (tail,)).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return "queue"


# --------------------------------------------------------------------------- #
# THE GATE
# --------------------------------------------------------------------------- #
def can_send_to(phone, ctx, config=None) -> tuple:
    """May this system send a text to this number? Returns `(bool, why)`.

    Open for exactly two cases:

      1. the recipient IS the owner's number (`OWNER_PHONE_NUMBER`, or the
         `owner` row in `permissions`); or
      2. `AITEXT_ALLOW_THIRD_PARTY_SENDS=1` in the config AND `ctx["allow"] == "auto"`.

    Everything else - an unknown number, an `allow=queue` friend, a family member
    with `allow=auto`, a caller who passed `ctx=None` - is closed. Never raises:
    an exception from a gate is a gate that might be bypassed by the next caller.
    """
    try:
        cfg = _config(config)
        if not phone or not _digits(phone):
            return False, "no recipient number"
        owner, how = _is_owner(phone, cfg)
        if owner:
            return True, f"recipient is the owner's own number ({how})"
        if _digits(phone)[-10:] in _private_ask_allowlist(cfg):
            return True, ("recipient is on the private-ask allowlist "
                          "(AITEXT_PRIVATE_ASK_ALLOW): a named person the owner has "
                          "authorised a 1:1 question to on this line")
        if not _truthy(_get(cfg, "allow_third_party", "AITEXT_ALLOW_THIRD_PARTY_SENDS",
                            default="0")):
            return False, ("third-party sends are CLOSED: AITEXT_ALLOW_THIRD_PARTY_SENDS "
                           "is not 1 (the default is closed)")
        allow = (ctx or {}).get("allow") if isinstance(ctx, dict) else None
        allow = "queue" if allow in (None, "") else str(allow).strip().lower()
        if allow != "auto":
            return False, f"third-party send refused: the ledger says allow={allow!r}, not 'auto'"
        return True, ("third party: AITEXT_ALLOW_THIRD_PARTY_SENDS=1 and the ledger "
                      "says allow=auto")
    except Exception as exc:  # a gate that raises is a gate that gets skipped
        return False, f"gate error, refusing to send: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# THE OUTBOUND CLASSIFICATION GATE
# --------------------------------------------------------------------------- #
#
# WHY THIS EXISTS. This module is the only transport for anything sent to the owner, and
# it used to transmit whatever body it was handed. Between 2026-09-28 and 2026-10-02 his
# own thread carried three kinds of message that cost him attention and bought nothing:
#
#   * acknowledgement-only bodies -- "Got it - filed as housekeeping#392." (two of them
#     inside one day), "Remembered.", "Captured as a task.";
#   * promise-only bodies -- "Let me pull the current state so I act on the latest info."
#     (after which he texted "Are you still diagnosing?" three times);
#   * an INTERNAL MACHINE INSTRUCTION texted to a person --
#     "[q1790960402] Amazon order history in the ledger is stale (newest order
#      2026-09-10). On the desktop (ZABZ-YOGA) run".
#
# His own words, 2026-10-02 18:58Z: "You literally sent me this text earlier. What the
# hell I think you unified brain broke."
#
# THE CONTRACT. A body bound for an owner number classifies as exactly one of:
#
#   QUESTION  one question only he can answer, already carrying the evidence we gathered
#   RESULT    a conclusion, or the outcome of work he asked for, naming the thing and the
#             answer. A body that carries a concrete specific -- an amount, a card tail,
#             a confirmation number, a phone number, a date -- is an outcome, not chatter.
#   ALERT     something is broken or due and needs him, with what broke and since when
#   ACK       the ONE acknowledgement he asked for in his own words on 2026-09-30 16:12Z
#             ("Did you get my text? Why don't you like confirm so I know you got it or
#             something?"). Admissible ONLY when a caller DECLARES it, and only one caller
#             does: `ack_filed_text`, which is deduped per inbound sid and opens no turn.
#   NOISE     everything else, refused here with a NAMED reason.
#
# WHAT A REFUSAL COSTS, AND WHAT IT DOES NOT. A refusal is not silence and it is not a
# dead end:
#
#   1. IT IS RECORDED, LOUDLY. The body, its hash and the reason go into the channel's own
#      `send_attempt` ledger (outcome='refused', code=<reason>) through the flood guard --
#      the ledger `text-health.py` and the brake already read. No second ledger is invented.
#   2. A GENUINE RESULT INSIDE A NOISY BODY STILL REACHES HIM. The gate SALVAGES: noise
#      sentences are dropped, the substantive core is re-classified, and the core (not the
#      noise) is what goes out. "Got it - that dress purchase is personal, not business.
#      I'll keep it out of the business books. Let me pull the Amazon card details now."
#      sends "that dress purchase is personal, not business." -- the answer he asked for,
#      without the receipt he did not. `AITEXT_NOISE_SALVAGE=0` turns the salvage off, and
#      then the whole body is refused.
#   3. IT SPEAKS TO THE CALLER. The returned dict carries `ok=False`, a named `error`, the
#      `gate` verdict and the `refused` record id, so the asker can see why and fix its own
#      wording -- which is the only place the fix can be made.
#
# AND ONE DELIBERATE ASYMMETRY: A DRY RUN REPORTS, A REAL SEND ENFORCES. A dry run is how a
# caller checks itself before sending; making it refuse would turn "what would you do with
# this body?" into a silent second rule. So a dry run returns ok=True with the verdict in
# `gate_refusal` and a sentence naming it in `detail`; a real send refuses and records.
#
# Everything below is a pure function of the body: no store, no network, no clock.

CLASS_QUESTION = "QUESTION"
CLASS_RESULT = "RESULT"
CLASS_ALERT = "ALERT"
CLASS_ACK = "ACK"
CLASS_NOISE = "NOISE"

#: The refusal reasons. NAMED, not prose, so a week of refusals can be counted and compared
#: (`select code, count(*) from send_attempt where outcome='refused' group by code`).
NOISE_PROBE = "probe"
NOISE_INTERNAL = "internal_instruction"
NOISE_REFERENCE = "ledger_reference"
NOISE_ACK = "acknowledgement_only"
NOISE_PROMISE = "promise_only"
NOISE_RESTATEMENT = "restatement_only"
NOISE_CEILING = "over_ceiling_without_substance"
NOISE_UNCLASSIFIED = "unclassified"
#: A machine ENVELOPE wrapped around a question (`🤖 CEO needs your input`, the
#: `ask_owner` composer's own prefix). The envelope is our bookkeeping, not part of
#: what a person reads, so the body is refused AS HANDED IN and the question inside
#: it is salvaged -- exactly like a bare `[qNNN]` queue reference.
NOISE_ENVELOPE = "machine_envelope"

#: The env switch for the salvage route (see property 2 above). Default ON: refusing a real
#: answer because it was wrapped in an acknowledgement would be the disease, not the cure.
ENV_NOISE_SALVAGE = "AITEXT_NOISE_SALVAGE"

#: A probe is a string this system writes to prove a path works. None of these is ever for
#: the owner, and each one has been texted to him. "test" alone is deliberately NOT in here:
#: it is a 4-character ordinary body, and the DoD in the brief runs `send --body "test"` as
#: its proof that ordinary sending still works.
_PROBE_RE = re.compile(
    r"\b(probe|selftest|self-test|self test|gate failed|turn-ledger probe|ledger probe|"
    r"test string|test message|this is a test|if you see this)\b", re.I)

#: A HOLD, NOT A MESSAGE. The routing acknowledgement the app's SMS auto-reply and the
#: responder send while they work ("I still have your message and I'm routing it now.
#: If this is urgent, text the exact blocker.") is a receipt: it buys him nothing. Its
#: "if this is urgent" clause also made the gate read the body as an ALERT, because
#: `_ALERT_RE` matches a bare `URGENT` anywhere. Measured 2026-10-13: EIGHT delivered
#: copies of that sentence sat in his thread. ANCHORED AT THE START and refused WHOLE:
#: the sentence that would be salvaged is the hold itself, not an answer wrapped in
#: noise, and a real result that merely contains "stand by" must survive.
_HOLD_LEAD_RE = re.compile(
    r"^\s*(?:i\s+)?(?:still have your message|have your message and i'?m routing|"
    r"i'?m routing (?:it|this|your message)|routing (?:it|this) now|"
    r"still working on (?:it|this)|working on (?:it|this) now|"
    r"hang tight|sit tight|stand by|i'?ll (?:get back|follow up) (?:to )?you)\b", re.I)

#: MACHINE TELEMETRY HANDED TO A PERSON. The voice system's private call summaries
#: ("📞 Call escalation from ...: Call summary — private ...:\n<transcript>") are an
#: internal record of a call, not a message the owner can act on -- measured
#: 2026-10-13, six of them delivered inside the replayed window, classified RESULT
#: because they happen to contain a fact. Refused WHOLE, anchored at the start so a
#: real alert that merely mentions a call survives.
_TELEMETRY_RE = re.compile(
    r"^\s*(?:📞\s*|\U0001F4DE\s*)?Call (?:escalation|summary)\b|"
    r"^\s*(?:📞\s*|\U0001F4DE\s*)?Escalation from\b", re.I)

#: A COURTESY CLOSE. "If there's anything else you need, just let me know!" is what a
#: model appends to a reply; it is a receipt with a question mark's manners, not an
#: answer. Measured 2026-10-13: the gate refused "Got it! I will stop sending you
#: reminders. If there's anything else you need, just let me know!" and then SALVAGED
#: the courtesy line, so the receipt went out anyway. Deliberately narrow (`anything
#: else`, an exact `just let me know`, thanks alone) so "Let me know if the $50 is
#: right" -- a real ask carrying a fact -- is untouched.
_COURTESY_RE = re.compile(
    r"^\s*(?:if\s+)?(?:there'?s\s+|there\s+is\s+|is\s+)?(?:anything|something)\s+else\b|"
    r"^\s*just let me know[!.,\s]*$|"
    r"^\s*(?:if you need anything|let me know if you need)\b|"
    r"^\s*(?:thanks|thank you|cheers)[!.,\s]*$", re.I)

#: THE MACHINE ENVELOPE the `ask_owner` composer puts on an owner question. See
#: `NOISE_ENVELOPE`: it is stripped and the question is salvaged, so the row is refused
#: and the question still reaches him.
_ENVELOPE_RE = re.compile(
    r"^\s*(?:🤖|🚧|🔴|⚠️|❗)?\s*(?:CEO needs your input|CEO is STUCK and needs help|"
    r"URGENT\s*[—\-–]\s*CEO needs a decision|CEO needs a decision)\b", re.I)
_ENVELOPE_STRIP_RE = re.compile(
    r"^\s*(?:🤖|🚧|🔴|⚠️|❗)?\s*(?:CEO needs your input|CEO is STUCK and needs help|"
    r"URGENT\s*[—\-–]\s*CEO needs a decision|CEO needs a decision)\s*[:,\-—–]?\s*", re.I)

#: AN INSTRUCTION TO A MACHINE, A SESSION OR A REPO. These are dropped from any body, however
#: it is framed, because none of them is ever something a person reads: a guardrail aimed at
#: a session ("Do NOT re-ask declined questions (section 6a)"), the hand-off note ("Ask owner
#: ONCE in conversation", "Record result in docs/..."), the runner's own verb ("re-run"),
#: and an internal task/row reference ("Task #26089").
_AGENT_IMPERATIVE_RE = re.compile(
    r"(record result in|ask owner once|on the desktop|in conversation|re-?run\b|"
    r"do not (?:re-?ask|re-?send|re-?text|send anything|outbound)|"
    r"never (?:re-?ask|re-?send)|section \d+[a-z]?\b|next tick|wake flag|"
    r"\b(?:task|item|row|issue|ledger|probe)\s*#\d+\b|\btask\s+\d{3,}\b)", re.I)

#: A sentence that OPENS with an imperative and names a machine is an instruction to us, not
#: a request of him -- "Run the scrape on ZABZ-YOGA", "ssh in and check the log" -- even when
#: the body also says "tell me".
_LEADING_IMPERATIVE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:run|re-?run|rerun|execute|scp|ssh|fetch|refresh|resync|re-?scrape|"
    r"delete|drop|truncate|restart|deploy)\b", re.I)

#: A MENTION of a machine: a path, a host, a file suffix, our jargon. This one is
#: context-dependent ON PURPOSE, and that is the fix for the first version of this gate.
#: Measured 2026-10-02 against the 22 pending questions in the owner's queue: a plain
#: sentence-level test dropped the EVIDENCE and the RECOMMENDATION out of five genuine
#: questions -- "sign in to Amazon once on the ZABZ-YOGA laptop", "Keep 70 USD/day ... (25.0
#: in wake.py, 70.00 in the dispatcher)", "Attach a second disk ... secretary.db" -- and a
#: refused question is a question he never gets asked. So a mention is noise only when the
#: body asks him NOTHING; a body that asks him something is a message about the machine, and
#: those five questions are exactly the kind of thing only he can decide.
_MACHINE_MENTION_RE = re.compile(
    r"(~/|\$HOME|/home/|/tmp/|/var/|/etc/|/opt/|\bC:\\)"
    r"|\b(ZABZ-YOGA|ZABZ-TECH|zabz-tech-linux|secratary)\b"
    r"|\b(crontab|cron|systemd|journalctl|scp|ssh|sqlite3|python3|pwsh|bash)\b"
    r"|\.py\b|\.sh\b|\.db\b|\.md\b|\bdocs/[a-z0-9._-]+/"
    r"|\b(the session|this session|the tick|the runner|the dispatcher)\b"
    r"|\b(is|are|went|has gone|has been)\s+stale\b|\bstale\b"
    r"|\b(last sync|the sync|the scrape|resync|re-?scrape|no scrape has run)\b"
    # OUR OWN RUNTIME'S STATUS LINES. Measured 2026-10-08: the owner texted
    # "How many books do we have to get back?" and the app's SMS reply was
    # "[Budget exceeded for : ceoreserveexhausted]" -- a budget pre-flight error
    # handed to a person, twice. A status about our own machinery is not a message
    # to him, and a bracket-wrapped one is a machine artifact by construction. The
    # phrases are the *class* (budget/quota/cap/reserve/circuit exhausted), not the
    # one string that happened to leak; and `_noise_sentence_code` still exempts a
    # body that ASKS him something, so a real question about the budget survives.
    r"|\b(?:budget|quota|cap)\s+(?:exceeded|exhausted|depleted|reached|blocked)\b"
    r"|\b(?:reserve|pool)\s+(?:exceeded|exhausted|depleted)\b"
    r"|\bceo[ _-]?reserve\b|\bcircuit[- ]?(?:broken|open|half)\b"
    r"|\bvelocity_exceeded\b|\branaway_loop\b|\bhard\s+deadlock\b"
    r"|\bno\s+(?:budget|quota)\s+(?:left|remaining)\b"
    r"|\bbudget\s+(?:block|reset|limit)\b"
    r"|^\s*\[[^\]]{0,120}\b(?:exceeded|exhausted|blocked|circuit|budget|quota)\b[^\]]{0,120}\]\s*$",
    re.I)

#: A REMINDER IS LEGITIMATE WHEN THE OWNER ASKED FOR IT; it is a WORK ORDER when it
#: carries a repo path, a file or an agent imperative. Measured 2026-10-06: three
#: "Reminder: Pay Yisroel Weinberg ..." texts reached the owner, each naming
#: "lpt-hub/docs/operations/payroll/..." and instructing "Do NOT run Gusto off-cycle".
#: The gate refused the wrapper and SALVAGED the core, so the work order still went out.
_REMINDER_LEAD_RE = re.compile(r"^\s*\S{0,3}\s*Reminder\s*[:\-]", re.I)

#: A body that declares itself one-way. "Automated alert - no reply needed." is the exact
#: shape an external heartbeat uses for a status line; it is not a message unless it names
#: a condition that needs him (see the ALERT check), so it must not leave his channel.
_ONE_WAY_NOTICE_RE = re.compile(
    r"\b(?:automated (?:alert|message|notice|report)|"
    r"no reply (?:needed|required|necessary)|do not reply|don'?t reply|"
    r"no action (?:needed|required)|no response (?:needed|required))\b", re.I)

#: The two reference shapes this system puts in front of a question. `[ask-N]`/`#ask-N` is
#: the CFO/owner-ask reference; `[q<epoch>]` is what `owner-ask.py` composes. A body that
#: opens with one of them is a QUEUE ROW, not a message: it is a question only if it asks.
_ASK_TOKEN_RE = re.compile(r"\[ask-\d+\]|#ask-\d+\b|\bask-\d{6,}\b", re.I)
_BARE_REF_LEAD_RE = re.compile(r"^\s*(?:\[q\d+\]|\[ask-\d+\]|#ask-\d+)\s*[:,-]?\s*", re.I)

_QUESTION_MARK_RE = re.compile(r"[?\uFF1F]")
#: Phrases that ask him to answer, with or without a question mark -- the askers in this
#: system compose "Reply 'yes' - or tell me what it was", which is a question.
_ANSWER_REQUEST_RE = re.compile(
    r"\b(reply|respond|say yes|say no|tell me|let me know|your call|which one|"
    r"should i|do you want|want me to|can you|will you|are you|did you|is it|"
    r"i recommend|recommend:|i'd file it|i would file it)\b", re.I)

#: AN ASK CAN BE NEGATED, and the first version of this gate read the negation as the
#: ask. "Automated alert - no reply needed." contains "reply", so the ask regex matched
#: and a one-way monitor notice was admitted as a QUESTION (measured 2026-10-06: an
#: external heartbeat body saying exactly that, sent to the owner). A negated ask asks
#: him nothing, so the phrase comes off before the ask is looked for.
_NEGATED_ASK_RE = re.compile(
    r"\b(?:no|not|don'?t|do not|doesn'?t|never|without)\s+"
    r"(?:reply|respond|response|answer|action|need(?:ed)?|require(?:d)?)\b"
    r"|\bno\s+(?:reply|response|answer|action)\b", re.I)

#: Something needs him. Each marker is a thing this system has actually texted him about:
#: a lapsed policy, a collector, a suspended account, a dead process, an overdue form.
_ALERT_RE = re.compile(
    r"(⚠|\U0001F6A8|\bURGENT\b|\bdeadline\b|\boverdue\b|\bpast (?:its|the|due)\b|"
    r"\bexpired\b|\brevoked\b|\blapsed\b|\bsuspend(?:ed|ing)?\b|\bcollector\b|"
    r"\bcollections?\b|\bno (?:fire|cover)\b|\bis down\b|\bwent down\b|\bwent missing\b|"
    r"\bhas died\b|\bprocess died\b|\bdied\b|\bdead\b|\bcrash(?:ed|ing)?\b|"
    r"\brestart(?:ing|ed)?\b|\bbroken\b|\bbroke\b|\bfail(?:ed|ing|ure)\b|\boutage\b|"
    r"\bunreachable\b|\bblocked\b|\bnot answering\b|\bneeds? (?:you|your)\b)", re.I)

#: A concrete fact about the real world. One of these is the difference between "an outcome"
#: and "chatter": it is what makes a body worth his attention and what an asker must supply.
_SPECIFICS = (
    ("amount", re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})*\.\d{2}\b")),
    ("phone", re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("card_tail", re.compile(r"\bend(?:s|ing)?(?: in| with)?\s+\d{3,4}\b", re.I)),
    ("reference", re.compile(
        r"\b(?:confirmation|order|reservation|ticket|invoice|account|bill|form|policy|"
        r"claim|booking|reference|ref)\s*(?:number|no\.?|#|id|:)?\s*[A-Z0-9][A-Z0-9-]{3,}\b",
        re.I)),
    ("date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
    ("url", re.compile(r"https?://\S+|\b[a-z0-9-]+\.(?:com|net|org|gov|io|co)\b", re.I)),
)

#: Verdicts that report work that actually happened. Not required for a result -- a
#: specific fact is enough -- but they are why an unadorned sentence is admitted below.
_RESULT_VERB_RE = re.compile(
    r"\b(checked|pulled|found|fixed|researched|filed|recorded|confirmed|corrected|"
    r"reconciled|resolved|closed|replied|verified|reversed|matched|updated|noted|"
    r"correcting|turns out|no longer|already on record|nothing to)\b", re.I)

#: Bodies that are nothing but a receipt for having read him. Each one has been sent.
_ACK_PREFIX_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|got it|gotcha|noted|remembered|captured(?: as a task)?|understood|"
    r"acknowledged|already (?:on it|filed)|on it|filed as|logged as|i have it|i'?ve got it|"
    r"thanks|thank you|sure|sounds good|will do|done)\b", re.I)

#: The beginning of work, which is not a message. Rule 2 of the workstream brief: the work
#: runs and its RESULT is what goes out. "I will NOT write the PIN into any document" is a
#: statement of restraint, not the beginning of work, and it stays.
_PROMISE_RE = re.compile(
    r"^\s*(?:and\s+)?(?:let me|i'?ll(?!\s+not\b)\b|i will(?!\s+not\b)\b|i'?m going to\b|"
    r"i am going to\b|i'?m on it\b|i am on it\b|working on it\b|pulling\b|digging\b|"
    r"diagnosing\b|checking now\b|looking into|starting now\b|stand by\b|hang on\b|"
    r"one moment\b|give me (?:a|one) (?:minute|moment|sec))\b", re.I)

#: Sentences that only repeat his own words back at him. Refused on their own, kept when
#: they carry a fact (see `_has_substance`).
_RESTATE_RE = re.compile(
    r"^\s*(?:you'?re right|you are right|you'?d already|you already|as you said|"
    r"i should have|my (?:mistake|apologies)|sorry|apologies)\b", re.I)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text) -> list:
    """The body, one sentence at a time. A whole body is judged by its sentences: that is
    what lets the gate keep the answer and drop the receipt around it."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(str(text or "")) if s.strip()]


def _has_question(text) -> bool:
    return bool(_QUESTION_MARK_RE.search(text or ""))


def _ws(text) -> str:
    """The body with its whitespace collapsed. Used to compare a body with its own core:
    a body that only had its newlines joined has NOT been salvaged, and saying it was
    would make every multi-line message look like a refusal."""
    return " ".join(str(text or "").split())


def _specifics(text) -> list:
    """The names of every concrete fact in the body ('amount', 'card_tail', ...)."""
    return [name for name, rx in _SPECIFICS if rx.search(text or "")]


def _has_substance(text) -> bool:
    """Is there anything in this sentence a person would be glad to have read?"""
    return bool(_specifics(text)) or _has_question(text)


def _asks_him(text) -> bool:
    """Does the WHOLE body ask him something? The answer decides whether a machine mention
    inside it is jargon or an instruction (see `_MACHINE_MENTION_RE`)."""
    t = _NEGATED_ASK_RE.sub(" ", str(text or ""))
    return bool(_has_question(t) or _ANSWER_REQUEST_RE.search(t)
                or _ASK_TOKEN_RE.search(t))


def _noise_sentence_code(sentence, *, body_asks: bool = False) -> str:
    """The reason this ONE sentence is not worth his phone, or '' when it is.

    Order matters. A probe is a probe even if it is 300 characters of prose; an instruction
    to a session is not excused by ending in a question mark ("Ask owner ONCE in
    conversation: did the groin rash clear?" is a machine's note, not a message); and a
    mention of a machine is only noise when the body asks him nothing at all.
    """
    t = str(sentence or "").strip()
    if not t:
        return ""
    if _PROBE_RE.search(t):
        return NOISE_PROBE
    if _AGENT_IMPERATIVE_RE.search(t):
        return NOISE_INTERNAL
    if _LEADING_IMPERATIVE_RE.match(t) and _MACHINE_MENTION_RE.search(t):
        return NOISE_INTERNAL
    if _MACHINE_MENTION_RE.search(t) and not body_asks:
        return NOISE_INTERNAL
    if _PROMISE_RE.match(t) and not _specifics(t):
        return NOISE_PROMISE
    if _COURTESY_RE.match(t) and not _specifics(t) and not _has_question(t):
        return NOISE_ACK
    if _ACK_PREFIX_RE.match(t) and not _has_substance(t):
        return NOISE_ACK
    if _RESTATE_RE.match(t) and not _has_substance(t):
        return NOISE_RESTATEMENT
    return ""


def _strip_noise_prefix(sentence, *, body_asks: bool = False) -> str:
    """Drop a leading queue reference and a leading receipt word from a sentence that
    carries something, so the salvage reads like a sentence and not like a log line.

    Re-checked after each strip: "Got it - filed as housekeeping#392." must not survive as
    "filed as housekeeping#392." -- an acknowledgement with its hat taken off.
    """
    t = str(sentence or "").strip()
    for _ in range(3):
        before = t
        t = _BARE_REF_LEAD_RE.sub("", t).strip()
        t = _ACK_PREFIX_RE.sub("", t).strip()
        t = _RESTATE_RE.sub("", t).strip()
        t = re.sub(r"^[\s,;:.\-\u2013\u2014]+", "", t).strip()
        if t == before:
            break
        if _noise_sentence_code(t, body_asks=body_asks):
            return ""
    # Stripping "Got it" off "Got it!" leaves "!", which is not a sentence and used to be
    # KEPT and joined onto the next one (measured 2026-10-13: the salvage of a receipt came
    # out as "! If there's anything else you need…"). A core with no letter or digit is
    # nothing.
    if t and not re.search(r"[A-Za-z0-9]", t):
        return ""
    return t


def _sentence_core(sentence, *, body_asks: bool = False) -> tuple:
    """`(kept_text, noise_code)` for ONE sentence.

    A sentence that is nothing but a receipt, a promise or a machine instruction is dropped
    whole. A sentence that LEADS with a receipt and then says something -- "Got it - that
    dress purchase is personal, not business." -- is kept with the receipt stripped off,
    because that sentence is the whole reason the salvage route exists.
    """
    s = str(sentence or "").strip()
    # A courtesy close is dropped WHOLE: there is no prefix to strip off it, so the
    # NOISE_ACK salvage route below would KEEP it and send the receipt on its own
    # (measured 2026-10-13: "...anything else you need, just let me know!" was the only
    # thing salvaged out of a pure acknowledgement). See `_COURTESY_RE`.
    if _COURTESY_RE.match(s) and not _specifics(s) and not _has_question(s):
        return "", NOISE_ACK
    code = _noise_sentence_code(s, body_asks=body_asks)
    if code and code not in (NOISE_ACK, NOISE_RESTATEMENT):
        return "", code
    cleaned = _strip_noise_prefix(s, body_asks=body_asks)
    if not cleaned:
        return "", (code or NOISE_ACK)
    # A short sentence is NOT dropped here: "Checked it." carries real work and belongs in
    # the core. Only the core as a whole is judged for substance, below -- dropping each
    # sentence on its own length would report a normal message as salvaged.
    return cleaned, ""


def _classify_positive(text) -> tuple:
    """`(class, code, reason)` for a body that is not noise, or None when it is nothing.

    A refusal is EXPENSIVE -- it silences a person -- so the last resort is generous: a
    plain sentence of at least three words is admitted as a reported fact. What is NOT
    generous is the floor: a body with no question, no fact and no sentence ("test") has
    nothing to say to him and is refused.
    """
    t = str(text or "").strip()
    if _ASK_TOKEN_RE.search(t):
        return (CLASS_QUESTION, "question_with_ask_reference",
                "it is one of our own composed asks (an [ask-N] reference) and it carries "
                "its evidence")
    if _has_question(t) and not _AGENT_IMPERATIVE_RE.search(t):
        return (CLASS_QUESTION, "question_asked",
                "it asks him something and is not an instruction to a machine")
    if _ANSWER_REQUEST_RE.search(_NEGATED_ASK_RE.sub(" ", t)):
        return (CLASS_QUESTION, "answer_requested",
                "it asks him to answer or to choose, with or without a question mark")
    if _ALERT_RE.search(t):
        return (CLASS_ALERT, "alert_needs_him",
                "it reports something broken, due or blocked, and names it")
    found = _specifics(t)
    if found:
        return (CLASS_RESULT, "result_with_specifics(" + ",".join(found) + ")",
                "it reports an outcome and carries the facts that make it checkable: "
                + ", ".join(found))
    if _RESULT_VERB_RE.search(t) and len(t) >= 15 and len(t.split()) >= 3:
        return (CLASS_RESULT, "reported_outcome",
                "it reports work that was done")
    if len(t) >= 15 and len(t.split()) >= 3:
        return (CLASS_RESULT, "reported_fact",
                "a plain statement of fact: admitted because a refusal silences a person, "
                "and there is nothing here that costs him attention without buying something")
    return None


def _ack_shaped(text, ceiling: int) -> bool:
    """Is this body the ONE acknowledgement the owner asked for?

    Short, a receipt and nothing else, asks nothing. `ack_filed_text` builds exactly this
    ("Got it - filed as LPT#4242."), deduped per inbound sid, and it is the only caller
    that may declare it.
    """
    t = str(text or "").strip()
    return bool(t) and len(t) <= int(ceiling or APP_OWNER_TEXT_CEILING) \
        and bool(_ACK_PREFIX_RE.match(t)) and not _has_question(t) \
        and not _specifics(t) and len(_sentences(t)) == 1


def classify_owner_body(body, *, declared_class=None, ceiling=None) -> dict:
    """Classify ONE owner-bound body. Pure: no store, no network, no clock.

    Returns `{body, chars, cls, code, reason, refused, salvaged, send_body, dropped,
    specifics}`.

    `refused` means "the body AS HANDED IN may not be sent": either it is noise, or it was
    noise wrapped around a real answer. `send_body` is what may actually go out -- the body
    itself when it was clean, the salvaged core when it was not, and None when there is
    nothing worth sending. A caller that ignores `refused` still cannot send noise, because
    `send()` enforces this before it touches a transport.
    """
    text = str(body or "").strip()
    # TYPOGRAPHIC APOSTROPHES ARE WHAT THE MODEL ACTUALLY EMITS; every pattern in this
    # file is written with the ASCII one. Normalise the character rather than every
    # pattern: measured 2026-10-13, "Understood. I’ll set a reminder for one week from
    # now to revisit this." (U+2019) was NOT seen as a promise, so the gate refused the
    # receipt and then SALVAGED the promise and sent it -- the exact sentence the wake
    # named. Normalising here also fixes `don’t`, `I’ve`, `it’s` and the rest.
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    if ceiling is None:
        ceiling = APP_OWNER_TEXT_CEILING
    try:
        ceiling = int(ceiling)
    except (TypeError, ValueError):
        ceiling = APP_OWNER_TEXT_CEILING
    out = {"body": text, "chars": len(text), "cls": None, "code": "", "reason": "",
           "refused": False, "salvaged": None, "send_body": None, "dropped": [],
           "specifics": [], "trimmed": False, "lead_reference": False}
    if not text:
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_UNCLASSIFIED,
                   reason="empty body: there is nothing here for him to read")
        return out

    declared = str(declared_class or "").strip().upper()
    if declared == CLASS_ACK:
        if _ack_shaped(text, ceiling):
            out.update(cls=CLASS_ACK, code="ack_owner_requested", send_body=text,
                       reason=("the one acknowledgement he asked for on 2026-09-30, declared "
                               "by the caller that owns it (ack_filed_text): %d chars, asks "
                               "nothing, opens no turn" % len(text)))
            return out
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_UNCLASSIFIED,
                   reason=("declared %s, but the body is not that shape (it must be one "
                           "short receipt sentence, asking nothing, within %d chars): a "
                           "declared class has to be earned, not asserted"
                           % (CLASS_ACK, ceiling)))
        return out

    # A body that OPENS with a bare queue reference (`[q1790960402] ...`) is a queue row
    # read aloud, not a message. Its reference is a machine artifact that is never part of
    # anything a person reads, so it comes off either way -- and if what is left asks him
    # nothing, the row is refused as a row (NOISE_REFERENCE) and only its answer is sent.
    lead_reference = bool(_BARE_REF_LEAD_RE.match(text))
    body_asks = _asks_him(text)

    # ── 0a. THE MACHINE ENVELOPE IS NOT PART OF THE MESSAGE ────────────────
    # `🤖 CEO needs your input` is the `ask_owner` composer's own prefix -- our
    # bookkeeping, like a `[qNNN]` reference. It comes off BEFORE the body is judged, so
    # the question inside is classified on its merits; the row is still REFUSED as handed
    # in (NOISE_ENVELOPE) and the question is what goes out. See step 2c.
    envelope = bool(_ENVELOPE_RE.match(text))
    if envelope:
        text = _ENVELOPE_STRIP_RE.sub("", text, count=1).strip()
        body_asks = _asks_him(text)
        lead_reference = bool(_BARE_REF_LEAD_RE.match(text))
        out["envelope"] = True

    # ── 0. A REMINDER THAT IS A WORK ORDER, NOT A MESSAGE ──────────────────
    # Refused WHOLE (no salvage): the sentence that would be salvaged is the work order
    # itself, not an answer wrapped in noise. See `_REMINDER_LEAD_RE`.
    if _REMINDER_LEAD_RE.match(text) and (_MACHINE_MENTION_RE.search(text)
                                          or _AGENT_IMPERATIVE_RE.search(text)):
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_INTERNAL,
                   reason=_NOISE_REASONS[NOISE_INTERNAL] % {"body": text[:110],
                                                            "limit": ceiling})
        return out

    # ── 0b. A HOLD OR A PRIVATE CALL SUMMARY, NOT A MESSAGE ────────────────
    # Refused WHOLE (no salvage), for the same reason as the work-order reminder: the
    # only sentences inside them are the hold/telemetry itself. Measured 2026-10-13:
    # eight copies of the routing hold and six private call summaries had reached him.
    if _HOLD_LEAD_RE.match(text):
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_ACK,
                   reason=_NOISE_REASONS[NOISE_ACK] % {"body": text[:110],
                                                       "limit": ceiling})
        return out
    if _TELEMETRY_RE.match(text):
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_INTERNAL,
                   reason=_NOISE_REASONS[NOISE_INTERNAL] % {"body": text[:110],
                                                            "limit": ceiling})
        return out
    kept, dropped, ref_stripped = [], [], False
    for sentence in _sentences(text):
        had_ref = bool(_BARE_REF_LEAD_RE.match(sentence))
        cleaned, code = _sentence_core(sentence, body_asks=body_asks)
        if code:
            dropped.append((code, sentence[:160]))
            continue
        if had_ref and not _BARE_REF_LEAD_RE.match(cleaned):
            ref_stripped = True
        kept.append(cleaned)
    core = " ".join(kept).strip()
    out["lead_reference"] = lead_reference
    out["dropped"] = dropped
    out["body_asks"] = body_asks

    # ── 1. Nothing substantive survived the noise ──────────────────────────
    if not core or len(core) < 15 or len(core.split()) < 3:
        if dropped:
            code, detail = dropped[0][0], dropped[0][1]
        elif lead_reference:
            code, detail = NOISE_REFERENCE, text[:160]
        elif len(text) > ceiling:
            code, detail = NOISE_CEILING, text[:160]
        else:
            code, detail = NOISE_UNCLASSIFIED, text[:160]
        out.update(cls=CLASS_NOISE, refused=True, code=code, dropped=dropped,
                   specifics=_specifics(core),
                   reason=_NOISE_REASONS[code] % {"body": detail[:110], "limit": ceiling})
        return out

    # ── 2. The core is not a QUESTION, a RESULT or an ALERT ────────────────
    positive = _classify_positive(core)
    if positive is None:
        code = (NOISE_REFERENCE if lead_reference
                else NOISE_CEILING if len(text) > ceiling else NOISE_UNCLASSIFIED)
        out.update(cls=CLASS_NOISE, refused=True, code=code, dropped=dropped,
                   reason=_NOISE_REASONS[code] % {"body": core[:110], "limit": ceiling})
        return out

    cls, code, reason = positive

    # ── 2b. A ONE-WAY NOTICE IS A STATUS LINE, NOT A MESSAGE ───────────────
    # The ALERT class is exempt: "the company is DOWN ... no reply needed" DOES need him,
    # and the brief admits an ALERT. What is refused is the notice that names no condition
    # needing him ("the company is BACK", "the guard answered 307") while saying, in its own
    # words, that no reply is expected. See `_ONE_WAY_NOTICE_RE`.
    if cls != CLASS_ALERT and not _has_question(core) and _ONE_WAY_NOTICE_RE.search(core):
        _m = _ONE_WAY_NOTICE_RE.search(core)
        out.update(cls=CLASS_NOISE, refused=True, code=NOISE_UNCLASSIFIED,
                   dropped=dropped, specifics=_specifics(core),
                   reason=("it declares itself a one-way notice (%r) and asks him nothing: "
                           "a status line is not a message he can act on"
                           % (_m.group(0)[:60] if _m else "")))
        return out
    out.update(cls=cls, code=code, reason=reason, specifics=_specifics(core))

    # ── 2c. THE MACHINE ENVELOPE WAS REFUSED AS HANDED IN; THE QUESTION GOES ─
    # A genuine question that arrived wrapped in `🤖 CEO needs your input` is a real
    # question (it must not be silenced) and a queue row sent verbatim (it must not be
    # sent as a row). So the wrapper is refused and RECORDED, and the question without
    # the envelope is what goes out -- the same bargain as a bare `[qNNN]` reference.
    if envelope:
        out.update(refused=True, code=NOISE_ENVELOPE, salvaged=core, send_body=core)
        out["reason"] = (_NOISE_REASONS[NOISE_ENVELOPE] % {"body": out["body"][:110],
                                                           "limit": ceiling}
                         + "; salvaged: the question goes out without the envelope: %r"
                           % core[:160])
        return out

    # ── 3. A queue row that asks him nothing is a reference, not a message ──
    if lead_reference and not (
            _has_question(text)
            or _ANSWER_REQUEST_RE.search(_NEGATED_ASK_RE.sub(" ", text))
            or _ASK_TOKEN_RE.search(text)):
        out.update(refused=True, code=NOISE_REFERENCE, salvaged=core, send_body=core)
        out["reason"] = (_NOISE_REASONS[NOISE_REFERENCE] % {"body": text[:110],
                                                           "limit": ceiling}
                         + "; salvaged: the answer inside it goes out without the queue "
                           "reference: %r" % core[:160])
        return out

    # ── 4. Noise sentences were dropped: refuse the wrapper, send the answer ─
    if dropped:
        out.update(refused=True, code=dropped[0][0], salvaged=core, send_body=core)
        out["reason"] += ("; REFUSED AS HANDED IN and salvaged: %d noise sentence(s) were "
                          "dropped (%s). The body that goes out is %r"
                          % (len(dropped), ", ".join(sorted({c for c, _ in dropped})),
                             core[:160]))
        return out

    # ── 5. Clean, except that a machine reference came off the front ────────
    if ref_stripped:
        out.update(send_body=core, trimmed=True)
        out["reason"] += ("; the leading queue reference was removed before sending: it is "
                          "part of our bookkeeping, not part of the question")
        return out

    out["send_body"] = text
    return out


#: One plain-English reason per refusal code. `%{body}` is the sentence that caused it.
_NOISE_REASONS = {
    NOISE_PROBE: "it is a probe this system writes to test itself, not a message to a "
                 "person: %(body)r",
    NOISE_INTERNAL: "it is an instruction to a machine, a path or a status about our own "
                    "data, not something a person reads: %(body)r",
    NOISE_REFERENCE: "it is a bare queue/ledger reference with no question in it: %(body)r",
    NOISE_ACK: "it only acknowledges him ('%(body)s'): a receipt is not a message, and the "
               "answer he asked for is still owed",
    NOISE_PROMISE: "it only promises work ('%(body)s'): the work runs and its RESULT is "
                   "what goes out, never the promise",
    NOISE_RESTATEMENT: "it only repeats his own words back to him: %(body)r",
    NOISE_ENVELOPE: "it arrived in the machine envelope our own ask_owner composer puts "
                    "on a queue row ('%(body)s'): the envelope is our bookkeeping, not "
                    "part of a message",
    NOISE_CEILING: "it is over his %(limit)d-char one-text ceiling and carries no question "
                   "and no result to fit to: %(body)r",
    NOISE_UNCLASSIFIED: "it is not a QUESTION, a RESULT or an ALERT -- there is nothing in "
                        "it for him to read: %(body)r",
}


def noise_salvage_enabled(cfg: dict | None = None) -> bool:
    """Is the salvage route on? `AITEXT_NOISE_SALVAGE=0/no/off/false` turns it off.

    On by default, because the alternative -- refusing "Got it - the $299.29 is your mom's
    Amex" outright -- throws away the answer along with the receipt.
    """
    raw = str(os.environ.get(ENV_NOISE_SALVAGE,
                             (cfg or {}).get("noise_salvage", "1"))).strip().lower()
    return raw not in ("0", "no", "off", "false")


def gate_refusal_text(verdict: dict) -> str:
    """The sentence a caller (and the log) gets back when the gate refuses a body."""
    v = verdict or {}
    return ("the outbound gate refused this body: %s -- %s"
            % (v.get("code") or "unclassified", v.get("reason") or "no reason recorded"))


def _record_gate_refusal(cfg: dict, to_e164: str, body, verdict: dict) -> dict:
    """Write the refusal where refusals already live: `send_attempt` in the channel store.

    Not silent, and not a second ledger. `flood.note` is the module that owns that table and
    it is the same call the sender already makes for `no_credentials`; a refusal an operator
    cannot see a week later is a refusal that never happened.
    """
    code = (verdict or {}).get("code") or NOISE_UNCLASSIFIED
    detail = (verdict or {}).get("reason") or "refused by the outbound classification gate"
    note = {}
    if flood is not None:
        note = _flood_note(cfg, to_e164, body, "refused", code=code, detail=detail[:500])
    if not note:
        print("textsend: REFUSED an owner-bound body (%s) and the attempt ledger could not "
              "be written (owner_flood_guard.py is not available in this tree): %s"
              % (code, str(body or "")[:80]), file=sys.stderr)
    return note


# --------------------------------------------------------------------------- #
# Body hygiene: signature, and SMS segments
# --------------------------------------------------------------------------- #
def is_signed(body) -> bool:
    """Does the body end with a line reading exactly `- Daniel`? (L1976)"""
    text = str(body or "").rstrip()
    if not text:
        return False
    return text.splitlines()[-1].rstrip() == SIGNATURE


def _split_signature(body: str) -> tuple:
    """(head, SIGNATURE) when signed, else (body, None). The signature is split
    off before truncation so that truncating a long body cannot silently send an
    UNSIGNED text - the one thing worse than a long text is an unsigned one."""
    if is_signed(body):
        lines = str(body).rstrip().splitlines()
        return "\n".join(lines[:-1]).rstrip("\n"), SIGNATURE
    return str(body or ""), None


def _truncate_at_sentence(text: str, floor: int = 40) -> str:
    """Cut at the last sentence end, else a line break, else a word boundary.
    Never mid-word unless there is no other choice."""
    t = (text or "").rstrip()
    if len(t) <= floor:
        return t
    for i in range(len(t) - 1, floor - 1, -1):
        if t[i] in ".!?":
            return t[: i + 1]
    j = t.rfind("\n")
    if j >= floor:
        return t[:j]
    k = t.rfind(" ")
    if k >= floor:
        return t[:k]
    return t


def fit_to_segments(body, *, soft: int = SOFT_LIMIT, hard: int = HARD_LIMIT) -> tuple:
    """`(fitted_body, detail)`. Over 6 segments (~930 chars) the body is cut at a
    sentence boundary and the cut is REPORTED - a truncated text that does not
    say it was truncated is a lie to whoever reads the log."""
    original = str(body or "")
    if len(original) <= soft:
        return original, ""
    head, sig = _split_signature(original)
    tail = ("\n" + sig) if sig else ""
    room = max(soft - len(tail), 40)
    fitted = (_truncate_at_sentence(head[:room]) + tail).strip()
    detail = (f"truncated {len(original)} -> {len(fitted)} chars at a sentence boundary "
              f"(the body was over {soft} chars / 6 SMS segments)")
    if len(fitted) > hard:
        room = max(hard - len(tail), 40)
        fitted = (_truncate_at_sentence(head[:room]) + tail).strip()
        detail = (f"truncated {len(original)} -> {len(fitted)} chars: over {soft} chars / 6 "
                  f"segments and over Twilio's hard cap of {hard}; cut at a sentence boundary")
    return fitted, detail


# --------------------------------------------------------------------------- #
# Transport (the only two places that touch the network, both injectable)
# --------------------------------------------------------------------------- #
def _twilio_post(cfg: dict, acct: str, tok: str, payload: dict, *, timeout: int = 60) -> dict:
    """One Twilio REST send. Same shape as `send-from-ai-line.py`."""
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Messages.json",
        data=data, method="POST")
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{acct}:{tok}".encode()).decode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _notify_post(url: str, message: str, *, timeout: int = 30) -> tuple:
    """POST one owner notification. Returns `(status, encoding, response_text)`.

    The contract says JSON `{"message": ...}`. The route that is actually
    deployed declares `message: str = Form(...)` (`app/main.py:17215`), which
    FastAPI serves from `application/x-www-form-urlencoded` - a JSON body gets a
    422 no matter how right the field name is. A 422 on a required field creates
    nothing, so BOTH encodings are tried, JSON first, and whichever the server
    accepted is returned and reported. Trying twice cannot notify twice; guessing
    once, wrongly, means the owner is never told.

    Raises on any failure that is not an encoding mismatch - a dead app is what
    the Twilio fallback is for.
    """
    attempts = []
    for encoding in ("json", "form"):
        if encoding == "json":
            data = json.dumps({"message": message}).encode()
            ctype = "application/json"
        else:
            data = urllib.parse.urlencode({"message": message}).encode()
            ctype = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = int(getattr(r, "status", 200) or 200)
                try:
                    body = r.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                return status, encoding, body[:600]
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            attempts.append(f"{encoding} -> HTTP {exc.code}: {body[:160]}")
            if exc.code in (415, 422):   # wrong encoding: nothing was created
                continue
            raise RuntimeError("; ".join(attempts)) from exc
    raise RuntimeError("the notify endpoint rejected every encoding: " + "; ".join(attempts))


def _blank(channel: str, dry_run: bool) -> dict:
    return {"ok": False, "sid": None, "error": None, "channel": channel,
            "dry_run": bool(dry_run), "detail": ""}


def _credentials(cfg: dict) -> tuple:
    return (_get(cfg, "TWILIO_ACCOUNT_SID"), _get(cfg, "TWILIO_AUTH_TOKEN"))


def _record_send(cfg: dict, sid: str, frm: str, to: str, body: str, status: str,
                 reason: str) -> dict:
    """The same `messages` INSERT shape `send-from-ai-line.py` uses, so a text
    that went out is in the store the sensor reads, with the SID that proves it."""
    ts = _now()
    path = _db_path(cfg)
    try:
        if store is not None:
            conn = store.connect(path)  # creates the dir, sets WAL + busy timeout
        else:  # pragma: no cover - only when textstore.py is absent
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=20)
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (sid, direction, from_number, to_number, body, date_sent, status,
                first_seen, app_has_it, state, decided_by, decided_at, reason)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, "outbound", frm, to, body, ts, status, ts, None, "answered",
             "textsend", ts, reason))
        conn.commit()
        conn.close()
        return {"ok": True, "error": None, "db": str(path)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "db": str(path)}


def sender_number(config=None) -> str:
    """The AI line. One definition, used by the gate's caller, the send and the log."""
    cfg = _config(config)
    return _e164(_get(cfg, "from_number", "TWILIO_PHONE_NUMBER") or AI_LINE_DEFAULT)


# --------------------------------------------------------------------------- #
# send
# --------------------------------------------------------------------------- #
def send(to, body, *, config=None, dry_run=True, direct_request=False,
         interrupt: bool = False,
         urgency: str = "normal", opens_turn: "bool | None" = None,
         declared_class: "str | None" = None,
         media_urls: "list[str] | None" = None,
         reason: "str | None" = None,
         class_hint: "str | None" = None) -> dict:
    """Send one text from the AI line, or refuse and say why.

    Order of business, and the order matters:

      1. the gate, re-checked here even though `can_send_to` is the caller's job;
      1b. THE OWNER'S CONVERSATION LEDGER, for a message to him: one unanswered QUESTION
          holds the channel, so a second question is refused rather than sent. A waiting
          message TAKES THE FLOOR when it outranks the open one
          (`may_supersede_open_turn`: money beats machinery, whatever each calls
          itself), when it is `critical`/`stuck`, or on `direct_request=True` for a
          message he asked for. `urgent` alone buys nothing -- that label is the
          sender's opinion of itself, and `urgent_email` is what happened when it
          could. A message that asks nothing never opens a turn in the first place.
      1c. THE OUTBOUND CLASSIFICATION GATE, for a body bound to an owner number: it must be
          a QUESTION, a RESULT or an ALERT (or the one acknowledgement, declared by
          `ack_filed_text` through `declared_class`). Everything else is refused with a
          named reason recorded in the store's own `send_attempt` ledger, and a genuine
          answer wrapped in noise is SALVAGED and sent without the noise. A DRY RUN reports
          the verdict instead of enforcing it -- see the gate's own section above.
      2. the signature (`- Daniel`, L1976), unless the recipient is the owner or
         `AITEXT_ALLOW_UNSIGNED=1`;
      3. the segment fit, reporting any truncation in `detail`;
      4. the dry run, which stops before any credential is even read;
      5. Twilio, then the store, then the SID, then the turn.

    `class_hint` is the class this module hands to the owner-text relay. `"reply"`
    (`REPLY_CLASS`) is the one that matters: the relay's FLOOR is a rule about
    UNSOLICITED traffic, and a message that ANSWERS something he just said is solicited,
    so a reply must not be held 20 minutes behind an unrelated reminder. It is derived
    from `direct_request=True` when the caller does not name one -- that flag already
    means "he asked for this message himself", which is the same fact -- and an explicit
    `class_hint` always wins.

    Never raises. Every failure - including "the network is unreachable" - is a
    returned dict, so a caller cannot mistake an exception for a successful send
    and cannot send twice by retrying one.
    """
    cfg = _config(config)
    res = _blank(CHANNEL_LINE, dry_run)
    relay_attempt_id = None        # the relay's attempt row for THIS send, if any
    relay_recorded = False         # has its outcome been written back yet?
    relay_ref_wire = _relay_ref(body)   # the ask token as the CALLER wrote it:
                                        # the gate below may strip it from the
                                        # body that actually goes out
    try:
        to_e164 = _e164(to)
        if not to_e164:
            res["error"] = "no recipient number"
            res["detail"] = "refused: nothing to send to"
            return res

        owner, how = _is_owner(to_e164, cfg)
        if not owner:
            allowed, why = can_send_to(to_e164, {"allow": _ledger_allow(to_e164, cfg)}, cfg)
            if not allowed:
                res["error"] = f"send gate closed: {why}"
                res["detail"] = "refused before any network call (the send gate overrides everything)"
                return res
        elif not direct_request:
            # THE ONE-AT-A-TIME RULE, on this side of the system too. See
            # `open_owner_turn` for why: this path used to be outside the ledger
            # the app enforces, so the app and this sender could each ask him a
            # question at the same moment.
            #
            # AND IT IS NOT A FLAT BAR. A waiting message may take the floor when it
            # OUTRANKS the open one -- see `may_supersede_open_turn` for the
            # measurement that made this a ranking rather than "anything that calls
            # itself urgent". Without the ranking the CFO could not ask at all while
            # the app's own email-triage notice held the turn.
            held = open_owner_turn(cfg)
            if held is not None:
                turn_reason = reason if reason is not None else infer_turn_reason(body)
                may, supersede_why = may_supersede_open_turn(
                    held, reason=turn_reason, urgency=urgency
                )
                if may:
                    res["superseded_turn"] = held["id"]
                    res["detail"] = (
                        (res.get("detail") or "")
                        + " | takes the floor from open turn #%s: %s"
                        % (held["id"], supersede_why)
                    )
                else:
                    res["error"] = (
                        "owner conversation open: he has not answered the message sent "
                        f"{held['age_hours']}h ago (turn #{held['id']}); one at a time"
                    )
                    res["detail"] = (
                        "refused before any network call. This is the owner's own rule - one "
                        "text at a time until he answers - and it is why this refusal exists "
                        "rather than a silent second question. A message he ASKED for passes "
                        "direct_request=True, and a message that outranks the open one passes "
                        "on rank (app/owner_text.owner_text_priority)."
                    )
                    return res

        # ── THE OUTBOUND CLASSIFICATION GATE, for a body bound to him ────────
        # After the one-at-a-time ledger (a held turn is a different refusal) and before
        # the signature and the segment fit, so a body that is not worth his time is never
        # fitted, never signed, and never counted as an attempt to deliver. The verdict is
        # reported in `gate` on every owner-bound send, accepted or not: a gate whose
        # decisions are invisible is a gate nobody can trust.
        gate = None
        if owner:
            gate = classify_owner_body(
                body, declared_class=declared_class,
                ceiling=(flood.owner_text_ceiling(cfg) if flood is not None
                         else APP_OWNER_TEXT_CEILING))
            res["gate"] = {"cls": gate["cls"], "code": gate["code"]}
            if gate["refused"]:
                res["gate_refusal"] = {"code": gate["code"], "reason": gate["reason"]}
                if gate.get("send_body") and noise_salvage_enabled(cfg):
                    # Rule 1: a genuine RESULT must still reach him. The wrapper is refused
                    # and RECORDED; the answer inside it is what goes out.
                    res["salvaged_from"] = gate["code"]
                    res["salvaged_body"] = gate["send_body"]
                    res["gate"]["salvaged"] = True
                    _record_gate_refusal(cfg, to_e164, body, gate)
                    body = gate["send_body"]
                elif dry_run:
                    # A DRY RUN REPORTS; IT DOES NOT ENFORCE. See the gate's section: the
                    # caller is asking "what would happen", and the answer is in
                    # `gate_refusal` -- told, not hidden, and not turned into a second rule.
                    pass
                else:
                    res["error"] = gate_refusal_text(gate)
                    res["detail"] = (
                        "refused before any network call, by the outbound classification "
                        "gate. Every body bound for his phone must be a QUESTION, a RESULT "
                        "or an ALERT (or the one acknowledgement he asked for, declared by "
                        "ack_filed_text through declared_class). The refusal is recorded in "
                        "the store's own send_attempt ledger under this code, and returned "
                        "to the caller so it can rewrite the message: a refusal is not "
                        "silence, it is the answer not being ready to send yet.")
                    res["refused_attempts"] = _record_gate_refusal(cfg, to_e164, body, gate)
                    return res
            elif gate.get("send_body") and gate["send_body"] != body:
                # Accepted, but a machine artifact came off the front of it (the `[qNNN]`
                # reference a queue row is stored under). It is our bookkeeping, not part
                # of the question, so the body that goes is the one without it.
                res["gate"]["trimmed"] = True
                body = gate["send_body"]

        unsigned_ok = owner or _truthy(_get(cfg, "allow_unsigned", "AITEXT_ALLOW_UNSIGNED"))
        if not is_signed(body) and not unsigned_ok:
            res["error"] = ("unsigned: the body does not end with a line reading exactly "
                            f"'{SIGNATURE}'")
            res["detail"] = ("refused before any network call - owner's standing rule "
                             "(journal L1976). Set AITEXT_ALLOW_UNSIGNED=1 only for a "
                             "recipient that is not a person.")
            return res

        fitted, trunc_detail = fit_to_segments(body)
        if is_signed(body) and not is_signed(fitted):
            # Cannot happen through fit_to_segments, and it must never happen at
            # all: an unsigned text leaving this line is the whole of B9.
            fitted = fitted.rstrip() + "\n" + SIGNATURE
            trunc_detail = (trunc_detail + " | signature re-appended after truncation").strip(" |")

        # ── THE FLOOD BRAKE, before anything leaves ────────────────────────
        # Owner-bound only: this brake exists because his phone is the one endpoint a
        # retry loop can flood without anybody noticing (911 `suppressed` rows on
        # 2026-10-01, zero of them delivered, the instrument still reading OK).
        # ── THE OWNER'S RATE FLOOR ──────────────────────────────────────────
        # His words, 2026-10-09: "text me, let's say once every 20 minutes at most."
        # Checked BEFORE the turn ledger and before the POST, so no producer on the
        # cron -- cfo-ask (*/30), owner-ask (5,35), the attention digest (:30) -- can
        # put two texts on his phone inside the window. `interrupt` is the caller's
        # own deliberate declaration for a person or property in danger and is the one
        # thing that outranks it; a mere `urgent` label does not, because that is a
        # sender's opinion of itself and it is what this module exists to stop.
        if owner and not interrupt:
            _floor_refused, _floor_detail = rate_floor_verdict(cfg)
            if _floor_refused:
                res["error"] = "rate_floor"
                res["detail"] = _floor_detail
                res["code"] = "rate_floor"
                _flood_note(cfg, to_e164, body, "refused", code="rate_floor",
                            detail=_floor_detail[:200])
                return res

        if owner:
            if _flood_verdict(cfg, to_e164, body, res) is not None:
                return res

        frm = sender_number(cfg)
        if dry_run:
            res["ok"] = True
            res["detail"] = (f"DRY RUN - nothing sent. would send {len(fitted)} chars from "
                             f"{frm} to {to_e164}. " + trunc_detail).strip()
            if gate is not None and gate.get("salvaged"):
                res["detail"] += (" | SALVAGED: the body as handed in was refused (%s) and "
                                  "the answer found inside it is what would go out"
                                  % str(res.get("salvaged_from") or gate["code"]))
            elif gate is not None and gate.get("refused"):
                res["detail"] += (" | THE GATE WOULD REFUSE THIS (%s): %s -- a real send is "
                                  "refused and recorded; the dry run only reports it"
                                  % (gate["code"], gate["reason"]))
            return res

        acct, tok = _credentials(cfg)
        if not acct or not tok:
            res["error"] = "no Twilio credentials (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)"
            res["detail"] = f"looked in {DEFAULT_ENV_FILE} and in the environment"
            if owner:
                _flood_note(cfg, to_e164, body, "refused", code="no_credentials",
                            detail=res["error"])
            return res

        # ── THE OWNER-TEXT RELAY, the last policy layer before his phone ─────
        # Consulted EXACTLY ONCE per real send, and only here. It sits below the
        # dry-run return above (a dry run must not write an attempt row, and must not
        # wake the relay at all), and below every refusal that already existed, so the
        # gate, the 20-minute floor and the turn ledger are unchanged and a refusal by
        # any of them is still that refusal. `owner` keeps it on the owner's channel,
        # which is the only channel the relay knows about - its interface has no
        # recipient. On anything but SEND this returns this module's own refusal shape
        # with ok=False, the verdict in `error` and exit 1, and transmits nothing.
        #
        # THE REPLY MARKER. An explicit `class_hint` wins; otherwise the existing
        # `direct_request=True` marker -- this module's own flag for "a message he asked
        # for" -- is reported to the relay as REPLY_CLASS, so a solicited answer is not
        # held by the relay's FLOOR. See `send()`'s docstring and the relay's REPLY_CLASS.
        if owner:
            # THE RELAY JUDGES THE BYTES THAT WILL BE POSTED. It used to be handed the
            # raw `body` while `_payload` below carried `fitted` (up to ~930 chars from
            # `fit_to_segments`), so the relay recorded one text and the phone received
            # another. `_relay_gate` now applies the owner ceiling itself and returns
            # the bytes to send; `fitted` becomes exactly that.
            relay_attempt_id, _relay_refused, fitted = _relay_gate(
                res, fitted, reason=reason, urgency=urgency, ref=relay_ref_wire,
                class_hint=(class_hint or (REPLY_CLASS if direct_request else None)))
            # The gate may have shortened `fitted` to the ceiling. An unsigned text
            # leaving this line is the whole of B9, so re-assert the signature LAST.
            if is_signed(body) and not is_signed(fitted):
                fitted = fitted.rstrip() + "\n" + SIGNATURE
                trunc_detail = (trunc_detail + " | signature re-appended after the "
                                "owner-ceiling fit").strip(" |")
            if _relay_refused is not None:
                return _relay_refused

        _payload = {"From": frm, "To": to_e164, "Body": fitted}
        for _i, _u in enumerate(media_urls or []):
            _payload[f"MediaUrl{_i}"] = str(_u)
        raw = _twilio_post(cfg, acct, tok, _payload)
        sid = str((raw or {}).get("sid") or "") or None
        if not sid:
            if relay_attempt_id is not None and not relay_recorded:
                _relay_record_failed(relay_attempt_id,
                                     error="Twilio accepted the request but returned no sid")
                relay_recorded = True
            res["error"] = "Twilio accepted the request but returned no sid"
            res["detail"] = json.dumps(raw)[:300] if raw else "empty response"
            return res
        status = str((raw or {}).get("status") or "")
        res["ok"] = True
        res["sid"] = sid
        res["detail"] = (f"sent from {frm} to {to_e164}; twilio status={status or '?'}"
                         + (f"; {trunc_detail}" if trunc_detail else ""))
        if relay_attempt_id is not None:
            relay_recorded = _relay_record_sent(relay_attempt_id, sid=str(sid or ""),
                                                status=status or "sent", body=body)
        rec = _record_send(cfg, sid, frm, to_e164, fitted, status,
                           str(_get(cfg, "reason", default="sent from the AI line by textsend")))
        if not rec["ok"]:
            res["detail"] += f" | NOT recorded in the store: {rec['error']}"
        if owner:
            asks = bool(_QUESTION_RE.search(fitted)) if opens_turn is None else bool(opens_turn)
            res["opened_turn"] = asks
            if not asks:
                # An acknowledgement is not a question and must not hold the channel.
                res["detail"] += (" | no turn opened: the body asks nothing "
                                  "(no question mark), so the one-at-a-time rule does not apply")
            else:
                # Open the turn the app's gate reads. If this fails the app will not know a
                # question is outstanding, so it is reported in `detail` rather than swallowed:
                # a ledger write whose effect is never checked is not a ledger.
                opened = record_owner_turn(
                    cfg, fitted, reason=str(_get(cfg, "reason", default="aitext-responder")),
                    sid=str(sid or ""),
                )
                res["turn_opened"] = opened
                if not opened:
                    res["detail"] += (
                        " | WARNING: the owner conversation turn was NOT recorded, so the app "
                        "cannot see this question and may send him another"
                    )
            # The attempt is recorded AFTER it happened, so a delivery is never counted as
            # an attempt-that-was-refused; the brake trips on repeated failures, not on
            # repeated successes.
            _flood_note(cfg, to_e164, body, "sent", code=status or "sent",
                        detail=trunc_detail or res["detail"][:200])
        return res
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["detail"] = "the send failed and is reported as a value, not raised"
        if relay_attempt_id is not None and not relay_recorded:
            _relay_record_failed(relay_attempt_id, error=res["error"])
            relay_recorded = True
        return res


# --------------------------------------------------------------------------- #
# ack_filed_text - the ONE acknowledgement he asked for
# --------------------------------------------------------------------------- #
ACK_ENV = "AITEXT_ACK_OWNER_REQUESTS"
ACK_MARKER = "ack-filed"


def ack_owner_requests_enabled() -> bool:
    """Is the acknowledgement on? `AITEXT_ACK_OWNER_REQUESTS=0/no/off/false` turns it off.

    ON by default, and that default is a decision with a date on it. Owner, 2026-09-30
    16:12Z, after his own text was filed as work and he heard nothing back:

        "Did you get my text? Why don't you like confirm so I know you got it or
         something?"

    That is the latest word on the subject and it reverses 2026-09-28, when he called
    receipts pointless -- which is why the S4 brief still forbids the BRAIN sending one
    (`test-owner-guard.py` checks that line, and it is right: the brain's one message is
    the answer, not a receipt). What he asked for is narrower than a receipt: ONE line,
    immediately, and only when his text has been filed as work that will take a while.
    """
    raw = str(os.environ.get(ACK_ENV, "1")).strip().lower()
    return raw not in ("0", "no", "off", "false")


def _already_acked(cfg: dict, sid: str) -> bool:
    """Has this exact inbound text already been acknowledged? Read-only; False on doubt.

    The marker lives in the store's own `reason` column, so "exactly one" is a property
    of the record rather than of whichever code path happened to run: the same text
    processed twice (a retried cron tick, a replayed row) cannot produce a second text.
    """
    if not sid:
        return False
    conn = _ro_connect(_db_path(cfg))
    if conn is None:
        return False
    try:
        return bool(conn.execute(
            "SELECT 1 FROM messages WHERE direction='outbound' AND reason=? LIMIT 1",
            ("%s:%s" % (ACK_MARKER, sid),)).fetchone())
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def ack_filed_text(phone: str, filed: dict, body: str = "", *, sid: str = "",
                   config=None, dry_run: bool = True, send=None) -> dict:
    """Send ONE short acknowledgement that his text has been filed as work.

    THREE PROPERTIES, each one a thing he or the system already paid for:

      * EXACTLY ONE. Deduped on the inbound `sid` through the store, so a text he sent
        once is acknowledged once, however many times the row is worked. `send()` also
        records the outbound, so the ack is visible in his own thread (`text-health.py`
        I1) like any other message.
      * IT OPENS NO TURN. `opens_turn=False` -- an acknowledgement is not a question, and
        if it opened an unanswered `owner_text_turn` the REAL answer would be blocked
        behind it by the one-at-a-time gate (`textsend.open_owner_turn`), which is the
        exact shape of the bug this whole channel keeps re-learning.
      * IT DOES NOT STAND IN FOR THE ANSWER. It is sent only where the work has been
        filed and the answer is still coming; a text this system answers directly stays a
        single reply, and nothing here is called on that path.
      * IT IS THE ONE RECEIPT THAT IS ALLOWED, AND IT IS DECLARED. The outbound
        classification gate refuses an acknowledgement-shaped body from every other caller
        -- "Got it - filed as housekeeping#392." is a receipt, not a message, and he has
        twice called them pointless. This function is the single exception, and it is
        DECLARED, not detected: `declared_class=CLASS_ACK` says out loud which class it is
        claiming, and the gate re-checks the shape (one sentence, asks nothing, within the
        ceiling) before admitting it. If the owner ever turns the acknowledgement off
        (`AITEXT_ACK_OWNER_REQUESTS=0`), nothing changes about the gate: the default answer
        for a receipt from any other caller is still to refuse it.

    Never raises: it returns a dict, and a failure to acknowledge is reported rather than
    swallowed. Callers pass `dry_run` through -- the ack obeys the same switch as every
    other send on this line.
    """
    filed = filed or {}
    res = _blank(CHANNEL_OWNER, dry_run)
    res["channel"] = "ack"
    try:
        cfg = _config(config)
        if not ack_owner_requests_enabled():
            res["skipped"] = "%s is off" % ACK_ENV
            return res
        to_e164 = _e164(phone)
        if not to_e164:
            res["error"] = "no phone number to acknowledge to"
            return res
        if _already_acked(cfg, sid):
            res["skipped"] = "this text (sid %s) has already been acknowledged" % sid
            return res
        project, item = str(filed.get("project") or "work"), filed.get("id")
        if filed.get("already"):
            text = "Already on it (%s#%s)." % (project, item)
        elif item not in (None, ""):
            text = "Got it - filed as %s#%s." % (project, item)
        else:
            text = "Got it - I have it and I am on it."
        # `?` is deliberate in the assertion below rather than in the wording: the body
        # asks nothing, and `opens_turn=False` says so out loud rather than relying on a
        # punctuation test to keep the channel open.
        ack_cfg = dict(cfg)
        ack_cfg["reason"] = "%s:%s" % (ACK_MARKER, sid or "no-sid")
        caller = send or globals().get("send")
        try:
            res = caller(to_e164, text, config=ack_cfg, dry_run=dry_run, opens_turn=False,
                         declared_class=CLASS_ACK)
        except TypeError as exc:
            # An injected or older sender without the keyword. The ack still goes, and the
            # fact that its class was NOT declared is reported rather than assumed away:
            # an undeclared acknowledgement is exactly the noise the classification gate
            # refuses, so a silent fallback here would look like the gate working.
            if "declared_class" not in str(exc):
                raise
            res = caller(to_e164, text, config=ack_cfg, dry_run=dry_run, opens_turn=False)
            res["detail"] = (str(res.get("detail") or "")
                             + " | NOTE: the sender has no declared_class parameter, so this "
                               "acknowledgement went out undeclared (it was not classified "
                               "at the outbound gate)").strip()
        res["channel"] = "ack"
        res["ack_body"] = text
        res["ack_sid_of_his_text"] = sid
        return res
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["detail"] = "the acknowledgement failed and is reported as a value, not raised"
        return res


# --------------------------------------------------------------------------- #
# notify_owner - NOT an SMS
# --------------------------------------------------------------------------- #
def notify_owner(body, *, config=None, dry_run=True) -> dict:
    """Tell the owner something. Through the app's own queue, NOT by texting him.

    `POST {SECRETARY_API_BASE}/tools/notify-owner` with `{"message": ...}` - see
    `_notify_post`, because the route that is actually deployed is form-encoded
    and the encoding that worked is named in `detail`. There is a live kill
    switch (`OWNER_SMS_KILL_SWITCH`, created 2026-07-14 after the CEO sent 28+
    "URGENT" texts); while that file exists the app itself holds any owner SMS
    (`send_owner_update` enqueues it with status `held`), and this module refuses
    the Twilio fallback rather than cheerfully attempting it. The path actually
    used is always reported in `detail`.

    Never raises.

    TWO THINGS THIS PATH OWED THE OWNER, both measured on 2026-10-01:

      * A body longer than the app's one-text ceiling was POSTed whole, the app's gate
        refused it with `too_long`, and the app answered HTTP 200 with
        `{"ok": true, "suppressed": true, "held": true}` -- which this function reported
        as "delivered to the owner's notification queue". 911 rows were written to
        `sms_log` that day with `status='suppressed'` and no `twilio_sid`. A body that
        does not fit is now FITTED here (`fit_owner_body`), so length is never the reason
        the owner is not told, and the app's own verdict is read instead of its HTTP
        status, so "it is sitting in a queue" is never reported as "he was told".
      * Nothing counted repeated identical attempts, so the same 811-character reminder
        was re-fired every ~60 s for seven hours. The flood brake now sees them.
    """
    cfg = _config(config)
    res = _blank(CHANNEL_OWNER, dry_run)
    try:
        text = str(body or "")
        url = _notify_url(cfg)
        if not text.strip():
            res["error"] = "empty body"
            res["detail"] = "refused: nothing to tell the owner"
            return res

        owner = _get(cfg, "owner_phone", "OWNER_PHONE_NUMBER")
        if not owner:
            owners = owner_numbers(cfg)
            owner = owners[0] if owners else None

        # ── THE OUTBOUND CLASSIFICATION GATE ────────────────────────────────
        # The same gate `send()` enforces, in the same order (before the fit, before the
        # POST, before the Twilio fallback): this path is the OTHER way a body reaches
        # his phone, and a rule enforced on one of two paths is not a rule. A DRY RUN
        # reports the verdict instead of enforcing it, exactly as `send()` does.
        gate = None
        if owner:
            gate = classify_owner_body(
                text, ceiling=(flood.owner_text_ceiling(cfg) if flood is not None
                               else APP_OWNER_TEXT_CEILING))
            res["gate"] = {"cls": gate["cls"], "code": gate["code"]}
            if gate["refused"]:
                res["gate_refusal"] = {"code": gate["code"], "reason": gate["reason"]}
                if gate.get("send_body") and noise_salvage_enabled(cfg):
                    res["salvaged_from"] = gate["code"]
                    res["salvaged_body"] = gate["send_body"]
                    res["gate"]["salvaged"] = True
                    _record_gate_refusal(cfg, _e164(owner), text, gate)
                    text = gate["send_body"]
                elif dry_run:
                    pass                      # report, do not enforce -- see `send()`
                else:
                    res["error"] = gate_refusal_text(gate)
                    res["detail"] = (
                        "refused before any POST and before any network call, by the "
                        "outbound classification gate. Everything that reaches his phone "
                        "must be a QUESTION, a RESULT or an ALERT: an acknowledgement, a "
                        "promise to look into it, a probe, an internal machine instruction "
                        "or a bare queue reference is not a message. The refusal is "
                        "recorded in the store's own send_attempt ledger under this code.")
                    res["refused_attempts"] = _record_gate_refusal(cfg, _e164(owner), text, gate)
                    return res
            elif gate.get("send_body") and gate["send_body"] != text:
                # Accepted, with a machine artifact removed from the front of it. See the
                # same branch in `send()`.
                res["gate"]["trimmed"] = True
                text = gate["send_body"]

        # Fit BEFORE the POST: the app's gate judges 320 characters by default, and a
        # body over it is held, not sent. Fitting is what makes the difference between
        # "he was told" and "it is in a queue with a refusal in its history".
        posted, fit_detail = fit_owner_body(text, cfg=cfg)
        if fit_detail:
            res["fitted_chars"] = len(posted)
            res["original_chars"] = len(text)

        if dry_run:
            res["ok"] = True
            res["detail"] = (f"DRY RUN - nothing sent. would POST "
                             f"{{\"message\": <{len(posted)} chars>}} to {url}"
                             + (f"; {fit_detail}" if fit_detail else ""))
            if gate is not None and gate.get("salvaged"):
                res["detail"] += (" | SALVAGED: the body as handed in was refused (%s) and "
                                  "the answer found inside it is what would go out"
                                  % str(res.get("salvaged_from") or gate["code"]))
            elif gate is not None and gate.get("refused"):
                res["detail"] += (" | THE GATE WOULD REFUSE THIS (%s): %s -- a real notify "
                                  "is refused and recorded; the dry run only reports it"
                                  % (gate["code"], gate["reason"]))
            return res

        if owner and _flood_verdict(cfg, _e164(owner), text, res) is not None:
            return res

        try:
            status, encoding, answer = _notify_post(url, posted)
            reached, why = _app_notify_verdict(answer)
            if reached:
                res["ok"] = True
                res["detail"] = (f"delivered to the owner's notification queue: POST {url} "
                                 f"(HTTP {status}, {encoding}-encoded"
                                 + (f", app said {answer.strip()[:200]}" if answer.strip() else "")
                                 + "). No SMS involved."
                                 + (f"; {fit_detail}" if fit_detail else ""))
                if owner:
                    _flood_note(cfg, _e164(owner), text, "sent", code="notify-queue",
                                detail=fit_detail)
                return res
            # The app took the message and HELD it. That is not a delivery, and reporting
            # it as one is how 911 rows became invisible.
            res["ok"] = False
            res["suppressed"] = True
            res["error"] = f"held by the app ({why}); nothing reached him"
            res["detail"] = (
                f"POST {url} answered HTTP {status} but the app's own answer says it "
                f"SUPPRESSED the message (reason={why}); it is in the app's owner queue, "
                f"not on his phone. app said {answer.strip()[:200]}"
                + (f"; {fit_detail}" if fit_detail else ""))
            if owner:
                _flood_note(cfg, _e164(owner), text, "suppressed", code=str(why),
                            detail=res["detail"][:300])
            return res
        except Exception as exc:
            app_error = f"{type(exc).__name__}: {exc}"
            if "HTTP 422" in app_error or "rejected every encoding" in app_error:
                app_error += " (the endpoint may have changed shape - see _notify_post)"

        ks = _kill_switch(cfg)
        if ks.exists():
            res["error"] = f"owner notify failed: {app_error}"
            res["detail"] = (f"POST {url} failed ({app_error}); the owner-SMS fallback is "
                             f"BLOCKED by the kill switch at {ks} - nothing was sent.")
            return res

        if not owner:
            res["error"] = f"owner notify failed: {app_error}"
            res["detail"] = ("and no owner number is known (OWNER_PHONE_NUMBER / permissions), "
                             "so there was nobody to fall back to - nothing was sent.")
            return res

        acct, tok = _credentials(cfg)
        if not acct or not tok:
            res["error"] = f"owner notify failed: {app_error}"
            res["detail"] = "and there are no Twilio credentials for the fallback - nothing sent"
            return res

        # The owner is exempt from the `- Daniel` signature rule (it exists to
        # stop a customer reading a scratch pad, not to stop us reaching him),
        # but not from Twilio's segment limits.
        fitted, trunc_detail = fit_to_segments(text)
        frm = sender_number(cfg)
        to_owner = _e164(owner)

        # ── THE FALLBACK OBEYS THE OWNER'S OWN RULES (2026-10-13) ──────────────
        # This is the ONE path on this channel that reached his phone without
        # passing the ledger, and it is reached exactly when the app endpoint is
        # down - i.e. when nothing else is watching. Measured 2026-10-13: the app
        # path was gated and this one was not, so a broken endpoint was a way
        # around the one-at-a-time rule. Same rule here, applied rather than
        # bypassed: if he has not answered, we do not speak again.
        _held = open_owner_turn(cfg)
        if _held is not None:
            _may, _why = may_supersede_open_turn(
                _held, reason=infer_turn_reason(text), urgency="normal")
            if not _may:
                res["error"] = (
                    "owner notify failed and the Twilio fallback is blocked by the "
                    "owner's one-at-a-time rule: he has not answered the message sent "
                    "%sh ago (turn #%s); one text at a time"
                    % (_held.get("age_hours"), _held.get("id")))
                res["detail"] = (
                    "refused BEFORE any network call. The app endpoint is the normal "
                    "gate and it is down; the fallback applies the same owner rules "
                    "instead of bypassing them. (%s)" % _why)
                res["code"] = "turn_grace"
                return res

        _floor_refused, _floor_detail = rate_floor_verdict(cfg)
        if _floor_refused:
            res["error"] = ("owner notify failed and the Twilio fallback is inside the "
                            "owner's rate floor")
            res["detail"] = str(_floor_detail or "")
            res["code"] = "rate_floor"
            return res

        raw = _twilio_post(cfg, acct, tok, {"From": frm, "To": to_owner, "Body": fitted})
        sid = str((raw or {}).get("sid") or "") or None
        res["sid"] = sid
        res["ok"] = bool(sid)
        if not sid:
            res["error"] = "owner notify failed and the SMS fallback returned no sid"
        res["detail"] = (f"the app endpoint failed ({app_error}); fell back to Twilio SMS to "
                         f"the owner {to_owner} (kill switch {ks} absent)"
                         + (f"; {trunc_detail}" if trunc_detail else ""))
        if sid:
            _record_send(cfg, sid, frm, to_owner, fitted, str((raw or {}).get("status") or ""),
                         "owner notification fallback")
        _flood_note(cfg, to_owner, text, "sent" if sid else "failed",
                    code="notify-fallback",
                    detail=trunc_detail or str(res.get("error") or "")[:200])
        return res
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["detail"] = "notify_owner failed and is reported as a value, not raised"
        return res


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #
def history(db_path=None, limit: int = 20) -> list:
    """The last `limit` outbound texts this system sent, newest first. Empty list
    when the store or the table is absent - an absent store is a fresh store, not
    an error, and a reader that raises on a fresh store is a reader nobody runs."""
    path = Path(db_path) if db_path else _db_path(_config(None))
    conn = _ro_connect(path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE direction='outbound' "
            "ORDER BY date_sent DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CLI - an operator's hand, and the live proof's driver
# --------------------------------------------------------------------------- #
def _body_from(args) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8").strip()
    return args.body or ""


def cmd_check(args) -> int:
    ctx = {"allow": args.allow, "phone": args.to}
    ok, why = can_send_to(args.to, ctx, None)
    print(f"to      {args.to}")
    print(f"owner?  {owner_numbers() or '(none configured)'}")
    print(f"ledger  allow={_ledger_allow(args.to, _config(None))}")
    print(f"gate    {'OPEN' if ok else 'CLOSED'} - {why}")
    print(f"from    {sender_number()}")
    print(f"third-party env: AITEXT_ALLOW_THIRD_PARTY_SENDS="
          f"{os.environ.get('AITEXT_ALLOW_THIRD_PARTY_SENDS') or '(unset -> closed)'}")
    # `--body` is optional and read-only: it shows what the OUTBOUND CLASSIFICATION GATE
    # would say about this exact body before anybody sends it. Nothing is sent, nothing is
    # recorded -- a check must be safe to run on a live message.
    body = ""
    if getattr(args, "body", None) or getattr(args, "body_file", None):
        body = _body_from(args)
    if body:
        own, _how = _is_owner(_e164(args.to), _config(None))
        if not own:
            print(f"class   (not an owner number: the classification gate does not apply)")
        else:
            verdict = classify_owner_body(
                body, ceiling=(flood.owner_text_ceiling(None) if flood is not None
                               else APP_OWNER_TEXT_CEILING))
            print(f"class   {verdict['cls']}  {verdict['code']}")
            print(f"gate    {'REFUSED' if verdict['refused'] else 'ACCEPTED'} - "
                  f"{verdict['reason']}")
            if verdict.get("salvaged"):
                print(f"salvage {verdict['salvaged']!r}")
    return 0


def cmd_send(args) -> int:
    body = _body_from(args)
    res = send(args.to, body, dry_run=not args.send,
               reason=getattr(args, "reason", None),
               urgency=getattr(args, "urgency", "normal") or "normal")
    _print_result(res)
    return 0 if res.get("ok") else 1


def cmd_notify(args) -> int:
    res = notify_owner(_body_from(args), dry_run=not args.send)
    _print_result(res)
    return 0 if res.get("ok") else 1


def cmd_history(args) -> int:
    rows = history(args.db, args.limit)
    print(f"{len(rows)} outbound message(s)")
    for r in rows:
        print("  %-20s %-16s %-9s %s"
              % (r.get("date_sent"), r.get("to_number"), r.get("status") or "-",
                 (r.get("body") or "")[:70]))
    return 0


def cmd_sender(args) -> int:
    print(sender_number())
    return 0


def cmd_doctor(args) -> int:
    """`doctor` -- one command that answers "which database is this sender reading?"."""
    return _doctor_report(getattr(args, "db", None),
                          min_turns=int(getattr(args, "min_turns", DOCTOR_MIN_TURNS)))


def _print_result(res: dict) -> None:
    print(f"ok={res.get('ok')}  channel={res.get('channel')}  dry_run={res.get('dry_run')}"
          f"  sid={res.get('sid')}")
    if res.get("error"):
        print(f"error: {res['error']}")
    if res.get("detail"):
        print(f"detail: {res['detail']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--doctor", action="store_true",
                   help="alias for the `doctor` subcommand: which store am I reading?")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("check", help="ask the gate about a number, send nothing")
    s.add_argument("--to", required=True)
    s.add_argument("--allow", default="queue", choices=["auto", "queue", "never"])
    s.add_argument("--body", default=None,
                   help="also show what the outbound classification gate says about this body")
    s.add_argument("--body-file", default=None,
                   help="same, from a file (nothing is sent and nothing is recorded)")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("send", help="send one text (default: dry run)")
    s.add_argument("--to", required=True)
    s.add_argument("--body-file")
    s.add_argument("--body")
    s.add_argument("--send", action="store_true", help="actually send (default is dry-run)")
    # Naming the reason is how a caller claims a rank on the owner's channel
    # (app/owner_text.owner_text_priority). It is optional because it can be
    # derived from the body, but an asker that knows it is asking about money
    # should say so rather than rely on the body's shape.
    s.add_argument("--reason", default=None,
                   help="why this message exists, e.g. cfo_ask, reminder, urgent_email "
                        "(default: inferred from the body)")
    s.add_argument("--urgency", default="normal",
                   choices=["normal", "high", "urgent", "critical", "stuck"],
                   help="the sender's own opinion of its message; it separates "
                        "messages within a rank and never crosses one")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("notify", help="tell the owner (default: dry run)")
    s.add_argument("--body-file")
    s.add_argument("--body")
    s.add_argument("--send", action="store_true", help="actually notify (default is dry-run)")
    s.set_defaults(func=cmd_notify)

    s = sub.add_parser("history")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--db", default=None)
    s.set_defaults(func=cmd_history)

    sub.add_parser("sender").set_defaults(func=cmd_sender)

    # ONE COMMAND, NO ARGUMENTS: which store is this sender about to read, and is it the
    # one the live app writes? Read-only, so it is safe on the production box.
    s = sub.add_parser("doctor",
                       help="does this sender read the store the live app writes? "
                            "reports both paths and both row counts; reads only")
    s.add_argument("--db", default=None,
                   help="check THIS store instead of the resolved one (read-only)")
    s.add_argument("--min-turns", type=int, default=DOCTOR_MIN_TURNS,
                   help=f"minimum acceptable owner_text_turn rows (default {DOCTOR_MIN_TURNS})")
    s.set_defaults(func=cmd_doctor)

    args = p.parse_args()
    if getattr(args, "doctor", False):
        args = p.parse_args(["doctor"])
    if not getattr(args, "func", None):
        args = p.parse_args(["check", "--to", AI_LINE_DEFAULT])
    return args.func(args)


#: Import-time divergence check, OFF BY DEFAULT. Sixteen operator scripts import this
#: module; a resolution probe must never be able to kill one of them, so the switch is
#: explicit. With it on, an import that cannot see the same store the app writes stops
#: LOUDLY instead of quietly reading the wrong one -- which is precisely the defect that
#: put an empty 1.8 MB copy in front of the owner's own text channel on 2026-10-13.
def _assert_app_db_is_the_apps_db() -> None:
    if str(os.environ.get("AITEXT_APP_DB_ASSERT") or "").strip().lower() not in (
            "1", "true", "yes", "on"):
        return
    report = doctor()
    if not report["ok"]:
        raise RuntimeError("textsend/app database divergence: " + report["detail"])


_assert_app_db_is_the_apps_db()


if __name__ == "__main__":
    sys.exit(main())
