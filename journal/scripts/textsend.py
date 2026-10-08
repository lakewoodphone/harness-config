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
from datetime import datetime, timezone
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
def send(to, body, *, config=None, dry_run=True) -> dict:
    """Send one text from the AI line, or refuse and say why.

    Order of business, and the order matters:

      1. the gate, re-checked here even though `can_send_to` is the caller's job;
      2. the signature (`- Daniel`, L1976), unless the recipient is the owner or
         `AITEXT_ALLOW_UNSIGNED=1`;
      3. the segment fit, reporting any truncation in `detail`;
      4. the dry run, which stops before any credential is even read;
      5. Twilio, then the store, then the SID.

    Never raises. Every failure - including "the network is unreachable" - is a
    returned dict, so a caller cannot mistake an exception for a successful send
    and cannot send twice by retrying one.
    """
    cfg = _config(config)
    res = _blank(CHANNEL_LINE, dry_run)
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

        frm = sender_number(cfg)
        if dry_run:
            res["ok"] = True
            res["detail"] = (f"DRY RUN - nothing sent. would send {len(fitted)} chars from "
                             f"{frm} to {to_e164}. " + trunc_detail).strip()
            return res

        acct, tok = _credentials(cfg)
        if not acct or not tok:
            res["error"] = "no Twilio credentials (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)"
            res["detail"] = f"looked in {DEFAULT_ENV_FILE} and in the environment"
            return res

        raw = _twilio_post(cfg, acct, tok, {"From": frm, "To": to_e164, "Body": fitted})
        sid = str((raw or {}).get("sid") or "") or None
        if not sid:
            res["error"] = "Twilio accepted the request but returned no sid"
            res["detail"] = json.dumps(raw)[:300] if raw else "empty response"
            return res
        status = str((raw or {}).get("status") or "")
        res["ok"] = True
        res["sid"] = sid
        res["detail"] = (f"sent from {frm} to {to_e164}; twilio status={status or '?'}"
                         + (f"; {trunc_detail}" if trunc_detail else ""))
        rec = _record_send(cfg, sid, frm, to_e164, fitted, status,
                           str(_get(cfg, "reason", default="sent from the AI line by textsend")))
        if not rec["ok"]:
            res["detail"] += f" | NOT recorded in the store: {rec['error']}"
        return res
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["detail"] = "the send failed and is reported as a value, not raised"
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

        if dry_run:
            res["ok"] = True
            res["detail"] = (f"DRY RUN - nothing sent. would POST "
                             f"{{\"message\": <{len(text)} chars>}} to {url}")
            return res

        try:
            status, encoding, answer = _notify_post(url, text)
            res["ok"] = True
            res["detail"] = (f"delivered to the owner's notification queue: POST {url} "
                             f"(HTTP {status}, {encoding}-encoded"
                             + (f", app said {answer.strip()[:200]}" if answer.strip() else "")
                             + "). No SMS involved.")
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

        owner = _get(cfg, "owner_phone", "OWNER_PHONE_NUMBER")
        if not owner:
            owners = owner_numbers(cfg)
            owner = owners[0] if owners else None
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
    return 0


def cmd_send(args) -> int:
    body = _body_from(args)
    res = send(args.to, body, dry_run=not args.send)
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
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("check", help="ask the gate about a number, send nothing")
    s.add_argument("--to", required=True)
    s.add_argument("--allow", default="queue", choices=["auto", "queue", "never"])
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("send", help="send one text (default: dry run)")
    s.add_argument("--to", required=True)
    s.add_argument("--body-file")
    s.add_argument("--body")
    s.add_argument("--send", action="store_true", help="actually send (default is dry-run)")
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

    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["check", "--to", AI_LINE_DEFAULT])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
